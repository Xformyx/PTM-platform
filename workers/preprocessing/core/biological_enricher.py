"""
Biological Enricher — UniProt, STRING-DB, KEGG enrichment.
Ported from ptm-preprocessing_v2_260131/src/biological_enricher.py.

Changes from original:
  - All API calls (UniProt, STRING, KEGG) → MCP Client batch endpoints
  - ThreadPoolExecutor + requests → MCP batch calls
  - print() → logging
  - progress_callback for Celery integration

Column names match ptm-preprocessing_v2_260131:
  Subcellular_Localization, Protein_Function_Summary,
  GO_Biological_Process, GO_Molecular_Function, GO_Cellular_Component,
  STRING_Interactors, STRING_Interaction_Score, KEGG_Pathways
"""

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class BiologicalEnricher:
    """Enriches PTM data with UniProt, STRING, and KEGG annotations via MCP Server."""

    def __init__(
        self,
        mcp_client=None,
        cache_dir: str = "./cache",
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ):
        self.mcp = mcp_client
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._progress = progress_callback or (lambda p, m: None)

    # ------------------------------------------------------------------
    # Column helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_protein_column(df: pd.DataFrame) -> Optional[str]:
        candidates = ["Protein.Group", "protein_id", "UniProt_ID", "Protein"]
        for c in candidates:
            if c in df.columns:
                return c
        return None

    @staticmethod
    def _find_gene_column(df: pd.DataFrame) -> Optional[str]:
        candidates = ["Gene.Name", "gene_name", "Gene", "Gene_Name"]
        for c in candidates:
            if c in df.columns:
                return c
        return None

    @staticmethod
    def _clean_protein_id(pid: str) -> str:
        if "|" in pid:
            parts = pid.split("|")
            if len(parts) >= 2:
                return parts[1]
        if "-" in pid:
            return pid.split("-")[0]
        return pid.strip()

    # ------------------------------------------------------------------
    # Main enrichment
    # ------------------------------------------------------------------

    def enrich_dataframe(
        self,
        df: pd.DataFrame,
        species_tax_id: str = "10090",
        kegg_organism: str = "mmu",
    ) -> pd.DataFrame:
        """
        Enrich a dataframe with UniProt, STRING-DB, and KEGG annotations.
        All API calls go through the MCP Server.
        Column names match ptm-preprocessing_v2_260131 output.
        """
        if not self.mcp:
            logger.warning("No MCP client — skipping biological enrichment")
            return df

        df = df.copy()

        # v2 column names
        str_cols = [
            "Subcellular_Localization", "Protein_Function_Summary",
            "GO_Biological_Process", "GO_Molecular_Function", "GO_Cellular_Component",
            "STRING_Interactors",
            "KEGG_Pathways",
        ]
        for col in str_cols:
            if col not in df.columns:
                df[col] = ""
        if "STRING_Interaction_Score" not in df.columns:
            df["STRING_Interaction_Score"] = ""

        protein_col = self._find_protein_column(df)
        gene_col = self._find_gene_column(df)

        # ---- Phase 1: UniProt ----
        if protein_col:
            self._progress(0.10, "UniProt enrichment")
            unique_proteins = [self._clean_protein_id(p) for p in df[protein_col].dropna().unique()]
            logger.info(f"UniProt: fetching {len(unique_proteins)} proteins via MCP")

            last_uniprot = [0, 0]
            heartbeat_stop = [False]
            heartbeat_seq = [0]

            def uniprot_progress(done, total, msg):
                last_uniprot[0], last_uniprot[1] = done, total
                frac = done / total if total > 0 else 1.0
                self._progress(0.10 + frac * 0.25, f"UniProt: {done:,}/{total:,}")

            def heartbeat():
                for _ in range(180):
                    if heartbeat_stop[0]:
                        break
                    time.sleep(5)
                    if heartbeat_stop[0]:
                        break
                    d, t = last_uniprot[0], last_uniprot[1]
                    if t > 0:
                        heartbeat_seq[0] += 1
                        elapsed = heartbeat_seq[0] * 5
                        frac = d / t
                        self._progress(
                            0.10 + frac * 0.25,
                            f"UniProt: {d:,}/{t:,} — still working ({elapsed}s)",
                        )

            heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
            heartbeat_thread.start()
            try:
                uniprot_data = self.mcp.fetch_uniprot_parallel(
                    unique_proteins, batch_size=10, max_workers=4, progress_cb=uniprot_progress,
                )
            finally:
                heartbeat_stop[0] = True

            for original_pid in df[protein_col].dropna().unique():
                clean = self._clean_protein_id(original_pid)
                info = uniprot_data.get(clean, {})
                mask = df[protein_col] == original_pid

                df.loc[mask, "Subcellular_Localization"] = "; ".join(info.get("subcellular_location", []))
                func_summary = info.get("function_summary", "")
                df.loc[mask, "Protein_Function_Summary"] = func_summary[:500] if func_summary else ""
                df.loc[mask, "GO_Biological_Process"] = "; ".join(info.get("go_terms_bp", [])[:5])
                df.loc[mask, "GO_Molecular_Function"] = "; ".join(info.get("go_terms_mf", [])[:5])
                df.loc[mask, "GO_Cellular_Component"] = "; ".join(info.get("go_terms_cc", [])[:5])

            logger.info("UniProt enrichment complete")

        # ---- Phase 2: STRING-DB ----
        if gene_col:
            self._progress(0.40, "STRING-DB enrichment")
            unique_genes = [g for g in df[gene_col].dropna().unique() if g != "Unknown"]
            logger.info(f"STRING-DB: fetching {len(unique_genes)} genes via MCP")

            last_string = [0, 0]
            string_stop = [False]
            string_seq = [0]

            def string_progress(done, total, msg):
                last_string[0], last_string[1] = done, total
                frac = done / total if total > 0 else 1.0
                self._progress(0.40 + frac * 0.25, f"STRING-DB: {done:,}/{total:,}")

            def string_heartbeat():
                for _ in range(180):
                    if string_stop[0]:
                        break
                    time.sleep(5)
                    if string_stop[0]:
                        break
                    d, t = last_string[0], last_string[1]
                    if t > 0:
                        string_seq[0] += 1
                        elapsed = string_seq[0] * 5
                        frac = d / t
                        self._progress(
                            0.40 + frac * 0.25,
                            f"STRING-DB: {d:,}/{t:,} — still working ({elapsed}s)",
                        )

            threading.Thread(target=string_heartbeat, daemon=True).start()
            try:
                string_data = self.mcp.fetch_stringdb_parallel(
                    unique_genes, species=species_tax_id, max_workers=4, progress_cb=string_progress,
                )
            finally:
                string_stop[0] = True

            for gene in unique_genes:
                info = string_data.get(gene, {})
                mask = df[gene_col] == gene
                interactions = info.get("interactions", [])
                partners = "; ".join(f"{i['partner']}({i['score']:.2f})" for i in interactions[:5])
                df.loc[mask, "STRING_Interactors"] = partners
                scores = [i.get("score", 0) for i in interactions[:5]]
                avg_score = f"{sum(scores) / len(scores):.2f}" if scores else ""
                df.loc[mask, "STRING_Interaction_Score"] = avg_score

            logger.info("STRING-DB enrichment complete")

        # ---- Phase 3: KEGG ----
        if gene_col:
            self._progress(0.70, "KEGG enrichment")
            unique_genes = [g for g in df[gene_col].dropna().unique() if g != "Unknown"]
            logger.info(f"KEGG: fetching {len(unique_genes)} genes via MCP")

            last_kegg = [0, 0]
            kegg_stop = [False]
            kegg_seq = [0]

            def kegg_progress(done, total, msg):
                last_kegg[0], last_kegg[1] = done, total
                frac = done / total if total > 0 else 1.0
                self._progress(0.70 + frac * 0.25, f"KEGG: {done:,}/{total:,}")

            def kegg_heartbeat():
                for _ in range(180):
                    if kegg_stop[0]:
                        break
                    time.sleep(5)
                    if kegg_stop[0]:
                        break
                    d, t = last_kegg[0], last_kegg[1]
                    if t > 0:
                        kegg_seq[0] += 1
                        elapsed = kegg_seq[0] * 5
                        frac = d / t
                        self._progress(
                            0.70 + frac * 0.25,
                            f"KEGG: {d:,}/{t:,} — still working ({elapsed}s)",
                        )

            threading.Thread(target=kegg_heartbeat, daemon=True).start()
            try:
                kegg_data = self.mcp.fetch_kegg_parallel(
                    unique_genes, organism=kegg_organism, max_workers=4, progress_cb=kegg_progress,
                )
            finally:
                kegg_stop[0] = True

            for gene in unique_genes:
                info = kegg_data.get(gene, {})
                mask = df[gene_col] == gene
                pathways = info.get("pathways", [])
                pathway_str = "; ".join(f"{p['name']} ({p['id']})" for p in pathways[:5])
                df.loc[mask, "KEGG_Pathways"] = pathway_str

            logger.info("KEGG enrichment complete")

        self._progress(1.0, "Biological enrichment complete")
        self._print_stats(df)
        return df

    def _print_stats(self, df: pd.DataFrame):
        total = len(df)
        if "Subcellular_Localization" in df.columns:
            has_loc = (df["Subcellular_Localization"].str.len() > 0).sum()
            logger.info(f"Subcellular_Localization: {has_loc}/{total}")
        if "STRING_Interactors" in df.columns:
            has_str = (df["STRING_Interactors"].str.len() > 0).sum()
            logger.info(f"STRING_Interactors: {has_str}/{total}")
        if "KEGG_Pathways" in df.columns:
            has_kegg = (df["KEGG_Pathways"].str.len() > 0).sum()
            logger.info(f"KEGG_Pathways: {has_kegg}/{total}")
