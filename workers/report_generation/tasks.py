"""
Stage 3: Report Generation Pipeline — Celery Task.

Uses LangGraph StateGraph to orchestrate:
  1. Context loading (enriched PTM data)
  2. Research analysis (PTM patterns per question)
  3. Hypothesis generation (LLM-powered)
  4. Hypothesis validation (ChromaDB RAG)
  5. Network analysis (Cytoscape Option A)
  6. Section writing (LLM + RAG)
  7. Final report editing and compilation
"""

import json
import logging
import os
import time
import traceback
from pathlib import Path

import redis as _redis

from celery_app import app
from common.db_update import get_order_status, update_order_status
from common.notifications import notify_order_status
from common.progress import publish_analysis_log, publish_progress
from common.webhook import send_step_webhook

logger = logging.getLogger("ptm-workers.report-generation")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/outputs")
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def _resolve_enriched_json_path(order_id: int, rag_dir: Path, explicit: str | None) -> str:
    """
    Prefer config path if the file exists; otherwise pick newest enriched_ptm_data*.json
    under rag_dir. Avoids FileNotFoundError when RAG chained path is stale or volume reset.
    """
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p.resolve())
        logger.warning(
            "[Order %s] enriched_json_path not found (%s), searching %s",
            order_id,
            explicit,
            rag_dir,
        )
    rag_dir = Path(rag_dir)
    if not rag_dir.is_dir():
        raise FileNotFoundError(
            f"[Order {order_id}] RAG output directory missing: {rag_dir}. "
            "Run preprocessing and RAG Enrichment so the order output folder exists."
        )
    candidates = sorted(
        rag_dir.glob("enriched_ptm_data*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"[Order {order_id}] No enriched_ptm_data*.json under {rag_dir}. "
            "Run RAG Enrichment to completion (order must reach the JSON save step). "
            f"Expected file was: {explicit or f'enriched_ptm_data_*.json in {rag_dir}'}"
        )
    chosen = candidates[0]
    logger.info("[Order %s] Using enriched JSON: %s", order_id, chosen)
    return str(chosen.resolve())


def _emit_kinase_phase(order_id: int, status: str, detail: str, pct: float = 0):
    """Emit a report_phase log entry for the kinase_annotation step."""
    publish_analysis_log(
        order_id, f"[report:kinase_annotation] {status}: {detail}",
        stage="report_generation", step="report_phase", status="progress",
        metadata={"type": "report_phase", "step": "kinase_annotation",
                  "status": status, "detail": detail, "pct": round(pct, 1)},
        persist=True,
    )


def _auto_build_kinase_modules(order_id: int, enriched_data: list, config: dict) -> dict:
    """Auto-build Global Kinase Modules when not pre-computed by the user.

    Runs the same pipeline-internal logic as kinase_annotation_node but earlier,
    so the result is available as frontend_kinase_analysis from the start and
    also saved to orders.kinase_analysis_data for POTATIO AI chat.
    """
    t0 = time.time()
    _emit_kinase_phase(order_id, "running", "Auto-building Global Kinase Modules")
    publish_progress(
        order_id, "report_generation", "kinase_modules", "running", 1,
        "Auto-building Global Kinase Modules",
    )
    try:
        from report_generation.core.nodes.kinase_annotation_node import (
            _build_global_kinase_modules,
            PHOSPHO_MOTIF_DB,
            UBI_MOTIF_DB,
        )

        ptm_type = (config.get("experimental_context") or {}).get("ptm_type", "phosphorylation")
        motif_db = PHOSPHO_MOTIF_DB if ptm_type == "phosphorylation" else UBI_MOTIF_DB

        result = _build_global_kinase_modules(
            enriched_data=enriched_data,
            cluster_annotations=[],
            clusters=[],
            motif_db=motif_db,
            ptm_type=ptm_type,
        )
        n_modules = result.get("summary", {}).get("total_kinase_modules", 0)
        n_confirmed = result.get("summary", {}).get("total_confirmed", 0)
        elapsed = round(time.time() - t0, 1)
        logger.info(
            f"[Order {order_id}] Auto-built Global Kinase Modules: "
            f"{n_modules} modules in {elapsed}s"
        )
        detail = f"Built {n_modules} kinase modules ({n_confirmed} confirmed, {elapsed}s)"
        _emit_kinase_phase(order_id, "done", detail)
        publish_progress(
            order_id, "report_generation", "kinase_modules", "running", 2,
            detail,
        )

        # Persist to DB so POTATIO AI chat can use it without Global Annotate
        try:
            from common.db_engine import get_engine as _get_engine
            from sqlalchemy import text as _text
            _engine = _get_engine()
            with _engine.connect() as _conn:
                _conn.execute(
                    _text(
                        "UPDATE orders SET kinase_analysis_data = :kad WHERE id = :oid"
                    ),
                    {"oid": order_id, "kad": json.dumps(result)},
                )
                _conn.commit()
            logger.info(f"[Order {order_id}] Saved auto-built kinase_analysis_data to DB")
        except Exception as _db_err:
            logger.warning(f"[Order {order_id}] Could not save kinase_analysis_data to DB: {_db_err}")

        return result
    except Exception as e:
        logger.warning(f"[Order {order_id}] Auto-build kinase modules failed (non-fatal): {e}")
        _emit_kinase_phase(order_id, "error", f"Failed (non-fatal): {e}")
        return {}


_REPORT_STEP_ORDER = [
    "kinase_annotation", "context_loading", "question_generation", "research",
    "hypothesis", "validation", "network", "rq_refinement", "writing",
    "report_copilot", "qa_report", "compilation",
]


def _make_progress_cb(order_id):
    seen_steps: set[str] = set()

    def _emit(step, status, detail="", pct=0):
        seen_steps.add(step)
        publish_analysis_log(
            order_id, f"[report:{step}] {status}: {detail}",
            stage="report_generation", step="report_phase", status="progress",
            metadata={"type": "report_phase", "step": step, "status": status,
                      "detail": detail, "pct": round(pct, 1)},
            persist=True,
        )

    def _backfill_prior(current_step):
        """Mark all steps before current_step as 'done' if not yet seen."""
        idx = _REPORT_STEP_ORDER.index(current_step) if current_step in _REPORT_STEP_ORDER else -1
        if idx <= 0:
            return
        for prev in _REPORT_STEP_ORDER[:idx]:
            if prev not in seen_steps:
                _emit(prev, "done", "Completed (cached)", 0)

    def cb(pct, msg):
        publish_progress(order_id, "report_generation", "graph", "running", round(pct, 1), msg)

        if "Loading enriched PTM data" in msg:
            _emit("context_loading", "running", msg, pct)
        elif msg.startswith("Context loaded:"):
            _emit("context_loading", "done", msg, pct)
        elif "Generating AI research questions" in msg:
            _backfill_prior("question_generation")
            _emit("question_generation", "running", msg, pct)
        elif msg.startswith("Generated ") and "question" in msg:
            _backfill_prior("question_generation")
            _emit("question_generation", "done", msg, pct)
        elif msg.startswith("Using ") and "question" in msg:
            _backfill_prior("question_generation")
            _emit("question_generation", "done", msg, pct)
        elif msg == "Analyzing PTM data":
            _backfill_prior("research")
            _emit("research", "running", msg, pct)
        elif msg.startswith("Researching:"):
            _emit("research", "running", msg, pct)
        elif msg.startswith("Research complete:"):
            _backfill_prior("research")
            _emit("research", "done", msg, pct)
        elif msg == "Generating hypotheses":
            _backfill_prior("hypothesis")
            _emit("hypothesis", "running", msg, pct)
        elif msg.startswith("Hypothesis for Q"):
            _emit("hypothesis", "running", msg, pct)
        elif msg.startswith("Generated ") and "hypothes" in msg:
            _backfill_prior("hypothesis")
            _emit("hypothesis", "done", msg, pct)
        elif msg == "Validating hypotheses":
            _backfill_prior("validation")
            _emit("validation", "running", msg, pct)
        elif msg.startswith("Validation complete:"):
            _backfill_prior("validation")
            _emit("validation", "done", msg, pct)
        elif "Analyzing signaling networks" in msg:
            _backfill_prior("network")
            _emit("network", "running", msg, pct)
        elif "Network analysis complete" in msg or "Network analysis failed" in msg:
            _backfill_prior("network")
            _emit("network", "done", msg, pct)
        elif "Refining research questions" in msg:
            _backfill_prior("rq_refinement")
            _emit("rq_refinement", "running", msg, pct)
        elif "refined" in msg and "question" in msg.lower():
            _backfill_prior("rq_refinement")
            _emit("rq_refinement", "done", msg, pct)
        elif "RQ refinement skipped" in msg:
            _backfill_prior("rq_refinement")
            _emit("rq_refinement", "done", msg, pct)
        elif msg == "Writing report sections":
            _backfill_prior("writing")
            _emit("writing", "running", msg, pct)
        elif msg.startswith("Writing "):
            _emit("writing", "running", msg, pct)
        elif msg == "All sections written":
            _backfill_prior("writing")
            _emit("writing", "done", msg, pct)
        elif "Report co-pilot" in msg and "reviewing" in msg:
            _backfill_prior("report_copilot")
            _emit("report_copilot", "running", msg, pct)
        elif "Report reviewed" in msg or "Report co-pilot skipped" in msg:
            _backfill_prior("report_copilot")
            _emit("report_copilot", "done", msg, pct)
        elif "Generating Q&A report" in msg:
            _backfill_prior("qa_report")
            _emit("qa_report", "running", msg, pct)
        elif "Q&A report generated" in msg:
            _backfill_prior("qa_report")
            _emit("qa_report", "done", msg, pct)
        elif msg == "Compiling final report":
            _backfill_prior("compilation")
            _emit("compilation", "running", msg, pct)
        elif "Report generation complete" in msg:
            _backfill_prior("compilation")
            _emit("compilation", "done", msg, pct)

    return cb


@app.task(bind=True, name="report_generation.tasks.generate_questions_task", max_retries=1)
def generate_questions_task(self, order_id: int, md_path: str, llm_provider: str, llm_model: str, max_questions: int = 8):
    """Generate AI research questions from a comprehensive MD report."""
    logger.info(f"[Order {order_id}] Generating questions from {md_path}")
    publish_progress(order_id, "report_generation", "questions", "running", 0, "Generating AI research questions...")

    try:
        content = Path(md_path).read_text(encoding="utf-8", errors="replace")

        from report_generation.core.nodes.question_generator import generate_questions_from_content
        result = generate_questions_from_content(
            content=content,
            llm_provider=llm_provider,
            llm_model=llm_model,
            max_questions=max_questions,
        )

        if result["success"]:
            update_order_status(order_id, None, report_options_merge={"ai_questions": result["questions"]})
            publish_progress(
                order_id, "report_generation", "questions", "completed", 100,
                f"Generated {result['count']} AI research questions",
                metadata={"questions": result["questions"]},
            )
        else:
            publish_progress(
                order_id, "report_generation", "questions", "completed", 100,
                f"Question generation: {result.get('error', 'using fallback')}",
                metadata={"questions": result["questions"]},
            )

        return result
    except Exception as e:
        logger.error(f"[Order {order_id}] Question generation failed: {e}", exc_info=True)
        publish_progress(order_id, "report_generation", "questions", "failed", -1, str(e))
        raise


@app.task(bind=True, name="report_generation.tasks.run_report_generation", max_retries=1)
def run_report_generation(self, order_id: int, config: dict):
    """
    Stage 3: Report Generation Pipeline (LangGraph).

    config keys:
      - rag_output_dir: str           (path to Stage 2 output)
      - enriched_json_path: str       (path to enriched PTM JSON)
      - md_report_path: str           (path to Stage 2 MD report)
      - experimental_context: dict
      - research_questions: list[str]  (optional — auto-generated if missing)
      - chromadb_collections: list[str]
      - llm_provider: str             (default 'ollama')
      - llm_model: str                (default from env)
      - report_title: str
    """
    from common.run_control import RunSuperseded, bind_run_generation, is_stale_generation

    bind_run_generation(order_id, config.get("run_generation"))
    if is_stale_generation(order_id, config.get("run_generation")):
        logger.info(f"[Order {order_id}] Report generation skipped — stale run_generation")
        return {"order_id": order_id, "status": "skipped", "reason": "stale_generation"}

    lock_key = f"report_gen_lock:{order_id}"
    lock_client = _redis.from_url(_REDIS_URL, decode_responses=True)
    acquired = lock_client.set(lock_key, "1", nx=True, ex=14400)  # 4-hour TTL
    if not acquired:
        logger.warning(
            f"[Order {order_id}] Report generation already running (lock exists). "
            f"Skipping duplicate execution."
        )
        return {"order_id": order_id, "status": "skipped", "reason": "duplicate"}

    _current_status = get_order_status(order_id)
    # Allow report generation only from valid predecessor states.
    # "rag_enrichment" = normal chain from RAG.
    # "completed"/"failed" = explicit re-run before the API flips status.
    # "report_generation" = POST /orders/{id}/run-stage sets this before dispatch
    # so the UI shows in-progress; do NOT treat it as stale.
    # "queued" is intentionally excluded — that is the preprocessing/RAG dispatch
    # marker and also the leftover status of a cancelled/restarted pipeline.
    # cancelled / preprocessing / None = stale task; must not overwrite state.
    _allowed_start_statuses = {"rag_enrichment", "completed", "failed", "report_generation"}
    if _current_status not in _allowed_start_statuses:
        try:
            lock_client.delete(lock_key)
        except Exception:
            pass
        logger.info(
            f"[Order {order_id}] Report generation skipped — "
            f"unexpected status: {_current_status!r} (expected one of {_allowed_start_statuses})"
        )
        return {"order_id": order_id, "status": "skipped", "reason": f"unexpected_status:{_current_status}"}

    start_time = time.time()
    order_code = config.get("order_code") or str(order_id)
    order_output = Path(OUTPUT_DIR) / order_code
    order_output.mkdir(parents=True, exist_ok=True)

    update_order_status(order_id, "report_generation", current_stage="report_generation", progress_pct=0,
                        stage_detail="Report generation started")

    # Clear stale report_phase logs from previous runs so the UI starts clean
    try:
        from common.db_engine import get_engine as _get_engine
        from sqlalchemy import text as _text
        _eng = _get_engine()
        with _eng.connect() as _conn:
            _conn.execute(
                _text("DELETE FROM order_logs WHERE order_id = :oid AND step = 'report_phase'"),
                {"oid": order_id},
            )
            _conn.commit()
        logger.info(f"[Order {order_id}] Cleared previous report_phase logs")
    except Exception as _del_err:
        logger.warning(f"[Order {order_id}] Could not clear old report_phase logs: {_del_err}")

    logger.info(f"[Order {order_id}] Report generation started")
    publish_progress(order_id, "report_generation", "start", "started", 0, "Report generation pipeline started")
    send_step_webhook(order_id, "report_generation", "started")

    try:
        # Resolve enriched data path (handles missing explicit path after RAG stop / volume issues)
        rag_dir = Path(config.get("rag_output_dir", str(order_output)))
        enriched_path = _resolve_enriched_json_path(
            order_id, rag_dir, config.get("enriched_json_path")
        )

        # Load enriched data
        with open(enriched_path, "r", encoding="utf-8") as f:
            enriched_data = json.load(f)
        logger.info(f"[Order {order_id}] Loaded {len(enriched_data)} enriched PTMs from {enriched_path}")

        # v9.35: Auto-build Global Kinase Modules if not pre-computed
        kinase_analysis_data = config.get("kinase_analysis_data") or {}
        if kinase_analysis_data.get("kinase_modules"):
            n_km = len(kinase_analysis_data["kinase_modules"])
            _emit_kinase_phase(order_id, "skipped", f"Using pre-computed data ({n_km} kinase modules)")
            logger.info(f"[Order {order_id}] Kinase modules already in DB ({n_km} modules) — skipped")
        else:
            kinase_analysis_data = _auto_build_kinase_modules(order_id, enriched_data, config)

        # Build initial state (merge single_time_point into experimental_context)
        experimental_context = dict(config.get("experimental_context") or {})
        experimental_context["single_time_point"] = config.get("single_time_point", False)
        analysis_mode = config.get("analysis_mode", "ptm_only")

        # v9.20: Load receptor_inference_data from DB
        inferred_receptors_from_db = []
        # v9.44: Load kinase_activity_heatmap + signal_propagation_data from DB
        kinase_activity_heatmap_from_db = {}
        temporal_ptm_protein_analysis_from_db = {}
        signal_propagation_from_db = {}
        # v11.6: IP overlay data (physical interaction evidence)
        ip_overlay_from_db = {}
        # Atlas context: optional GO cellular-component annotations.
        substrate_go_localization_from_db = {}
        # v10.1: Load vector_plot_raw_data (full TSV) for LLM access
        vector_plot_raw_data = []
        ptm_type_for_suffix = (config.get("experimental_context") or {}).get("ptm_type", "phosphorylation")
        _vp_suffix = "_phospho" if ptm_type_for_suffix == "phosphorylation" else "_ubi"
        for _vp_name in (f"ptm_vector_data_normalized{_vp_suffix}.tsv", f"ptm_vector_data_with_motifs{_vp_suffix}.tsv"):
            _vp_path = order_output / _vp_name
            if _vp_path.exists():
                import csv as _csv
                with open(_vp_path, "r", encoding="utf-8") as _vf:
                    _reader = _csv.DictReader(_vf, delimiter="\t")
                    for _row in _reader:
                        _gene = _row.get("Gene.Name", _row.get("gene", ""))
                        _pos = _row.get("PTM_Position", _row.get("position", ""))
                        _cond = _row.get("Condition", "")
                        try:
                            _rel_fc = float(_row.get("PTM_Relative_Log2FC", "") or 0)
                        except (ValueError, TypeError):
                            _rel_fc = 0
                        try:
                            _prot_fc = float(_row.get("Protein_Log2FC", "") or 0)
                        except (ValueError, TypeError):
                            _prot_fc = 0
                        vector_plot_raw_data.append({
                            "gene": _gene, "position": str(_pos), "condition": _cond,
                            "ptm_relative_log2fc": round(_rel_fc, 3),
                            "protein_log2fc": round(_prot_fc, 3),
                        })
                logger.info(f"[Order {order_id}] Loaded {len(vector_plot_raw_data)} vector plot raw data rows from {_vp_name}")
                break

        # v10.1: Load pipeline_statistics for Methods section
        pipeline_statistics = {}
        _stats_path = order_output / f"pipeline_statistics{_vp_suffix}.json"
        if _stats_path.exists():
            try:
                with open(_stats_path, "r", encoding="utf-8") as _sf:
                    pipeline_statistics = json.load(_sf)
                logger.info(f"[Order {order_id}] Loaded pipeline statistics from {_stats_path.name}")
            except Exception as _stats_err:
                logger.warning(f"[Order {order_id}] Could not load pipeline statistics: {_stats_err}")
        # v10.7: Load ubiquitin linkage analysis (ubi mode only)
        ubiquitin_linkage_data = {}
        _linkage_path = order_output / f"ubiquitin_linkage_analysis{_vp_suffix}.json"
        if _linkage_path.exists():
            try:
                with open(_linkage_path, "r", encoding="utf-8") as _lf:
                    ubiquitin_linkage_data = json.load(_lf)
                if ubiquitin_linkage_data.get("detected"):
                    logger.info(f"[Order {order_id}] Loaded ubiquitin linkage analysis: {len(ubiquitin_linkage_data.get('summary', {}).get('detected_types', []))} chain types")
            except Exception as _link_err:
                logger.warning(f"[Order {order_id}] Could not load linkage analysis: {_link_err}")

        try:
            from common.db_engine import get_engine as _get_shared_engine
            from sqlalchemy import text as _text
            _engine = _get_shared_engine()
            with _engine.connect() as _conn:
                _row = _conn.execute(
                    _text(
                        "SELECT receptor_inference_data, kinase_activity_heatmap, "
                        "signal_propagation_data, ip_overlay_data, substrate_go_localization, kinase_analysis_data "
                        "FROM orders WHERE id = :oid"
                    ),
                    {"oid": order_id},
                ).fetchone()
            if _row:
                import json as _json
                if _row[0]:
                    _rid = _row[0] if isinstance(_row[0], dict) else _json.loads(_row[0])
                    inferred_receptors_from_db = _rid.get("receptors", [])
                    logger.info(f"[Order {order_id}] Loaded {len(inferred_receptors_from_db)} inferred receptors from DB")
                if _row[1]:
                    kinase_activity_heatmap_from_db = _row[1] if isinstance(_row[1], dict) else _json.loads(_row[1])
                    logger.info(f"[Order {order_id}] Loaded kinase activity heatmap from DB ({len(kinase_activity_heatmap_from_db.get('kinase_scores', []))} kinases)")
                if _row[2]:
                    signal_propagation_from_db = _row[2] if isinstance(_row[2], dict) else _json.loads(_row[2])
                    logger.info(f"[Order {order_id}] Loaded signal propagation data from DB")
                if _row[3]:
                    ip_overlay_from_db = _row[3] if isinstance(_row[3], dict) else _json.loads(_row[3])
                    logger.info(f"[Order {order_id}] Loaded IP overlay data from DB (bait: {ip_overlay_from_db.get('bait', {}).get('gene', 'unknown')})")
                if _row[4]:
                    substrate_go_localization_from_db = _row[4] if isinstance(_row[4], dict) else _json.loads(_row[4])
                    logger.info(f"[Order {order_id}] Loaded GO localization data from DB")
                if _row[5]:
                    _kad = _row[5] if isinstance(_row[5], dict) else _json.loads(_row[5])
                    temporal_ptm_protein_analysis_from_db = _kad.get("temporal_ptm_protein_analysis") or {}
            if not temporal_ptm_protein_analysis_from_db:
                temporal_ptm_protein_analysis_from_db = (
                    kinase_activity_heatmap_from_db.get("temporal_ptm_protein_analysis") or {}
                )
            if temporal_ptm_protein_analysis_from_db:
                kinase_analysis_data["temporal_ptm_protein_analysis"] = temporal_ptm_protein_analysis_from_db
                logger.info(
                    f"[Order {order_id}] Loaded shared PTM–protein temporal evidence "
                    f"({temporal_ptm_protein_analysis_from_db.get('cross_layer_edge_count', 0)} edges)"
                )
        except Exception as _rec_err:
            logger.warning(f"[Order {order_id}] Could not load analysis data from DB: {_rec_err}")

        # v11.5f: Fallback — use receptor_inference_data from report_config if DB is empty
        if not inferred_receptors_from_db:
            _config_rid = config.get("receptor_inference_data", {})
            if _config_rid and _config_rid.get("receptors"):
                inferred_receptors_from_db = _config_rid["receptors"]
                logger.info(
                    f"[Order {order_id}] Loaded {len(inferred_receptors_from_db)} inferred receptors "
                    f"from report_config (auto-pipeline fallback)"
                )

        initial_state = {
            "order_id": order_id,
            "enriched_ptm_data": enriched_data,
            "enriched_json_path": enriched_path,
            "md_report_path": config.get("md_report_path", ""),
            "tsv_data_path": config.get("tsv_data_path", ""),
            "experimental_context": experimental_context,
            "research_questions": config.get("research_questions", []),
            "chromadb_collections": config.get("chromadb_collections", []),
            "collection_names": config.get("chromadb_collections", []),
            "output_dir": str(order_output),
            "llm_provider": config.get("llm_provider", "ollama"),
            "llm_model": config.get("llm_model"),
            "report_title": config.get("report_title", "PTM Comprehensive Analysis Report"),
            "report_type": config.get("report_type", "comprehensive"),
            "report_config": config.get("report_config", {}),
            # v12.1: opt-in external Discussion Evidence Packet integration.
            "co_scientist_integration": config.get("co_scientist_integration", {}),
            # P3: Optional post-analysis intervention evidence. This is kept
            # separate from the unbiased discovery time-course inputs.
            "perturbation_evidence": config.get("perturbation_evidence", {}),
            "analysis_mode": analysis_mode,
            "temporal_contract": config.get("temporal_contract", "dynamics_v1"),
            "progress_callback": _make_progress_cb(order_id),
            # v9.12/v9.35: Frontend kinase analysis results (auto-built if absent)
            "frontend_kinase_analysis": kinase_analysis_data,
            "temporal_ptm_protein_analysis": temporal_ptm_protein_analysis_from_db,
            # v9.20: Inferred upstream receptors from vector-plot-data analysis
            "inferred_receptors": inferred_receptors_from_db,
            # v9.33: PTM selection settings (synced with frontend kinase module analysis)
            "top_n_ptms": config.get("top_n_ptms", 50),
            "ptm_selection_mode": config.get("ptm_selection_mode", "top_n"),
            # v9.44: Kinase activity heatmap data (auto-computed in RAG stage)
            "kinase_activity_heatmap": kinase_activity_heatmap_from_db or config.get("kinase_activity_heatmap", {}),
            # v9.44: Signal propagation data for report generation
            "signal_propagation_data": signal_propagation_from_db,
            "substrate_go_localization": substrate_go_localization_from_db,
            # v10.1: Vector plot raw data (full TSV) for LLM comprehensive access
            "vector_plot_raw_data": vector_plot_raw_data,
            # v10.1: Pipeline statistics for Methods section
            "pipeline_statistics": pipeline_statistics,
            # v10.7: Ubiquitin chain linkage analysis (ubi mode only)
            "ubiquitin_linkage_data": ubiquitin_linkage_data,
            # v11.6: IP (Immunoprecipitation) overlay data — physical interaction evidence
            "ip_overlay_data": ip_overlay_from_db,
        }

        # ── Cross-Talk mode: load secondary PTM data into initial_state ──
        if analysis_mode == "cross_talk":
            logger.info(f"[Order {order_id}] Cross-Talk mode: loading secondary PTM data")
            secondary_ptm_type = config.get("secondary_ptm_type", "ubiquitylation")
            secondary_output_dir = config.get("secondary_output_dir")
            secondary_enriched_json = config.get("secondary_enriched_json_path")
            secondary_md_path = config.get("secondary_md_report_path", "")
            secondary_tsv_path = config.get("secondary_tsv_data_path", "")

            # Try to find secondary enriched JSON if not explicitly provided
            if not secondary_enriched_json and secondary_output_dir:
                sec_dir = Path(secondary_output_dir)
                sec_candidates = list(sec_dir.glob("enriched_ptm_data_*.json"))
                if sec_candidates:
                    secondary_enriched_json = str(sec_candidates[0])
                    logger.info(f"[Order {order_id}] Found secondary enriched JSON: {secondary_enriched_json}")

            # Also check in the main order output's secondary_ptm subdirectory
            if not secondary_enriched_json:
                sec_subdir = order_output / "secondary_ptm"
                if sec_subdir.exists():
                    sec_candidates = list(sec_subdir.glob("enriched_ptm_data_*.json"))
                    if sec_candidates:
                        secondary_enriched_json = str(sec_candidates[0])
                        logger.info(f"[Order {order_id}] Found secondary enriched JSON in secondary_ptm/: {secondary_enriched_json}")

            # Load secondary enriched data
            secondary_enriched_data = []
            if secondary_enriched_json and Path(secondary_enriched_json).exists():
                try:
                    with open(secondary_enriched_json, "r") as f:
                        secondary_enriched_data = json.load(f)
                    logger.info(f"[Order {order_id}] Loaded {len(secondary_enriched_data)} secondary enriched PTMs")
                except Exception as sec_err:
                    logger.warning(f"[Order {order_id}] Failed to load secondary enriched JSON: {sec_err}")

            # Find secondary TSV path if not provided
            if not secondary_tsv_path and secondary_output_dir:
                sec_dir = Path(secondary_output_dir)
                sec_suffix = "_ubi" if secondary_ptm_type.startswith("ubiquit") else "_phospho"
                sec_bio_tsv = sec_dir / f"unified_protein_data_enriched_bio_enriched{sec_suffix}.tsv"
                if sec_bio_tsv.exists():
                    secondary_tsv_path = str(sec_bio_tsv)
                else:
                    sec_tsv_candidates = list(sec_dir.glob("*bio_enriched*.tsv"))
                    if sec_tsv_candidates:
                        secondary_tsv_path = str(sec_tsv_candidates[0])

            # Find secondary MD report if not provided
            if not secondary_md_path and secondary_output_dir:
                sec_dir = Path(secondary_output_dir)
                sec_md_candidates = list(sec_dir.glob("comprehensive_report*.md"))
                if sec_md_candidates:
                    secondary_md_path = str(sec_md_candidates[0])

            # Build secondary_results dict (mimicking network_results structure)
            secondary_results = {}
            if secondary_enriched_data:
                # Extract summary and timepoints from secondary enriched data
                timepoints = set()
                proteins = set()
                for item in secondary_enriched_data:
                    tp = item.get("condition") or item.get("Condition", "")
                    if tp:
                        timepoints.add(tp)
                    pg = item.get("protein_group") or item.get("Protein.Group", "")
                    if pg:
                        proteins.add(pg)
                secondary_results = {
                    "enriched_data": secondary_enriched_data,
                    "timepoints": sorted(list(timepoints)),
                    "proteins": list(proteins),
                    "summary": {
                        "total_ptms": len(secondary_enriched_data),
                        "total_proteins": len(proteins),
                        "total_timepoints": len(timepoints),
                    },
                }
                logger.info(
                    f"[Order {order_id}] Secondary results: {len(secondary_enriched_data)} PTMs, "
                    f"{len(proteins)} proteins, {len(timepoints)} timepoints"
                )

            initial_state.update({
                "secondary_results": secondary_results,
                "secondary_ptm_type": secondary_ptm_type,
                "secondary_md_content": secondary_md_path,
                "secondary_tsv_path": secondary_tsv_path,
                "primary_tsv_path": config.get("tsv_data_path", ""),
            })
            logger.info(f"[Order {order_id}] Cross-Talk state prepared: secondary_ptm_type={secondary_ptm_type}")

        # ── v9.35: LLM Pre-flight Check ──────────────────────────────
        # Verify LLM availability BEFORE starting the expensive pipeline.
        # If LLM is not reachable, fail early with a clear error message
        # instead of running the full pipeline and producing a fallback report.
        llm_provider = config.get("llm_provider", "ollama")
        llm_model = config.get("llm_model")
        try:
            from common.llm_client import LLMClient
            preflight_llm = LLMClient(provider=llm_provider, model=llm_model)
            llm_available = preflight_llm.is_available()
            llm_info = preflight_llm.get_provider_info()
            logger.info(f"[Order {order_id}] LLM pre-flight check: provider={preflight_llm.provider}, model={preflight_llm.model}, available={llm_available}")

            if not llm_available:
                error_msg = (
                    f"LLM pre-flight check FAILED: {llm_info} is not available. "
                    f"Report generation cannot proceed without a working LLM. "
                    f"Please verify: (1) Ollama is running and the model '{preflight_llm.model}' is pulled, "
                    f"or (2) Cloud API key (OPENAI_API_KEY / GEMINI_API_KEY) is configured."
                )
                logger.error(f"[Order {order_id}] {error_msg}")
                update_order_status(order_id, "failed", error_message=error_msg)
                notify_order_status(order_id, "failed", error_msg)
                publish_progress(
                    order_id, "report_generation", "llm_preflight", "failed", -1, error_msg,
                    metadata={"llm_provider": preflight_llm.provider, "llm_model": preflight_llm.model},
                )
                raise RuntimeError(error_msg)

            # Quick generation test — send a trivial prompt to confirm the model responds.
            # Retry up to 3 times: Ollama may be busy with other requests (RAG Phase B).
            test_response = None
            for _attempt in range(3):
                test_response = preflight_llm.generate("Respond with OK.", max_tokens=100)
                if test_response and not test_response.startswith("[LLM Error"):
                    break
                logger.warning(f"[Order {order_id}] LLM pre-flight attempt {_attempt + 1}/3 failed, retrying in 10s…")
                time.sleep(10)
            if test_response is None or test_response.startswith("[LLM Error"):
                error_msg = (
                    f"LLM pre-flight generation test FAILED: {llm_info} returned error. "
                    f"Response: {test_response[:200] if test_response else 'None'}. "
                    f"The model may be loading or misconfigured."
                )
                logger.error(f"[Order {order_id}] {error_msg}")
                update_order_status(order_id, "failed", error_message=error_msg)
                notify_order_status(order_id, "failed", error_msg)
                publish_progress(
                    order_id, "report_generation", "llm_preflight", "failed", -1, error_msg,
                    metadata={"llm_provider": preflight_llm.provider, "llm_model": preflight_llm.model},
                )
                raise RuntimeError(error_msg)

            logger.info(f"[Order {order_id}] LLM pre-flight check PASSED: {llm_info} responded successfully")
            publish_progress(order_id, "report_generation", "llm_preflight", "running", 1, f"LLM verified: {llm_info}")
        except RuntimeError:
            raise  # Re-raise our own pre-flight errors
        except Exception as preflight_err:
            # Non-critical: if the pre-flight check itself fails (e.g., import error),
            # log a warning but allow the pipeline to proceed
            logger.warning(f"[Order {order_id}] LLM pre-flight check could not be performed: {preflight_err}")

        # Execute LangGraph pipeline
        publish_progress(order_id, "report_generation", "graph", "started", 2, "Executing LangGraph pipeline")

        from report_generation.core.graph import build_report_graph
        graph = build_report_graph()
        final_state = graph.invoke(initial_state)

        # v11.8: Save TF inference data to signal_propagation_data (append tf_inferences key)
        _tf_inf = final_state.get("tf_inference_data") or {}
        if _tf_inf and _tf_inf.get("inferred_tfs"):
            try:
                from common.db_engine import get_engine as _get_tf_engine
                from sqlalchemy import text as _tf_text
                _spd = signal_propagation_from_db.copy() if signal_propagation_from_db else {}
                _spd["tf_inferences"] = _tf_inf
                _tf_eng = _get_tf_engine()
                with _tf_eng.connect() as _tf_conn:
                    _tf_conn.execute(
                        _tf_text(
                            "UPDATE orders SET signal_propagation_data = :spd WHERE id = :oid"
                        ),
                        {"oid": order_id, "spd": json.dumps(_spd, default=str)},
                    )
                    _tf_conn.commit()
                logger.info(
                    f"[Order {order_id}] Saved TF inference data to signal_propagation_data "
                    f"({len(_tf_inf.get('inferred_tfs', []))} TFs)"
                )
            except Exception as _tf_save_err:
                logger.warning(f"[Order {order_id}] Could not save TF inference data: {_tf_save_err}")

        # Post-process: PTM terminology + citation insertion + fake ref removal
        try:
            from common.report_postprocessor import postprocess_full_report
            # Resolve ptm_type with priority chain:
            # 1. final_state["ptm_type"] — set by context_loader after analyzing actual data
            # 2. config["experimental_context"]["ptm_type"] — from order DB
            # 3. Detect from enriched_data — scan PTM_Type field in actual data
            # 4. Default "phosphorylation"
            ptm_type_label = final_state.get("ptm_type", "").strip()
            if not ptm_type_label:
                ptm_type_label = (config.get("experimental_context") or {}).get("ptm_type", "").strip()
            if not ptm_type_label:
                # Fallback: detect from enriched data
                _ptm_counts = {}
                for _ptm in enriched_data:
                    _pt = (_ptm.get("ptm_type") or _ptm.get("PTM_Type", "phosphorylation")).lower().strip()
                    _ptm_counts[_pt] = _ptm_counts.get(_pt, 0) + 1
                if _ptm_counts:
                    ptm_type_label = max(_ptm_counts, key=_ptm_counts.get)
                    logger.info(f"[Order {order_id}] Post-process: ptm_type detected from enriched data: '{ptm_type_label}' (counts={_ptm_counts})")
                else:
                    ptm_type_label = "phosphorylation"
            logger.info(f"[Order {order_id}] Post-process: ptm_type_label='{ptm_type_label}' (source: {'final_state' if final_state.get('ptm_type') else 'config/enriched'}), report_files={final_state.get('report_files', [])}")
            logger.info(f"[Order {order_id}] Post-process: final_state.ptm_type='{final_state.get('ptm_type', 'N/A')}', config.experimental_context.ptm_type='{(config.get('experimental_context') or {}).get('ptm_type', 'N/A')}'")
            for rpt_path in final_state.get("report_files", []):
                if rpt_path and Path(rpt_path).exists() and rpt_path.endswith(".md"):
                    raw = Path(rpt_path).read_text(encoding="utf-8")
                    logger.info(f"[Order {order_id}] Post-process: raw length={len(raw)}, ptm_type='{ptm_type_label}'")
                    processed = postprocess_full_report(raw, ptm_type_label)
                    Path(rpt_path).write_text(processed, encoding="utf-8")
                    logger.info(f"[Order {order_id}] Post-processed {Path(rpt_path).name} ({len(raw)} -> {len(processed)} chars)")
                else:
                    logger.warning(f"[Order {order_id}] Post-process: skipped rpt_path='{rpt_path}' (exists={Path(rpt_path).exists() if rpt_path else 'N/A'}, endswith_md={rpt_path.endswith('.md') if rpt_path else 'N/A'})")
        except Exception as pp_err:
            logger.warning(f"[Order {order_id}] Post-processing skipped: {pp_err}")
            logger.warning(f"[Order {order_id}] Post-processing traceback:\n{traceback.format_exc()}")

        # Convert report to Word (.docx)
        try:
            from common.markdown_to_docx import convert_report_to_docx
            for rpt_path in final_state.get("report_files", []):
                if rpt_path and Path(rpt_path).exists() and rpt_path.endswith(".md"):
                    docx_out = convert_report_to_docx(rpt_path, str(order_output))
                    if docx_out:
                        logger.info(f"[Order {order_id}] Word export: {Path(docx_out).name}")
        except Exception as docx_err:
            logger.warning(f"[Order {order_id}] Word export skipped: {docx_err}")

        # Convert report to HTML (interactive: ref links, article modal, zoom, sidebar)
        try:
            from common.markdown_to_html import convert_report_to_html
            refs = final_state.get("collected_references") or []
            for rpt_path in final_state.get("report_files", []):
                if rpt_path and Path(rpt_path).exists() and rpt_path.endswith(".md"):
                    html_out = convert_report_to_html(
                        rpt_path,
                        output_dir=str(order_output),
                        references=refs,
                        api_base_url="/api",
                    )
                    if html_out:
                        logger.info(f"[Order {order_id}] HTML export: {Path(html_out).name}")
                        break
        except Exception as html_err:
            logger.warning(f"[Order {order_id}] HTML export skipped: {html_err}")

        # Collect output files
        report_files = final_state.get("report_files", [])
        output_file_names = [Path(f).name for f in report_files if f]
        for f in order_output.glob("*.docx"):
            if f.name not in output_file_names:
                output_file_names.append(f.name)
        for rpt_path in final_state.get("report_files", []):
            if rpt_path and str(rpt_path).endswith(".md"):
                html_name = Path(rpt_path).stem + ".html"
                if (order_output / html_name).exists() and html_name not in output_file_names:
                    output_file_names.append(html_name)
                break

        elapsed = round(time.time() - start_time, 1)

        # v9.35: Detect LLM fallback usage and warn user
        fallback_sections = final_state.get("llm_fallback_sections", [])
        core_sections = {"abstract", "introduction", "results", "discussion", "conclusion"}
        core_fallbacks = [s for s in fallback_sections if s in core_sections]
        llm_failed = len(core_fallbacks) >= 3  # 3+ core sections in fallback = LLM effectively failed

        if llm_failed:
            fallback_warning = (
                f"WARNING: LLM failed for {len(core_fallbacks)}/{len(core_sections)} core sections "
                f"({', '.join(core_fallbacks)}). The report contains placeholder text instead of "
                f"AI-generated analysis. Please check LLM availability and re-run report generation."
            )
            logger.warning(f"[Order {order_id}] {fallback_warning}")
        elif fallback_sections:
            fallback_warning = (
                f"Partial LLM fallback: {len(fallback_sections)} section(s) used placeholder text "
                f"({', '.join(fallback_sections)}). Other sections were generated successfully."
            )
            logger.warning(f"[Order {order_id}] {fallback_warning}")
        else:
            fallback_warning = None

        # v10.0: Persist RQ refinement metadata + copilot review as log events
        rq_meta = final_state.get("rq_refinement_metadata") or {}
        if rq_meta and not rq_meta.get("skipped"):
            publish_analysis_log(
                order_id,
                f"[rq_refinement] Refined {rq_meta.get('original_count', 0)} → {rq_meta.get('refined_count', 0)} questions",
                stage="report_generation", step="rq_refinement", status="done",
                metadata={
                    "type": "rq_refinement",
                    "original_questions": final_state.get("original_research_questions", []),
                    "refined_questions": final_state.get("research_questions", []),
                    "refined_items": rq_meta.get("refined_items", []),
                    "key_discovery": rq_meta.get("key_discovery", ""),
                    "suggested_experiments": rq_meta.get("suggested_experiments", []),
                },
                persist=True,
            )
        copilot_review = final_state.get("copilot_review") or {}
        if copilot_review and not copilot_review.get("skipped"):
            publish_analysis_log(
                order_id,
                f"[report_copilot] Review: {copilot_review.get('overall_quality', 'N/A')}",
                stage="report_generation", step="report_copilot", status="done",
                metadata={
                    "type": "report_copilot",
                    "overall_quality": copilot_review.get("overall_quality"),
                    "section_reviews": copilot_review.get("section_reviews", []),
                    "missing_connections": copilot_review.get("missing_connections", []),
                    "literature_suggestions": copilot_review.get("literature_suggestions", []),
                },
                persist=True,
            )

        progress_metadata = {
            "output_files": output_file_names,
            "elapsed_seconds": elapsed,
            "sections_generated": len(final_state.get("sections", {})),
            "hypotheses_count": len(final_state.get("validated_hypotheses", [])),
            "cytoscape_connected": final_state.get("network_analysis", {}).get("cytoscape_connected", False),
        }
        temporal_fidelity = final_state.get("temporal_report_fidelity") or {}
        temporal_packet = final_state.get("temporal_report_evidence_packet") or {}
        temporal_review_sections = [
            section for section, audit in temporal_fidelity.items()
            if isinstance(audit, dict) and audit.get("status") == "review_required"
        ]
        temporal_llm_draft_review_sections = [
            section for section, audit in temporal_fidelity.items()
            if isinstance(audit, dict) and audit.get("llm_draft_status") == "review_required"
        ]
        temporal_llm_draft_untraced_sections = [
            section for section, audit in temporal_fidelity.items()
            if isinstance(audit, dict) and audit.get("llm_draft_status") == "untraced"
        ]
        progress_metadata["temporal_evidence"] = {
            "packet_status": temporal_packet.get("status", "unavailable"),
            "record_count": temporal_packet.get("record_count", 0),
            "section_status": {
                section: audit.get("status")
                for section, audit in temporal_fidelity.items()
                if isinstance(audit, dict)
            },
            "llm_draft_section_status": {
                section: audit.get("llm_draft_status", audit.get("status"))
                for section, audit in temporal_fidelity.items()
                if isinstance(audit, dict)
            },
            "review_required_sections": temporal_review_sections,
            "llm_draft_review_required_sections": temporal_llm_draft_review_sections,
            "llm_draft_untraced_sections": temporal_llm_draft_untraced_sections,
            "deterministic_addendum_sections": [
                section for section, audit in temporal_fidelity.items()
                if isinstance(audit, dict) and audit.get("deterministic_addendum_applied")
            ],
            "packet_snapshot": temporal_packet.get("snapshot_path"),
            "fidelity_snapshot": final_state.get("temporal_report_fidelity_snapshot"),
        }
        if fallback_sections:
            progress_metadata["llm_fallback_sections"] = fallback_sections
            progress_metadata["llm_fallback_warning"] = fallback_warning

        publish_progress(
            order_id, "report_generation", "finalization", "completed", 100,
            f"Report generation complete ({elapsed}s)",
            metadata=progress_metadata,
        )

        all_output_files = [f.name for f in order_output.iterdir() if f.is_file() and f.suffix in (".md", ".docx", ".html", ".json", ".tsv", ".txt", ".png")]
        result_data = {
            "report_files": output_file_names,
            "all_files": all_output_files,
            "output_dir": str(order_output),
        }
        if fallback_sections:
            result_data["llm_fallback_sections"] = fallback_sections
            result_data["llm_fallback_warning"] = fallback_warning
        result_data["temporal_evidence"] = progress_metadata["temporal_evidence"]

        # Persist external Co-Scientist packet telemetry for Order UI / operators.
        try:
            from report_generation.core.nodes.external_coscientist_node import (
                build_integration_telemetry,
                write_integration_telemetry,
            )
            telemetry = build_integration_telemetry(final_state)
            telemetry_path = write_integration_telemetry({**final_state, "output_dir": str(order_output)})
            if telemetry_path:
                telemetry["status_file"] = Path(telemetry_path).name
            result_data["co_scientist_integration_result"] = telemetry
            if telemetry.get("status") and telemetry["status"] not in {"disabled"}:
                logger.info(
                    "[Order %s] Co-Scientist integration status=%s warning=%s eligible=%s",
                    order_id,
                    telemetry.get("status"),
                    telemetry.get("warning"),
                    telemetry.get("eligible_hypotheses"),
                )
        except Exception as telemetry_err:
            logger.warning("[Order %s] Could not persist Co-Scientist telemetry: %s", order_id, telemetry_err)

        # v9.35: If LLM effectively failed, mark as completed_with_warnings instead of completed
        completion_detail = f"Report generation complete ({elapsed}s)"
        if temporal_review_sections:
            completion_detail += f"; temporal evidence review required: {', '.join(temporal_review_sections)}"
        elif temporal_llm_draft_review_sections or temporal_llm_draft_untraced_sections:
            repaired_sections = temporal_llm_draft_review_sections + temporal_llm_draft_untraced_sections
            completion_detail += f"; deterministic temporal evidence addendum applied: {', '.join(repaired_sections)}"
        if llm_failed:
            update_order_status(
                order_id, "completed", progress_pct=100, result_files=result_data,
                error_message=fallback_warning,
                current_stage="completed",
                stage_detail=completion_detail,
            )
            notify_order_status(order_id, "completed", fallback_warning)
            logger.warning(
                f"[Order {order_id}] Report completed WITH WARNINGS in {elapsed}s — "
                f"LLM fallback used for {len(core_fallbacks)} core sections"
            )
        else:
            update_order_status(
                order_id, "completed", progress_pct=100, result_files=result_data,
                current_stage="completed",
                stage_detail=completion_detail,
            )
            notify_order_status(order_id, "completed")
            logger.info(f"[Order {order_id}] Report generation completed in {elapsed}s — {len(output_file_names)} files")

        send_step_webhook(order_id, "report_generation", "completed")
        send_step_webhook(order_id, "order", "completed")

        return {
            "order_id": order_id,
            "status": "completed",
            "elapsed_seconds": elapsed,
            "output_dir": str(order_output),
            "output_files": output_file_names,
        }

    except RunSuperseded:
        logger.info(f"[Order {order_id}] Report generation stopped — run superseded")
        return {"order_id": order_id, "status": "skipped", "reason": "superseded"}
    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        error_msg = f"Report generation failed: {str(e)}"
        logger.error(f"[Order {order_id}] {error_msg}", exc_info=True)
        update_order_status(order_id, "failed", error_message=error_msg)
        notify_order_status(order_id, "failed", error_msg)
        publish_progress(
            order_id, "report_generation", "error", "failed", -1, error_msg,
            metadata={"traceback": traceback.format_exc(), "elapsed_seconds": elapsed},
        )
        raise
    finally:
        try:
            lock_client.delete(lock_key)
        except Exception:
            pass
