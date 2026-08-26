import math

from ptm_shared.motif_candidate_calibration import (
    calibrate_motif_annotations,
    candidate_resolution_level,
    hierarchy_family,
)


def test_background_calibration_prefers_rarer_confirmed_motif():
    annotations = [
        {
            "sequence_window": "AAAAARQQSPKAAA",
            "motif_predicted_kinases": [
                {"canonical_family": "BROAD", "kinase_family": "BROAD", "source": "inline_motif_match"},
                {"canonical_family": "SPECIFIC", "kinase_family": "SPECIFIC", "source": "inline_motif_match"},
            ],
        },
        {"sequence_window": "AAAAATPKAAAA", "motif_predicted_kinases": []},
        {"sequence_window": "AAAAASPGAAAA", "motif_predicted_kinases": []},
        {"sequence_window": "AAAAATPEAAAA", "motif_predicted_kinases": []},
    ]
    calibrated, summary = calibrate_motif_annotations(
        annotations,
        {"BROAD": [r"[ST]P"], "SPECIFIC": [r"R..[ST]P[KR]"]},
    )
    candidates = calibrated[0]["motif_predicted_kinases"]
    probabilities = {row["canonical_family"]: row["candidate_probability"] for row in candidates}
    assert probabilities["SPECIFIC"] > probabilities["BROAD"]
    assert math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-7)
    assert summary["selection_boundary"].startswith("observed sequence")


def test_residue_prediction_remains_low_information():
    annotations = [{
        "sequence_window": "AAAAASAAAAA",
        "motif_predicted_kinases": [
            {"canonical_family": "CK2", "kinase_family": "CK2", "source": "residue_prediction"},
        ],
    }]
    calibrated, _ = calibrate_motif_annotations(annotations, {"CK2": [r"[ST]..[DE]"]})
    candidate = calibrated[0]["motif_predicted_kinases"][0]
    assert candidate["candidate_support_class"] == "residue_only_low_information"
    assert candidate["candidate_probability"] == 1.0


def test_hierarchy_is_conservative_for_family_and_isoform_names():
    assert hierarchy_family("CDK1/CDK2") == "CDK"
    assert hierarchy_family("CDK1") == "CDK"
    assert hierarchy_family("MAPK1") == "MAPK"
    assert hierarchy_family("MTOR") == "MTOR"
    assert candidate_resolution_level("CDK1/CDK2") == "family"
    assert candidate_resolution_level("CDK1") == "gene_or_isoform"
