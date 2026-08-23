"""Quick Analysis: subset DIA-NN PR/PG before the unchanged quant path.

구현 대상: docs/quick_analysis_contract_v1.md §4–§7
사전등록: 2026-08-23 선언. 탐색적. primary 승격 금지.
해석 한계: 행을 줄일 뿐이며 sample-median 정규화 인자가 Full과 달라진다.
           같은 site의 Quick Log2FC를 Full과 비교하지 않는다.
주장 금지: 이 서브셋이 kinase 예측·효과크기를 개선했다고 쓰지 않는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("ptm-workers.preprocessing.quick_analysis")

# Mirrors preprocessing.core.config.PTM_MODES unimod_id. Keep in lockstep.
QUICK_UNIMOD_BY_MODE = {"phospho": "21", "ubi": "121"}

QUICK_MAX_PTM_PRECURSORS = 400
"""Quick PTM precursor 예산.

docs/quick_analysis_contract_v1.md §4 에서 2026-08-23 선언. 측정 전.
Wave/TMM 경로를 연습할 크기지 과학적 통과 임계가 아니다.
측정 후 변경하면 이전 Quick 오더와 비교가 무효가 된다.
"""

QUICK_PER_PROTEIN_CAP = 4
"""단백질당 선택 상한.

docs/quick_analysis_contract_v1.md §4 에서 2026-08-23 선언. 측정 전.
한 hub 단백질이 예산을 독점하지 않게 하고 다중 site를 남긴다.
"""

QUICK_MIN_DETECTION_FRAC = 0.50
"""1차 적격 검출률.

docs/quick_analysis_contract_v1.md §4 에서 2026-08-23 선언. 측정 전.
샘플 열의 절반 이상에서 intensity > 0 인 site를 우선한다.
"""

QUICK_MAX_PTM_PRECURSORS_MIN = 10
QUICK_MAX_PTM_PRECURSORS_MAX = 5000
QUICK_PER_PROTEIN_CAP_MIN = 0
QUICK_PER_PROTEIN_CAP_MAX = 50
QUICK_MIN_DETECTION_FRAC_MIN = 0.0
QUICK_MIN_DETECTION_FRAC_MAX = 1.0
QUICK_MAX_NON_PTM_PROTEINS = 200
QUICK_MAX_NON_PTM_PROTEINS_MIN = 0
QUICK_MAX_NON_PTM_PROTEINS_MAX = 5000
QUICK_KEEP_UNMODIFIED_PAIRS_DEFAULT = True
QUICK_INCLUDE_NON_PTM_DEFAULT = False
QUICK_KEEP_ALL_PTM_DEFAULT = False
"""Custom Quick 범위와 기본값.

docs/quick_analysis_contract_v1.md §4.1 에서 2026-08-23 선언. 측정 전.
기본값은 §4와 같다. 범위 밖은 clamp. 시점 열은 오버라이드 금지.
"""

CONTRACT_PATH = "docs/quick_analysis_contract_v1.md"

_METADATA_COLUMNS = frozenset(
    {
        "Protein.Group",
        "Protein.Ids",
        "Protein.Names",
        "Genes",
        "First.Protein.Description",
        "Proteotypic",
        "Stripped.Sequence",
        "Modified.Sequence",
        "Precursor.Charge",
        "Precursor.Id",
    }
)


def is_quick_analysis(analysis_options: dict | None) -> bool:
    """True when the order asked for the exploratory input subset."""
    if not analysis_options:
        return False
    return bool(analysis_options.get("quick_analysis"))


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


def _clamp_float(value: Any, default: float, lo: float, hi: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(parsed):
        return default
    return max(lo, min(hi, parsed))


def resolve_quick_settings(analysis_options: dict | None) -> dict[str, Any]:
    """Clamp Custom Quick fields to the §4.1 bounds. Defaults equal §4.

    구현 대상: docs/quick_analysis_contract_v1.md §4.1
    사전등록: 2026-08-23 선언. 탐색적.
    해석 한계: clamp는 입력 보호이지 과학적 최적값이 아니다.
    주장 금지: 사용자가 고른 예산이 더 정확한 kinase 추정을 만든다고 쓰지 않는다.
    """
    opts = analysis_options or {}
    keep_all_ptm = _as_bool(opts.get("quick_keep_all_ptm"), QUICK_KEEP_ALL_PTM_DEFAULT)
    max_ptm_precursors = _clamp_int(
        opts.get("quick_max_ptm_precursors"),
        QUICK_MAX_PTM_PRECURSORS,
        QUICK_MAX_PTM_PRECURSORS_MIN,
        QUICK_MAX_PTM_PRECURSORS_MAX,
    )
    per_protein_cap = _clamp_int(
        opts.get("quick_per_protein_cap"),
        QUICK_PER_PROTEIN_CAP,
        QUICK_PER_PROTEIN_CAP_MIN,
        QUICK_PER_PROTEIN_CAP_MAX,
    )
    min_detection_frac = _clamp_float(
        opts.get("quick_min_detection_frac"),
        QUICK_MIN_DETECTION_FRAC,
        QUICK_MIN_DETECTION_FRAC_MIN,
        QUICK_MIN_DETECTION_FRAC_MAX,
    )
    keep_unmodified_pairs = _as_bool(
        opts.get("quick_keep_unmodified_pairs"),
        QUICK_KEEP_UNMODIFIED_PAIRS_DEFAULT,
    )
    include_non_ptm = _as_bool(
        opts.get("quick_include_non_ptm"),
        QUICK_INCLUDE_NON_PTM_DEFAULT,
    )
    max_non_ptm_proteins = _clamp_int(
        opts.get("quick_max_non_ptm_proteins"),
        QUICK_MAX_NON_PTM_PROTEINS,
        QUICK_MAX_NON_PTM_PROTEINS_MIN,
        QUICK_MAX_NON_PTM_PROTEINS_MAX,
    )
    applied = {
        "keep_all_ptm": keep_all_ptm,
        "max_ptm_precursors": max_ptm_precursors,
        "per_protein_cap": per_protein_cap,
        "min_detection_frac": min_detection_frac,
        "keep_unmodified_pairs": keep_unmodified_pairs,
        "include_non_ptm": include_non_ptm,
        "max_non_ptm_proteins": max_non_ptm_proteins,
    }
    defaults = {
        "keep_all_ptm": QUICK_KEEP_ALL_PTM_DEFAULT,
        "max_ptm_precursors": QUICK_MAX_PTM_PRECURSORS,
        "per_protein_cap": QUICK_PER_PROTEIN_CAP,
        "min_detection_frac": QUICK_MIN_DETECTION_FRAC,
        "keep_unmodified_pairs": QUICK_KEEP_UNMODIFIED_PAIRS_DEFAULT,
        "include_non_ptm": QUICK_INCLUDE_NON_PTM_DEFAULT,
        "max_non_ptm_proteins": QUICK_MAX_NON_PTM_PROTEINS,
    }
    overrides_applied = [key for key, value in applied.items() if value != defaults[key]]
    return {
        **applied,
        "overrides_applied": overrides_applied,
        "defaults": defaults,
    }


def _sample_columns(df: pd.DataFrame) -> list[str]:
    """Match PTMQuantificationAnalyzer.load_data: columns ending in .mzML."""
    mzml = [c for c in df.columns if str(c).endswith(".mzML")]
    if mzml:
        return mzml
    fallback = []
    for col in df.columns:
        if col in _METADATA_COLUMNS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            fallback.append(col)
    return fallback


def _greedy_select(
    ranked: pd.DataFrame,
    budget: int,
    per_protein_cap: int,
    per_protein: dict[str, int] | None = None,
) -> tuple[pd.Index, dict[str, int]]:
    chosen: list[Any] = []
    counts = dict(per_protein or {})
    if budget <= 0:
        return pd.Index(chosen), counts
    for idx, protein in ranked["Protein.Group"].items():
        key = str(protein)
        if per_protein_cap > 0 and counts.get(key, 0) >= per_protein_cap:
            continue
        chosen.append(idx)
        counts[key] = counts.get(key, 0) + 1
        if len(chosen) >= budget:
            break
    return pd.Index(chosen), counts


def select_quick_precursor_indices(
    pr: pd.DataFrame,
    unimod_id: str,
    *,
    max_ptm_precursors: int = QUICK_MAX_PTM_PRECURSORS,
    per_protein_cap: int = QUICK_PER_PROTEIN_CAP,
    min_detection_frac: float = QUICK_MIN_DETECTION_FRAC,
    keep_all_ptm: bool = QUICK_KEEP_ALL_PTM_DEFAULT,
    keep_unmodified_pairs: bool = QUICK_KEEP_UNMODIFIED_PAIRS_DEFAULT,
) -> tuple[pd.Index, dict[str, Any]]:
    """Return PR indices to keep and selection stats. Deterministic.

    구현 대상: docs/quick_analysis_contract_v1.md §5
    사전등록: 2026-08-23. 탐색적.
    해석 한계: 검출률·단백질 상한은 시간 형태를 남기기 위한 입력 규칙이지
               생물학적 중요도 순위가 아니다.
    주장 금지: 선택된 site가 더 중요한 substrate라고 쓰지 않는다.
    """
    if "Modified.Sequence" not in pr.columns or "Protein.Group" not in pr.columns:
        raise ValueError("PR matrix missing Modified.Sequence or Protein.Group")

    sample_cols = _sample_columns(pr)
    marker = f"UniMod:{unimod_id}"
    modified = pr["Modified.Sequence"].astype(str)
    ptm_mask = modified.str.contains(marker, na=False)
    ptm = pr.loc[ptm_mask].copy()
    if ptm.empty:
        raise ValueError(f"Quick Analysis: no precursors contain {marker}")

    if "Precursor.Id" not in ptm.columns:
        ptm["Precursor.Id"] = ptm.index.astype(str)

    if sample_cols:
        intensity = ptm[sample_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        ptm["_detection_frac"] = np.sum(np.isfinite(intensity) & (intensity > 0), axis=1) / len(sample_cols)
    else:
        ptm["_detection_frac"] = 0.0
    ptm["_protein"] = ptm["Protein.Group"].astype(str)
    ptm["_precursor"] = ptm["Precursor.Id"].astype(str)
    ranked = ptm.sort_values(
        ["_detection_frac", "_protein", "_precursor"],
        ascending=[False, True, True],
        kind="mergesort",
    )

    budget = int(len(ranked)) if keep_all_ptm else int(max_ptm_precursors)
    eligible = ranked[ranked["_detection_frac"] >= min_detection_frac]
    selected, protein_counts = _greedy_select(eligible, budget, per_protein_cap)
    used_relaxed = False
    if len(selected) < budget:
        used_relaxed = True
        remainder = ranked.loc[~ranked.index.isin(selected)]
        extra, _ = _greedy_select(
            remainder,
            budget - len(selected),
            per_protein_cap,
            protein_counts,
        )
        selected = selected.union(extra)

    pair_indices: list[Any] = []
    if keep_unmodified_pairs and "Stripped.Sequence" in pr.columns:
        kept = pr.loc[selected, ["Protein.Group", "Stripped.Sequence"]]
        keys = set(zip(kept["Protein.Group"].astype(str), kept["Stripped.Sequence"].astype(str)))
        unmodified = pr.loc[~ptm_mask]
        for idx, row in unmodified.iterrows():
            key = (str(row.get("Protein.Group", "")), str(row.get("Stripped.Sequence", "")))
            if key in keys:
                pair_indices.append(idx)

    keep = selected.union(pd.Index(pair_indices)).drop_duplicates()
    stats = {
        "sample_columns_kept": list(sample_cols),
        "ptm_universe": int(ptm_mask.sum()),
        "ptm_precursors_selected": int(len(selected)),
        "unmodified_pairs_added": int(len(pair_indices)),
        "detection_gate_relaxed": used_relaxed,
        "unimod_id": unimod_id,
        "keep_all_ptm": bool(keep_all_ptm),
        "keep_unmodified_pairs": bool(keep_unmodified_pairs),
        "selection_budget": budget,
    }
    return keep, stats


def _select_non_ptm_proteins(
    pg: pd.DataFrame,
    excluded_proteins: set[str],
    sample_cols: list[str],
    budget: int,
) -> list[str]:
    """Add leftover PG proteins ranked by detection_frac. PR rows are not added.

    구현 대상: docs/quick_analysis_contract_v1.md §4.1
    사전등록: 2026-08-23. 탐색적.
    해석 한계: 네트워크/protein-level 맥락용이다. 정량 우주를 Full로 되돌리지 않는다.
    주장 금지: 추가된 PG가 더 좋은 배경 proteome이라고 쓰지 않는다.
    """
    if budget <= 0:
        return []
    candidates = pg[~pg["Protein.Group"].astype(str).isin(excluded_proteins)].copy()
    if candidates.empty:
        return []
    present = [col for col in sample_cols if col in candidates.columns]
    if present:
        intensity = candidates[present].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        candidates["_detection_frac"] = np.sum(
            np.isfinite(intensity) & (intensity > 0), axis=1
        ) / len(present)
    else:
        candidates["_detection_frac"] = 0.0
    candidates["_protein"] = candidates["Protein.Group"].astype(str)
    ranked = candidates.sort_values(
        ["_detection_frac", "_protein"],
        ascending=[False, True],
        kind="mergesort",
    )
    return ranked["_protein"].head(int(budget)).tolist()


def subset_diann_matrices_for_quick_analysis(
    pr_path: str,
    pg_path: str,
    output_dir: str | Path,
    ptm_mode: str,
    *,
    analysis_options: dict | None = None,
    max_ptm_precursors: int | None = None,
    per_protein_cap: int | None = None,
    min_detection_frac: float | None = None,
    keep_all_ptm: bool | None = None,
    keep_unmodified_pairs: bool | None = None,
    include_non_ptm: bool | None = None,
    max_non_ptm_proteins: int | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Write subset TSVs and a manifest. Analyzer formulas are not touched.

    구현 대상: docs/quick_analysis_contract_v1.md §5–§7
    사전등록: 2026-08-23. 탐색적.
    해석 한계: 이후 median 정규화는 이 축소 행렬에서 다시 계산된다.
    주장 금지: 산출 Log2FC를 Full 실행과 같거나 더 정확하다고 쓰지 않는다.
    """
    unimod_id = QUICK_UNIMOD_BY_MODE.get(ptm_mode)
    if unimod_id is None:
        raise ValueError(f"Unknown ptm_mode for Quick Analysis: {ptm_mode}")

    settings = resolve_quick_settings(analysis_options)
    if max_ptm_precursors is not None:
        settings["max_ptm_precursors"] = int(max_ptm_precursors)
    if per_protein_cap is not None:
        settings["per_protein_cap"] = int(per_protein_cap)
    if min_detection_frac is not None:
        settings["min_detection_frac"] = float(min_detection_frac)
    if keep_all_ptm is not None:
        settings["keep_all_ptm"] = bool(keep_all_ptm)
    if keep_unmodified_pairs is not None:
        settings["keep_unmodified_pairs"] = bool(keep_unmodified_pairs)
    if include_non_ptm is not None:
        settings["include_non_ptm"] = bool(include_non_ptm)
    if max_non_ptm_proteins is not None:
        settings["max_non_ptm_proteins"] = int(max_non_ptm_proteins)

    pr = pd.read_csv(pr_path, sep="\t", on_bad_lines="warn", low_memory=False)
    pg = pd.read_csv(pg_path, sep="\t", on_bad_lines="warn", low_memory=False)
    keep_idx, stats = select_quick_precursor_indices(
        pr,
        unimod_id,
        max_ptm_precursors=settings["max_ptm_precursors"],
        per_protein_cap=settings["per_protein_cap"],
        min_detection_frac=settings["min_detection_frac"],
        keep_all_ptm=settings["keep_all_ptm"],
        keep_unmodified_pairs=settings["keep_unmodified_pairs"],
    )
    pr_sub = pr.loc[keep_idx].copy()
    if "Protein.Group" not in pg.columns:
        raise ValueError("PG matrix missing Protein.Group")
    kept_proteins = set(pr_sub["Protein.Group"].astype(str))
    non_ptm_proteins_added: list[str] = []
    if settings["include_non_ptm"]:
        non_ptm_proteins_added = _select_non_ptm_proteins(
            pg,
            kept_proteins,
            _sample_columns(pg),
            settings["max_non_ptm_proteins"],
        )
        kept_proteins = kept_proteins | set(non_ptm_proteins_added)
    pg_sub = pg[pg["Protein.Group"].astype(str).isin(kept_proteins)].copy()

    out = Path(output_dir) / "quick_analysis"
    out.mkdir(parents=True, exist_ok=True)
    pr_out = out / "report.pr_matrix.quick.tsv"
    pg_out = out / "report.pg_matrix.quick.tsv"
    pr_sub.to_csv(pr_out, sep="\t", index=False)
    pg_sub.to_csv(pg_out, sep="\t", index=False)

    manifest: dict[str, Any] = {
        "quick_analysis": True,
        "contract": CONTRACT_PATH,
        "preregistration": "exploratory",
        "primary_claim_allowed": False,
        "median_normalization_not_comparable_to_full": True,
        "ptm_mode": ptm_mode,
        "unimod_id": unimod_id,
        "max_ptm_precursors": settings["max_ptm_precursors"],
        "per_protein_cap": settings["per_protein_cap"],
        "min_detection_frac": settings["min_detection_frac"],
        "keep_all_ptm": settings["keep_all_ptm"],
        "keep_unmodified_pairs": settings["keep_unmodified_pairs"],
        "include_non_ptm": settings["include_non_ptm"],
        "max_non_ptm_proteins": settings["max_non_ptm_proteins"],
        "overrides_applied": settings.get("overrides_applied", []),
        "non_ptm_proteins_added": non_ptm_proteins_added,
        "pr_rows_before": int(len(pr)),
        "pr_rows_after": int(len(pr_sub)),
        "pg_rows_before": int(len(pg)),
        "pg_rows_after": int(len(pg_sub)),
        **stats,
        "pr_subset_path": str(pr_out),
        "pg_subset_path": str(pg_out),
    }
    manifest_path = out / "quick_analysis_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "Quick Analysis subset: PR %s → %s, PG %s → %s, PTM selected %s, pairs %s",
        manifest["pr_rows_before"],
        manifest["pr_rows_after"],
        manifest["pg_rows_before"],
        manifest["pg_rows_after"],
        manifest["ptm_precursors_selected"],
        manifest["unmodified_pairs_added"],
    )
    return str(pr_out), str(pg_out), manifest
