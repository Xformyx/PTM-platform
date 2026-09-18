"""Separate production Celery queue; no benchmark worker permissions or inputs."""
import asyncio
import os
from celery import Celery

celery_app = Celery("ptm_production_tmm", broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1"),
                    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2"))
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 43200}, result_backend_transport_options={"visibility_timeout": 43200},
    visibility_timeout=43200, task_routes={"app.tasks.production_tmm.*": {"queue": "production_tmm"}})


@celery_app.task(name="app.tasks.production_tmm.execute", bind=True,
                 soft_time_limit=21600, time_limit=21720)
def execute(self, job_id):
    from app.services.production_tmm_executor import execute_production_tmm
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.config import get_settings
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async def run():
        try: return await execute_production_tmm(job_id, session_factory=factory)
        finally: await engine.dispose()
    return asyncio.run(run())


@celery_app.task(name="app.tasks.production_tmm.submit_order", bind=True,
                 soft_time_limit=21600, time_limit=21720)
def submit_order(self, order_id, request=None):
    """Trusted pipeline producer; broker message contains IDs/config, not matrices."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.config import get_settings
    from app.models.order import Order
    from app.services.analysis_jobs import submit_analysis
    from app.services.production_tmm_executor import execute_production_tmm
    engine = create_async_engine(get_settings().DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async def run():
        try:
            async with factory() as db:
                order = await db.get(Order, order_id)
                if order is None: raise ValueError("order_missing")
                job = await submit_analysis(db, order, None, request or {}, enqueue=False)
                job_id = job.job_id
            return await execute_production_tmm(job_id, session_factory=factory)
        finally: await engine.dispose()
    return asyncio.run(run())


@celery_app.task(name="app.tasks.production_tmm.prepare_view", bind=True)
def prepare_view(self, order_id, task_token):
    """Additive backfill: preserve source and previous analysis revisions."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.config import get_settings
    from app.models.order import Order
    from pathlib import Path
    from ptm_shared.analysis_revision import publish_analysis_input
    from ptm_shared.vector_columnar import publish_vector_columnar
    engine=create_async_engine(get_settings().DATABASE_URL,poolclass=NullPool)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    async def run():
        try:
            async with factory() as db:
                order=await db.get(Order,order_id)
                options=dict(order.analysis_options or {})
                if (options.get("vector_index_job") or {}).get("task_id") != task_token:
                    return {"execution_status":"superseded"}
                options["vector_index_job"]={"task_id":task_token,"execution_status":"running"}
                order.analysis_options=options;await db.commit()
                try:
                    root=Path(get_settings().OUTPUT_DIR)/order.order_code
                    config={"ptm_type":order.ptm_type,"analysis_context":order.analysis_context or {},"analysis_options":{k:v for k,v in (order.analysis_options or {}).items() if k.startswith("quick_")}}
                    from ptm_shared.analysis_revision import input_directory, verify_input
                    try: revision=verify_input(input_directory(root))
                    except FileNotFoundError: revision=publish_analysis_input(root,config=config)
                    columnar=publish_vector_columnar(root,"_phospho" if order.ptm_type=="phosphorylation" else "_ubi")
                    state={"task_id":task_token,"execution_status":"completed","input_revision":revision["input_revision"],"measurement_revision":columnar["measurement_revision"]}
                except Exception:
                    state={"task_id":task_token,"execution_status":"failed","failure_reason":"vector_index_publication_failed"}
                    raise
                finally:
                    await db.refresh(order)
                    options=dict(order.analysis_options or {})
                    if (options.get("vector_index_job") or {}).get("task_id")==task_token:
                        order.analysis_options={**options,"vector_index_job":state};await db.commit()
                return state
        finally: await engine.dispose()
    return asyncio.run(run())
