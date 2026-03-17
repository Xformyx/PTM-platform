"""
Stage 1: PTM Preprocessing Pipeline — Celery Task.

Orchestrates the full preprocessing flow:
  1. PTM Quantification (ptm_quantification.py)
  2. Unified Enrichment — domain + motif (unified_enricher.py)
  3. Biological Enrichment — UniProt/STRING/KEGG via MCP (biological_enricher.py)
  4. Finalization

Each step checks for existing output files and skips if already completed.
MCP API results are cached in Redis (TTL 7 days) by the MCP server.
"""

import json
import logging
import os
import time
import traceback
from pathlib import Path

from celery_app import app
from common.db_update import get_order_status, update_order_status
from common.mcp_client import MCPClient
from common.progress import publish_progress

logger = logging.getLogger("ptm-workers.preprocessing")

INPUT_DIR = os.getenv("INPUT_DIR", "/data/inputs")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/data/outputs")


def _make_progress_callback(order_id: int, stage: str, step: str, base_pct: float, range_pct: float):
    """Create a progress callback that maps [0,1] to [base_pct, base_pct+range_pct]."""
    def cb(fraction: float, message: str):
        pct = base_pct + fraction * range_pct
        publish_progress(order_id, stage, step, "running", round(pct, 1), message)
    return cb


def _has_output(output_dir: Path, *filenames: str) -> bool:
    """Check if all expected output files exist and are non-empty."""
    for fn in filenames:
        f = output_dir / fn
        if not f.exists() or f.stat().st_size == 0:
            return False
    return True


def _apply_downsampling(df, analysis_options: dict | None, order_id: int) -> "pd.DataFrame":
    """Apply downsampling to reduce the number of proteins for biological enrichment.

    Returns a filtered DataFrame. PTM sites (Has_PTM=True) are always kept.
    """
    import pandas as pd

    if not analysis_options:
        return df

    mode = analysis_options.get("mode", "full")
    if mode == "full":
        return df

    total_before = len(df)
    ptm_col = "Has_PTM" if "Has_PTM" in df.columns else ("Is_PTM_Site" if "Is_PTM_Site" in df.columns else None)
    has_log2fc = "Protein_Log2FC" in df.columns

    ptm_mask = df[ptm_col].astype(str).str.lower().isin(["true", "1", "yes"]) if ptm_col else pd.Series(False, index=df.index)
    ptm_df = df[ptm_mask]
    non_ptm_df = df[~ptm_mask]

    if mode == "ptm_topn":
        top_n = int(analysis_options.get("topN", 500))
        if has_log2fc:
            non_ptm_sorted = non_ptm_df.copy()
            non_ptm_sorted["_abs_log2fc"] = non_ptm_sorted["Protein_Log2FC"].abs()
            top_proteins = non_ptm_sorted.nlargest(top_n, "_abs_log2fc")["Protein.Group"].unique()
            filtered_non_ptm = non_ptm_df[non_ptm_df["Protein.Group"].isin(top_proteins)]
        else:
            filtered_non_ptm = non_ptm_df.head(top_n)
        df = pd.concat([ptm_df, filtered_non_ptm], ignore_index=True)

    elif mode == "log2fc_threshold":
        threshold = float(analysis_options.get("log2fcThreshold", 0.5))
        if has_log2fc:
            filtered_non_ptm = non_ptm_df[non_ptm_df["Protein_Log2FC"].abs() >= threshold]
        else:
            filtered_non_ptm = non_ptm_df
        df = pd.concat([ptm_df, filtered_non_ptm], ignore_index=True)

    elif mode == "custom_count":
        count = int(analysis_options.get("proteinCount", 1000))
        if has_log2fc:
            non_ptm_sorted = non_ptm_df.copy()
            non_ptm_sorted["_abs_log2fc"] = non_ptm_sorted["Protein_Log2FC"].abs()
            top_proteins = non_ptm_sorted.nlargest(count, "_abs_log2fc")["Protein.Group"].unique()
            filtered_non_ptm = non_ptm_df[non_ptm_df["Protein.Group"].isin(top_proteins)]
        else:
            filtered_non_ptm = non_ptm_df.head(count)
        df = pd.concat([ptm_df, filtered_non_ptm], ignore_index=True)

    elif mode == "protein_list":
        list_path = analysis_options.get("protein_list_path")
        if list_path and os.path.exists(list_path):
            with open(list_path, "r") as f:
                target_ids = {line.strip() for line in f if line.strip()}
            logger.info(f"[Order {order_id}] Protein list loaded: {len(target_ids)} IDs")
            protein_col = "Protein.Group" if "Protein.Group" in non_ptm_df.columns else None
            if protein_col:
                filtered_non_ptm = non_ptm_df[
                    non_ptm_df[protein_col].apply(
                        lambda x: any(tid in str(x) for tid in target_ids) if pd.notna(x) else False
                    )
                ]
            else:
                filtered_non_ptm = non_ptm_df
            df = pd.concat([ptm_df, filtered_non_ptm], ignore_index=True)
        else:
            logger.warning(f"[Order {order_id}] Protein list file not found: {list_path}")

    # Clean up temp column if created
    if "_abs_log2fc" in df.columns:
        df = df.drop(columns=["_abs_log2fc"])

    total_after = len(df)
    unique_proteins = df["Protein.Group"].nunique() if "Protein.Group" in df.columns else total_after
    logger.info(
        f"[Order {order_id}] Downsampling ({mode}): {total_before:,} → {total_after:,} rows, "
        f"{unique_proteins:,} unique proteins"
    )
    return df


@app.task(bind=True, name="preprocessing.tasks.run_preprocessing", max_retries=1)
def run_preprocessing(self, order_id: int, config: dict):
    """
    Stage 1: Full PTM Preprocessing Pipeline.

    config keys:
      - pr_matrix_path: str   (absolute path to PR matrix file)
      - pg_matrix_path: str   (absolute path to PG matrix file)
      - fasta_path: str       (absolute path to FASTA file)
      - config_xlsx_path: str (absolute path to config.xlsx, optional)
      - ptm_mode: 'phospho' | 'ubi'
      - condition_map: dict   {filename: condition}  (optional, built from config.xlsx)
      - species_tax_id: str   (default '10090')
      - kegg_organism: str    (default 'mmu')
    """
    start_time = time.time()
    order_code = config.get("order_code", f"order-{order_id}")
    order_output = Path(OUTPUT_DIR) / order_code
    order_output.mkdir(parents=True, exist_ok=True)

    update_order_status(order_id, "preprocessing", current_stage="preprocessing", progress_pct=0)
    logger.info(f"[Order {order_id}] Preprocessing started — mode={config.get('ptm_mode', 'phospho')}")
    publish_progress(order_id, "preprocessing", "start", "started", 0, "Preprocessing pipeline started")

    try:
        pr_path = config["pr_matrix_path"]
        pg_path = config["pg_matrix_path"]
        fasta_path = config["fasta_path"]
        ptm_mode = config.get("ptm_mode", "phospho")
        condition_map = config.get("condition_map")
        species = config.get("species_tax_id", "10090")
        kegg_org = config.get("kegg_organism", "mmu")

        if not condition_map:
            config_xlsx = config.get("config_xlsx_path")
            if config_xlsx and os.path.exists(config_xlsx):
                import pandas as pd
                logger.info(f"[Order {order_id}] Loading condition_map from config.xlsx: {config_xlsx}")
                df = pd.read_excel(config_xlsx)
                if "File_Name" in df.columns and "Group" in df.columns:
                    condition_map = {}
                    for _, row in df.iterrows():
                        condition_map[str(row["File_Name"])] = str(row["Group"])
                    logger.info(f"[Order {order_id}] Loaded {len(condition_map)} sample mappings from config.xlsx")
                else:
                    logger.warning(f"[Order {order_id}] config.xlsx missing File_Name/Group columns")

        for label, path in [("PR Matrix", pr_path), ("PG Matrix", pg_path), ("FASTA", fasta_path)]:
            if not os.path.exists(path):
                raise FileNotFoundError(f"{label} not found: {path}")

        file_suffix = "_phospho" if ptm_mode == "phospho" else "_ubi"

        # ================================================================
        # Step 1: PTM Quantification (0% – 50%)
        # ================================================================
        quant_output = f"ptm_vector_data_normalized{file_suffix}.tsv"
        all_protein_output = f"all_protein_level_changes_normalized{file_suffix}.tsv"

        if _has_output(order_output, quant_output, all_protein_output):
            logger.info(f"[Order {order_id}] Step 1 skipped — quantification outputs already exist")
            publish_progress(order_id, "preprocessing", "ptm_quantification", "completed", 50, "PTM quantification skipped (cached)")
        else:
            publish_progress(order_id, "preprocessing", "ptm_quantification", "started", 2, "Loading input files")

            from preprocessing.core.ptm_quantification import PTMQuantificationAnalyzer

            quant_cb = _make_progress_callback(order_id, "preprocessing", "ptm_quantification", 2, 48)

            analyzer = PTMQuantificationAnalyzer(
                fasta_path=fasta_path,
                output_dir=str(order_output),
                ptm_mode=ptm_mode,
                condition_map=condition_map,
                progress_callback=quant_cb,
            )

            success = analyzer.run_analysis(pr_path, pg_path)
            if not success:
                raise RuntimeError("PTM quantification failed")

            publish_progress(order_id, "preprocessing", "ptm_quantification", "completed", 50, "PTM quantification complete")

        # --- Pipeline Statistics: collect Step 1 & 2 stats ---
        try:
            from preprocessing.core.pipeline_statistics import PipelineStatistics
            import pandas as pd

            stats_json_path = order_output / f"pipeline_statistics{file_suffix}.json"
            ps = PipelineStatistics(ptm_mode=ptm_mode)

            # Step 1: Input stats
            pr_df = pd.read_csv(pr_path, sep="\t", low_memory=False)
            pg_df = pd.read_csv(pg_path, sep="\t", low_memory=False)
            ps.collect_input_stats(pr_df, pg_df, fasta_path, condition_map or {})

            # Step 2: Quantification stats from output files
            ptm_vector_path = order_output / quant_output
            all_protein_path = order_output / all_protein_output
            if ptm_vector_path.exists():
                ptm_vec_df = pd.read_csv(ptm_vector_path, sep="\t", low_memory=False)
                if all_protein_path.exists():
                    all_prot_df = pd.read_csv(all_protein_path, sep="\t", low_memory=False)
                else:
                    all_prot_df = pd.DataFrame()

                # Collect normalization stats (before/after counts from PR/PG)
                ps.stats["step2_quantification"] = {
                    "normalization": {
                        "pr_precursors_before": len(pr_df),
                        "pg_proteins_before": len(pg_df),
                    },
                }

                # PTM filtering stats
                ptm_mask = ptm_vec_df.get("Has_PTM", pd.Series(dtype=bool)).astype(str).str.lower().isin(["true", "1", "yes"])
                ptm_count = int(ptm_mask.sum()) if ptm_mask.any() else len(ptm_vec_df)
                ps.stats["step2_quantification"]["ptm_filtering"] = {
                    "total_precursors": len(pr_df),
                    "ptm_precursors": ptm_count,
                    "ptm_proteins": int(ptm_vec_df["Protein.Group"].nunique()) if "Protein.Group" in ptm_vec_df.columns else 0,
                    "ptm_sites": int(ptm_vec_df["PTM_Site"].nunique()) if "PTM_Site" in ptm_vec_df.columns else 0,
                    "ptm_ratio": round(ptm_count / max(len(pr_df), 1) * 100, 1),
                }

                # Relative quantification stats
                ps.stats["step2_quantification"]["relative_quant"] = {
                    "total_entries": len(ptm_vec_df),
                    "unique_proteins": int(ptm_vec_df["Protein.Group"].nunique()) if "Protein.Group" in ptm_vec_df.columns else 0,
                    "unique_sites": int(ptm_vec_df["PTM_Site"].nunique()) if "PTM_Site" in ptm_vec_df.columns else 0,
                }

                # Comparison stats per condition
                if "Condition" in ptm_vec_df.columns and "PTM_Log2FC" in ptm_vec_df.columns:
                    per_condition = {}
                    for cond, grp in ptm_vec_df.groupby("Condition"):
                        log2fc = grp["PTM_Log2FC"].dropna()
                        per_condition[str(cond)] = {
                            "total_entries": len(grp),
                            "unique_proteins": int(grp["Protein.Group"].nunique()) if "Protein.Group" in grp.columns else 0,
                            "up_regulated": int((log2fc > 1).sum()),
                            "down_regulated": int((log2fc < -1).sum()),
                            "unchanged": int(((log2fc >= -1) & (log2fc <= 1)).sum()),
                            "mean_log2fc": round(float(log2fc.mean()), 4) if len(log2fc) > 0 else 0,
                        }
                    ps.stats["step2_quantification"]["comparisons"] = {
                        "total_comparisons": len(per_condition),
                        "per_condition": per_condition,
                    }

                # Protein changes stats
                if not all_prot_df.empty and "Protein.Group" in all_prot_df.columns:
                    ptm_prot_ids = set(ptm_vec_df["Protein.Group"].unique()) if "Protein.Group" in ptm_vec_df.columns else set()
                    all_prot_ids = set(all_prot_df["Protein.Group"].unique())
                    non_ptm_ids = all_prot_ids - ptm_prot_ids
                    ps.stats["step2_quantification"]["protein_changes"] = {
                        "all_proteins": {"total": len(all_prot_df), "unique_proteins": len(all_prot_ids)},
                        "ptm_proteins": {"total": len(ptm_vec_df), "unique_proteins": len(ptm_prot_ids)},
                        "non_ptm_proteins": len(non_ptm_ids),
                    }

                # PTM vector / quadrant analysis
                if "Protein_Log2FC" in ptm_vec_df.columns and "PTM_Log2FC" in ptm_vec_df.columns:
                    prot_fc = ptm_vec_df["Protein_Log2FC"].dropna()
                    ptm_fc = ptm_vec_df["PTM_Log2FC"].dropna()
                    valid = ptm_vec_df.dropna(subset=["Protein_Log2FC", "PTM_Log2FC"])
                    ps.stats["step2_quantification"]["ptm_vector"] = {
                        "total_vectors": len(valid),
                        "unique_proteins": int(valid["Protein.Group"].nunique()) if "Protein.Group" in valid.columns else 0,
                        "quadrant_analysis": {
                            "Q1_up_up": int(((valid["Protein_Log2FC"] > 0) & (valid["PTM_Log2FC"] > 0)).sum()),
                            "Q2_down_up": int(((valid["Protein_Log2FC"] < 0) & (valid["PTM_Log2FC"] > 0)).sum()),
                            "Q3_down_down": int(((valid["Protein_Log2FC"] < 0) & (valid["PTM_Log2FC"] < 0)).sum()),
                            "Q4_up_down": int(((valid["Protein_Log2FC"] > 0) & (valid["PTM_Log2FC"] < 0)).sum()),
                        },
                    }

            # Save intermediate stats
            with open(stats_json_path, "w", encoding="utf-8") as f:
                json.dump(ps.stats, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"[Order {order_id}] Pipeline statistics (Step 1-2) saved: {stats_json_path.name}")

        except Exception as stats_err:
            logger.warning(f"[Order {order_id}] Pipeline statistics collection failed (non-fatal): {stats_err}")

        # ================================================================
        # Step 1b: PTM Vector Report (2D scatter plots) — right after Step 1
        # ================================================================
        has_vector_reports = any(
            f.name.startswith("ptm_vector_report_") or f.name.startswith("ptm_vector_summary_report")
            for f in order_output.glob("*.png")
        )
        if not has_vector_reports:
            vector_file = order_output / quant_output
            if vector_file.exists() and vector_file.stat().st_size > 0:
                try:
                    publish_progress(order_id, "preprocessing", "vector_report", "started", 52, "Generating PTM vector plots")
                    from preprocessing.core.ptm_vector_report_generator import PTMVectorReportGenerator
                    gen = PTMVectorReportGenerator(str(order_output))
                    gen.generate_all(str(vector_file), file_suffix)
                    publish_progress(order_id, "preprocessing", "vector_report", "completed", 55, "PTM vector plots generated")
                except Exception as vec_err:
                    logger.warning(f"[Order {order_id}] PTM vector report failed (non-fatal): {vec_err}")

        # ================================================================
        # Step 2: Unified Enrichment — domain + motif (50% – 70%)
        # ================================================================
        enriched_output = f"unified_protein_data_enriched{file_suffix}.tsv"

        if _has_output(order_output, enriched_output):
            logger.info(f"[Order {order_id}] Step 2 skipped — unified enrichment output already exists")
            publish_progress(order_id, "preprocessing", "unified_enrichment", "completed", 70, "Domain/motif enrichment skipped (cached)")
        else:
            publish_progress(order_id, "preprocessing", "unified_enrichment", "started", 50, "Starting domain/motif enrichment")

            from preprocessing.core.unified_enricher import UnifiedProteinEnricher

            mcp = MCPClient()
            enrichment_cb = _make_progress_callback(order_id, "preprocessing", "unified_enrichment", 50, 20)

            ptm_vector_file = str(order_output / quant_output)
            all_protein_file = str(order_output / all_protein_output)

            if os.path.exists(ptm_vector_file) and os.path.exists(all_protein_file):
                enricher = UnifiedProteinEnricher(
                    fasta_path=fasta_path,
                    output_dir=str(order_output),
                    cache_dir=str(order_output / "cache"),
                    file_suffix=file_suffix,
                    ptm_mode=ptm_mode,
                    mcp_client=mcp,
                    progress_callback=enrichment_cb,
                )
                enricher.run_unified_enrichment(ptm_vector_file, all_protein_file)
            else:
                logger.warning(f"[Order {order_id}] Skipping unified enrichment — missing input files")

            publish_progress(order_id, "preprocessing", "unified_enrichment", "completed", 70, "Domain/motif enrichment complete")


        # ================================================================
        # Step 3: Biological Enrichment — UniProt/STRING/KEGG (70% – 90%)
        # ================================================================
        bio_output = f"unified_protein_data_enriched_bio_enriched{file_suffix}.tsv"

        if _has_output(order_output, bio_output):
            logger.info(f"[Order {order_id}] Step 3 skipped — biological enrichment output already exists")
            publish_progress(order_id, "preprocessing", "biological_enrichment", "completed", 90, "Biological enrichment skipped (cached)")
        else:
            publish_progress(order_id, "preprocessing", "biological_enrichment", "started", 70, "Starting biological enrichment")

            from preprocessing.core.biological_enricher import BiologicalEnricher

            if "mcp" not in dir():
                mcp = MCPClient()

            bio_cb = _make_progress_callback(order_id, "preprocessing", "biological_enrichment", 70, 20)
            enriched_file = order_output / enriched_output

            if enriched_file.exists():
                import pandas as pd
                df = pd.read_csv(enriched_file, sep="\t", low_memory=False)

                # Apply downsampling if configured
                analysis_opts = config.get("analysis_options")
                df = _apply_downsampling(df, analysis_opts, order_id)
                ds_mode = (analysis_opts or {}).get("mode", "full")
                if ds_mode != "full":
                    unique_count = df["Protein.Group"].nunique() if "Protein.Group" in df.columns else len(df)
                    publish_progress(
                        order_id, "preprocessing", "biological_enrichment", "running", 71,
                        f"Downsampled to {unique_count:,} proteins ({ds_mode})",
                    )

                bio_enricher = BiologicalEnricher(
                    mcp_client=mcp,
                    cache_dir=str(order_output / "cache"),
                    progress_callback=bio_cb,
                )
                enriched_df = bio_enricher.enrich_dataframe(df, species_tax_id=species, kegg_organism=kegg_org)

                bio_out = order_output / bio_output
                enriched_df.to_csv(bio_out, sep="\t", index=False)
                logger.info(f"[Order {order_id}] Biological enrichment saved: {bio_out.name}")
            else:
                logger.warning(f"[Order {order_id}] Skipping biological enrichment — {enriched_file.name} not found")

            publish_progress(order_id, "preprocessing", "biological_enrichment", "completed", 90, "Biological enrichment complete")

        # --- Pipeline Statistics: collect Final Output stats ---
        try:
            import pandas as pd
            bio_path = order_output / bio_output
            stats_json_path = order_output / f"pipeline_statistics{file_suffix}.json"
            if bio_path.exists() and stats_json_path.exists():
                with open(stats_json_path, "r", encoding="utf-8") as f:
                    existing_stats = json.load(f)
                bio_df = pd.read_csv(bio_path, sep="\t", low_memory=False)
                unique_proteins = int(bio_df["Protein.Group"].nunique()) if "Protein.Group" in bio_df.columns else 0
                conditions = int(bio_df["Condition"].nunique()) if "Condition" in bio_df.columns else 0
                existing_stats["final_output"] = {
                    "total_rows": len(bio_df),
                    "total_columns": len(bio_df.columns),
                    "unique_proteins": unique_proteins,
                    "conditions": conditions,
                }
                with open(stats_json_path, "w", encoding="utf-8") as f:
                    json.dump(existing_stats, f, indent=2, ensure_ascii=False, default=str)
                logger.info(f"[Order {order_id}] Pipeline statistics (Final Output) updated")
        except Exception as stats_err:
            logger.warning(f"[Order {order_id}] Final Output statistics collection failed (non-fatal): {stats_err}")

        # ================================================================
        # Step 4: Finalization (90% – 100%)
        # ================================================================
        publish_progress(order_id, "preprocessing", "finalization", "started", 90, "Finalizing results")

        output_files = [f.name for f in order_output.iterdir() if f.is_file() and f.suffix in (".tsv", ".txt", ".png", ".json")]
        elapsed = round(time.time() - start_time, 1)

        publish_progress(
            order_id, "preprocessing", "finalization", "completed", 100,
            f"Preprocessing complete ({elapsed}s, {len(output_files)} files)",
            metadata={"output_files": output_files, "elapsed_seconds": elapsed},
        )

        logger.info(f"[Order {order_id}] Preprocessing completed in {elapsed}s — {len(output_files)} output files")

        if "mcp" in dir():
            mcp.close()

        if not config.get("chain_to_next", True) or get_order_status(order_id) == "cancelled":
            logger.info(f"[Order {order_id}] Preprocessing complete (no chain — re-run only or cancelled)")
            if get_order_status(order_id) != "cancelled":
                update_order_status(order_id, "completed", current_stage="preprocessing", progress_pct=100)
            return {
                "order_id": order_id,
                "status": "completed",
                "elapsed_seconds": elapsed,
                "output_dir": str(order_output),
                "output_files": output_files,
            }

        # Chain to Stage 2: RAG Enrichment
        rag_config = {
            "order_code": order_code,
            "preprocessing_output_dir": str(order_output),
            "ptm_mode": ptm_mode,
            "experimental_context": config.get("experimental_context"),
            "top_n_ptms": config.get("top_n_ptms", 50),
            "chromadb_collections": config.get("chromadb_collections", []),
            "llm_provider": config.get("llm_provider", "ollama"),
            "llm_model": config.get("llm_model"),
            "rag_llm_model": config.get("rag_llm_model"),
            "rag_llm_provider": config.get("rag_llm_provider"),
            "report_title": config.get("report_title", "PTM Comprehensive Analysis Report"),
        }
        app.send_task(
            "rag_enrichment.tasks.run_rag_enrichment",
            args=[order_id, rag_config],
            queue="rag_enrichment",
        )
        logger.info(f"[Order {order_id}] Chained to RAG enrichment")

        return {
            "order_id": order_id,
            "status": "completed",
            "elapsed_seconds": elapsed,
            "output_dir": str(order_output),
            "output_files": output_files,
            "next_stage": "rag_enrichment",
        }

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        error_msg = f"Preprocessing failed: {str(e)}"
        logger.error(f"[Order {order_id}] {error_msg}", exc_info=True)
        update_order_status(order_id, "failed", error_message=error_msg)
        publish_progress(
            order_id, "preprocessing", "error", "failed", -1, error_msg,
            metadata={"traceback": traceback.format_exc(), "elapsed_seconds": elapsed},
        )
        raise
