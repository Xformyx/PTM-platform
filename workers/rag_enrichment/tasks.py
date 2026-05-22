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
import threading
import time
import traceback
from pathlib import Path

import pandas as pd

from celery_app import app
from common.db_update import get_order_status, update_order_status
from common.notifications import notify_order_status
from common.mcp_client import MCPClient
from common.progress import publish_analysis_log, publish_progress
from common.webhook import send_step_webhook

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
      - ptm_selection_mode: str         (default 'top_n' — PTM selection strategy)
          'top_n'            : legacy behaviour — rank by max |FC|, take top_n
          'de_novo'          : only Control_Pseudocount_Used == True PTMs
          'regulated'        : only q_value < 0.05 AND |Log2FC| >= 1.0 PTMs
          'de_novo_regulated': de_novo UNION regulated
          'minor'            : PTMs that are neither de_novo nor regulated
          'all'              : all PTMs (no limit)
      - top_n_ptms: int                 (default 50 — used only when mode is 'top_n')
    """
    start_time = time.time()
    order_code = config.get("order_code") or str(order_id)
    order_output = Path(OUTPUT_DIR) / order_code
    order_output.mkdir(parents=True, exist_ok=True)

    update_order_status(order_id, "rag_enrichment", current_stage="rag_enrichment", progress_pct=0,
                        stage_detail="RAG enrichment started")

    # Clear stale ptm_phase/ptm_list logs from previous runs so the UI starts clean
    try:
        from common.db_engine import get_engine as _get_engine
        from sqlalchemy import text as _text
        _eng = _get_engine()
        with _eng.connect() as _conn:
            _conn.execute(
                _text(
                    "DELETE FROM order_logs WHERE order_id = :oid "
                    "AND stage = 'rag_enrichment' AND step = 'ptm_phase'"
                ),
                {"oid": order_id},
            )
            _conn.commit()
        logger.info(f"[Order {order_id}] Cleared previous ptm_phase logs")
    except Exception as _del_err:
        logger.warning(f"[Order {order_id}] Could not clear old ptm_phase logs: {_del_err}")

    logger.info(f"[Order {order_id}] RAG enrichment started")
    publish_progress(order_id, "rag_enrichment", "start", "started", 0, "RAG enrichment pipeline started")

    try:
        preprocessing_dir = Path(config.get("preprocessing_output_dir", str(order_output)))
        ptm_mode = config.get("ptm_mode", "phospho")
        single_time_point = config.get("single_time_point", False)
        experimental_context = dict(config.get("experimental_context") or {})
        experimental_context["single_time_point"] = single_time_point
        top_n = config.get("top_n_ptms", 50)
        ptm_selection_mode = config.get("ptm_selection_mode", "top_n")
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

        # Select PTMs based on ptm_selection_mode.
        # Modes: top_n | de_novo | regulated | de_novo_regulated | minor | all
        # Legacy classification mode also supported via use_classification_selection flag.
        use_classification = config.get("use_classification_selection", False)

        gene_col = "Gene.Name" if "Gene.Name" in df.columns else "gene"
        pos_col = "PTM_Position" if "PTM_Position" in df.columns else "position"
        cond_col = "Condition" if "Condition" in df.columns else "condition"
        fc_col = "PTM_Relative_Log2FC" if "PTM_Relative_Log2FC" in df.columns else "ptm_relative_log2fc"

        if use_classification and fc_col in df.columns:
            # Classification-based selection (ported from ptm-vector-ai)
            from rag_enrichment.core.enrichment_pipeline import RAGEnrichmentPipeline
            all_ptm_records = df.to_dict("records")
            conditions_list = sorted(df[cond_col].dropna().unique().tolist()) if cond_col in df.columns else None
            classified_ptms = RAGEnrichmentPipeline.select_ptms_by_classification(
                ptm_data=all_ptm_records,
                conditions=conditions_list,
                include_high=True,
                include_moderate=True,
                include_low=False,
                top_n=top_n,
            )
            # Get keys of selected PTMs and filter df to keep all condition rows
            selected_keys = set()
            for p in classified_ptms:
                g = p.get("gene") or p.get("Gene.Name", "?")
                s = p.get("position") or p.get("PTM_Position", "?")
                selected_keys.add((str(g), str(s)))

            df["_key"] = list(zip(df[gene_col].astype(str), df[pos_col].astype(str)))
            df = df[df["_key"].isin(selected_keys)]
            df = df.drop(columns=["_key"])
            n_unique = len(selected_keys)

            # Count by significance
            sig_counts = {}
            for p in classified_ptms:
                sig = p.get("classification", {}).get("significance", "?")
                sig_counts[sig] = sig_counts.get(sig, 0) + 1
            logger.info(
                f"[Order {order_id}] Classification selection: {n_unique} unique PTMs "
                f"(High={sig_counts.get('High', 0)}, Moderate={sig_counts.get('Moderate', 0)}, "
                f"Low={sig_counts.get('Low', 0)}), {len(df)} total rows"
            )

        elif fc_col in df.columns and cond_col in df.columns:
            import numpy as _np
            df["_abs_fc"] = df[fc_col].abs()
            conditions = df[cond_col].dropna().unique()
            df["_key"] = list(zip(df[gene_col].astype(str), df[pos_col].astype(str)))

            # ── v9.26: PTM Selection Mode ──────────────────────────────────────
            # Modes: top_n | de_novo | regulated | de_novo_regulated | minor | all
            # -----------------------------------------------------------------
            pc_col = "Control_Pseudocount_Used" if "Control_Pseudocount_Used" in df.columns else None
            q_col  = "q_value" if "q_value" in df.columns else None

            # Per-PTM aggregates
            key_max_fc = df.groupby("_key")["_abs_fc"].max()
            key_denovo = df.groupby("_key")[pc_col].any() if pc_col else None
            key_min_q  = df.groupby("_key")[q_col].min() if q_col else None

            # Classify every unique PTM key
            denovo_keys: set = set()
            regulated_keys: set = set()
            minor_keys: set = set()

            # ── 2-pass regulated classification ──────────────────────────────
            # Pass 1: Strict criteria (q_value < 0.05 AND |FC| >= 1.0)
            # Pass 2: If Pass 1 yields 0 regulated, relax to |FC| >= 0.8 only
            # This handles datasets where BH correction is too conservative
            # (all q_values > 0.05) while preserving q_value when available.
            # ─────────────────────────────────────────────────────────────────
            non_denovo_keys: list = []
            for k in key_max_fc.index:
                is_denovo = bool(key_denovo is not None and key_denovo.get(k, False))
                if is_denovo:
                    denovo_keys.add(k)
                    continue  # De novo PTMs are never also Regulated
                non_denovo_keys.append(k)

            # Pass 1: strict q_value-based classification
            for k in non_denovo_keys:
                fc_val = key_max_fc.get(k, 0.0)
                is_regulated = False
                if key_min_q is not None:
                    q_val = key_min_q.get(k)
                    if q_val is not None and not _np.isnan(float(q_val)) and float(q_val) < 0.05 and fc_val >= 1.0:
                        is_regulated = True
                else:
                    # No q_value column at all — use |FC| >= 0.8
                    if fc_val >= 0.8:
                        is_regulated = True
                if is_regulated:
                    regulated_keys.add(k)
                else:
                    minor_keys.add(k)

            # Pass 2: if q_value column exists but yielded 0 regulated,
            # re-classify using |FC| >= 0.8 as fallback threshold
            if key_min_q is not None and len(regulated_keys) == 0 and len(non_denovo_keys) > 0:
                logger.info(
                    f"[Order {order_id}] Pass 1 (q<0.05 + |FC|>=1.0) yielded 0 regulated PTMs. "
                    f"Applying Pass 2 fallback: |FC| >= 0.8 for {len(non_denovo_keys)} non-de_novo PTMs."
                )
                regulated_keys = set()
                minor_keys = set()
                for k in non_denovo_keys:
                    fc_val = key_max_fc.get(k, 0.0)
                    if fc_val >= 0.8:
                        regulated_keys.add(k)
                    else:
                        minor_keys.add(k)
                logger.info(
                    f"[Order {order_id}] Pass 2 result: {len(regulated_keys)} regulated, "
                    f"{len(minor_keys)} minor PTMs."
                )

            # Apply selection based on mode
            mode = ptm_selection_mode
            if mode == "all":
                selected_keys = set(key_max_fc.index.tolist())
                fill_keys: set = set()
            elif mode == "de_novo":
                selected_keys = denovo_keys
                fill_keys = set()
            elif mode == "regulated":
                selected_keys = regulated_keys
                fill_keys = set()
            elif mode == "de_novo_regulated":
                selected_keys = denovo_keys | regulated_keys
                fill_keys = set()
            elif mode == "minor":
                selected_keys = minor_keys
                fill_keys = set()
            else:
                # Default: 'top_n' — De novo + Regulated guaranteed, fill remainder
                priority_keys = denovo_keys | regulated_keys
                remaining_slots = max(0, top_n - len(priority_keys))
                remaining_sorted = key_max_fc.drop(index=list(priority_keys), errors="ignore") \
                                             .sort_values(ascending=False)
                fill_keys = set(remaining_sorted.head(remaining_slots).index.tolist())
                selected_keys = priority_keys | fill_keys

            # Fallback: if mode-based selection yields nothing, fall back to top_n
            if not selected_keys:
                logger.warning(
                    f"[Order {order_id}] ptm_selection_mode='{mode}' yielded 0 PTMs "
                    f"(q_value data available: {q_col is not None}). "
                    f"Falling back to top_{top_n} by |FC|."
                )
                fill_keys = set(key_max_fc.sort_values(ascending=False).head(top_n).index.tolist())
                selected_keys = fill_keys

            # Keep all rows (all conditions) for the selected gene+position pairs
            df = df[df["_key"].isin(selected_keys)]
            df = df.drop(columns=["_abs_fc", "_key"])

            n_unique = len(selected_keys)
            _total_unique = len(key_max_fc.index)
            logger.info(
                f"[Order {order_id}] [RAG-SELECT] "
                f"mode='{mode}' | "
                f"전체 unique PTM={_total_unique} | "
                f"De novo={len(denovo_keys)}, Regulated={len(regulated_keys)}, Minor={len(minor_keys)} | "
                f"선택됨={n_unique} unique PTMs ({len(df)} rows, {len(conditions)} conditions) | "
                f"top_n_setting={top_n} (mode!=top_n 이면 무시됨)"
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
                        f"[{n_unique} PTMs selected, {len(ptm_data)} rows] mode='{ptm_selection_mode}' → enrichment 시작")

        # ================================================================
        # Step 2: RAG Enrichment — PubMed + pattern matching (10% – 70%)
        # ================================================================
        publish_progress(order_id, "rag_enrichment", "enrichment", "started", 10, "Starting literature enrichment")
        send_step_webhook(order_id, "rag_enrichment", "started")

        from rag_enrichment.core.enrichment_pipeline import RAGEnrichmentPipeline

        mcp = MCPClient()
        enrich_cb = _make_progress_cb(order_id, "rag_enrichment", "enrichment", 10, 60)

        def _analysis_log(msg: str, metadata: dict | None = None, *, persist: bool = False) -> None:
            publish_analysis_log(order_id, msg, metadata=metadata, persist=persist)

        rag_llm_model = config.get("rag_llm_model")
        rag_llm_provider = config.get("rag_llm_provider")
        report_llm_provider = config.get("llm_provider", "ollama")

        def _env_bool(name: str, default: bool = True) -> bool:
            return os.getenv(name, "true" if default else "false").lower() not in ("false", "0", "no")

        pipeline = RAGEnrichmentPipeline(
            mcp_client=mcp,
            progress_callback=enrich_cb,
            analysis_log=_analysis_log,
            enable_llm_analysis=_env_bool("RAG_ENABLE_LLM", default=True),
            rag_enrichment_llm_model=config.get("rag_enrichment_llm_model"),
            rag_enrichment_llm_provider=config.get("rag_enrichment_llm_provider"),
            rag_llm_model=rag_llm_model,
            rag_llm_provider=rag_llm_provider,
            llm_provider=report_llm_provider,
            llm_model=config.get("llm_model"),
        )

        # Cancellation: poll DB every 5 s; set event when order becomes cancelled.
        cancel_event = threading.Event()

        def _cancellation_poller():
            while not cancel_event.is_set():
                try:
                    if get_order_status(order_id) == "cancelled":
                        cancel_event.set()
                        logger.info(f"[Order {order_id}] cancellation detected — signalling pipeline to stop")
                        break
                except Exception:
                    pass
                time.sleep(1)

        _poll_thread = threading.Thread(target=_cancellation_poller, daemon=True, name=f"cancel_poll_{order_id}")
        _poll_thread.start()

        enriched_ptms = pipeline.enrich_ptm_data(
            ptm_data=ptm_data,
            experimental_context=experimental_context,
            cancel_event=cancel_event,
        )

        # Stop the poller once the pipeline finishes (normal or early exit).
        cancel_event.set()

        # Do not continue to MD report / webhooks / chain if the user cancelled (cancel_event is always set here).
        if get_order_status(order_id) == "cancelled":
            logger.info(
                f"[Order {order_id}] RAG enrichment stopped by user — skipping MD report, finalization, and chain"
            )
            try:
                mcp.close()
            except Exception:
                pass
            return {
                "order_id": order_id,
                "status": "cancelled",
                "elapsed_seconds": round(time.time() - start_time, 1),
                "message": "Stopped by user",
            }

        # Save enriched data as JSON
        enriched_json_path = order_output / f"enriched_ptm_data{file_suffix}.json"
        with open(enriched_json_path, "w", encoding="utf-8") as f:
            json.dump(enriched_ptms, f, indent=2, default=str)

        # ── Logging: JSON 저장 결과 ──────────────────────────────────────────
        _json_unique_keys = set()
        for _item in enriched_ptms:
            _g = _item.get("Gene.Name", "") or _item.get("gene", "")
            _s = _item.get("PTM_Position", "") or _item.get("position", "")
            if _g and _s:
                _json_unique_keys.add(f"{_g}_{_s}")
        logger.info(
            f"[Order {order_id}] [RAG-SAVE] "
            f"JSON: {enriched_json_path.name} | "
            f"total rows={len(enriched_ptms)}, unique PTMs={len(_json_unique_keys)}"
        )

        publish_progress(order_id, "rag_enrichment", "enrichment", "completed", 70, "Literature enrichment complete")

        # ================================================================
        # Step 3: MD Report Generation (70% – 95%)
        # ================================================================
        publish_progress(order_id, "rag_enrichment", "report_generation", "started", 70, "Generating MD report")

        from rag_enrichment.core.report_generator import ComprehensiveReportGenerator
        from rag_enrichment.core.ptm_merger import merge_multi_condition_ptms

        # Merge multi-condition rows into unified PTM entries
        # When single_time_point, conditions are not treated as timepoints (no trajectory)
        merged_ptms = merge_multi_condition_ptms(enriched_ptms, single_time_point=single_time_point)
        logger.info(
            f"[Order {order_id}] Merged {len(enriched_ptms)} rows -> "
            f"{len(merged_ptms)} unique PTMs (multi-condition merged)"
        )

        generator = ComprehensiveReportGenerator(experimental_context=experimental_context)
        report_md = generator.generate_full_report(merged_ptms)

        md_path = order_output / f"comprehensive_report{file_suffix}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        logger.info(f"[Order {order_id}] Saved report: {md_path.name}")

        publish_progress(order_id, "rag_enrichment", "report_generation", "completed", 90, "MD report generated")

        # ================================================================
        # Step 3.5: Secondary PTM enrichment for Cross-Talk mode (90% – 95%)
        # ================================================================
        analysis_mode = config.get("analysis_mode", "ptm_only")
        secondary_enriched_json_path = None
        secondary_md_path_out = None
        secondary_tsv_path = None

        if analysis_mode == "cross_talk":
            secondary_ptm_type = config.get("secondary_ptm_type", "ubiquitylation")
            secondary_ptm_mode = "ubi" if secondary_ptm_type.startswith("ubiquit") else "phospho"
            secondary_file_suffix = "_ubi" if secondary_ptm_mode == "ubi" else "_phospho"

            # Look for secondary preprocessing output
            secondary_output_dir = config.get("secondary_output_dir")
            if not secondary_output_dir:
                secondary_output_dir = str(order_output / "secondary_ptm")

            sec_dir = Path(secondary_output_dir)
            sec_vector_file = sec_dir / f"ptm_vector_data_normalized{secondary_file_suffix}.tsv"
            if not sec_vector_file.exists():
                sec_vector_file = sec_dir / f"ptm_vector_data_with_motifs{secondary_file_suffix}.tsv"

            if sec_vector_file.exists():
                publish_progress(order_id, "rag_enrichment", "secondary_enrichment", "started", 90,
                                f"Enriching secondary {secondary_ptm_type} data")

                sec_df = pd.read_csv(sec_vector_file, sep="\t", low_memory=False)
                logger.info(f"[Order {order_id}] Secondary: Loaded {len(sec_df)} entries from {sec_vector_file.name}")

                # Select top-N secondary PTMs
                sec_gene_col = "Gene.Name" if "Gene.Name" in sec_df.columns else "gene"
                sec_pos_col = "PTM_Position" if "PTM_Position" in sec_df.columns else "position"
                sec_fc_col = "PTM_Relative_Log2FC" if "PTM_Relative_Log2FC" in sec_df.columns else "ptm_relative_log2fc"
                sec_cond_col = "Condition" if "Condition" in sec_df.columns else "condition"

                if sec_fc_col in sec_df.columns and sec_cond_col in sec_df.columns:
                    sec_df["_abs_fc"] = sec_df[sec_fc_col].abs()
                    sec_df["_key"] = list(zip(sec_df[sec_gene_col].astype(str), sec_df[sec_pos_col].astype(str)))
                    sec_key_max = sec_df.groupby("_key")["_abs_fc"].max().sort_values(ascending=False)
                    sec_selected = set(sec_key_max.head(top_n).index.tolist())
                    sec_df = sec_df[sec_df["_key"].isin(sec_selected)]
                    sec_df = sec_df.drop(columns=["_abs_fc", "_key"])
                    logger.info(f"[Order {order_id}] Secondary: selected {len(sec_selected)} unique PTMs")

                sec_ptm_data = sec_df.to_dict("records")

                # Enrich secondary PTMs
                sec_enrich_cb = _make_progress_cb(order_id, "rag_enrichment", "secondary_enrichment", 90, 3)
                sec_pipeline = RAGEnrichmentPipeline(
                    mcp_client=mcp,
                    progress_callback=sec_enrich_cb,
                    analysis_log=_analysis_log,
                    rag_enrichment_llm_model=config.get("rag_enrichment_llm_model"),
                    rag_enrichment_llm_provider=config.get("rag_enrichment_llm_provider"),
                    rag_llm_model=rag_llm_model,
                    rag_llm_provider=rag_llm_provider,
                    llm_provider=report_llm_provider,
                    llm_model=config.get("llm_model"),
                )
                sec_enriched = sec_pipeline.enrich_ptm_data(
                    ptm_data=sec_ptm_data,
                    experimental_context={**experimental_context, "ptm_type": secondary_ptm_type},
                )

                # Save secondary enriched JSON
                secondary_enriched_json_path = order_output / f"enriched_ptm_data{secondary_file_suffix}.json"
                with open(secondary_enriched_json_path, "w", encoding="utf-8") as f:
                    json.dump(sec_enriched, f, indent=2, default=str)
                logger.info(f"[Order {order_id}] Saved secondary enriched data: {secondary_enriched_json_path.name}")

                # Generate secondary MD report
                sec_merged = merge_multi_condition_ptms(sec_enriched, single_time_point=single_time_point)
                sec_generator = ComprehensiveReportGenerator(
                    experimental_context={**experimental_context, "ptm_type": secondary_ptm_type}
                )
                sec_report_md = sec_generator.generate_full_report(sec_merged)
                secondary_md_path_out = order_output / f"comprehensive_report{secondary_file_suffix}.md"
                with open(secondary_md_path_out, "w", encoding="utf-8") as f:
                    f.write(sec_report_md)
                logger.info(f"[Order {order_id}] Saved secondary report: {secondary_md_path_out.name}")

                # Find secondary TSV path
                sec_bio_tsv = sec_dir / f"unified_protein_data_enriched_bio_enriched{secondary_file_suffix}.tsv"
                if sec_bio_tsv.exists():
                    secondary_tsv_path = str(sec_bio_tsv)
                else:
                    sec_tsv_candidates = list(sec_dir.glob("*bio_enriched*.tsv"))
                    if sec_tsv_candidates:
                        secondary_tsv_path = str(sec_tsv_candidates[0])

                publish_progress(order_id, "rag_enrichment", "secondary_enrichment", "completed", 95,
                                f"Secondary {secondary_ptm_type} enrichment complete ({len(sec_enriched)} PTMs)")
            else:
                logger.warning(f"[Order {order_id}] Cross-Talk: secondary vector file not found at {sec_vector_file}")
                publish_progress(order_id, "rag_enrichment", "secondary_enrichment", "skipped", 95,
                                "Secondary PTM vector file not found — skipping secondary enrichment")

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
        send_step_webhook(order_id, "rag_enrichment", "completed")
        mcp.close()

        # Chain to Stage 3: Report Generation
        report_config = {
            "order_code": order_code,
            "rag_output_dir": str(order_output),
            "enriched_json_path": str(enriched_json_path),
            "md_report_path": str(md_path),
            "tsv_data_path": config.get("tsv_data_path", ""),
            "experimental_context": experimental_context,
            "research_questions": config.get("research_questions", []),
            "chromadb_collections": config.get("chromadb_collections", []),
            "llm_provider": config.get("llm_provider", "ollama"),
            "llm_model": config.get("llm_model"),
            "report_title": config.get("report_title", "PTM Comprehensive Analysis Report"),
            "report_type": config.get("report_type", "comprehensive"),
            "report_config": config.get("report_config", {}),
            "analysis_mode": analysis_mode,
            "secondary_ptm_type": config.get("secondary_ptm_type"),
        }
        # Cross-Talk: add secondary paths to report_config
        if analysis_mode == "cross_talk":
            report_config["secondary_enriched_json_path"] = str(secondary_enriched_json_path) if secondary_enriched_json_path else None
            report_config["secondary_md_report_path"] = str(secondary_md_path_out) if secondary_md_path_out else None
            report_config["secondary_tsv_data_path"] = secondary_tsv_path
            report_config["secondary_output_dir"] = str(order_output / "secondary_ptm") if (order_output / "secondary_ptm").exists() else str(order_output)
            logger.info(f"[Order {order_id}] Cross-Talk report_config: secondary_enriched={secondary_enriched_json_path}, secondary_md={secondary_md_path_out}")
        _status_before_chain = get_order_status(order_id)
        if config.get("chain_to_next", True) and _status_before_chain == "rag_enrichment":
            app.send_task(
                "report_generation.tasks.run_report_generation",
                args=[order_id, report_config],
                queue="report_generation",
            )
            logger.info(f"[Order {order_id}] Chained to report generation")
        else:
            logger.info(
                f"[Order {order_id}] RAG complete — skipping chain "
                f"(chain_to_next={config.get('chain_to_next', True)}, status={_status_before_chain!r})"
            )

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
        notify_order_status(order_id, "failed", error_msg)
        publish_progress(
            order_id, "rag_enrichment", "error", "failed", -1, error_msg,
            metadata={"traceback": traceback.format_exc(), "elapsed_seconds": elapsed},
        )
        raise
    finally:
        try:
            mcp.close()
        except Exception:
            pass
