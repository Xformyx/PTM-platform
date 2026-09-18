"""Lease observations never substitute for proof that the execution lock is free."""
import asyncio
import fcntl
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import select, update, or_
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.models.analysis_job import AnalysisJob, AnalysisHead
from app.models.order import Order
from app.config import get_settings

LEASE_SECONDS = 120
MAX_RECOVERIES = 3


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def heartbeat_once(factory, job_id, attempt):
    async with factory() as db:
        await db.execute(update(AnalysisJob).where(AnalysisJob.job_id==job_id,
            AnalysisJob.attempt_token==attempt, AnalysisJob.execution_status=='running').values(heartbeat_at=utcnow()))
        await db.commit()


def start_heartbeat(factory, job_id, attempt, *, interval=30):
    stop = threading.Event()
    # A separate connection/loop keeps heartbeats alive during CPU-bound stages.
    url = factory.kw['bind'].url
    def run():
        engine=create_async_engine(url,poolclass=NullPool)
        own_factory=async_sessionmaker(engine,expire_on_commit=False)
        try:
            while not stop.wait(interval):
                try: asyncio.run(heartbeat_once(own_factory,job_id,attempt))
                except Exception:
                    logging.getLogger(__name__).warning('Analysis heartbeat unavailable; execution lock remains owned')
        finally:
            asyncio.run(engine.dispose())
    thread=threading.Thread(target=run,name='analysis-heartbeat',daemon=True)
    thread.start()
    return stop,thread


async def recover_job(db, job_id, *, manual=False, now=None, enqueue=None):
    from app.services.analysis_jobs import enqueue_job
    enqueue=enqueue or enqueue_job
    now=now or utcnow()
    job=await db.get(AnalysisJob,job_id)
    if job is None: return {'recovery':'missing'}
    await db.execute(select(Order.id).where(Order.id==job.order_id).with_for_update())
    await db.refresh(job,with_for_update=True)
    if job.execution_status in {'completed','cancelled','superseded'}:
        await db.commit();return {'recovery':'terminal','execution_status':job.execution_status}
    previous=job.heartbeat_at or job.updated_at or job.created_at
    if not manual and (job.execution_status not in {'running','queued'} or previous > now-timedelta(seconds=LEASE_SECONDS)):
        await db.commit();return {'recovery':'lease_current'}
    order=await db.get(Order,job.order_id)
    storage=Path(get_settings().OUTPUT_DIR)/order.order_code/'.analysis_results'
    storage.mkdir(parents=True,exist_ok=True)
    lock=(storage/f'{job_id}.lock').open('a')
    try:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            await db.commit();return {'recovery':'execution_still_owned'}
        head=await db.get(AnalysisHead,job.order_id)
        if job.cancel_requested:
            job.execution_status,job.active_key='cancelled',None
        elif job.request_config['analysis_scope']=='full_eligible' and (head is None or head.requested_job_id!=job_id):
            job.execution_status,job.active_key='superseded',None
        elif job.recovery_count >= MAX_RECOVERIES:
            job.execution_status,job.failure_reason,job.active_key='failed','recovery_budget_exhausted',None
        else:
            equivalent=(await db.execute(select(AnalysisJob.job_id).where(
                AnalysisJob.active_key==f'{job.order_id}:{job.input_signature}',AnalysisJob.job_id!=job_id))).scalar_one_or_none()
            if equivalent:
                await db.commit()
                return {'recovery':'equivalent_job_active','job_id':equivalent}
            # Fence a dead attempt before requeue; completed stages remain reusable.
            job.attempt_token=None
            job.execution_status,job.failure_reason='queued',None
            job.active_key=f'{job.order_id}:{job.input_signature}'
            job.recovery_count+=1
            job.heartbeat_at=now
        await db.commit()
        status=job.execution_status
    finally:
        lock.close()
    if status=='queued':
        try: enqueue(job_id)
        except Exception:
            job.execution_status,job.failure_reason,job.active_key='failed','broker_unavailable',None
            await db.commit()
            return {'recovery':'failed','execution_status':'failed','failure_reason':'broker_unavailable'}
    return {'recovery':'requeued' if status=='queued' else 'terminal','execution_status':status}


async def recovery_loop(factory):
    while True:
        try:
            async with factory() as db:
                cutoff=utcnow()-timedelta(seconds=LEASE_SECONDS)
                jobs=(await db.execute(select(AnalysisJob.job_id).where(
                    AnalysisJob.execution_status.in_(['queued','running']),
                    or_(AnalysisJob.heartbeat_at<cutoff,AnalysisJob.heartbeat_at.is_(None)))
                    .order_by(AnalysisJob.created_at).limit(100))).scalars().all()
                for job_id in jobs: await recover_job(db,job_id)
        except asyncio.CancelledError: raise
        except Exception:
            logging.getLogger(__name__).warning('Analysis recovery check unavailable; no execution slot released')
        await asyncio.sleep(30)
