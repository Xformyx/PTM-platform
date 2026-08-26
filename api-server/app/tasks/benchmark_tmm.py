"""Celery entry point for the durable strict-primary TMM stage."""

from __future__ import annotations

import asyncio
import os

from celery import Celery

from app.services.benchmark_tmm_executor import execute_benchmark_tmm

celery_app = Celery("ptm_benchmark_tmm")
celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
celery_app.conf.task_routes = {"app.tasks.benchmark_tmm.*": {"queue": "benchmark_tmm"}}


@celery_app.task(name="app.tasks.benchmark_tmm.run_benchmark_tmm", bind=True)
def run_benchmark_tmm(self, benchmark_run_id: int, user_id: int | None) -> dict[str, object]:
    return asyncio.run(execute_benchmark_tmm(benchmark_run_id, user_id))
