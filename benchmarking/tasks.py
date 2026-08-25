"""Offline locked scorer worker; never imported by API, workers, or reports."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from celery import shared_task
from sqlalchemy import create_engine, text

from .contracts import BenchmarkManifest
from .locked_scorer import LockedBenchmarkScorer
from .result_bundle import write_score_bundle


def _sync_database_url() -> str:
    return os.environ["DATABASE_URL"].replace("mysql+asyncmy", "mysql+pymysql")


@shared_task(name="benchmarking.tasks.score_benchmark_run", bind=True)
def score_benchmark_run(self, benchmark_run_id: int) -> dict:
    engine = create_engine(_sync_database_url(), future=True)
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT dataset_id, artifact_path FROM benchmark_runs WHERE id = :id"),
            {"id": benchmark_run_id},
        ).mappings().first()
        if not row:
            raise ValueError("BenchmarkRun not found")
        conn.execute(text("UPDATE benchmark_runs SET status = 'scoring', started_at = COALESCE(started_at, NOW()) WHERE id = :id"), {"id": benchmark_run_id})
    try:
        reference_root = Path(os.getenv("BENCHMARK_REFERENCE_DIR", "/opt/benchmarks"))
        result_root = Path(os.getenv("BENCHMARK_RESULT_DIR", "/app/storage/benchmarks"))
        manifest_path = reference_root / row["dataset_id"] / f"{row['dataset_id']}.manifest.json"
        artifact_path = Path(row["artifact_path"])
        manifest = BenchmarkManifest.load(manifest_path)
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        result = LockedBenchmarkScorer(manifest).score(artifact)
        bundle = write_score_bundle(
            result,
            output_dir=result_root / f"benchmark_run_{benchmark_run_id}",
            analysis_artifact_path=artifact_path,
        )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE benchmark_runs SET status = 'completed', result_path = :result_path, "
                    "score_summary = :summary, completed_at = NOW(), provenance = JSON_SET(COALESCE(provenance, JSON_OBJECT()), '$.scored_at_utc', :scored_at) WHERE id = :id"
                ),
                {
                    "id": benchmark_run_id,
                    "result_path": str(bundle["result_json"]),
                    "summary": json.dumps(result["metrics"]),
                    "scored_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return {"benchmark_run_id": benchmark_run_id, "status": "completed", "result_path": str(bundle["result_json"])}
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE benchmark_runs SET status = 'failed', error_message = :error, completed_at = NOW() WHERE id = :id"),
                {"id": benchmark_run_id, "error": str(exc)[:2000]},
            )
        raise
