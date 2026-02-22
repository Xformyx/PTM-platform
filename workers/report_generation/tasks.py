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

from celery_app import app
from common.db_update import update_order_status
from common.progress import publish_progress

logger = logging.getLogger("ptm-workers.report-generation")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/outputs")


def _make_progress_cb(order_id):
    def cb(pct, msg):
        publish_progress(order_id, "report_generation", "graph", "running", round(pct, 1), msg)
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
    start_time = time.time()
    order_code = config.get("order_code") or str(order_id)
    order_output = Path(OUTPUT_DIR) / order_code
    order_output.mkdir(parents=True, exist_ok=True)

    update_order_status(order_id, "report_generation", current_stage="report_generation", progress_pct=0)
    logger.info(f"[Order {order_id}] Report generation started")
    publish_progress(order_id, "report_generation", "start", "started", 0, "Report generation pipeline started")

    try:
        # Resolve enriched data path
        rag_dir = Path(config.get("rag_output_dir", str(order_output)))
        enriched_path = config.get("enriched_json_path")
        if not enriched_path:
            candidates = list(rag_dir.glob("enriched_ptm_data_*.json"))
            if candidates:
                enriched_path = str(candidates[0])
            else:
                raise FileNotFoundError(f"No enriched PTM JSON found in {rag_dir}")

        # Load enriched data
        with open(enriched_path, "r") as f:
            enriched_data = json.load(f)
        logger.info(f"[Order {order_id}] Loaded {len(enriched_data)} enriched PTMs from {enriched_path}")

        # Build initial state
        initial_state = {
            "order_id": order_id,
            "enriched_ptm_data": enriched_data,
            "enriched_json_path": enriched_path,
            "md_report_path": config.get("md_report_path", ""),
            "tsv_data_path": config.get("tsv_data_path", ""),
            "experimental_context": config.get("experimental_context") or {},
            "research_questions": config.get("research_questions", []),
            "chromadb_collections": config.get("chromadb_collections", []),
            "output_dir": str(order_output),
            "llm_provider": config.get("llm_provider", "ollama"),
            "llm_model": config.get("llm_model"),
            "report_title": config.get("report_title", "PTM Comprehensive Analysis Report"),
            "report_type": config.get("report_type", "comprehensive"),
            "progress_callback": _make_progress_cb(order_id),
        }

        # Execute LangGraph pipeline
        publish_progress(order_id, "report_generation", "graph", "started", 2, "Executing LangGraph pipeline")

        from report_generation.core.graph import build_report_graph
        graph = build_report_graph()
        final_state = graph.invoke(initial_state)

        # Post-process: PTM terminology + citation insertion + fake ref removal
        try:
            from common.report_postprocessor import postprocess_full_report
            ptm_type_label = (config.get("experimental_context") or {}).get("ptm_type", "phosphorylation")
            for rpt_path in final_state.get("report_files", []):
                if rpt_path and Path(rpt_path).exists() and rpt_path.endswith(".md"):
                    raw = Path(rpt_path).read_text(encoding="utf-8")
                    processed = postprocess_full_report(raw, ptm_type_label)
                    Path(rpt_path).write_text(processed, encoding="utf-8")
                    logger.info(f"[Order {order_id}] Post-processed {Path(rpt_path).name}")
        except Exception as pp_err:
            logger.warning(f"[Order {order_id}] Post-processing skipped: {pp_err}")

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

        # Collect output files
        report_files = final_state.get("report_files", [])
        output_file_names = [Path(f).name for f in report_files if f]
        for f in order_output.glob("*.docx"):
            if f.name not in output_file_names:
                output_file_names.append(f.name)

        elapsed = round(time.time() - start_time, 1)

        publish_progress(
            order_id, "report_generation", "finalization", "completed", 100,
            f"Report generation complete ({elapsed}s)",
            metadata={
                "output_files": output_file_names,
                "elapsed_seconds": elapsed,
                "sections_generated": len(final_state.get("sections", {})),
                "hypotheses_count": len(final_state.get("validated_hypotheses", [])),
                "cytoscape_connected": final_state.get("network_analysis", {}).get("cytoscape_connected", False),
            },
        )

        all_output_files = [f.name for f in order_output.iterdir() if f.is_file() and f.suffix in (".md", ".docx", ".json", ".tsv", ".txt", ".png")]
        result_data = {
            "report_files": output_file_names,
            "all_files": all_output_files,
            "output_dir": str(order_output),
        }
        update_order_status(order_id, "completed", progress_pct=100, result_files=result_data)
        logger.info(f"[Order {order_id}] Report generation completed in {elapsed}s — {len(output_file_names)} files")

        return {
            "order_id": order_id,
            "status": "completed",
            "elapsed_seconds": elapsed,
            "output_dir": str(order_output),
            "output_files": output_file_names,
        }

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        error_msg = f"Report generation failed: {str(e)}"
        logger.error(f"[Order {order_id}] {error_msg}", exc_info=True)
        update_order_status(order_id, "failed", error_message=error_msg)
        publish_progress(
            order_id, "report_generation", "error", "failed", -1, error_msg,
            metadata={"traceback": traceback.format_exc(), "elapsed_seconds": elapsed},
        )
        raise
