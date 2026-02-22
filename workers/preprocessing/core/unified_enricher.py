"""
Unified Protein Enricher — domain & motif enrichment for PTM data.
Ported from ptm-preprocessing_v2_260131/src/unified_enricher.py.

Changes from original:
  - InterPro API calls → MCP Client (batch)
  - print() → logging
  - ThreadPoolExecutor for API calls replaced by MCP batch endpoint
  - progress_callback for Celery integration

Schema matches ptm-preprocessing_v2_260131 output:
  Domains, Domain_Count, Motifs, Motif_Count, Sequence_Window, Motif_Analysis_Error,
  Motifs_Sequence_Window, Matched_Motifs, Predicted_Regulator,
  Enhanced_Sequence_Window, Enhanced_Matched_Motifs, Enhanced_Predicted_Regulator,
  Detailed_Regulator_Predictions
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from Bio import SeqIO

from .enhanced_motif_analyzer_v2 import EnhancedMotifAnalyzerV2

logger = logging.getLogger(__name__)

PTM_TYPE_NAMES = {
    "phospho": "Phosphorylation",
    "ubi": "Ubiquitylation",
}

MOTIF_PATTERNS = {
    "PKA_motif": {"pattern": r"[RK][RK].[ST]", "residues": ["S", "T"]},
    "PKC_motif": {"pattern": r"[ST].[RK]", "residues": ["S", "T"]},
    "CK2_motif": {"pattern": r"[ST]..E", "residues": ["S", "T"]},
    "CDK_motif": {"pattern": r"[ST]P[RK]", "residues": ["S", "T"]},
    "MAPK_motif": {"pattern": r"P.[ST]P", "residues": ["S", "T"]},
    "SH2_motif": {"pattern": r"Y..P", "residues": ["Y"]},
    "PTB_motif": {"pattern": r"NPX[YF]", "residues": ["Y"]},
    "14-3-3_motif": {"pattern": r"R.[ST].P", "residues": ["S", "T"]},
    "HAT_motif": {"pattern": r"K[GAVS]", "residues": ["K"]},
    "HDAC_motif": {"pattern": r"K.[ST]", "residues": ["K"]},
    "Basophilic_kinase": {"pattern": r"[RK].[ST]", "residues": ["S", "T"]},
    "Acidophilic_kinase": {"pattern": r"[ST]..[DE]", "residues": ["S", "T"]},
    "Proline_directed": {"pattern": r"[ST]P", "residues": ["S", "T"]},
    "Cysteine_alkylation": {"pattern": r"C", "residues": ["C"]},
    "Disulfide_bridge": {"pattern": r"C..C", "residues": ["C"]},
    "N-terminal_acetylation": {"pattern": r"^[ASGM]", "residues": ["A", "S", "G", "M"]},
}


class UnifiedProteinEnricher:
    """Domain and motif enrichment for PTM vector data using MCP Server."""

    def __init__(
        self,
        fasta_path: str,
        output_dir: str = "results",
        cache_dir: str = "cache",
        file_suffix: str = "_phospho",
        ptm_mode: str = "phospho",
        mcp_client=None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ):
        self.fasta_path = fasta_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.file_suffix = file_suffix
        self.ptm_mode = ptm_mode
        self.data_type_name = PTM_TYPE_NAMES.get(ptm_mode, "PTM")
        self.mcp = mcp_client
        self._progress = progress_callback or (lambda p, m: None)

        self.fasta_dict: Dict[str, str] = {}
        self.protein_names: Dict[str, str] = {}
        self.gene_names: Dict[str, str] = {}
        self.domain_cache: Dict[str, List[str]] = {}
        self.motif_cache: Dict[str, dict] = {}

        self.enhanced_motif_analyzer: Optional[EnhancedMotifAnalyzerV2] = None

    # ------------------------------------------------------------------
    # FASTA loading
    # ------------------------------------------------------------------

    def load_fasta(self) -> bool:
        try:
            for record in SeqIO.parse(self.fasta_path, "fasta"):
                uid = self._extract_uniprot_id(record.id)
                if uid:
                    self.fasta_dict[uid] = str(record.seq)
                    pname, gname = self._parse_fasta_header(record.description)
                    self.protein_names[uid] = pname
                    self.gene_names[uid] = gname
            logger.info(f"FASTA loaded: {len(self.fasta_dict):,} proteins")
            return True
        except Exception as e:
            logger.error(f"FASTA loading failed: {e}")
            return False

    @staticmethod
    def _extract_uniprot_id(fasta_id: str) -> Optional[str]:
        if "|" in fasta_id:
            parts = fasta_id.split("|")
            return parts[1] if len(parts) >= 2 else None
        return fasta_id.split()[0].replace(">", "")

    @staticmethod
    def _parse_fasta_header(description: str) -> Tuple[str, str]:
        protein_name = gene_name = ""
        gn = re.search(r"GN=([^\s]+)", description)
        if gn:
            gene_name = gn.group(1)
        if " OS=" in description:
            name_part = description.split(" OS=")[0]
            if "|" in name_part:
                parts = name_part.split("|")
                if len(parts) >= 3:
                    words = parts[2].split()
                    protein_name = " ".join(words[1:]) if len(words) > 1 else parts[2]
            else:
                words = name_part.split()
                protein_name = " ".join(words[1:]) if len(words) > 1 else name_part
        return (protein_name.strip() or "Unknown protein"), (gene_name.strip() or "Unknown")

    @staticmethod
    def clean_protein_id(protein_id: str) -> str:
        if not protein_id or not isinstance(protein_id, str):
            return ""
        if "|" in protein_id:
            parts = protein_id.split("|")
            if len(parts) >= 2:
                return parts[1]
        if ";" in protein_id:
            protein_id = protein_id.split(";")[0]
        return protein_id.strip()

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def load_cache(self):
        domain_file = self.cache_dir / "domain_cache.json"
        if domain_file.exists():
            try:
                with open(domain_file, "r", encoding="utf-8") as f:
                    self.domain_cache = json.load(f)
                logger.info(f"Domain cache loaded: {len(self.domain_cache)} entries")
            except Exception as e:
                logger.warning(f"Domain cache load failed: {e}")

        motif_file = self.cache_dir / "motif_cache.json"
        if motif_file.exists():
            try:
                with open(motif_file, "r", encoding="utf-8") as f:
                    self.motif_cache = json.load(f)
                logger.info(f"Motif cache loaded: {len(self.motif_cache)} entries")
            except Exception as e:
                logger.warning(f"Motif cache load failed: {e}")

    def save_cache(self):
        try:
            with open(self.cache_dir / "domain_cache.json", "w", encoding="utf-8") as f:
                json.dump(self.domain_cache, f, ensure_ascii=False, indent=2)
            with open(self.cache_dir / "motif_cache.json", "w", encoding="utf-8") as f:
                json.dump(self.motif_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Cache save failed: {e}")

    # ------------------------------------------------------------------
    # Domain fetching (via MCP)
    # ------------------------------------------------------------------

    def fetch_domains_via_mcp(self, protein_ids: List[str]) -> Dict[str, List[str]]:
        """Fetch domain annotations through MCP Server (InterPro batch)."""
        if not self.mcp:
            logger.warning("No MCP client available — skipping domain enrichment")
            return {}

        unique_ids = list({self.clean_protein_id(pid) for pid in protein_ids if pid})
        to_fetch = [pid for pid in unique_ids if pid and pid not in self.domain_cache]

        if not to_fetch:
            logger.info(f"All domain annotations cached ({len(self.domain_cache)} entries)")
            return self.domain_cache

        logger.info(f"Fetching domains for {len(to_fetch)} proteins via MCP (cached: {len(unique_ids) - len(to_fetch)})...")

        def domain_progress(done: int, total: int, msg: str):
            frac = done / total if total > 0 else 1.0
            self._progress(0.30 + frac * 0.20, f"InterPro domains: {done:,}/{total:,}")

        results = self.mcp.fetch_interpro_parallel(
            to_fetch, max_workers=4, progress_cb=domain_progress,
        )

        for pid, data in results.items():
            domains = [d["name"] for d in data.get("domains", [])]
            self.domain_cache[pid] = domains

        logger.info(f"Domain cache now has {len(self.domain_cache)} entries")
        return self.domain_cache

    # ------------------------------------------------------------------
    # Local motif pattern analysis (Step 1 — v2 compatible)
    # ------------------------------------------------------------------

    def analyze_motif_patterns(self, protein_id: str, modified_sequence: str, ptm_position: str) -> Dict:
        """Analyze motif patterns for a PTM site using local FASTA sequences."""
        cache_key = f"{protein_id}_{modified_sequence}_{ptm_position}"
        if cache_key in self.motif_cache:
            return self.motif_cache[cache_key]

        result = {"motifs": [], "motif_descriptions": [], "sequence_window": "", "error": None}
        try:
            clean_id = self.clean_protein_id(protein_id)
            sequence = self.fasta_dict.get(clean_id, "")
            if not sequence:
                result["error"] = f"Protein sequence not found: {clean_id}"
                self.motif_cache[cache_key] = result
                return result

            pos_str = str(ptm_position)
            if pos_str in ("N-term", "Unknown", "N/A", ""):
                self.motif_cache[cache_key] = result
                return result

            match = re.match(r"([A-Z])(\d+)", pos_str)
            if not match:
                result["error"] = f"PTM position parse failed: {pos_str}"
                self.motif_cache[cache_key] = result
                return result

            aa, pos = match.groups()
            pos = int(pos) - 1  # 0-based

            if pos < 0 or pos >= len(sequence):
                result["error"] = f"PTM position out of range: {pos + 1}/{len(sequence)}"
                self.motif_cache[cache_key] = result
                return result

            window_start = max(0, pos - 7)
            window_end = min(len(sequence), pos + 8)
            sequence_window = sequence[window_start:window_end]
            result["sequence_window"] = sequence_window

            ptm_site_in_window = pos - window_start

            for motif_name, motif_info in MOTIF_PATTERNS.items():
                pattern = motif_info["pattern"]
                target_residues = motif_info["residues"]
                if aa not in target_residues:
                    continue
                for m in re.finditer(pattern, sequence_window):
                    if m.start() <= ptm_site_in_window < m.end():
                        result["motifs"].append(motif_name)
                        break

        except Exception as e:
            result["error"] = str(e)

        self.motif_cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # Main enrichment
    # ------------------------------------------------------------------

    def run_unified_enrichment(
        self, ptm_vector_file: str, all_protein_file: str, max_workers: int = 15
    ) -> bool:
        try:
            self._progress(0.0, "Loading FASTA")
            if not self.load_fasta():
                return False

            self.load_cache()

            self._progress(0.05, "Loading PTM vector data")
            ptm_df = self._load_tsv(ptm_vector_file, "PTM vector data")
            if ptm_df.empty:
                return False

            self._progress(0.10, "Loading all protein data")
            all_protein_df = self._load_tsv(all_protein_file, "All protein data")
            if all_protein_df.empty:
                return False

            self._progress(0.15, "Creating unified dataset")
            unified_df = self.create_unified_dataset(ptm_df, all_protein_df)

            self._progress(0.20, "Enriching data")
            enriched_df = self.enrich_unified_data(unified_df)

            self._progress(0.90, "Saving results")
            self.save_unified_results(enriched_df)
            self.save_cache()

            self._progress(1.0, "Enrichment complete")
            return True
        except Exception as e:
            logger.error(f"Unified enrichment failed: {e}", exc_info=True)
            return False

    @staticmethod
    def _load_tsv(path: str, label: str) -> pd.DataFrame:
        try:
            df = pd.read_csv(path, sep="\t", low_memory=False)
            logger.info(f"{label}: {len(df):,} rows")
            return df
        except Exception as e:
            logger.error(f"Failed to load {label}: {e}")
            return pd.DataFrame()

    def create_unified_dataset(self, ptm_df: pd.DataFrame, all_protein_df: pd.DataFrame) -> pd.DataFrame:
        """Merge PTM and non-PTM protein data into unified dataset (v2 compatible)."""
        ptm_df = ptm_df.copy()
        ptm_df["Has_PTM"] = True
        ptm_df["Data_Type"] = self.data_type_name

        ptm_proteins = set(ptm_df["Protein.Group"].unique())
        non_ptm = all_protein_df[~all_protein_df["Protein.Group"].isin(ptm_proteins)].copy()
        non_ptm["Has_PTM"] = False
        non_ptm["Data_Type"] = "Protein_Only"
        non_ptm["Modified.Sequence"] = ""
        non_ptm["PTM_Type"] = ""
        non_ptm["PTM_Position"] = ""
        non_ptm["PTM_Relative_Log2FC"] = np.nan
        non_ptm["Control_Mean_Protein"] = non_ptm.get("Control_Mean")
        non_ptm["Treatment_Mean_Protein"] = non_ptm.get("Treatment_Mean")
        non_ptm["Protein_Log2FC"] = non_ptm.get("Log2FC")
        non_ptm["Protein_Fold_Change"] = non_ptm.get("Fold_Change")
        non_ptm["Control_Mean_PTM_Relative"] = np.nan

        unique_conditions = non_ptm["Condition"].unique() if "Condition" in non_ptm.columns else []
        for cond in unique_conditions:
            non_ptm[f"{cond}_Mean_PTM_Relative"] = np.nan

        unified = pd.concat([ptm_df, non_ptm], ignore_index=True, sort=False)
        logger.info(f"Unified dataset: {len(unified):,} rows (PTM: {len(ptm_df):,}, non-PTM: {len(non_ptm):,})")
        return unified

    def enrich_unified_data(self, unified_df: pd.DataFrame) -> pd.DataFrame:
        """Enrich unified dataset with domain and motif annotations (v2 schema)."""
        unique_proteins = unified_df["Protein.Group"].dropna().unique().tolist()
        logger.info(f"Enriching {len(unique_proteins)} unique proteins")

        # --- Domain enrichment via MCP ---
        self._progress(0.30, "Fetching domain annotations")
        self.fetch_domains_via_mcp(unique_proteins)

        # --- Step 1: Local motif analysis (v2 analyze_motif_patterns) ---
        self._progress(0.50, "Running local motif analysis")
        ptm_data = unified_df[unified_df["Has_PTM"] == True]
        if not ptm_data.empty:
            for _, row in ptm_data.iterrows():
                pid = self.clean_protein_id(row["Protein.Group"])
                ms = row.get("Modified.Sequence", "")
                pp = row.get("PTM_Position", "")
                if pd.notna(ms) and pd.notna(pp):
                    self.analyze_motif_patterns(pid, str(ms), str(pp))
            self.save_cache()

        # --- Step 2: Enhanced motif analysis (EnhancedMotifAnalyzerV2) ---
        self._progress(0.60, "Running enhanced motif analysis")
        try:
            self.enhanced_motif_analyzer = EnhancedMotifAnalyzerV2(
                cache_dir=str(self.cache_dir), fasta_path=str(self.fasta_path)
            )
            unified_df = self.enhanced_motif_analyzer.analyze_motifs_simple(unified_df)
        except Exception as e:
            logger.warning(f"Enhanced motif analysis failed: {e}")

        # Enhanced columns mapping (v2 compatible)
        unified_df["Enhanced_Sequence_Window"] = unified_df.get("Motifs_Sequence_Window", "")
        unified_df["Enhanced_Matched_Motifs"] = unified_df.get("Matched_Motifs", "")
        unified_df["Enhanced_Predicted_Regulator"] = unified_df.get("Predicted_Regulator", "")
        unified_df["Detailed_Regulator_Predictions"] = unified_df.get("Predicted_Regulator", "")

        # Fill missing enhanced motif columns
        for col in ["Motifs_Sequence_Window", "Matched_Motifs", "Predicted_Regulator",
                     "Enhanced_Sequence_Window", "Enhanced_Matched_Motifs",
                     "Enhanced_Predicted_Regulator", "Detailed_Regulator_Predictions"]:
            if col not in unified_df.columns:
                unified_df[col] = ""
            unified_df[col] = unified_df[col].fillna("")

        # --- Build per-row annotation from caches ---
        self._progress(0.75, "Building annotation columns")
        domains_list = []
        domain_counts = []
        motifs_list = []
        motif_counts = []
        seq_windows = []
        motif_errors = []

        for _, row in unified_df.iterrows():
            pid = self.clean_protein_id(row["Protein.Group"])

            # Domain info
            domains = self.domain_cache.get(pid, [])
            domains_list.append("; ".join(domains) if domains else "")
            domain_counts.append(len(domains))

            # Local motif info (only for PTM rows)
            motifs = []
            seq_window = ""
            motif_error = ""
            if row.get("Has_PTM", False) and pd.notna(row.get("Modified.Sequence", "")):
                cache_key = f"{pid}_{row.get('Modified.Sequence', '')}_{row.get('PTM_Position', '')}"
                if cache_key in self.motif_cache:
                    mr = self.motif_cache[cache_key]
                    motifs = mr.get("motifs", [])
                    seq_window = mr.get("sequence_window", "")
                    motif_error = mr.get("error", "") or ""

            motifs_list.append("; ".join(motifs) if motifs else "")
            motif_counts.append(len(motifs))
            seq_windows.append(seq_window)
            motif_errors.append(motif_error)

        unified_df["Domains"] = domains_list
        unified_df["Domain_Count"] = domain_counts
        unified_df["Motifs"] = motifs_list
        unified_df["Motif_Count"] = motif_counts
        unified_df["Sequence_Window"] = seq_windows
        unified_df["Motif_Analysis_Error"] = motif_errors

        # Remove redundant columns from non-PTM merge
        for col in ["Control_Mean", "Treatment_Mean", "Log2FC", "Fold_Change"]:
            if col in unified_df.columns:
                unified_df.drop(columns=[col], inplace=True, errors="ignore")

        logger.info("Enrichment complete")
        return unified_df

    def save_unified_results(self, enriched_df: pd.DataFrame):
        out = self.output_dir / f"unified_protein_data_enriched{self.file_suffix}.tsv"
        enriched_df.to_csv(out, sep="\t", index=False)
        logger.info(f"Saved: {out.name}")
        self._print_summary(enriched_df)

    def _print_summary(self, df: pd.DataFrame):
        total = len(df)
        ptm_count = df["Has_PTM"].sum() if "Has_PTM" in df.columns else 0
        logger.info(f"Total rows: {total:,} (PTM: {ptm_count:,}, non-PTM: {total - ptm_count:,})")

        if "Domain_Count" in df.columns:
            has_domain = (df["Domain_Count"] > 0).sum()
            logger.info(f"With domain annotations: {has_domain:,}")

        ptm_data = df[df["Has_PTM"] == True] if "Has_PTM" in df.columns else pd.DataFrame()
        if not ptm_data.empty and "Motif_Count" in ptm_data.columns:
            has_motif = (ptm_data["Motif_Count"] > 0).sum()
            logger.info(f"With motif matches (PTM only): {has_motif:,}/{len(ptm_data):,}")

        if not ptm_data.empty and "Enhanced_Matched_Motifs" in ptm_data.columns:
            enhanced_count = (ptm_data["Enhanced_Matched_Motifs"] != "No motif match").sum()
            enhanced_count2 = (ptm_data["Enhanced_Matched_Motifs"] != "").sum()
            logger.info(f"Enhanced motif matches (PTM only): {min(enhanced_count, enhanced_count2):,}/{len(ptm_data):,}")
