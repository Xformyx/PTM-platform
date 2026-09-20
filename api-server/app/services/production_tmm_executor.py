"""Production queue executor. No benchmark input, permission or truth imports."""
import asyncio
import fcntl
import json
import os
import resource
import shutil
import time
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.analysis_job import AnalysisJob, AnalysisHead
from app.models.order import Order
from app.config import get_settings
from app.services.analysis_jobs import reference_signature, runtime_signature
from app.services.analysis_universe import prepare_analysis, module_response
from app.services.production_temporal_analysis import score_tracks, trajectory_diagnostics, temporal_diagnostics, render_result
from ptm_shared.analysis_revision import verify_input, input_directory, write_stage, verify_result, RESULT_VERSION
from ptm_shared.analysis_universe import signature
from ptm_shared.report_revision import _atomic_json, file_sha256


class AnalysisInterrupted(RuntimeError):
    pass


async def execute_production_tmm(job_id, *, session_factory=AsyncSessionLocal):
    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        if job is None: raise ValueError("analysis_job_missing")
        if job.execution_status in {"completed", "cancelled", "superseded"}:
            return {"job_id": job_id, "execution_status": job.execution_status}
        order = await db.get(Order, job.order_id)
        root = Path(get_settings().OUTPUT_DIR) / order.order_code
        storage = root / ".analysis_results"
        storage.mkdir(parents=True, exist_ok=True)
        lock = (storage / f"{job_id}.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return {"job_id": job_id, "execution_status": "running", "reason": "execution_lock_owned"}
        await db.refresh(job, with_for_update=True)
        if job.execution_status in {"completed", "cancelled", "superseded"}:
            await db.commit()
            lock.close()
            return {"job_id":job_id,"execution_status":job.execution_status}
        attempt = str(uuid4())
        work = storage / job_id / attempt
        work.mkdir(parents=True)
        job.attempt_token = attempt
        job.execution_status = "running"
        from app.services.analysis_job_recovery import start_heartbeat, utcnow
        job.heartbeat_at = utcnow()
        await db.commit()
        heartbeat_stop, heartbeat_thread = start_heartbeat(session_factory, job_id, attempt)
        input_sig = job.input_signature
        cfg = dict(job.request_config)

        async def check():
            await db.execute(select(Order.id).where(Order.id == job.order_id).with_for_update())
            # Locking reads see current committed state even under MySQL's
            # REPEATABLE READ. Cancel and publication use the same Order lock.
            await db.refresh(job, with_for_update=True)
            head = None
            if cfg["analysis_scope"] == "full_eligible":
                head = (await db.execute(select(AnalysisHead).where(AnalysisHead.order_id == job.order_id)
                    .with_for_update().execution_options(populate_existing=True))).scalar_one()
            if cfg.get("parent_generation") is not None:
                from redis import Redis
                current = await asyncio.to_thread(lambda: Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"),
                    socket_connect_timeout=5, socket_timeout=5).get(f"order_run_gen:{job.order_id}"))
                if current is None:
                    raise RuntimeError("parent_generation_unavailable")
                if int(current) != int(cfg["parent_generation"]):
                    raise AnalysisInterrupted("superseded")
            if job.cancel_requested:
                raise AnalysisInterrupted("cancelled")
            if job.attempt_token != attempt or (head is not None and (head.generation != job.generation or head.requested_job_id != job_id)):
                raise AnalysisInterrupted("superseded")
            # A newer preprocessing input invalidates publication, not the old bytes.
            if input_directory(root).name != job.input_revision:
                raise AnalysisInterrupted("superseded")
            return head

        active_stage = None
        async def stage(name, fn, *args):
            nonlocal active_stage
            active_stage = name
            await check()
            previous = (job.stage_status or {}).get(name, {})
            await db.commit()
            if previous.get("execution_status") == "completed" and previous.get("input_signature") == input_sig:
                path = root / previous["path"]
                auxiliaries = previous.get("auxiliaries", [])
                if (path.is_file() and file_sha256(path) == previous["sha256"]
                        and all((root/a["path"]).is_file() and file_sha256(root/a["path"]) == a["sha256"] for a in auxiliaries)):
                    for extra in auxiliaries:
                        shutil.copyfile(root/extra["path"], work/extra["filename"])
                        artifacts.append({k:v for k,v in extra.items() if k != "path"})
                    payload = json.loads(path.read_text())
                    record = write_stage(work, name, payload, input_sig)
                    artifacts.append(record)
                    return payload
            job.stage_status = {**(job.stage_status or {}), name: {"execution_status": "running"}}
            await db.commit()
            before_files = {p.name for p in work.iterdir()}
            start = time.perf_counter()
            payload = fn(*args)  # CPU work runs in the Celery process, never the API loop.
            await check()
            auxiliaries = [{"name": p.name, "filename": p.name, "sha256": file_sha256(p), "input_signature": input_sig,
                            "path": str(p.relative_to(root))} for p in work.iterdir() if p.is_file() and p.name not in before_files]
            artifacts.extend({k:v for k,v in a.items() if k != "path"} for a in auxiliaries)
            record = write_stage(work, name, payload, input_sig)
            artifacts.append(record)
            job.stage_status = {**job.stage_status, name: {**record, "path": str((work/record["filename"]).relative_to(root)),
                "auxiliaries": auxiliaries, "execution_status": "completed", "elapsed_seconds": time.perf_counter()-start,
                "process_peak_rss_native_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}
            await db.commit()
            return payload

        artifacts = []
        try:
            await check()
            if cfg["runtime"] != runtime_signature() or cfg["references"] != reference_signature():
                raise AnalysisInterrupted("superseded")
            source = input_directory(root, job.input_revision)
            frozen = await stage("input_validation", verify_input, source)
            def candidates():
                manifest, inputs, sources = prepare_analysis(source, cfg["ptm_type"], cfg["analysis_context"],
                    config={**cfg["tmm_config"],"inference_mode":cfg.get("inference_mode","legacy_unrecorded")}, scope=cfg["analysis_scope"], subset_ids=cfg["analysis_feature_ids"], subset_reason=cfg["subset_reason"])
                from ptm_shared.analysis_inventory_index import write_inventory_indexes
                write_inventory_indexes(work, manifest)
                _atomic_json(work/'candidate_summary.json',module_response(manifest,compact=True))
                return {"manifest": manifest, "inputs": inputs, "source_status": sources}
            prepared = await stage("candidates", candidates)
            manifest, inputs = prepared["manifest"], prepared["inputs"]
            scores = await stage("score", score_tracks, manifest, inputs, cfg)
            await stage("engine_binding", lambda: {
                "schema_version":"production_engine_binding.v1",
                "measurement_revision":manifest["measurement_revision"],
                "feature_identity_version":manifest["feature_identity_version"],
                "analysis_scope":manifest["analysis_scope"],
                "candidate_graph_hash":signature(manifest["candidate_modules"]),
                "reference_snapshots":cfg["references"],"effective_config":scores["effective_config"],
                "engine_signature":signature(cfg["runtime"]),"runtime":cfg["runtime"],
                "inference_mode":cfg.get("inference_mode","legacy_unrecorded"),
                "input_signature":input_sig,"sample_manifest_hash":signature(manifest["sample_manifest"]),
                "condition_grid":manifest["conditions"],"primary_track":"protein_adjusted_relative_ptm_log2_contrast"})
            scores = await stage("trajectory_diagnostics", trajectory_diagnostics, scores, manifest, inputs, work)
            sidecar = await stage("temporal_diagnostics", temporal_diagnostics, scores, manifest, inputs, source, work, cfg["ptm_type"])
            result = await stage("result", render_result, scores, sidecar, manifest, inputs)
            def comparisons():
                from ptm_shared.kinase_model_comparison import run_footprint_comparisons
                requested = cfg.get("comparison_models", [])
                output = run_footprint_comparisons(manifest, inputs, [m for m in requested if m not in {"tmm_magnitude.v1","proda_label_free.v1","time_window_nnls.v1"}])
                if "time_window_nnls.v1" in requested:
                    from ptm_shared.time_window_comparison import compare_time_windows
                    output["models"].append(compare_time_windows(manifest,inputs,scores))
                if "proda_label_free.v1" in requested:
                    from ptm_shared.proda_comparison import run_proda_comparison
                    output["models"].append(run_proda_comparison(source,work/"proda-comparison",inputs["features"],cfg))
                if "tmm_magnitude.v1" in requested:
                    alternate = score_tracks(manifest, inputs, {"tmm_config":{**cfg["tmm_config"], "target_transform":"magnitude"}})
                    output["models"].append({"model_id":"tmm_magnitude.v1", "status":"completed", "track":"relative",
                        "evaluation_status":alternate["track_status"]["relative"], "effective_config":alternate["effective_config"],
                        "records":[{"kinase":k,"up_sums":v["weighted_up_sums"],"down_sums":v["weighted_down_sums"],
                                    "identifiability":v["tmm_identifiability"]} for k,v in alternate["relative"].items()],
                        "allocation_ledger":alternate["allocation_ledger"], "default_model_promoted":False,
                        "interpretation":"magnitude_shape_allocation_with_original_signed_observations"})
                output["requested_models"] = requested
                return output
            comparison = await stage("model_comparisons", comparisons)
            from ptm_shared.signaling_evidence_index import build_explorer_index
            def explorer():
                reference = os.getenv("PTM_PATHWAY_SOURCE_BUNDLE_PATH")
                frozen_reference = None
                if reference and Path(reference).is_file():
                    frozen_reference = work/"pathway_reference.json"
                    shutil.copyfile(reference, frozen_reference)
                    if file_sha256(frozen_reference) != cfg["references"].get("PTM_PATHWAY_SOURCE_BUNDLE_PATH"):
                        raise AnalysisInterrupted("superseded")
                return build_explorer_index(work, manifest, inputs, scores, sidecar, result, pathway_reference=frozen_reference, comparison=comparison)
            await stage("explorer", explorer)
            await check()
            revision = {"schema_version": RESULT_VERSION, "input_revision": job.input_revision,
                "input_signature": input_sig, "generation": job.generation, "attempt": attempt,
                "execution_status": "completed", "evaluation_status": result["evaluation_status"],
                "artifacts": artifacts, "required_stages": [a["name"] for a in artifacts]}
            revision["revision_id"] = signature(revision)
            _atomic_json(work/"manifest.json", revision)
            await asyncio.to_thread(verify_result, work)
            from ptm_shared.run_evidence_bundle import publish_analysis_bundle
            bundle = publish_analysis_bundle(work, order_id=job.order_id, job_id=job_id,
                parent_generation=cfg.get("parent_generation"), reference_snapshots=cfg["references"])
            # Lock admission/publication on the same existing Order row. Failed,
            # stale or cancelled attempts never replace the successful pointer.
            await db.execute(select(Order.id).where(Order.id == job.order_id).with_for_update())
            head = await check()
            if head is not None:
                head.current_job_id, head.current_revision = job_id, revision["revision_id"]
            job.execution_status, job.evaluation_status, job.active_key = "completed", result["evaluation_status"], None
            job.result_revision, job.result_path = revision["revision_id"], str(work.relative_to(root))
            # Compact compatibility pointers. Large evidence stays in artifacts.
            result["temporal_ptm_protein_analysis"]["artifact_path"] = str((work/"temporal_diagnostics.json").relative_to(root))
            result["temporal_ptm_protein_analysis"]["analysis_revision"] = revision["revision_id"]
            if head is not None:
                order.kinase_activity_heatmap = {"execution_status": "completed", "analysis_job_id": job_id,
                    "evidence_bundle_id": bundle["bundle_id"],
                    "revision_id": job.result_revision, "result_path": job.result_path, "coverage": result["coverage"],
                    "temporal_ptm_protein_analysis": result["temporal_ptm_protein_analysis"]}
                order.kinase_analysis_data = {"analysis_manifest_id": manifest["analysis_manifest_id"],
                    "analysis_job_id": job_id, "revision_id": job.result_revision, "result_path": job.result_path, "coverage": result["coverage"],
                    "temporal_ptm_protein_analysis": result["temporal_ptm_protein_analysis"]}
            await db.commit()
            return {"job_id": job_id, "execution_status": "completed", "revision_id": job.result_revision}
        except BaseException as exc:
            await db.rollback()
            await db.refresh(job)
            if job.attempt_token == attempt:
                import sqlite3
                import duckdb
                resource_failure = isinstance(exc, (MemoryError, OSError, duckdb.OutOfMemoryException)) or getattr(exc, 'sqlite_errorcode', None) in {sqlite3.SQLITE_FULL,sqlite3.SQLITE_NOMEM}
                reason = str(exc) if isinstance(exc, AnalysisInterrupted) else "resource_exhausted" if resource_failure else "solver_or_stage_failure"
                status = reason if reason in {"cancelled", "superseded"} else "timed_out" if type(exc).__name__ in {"SoftTimeLimitExceeded", "TimeoutError"} else "failed"
                job.execution_status, job.failure_reason, job.active_key = status, reason, None
                if active_stage and (job.stage_status or {}).get(active_stage, {}).get("execution_status") != "completed":
                    job.stage_status = {**(job.stage_status or {}), active_stage:{"execution_status":status,"failure_reason":reason}}
                await db.commit()
            if isinstance(exc, AnalysisInterrupted):
                return {"job_id": job_id, "execution_status": str(exc)}
            raise
        finally:
            # This happens after asyncio.to_thread has finished in ordinary stage
            # cancellation. The worker is not returned to the queue mid-compute.
            heartbeat_stop.set()
            await asyncio.to_thread(heartbeat_thread.join, 5)
            lock.close()
