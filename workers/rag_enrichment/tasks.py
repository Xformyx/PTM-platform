"""
Stage 2: RAG Enrichment Pipeline — Celery Task.

Takes preprocessing TSV output and enriches each PTM site with:
  1. PubMed literature search (multi-tier, via MCP)
  2. Pattern-based regulation extraction (no LLM)
  3. KEGG / STRING / UniProt annotations (via MCP)
  4. Comprehensive MD report generation
"""

import json
import logging
import os
import time
import traceback
from pathlib import Path

import pandas as pd

from celery_app import app
from common.db_update import get_order_status, update_order_status
from common.mcp_client import MCPClient
from common.progress import publish_progress

logger = logging.getLogger("ptm-workers.rag-enrichment")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/outputs")


def _make_progress_cb(order_id, stage, step, base, span):
    def cb(frac, msg):
        pct = base + frac * span
        publish_progress(order_id, stage, step, "running", round(pct, 1), msg)
    return cb


@app.task(bind=True, name="rag_enrichment.tasks.run_rag_enrichment", max_retries=1)
def run_rag_enrichment(self, order_id: int, config: dict):
    """
    Stage 2: RAG Enrichment Pipeline.

    config keys:
      - preprocessing_output_dir: str   (absolute path to Stage 1 output)
      - ptm_mode: 'phospho' | 'ubi'
      - experimental_context: dict      (optional: tissue, treatment, keywords, etc.)
      - max_articles_per_ptm: int       (default 15)
      - top_n_ptms: int                 (default 50 — limit to most significant PTMs)
    """
    start_time = time.time()
    order_code = config.get("order_code") or str(order_id)
    order_output = Path(OUTPUT_DIR) / order_code
    order_output.mkdir(parents=True, exist_ok=True)

    update_order_status(order_id, "rag_enrichment", current_stage="rag_enrichment", progress_pct=0)
    logger.info(f"[Order {order_id}] RAG enrichment started")
    publish_progress(order_id, "rag_enrichment", "start", "started", 0, "RAG enrichment pipeline started")

    try:
        preprocessing_dir = Path(config.get("preprocessing_output_dir", str(order_output)))
        ptm_mode = config.get("ptm_mode", "phospho")
        experimental_context = config.get("experimental_context")
        top_n = config.get("top_n_ptms", 50)
        file_suffix = "_phospho" if ptm_mode == "phospho" else "_ubi"

        # ================================================================
        # Step 1: Load PTM vector data from preprocessing output (0% – 10%)
        # ================================================================
        publish_progress(order_id, "rag_enrichment", "load_data", "started", 2, "Loading PTM vector data")

        vector_file = preprocessing_dir / f"ptm_vector_data_normalized{file_suffix}.tsv"
        if not vector_file.exists():
            vector_file = preprocessing_dir / f"ptm_vector_data_with_motifs{file_suffix}.tsv"
        if not vector_file.exists():
            raise FileNotFoundError(f"PTM vector file not found in {preprocessing_dir}")

        df = pd.read_csv(vector_file, sep="\t", low_memory=False)
        logger.info(f"[Order {order_id}] Loaded {len(df)} PTM entries from {vector_file.name}")

        # Select top-N most significant PTMs per condition (time-point),
        # then take the union across all conditions.
        # This ensures each time-point contributes its top PTMs and the
        # final set contains >= N unique gene+position combinations.
        gene_col = "Gene.Name" if "Gene.Name" in df.columns else "gene"
        pos_col = "PTM_Position" if "PTM_Position" in df.columns else "position"
        cond_col = "Condition" if "Condition" in df.columns else "condition"
        fc_col = "PTM_Relative_Log2FC" if "PTM_Relative_Log2FC" in df.columns else "ptm_relative_log2fc"

        if fc_col in df.columns and cond_col in df.columns:
            df["_abs_fc"] = df[fc_col].abs()
            conditions = df[cond_col].dropna().unique()
            selected_keys = set()  # set of (gene, position) tuples

            for cond in conditions:
                cond_df = df[df[cond_col] == cond].sort_values("_abs_fc", ascending=False)
                for _, row in cond_df.head(top_n).iterrows():
                    key = (str(row.get(gene_col, "")), str(row.get(pos_col, "")))
                    selected_keys.add(key)

            # Keep all rows (all conditions) for the selected gene+position pairs
            df["_key"] = list(zip(df[gene_col].astype(str), df[pos_col].astype(str)))
            df = df[df["_key"].isin(selected_keys)]
            df = df.drop(columns=["_abs_fc", "_key"])

            n_unique = len(selected_keys)
            logger.info(
                f"[Order {order_id}] Top N selection: {top_n} per condition "
                f"x {len(conditions)} conditions → {n_unique} unique PTMs, "
                f"{len(df)} total rows"
            )
        elif fc_col in df.columns:
            # Fallback: no Condition column — simple top-N by abs FC
            df["_abs_fc"] = df[fc_col].abs()
            df = df.sort_values("_abs_fc", ascending=False).head(top_n)
            df = df.drop(columns=["_abs_fc"])
            n_unique = top_n
        else:
            n_unique = len(df)

        ptm_data = df.to_dict("records")
        publish_progress(order_id, "rag_enrichment", "load_data", "completed", 10,
                        f"Loaded {len(ptm_data)} PTM entries ({n_unique} unique PTMs from top {top_n}/condition)")

        # ================================================================
        # Step 2: RAG Enrichment — PubMed + pattern matching (10% – 70%)
        # ================================================================
        publish_progress(order_id, "rag_enrichment", "enrichment", "started", 10, "Starting literature enrichment")

        from rag_enrichment.core.enrichment_pipeline import RAGEnrichmentPipeline

        mcp = MCPClient()
        enrich_cb = _make_progress_cb(order_id, "rag_enrichment", "enrichment", 10, 60)

        rag_llm_model = config.get("rag_llm_model")
        pipeline = RAGEnrichmentPipeline(
            mcp_client=mcp,
            progress_callback=enrich_cb,
            rag_llm_model=rag_llm_model,
            llm_provider=config.get("llm_provider", "ollama"),
            llm_model=config.get("llm_model"),
        )

        enriched_ptms = pipeline.enrich_ptm_data(
            ptm_data=ptm_data,
            experimental_context=experimental_context,
        )

        # Save enriched data as JSON
        enriched_json_path = order_output / f"enriched_ptm_data{file_suffix}.json"
        with open(enriched_json_path, "w", encoding="utf-8") as f:
            json.dump(enriched_ptms, f, indent=2, default=str)
        logger.info(f"[Order {order_id}] Saved enriched data: {enriched_json_path.name}")

        publish_progress(order_id, "rag_enrichment", "enrichment", "completed", 70, "Literature enrichment complete")

        # ================================================================
        # Step 3: MD Report Generation (70% – 95%)
        # ================================================================
        publish_progress(order_id, "rag_enrichment", "report_generation", "started", 70, "Generating MD report")

        from rag_enrichment.core.report_generator import ComprehensiveReportGenerator

        generator = ComprehensiveReportGenerator(experimental_context=experimental_context)
        report_md = generator.generate_full_report(enriched_ptms)

        md_path = order_output / f"comprehensive_report{file_suffix}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        logger.info(f"[Order {order_id}] Saved report: {md_path.name}")

        publish_progress(order_id, "rag_enrichment", "report_generation", "completed", 95, "MD report generated")

        # ================================================================
        # Step 4: Finalization (95% – 100%)
        # ================================================================
        elapsed = round(time.time() - start_time, 1)
        output_files = [f.name for f in order_output.iterdir() if f.suffix in (".json", ".md")]

        publish_progress(
            order_id, "rag_enrichment", "finalization", "completed", 100,
            f"RAG enrichment complete ({elapsed}s, {len(output_files)} files)",
            metadata={"output_files": output_files, "elapsed_seconds": elapsed,
                      "ptms_enriched": len(enriched_ptms)},
        )

        logger.info(f"[Order {order_id}] RAG enrichment completed in {elapsed}s")
        mcp.close()

        # Chain to Stage 3: Report Generation
        report_config = {
            "order_code": order_code,
            "rag_output_dir": str(order_output),
            "enriched_json_path": str(enriched_json_path),
            "md_report_path": str(md_path),
            "experimental_context": experimental_context,
            "research_questions": config.get("research_questions", []),
            "chromadb_collections": config.get("chromadb_collections", []),
            "llm_provider": config.get("llm_provider", "ollama"),
            "llm_model": config.get("llm_model"),
            "report_title": config.get("report_title", "PTM Comprehensive Analysis Report"),
        }
        if config.get("chain_to_next", True) and get_order_status(order_id) != "cancelled":
            app.send_task(
                "report_generation.tasks.run_report_generation",
                args=[order_id, report_config],
                queue="report_generation",
            )
            logger.info(f"[Order {order_id}] Chained to report generation")
        else:
            logger.info(f"[Order {order_id}] RAG complete (no chain — re-run only)")

        return {
            "order_id": order_id,
            "status": "completed",
            "elapsed_seconds": elapsed,
            "output_dir": str(order_output),
            "output_files": output_files,
            "ptms_enriched": len(enriched_ptms),
            "next_stage": "report_generation",
        }

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        error_msg = f"RAG enrichment failed: {str(e)}"
        logger.error(f"[Order {order_id}] {error_msg}", exc_info=True)
        update_order_status(order_id, "failed", error_message=error_msg)
        publish_progress(
            order_id, "rag_enrichment", "error", "failed", -1, error_msg,
            metadata={"traceback": traceback.format_exc(), "elapsed_seconds": elapsed},
        )
        raise
