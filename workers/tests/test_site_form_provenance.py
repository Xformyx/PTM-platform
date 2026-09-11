import importlib.util
from pathlib import Path

from ptm_shared.site_form_provenance import (
    aggregate_site_form_trajectories,
    audit_enriched_site_form_records,
    audit_enriched_vector_crosswalk,
    form_identity,
)


_MERGER_PATH = Path(__file__).resolve().parents[1] / "rag_enrichment" / "core" / "ptm_merger.py"
_SPEC = importlib.util.spec_from_file_location("rag_ptm_merger_form_test", _MERGER_PATH)
assert _SPEC and _SPEC.loader
_MERGER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MERGER)
collapse_ptm_rows_for_enrichment = _MERGER.collapse_ptm_rows_for_enrichment


def test_form_identity_prefers_modified_sequence_and_charge():
    identity = form_identity({
        "gene": "AKT1",
        "position": "S473",
        "Modified.Sequence": "RPHFPQFSYSAS(UniMod:21)TA",
        "Precursor.Charge": 2,
        "Precursor.Id": "precursor-1",
    })
    assert identity["site_key"] == "AKT1_S473"
    assert identity["site_form_key"].endswith("seq=RPHFPQFSYSAS(UniMod:21)TA|z=2")
    assert identity["form_identity_status"] == "resolved_sequence_charge"


def test_form_identity_is_explicitly_unresolved_without_sequence_or_charge():
    identity = form_identity({"gene": "AKT1", "position": "S473"})
    assert identity["site_form_key"] == "AKT1_S473|form=unresolved"
    assert identity["form_identity_status"] == "unresolved_missing_sequence_charge"
    assert identity["report_eligible"] is False


def test_form_identity_recovers_charge_from_exact_precursor_suffix_and_never_serializes_nan():
    identity = form_identity({
        "gene": "AKT1",
        "position": "S473",
        "Modified.Sequence": "AA(UniMod:21)PEPTIDE",
        "Precursor.Charge": float("nan"),
        "Precursor.Id": "AA(UniMod:21)PEPTIDE3",
    })
    assert identity["site_form_key"].endswith("|z=3")
    assert "nan" not in identity["site_form_key"].lower()
    assert identity["precursor_charge_source"] == "recovered_from_exact_precursor_suffix"
    assert identity["report_eligible"] is True


def test_site_aggregate_uses_per_timepoint_median_and_retains_form_keys():
    aggregate = aggregate_site_form_trajectories([
        {
            "site_form_key": "AKT1_S473|seq=A|z=2",
            "trajectory": {"timepoints": [
                {"timeLabel": "10min", "ptmLog2FC": 3.0},
                {"timeLabel": "0min", "ptmLog2FC": 1.0},
            ]},
        },
        {
            "site_form_key": "AKT1_S473|seq=B|z=3",
            "trajectory": {"timepoints": [
                {"timeLabel": "0min", "ptmLog2FC": 3.0},
                {"timeLabel": "10min", "ptmLog2FC": 1.0},
            ]},
        },
    ])
    assert aggregate["aggregation_method"] == "per_timepoint_median_track2_across_forms"
    assert aggregate["form_count"] == 2
    assert [point["timeLabel"] for point in aggregate["timepoints"]] == ["0min", "10min"]
    assert [point["ptmLog2FC"] for point in aggregate["timepoints"]] == [2.0, 2.0]
    assert all(point["contributing_form_count"] == 2 for point in aggregate["timepoints"])
    assert all(point["contributing_value_count"] == 2 for point in aggregate["timepoints"])
    assert aggregate["report_eligible"] is True


def test_collapse_preserves_site_forms_and_avoids_first_row_trajectory_selection():
    rows = [
        {
            "gene": "AKT1", "position": "S473", "Condition": "0min",
            "Modified.Sequence": "FORM_A", "Precursor.Charge": 2,
            "PTM_Relative_Log2FC": 1.0, "Protein_Log2FC": 0.0,
        },
        {
            "gene": "AKT1", "position": "S473", "Condition": "0min",
            "Modified.Sequence": "FORM_B", "Precursor.Charge": 3,
            "PTM_Relative_Log2FC": 3.0, "Protein_Log2FC": 0.0,
        },
        {
            "gene": "AKT1", "position": "S473", "Condition": "10min",
            "Modified.Sequence": "FORM_A", "Precursor.Charge": 2,
            "PTM_Relative_Log2FC": 5.0, "Protein_Log2FC": 0.0,
        },
        {
            "gene": "AKT1", "position": "S473", "Condition": "10min",
            "Modified.Sequence": "FORM_B", "Precursor.Charge": 3,
            "PTM_Relative_Log2FC": 1.0, "Protein_Log2FC": 0.0,
        },
    ]
    collapsed = collapse_ptm_rows_for_enrichment(rows)
    assert len(collapsed) == 1
    site = collapsed[0]
    assert len(site["site_form_trajectories"]) == 2
    assert site["site_aggregation"]["form_count"] == 2
    assert [point["ptmLog2FC"] for point in site["trajectory"]["timepoints"]] == [2.0, 3.0]
    assert site["site_form_provenance_audit"]["status"] == "validated"
    assert site["report_eligible_temporal_site_aggregation"] is True


def test_same_sequence_charge_two_and_three_remain_distinct_forms():
    rows = []
    for charge, precursor, value in ((2, "FORM2", 1.0), (3, "FORM3", 3.0)):
        rows.append({
            "gene": "MAPK1", "position": "T185", "Condition": "5min",
            "Modified.Sequence": "VADPDHT(UniMod:21)EY(UniMod:21)VATR",
            "Precursor.Charge": charge, "Precursor.Id": precursor,
            "PTM_Relative_Log2FC": value, "Protein_Log2FC": 0.0,
        })
    site = collapse_ptm_rows_for_enrichment(rows)[0]
    keys = [form["site_form_key"] for form in site["site_form_trajectories"]]
    assert len(keys) == len(set(keys)) == 2
    assert any(key.endswith("|z=2") for key in keys)
    assert any(key.endswith("|z=3") for key in keys)


def test_duplicate_precursor_condition_fails_closed():
    row = {
        "gene": "AKT1", "position": "S473", "Condition": "5min",
        "Modified.Sequence": "FORM_A", "Precursor.Charge": 2, "Precursor.Id": "FORM_A2",
        "PTM_Relative_Log2FC": 1.0, "Protein_Log2FC": 0.0,
    }
    try:
        collapse_ptm_rows_for_enrichment([row, dict(row)])
    except ValueError as exc:
        assert "duplicate precursor-condition" in str(exc)
    else:
        raise AssertionError("duplicate precursor-condition must fail closed")


def test_legacy_nan_charge_and_inconsistent_form_count_are_report_ineligible():
    audit = audit_enriched_site_form_records([{
        "gene": "AKT1",
        "position": "S473",
        "Precursor.Id": "FORM2",
        "condition_data": [{"condition": "5min", "precursor_id": "FORM2"}],
        "site_form_trajectories": [{
            "site_form_key": "AKT1_S473|seq=FORM|z=nan",
            "precursor_id": "FORM2",
            "report_eligible": True,
            "trajectory": {"timepoints": [{"timeLabel": "5min", "ptmLog2FC": 1.0}]},
        }],
        "site_aggregation": {
            "form_count": 0,
            "source_form_keys": [],
            "timepoints": [{
                "timeLabel": "5min", "ptmLog2FC": 1.0,
                "contributing_form_count": 2,
                "contributing_form_keys": ["AKT1_S473|seq=FORM|z=nan"],
            }],
        },
    }])
    assert audit["status"] == "incompatible"
    assert audit["report_eligible"] is False
    assert audit["error_code_counts"]["noncanonical_nan_charge"] == 1


def test_enriched_vector_crosswalk_requires_exact_precursor_condition_and_value():
    enriched = [{
        "condition_data": [
            {"precursor_id": "FORM2", "condition": "5min", "ptm_relative_log2fc": 1.25},
            {"precursor_id": "FORM3", "condition": "5min", "ptm_relative_log2fc": -0.5},
        ],
    }]
    vector = [
        {"precursor_id": "FORM2", "condition": "5min", "log2fc": 1.25},
        {"precursor_id": "FORM3", "condition": "5min", "log2fc": -0.5},
    ]
    audit = audit_enriched_vector_crosswalk(enriched, vector)
    assert audit["status"] == "validated"
    assert audit["compared_pair_count"] == 2

    mismatch = audit_enriched_vector_crosswalk(
        enriched,
        [
            {"precursor_id": "FORM2", "condition": "5min", "log2fc": 1.25},
            {"precursor_id": "FORM3", "condition": "5min", "log2fc": 0.5},
        ],
    )
    assert mismatch["status"] == "incompatible"
    assert mismatch["error_codes"] == ["enriched_vector_value_mismatch"]
