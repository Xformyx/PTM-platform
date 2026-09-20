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
import json
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
        sample_manifest: Optional[dict] = None,
        normalization_policy: str = "legacy_median.v1",
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
        self.sample_manifest = sample_manifest or {}
        if normalization_policy not in {"legacy_median.v1", "already_normalized.v1"}:
            raise ValueError("Unsupported normalization policy")
        self.normalization_policy = normalization_policy
        self.condition_map = condition_map if condition_map else {}
        self.external_condition_map = condition_map is not None
        self.available_conditions: List[str] = []
        self.treatment_conditions: List[str] = []
        self.fasta_dict: Dict[str, str] = {}
        self.fasta_reference_candidates: Dict[str, List[str]] = {}
        self._mapping_cache: Dict[Tuple[str, str, str], dict] = {}
        self._pg_lookup: Optional[pd.DataFrame] = None
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

            from ptm_shared.sample_manifest import validate_sample_manifest
            if self.sample_manifest.get("samples"):
                self.sample_manifest = validate_sample_manifest(self.sample_manifest, self.condition_map, self.pr_matrix.columns, self.pg_matrix.columns)
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

            self._progress(0.45, "Independent unadjusted PTM comparisons")
            unadjusted_ptm_comparisons = self.calculate_unadjusted_condition_comparisons(ptm_precursors)

            self._progress(0.50, "Protein-adjusted condition comparisons")
            ptm_comparisons = self.calculate_condition_comparisons(relative_quant_df)
            if ptm_comparisons.empty:
                return False

            self._progress(0.60, "Protein-level changes")
            all_protein_changes, ptm_protein_changes = self.calculate_protein_level_changes()

            self._progress(0.75, "PTM vector data")
            ptm_vector_df = self.create_ptm_vector_data(
                ptm_comparisons,
                ptm_protein_changes,
                paired_occupancy_df,
                unadjusted_ptm_comparisons=unadjusted_ptm_comparisons,
            )
            if ptm_vector_df.empty:
                return False

            self._progress(0.85, "Saving results")
            self.save_results(
                relative_quant_df, ptm_comparisons,
                all_protein_changes, ptm_protein_changes, ptm_vector_df, pair_audit_df,
                unadjusted_ptm_comparisons=unadjusted_ptm_comparisons,
            )
            self._write_observation_inventory(ptm_vector_df.to_dict('records'))

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

            from collections import defaultdict
            references, descriptions = defaultdict(set), defaultdict(set)
            for record in SeqIO.parse(self.fasta_path, "fasta"):
                uniprot_id = self._extract_uniprot_id(record.id)
                if uniprot_id:
                    references[uniprot_id].add(str(record.seq))
                    descriptions[uniprot_id].add(self._extract_protein_and_gene_info(record.description))
            self.fasta_reference_candidates = {key: sorted(values) for key, values in references.items()}
            self.fasta_dict = {key: next(iter(values)) for key, values in references.items() if len(values) == 1}
            self._mapping_cache = {}
            for key, values in descriptions.items():
                self.protein_names[key] = next(iter(values))[0] if len(values) == 1 else "Unknown protein"
                self.gene_names[key] = next(iter(values))[1] if len(values) == 1 else "Unknown"

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
        """Build Protein.Group → Genes map from DIA-NN PR/PG matrices.

        구현 대상: 기존 DIA-NN Genes 컬럼 조회. 매핑 규칙은 동일하다.
        사전등록: 2026-09-20 운영 정정. 177k PR `iterrows` 가 23분·OOM 전조였다.
        해석 한계: 저장 값은 이전과 같다. 순회만 벡터화했다.
        주장 금지: gene map 속도가 정량 정확도를 바꿨다고 쓰지 않는다.
        """
        self.diann_genes = {}
        for df in (getattr(self, "pg_matrix", None), getattr(self, "pr_matrix", None)):
            if df is None or "Genes" not in df.columns or "Protein.Group" not in df.columns:
                continue
            subset = df.loc[:, ["Protein.Group", "Genes"]].drop_duplicates("Protein.Group")
            pgs = subset["Protein.Group"].astype(str).to_numpy()
            genes = subset["Genes"].astype(str).str.strip().to_numpy()
            for pg, gene in zip(pgs, genes):
                if pg in self.diann_genes:
                    continue
                if gene and gene.lower() not in ("nan", "unknown"):
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
            from ptm_shared.tabular_import import read_quantitative_tsv
            self.pr_matrix = read_quantitative_tsv(self.pr_matrix_path, self.output_dir)
            logger.info(f"PR Matrix loaded: {len(self.pr_matrix):,} precursors")

            if not os.path.exists(self.pg_matrix_path):
                logger.error(f"PG Matrix not found: {self.pg_matrix_path}")
                return False
            self.pg_matrix = read_quantitative_tsv(self.pg_matrix_path, self.output_dir)
            logger.info(f"PG Matrix loaded: {len(self.pg_matrix):,} protein groups")
            # Conflicting denominator rows are not resolved by file order.
            self.pg_matrix = self.pg_matrix.drop_duplicates()
            if 'Protein.Group' in self.pg_matrix:
                conflicts = self.pg_matrix.duplicated('Protein.Group', keep=False)
                if conflicts.any():
                    from ptm_shared.report_revision import _atomic_json, file_sha256
                    _atomic_json(self.output_dir / ('protein_denominator_conflicts_' + file_sha256(self.pg_matrix_path) + '.json'),
                                 self.pg_matrix.loc[conflicts].to_dict('records'))
                    self.pg_matrix = self.pg_matrix.loc[~conflicts].copy()

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
            # Full-row inventory JSON was written here and peaked memory before
            # any contrast existed. Raw PR is kept on self.pr_matrix; the
            # completion write below records the same rows once.
            return True
        except Exception as e:
            logger.error(f"Data loading failed: {e}")
            return False

    def _write_observation_inventory(self, analysis_records=None):
        """Record input-row accounting without duplicating the PR matrix.

        구현 대상: docs/implementation/ptm-report-contract-map.md 원자료 전수 기록
        사전등록: 2026-09-20 운영 정정. 측정값 변경 없음. 표시·회계 직렬화만 축소.
        해석 한계: inventory는 입력 행 목록이며 정량 estimator가 아니다.
        주장 금지: 이 파일 존재로 전수 검열 완료나 생물 재현성을 주장하지 않는다.

        Sample intensities and per-sample QC stay in the source PR TSV. Records
        keep identity, status and a content hash so Report can bind coverage
        without loading a second copy of every intensity column.
        """
        import hashlib
        from ptm_shared.report_revision import file_sha256, _atomic_json
        if self.pr_matrix is None or self.pr_matrix.empty:
            return
        source_hash = file_sha256(self.pr_matrix_path)
        identity_cols = [c for c in ("Protein.Group", "Precursor.Id", "Modified.Sequence", "Precursor.Charge") if c in self.pr_matrix]
        distinct = self.pr_matrix.drop_duplicates()
        conflicts = distinct.loc[distinct.duplicated(identity_cols, keep=False), identity_cols]
        conflict_keys = {tuple(str(x) for x in row) for row in conflicts.itertuples(index=False, name=None)}
        seen, records = set(), []

        def logical_key(row):
            return tuple("" if pd.isna(row.get(c)) else str(row.get(c)) for c in identity_cols)

        processed_keys = {logical_key(row) for row in (analysis_records or [])}
        source_locators = self.pr_matrix.attrs.get("source_row_locators", [])
        identity_frame = self.pr_matrix[identity_cols].copy()
        sequences = identity_frame["Modified.Sequence"].astype(str) if "Modified.Sequence" in identity_frame else pd.Series("", index=self.pr_matrix.index)
        target_pat = re.compile("|".join(rf"UniMod:{re.escape(str(uid))}\b" for uid in self.target_ptms)) if self.target_ptms else None
        for row_index, ident in enumerate(identity_frame.itertuples(index=False, name=None)):
            if row_index % 50000 == 0:
                (getattr(self, "_progress", None) or (lambda _p, _m: None))(
                    0.86, f"Observation inventory {row_index}/{len(identity_frame)}"
                )
            row_number = source_locators[row_index]["start_line"] if row_index < len(source_locators) else row_index + 2
            identity = {col: (None if pd.isna(val) else val) for col, val in zip(identity_cols, ident)}
            content_id = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
            key = tuple("" if val is None else str(val) for val in identity.values())
            target = bool(target_pat and target_pat.search(str(sequences.iloc[row_index])))
            reason = ('conflicting_duplicate' if key in conflict_keys else 'exact_duplicate' if content_id in seen
                      else 'not_requested_ptm' if not target else 'eligible_pending_analysis')
            seen.add(content_id)
            record = {'observation_content_id': content_id, 'source_row': row_number,
                      'source_dataset_sha256': source_hash, 'identity': identity,
                      'analysis_status': 'pending' if reason == 'eligible_pending_analysis' else 'excluded',
                      'reason': reason, 'sample_observations_ref': 'source_pr_matrix'}
            if reason == 'eligible_pending_analysis' and analysis_records is not None:
                matched = key in processed_keys
                record.update(analysis_status='processed' if matched else 'not_evaluable',
                              reason='contrast_inventory_created' if matched else 'no_eligible_contrast')
            records.append(record)
        inventory = {'schema_version': 'source_observation_inventory.v1', 'record_payload': 'identity_status_only',
                     'source_dataset_sha256': source_hash, 'input_rows': len(records),
                     'input_sample_observations': len(records) * len(self.sample_columns),
                     'normalization_policy': self.normalization_policy, 'records': records}
        inventory['import_accounting'] = self.pr_matrix.attrs.get('import_accounting', {})
        inventory['analysis_completed'] = analysis_records is not None
        inventory['condition_map'] = self.condition_map
        inventory['sample_manifest'] = self.sample_manifest
        inventory_hash = hashlib.sha256(json.dumps(inventory, sort_keys=True, default=str).encode()).hexdigest()
        path = self.output_dir / ('observation_inventory_' + inventory_hash + '.json')
        if not path.exists():
            _atomic_json(path, inventory)
        _atomic_json(self.output_dir / 'observation_inventory_current.json', {'filename': path.name, 'sha256': file_sha256(path)})

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
            self._pg_lookup = None
            logger.info("Median normalization complete")
            return True
        except Exception as e:
            logger.error(f"Normalization failed: {e}")
            return False

    def _normalize_matrix(self, matrix: pd.DataFrame, sample_columns: List[str], matrix_type: str) -> Dict[str, float]:
        if getattr(self, "normalization_policy", "legacy_median.v1") == "already_normalized.v1":
            return {sample: 1.0 for sample in sample_columns}
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
            pattern = rf"UniMod:{uid}\b"
            matched = self.pr_matrix_normalized[
                self.pr_matrix_normalized["Modified.Sequence"].str.contains(pattern, na=False)
            ]
            logger.info(f"{name} (UniMod:{uid}): {len(matched):,}")
            parts.append(matched)

        if parts:
            df = pd.concat(parts, ignore_index=True).drop_duplicates()
            identity_cols = [c for c in ("Protein.Group", "Precursor.Id", "Modified.Sequence", "Precursor.Charge") if c in df]
            conflicts = df.duplicated(subset=identity_cols, keep=False)
            self.conflicting_precursors = df.loc[conflicts].to_dict("records")
            # Keep conflicts in an audit artifact; never choose a last-write winner.
            if conflicts.any():
                (self.output_dir / "conflicting_precursors.json").write_text(
                    json.dumps(self.conflicting_precursors, default=str, sort_keys=True), encoding="utf-8")
            df = df.loc[~conflicts].sort_values(identity_cols).reset_index(drop=True)
            logger.info(f"Filtered PTMs: {len(df):,}")
            return df
        return pd.DataFrame()

    # ------------------------------------------------------------------
    # Site-level relative quantification
    # ------------------------------------------------------------------

    def _protein_group_row(self, protein_group) -> object:
        """Return the first PG row for a group without scanning the matrix each time."""
        pg = self.pg_matrix_normalized
        if pg is None or pg.empty or "Protein.Group" not in pg.columns:
            return {}
        if getattr(self, "_pg_lookup", None) is None:
            # Conflicting Protein.Group rows were already dropped in load_data.
            self._pg_lookup = pg.drop_duplicates("Protein.Group").set_index("Protein.Group", drop=False)
        try:
            hit = self._pg_lookup.loc[protein_group]
        except KeyError:
            return {}
        return hit.iloc[0] if isinstance(hit, pd.DataFrame) else hit

    def calculate_site_level_relative_quantification(self, ptm_precursors: pd.DataFrame) -> pd.DataFrame:
        """Retain the sample grid and independent PR, PG and paired-ratio masks."""
        results = []
        n_precursors = len(ptm_precursors)
        for row_index, (_, row) in enumerate(ptm_precursors.iterrows()):
            if row_index % 200 == 0:
                (getattr(self, "_progress", None) or (lambda _p, _m: None))(
                    0.30, f"Site-level relative quantification {row_index}/{n_precursors}"
                )
            protein_group = row["Protein.Group"]
            precursor_id = row["Precursor.Id"]
            modified_sequence = row["Modified.Sequence"]
            ptm_type = self._determine_ptm_type(modified_sequence)
            source_fields = self._source_fields(row)
            ptm_position = self._extract_ptm_position(protein_group, modified_sequence, ptm_type)
            protein_row = self._protein_group_row(protein_group)
            for sample in self.sample_columns:
                ptm_intensity = row.get(sample, np.nan)
                protein_intensity = protein_row.get(sample, np.nan)
                pr_observed = bool(pd.notna(ptm_intensity) and np.isfinite(ptm_intensity) and ptm_intensity > 0)
                pg_observed = bool(pd.notna(protein_intensity) and np.isfinite(protein_intensity) and protein_intensity > 0)
                paired = pr_observed and pg_observed

                results.append({
                    **source_fields,
                    "Protein.Group": protein_group,
                    "Precursor.Id": precursor_id,
                    "Modified.Sequence": modified_sequence,
                    "PTM_Type": ptm_type,
                    "PTM_Position": ptm_position,
                    "Gene.Name": self._resolve_gene_name(protein_group),
                    "Sample": sample,
                    "Condition": self.condition_map.get(sample, "Unknown"),
                    "PTM_Intensity": ptm_intensity if pr_observed else np.nan,
                    "Protein_Intensity": protein_intensity if pg_observed else np.nan,
                    "PR_Observed": pr_observed,
                    "PG_Observed": pg_observed,
                    "Paired_Ratio_Observed": paired,
                    "PTM_Relative_Abundance": ptm_intensity / protein_intensity if paired else np.nan,
                    "Adjusted_Missing_Reason": (
                        "" if paired else "protein_denominator_unavailable" if pr_observed else "ptm_not_detected"
                    ),
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

        구현 대상: 기존 apparent paired occupancy (intensity fraction, uncalibrated).
        사전등록: 2026-09-20 운영 정정. estimator·임계(PAIR_MIN_*)는 유지.
        해석 한계: 반응계수 보정 없는 겉보기 occupancy이며 절대 occupancy가 아니다.
        주장 금지: 이 값으로 점유율·kinase 활성을 주장하지 않는다.

        Grouped sums replace per-row Series copies. Positive finite intensities
        are still summed per peptide form; missing modified or unmodified values
        remain missing and are never converted to zero.
        """
        if ptm_precursors is None or ptm_precursors.empty or self.pr_matrix_normalized is None:
            return pd.DataFrame(), pd.DataFrame()
        samples = [sample for sample in self.sample_columns if sample in self.pr_matrix_normalized.columns]
        if not samples:
            return pd.DataFrame(), pd.DataFrame()

        def _positive(frame: pd.DataFrame) -> pd.DataFrame:
            numeric = frame[samples].apply(pd.to_numeric, errors="coerce")
            return numeric.where(np.isfinite(numeric) & (numeric > 0))

        def _join_ids(series: pd.Series) -> str:
            return ";".join(sorted({str(value) for value in series.dropna() if str(value) not in {"", "nan"}}))

        pr = self.pr_matrix_normalized
        pr_seq = pr["Modified.Sequence"].astype(str) if "Modified.Sequence" in pr.columns else pd.Series("", index=pr.index)
        pr_pg = pr["Protein.Group"].astype(str) if "Protein.Group" in pr.columns else pd.Series("", index=pr.index)
        counterpart = pr_seq.map(self._is_unmodified_target_counterpart)
        backbone = pr_seq.map(self._clean_peptide_backbone)
        unmod_work = pd.concat([
            pr_pg.rename("_pg"), backbone.rename("_bb"),
            pr["Precursor.Id"] if "Precursor.Id" in pr.columns else pd.Series(index=pr.index, dtype=object),
            _positive(pr),
        ], axis=1).loc[counterpart & backbone.ne("") & pr_pg.ne("")]
        unmod_sums = unmod_work.groupby(["_pg", "_bb"], sort=False)[samples].sum(min_count=1)
        unmod_ids = unmod_work.groupby(["_pg", "_bb"], sort=False)["Precursor.Id"].agg(_join_ids) if "Precursor.Id" in unmod_work.columns else pd.Series(dtype=object)

        mod_work = pd.concat([
            ptm_precursors["Protein.Group"].astype(str).rename("_pg"),
            ptm_precursors["Modified.Sequence"].astype(str).rename("_seq"),
            ptm_precursors["Precursor.Id"] if "Precursor.Id" in ptm_precursors.columns else pd.Series(index=ptm_precursors.index, dtype=object),
            _positive(ptm_precursors),
        ], axis=1)
        mod_sums = mod_work.groupby(["_pg", "_seq"], sort=False)[samples].sum(min_count=1)
        mod_ids = mod_work.groupby(["_pg", "_seq"], sort=False)["Precursor.Id"].agg(_join_ids) if "Precursor.Id" in mod_work.columns else pd.Series(dtype=object)

        expected_conditions = sorted(set(self.condition_map.get(sample, "Unknown") for sample in samples))
        records: List[Dict[str, object]] = []
        audits: List[Dict[str, object]] = []
        for form_index, ((protein_group, modified_sequence), mod_row) in enumerate(mod_sums.iterrows()):
            if form_index % 2000 == 0:
                (getattr(self, "_progress", None) or (lambda _p, _m: None))(
                    0.40, f"Paired modified/unmodified audit {form_index}/{len(mod_sums)}"
                )
            modified_precursor_ids = str(mod_ids.get((protein_group, modified_sequence), ""))
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
            unmod_key = (protein_group, backbone)
            if unmod_key not in unmod_sums.index:
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
            unmod_row = unmod_sums.loc[unmod_key]
            condition_values: Dict[str, List[float]] = {}
            condition_samples: Dict[str, Dict[str, float]] = {}
            missing_reasons: Dict[str, str] = {}
            for sample in samples:
                condition = self.condition_map.get(sample, "Unknown")
                modified_intensity = mod_row[sample]
                unmodified_intensity = unmod_row[sample]
                if pd.isna(modified_intensity) or pd.isna(unmodified_intensity):
                    missing_reasons.setdefault(condition, "missing_modified" if pd.isna(modified_intensity) else "missing_unmodified")
                    continue
                denominator = float(modified_intensity) + float(unmodified_intensity)
                if denominator <= 0:
                    missing_reasons.setdefault(condition, "invalid_pair_denominator")
                    continue
                ratio = float(modified_intensity) / denominator
                condition_values.setdefault(condition, []).append(ratio)
                condition_samples.setdefault(condition, {})[sample] = ratio

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
                "Unmodified_Precursor_Ids": str(unmod_ids.get(unmod_key, "")),
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
                from ptm_shared.sample_manifest import compare_sample_units
                test = compare_sample_units(condition_samples["Control"], condition_samples[condition], getattr(self, "sample_manifest", None))
                p_value = test["p_value"] if test["p_value"] is not None else np.nan
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
                    "Occupancy_Statistical_Unit": test["statistical_unit"],
                    "Occupancy_Test_Status": test["status"],
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

    def _mapping_references(self):
        """Reuse the already-built FASTA index. Never copy 54k sequences per call.

        구현 대상: peptide_mapping_assertion.v1 입력 참조 사전.
        사전등록: 2026-09-20 운영 정정. `{**fasta_dict, **candidates}` 매 호출 복사가
        Order 80 SIGKILL의 원인 중 하나였다. 조회 결과는 동일하다.
        해석 한계: 참조 사전을 한 번만 넘긴다. 매핑 규칙·status는 바꾸지 않는다.
        주장 금지: 이 캐시로 site 좌표 정확도가 올랐다고 쓰지 않는다.
        """
        candidates = getattr(self, "fasta_reference_candidates", None)
        if candidates:
            return candidates
        return getattr(self, "fasta_dict", {}) or {}

    def _mapping_assertion(self, protein_id, modified_sequence, ptm_type=None):
        from ptm_shared.site_form_provenance import peptide_mapping_assertion
        ptm_type = ptm_type or self._determine_ptm_type(modified_sequence)
        cache_key = (str(protein_id), str(modified_sequence), str(ptm_type))
        cache = getattr(self, "_mapping_cache", None)
        if cache is None:
            self._mapping_cache = cache = {}
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        targets = [uid for uid, info in VARIABLE_MODIFICATIONS.items() if info["name"] == ptm_type]
        payload = peptide_mapping_assertion(
            protein_id, modified_sequence, self._mapping_references(), targets,
        )
        cache[cache_key] = payload
        return payload

    def _extract_ptm_position(self, protein_id: str, modified_sequence: str, ptm_type: str = None) -> str:
        mapping = self._mapping_assertion(protein_id, modified_sequence, ptm_type)
        if mapping["status"] == "unique" and mapping["candidate_positions"]:
            return ";".join(mapping["candidate_positions"])
        if mapping["candidates"]:
            return "Unknown"  # Candidate coordinates remain in the mapping assertion.
        residues = sorted({m["residue"] for m in mapping["modifications"]
                           if m["unimod_id"] in self.target_ptms})
        return ";".join(residues) or "Unknown"

    def _source_fields(self, row):
        mapping = self._mapping_assertion(row["Protein.Group"], row["Modified.Sequence"])
        keys = ("Precursor.Charge", "Localization.Probability", "PTM_Probability", "Q.Value",
                "Global.Q.Value", "PG.Q.Value", "FASTA_Taxonomy_ID", "Isoform")
        result = {k: row.get(k) for k in keys if k in row}
        result["Precursor.Charge"] = row.get("Precursor.Charge", "")
        result["Site_Mapping_Assertion"] = json.dumps(mapping, sort_keys=True)
        result["PTM_Positions"] = ";".join(mapping["candidate_positions"])
        result["Normalization_Policy"] = getattr(self, "normalization_policy", "legacy_median.v1")
        return result

    # ------------------------------------------------------------------
    # Condition comparisons & Log2FC
    # ------------------------------------------------------------------

    def calculate_unadjusted_condition_comparisons(self, ptm_precursors: pd.DataFrame) -> pd.DataFrame:
        """Calculate conventional PTM contrasts directly from normalized PR intensities.

        This axis is independent of protein abundance in the calculation.  It is
        intentionally distinct from the legacy ``PTM_Absolute_Log2FC`` field,
        which is reconstructed downstream from the protein-adjusted contrast and
        the protein contrast.  Control-nondetected features retain a NaN
        conventional value; no pseudocount-derived fold change is emitted here.
        """
        if ptm_precursors is None or ptm_precursors.empty:
            return pd.DataFrame()

        sample_columns = list(getattr(self, "sample_columns", None) or [])
        condition_map = dict(getattr(self, "condition_map", None) or {})
        control_samples = [
            sample for sample in sample_columns
            if condition_map.get(sample) == "Control" and sample in ptm_precursors.columns
        ]
        treatments = list(getattr(self, "treatment_conditions", None) or []) or sorted({
            str(condition)
            for condition in condition_map.values()
            if str(condition) != "Control"
        })
        treatment_samples = {
            treatment: [
                sample for sample in sample_columns
                if condition_map.get(sample) == treatment and sample in ptm_precursors.columns
            ]
            for treatment in treatments
        }

        def positive_values(row: pd.Series, samples: List[str]) -> List[float]:
            values: List[float] = []
            for sample in samples:
                value = row.get(sample)
                if pd.notna(value) and math.isfinite(float(value)) and float(value) > 0:
                    values.append(float(value))
            return values

        records: List[Dict[str, object]] = []
        n_precursors = len(ptm_precursors)
        for row_index, (_, row) in enumerate(ptm_precursors.iterrows()):
            if row_index % 200 == 0:
                (getattr(self, "_progress", None) or (lambda _p, _m: None))(
                    0.45, f"Independent unadjusted PTM comparisons {row_index}/{n_precursors}"
                )
            protein_group = str(row.get("Protein.Group", ""))
            precursor_id = str(row.get("Precursor.Id", ""))
            modified_sequence = str(row.get("Modified.Sequence", ""))
            ptm_type = self._determine_ptm_type(modified_sequence)
            source_fields = self._source_fields(row)
            ptm_position = self._extract_ptm_position(protein_group, modified_sequence, ptm_type)
            control_values = positive_values(row, control_samples)
            control_sample_ids = sorted(s for s in control_samples if positive_values(row, [s]))

            for treatment in treatments:
                current_values = positive_values(row, treatment_samples.get(treatment, []))

                control_mean = float(np.mean(control_values)) if control_values else np.nan
                treatment_mean = float(np.mean(current_values)) if current_values else np.nan
                conventional_log2fc = (
                    float(np.log2(treatment_mean / control_mean))
                    if control_values and control_mean > 0 and treatment_mean > 0
                    else np.nan
                )
                status = (
                    "computed_from_normalized_pr_replicates"
                    if control_values and current_values
                    else "treatment_not_detected_conventional_log2fc_na" if control_values
                    else "both_not_detected_conventional_log2fc_na" if not current_values
                    else "control_not_detected_conventional_log2fc_na"
                )
                from ptm_shared.sample_manifest import compare_sample_units
                treatment_sample_ids = sorted(
                    s for s in treatment_samples.get(treatment, []) if positive_values(row, [s])
                )
                test = compare_sample_units(
                    {s: row[s] for s in control_sample_ids},
                    {s: row[s] for s in treatment_sample_ids},
                    getattr(self, "sample_manifest", None))
                p_value = test["p_value"] if test["p_value"] is not None else np.nan

                records.append({
                    **source_fields,
                    "Protein.Group": protein_group,
                    "Precursor.Id": precursor_id,
                    "Modified.Sequence": modified_sequence,
                    "PTM_Type": ptm_type,
                    "PTM_Position": ptm_position,
                    "Condition": treatment,
                    "Comparison": f"{treatment}_vs_Control",
                    "PTM_Unadjusted_Control_Mean": control_mean,
                    "PTM_Unadjusted_Treatment_Mean": treatment_mean,
                    "PTM_Unadjusted_Log2FC": conventional_log2fc,
                    "PTM_Unadjusted_P_Value": p_value,
                    "PTM_Unadjusted_Control_N": len(control_values),
                    "PTM_Unadjusted_Treatment_N": len(current_values),
                    "PTM_Unadjusted_Control_Sample_IDs": json.dumps(control_sample_ids),
                    "PTM_Unadjusted_Treatment_Sample_IDs": json.dumps(treatment_sample_ids),
                    "PTM_Unadjusted_Control_Biological_N": test.get("control_biological_n"),
                    "PTM_Unadjusted_Treatment_Biological_N": test.get("treatment_biological_n"),
                    "PTM_Unadjusted_Method": test["method"] + "; BH across valid unadjusted feature-condition comparisons",
                    "PTM_Unadjusted_Statistical_Unit": test["statistical_unit"],
                    "PTM_Unadjusted_Test_Status": test["status"],
                    "PTM_Unadjusted_Status": status,
                    "PTM_Unadjusted_Conventional_Log2FC_NA": not bool(control_values and current_values),
                    "PTM_Unadjusted_Calculation_Mode": (
                        "ratio_of_condition_arithmetic_means_from_normalized_pr_intensity"
                    ),
                    "PTM_Unadjusted_Input_Scale": ("provided_normalized_pr_intensity" if getattr(self, "normalization_policy", "legacy_median.v1") == "already_normalized.v1" else "sample_wise_median_scaled_pr_intensity"),
                    "PTM_Unadjusted_Pseudocount_Used": False,
                    "PTM_Unadjusted_Estimator_ID": "independent_unadjusted_ratio_of_condition_arithmetic_means.v1",
                    "Quantitation_Estimator_Contract_Version": "ptm_quantitation_estimators.v1",
                })

        if not records:
            return pd.DataFrame()
        result = pd.DataFrame(records)
        result["PTM_Unadjusted_Q_Value"] = np.nan
        valid = result["PTM_Unadjusted_P_Value"].notna()
        if valid.any():
            _, q_values, _, _ = multipletests(
                result.loc[valid, "PTM_Unadjusted_P_Value"].values,
                alpha=0.05,
                method="fdr_bh",
            )
            result.loc[valid, "PTM_Unadjusted_Q_Value"] = q_values
        return result

    def calculate_condition_comparisons(self, relative_quant_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate condition comparisons with Welch's t-test and BH correction.

        For each PTM site × treatment condition:
        1. Compute mean Log2FC from replicate-level data
        2. Perform Welch's t-test (Control replicates vs Treatment replicates)
        3. Apply Benjamini-Hochberg correction for multiple testing
        4. Output p_value and q_value columns
        """
        if relative_quant_df.empty:
            return pd.DataFrame()
        # --- Build replicate-level grouped data (keep individual replicates) ---
        relative_quant_df = relative_quant_df.copy()
        if "Precursor.Charge" not in relative_quant_df:
            relative_quant_df["Precursor.Charge"] = ""
        relative_quant_df["Precursor.Charge"] = relative_quant_df["Precursor.Charge"].fillna("")
        id_cols = ["Protein.Group", "Precursor.Id", "Modified.Sequence", "PTM_Type", "PTM_Position", "Precursor.Charge"]

        # Condition means (for Log2FC calculation, same as before)
        condition_means = relative_quant_df.groupby(
            id_cols + ["Condition"], dropna=False,
        )["PTM_Relative_Abundance"].mean().reset_index()

        pivot_df = condition_means.pivot(
            index=id_cols,
            columns="Condition",
            values="PTM_Relative_Abundance",
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
            id_cols + ["Condition"], dropna=False,
        )["PTM_Relative_Abundance"].apply(list).reset_index()
        replicate_groups.rename(columns={"PTM_Relative_Abundance": "replicate_values"}, inplace=True)

        # Create a lookup dict: (Protein.Group, Precursor.Id, Condition) -> list of replicate values
        replicate_lookup = {}
        for _, rrow in replicate_groups.iterrows():
            key = tuple(rrow[c] for c in id_cols) + (rrow["Condition"],)
            replicate_lookup[key] = [v for v in rrow["replicate_values"] if pd.notna(v) and np.isfinite(v) and v > 0]
        pr_lookup = {}
        pg_lookup = {}
        paired_samples = {}
        paired_values = {}
        for key, group in relative_quant_df.groupby(id_cols + ["Condition"], dropna=False):
            paired_values[key] = {str(r["Sample"]): float(r["PTM_Relative_Abundance"]) for _, r in group.iterrows() if pd.notna(r["PTM_Relative_Abundance"]) and np.isfinite(r["PTM_Relative_Abundance"]) and r["PTM_Relative_Abundance"] > 0}
            paired_samples[key] = sorted(group.loc[np.isfinite(group["PTM_Relative_Abundance"]) & (group["PTM_Relative_Abundance"] > 0), "Sample"].astype(str).unique())
            for column, lookup in (("PTM_Intensity", pr_lookup), ("Protein_Intensity", pg_lookup)):
                values = pd.to_numeric(group[column], errors="coerce")
                lookup[key] = int((np.isfinite(values) & (values > 0)).sum())

        results = []
        for treatment in treatments:
            if treatment not in pivot_df.columns or "Control" not in pivot_df.columns:
                continue
            for _, row in pivot_df.iterrows():
                control_value = row["Control"]
                treatment_value = row[treatment]
                control_key = tuple(row[c] for c in id_cols) + ("Control",)
                treatment_key = tuple(row[c] for c in id_cols) + (treatment,)
                ctrl_reps = replicate_lookup.get(control_key, [])
                treat_reps = replicate_lookup.get(treatment_key, [])
                treatment_missing = not pr_lookup.get(treatment_key, 0)
                denominator_unavailable = (
                    (pr_lookup.get(control_key, 0) > 0 and not ctrl_reps)
                    or not treat_reps
                )
                # Pseudocounts remain an audit-only representation for genuine PR
                # control nondetection. Missing PG never triggers this branch.
                used_pc = bool(not denominator_unavailable and not pr_lookup.get(control_key, 0))
                control_adj = control_pseudo_count if used_pc else control_value
                log2_fc = np.log2(treatment_value / control_adj) if not denominator_unavailable else np.nan
                missing_reason = (
                    "both_not_detected" if treatment_missing and not pr_lookup.get(control_key, 0)
                    else "treatment_not_detected" if treatment_missing
                    else "protein_denominator_unavailable" if denominator_unavailable
                    else "control_not_detected" if used_pc else ""
                )

                from ptm_shared.sample_manifest import compare_sample_units
                test = compare_sample_units(paired_values.get(control_key, {}), paired_values.get(treatment_key, {}), getattr(self, "sample_manifest", None))
                p_value = test["p_value"] if test["p_value"] is not None else np.nan

                results.append({
                    **self._source_fields(row),
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
                    "PTM_ProteinAdjusted_Control_N": len(ctrl_reps),
                    "PTM_ProteinAdjusted_Treatment_N": len(treat_reps),
                    "PTM_ProteinAdjusted_Control_Sample_IDs": json.dumps(paired_samples.get(control_key, [])),
                    "PTM_ProteinAdjusted_Treatment_Sample_IDs": json.dumps(paired_samples.get(treatment_key, [])),
                    "PTM_ProteinAdjusted_Control_Biological_N": test.get("control_biological_n"),
                    "PTM_ProteinAdjusted_Treatment_Biological_N": test.get("treatment_biological_n"),
                    "PTM_ProteinAdjusted_Method": test["method"] + "; BH across valid adjusted feature-condition comparisons",
                    "PTM_ProteinAdjusted_Statistical_Unit": test["statistical_unit"],
                    "PTM_ProteinAdjusted_Test_Status": test["status"],
                    "PTM_ProteinAdjusted_Missing_Reason": missing_reason,
                    "PTM_ProteinAdjusted_Conventional_Log2FC_NA": bool(denominator_unavailable or used_pc),
                    "PR_Control_N": pr_lookup.get(control_key, 0),
                    "PR_Treatment_N": pr_lookup.get(treatment_key, 0),
                    "PG_Control_N": pg_lookup.get(control_key, 0),
                    "PG_Treatment_N": pg_lookup.get(treatment_key, 0),
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
                df, relative_quant_df, id_cols=id_cols, condition_map=self.condition_map,
            )
            metadata = [c for c in relative_quant_df.columns if c in {
                "Localization.Probability", "PTM_Probability", "Q.Value", "Global.Q.Value", "PG.Q.Value", "FASTA_Taxonomy_ID", "Isoform"}]
            if metadata:
                meta = relative_quant_df[id_cols + metadata].drop_duplicates()
                df = df.drop(columns=[c for c in metadata if c in df]).merge(meta, on=id_cols, how="left", validate="many_to_one")
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
            pg["Control_Mean"] = pg[ctrl_cols].where(np.isfinite(pg[ctrl_cols]) & (pg[ctrl_cols] > 0)).mean(axis=1) if ctrl_cols else np.nan

            for treatment, samples in treatment_samples_dict.items():
                tcols = [c for c in samples if c in pg.columns]
                pg[f"{treatment}_Mean"] = pg[tcols].where(np.isfinite(pg[tcols]) & (pg[tcols] > 0)).mean(axis=1) if tcols else np.nan

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
                            "Protein_Control_Sample_IDs": json.dumps(sorted(s for s in ctrl_cols if pd.notna(row[s]) and np.isfinite(row[s]) and row[s] > 0)),
                            "Protein_Treatment_Sample_IDs": json.dumps(sorted(s for s in treatment_samples_dict[treatment] if s in row and pd.notna(row[s]) and np.isfinite(row[s]) and row[s] > 0)),
                            "Protein_Control_N": sum(pd.notna(row[s]) and np.isfinite(row[s]) and row[s] > 0 for s in ctrl_cols),
                            "Protein_Treatment_N": sum(s in row and pd.notna(row[s]) and np.isfinite(row[s]) and row[s] > 0 for s in treatment_samples_dict[treatment]),
                            "Protein_Method": "ratio_of_condition_arithmetic_means; no_protein_test_computed",
                        })

            all_df = pd.DataFrame(changes)
            if all_df.empty:
                return all_df, all_df.copy()
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
        unadjusted_ptm_comparisons: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Emit the Stage 1 site/form × timepoint vector with precursor identity.

        구현 대상: docs/ptm_vector_p0_feature_provenance_restoration.md §2
        사전등록: 2026-09-01 선언. Insulin P0 ledger 재측정 전.
        해석 한계: Precursor.Id 보존은 feature identity의 필요조건이며
        mapping/relation 성공이나 kinase 귀속을 의미하지 않는다.
        주장 금지: 이 컬럼 추가로 kinase 예측 향상을 주장하지 않는다.
        """
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
            unadjusted_lookup: Dict[Tuple[str, str, str], Dict[str, object]] = {}
            if unadjusted_ptm_comparisons is not None and not unadjusted_ptm_comparisons.empty:
                for _, unadjusted_row in unadjusted_ptm_comparisons.iterrows():
                    unadjusted_lookup[(
                        str(unadjusted_row.get("Protein.Group", "")),
                        str(unadjusted_row.get("Precursor.Id", "")),
                        str(unadjusted_row.get("Modified.Sequence", "")),
                        str(unadjusted_row.get("Precursor.Charge", "")),
                        str(unadjusted_row.get("Condition", "")),
                    )] = unadjusted_row.to_dict()
            treatments = self.treatment_conditions or [
                c for c in ptm_comparisons["Condition"].unique() if c != "Control"
            ]

            def _form_key(row, condition=None):
                charge = row.get("Precursor.Charge", "")
                if pd.isna(charge):
                    charge = ""
                return (
                    str(row.get("Protein.Group", "")),
                    str(row.get("Precursor.Id", "")),
                    str(row.get("Modified.Sequence", "")),
                    str(charge),
                    str(row.get("Condition", "") if condition is None else condition),
                )

            treatment_mean_lookup: Dict[Tuple[str, str, str, str, str], float] = {}
            for rec in ptm_comparisons.to_dict("records"):
                treatment_mean_lookup.setdefault(_form_key(rec), rec.get("Treatment_Mean", np.nan))
            protein_change_lookup: Dict[Tuple[str, str], Dict[str, object]] = {}
            if ptm_protein_changes is not None and not ptm_protein_changes.empty:
                for rec in ptm_protein_changes.to_dict("records"):
                    protein_change_lookup.setdefault(
                        (str(rec.get("Protein.Group", "")), str(rec.get("Condition", ""))),
                        rec,
                    )

            for _, ptm_row in ptm_comparisons.iterrows():
                protein_group = ptm_row["Protein.Group"]
                condition = ptm_row["Condition"]

                pc = protein_change_lookup.get((str(protein_group), str(condition))) or {
                    "Protein.Name": self._resolve_protein_name(protein_group),
                    "Gene.Name": self._resolve_gene_name(protein_group),
                    "Control_Mean": np.nan, "Treatment_Mean": np.nan,
                    "Log2FC": np.nan, "Fold_Change": np.nan,
                }
                occupancy = occupancy_lookup.get((
                    str(protein_group), str(ptm_row["Modified.Sequence"]), str(condition)
                ), {})
                unadjusted = unadjusted_lookup.get((
                    str(protein_group), str(ptm_row["Precursor.Id"]), str(ptm_row["Modified.Sequence"]), str(ptm_row.get("Precursor.Charge", "")), str(condition)
                ), {})
                cmeans: Dict[str, float] = {
                    "Control_Mean_PTM_Relative": ptm_row["Control_Mean"],
                    "Control_Mean_Protein": pc["Control_Mean"],
                    "Treatment_Mean_Protein": pc["Treatment_Mean"],
                    "Protein_Log2FC": pc["Log2FC"],
                    "Protein_Fold_Change": pc["Fold_Change"],
                }

                for cond in treatments:
                    cmeans[f"{cond}_Mean_PTM_Relative"] = treatment_mean_lookup.get(
                        _form_key(ptm_row, cond), np.nan
                    )

                vector_data.append({
                    **self._source_fields(ptm_row),
                    "Protein.Group": protein_group,
                    "Protein.Name": pc["Protein.Name"],
                    "Gene.Name": pc["Gene.Name"],
                    "Precursor.Id": ptm_row["Precursor.Id"],
                    "Precursor.Charge": ptm_row.get("Precursor.Charge", ""),
                    "Modified.Sequence": ptm_row["Modified.Sequence"],
                    "PTM_Type": ptm_row["PTM_Type"],
                    "PTM_Position": ptm_row["PTM_Position"],
                    "Condition": condition,
                    "Comparison": ptm_row["Comparison"],
                    "PTM_Relative_Log2FC": ptm_row["Log2FC"],
                    "PTM_ProteinAdjusted_Log2FC": ptm_row["Log2FC"],
                    **{f"PTM_ProteinAdjusted_{suffix}": ptm_row.get(f"PTM_ProteinAdjusted_{suffix}") for suffix in ("Control_Sample_IDs", "Treatment_Sample_IDs", "Method", "Statistical_Unit", "Test_Status", "Control_Biological_N", "Treatment_Biological_N")},
                    **{f"PTM_Unadjusted_{suffix}": unadjusted.get(f"PTM_Unadjusted_{suffix}") for suffix in ("Control_Sample_IDs", "Treatment_Sample_IDs", "Method", "Statistical_Unit", "Test_Status", "Control_Biological_N", "Treatment_Biological_N")},
                    **{f"Protein_{suffix}": pc.get(f"Protein_{suffix}") for suffix in ("Control_Sample_IDs", "Treatment_Sample_IDs", "Control_N", "Treatment_N", "Method")},
                    "PTM_ProteinAdjusted_Control_N": ptm_row.get("PTM_ProteinAdjusted_Control_N", ptm_row.get("Control_N", np.nan)),
                    "PTM_ProteinAdjusted_Treatment_N": ptm_row.get("PTM_ProteinAdjusted_Treatment_N", ptm_row.get("Treatment_N", np.nan)),
                    "PTM_ProteinAdjusted_Missing_Reason": ptm_row.get("PTM_ProteinAdjusted_Missing_Reason", ""),
                    "PTM_ProteinAdjusted_Conventional_Log2FC_NA": ptm_row.get("PTM_ProteinAdjusted_Conventional_Log2FC_NA", False),
                    **{field: ptm_row.get(field, np.nan) for field in ("PR_Control_N", "PR_Treatment_N", "PG_Control_N", "PG_Treatment_N")},
                    "PTM_Unadjusted_Log2FC": unadjusted.get("PTM_Unadjusted_Log2FC", np.nan),
                    "PTM_Unadjusted_Control_Mean": unadjusted.get("PTM_Unadjusted_Control_Mean", np.nan),
                    "PTM_Unadjusted_Treatment_Mean": unadjusted.get("PTM_Unadjusted_Treatment_Mean", np.nan),
                    "PTM_Unadjusted_P_Value": unadjusted.get("PTM_Unadjusted_P_Value", np.nan),
                    "PTM_Unadjusted_Q_Value": unadjusted.get("PTM_Unadjusted_Q_Value", np.nan),
                    "PTM_Unadjusted_Control_N": unadjusted.get("PTM_Unadjusted_Control_N", np.nan),
                    "PTM_Unadjusted_Treatment_N": unadjusted.get("PTM_Unadjusted_Treatment_N", np.nan),
                    "PTM_Unadjusted_Status": unadjusted.get("PTM_Unadjusted_Status", "not_computed"),
                    "PTM_Unadjusted_Conventional_Log2FC_NA": bool(
                        unadjusted.get("PTM_Unadjusted_Conventional_Log2FC_NA", False)
                    ),
                    "PTM_Unadjusted_Calculation_Mode": unadjusted.get(
                        "PTM_Unadjusted_Calculation_Mode", "not_computed"
                    ),
                    "PTM_Unadjusted_Input_Scale": unadjusted.get(
                        "PTM_Unadjusted_Input_Scale", "not_recorded"
                    ),
                    "PTM_Unadjusted_Pseudocount_Used": bool(
                        unadjusted.get("PTM_Unadjusted_Pseudocount_Used", False)
                    ),
                    "PTM_Unadjusted_Estimator_ID": unadjusted.get(
                        "PTM_Unadjusted_Estimator_ID",
                        "independent_unadjusted_ratio_of_condition_arithmetic_means.v1",
                    ),
                    "PTM_ProteinAdjusted_Estimator_ID": "protein_adjusted_mean_of_sample_ptm_to_protein_ratios.v1",
                    "PTM_ProteinAdjusted_Aggregation_Order": "sample_ratios_then_condition_means_then_log2_contrast",
                    "Linked_Protein_Estimator_ID": "linked_protein_ratio_of_condition_arithmetic_means.v1",
                    "PTM_Absolute_Log2FC": ptm_row["Log2FC"] + cmeans.get("Protein_Log2FC", 0),
                    "PTM_Reconstructed_Log2FC": ptm_row["Log2FC"] + cmeans.get("Protein_Log2FC", 0),
                    "PTM_Reconstructed_Calculation_Mode": "protein_adjusted_log2fc_plus_protein_log2fc",
                    "PTM_Reconstructed_Estimator_ID": "legacy_reconstructed_adjusted_plus_protein.v1",
                    "Quantitation_Estimator_Contract_Version": "ptm_quantitation_estimators.v1",
                    "Protein_Adjustment_Delta_Log2FC": (
                        float(ptm_row["Log2FC"]) - float(unadjusted.get("PTM_Unadjusted_Log2FC"))
                        if pd.notna(unadjusted.get("PTM_Unadjusted_Log2FC"))
                        else np.nan
                    ),
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
        unadjusted_ptm_comparisons: Optional[pd.DataFrame] = None,
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

        if unadjusted_ptm_comparisons is not None and not unadjusted_ptm_comparisons.empty:
            p = self.output_dir / f"ptm_unadjusted_condition_comparisons_normalized{sfx}.tsv"
            unadjusted_ptm_comparisons.to_csv(p, sep="\t", index=False)
            logger.info(f"Saved independent unadjusted PTM comparisons: {p.name}")

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
