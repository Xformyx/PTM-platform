import importlib.util
from pathlib import Path

from ptm_shared.site_form_provenance import (
    aggregate_site_form_trajectories,
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
