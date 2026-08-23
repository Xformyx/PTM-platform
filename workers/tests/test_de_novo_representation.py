"""De novo representation contract tests.

구현 대상: docs/de_novo_representation_contract_v1.md §3–§8
사전등록: 2026-08-23. 탐색적.
해석 한계: 합성 intensity로 산식만 고정한다. 생물학적 중요도를 검증하지 않는다.
주장 금지: 통과를 kinase 귀속 또는 fold-change 정확도 개선으로 서술하지 않는다.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ptm_shared.de_novo_representation import (
    LOD_INDUCTION_RANK_CAP,
    LOD_PERCENTILE,
    DetectionCount,
    attach_de_novo_fields,
    classify_denovo_confidence,
    compute_site_metrics,
    estimate_control_lod,
    format_denovo_prompt_line,
    heatmap_denovo_value,
    heatmap_denovo_weight,
    lod_relative_log2,
    narrative_eligible_denovo,
    plot_value_for_row,
    ranking_score_for_site,
)


def _count(cond: str, detected: int, expected: int = 3) -> DetectionCount:
    return DetectionCount(condition=cond, detected=detected, expected=expected)


def test_lod_is_median_of_per_run_fifth_percentile():
    rows = []
    for run, values in (
        ("c1", [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
        ("c2", [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]),
    ):
        for i, intensity in enumerate(values):
            rows.append({
                "Protein.Group": f"P{i}",
                "Precursor.Id": f"pr{i}",
                "Sample": run,
                "Condition": "Control",
                "PTM_Intensity": intensity,
                "PTM_Relative_Abundance": intensity / 1000.0,
            })
    lod = estimate_control_lod(pd.DataFrame(rows))
    expected = np.median([
        float(np.percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], LOD_PERCENTILE)),
        float(np.percentile([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000], LOD_PERCENTILE)),
    ])
    assert lod is not None
    assert abs(lod - expected) < 1e-9


def test_lod_relative_is_lower_bound_log2_and_never_uses_pseudocount():
    lod = 16.0
    treatment = 16.0 * (2 ** 4.2)
    value = lod_relative_log2(treatment, lod)
    assert value is not None
    assert abs(value - 4.2) < 1e-9
    assert lod_relative_log2(treatment, None) is None
    assert lod_relative_log2(0.0, lod) is None


def test_confidence_grades_match_declared_detection_rules():
    control = _count("Control", 0)
    high = [
        _count("1min", 1),
        _count("5min", 3),
        _count("15min", 2),
        _count("30min", 3),
        _count("60min", 0),
    ]
    assert classify_denovo_confidence(control, high) == "high"
    assert classify_denovo_confidence(control, high, shared_peptide=True) == "high_shared"

    moderate = [_count("5min", 2), _count("15min", 1), _count("30min", 0)]
    assert classify_denovo_confidence(control, moderate) == "moderate"

    low = [_count("5min", 1), _count("15min", 0)]
    assert classify_denovo_confidence(control, low) == "low"

    assert classify_denovo_confidence(_count("Control", 1), high) == "ambiguous"
    isolated_full = [_count("5min", 3), _count("15min", 0), _count("30min", 0)]
    assert classify_denovo_confidence(control, isolated_full) == "moderate"


def test_peak_prefers_full_detection_over_higher_partial_abundance():
    control = _count("Control", 0)
    rows = [
        {"condition": "1min", "detected": 1, "expected": 3, "relative_abundance": 0.01, "mean_intensity": 100.0, "cv": 0.4},
        {"condition": "5min", "detected": 3, "expected": 3, "relative_abundance": 0.20, "mean_intensity": 400.0, "cv": 0.10},
        {"condition": "15min", "detected": 2, "expected": 3, "relative_abundance": 0.80, "mean_intensity": 800.0, "cv": 0.05},
        {"condition": "30min", "detected": 3, "expected": 3, "relative_abundance": 0.15, "mean_intensity": 300.0, "cv": 0.20},
    ]
    metrics = compute_site_metrics(
        control_detection=control,
        treatment_rows=rows,
        lod_intensity=25.0,
        abs_conventional_log2fc=29.1,
    )
    assert metrics.is_de_novo is True
    assert metrics.peak_condition == "5min"
    assert metrics.peak_is_provisional is False
    assert metrics.provisional_higher_partial == "15min"
    assert metrics.onset_condition == "1min"
    assert metrics.reliable_onset_condition == "5min"
    assert metrics.lod_relative_log2 is not None
    assert abs(metrics.lod_relative_log2 - math.log2(400.0 / 25.0)) < 1e-9
    assert metrics.ranking_score <= LOD_INDUCTION_RANK_CAP
    assert metrics.ranking_score < 29.1


def test_denovo_ranking_never_uses_pseudo_log2fc():
    huge = ranking_score_for_site(
        is_de_novo=True,
        confidence="high",
        detection_fraction_at_peak=1.0,
        lod_relative=4.2,
        abs_conventional_log2fc=29.1,
    )
    regulated = ranking_score_for_site(
        is_de_novo=False,
        confidence="",
        detection_fraction_at_peak=1.0,
        lod_relative=None,
        abs_conventional_log2fc=2.5,
    )
    legacy = ranking_score_for_site(
        is_de_novo=True,
        confidence="moderate",
        detection_fraction_at_peak=0.0,
        lod_relative=None,
        abs_conventional_log2fc=29.1,
    )
    assert huge == LOD_INDUCTION_RANK_CAP
    assert regulated == 2.5
    assert legacy == 1.5 * 0.55
    assert huge > regulated
    assert legacy < regulated


def test_heatmap_discards_de_novo_boost_and_caps_value():
    assert heatmap_denovo_weight("high") == 0.80
    assert heatmap_denovo_weight("low") == 0.20
    assert heatmap_denovo_value(29.1) == LOD_INDUCTION_RANK_CAP
    assert heatmap_denovo_value(2.2) == 2.2


def test_attach_marks_conventional_log2fc_na_and_writes_detection_pattern():
    relative = pd.DataFrame([
        {"Protein.Group": "P1", "Precursor.Id": "pr1", "Sample": "c1", "Condition": "Control",
         "PTM_Intensity": 20.0, "PTM_Relative_Abundance": 0.02},
        {"Protein.Group": "P1", "Precursor.Id": "pr1", "Sample": "c2", "Condition": "Control",
         "PTM_Intensity": 22.0, "PTM_Relative_Abundance": 0.02},
        {"Protein.Group": "P1", "Precursor.Id": "pr1", "Sample": "c3", "Condition": "Control",
         "PTM_Intensity": 24.0, "PTM_Relative_Abundance": 0.02},
        {"Protein.Group": "P9", "Precursor.Id": "denovo", "Sample": "t1a", "Condition": "5min",
         "PTM_Intensity": 400.0, "PTM_Relative_Abundance": 0.2},
        {"Protein.Group": "P9", "Precursor.Id": "denovo", "Sample": "t1b", "Condition": "5min",
         "PTM_Intensity": 420.0, "PTM_Relative_Abundance": 0.21},
        {"Protein.Group": "P9", "Precursor.Id": "denovo", "Sample": "t1c", "Condition": "5min",
         "PTM_Intensity": 410.0, "PTM_Relative_Abundance": 0.205},
        {"Protein.Group": "P9", "Precursor.Id": "denovo", "Sample": "t2a", "Condition": "15min",
         "PTM_Intensity": 200.0, "PTM_Relative_Abundance": 0.1},
        {"Protein.Group": "P9", "Precursor.Id": "denovo", "Sample": "t2b", "Condition": "15min",
         "PTM_Intensity": 210.0, "PTM_Relative_Abundance": 0.11},
        {"Protein.Group": "P1", "Precursor.Id": "pr1", "Sample": "t2c", "Condition": "15min",
         "PTM_Intensity": 30.0, "PTM_Relative_Abundance": 0.03},
    ])
    comparisons = pd.DataFrame([
        {
            "Protein.Group": "P9",
            "Precursor.Id": "denovo",
            "Condition": "5min",
            "Log2FC": 29.1,
            "Control_Pseudocount_Used": True,
        },
        {
            "Protein.Group": "P9",
            "Precursor.Id": "denovo",
            "Condition": "15min",
            "Log2FC": 27.4,
            "Control_Pseudocount_Used": True,
        },
    ])
    attached = attach_de_novo_fields(comparisons, relative)
    assert attached["Conventional_Log2FC_NA"].all()
    assert attached.iloc[0]["Detection_Control"] == "0/3"
    assert attached.iloc[0]["Detection_Treatment"] == "3/3"
    assert attached.iloc[1]["Detection_Treatment"] == "2/3"
    assert attached.iloc[0]["Detection_Pattern"] == "3/3 → 2/3"
    assert attached.iloc[0]["DeNovo_Confidence"] == "high"
    assert attached.iloc[0]["Ranking_Score"] < 29.1
    assert attached.iloc[0]["Peak_Condition"] == "5min"


def test_plot_and_prompt_never_surface_pseudo_log2fc():
    value, axis = plot_value_for_row({
        "control_pseudocount_used": True,
        "ptm_relative_log2fc": 29.1,
        "lod_relative_log2": 4.2,
    })
    assert value == 4.2
    assert axis == "lod_relative"
    line = format_denovo_prompt_line({
        "gene": "IRS1",
        "position": "S522",
        "denovo_confidence": "high",
        "detection_control": "0/3",
        "detection_pattern": "1/3 → 3/3 → 2/3",
        "lod_relative_log2": 4.2,
        "peak_condition": "15min",
        "onset_condition": "1min",
        "reliable_onset_condition": "5min",
    })
    assert "29.1" not in line
    assert "Log2FC=NA" in line
    assert "≥4.2 log2" in line
    assert narrative_eligible_denovo("low") is False
    assert narrative_eligible_denovo("high") is True
