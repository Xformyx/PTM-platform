import os

from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

app = Celery(
    "ptm_workers",
    broker=broker_url,
    backend=result_backend,
)

WATCHDOG_INTERVAL = int(os.getenv("WATCHDOG_CHECK_INTERVAL_SECONDS", "300"))

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
    broker_transport_options={
        "visibility_timeout": 43200,  # 12 hours — prevents Redis redelivery for long-running tasks
    },
    task_routes={
        "preprocessing.tasks.*": {"queue": "preprocessing"},
        "rag_enrichment.tasks.*": {"queue": "rag_enrichment"},
        "rag_enrichment.document_tasks.*": {"queue": "rag_enrichment"},
        "report_generation.tasks.*": {"queue": "report_generation"},
        "pptx_generation.tasks.*": {"queue": "report_generation"},
        "watchdog.tasks.*": {"queue": "default"},
    },
    task_default_queue="default",
    beat_schedule={
        "watchdog-check-stalled": {
            "task": "watchdog.tasks.check_stalled_orders",
            "schedule": WATCHDOG_INTERVAL,
        },
    },
)

app.autodiscover_tasks([
    "preprocessing",
    "rag_enrichment",
    "report_generation",
    "pptx_generation",
    "watchdog",
])

# document_tasks.py is not named 'tasks.py', so autodiscover won't find it.
# Explicit import ensures the @app.task decorators are registered.
import rag_enrichment.document_tasks  # noqa: F401, E402
import pptx_generation.tasks  # noqa: F401, E402
