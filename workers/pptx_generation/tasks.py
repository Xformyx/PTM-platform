"""
Celery tasks for PPTX generation (avoids HTTP/Cloudflare timeouts on long LLM calls).
"""

import logging

from celery_app import app

logger = logging.getLogger("ptm-workers.pptx_tasks")


@app.task(bind=True, name="pptx_generation.tasks.run_pptx_generation", max_retries=0)
def run_pptx_generation(self, order_id: int, llm_provider: str, llm_model: str):
    """
    Generate PPTX in worker process. Returns dict on success; raises on failure
    (Celery stores exception for AsyncResult).
    """
    from common.pptx_generator import generate_pptx_for_order_sync

    def report(stage: str, message: str, progress: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={"stage": stage, "message": message, "progress": progress},
        )

    logger.info("[PPTX task] start order_id=%s provider=%s model=%s", order_id, llm_provider, llm_model)
    report("queued", "Preparing PPTX generation…", 8)
    return generate_pptx_for_order_sync(
        order_id, llm_provider, llm_model, on_progress=report
    )
