import os

from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

app = Celery(
    "ptm_workers",
    broker=broker_url,
    backend=result_backend,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
    task_routes={
        "preprocessing.tasks.*": {"queue": "preprocessing"},
        "rag_enrichment.tasks.*": {"queue": "rag_enrichment"},
        "report_generation.tasks.*": {"queue": "report_generation"},
    },
    task_default_queue="default",
)

app.autodiscover_tasks([
    "preprocessing",
    "rag_enrichment",
    "report_generation",
])
