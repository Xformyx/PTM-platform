"""Report-path identity and protein missing-value regressions."""
import numpy as np

from report_generation.core.nodes.temporal_comovement_node import _build_temporal_matrix
from report_generation.core.temporal_analysis import build_nonptm_temporal_analysis


def test_distinct_precursors_at_same_gene_site_are_kept():
    networks = {
        "1min": {
            "active_nodes": [
                {"gene": "MAPK1", "site": "Y187", "feature_id": "PF-AAAAAAAA", "value": 1.0, "activity_class": "regulated"},
                {"gene": "MAPK1", "site": "Y187", "feature_id": "PF-BBBBBBBB", "value": -1.0, "activity_class": "regulated"},
            ]
        },
        "5min": {
            "active_nodes": [
                {"gene": "MAPK1", "site": "Y187", "feature_id": "PF-AAAAAAAA", "value": 2.0, "activity_class": "regulated"},
                {"gene": "MAPK1", "site": "Y187", "feature_id": "PF-BBBBBBBB", "value": -2.0, "activity_class": "regulated"},
            ]
        },
    }
    matrix, meta = _build_temporal_matrix(networks, ["1min", "5min"])
    assert len(meta) == 2
    assert {row["feature_id"] for row in meta} == {"PF-AAAAAAAA", "PF-BBBBBBBB"}
    assert matrix.shape[0] == 2


def test_missing_timepoint_is_nan_not_zero():
    networks = {
        "1min": {"active_nodes": [{"gene": "AKT1", "site": "S473", "feature_id": "PF-CCCCCCCC", "value": 1.0}]},
        "5min": {"active_nodes": []},
        "15min": {"active_nodes": [{"gene": "AKT1", "site": "S473", "feature_id": "PF-CCCCCCCC", "value": 0.0}]},
    }
    matrix, _ = _build_temporal_matrix(networks, ["1min", "5min", "15min"])
    assert np.isnan(matrix[0, 1])
    assert matrix[0, 2] == 0.0


def test_protein_missing_is_not_called_stable_significant():
    text = build_nonptm_temporal_analysis(
        {
            "networks": {
                "1min": {"non_ptm_nodes": [{"gene": "IRS1", "protein_log2fc": 0.05}]},
                "5min": {"non_ptm_nodes": [{"gene": "IRS1"}]},
            }
        },
        ["1min", "5min"],
        "phosphorylation",
    )
    assert "no significant abundance change" not in text.lower()
    assert "descriptive 0.3 threshold" in text
