"""Quick Analysis input subset contract tests.

구현 대상: docs/quick_analysis_contract_v1.md §4–§7
사전등록: 2026-08-23. 탐색적.
해석 한계: 합성 intensity로 선택 규칙만 고정한다. 생물학적 대표성을 검증하지 않는다.
주장 금지: 통과를 kinase 귀속 또는 Full 대비 정확도 개선으로 서술하지 않는다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "preprocessing" / "core" / "quick_analysis.py"
_SPEC = importlib.util.spec_from_file_location("quick_analysis_mod", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

QUICK_MAX_PTM_PRECURSORS = _MOD.QUICK_MAX_PTM_PRECURSORS
QUICK_MIN_DETECTION_FRAC = _MOD.QUICK_MIN_DETECTION_FRAC
QUICK_PER_PROTEIN_CAP = _MOD.QUICK_PER_PROTEIN_CAP
QUICK_UNIMOD_BY_MODE = _MOD.QUICK_UNIMOD_BY_MODE
is_quick_analysis = _MOD.is_quick_analysis
resolve_quick_settings = _MOD.resolve_quick_settings
select_quick_precursor_indices = _MOD.select_quick_precursor_indices
subset_diann_matrices_for_quick_analysis = _MOD.subset_diann_matrices_for_quick_analysis


def _pr_row(
    protein: str,
    precursor: str,
    stripped: str,
    modified: str,
    intensities: list[float],
    sample_names: list[str],
) -> dict:
    row = {
        "Protein.Group": protein,
        "Precursor.Id": precursor,
        "Stripped.Sequence": stripped,
        "Modified.Sequence": modified,
        "Genes": protein,
    }
    for name, value in zip(sample_names, intensities):
        row[name] = value
    return row


SAMPLES = ["ctrl_0.mzML", "t1_1.mzML", "t2_2.mzML", "t3_3.mzML"]


def _matrix() -> pd.DataFrame:
    rows = [
        # Protein A: 5 phospho sites, all complete — cap should keep 4
        _pr_row("P_A", "A1", "PEPTIDEA", "PEPTIDEA(UniMod:21)", [10, 12, 11, 13], SAMPLES),
        _pr_row("P_A", "A2", "PEPTIDEB", "PEPTIDEB(UniMod:21)", [9, 8, 10, 11], SAMPLES),
        _pr_row("P_A", "A3", "PEPTIDEC", "PEPTIDEC(UniMod:21)", [7, 7, 8, 9], SAMPLES),
        _pr_row("P_A", "A4", "PEPTIDED", "PEPTIDED(UniMod:21)", [6, 5, 6, 7], SAMPLES),
        _pr_row("P_A", "A5", "PEPTIDEE", "PEPTIDEE(UniMod:21)", [4, 4, 5, 5], SAMPLES),
        _pr_row("P_A", "A1u", "PEPTIDEA", "PEPTIDEA", [20, 21, 19, 22], SAMPLES),
        # Protein B: one complete phospho, one sparse (1/4)
        _pr_row("P_B", "B1", "OTHERAAA", "OTHERAAA(UniMod:21)", [15, 16, 14, 17], SAMPLES),
        _pr_row("P_B", "B2", "OTHERBBB", "OTHERBBB(UniMod:21)", [3, 0, 0, 0], SAMPLES),
        # Unrelated unmodified / other protein — should drop
        _pr_row("P_C", "C1", "NOMODSEQ", "NOMODSEQ", [100, 100, 100, 100], SAMPLES),
    ]
    return pd.DataFrame(rows)


def test_contract_constants_are_frozen():
    assert QUICK_MAX_PTM_PRECURSORS == 400
    assert QUICK_PER_PROTEIN_CAP == 4
    assert QUICK_MIN_DETECTION_FRAC == 0.50
    assert QUICK_UNIMOD_BY_MODE == {"phospho": "21", "ubi": "121"}


def test_is_quick_analysis_flag():
    assert is_quick_analysis({"quick_analysis": True}) is True
    assert is_quick_analysis({"quick_analysis": False}) is False
    assert is_quick_analysis({}) is False
    assert is_quick_analysis(None) is False


def test_per_protein_cap_and_unmodified_pair():
    keep, stats = select_quick_precursor_indices(
        _matrix(),
        "21",
        max_ptm_precursors=10,
        per_protein_cap=4,
        min_detection_frac=0.50,
    )
    pr = _matrix()
    kept = pr.loc[keep]
    a_ptm = kept[(kept["Protein.Group"] == "P_A") & kept["Modified.Sequence"].str.contains("UniMod:21")]
    assert len(a_ptm) == 4
    assert "A5" not in set(a_ptm["Precursor.Id"])
    assert "A1u" in set(kept["Precursor.Id"])
    assert "C1" not in set(kept["Precursor.Id"])
    assert stats["unmodified_pairs_added"] == 1
    # Eligible: A1–A4 + B1. Relaxed fill may add B2; A stays at the protein cap.
    assert stats["ptm_precursors_selected"] == 6
    assert "B2" in set(kept["Precursor.Id"])


def test_prefers_complete_trajectories_over_sparse():
    keep, _ = select_quick_precursor_indices(
        _matrix(),
        "21",
        max_ptm_precursors=5,
        per_protein_cap=4,
        min_detection_frac=0.50,
    )
    precursors = set(_matrix().loc[keep, "Precursor.Id"])
    assert "B1" in precursors
    # B2 is 1/4 detected; with budget 5 and 4 from A + B1, it should not displace B1
    assert "B1" in precursors


def test_keeps_all_sample_columns_and_matching_pg(tmp_path: Path):
    pr = _matrix()
    pg = pd.DataFrame(
        {
            "Protein.Group": ["P_A", "P_B", "P_C"],
            "ctrl_0.mzML": [50, 40, 999],
            "t1_1.mzML": [51, 41, 998],
            "t2_2.mzML": [52, 42, 997],
            "t3_3.mzML": [53, 43, 996],
        }
    )
    pr_path = tmp_path / "pr.tsv"
    pg_path = tmp_path / "pg.tsv"
    pr.to_csv(pr_path, sep="\t", index=False)
    pg.to_csv(pg_path, sep="\t", index=False)

    pr_out, pg_out, manifest = subset_diann_matrices_for_quick_analysis(
        str(pr_path),
        str(pg_path),
        tmp_path,
        "phospho",
        max_ptm_precursors=10,
    )
    pr_sub = pd.read_csv(pr_out, sep="\t")
    pg_sub = pd.read_csv(pg_out, sep="\t")
    for col in SAMPLES:
        assert col in pr_sub.columns
        assert col in pg_sub.columns
    assert set(pg_sub["Protein.Group"]) <= {"P_A", "P_B"}
    assert "P_C" not in set(pg_sub["Protein.Group"])
    assert manifest["median_normalization_not_comparable_to_full"] is True
    assert manifest["primary_claim_allowed"] is False
    assert manifest["preregistration"] == "exploratory"


def test_deterministic_order():
    keep_a, _ = select_quick_precursor_indices(_matrix(), "21", max_ptm_precursors=6)
    keep_b, _ = select_quick_precursor_indices(_matrix(), "21", max_ptm_precursors=6)
    assert list(keep_a) == list(keep_b)


def test_fails_when_no_target_ptm():
    pr = pd.DataFrame(
        [
            _pr_row("P_X", "X1", "AAAA", "AAAA", [1, 1, 1, 1], SAMPLES),
        ]
    )
    with pytest.raises(ValueError, match="UniMod:21"):
        select_quick_precursor_indices(pr, "21")


def test_resolve_quick_settings_defaults_and_clamp():
    defaults = resolve_quick_settings(None)
    assert defaults["max_ptm_precursors"] == 400
    assert defaults["per_protein_cap"] == 4
    assert defaults["min_detection_frac"] == 0.50
    assert defaults["keep_all_ptm"] is False
    assert defaults["keep_unmodified_pairs"] is True
    assert defaults["include_non_ptm"] is False
    assert defaults["max_non_ptm_proteins"] == 200
    assert defaults["overrides_applied"] == []

    clamped = resolve_quick_settings(
        {
            "quick_max_ptm_precursors": 99999,
            "quick_per_protein_cap": -3,
            "quick_min_detection_frac": 2.5,
            "quick_keep_unmodified_pairs": False,
        }
    )
    assert clamped["max_ptm_precursors"] == 5000
    assert clamped["per_protein_cap"] == 0
    assert clamped["min_detection_frac"] == 1.0
    assert clamped["keep_unmodified_pairs"] is False
    assert "max_ptm_precursors" in clamped["overrides_applied"]
    assert "keep_unmodified_pairs" in clamped["overrides_applied"]


def test_per_protein_cap_zero_keeps_all_sites_of_a_hub():
    keep, stats = select_quick_precursor_indices(
        _matrix(),
        "21",
        max_ptm_precursors=10,
        per_protein_cap=0,
        min_detection_frac=0.50,
    )
    kept = set(_matrix().loc[keep, "Precursor.Id"])
    assert "A5" in kept
    assert "B2" in kept
    assert stats["ptm_precursors_selected"] == 7


def test_drop_unmodified_pairs_when_asked():
    keep, stats = select_quick_precursor_indices(
        _matrix(),
        "21",
        max_ptm_precursors=10,
        per_protein_cap=4,
        keep_unmodified_pairs=False,
    )
    kept = set(_matrix().loc[keep, "Precursor.Id"])
    assert "A1u" not in kept
    assert stats["unmodified_pairs_added"] == 0


def test_include_non_ptm_proteins_adds_pg_only(tmp_path: Path):
    pr = _matrix()
    pg = pd.DataFrame(
        {
            "Protein.Group": ["P_A", "P_B", "P_C"],
            "ctrl_0.mzML": [50, 40, 999],
            "t1_1.mzML": [51, 41, 998],
            "t2_2.mzML": [52, 42, 997],
            "t3_3.mzML": [53, 43, 996],
        }
    )
    pr_path = tmp_path / "pr.tsv"
    pg_path = tmp_path / "pg.tsv"
    pr.to_csv(pr_path, sep="\t", index=False)
    pg.to_csv(pg_path, sep="\t", index=False)

    _, pg_out, manifest = subset_diann_matrices_for_quick_analysis(
        str(pr_path),
        str(pg_path),
        tmp_path,
        "phospho",
        analysis_options={
            "quick_analysis": True,
            "quick_include_non_ptm": True,
            "quick_max_non_ptm_proteins": 200,
            "quick_max_ptm_precursors": 10,
        },
    )
    pg_sub = pd.read_csv(pg_out, sep="\t")
    assert "P_C" in set(pg_sub["Protein.Group"])
    assert "P_C" in manifest["non_ptm_proteins_added"]
    pr_sub = pd.read_csv(manifest["pr_subset_path"], sep="\t")
    assert "C1" not in set(pr_sub["Precursor.Id"])
