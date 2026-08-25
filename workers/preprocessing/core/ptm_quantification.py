"""
PTM Relative Quantification Analysis — Normalized Version with Enhanced Motif Analysis.
Ported from ptm-preprocessing_v2_260131/src/ptm_quantification.py.

Changes from original:
  - print() → logging
  - Removed matplotlib/seaborn/argparse (no GUI, no CLI)
  - Uses config.py constants
  - progress_callback for Celery integration
"""

import logging
import math
import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
from Bio import SeqIO
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .config import FIXED_MODIFICATIONS, PTM_MODES, VARIABLE_MODIFICATIONS
from .enhanced_motif_analyzer_v2 import EnhancedMotifAnalyzerV2

logger = logging.getLogger(__name__)

# Dual-track PTM quantification defaults.  Track 1 is deliberately conservative:
# without response-factor calibration it emits apparent paired occupancy, never
# physical absolute occupancy.  Track 2 remains the existing relative PTM path.
PAIR_MIN_REPLICATES = 2
PAIR_MIN_OBSERVED_TIMEPOINTS = 4
PAIR_MIN_COMPLETENESS = 0.70


class PTMQuantificationAnalyzer:
    """Median Normalization을 포함한 PTM Relative Quantification 분석 클래스."""

    def __init__(
        self,
        fasta_path: str,
        output_dir: str = "results",
        ptm_mode: str = "phospho",
        condition_map: Optional[Dict[str, str]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ):
        self.fasta_path = fasta_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if ptm_mode not in PTM_MODES:
            raise ValueError(f"Unsupported ptm_mode: {ptm_mode}. Available: {list(PTM_MODES.keys())}")

        self.ptm_mode = ptm_mode
        self.ptm_mode_config = PTM_MODES[ptm_mode]
        self.file_suffix = self.ptm_mode_config["file_suffix"]
        self.target_ptms = {self.ptm_mode_config["unimod_id"]: self.ptm_mode_config["name"]}

        logger.info(f"PTM mode: {ptm_mode.upper()} ({self.ptm_mode_config['name']})")

        self.pr_matrix = None
        self.pg_matrix = None
        self.pr_matrix_normalized = None
        self.pg_matrix_normalized = None
        self.sample_columns = None
        self.condition_map = condition_map if condition_map else {}
        self.external_condition_map = condition_map is not None
        self.available_conditions: List[str] = []
        self.treatment_conditions: List[str] = []
        self.fasta_dict: Dict[str, str] = {}
        self.protein_names: Dict[str, str] = {}
        self.gene_names: Dict[str, str] = {}
        self.diann_genes: Dict[str, str] = {}  # Protein.Group → Genes from DIA-NN matrix

        self._progress = progress_callback or (lambda p, m: None)

        try:
            cache_dir = self.output_dir / "cache"
            self.motif_analyzer = EnhancedMotifAnalyzerV2(
                cache_dir=str(cache_dir), fasta_path=str(self.fasta_path)
            )
        except Exception as e:
            logger.warning(f"Motif Analyzer init failed: {e}")
            self.motif_analyzer = None

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run_analysis(self, pr_matrix_path: str, pg_matrix_path: str) -> bool:
        self.pr_matrix_path = pr_matrix_path
        self.pg_matrix_path = pg_matrix_path
        return self.run_complete_analysis()

    def run_complete_analysis(self) -> bool:
        try:
            self._progress(0.01, "FASTA loading")
            if not self.load_fasta():
                return False

            self._progress(0.05, "Data loading")
            if not self.load_data():
                return False

            self._progress(0.10, "Median normalization")
            if not self.apply_median_normalization():
                return False

            self._progress(0.20, "Target PTM filtering")
            ptm_precursors = self.filter_target_ptms()
            if ptm_precursors.empty:
                logger.error("No target PTMs found")
                return False

            self._progress(0.30, "Site-level relative quantification")
            relative_quant_df = self.calculate_site_level_relative_quantification(ptm_precursors)
            if relative_quant_df.empty:
                return False

            self._progress(0.40, "Paired modified/unmodified audit")
            paired_occupancy_df, pair_audit_df = self.calculate_paired_occupancy(ptm_precursors)

            self._progress(0.50, "Condition comparisons")
            ptm_comparisons = self.calculate_condition_comparisons(relative_quant_df)
            if ptm_comparisons.empty:
                return False

            self._progress(0.60, "Protein-level changes")
            all_protein_changes, ptm_protein_changes = self.calculate_protein_level_changes()
            if all_protein_changes.empty:
                return False

            self._progress(0.75, "PTM vector data")
            ptm_vector_df = self.create_ptm_vector_data(
                ptm_comparisons, ptm_protein_changes, paired_occupancy_df
            )
            if ptm_vector_df.empty:
                return False

            self._progress(0.85, "Saving results")
            self.save_results(
                relative_quant_df, ptm_comparisons,
                all_protein_changes, ptm_protein_changes, ptm_vector_df, pair_audit_df,
            )

            self._progress(0.95, "Quantification complete")
            return True

        except Exception as e:
            logger.error(f"Analysis failed: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # FASTA loading
    # ------------------------------------------------------------------

    def load_fasta(self) -> bool:
        try:
            if not os.path.exists(self.fasta_path):
                logger.error(f"FASTA not found: {self.fasta_path}")
                return False

            for record in SeqIO.parse(self.fasta_path, "fasta"):
                uniprot_id = self._extract_uniprot_id(record.id)
                if uniprot_id:
                    self.fasta_dict[uniprot_id] = str(record.seq)
                    pname, gname = self._extract_protein_and_gene_info(record.description)
                    self.protein_names[uniprot_id] = pname
                    self.gene_names[uniprot_id] = gname

            logger.info(f"FASTA loaded: {len(self.fasta_dict):,} proteins")
            return True
        except Exception as e:
            logger.error(f"FASTA loading failed: {e}")
            return False

    @staticmethod
    def _extract_uniprot_id(fasta_id: str) -> Optional[str]:
        if "|" in fasta_id:
            parts = fasta_id.split("|")
            if len(parts) >= 2:
                return parts[1]
        return fasta_id.split()[0].replace(">", "")

    @staticmethod
    def _extract_protein_and_gene_info(description: str) -> Tuple[str, str]:
        try:
            protein_name = ""
            gene_name = ""

            gn_match = re.search(r"GN=([^\s]+)", description)
            if gn_match:
                gene_name = gn_match.group(1)

            if " OS=" in description:
                name_part = description.split(" OS=")[0]
                if "|" in name_part:
                    parts = name_part.split("|")
                    if len(parts) >= 3:
                        words = parts[2].split()
                        protein_name = " ".join(words[1:]) if len(words) > 1 else parts[2]
                    else:
                        protein_name = " ".join(parts[-1].split()[1:]) if len(parts[-1].split()) > 1 else parts[-1]
                else:
                    words = name_part.split()
                    protein_name = " ".join(words[1:]) if len(words) > 1 else name_part
            else:
                words = description.split()
                protein_name = " ".join(words[1:]) if len(words) > 1 else description

            return (protein_name.strip() or "Unknown protein"), (gene_name.strip() or "Unknown")
        except Exception:
            return "Unknown protein", "Unknown"

    @staticmethod
    def _split_protein_ids(protein_group: str) -> List[str]:
        """Split DIA-NN Protein.Group (may contain ';'-separated IDs)."""
        return [p.strip() for p in str(protein_group).split(";") if p.strip()]

    def _resolve_from_dict(self, protein_group: str, mapping: Dict[str, str], default: str = "") -> str:
        """Look up by full Protein.Group, then by each individual UniProt ID."""
        if protein_group in mapping:
            val = mapping[protein_group]
            if val and str(val).lower() not in ("unknown", "nan", ""):
                return val
        for pid in self._split_protein_ids(protein_group):
            if pid in mapping:
                val = mapping[pid]
                if val and str(val).lower() not in ("unknown", "nan", ""):
                    return val
        return default

    def _resolve_gene_name(self, protein_group: str) -> str:
        """Resolve gene name: DIA-NN Genes column first, then FASTA GN= lookup."""
        if protein_group in self.diann_genes:
            g = str(self.diann_genes[protein_group]).strip()
            if g and g.lower() not in ("unknown", "nan"):
                return g.split(";")[0].strip()
        for pid in self._split_protein_ids(protein_group):
            if pid in self.diann_genes:
                g = str(self.diann_genes[pid]).strip()
                if g and g.lower() not in ("unknown", "nan"):
                    return g.split(";")[0].strip()
        return self._resolve_from_dict(protein_group, self.gene_names, "Unknown") or "Unknown"

    def _resolve_protein_name(self, protein_group: str) -> str:
        return self._resolve_from_dict(protein_group, self.protein_names, "Unknown protein") or "Unknown protein"

    def _build_diann_gene_map(self) -> None:
        """Build Protein.Group → Genes map from DIA-NN PR/PG matrices."""
        self.diann_genes = {}
        for df in (getattr(self, "pg_matrix", None), getattr(self, "pr_matrix", None)):
            if df is None or "Genes" not in df.columns or "Protein.Group" not in df.columns:
                continue
            for _, row in df[["Protein.Group", "Genes"]].drop_duplicates("Protein.Group").iterrows():
                pg = str(row["Protein.Group"])
                gene = str(row["Genes"]).strip()
                if gene and gene.lower() not in ("nan", "unknown") and pg not in self.diann_genes:
                    self.diann_genes[pg] = gene
        if self.diann_genes:
            logger.info(f"DIA-NN gene map: {len(self.diann_genes):,} protein groups")

    # ------------------------------------------------------------------
    # Data loading & condition mapping
    # ------------------------------------------------------------------

    def load_data(self) -> bool:
        try:
            if not os.path.exists(self.pr_matrix_path):
                logger.error(f"PR Matrix not found: {self.pr_matrix_path}")
                return False
            self.pr_matrix = pd.read_csv(self.pr_matrix_path, sep="\t", on_bad_lines="warn", low_memory=False)
            logger.info(f"PR Matrix loaded: {len(self.pr_matrix):,} precursors")

            if not os.path.exists(self.pg_matrix_path):
                logger.error(f"PG Matrix not found: {self.pg_matrix_path}")
                return False
            self.pg_matrix = pd.read_csv(self.pg_matrix_path, sep="\t", on_bad_lines="warn", low_memory=False)
            logger.info(f"PG Matrix loaded: {len(self.pg_matrix):,} protein groups")

            self.sample_columns = [col for col in self.pr_matrix.columns if col.endswith(".mzML")]
            # Blind-benchmark snapshots may alias headers as S001.mzML; if a
            # caller already passed condition_map keys that exist as columns,
            # prefer those when no .mzML columns were detected.
            if (
                not self.sample_columns
                and self.external_condition_map
                and self.condition_map
            ):
                mapped = [
                    col for col in self.pr_matrix.columns
                    if col in self.condition_map
                ]
                if mapped:
                    self.sample_columns = mapped
                    logger.info(
                        "Samples resolved from condition_map keys "
                        f"(no .mzML headers): {len(self.sample_columns)}"
                    )
            logger.info(f"Samples: {len(self.sample_columns)}")

            self._build_diann_gene_map()
            self.create_condition_mapping()
            return True
        except Exception as e:
            logger.error(f"Data loading failed: {e}")
            return False

    def create_condition_mapping(self):
        if self.external_condition_map and self.condition_map:
            matched_map = {}
            for sample in self.sample_columns:
                if sample in self.condition_map:
                    matched_map[sample] = self.condition_map[sample]
                else:
                    sample_basename = os.path.basename(sample)
                    matched = False
                    for key, condition in self.condition_map.items():
                        key_basename = os.path.basename(key)
                        if sample_basename == key_basename or sample_basename in key or key_basename in sample:
                            matched_map[sample] = condition
                            matched = True
                            break
                    if not matched:
                        logger.warning(f"Condition mapping miss: {sample}")
                        matched_map[sample] = "Unknown"
            self.condition_map = matched_map
        else:
            for sample in self.sample_columns:
                if "Control_" in sample or "ctrl" in sample.lower() or "Cont_" in sample:
                    self.condition_map[sample] = "Control"
                elif "_A_" in sample:
                    self.condition_map[sample] = "A"
                elif "_B_" in sample:
                    self.condition_map[sample] = "B"
                elif "_C_" in sample:
                    self.condition_map[sample] = "C"
                else:
                    self.condition_map[sample] = "Unknown"

        # Normalize control aliases (Con, Ctrl, Ctr, WT, etc.) to "Control"
        CONTROL_ALIASES = frozenset({"con", "ctrl", "ctr", "control", "wt", "wildtype", "untreated", "baseline"})
        normalized_map = {}
        for sample, cond in self.condition_map.items():
            normalized_map[sample] = "Control" if (cond and cond.strip().lower() in CONTROL_ALIASES) else cond
        self.condition_map = normalized_map

        condition_counts: Dict[str, int] = {}
        for cond in self.condition_map.values():
            condition_counts[cond] = condition_counts.get(cond, 0) + 1
        for cond, cnt in sorted(condition_counts.items()):
            logger.info(f"  {cond}: {cnt} samples")

        self.available_conditions = list(condition_counts.keys())
        self.treatment_conditions = [c for c in self.available_conditions if c != "Control"]

        if "Control" not in self.available_conditions:
            logger.warning("No Control condition found — comparisons will be limited")

    # ------------------------------------------------------------------
    # Median Normalization
    # ------------------------------------------------------------------

    def apply_median_normalization(self) -> bool:
        try:
            self.pr_matrix_normalized = self.pr_matrix.copy()
            pr_factors = self._normalize_matrix(self.pr_matrix_normalized, self.sample_columns, "PR")

            self.pg_matrix_normalized = self.pg_matrix.copy()
            pg_factors = self._normalize_matrix(self.pg_matrix_normalized, self.sample_columns, "PG")

            self._save_normalization_factors(pr_factors, pg_factors)
            logger.info("Median normalization complete")
            return True
        except Exception as e:
            logger.error(f"Normalization failed: {e}")
            return False

    def _normalize_matrix(self, matrix: pd.DataFrame, sample_columns: List[str], matrix_type: str) -> Dict[str, float]:
        factors: Dict[str, float] = {}
        medians: Dict[str, float] = {}
        for sample in sample_columns:
            values = matrix[sample].replace(0, np.nan).dropna()
            medians[sample] = values.median() if len(values) > 0 else 1.0

        global_median = np.median(list(medians.values()))
        for sample in sample_columns:
            factor = global_median / medians[sample]
            factors[sample] = factor
            matrix[sample] = matrix[sample] * factor
        return factors

    def _save_normalization_factors(self, pr_factors: Dict[str, float], pg_factors: Dict[str, float]):
        rows = []
        for sample in self.sample_columns:
            rows.append({"Matrix_Type": "PR", "Sample": sample, "Normalization_Factor": pr_factors[sample]})
            rows.append({"Matrix_Type": "PG", "Sample": sample, "Normalization_Factor": pg_factors[sample]})
        pd.DataFrame(rows).to_csv(self.output_dir / "normalization_factors.tsv", sep="\t", index=False)

    # ------------------------------------------------------------------
    # PTM filtering
    # ------------------------------------------------------------------

    def filter_target_ptms(self) -> pd.DataFrame:
        parts = []
        for uid, name in self.target_ptms.items():
            pattern = f"UniMod:{uid}"
            matched = self.pr_matrix_normalized[
                self.pr_matrix_normalized["Modified.Sequence"].str.contains(pattern, na=False)
            ]
            logger.info(f"{name} (UniMod:{uid}): {len(matched):,}")
            parts.append(matched)

        if parts:
            df = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["Precursor.Id"])
            logger.info(f"Filtered PTMs: {len(df):,}")
            return df
        return pd.DataFrame()

    # ------------------------------------------------------------------
    # Site-level relative quantification
    # ------------------------------------------------------------------

    def calculate_site_level_relative_quantification(self, ptm_precursors: pd.DataFrame) -> pd.DataFrame:
        results = []
        for _, row in ptm_precursors.iterrows():
            protein_group = row["Protein.Group"]
            precursor_id = row["Precursor.Id"]
            modified_sequence = row["Modified.Sequence"]
            ptm_type = self._determine_ptm_type(modified_sequence)
            ptm_position = self._extract_ptm_position(protein_group, modified_sequence, ptm_type)

            for sample in self.sample_columns:
                ptm_intensity = row[sample] if pd.notna(row[sample]) and row[sample] > 0 else 0
                if ptm_intensity <= 0:
                    continue

                protein_row = self.pg_matrix_normalized[self.pg_matrix_normalized["Protein.Group"] == protein_group]
                if protein_row.empty:
                    continue
                protein_intensity = protein_row.iloc[0][sample]
                if not (pd.notna(protein_intensity) and protein_intensity > 0):
                    continue

                results.append({
                    "Protein.Group": protein_group,
                    "Precursor.Id": precursor_id,
                    "Modified.Sequence": modified_sequence,
                    "PTM_Type": ptm_type,
                    "PTM_Position": ptm_position,
                    "Sample": sample,
                    "Condition": self.condition_map.get(sample, "Unknown"),
                    "PTM_Intensity": ptm_intensity,
                    "Protein_Intensity": protein_intensity,
                    "PTM_Relative_Abundance": ptm_intensity / protein_intensity,
                })

        if results:
            df = pd.DataFrame(results)
            logger.info(f"Site-level quantification: {len(df)} records")
            return df
        return pd.DataFrame()

    def _determine_ptm_type(self, modified_sequence: str) -> str:
        for uid, name in self.target_ptms.items():
            if f"UniMod:{uid}" in modified_sequence:
                return name
        return "Unknown"

    @staticmethod
    def _clean_peptide_backbone(modified_sequence: str) -> str:
        """Return an uppercase peptide backbone without UniMod annotations."""
        if pd.isna(modified_sequence):
            return ""
        return re.sub(r"\(UniMod:\d+\)", "", str(modified_sequence)).strip().upper()

    def _target_modification_count(self, modified_sequence: str) -> int:
        return len(re.findall(rf"\(UniMod:{re.escape(str(self.ptm_mode_config['unimod_id']))}\)", str(modified_sequence)))

    def _is_unmodified_target_counterpart(self, modified_sequence: str) -> bool:
        """Return True only for a safe counterpart without target/variable PTMs.

        Fixed modifications such as carbamidomethylation are tolerated because they
        are shared preparation chemistry, while other variable modifications are
        excluded rather than silently mixed into a paired occupancy denominator.
        """
        unimod_ids = re.findall(r"\(UniMod:(\d+)\)", str(modified_sequence))
        return all(uid in FIXED_MODIFICATIONS for uid in unimod_ids)

    def calculate_paired_occupancy(self, ptm_precursors: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build Track 1 paired modified/unmodified peptide evidence.

        The returned occupancy is an *apparent paired occupancy* based on MS
        intensity fraction.  It is not absolute physical occupancy because the
        modified and unmodified peptide response factors are not calibrated here.
        Missing modified or unmodified signals remain missing; they are never
        converted to zero.
        """
        target_uid = str(self.ptm_mode_config["unimod_id"])
        unmodified_index: Dict[Tuple[str, str], List[pd.Series]] = {}
        for _, row in self.pr_matrix_normalized.iterrows():
            sequence = row.get("Modified.Sequence", "")
            if not self._is_unmodified_target_counterpart(sequence):
                continue
            backbone = self._clean_peptide_backbone(sequence)
            protein_group = str(row.get("Protein.Group", ""))
            if backbone and protein_group:
                unmodified_index.setdefault((protein_group, backbone), []).append(row)

        records: List[Dict[str, object]] = []
        audits: List[Dict[str, object]] = []
        expected_conditions = sorted(set(self.condition_map.get(sample, "Unknown") for sample in self.sample_columns))
        processed_forms: Set[Tuple[str, str]] = set()
        for _, modified_row in ptm_precursors.iterrows():
            modified_sequence = modified_row.get("Modified.Sequence", "")
            protein_group = str(modified_row.get("Protein.Group", ""))
            form_key = (protein_group, str(modified_sequence))
            if form_key in processed_forms:
                continue
            processed_forms.add(form_key)
            modified_form_rows = ptm_precursors[
                (ptm_precursors["Protein.Group"].astype(str) == protein_group)
                & (ptm_precursors["Modified.Sequence"].astype(str) == str(modified_sequence))
            ]
            modified_precursor_ids = ";".join(sorted(
                str(value) for value in modified_form_rows["Precursor.Id"].dropna().unique()
            ))
            if self._target_modification_count(modified_sequence) != 1:
                audits.append({
                    "Protein.Group": protein_group,
                    "Modified_Precursor_Ids": modified_precursor_ids,
                    "Modified.Sequence": modified_sequence,
                    "Pair_Status": "excluded_multiform_or_multiple_target_modifications",
                    "Pair_Quality_Tier": "O0",
                })
                continue
            backbone = self._clean_peptide_backbone(modified_sequence)
            counterparts = unmodified_index.get((protein_group, backbone), [])
            if not counterparts:
                audits.append({
                    "Protein.Group": protein_group,
                    "Modified_Precursor_Ids": modified_precursor_ids,
                    "Modified.Sequence": modified_sequence,
                    "Peptide_Backbone": backbone,
                    "Pair_Status": "missing_unmodified_counterpart",
                    "Pair_Quality_Tier": "O0",
                })
                continue

            pair_key = f"{protein_group}|{backbone}|{modified_sequence}"
            condition_values: Dict[str, List[float]] = {}
            missing_reasons: Dict[str, str] = {}
            for sample in self.sample_columns:
                condition = self.condition_map.get(sample, "Unknown")
                modified_values = [
                    float(row.get(sample))
                    for _, row in modified_form_rows.iterrows()
                    if pd.notna(row.get(sample)) and row.get(sample) > 0
                ]
                modified_intensity = sum(modified_values) if modified_values else None
                counterpart_values = [
                    float(counterpart.get(sample))
                    for counterpart in counterparts
                    if pd.notna(counterpart.get(sample)) and counterpart.get(sample) > 0
                ]
                unmodified_intensity = sum(counterpart_values) if counterpart_values else None
                if modified_intensity is None or unmodified_intensity is None:
                    missing_reasons.setdefault(condition, "missing_modified" if modified_intensity is None else "missing_unmodified")
                    continue
                denominator = modified_intensity + unmodified_intensity
                if denominator <= 0:
                    missing_reasons.setdefault(condition, "invalid_pair_denominator")
                    continue
                condition_values.setdefault(condition, []).append(modified_intensity / denominator)

            observed_conditions = [condition for condition, values in condition_values.items() if len(values) >= PAIR_MIN_REPLICATES]
            expected_count = max(len(expected_conditions), 1)
            completeness = len(observed_conditions) / expected_count
            qualified = len(observed_conditions) >= PAIR_MIN_OBSERVED_TIMEPOINTS and completeness >= PAIR_MIN_COMPLETENESS
            tier = "O2" if qualified else "O0"
            status = "qualified_apparent_paired_occupancy" if qualified else "insufficient_pair_completeness"
            audits.append({
                "Protein.Group": protein_group,
                "Modified_Precursor_Ids": modified_precursor_ids,
                "Modified.Sequence": modified_sequence,
                "Peptide_Backbone": backbone,
                "Paired_Peptide_Key": pair_key,
                "Unmodified_Precursor_Ids": ";".join(str(row.get("Precursor.Id", "")) for row in counterparts),
                "Pair_Status": status,
                "Pair_Quality_Tier": tier,
                "Expected_Timepoints": expected_count,
                "Observed_Timepoints": len(observed_conditions),
                "Pair_Missingness": round(1.0 - completeness, 6),
                "Missing_Reason_By_Condition": ";".join(f"{key}:{value}" for key, value in sorted(missing_reasons.items())),
                "Occupancy_Calibration_Type": "none",
            })
            if not qualified or "Control" not in condition_values or len(condition_values["Control"]) < PAIR_MIN_REPLICATES:
                continue
            control_mean = float(np.mean(condition_values["Control"]))
            control_logit = math.log(np.clip(control_mean, 1e-6, 1 - 1e-6) / (1 - np.clip(control_mean, 1e-6, 1 - 1e-6)))
            for condition in observed_conditions:
                if condition == "Control":
                    continue
                values = condition_values[condition]
                occupancy_mean = float(np.mean(values))
                occupancy_logit = math.log(np.clip(occupancy_mean, 1e-6, 1 - 1e-6) / (1 - np.clip(occupancy_mean, 1e-6, 1 - 1e-6)))
                p_value = np.nan
                if len(values) >= PAIR_MIN_REPLICATES and len(condition_values["Control"]) >= PAIR_MIN_REPLICATES:
                    try:
                        _, p_value = stats.ttest_ind(values, condition_values["Control"], equal_var=False, nan_policy="omit")
                    except Exception:
                        p_value = np.nan
                records.append({
                    "Protein.Group": protein_group,
                    "Precursor.Id": modified_precursor_ids,
                    "Modified.Sequence": modified_sequence,
                    "Condition": condition,
                    "Quantification_Track": "apparent_paired_occupancy",
                    "Paired_Peptide_Key": pair_key,
                    "Paired_Form_Level": "peptide_form",
                    "Occupancy_Fraction": occupancy_mean,
                    "Occupancy_Percent": occupancy_mean * 100.0,
                    "Occupancy_Control_Fraction": control_mean,
                    "Occupancy_Delta_PP": (occupancy_mean - control_mean) * 100.0,
                    "Occupancy_Logit_Delta": occupancy_logit - control_logit,
                    "Occupancy_Calibration_Type": "none",
                    "Pair_Quality_Tier": tier,
                    "Pair_Missingness": 1.0 - completeness,
                    "Occupancy_P_Value": p_value,
                    "Occupancy_N": len(values),
                    "Occupancy_Control_N": len(condition_values["Control"]),
                })
        occupancy_df = pd.DataFrame(records)
        audit_df = pd.DataFrame(audits)
        if not occupancy_df.empty:
            valid_mask = occupancy_df["Occupancy_P_Value"].notna()
            occupancy_df["Occupancy_Q_Value"] = np.nan
            if valid_mask.any():
                _, q_values, _, _ = multipletests(occupancy_df.loc[valid_mask, "Occupancy_P_Value"], alpha=0.05, method="fdr_bh")
                occupancy_df.loc[valid_mask, "Occupancy_Q_Value"] = q_values
        logger.info("Paired occupancy audit: qualified=%s, audits=%s", len(occupancy_df), len(audit_df))
        return occupancy_df, audit_df

    def _extract_ptm_position(self, protein_id: str, modified_sequence: str, ptm_type: str = None) -> str:
        try:
            if ptm_type is None:
                ptm_type = self._determine_ptm_type(modified_sequence)

            target_unimod_ids = [uid for uid, info in VARIABLE_MODIFICATIONS.items() if info["name"] == ptm_type]

            candidate_ids = self._split_protein_ids(protein_id)
            if protein_id in self.fasta_dict and protein_id not in candidate_ids:
                candidate_ids.insert(0, protein_id)

            for pid in candidate_ids:
                if pid not in self.fasta_dict:
                    continue
                protein_sequence = self.fasta_dict[pid]
                clean_sequence = re.sub(r"\([^)]*\)", "", modified_sequence)
                peptide_start = protein_sequence.find(clean_sequence)

                if peptide_start != -1:
                    clean_index = 0
                    i = 0
                    while i < len(modified_sequence):
                        m = re.match(r"([A-Z])\(UniMod:(\d+)\)", modified_sequence[i:])
                        if m:
                            residue, unimod_id = m.group(1), m.group(2)
                            if unimod_id not in FIXED_MODIFICATIONS:
                                if not target_unimod_ids or unimod_id in target_unimod_ids:
                                    return f"{residue}{peptide_start + clean_index + 1}"
                            clean_index += 1
                            i += m.end()
                        elif modified_sequence[i].isupper():
                            clean_index += 1
                            i += 1
                        else:
                            i += 1

                    if modified_sequence.startswith("(UniMod:1)"):
                        return "N-term"

            for match in re.finditer(r"([A-Z])\(UniMod:(\d+)\)", modified_sequence):
                residue, unimod_id = match.group(1), match.group(2)
                if unimod_id in FIXED_MODIFICATIONS:
                    continue
                if target_unimod_ids and unimod_id not in target_unimod_ids:
                    continue
                return residue

            if modified_sequence.startswith("(UniMod:1)"):
                return "N-term"
            return "Unknown"
        except Exception:
            return "Unknown"

    # ------------------------------------------------------------------
    # Condition comparisons & Log2FC
    # ------------------------------------------------------------------

    def calculate_condition_comparisons(self, relative_quant_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate condition comparisons with Welch's t-test and BH correction.

        For each PTM site × treatment condition:
        1. Compute mean Log2FC from replicate-level data
        2. Perform Welch's t-test (Control replicates vs Treatment replicates)
        3. Apply Benjamini-Hochberg correction for multiple testing
        4. Output p_value and q_value columns
        """
        # --- Build replicate-level grouped data (keep individual replicates) ---
        id_cols = ["Protein.Group", "Precursor.Id", "Modified.Sequence", "PTM_Type", "PTM_Position"]

        # Condition means (for Log2FC calculation, same as before)
        condition_means = relative_quant_df.groupby(
            id_cols + ["Condition"]
        )["PTM_Relative_Abundance"].mean().reset_index()

        pivot_df = condition_means.pivot_table(
            index=id_cols,
            columns="Condition",
            values="PTM_Relative_Abundance",
            fill_value=np.nan,
        ).reset_index()

        control_pseudo_count = None
        if "Control" in pivot_df.columns:
            vals = pivot_df["Control"].dropna()
            vals = vals[vals > 0]
            control_pseudo_count = vals.min() * 0.005 if len(vals) > 0 else 1e-6

        treatments = self.treatment_conditions if self.treatment_conditions else [
            c for c in pivot_df.columns
            if c not in id_cols + ["Control"]
        ]

        # --- Build replicate-level lookup for t-test ---
        # Group replicate values by (PTM site, Condition)
        replicate_groups = relative_quant_df.groupby(
            id_cols + ["Condition"]
        )["PTM_Relative_Abundance"].apply(list).reset_index()
        replicate_groups.rename(columns={"PTM_Relative_Abundance": "replicate_values"}, inplace=True)

        # Create a lookup dict: (Protein.Group, Precursor.Id, Condition) -> list of replicate values
        replicate_lookup = {}
        for _, rrow in replicate_groups.iterrows():
            key = (rrow["Protein.Group"], rrow["Precursor.Id"], rrow["Condition"])
            replicate_lookup[key] = rrow["replicate_values"]

        results = []
        for treatment in treatments:
            if treatment not in pivot_df.columns or "Control" not in pivot_df.columns:
                continue
            for _, row in pivot_df.iterrows():
                control_value = row["Control"]
                treatment_value = row[treatment]
                control_adj = control_value if pd.notna(control_value) and control_value > 0 else control_pseudo_count
                if not (pd.notna(treatment_value) and treatment_value > 0):
                    continue

                log2_fc = np.log2(treatment_value / control_adj)
                used_pc = not (pd.notna(control_value) and control_value > 0)

                # --- Welch's t-test ---
                p_value = np.nan
                ctrl_reps = replicate_lookup.get((row["Protein.Group"], row["Precursor.Id"], "Control"), [])
                treat_reps = replicate_lookup.get((row["Protein.Group"], row["Precursor.Id"], treatment), [])

                if len(ctrl_reps) >= 2 and len(treat_reps) >= 2:
                    try:
                        _, p_value = stats.ttest_ind(
                            ctrl_reps, treat_reps, equal_var=False, nan_policy="omit"
                        )
                    except Exception:
                        p_value = np.nan
                elif used_pc:
                    # De novo PTMs: no control replicates → p_value stays NaN
                    pass
                # If only 1 replicate per group, p_value stays NaN

                results.append({
                    "Protein.Group": row["Protein.Group"],
                    "Precursor.Id": row["Precursor.Id"],
                    "Modified.Sequence": row["Modified.Sequence"],
                    "PTM_Type": row["PTM_Type"],
                    "PTM_Position": row["PTM_Position"],
                    "Condition": treatment,
                    "Comparison": f"{treatment}_vs_Control",
                    "Control_Mean": control_value if not used_pc else control_pseudo_count,
                    "Treatment_Mean": treatment_value,
                    "Log2FC": log2_fc,
                    "Fold_Change": 2 ** log2_fc,
                    "Control_Pseudocount_Used": used_pc,
                    "p_value": p_value,
                    "Control_N": len(ctrl_reps),
                    "Treatment_N": len(treat_reps),
                })

        if results:
            df = pd.DataFrame(results)

            # --- Benjamini-Hochberg correction ---
            valid_mask = df["p_value"].notna()
            if valid_mask.sum() > 0:
                _, q_values, _, _ = multipletests(
                    df.loc[valid_mask, "p_value"].values,
                    alpha=0.05,
                    method="fdr_bh",
                )
                df.loc[valid_mask, "q_value"] = q_values
            else:
                df["q_value"] = np.nan

            # Fill NaN q_value for entries without valid p_value
            if "q_value" not in df.columns:
                df["q_value"] = np.nan

            n_tested = valid_mask.sum()
            n_sig = (df["q_value"] < 0.05).sum() if "q_value" in df.columns else 0
            from ptm_shared.de_novo_representation import attach_de_novo_fields

            df = attach_de_novo_fields(
                df, relative_quant_df, condition_map=self.condition_map,
            )
            n_denovo = int(df["Conventional_Log2FC_NA"].sum()) if "Conventional_Log2FC_NA" in df.columns else 0
            logger.info(
                f"Condition comparisons: {len(df)} records, "
                f"t-test performed: {n_tested}, "
                f"significant (q<0.05): {n_sig}, "
                f"de_novo_rows={n_denovo}"
            )
            return df
        return pd.DataFrame()

    # ------------------------------------------------------------------
    # Protein-level changes
    # ------------------------------------------------------------------

    def calculate_protein_level_changes(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        try:
            ptm_proteins_set = set(
                self.pr_matrix_normalized[
                    self.pr_matrix_normalized["Modified.Sequence"].str.contains(r"UniMod:(1|21)", na=False, regex=True)
                ]["Protein.Group"].unique()
            )

            control_samples = [s for s, c in self.condition_map.items() if c == "Control"]
            treatment_samples_dict = {
                t: [s for s, c in self.condition_map.items() if c == t]
                for t in self.treatment_conditions
            }

            pg = self.pg_matrix_normalized.copy()
            ctrl_cols = [c for c in control_samples if c in pg.columns]
            pg["Control_Mean"] = pg[ctrl_cols].replace(0, np.nan).mean(axis=1) if ctrl_cols else np.nan

            for treatment, samples in treatment_samples_dict.items():
                tcols = [c for c in samples if c in pg.columns]
                pg[f"{treatment}_Mean"] = pg[tcols].replace(0, np.nan).mean(axis=1) if tcols else np.nan

            changes = []
            for idx, row in pg.iterrows():
                protein_group = row["Protein.Group"]
                control_mean = row["Control_Mean"]
                protein_name = self._resolve_protein_name(protein_group)
                gene_name = self._resolve_gene_name(protein_group)
                has_ptm = protein_group in ptm_proteins_set

                for treatment in self.treatment_conditions:
                    treatment_mean = row[f"{treatment}_Mean"]
                    if pd.notna(control_mean) and pd.notna(treatment_mean) and control_mean > 0 and treatment_mean > 0:
                        log2fc = np.log2(treatment_mean / control_mean)
                        changes.append({
                            "Protein.Group": protein_group,
                            "Protein.Name": protein_name,
                            "Gene.Name": gene_name,
                            "Has_PTM": has_ptm,
                            "Condition": treatment,
                            "Comparison": f"{treatment}_vs_Control",
                            "Control_Mean": control_mean,
                            "Treatment_Mean": treatment_mean,
                            "Log2FC": log2fc,
                            "Fold_Change": 2 ** log2fc,
                        })

            all_df = pd.DataFrame(changes)
            ptm_df = all_df[all_df["Has_PTM"] == True].copy()
            logger.info(f"Protein-level: all={len(all_df)}, ptm={len(ptm_df)}")
            return all_df, ptm_df
        except Exception as e:
            logger.error(f"Protein-level calculation failed: {e}", exc_info=True)
            return pd.DataFrame(), pd.DataFrame()

    # ------------------------------------------------------------------
    # PTM vector data
    # ------------------------------------------------------------------

    def create_ptm_vector_data(
        self,
        ptm_comparisons: pd.DataFrame,
        ptm_protein_changes: pd.DataFrame,
        paired_occupancy_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        try:
            vector_data = []
            occupancy_lookup: Dict[Tuple[str, str, str], Dict[str, object]] = {}
            if paired_occupancy_df is not None and not paired_occupancy_df.empty:
                for _, occupancy_row in paired_occupancy_df.iterrows():
                    occupancy_lookup[(
                        str(occupancy_row.get("Protein.Group", "")),
                        str(occupancy_row.get("Modified.Sequence", "")),
                        str(occupancy_row.get("Condition", "")),
                    )] = occupancy_row.to_dict()
            treatments = self.treatment_conditions or [
                c for c in ptm_comparisons["Condition"].unique() if c != "Control"
            ]

            for _, ptm_row in ptm_comparisons.iterrows():
                protein_group = ptm_row["Protein.Group"]
                condition = ptm_row["Condition"]

                pchange = ptm_protein_changes[
                    (ptm_protein_changes["Protein.Group"] == protein_group)
                    & (ptm_protein_changes["Condition"] == condition)
                ]
                if pchange.empty:
                    continue

                pc = pchange.iloc[0]
                occupancy = occupancy_lookup.get((
                    str(protein_group), str(ptm_row["Modified.Sequence"]), str(condition)
                ), {})
                cmeans: Dict[str, float] = {
                    "Control_Mean_PTM_Relative": ptm_row["Control_Mean"],
                    "Control_Mean_Protein": pc["Control_Mean"],
                    "Treatment_Mean_Protein": pc["Treatment_Mean"],
                    "Protein_Log2FC": pc["Log2FC"],
                    "Protein_Fold_Change": pc["Fold_Change"],
                }

                for cond in treatments:
                    cond_data = ptm_comparisons[
                        (ptm_comparisons["Protein.Group"] == protein_group)
                        & (ptm_comparisons["Precursor.Id"] == ptm_row["Precursor.Id"])
                        & (ptm_comparisons["Condition"] == cond)
                    ]
                    cmeans[f"{cond}_Mean_PTM_Relative"] = (
                        cond_data.iloc[0]["Treatment_Mean"] if not cond_data.empty else np.nan
                    )

                vector_data.append({
                    "Protein.Group": protein_group,
                    "Protein.Name": pc["Protein.Name"],
                    "Gene.Name": pc["Gene.Name"],
                    "Modified.Sequence": ptm_row["Modified.Sequence"],
                    "PTM_Type": ptm_row["PTM_Type"],
                    "PTM_Position": ptm_row["PTM_Position"],
                    "Condition": condition,
                    "Comparison": ptm_row["Comparison"],
                    "PTM_Relative_Log2FC": ptm_row["Log2FC"],
                    "PTM_Absolute_Log2FC": ptm_row["Log2FC"] + cmeans.get("Protein_Log2FC", 0),
                    "Residual": ptm_row["Log2FC"],
                    "Has_PTM": True,
                    "Data_Type": "PTM",
                    "Control_Pseudocount_Used": ptm_row.get("Control_Pseudocount_Used", False),
                    "p_value": ptm_row.get("p_value", np.nan),
                    "q_value": ptm_row.get("q_value", np.nan),
                    "Detection_Control": ptm_row.get("Detection_Control", ""),
                    "Detection_Treatment": ptm_row.get("Detection_Treatment", ""),
                    "Detection_Pattern": ptm_row.get("Detection_Pattern", ""),
                    "DeNovo_Confidence": ptm_row.get("DeNovo_Confidence", ""),
                    "LOD_Intensity": ptm_row.get("LOD_Intensity", np.nan),
                    "LOD_Percentile": ptm_row.get("LOD_Percentile", np.nan),
                    "LOD_Relative_Log2": ptm_row.get("LOD_Relative_Log2", np.nan),
                    "Peak_Condition": ptm_row.get("Peak_Condition", ""),
                    "Peak_Is_Provisional": ptm_row.get("Peak_Is_Provisional", False),
                    "Peak_Normalized_Log2_Intensity": ptm_row.get("Peak_Normalized_Log2_Intensity", np.nan),
                    "Peak_Protein_Normalized_Abundance": ptm_row.get("Peak_Protein_Normalized_Abundance", np.nan),
                    "Onset_Condition": ptm_row.get("Onset_Condition", ""),
                    "Reliable_Onset_Condition": ptm_row.get("Reliable_Onset_Condition", ""),
                    "Shared_Peptide": ptm_row.get("Shared_Peptide", False),
                    "Conventional_Log2FC_NA": ptm_row.get("Conventional_Log2FC_NA", False),
                    "Ranking_Score": ptm_row.get("Ranking_Score", np.nan),
                    "Normalized_Log2_Intensity": ptm_row.get("Normalized_Log2_Intensity", np.nan),
                    "Treatment_CV": ptm_row.get("Treatment_CV", np.nan),
                    "Detection_N": ptm_row.get("Detection_N", np.nan),
                    "Detection_Expected": ptm_row.get("Detection_Expected", np.nan),
                    # Track 1 fields are additive.  Existing Track 2 consumers can
                    # continue to use PTM_Relative_Log2FC unchanged.
                    "Quantification_Track": occupancy.get("Quantification_Track", "protein_normalized_relative_ptm"),
                    "Paired_Peptide_Key": occupancy.get("Paired_Peptide_Key", ""),
                    "Paired_Form_Level": occupancy.get("Paired_Form_Level", ""),
                    "Occupancy_Fraction": occupancy.get("Occupancy_Fraction", np.nan),
                    "Occupancy_Percent": occupancy.get("Occupancy_Percent", np.nan),
                    "Occupancy_Control_Fraction": occupancy.get("Occupancy_Control_Fraction", np.nan),
                    "Occupancy_Delta_PP": occupancy.get("Occupancy_Delta_PP", np.nan),
                    "Occupancy_Logit_Delta": occupancy.get("Occupancy_Logit_Delta", np.nan),
                    "Occupancy_Calibration_Type": occupancy.get("Occupancy_Calibration_Type", "none"),
                    "Pair_Quality_Tier": occupancy.get("Pair_Quality_Tier", "O0"),
                    "Pair_Missingness": occupancy.get("Pair_Missingness", np.nan),
                    "Occupancy_P_Value": occupancy.get("Occupancy_P_Value", np.nan),
                    "Occupancy_Q_Value": occupancy.get("Occupancy_Q_Value", np.nan),
                    "Occupancy_N": occupancy.get("Occupancy_N", np.nan),
                    "Occupancy_Control_N": occupancy.get("Occupancy_Control_N", np.nan),
                    **cmeans,
                })

            if vector_data:
                vdf = pd.DataFrame(vector_data)
                logger.info(f"PTM vector data: {len(vdf)} records")
                return vdf
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Vector data creation failed: {e}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Save results
    # ------------------------------------------------------------------

    def save_results(
        self,
        relative_quant_df: pd.DataFrame,
        ptm_comparisons: pd.DataFrame,
        all_protein_changes: pd.DataFrame,
        ptm_protein_changes: pd.DataFrame,
        ptm_vector_df: pd.DataFrame,
        pair_audit_df: Optional[pd.DataFrame] = None,
    ):
        sfx = self.file_suffix

        if not relative_quant_df.empty:
            p = self.output_dir / f"site_level_relative_quantification_normalized{sfx}.tsv"
            relative_quant_df.to_csv(p, sep="\t", index=False)
            logger.info(f"Saved: {p.name}")

        if not ptm_comparisons.empty:
            p = self.output_dir / f"ptm_condition_comparisons_normalized{sfx}.tsv"
            ptm_comparisons.to_csv(p, sep="\t", index=False)
            logger.info(f"Saved: {p.name}")

        if not all_protein_changes.empty:
            p = self.output_dir / f"all_protein_level_changes_normalized{sfx}.tsv"
            all_protein_changes.to_csv(p, sep="\t", index=False)
            logger.info(f"Saved: {p.name}")

        if not ptm_protein_changes.empty:
            p = self.output_dir / f"ptm_protein_level_changes_normalized{sfx}.tsv"
            ptm_protein_changes.to_csv(p, sep="\t", index=False)
            logger.info(f"Saved: {p.name}")

        if not ptm_vector_df.empty:
            p = self.output_dir / f"ptm_vector_data_normalized{sfx}.tsv"
            ptm_vector_df.to_csv(p, sep="\t", index=False)
            logger.info(f"Saved: {p.name}")

            if self.motif_analyzer:
                self._perform_enhanced_motif_analysis(ptm_vector_df)

        if pair_audit_df is not None:
            p = self.output_dir / f"paired_peptide_occupancy_audit{sfx}.tsv"
            pair_audit_df.to_csv(p, sep="\t", index=False)
            logger.info(f"Saved paired occupancy audit: {p.name}")

        self._save_analysis_summary(relative_quant_df, ptm_comparisons, all_protein_changes, ptm_vector_df)

    def _perform_enhanced_motif_analysis(self, ptm_vector_df: pd.DataFrame):
        try:
            ptm_with_motifs = self.motif_analyzer.analyze_motifs_simple(ptm_vector_df)
            p = self.output_dir / f"ptm_vector_data_with_motifs{self.file_suffix}.tsv"
            ptm_with_motifs.to_csv(p, sep="\t", index=False)
            logger.info(f"Saved motif results: {p.name}")

            summary_file = self.output_dir / f"motif_analysis_summary{self.file_suffix}.txt"
            self.motif_analyzer.generate_motif_summary(ptm_with_motifs, str(summary_file))

            viz = self.motif_analyzer.create_motif_visualization_data(ptm_with_motifs)
            if not viz.empty:
                vp = self.output_dir / f"motif_visualization_data{self.file_suffix}.tsv"
                viz.to_csv(vp, sep="\t", index=False)
        except Exception as e:
            logger.warning(f"Enhanced motif analysis failed: {e}")

    def _save_analysis_summary(self, relative_quant_df, ptm_comparisons, all_protein_changes, ptm_vector_df):
        try:
            p = self.output_dir / f"analysis_summary_normalized{self.file_suffix}.txt"
            with open(p, "w", encoding="utf-8") as f:
                f.write("PTM Relative Quantification Analysis Summary (Normalized)\n")
                f.write("=" * 60 + "\n\n")
                f.write(f"PTM Mode: {self.ptm_mode.upper()} ({self.ptm_mode_config['name']})\n")
                f.write(f"UniMod ID: {self.ptm_mode_config['unimod_id']}\n")
                f.write(f"Target residues: {', '.join(self.ptm_mode_config['residues'])}\n\n")
                f.write(f"Samples: {len(self.sample_columns)}\n")
                f.write(f"PR Matrix precursors: {len(self.pr_matrix):,}\n")
                f.write(f"PG Matrix protein groups: {len(self.pg_matrix):,}\n")
                f.write(f"FASTA proteins: {len(self.fasta_dict):,}\n\n")
                if not relative_quant_df.empty:
                    f.write(f"Site-level quantification: {len(relative_quant_df):,}\n")
                    f.write(f"Condition comparisons: {len(ptm_comparisons):,}\n")
                    f.write(f"PTM vectors: {len(ptm_vector_df):,}\n")
                f.write(f"\nTimestamp: {pd.Timestamp.now()}\n")
        except Exception as e:
            logger.warning(f"Summary save failed: {e}")
