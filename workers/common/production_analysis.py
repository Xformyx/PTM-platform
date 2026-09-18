"""RAG/report use the same server-owned temporal job as the interactive API."""
import json
from pathlib import Path
from celery.result import allow_join_result
from celery_app import app
from common.db_engine import get_engine
from sqlalchemy import text
from ptm_shared.analysis_revision import verify_result


def complete_production_analysis(order_id, config):
    from common.run_control import abort_if_superseded
    abort_if_superseded(order_id)
    task = app.send_task("app.tasks.production_tmm.submit_order",
        args=[order_id, {"analysis_scope": "full_eligible", "tmm_config": config.get("tmm_config") or {}}],
        queue="production_tmm")
    # This orchestration worker waits; all computation lives in the dedicated
    # queue. A disconnected browser has no bearing on this dependency.
    with allow_join_result():
        response = task.get(timeout=21780, propagate=True)
    abort_if_superseded(order_id)
    if response.get("execution_status") != "completed":
        raise RuntimeError("required_production_analysis_" + str(response.get("execution_status")))
    with get_engine().connect() as connection:
        row = connection.execute(text("SELECT j.result_path, o.order_code FROM analysis_jobs j JOIN orders o ON o.id=j.order_id WHERE j.job_id=:job AND j.order_id=:oid AND j.execution_status='completed'"),
                                 {"job": response["job_id"], "oid": order_id}).mappings().one()
    import os
    directory = Path(os.getenv("OUTPUT_DIR", "/app/data/outputs")) / row["order_code"] / row["result_path"]
    revision = verify_result(directory)
    result = json.loads((directory/"result.json").read_text())
    candidates = json.loads((directory/"candidates.json").read_text())["manifest"]
    summary = result["temporal_ptm_protein_analysis"]
    summary["artifact_path"] = str((directory/"temporal_diagnostics.json").relative_to(directory.parents[2]))
    return {"kinase_analysis_data": {"analysis_manifest_id": candidates["analysis_manifest_id"],
                "result_path": row["result_path"], "revision_id": revision["revision_id"], "analysis_job_id": response["job_id"],
                "coverage": result["coverage"], "kinase_modules": candidates["candidate_modules"],
                "temporal_ptm_protein_analysis": summary},
            "kinase_activity_heatmap": result, "temporal_ptm_protein_analysis": summary,
            "analysis_revision": revision, "analysis_job_id": response["job_id"]}
