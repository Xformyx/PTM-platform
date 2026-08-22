import math

from ptm_shared.atlas_compat import atlas_form_trajectories, atlas_records, json_safe


def test_atlas_records_accepts_legacy_wrapped_payload():
    records = atlas_records({"enriched_ptms": [{"gene": "AKT1", "position": "S473"}]})
    assert records == [{"gene": "AKT1", "position": "S473"}]


def test_atlas_form_trajectories_skips_malformed_legacy_forms():
    record = {
        "gene": "AKT1",
        "site_form_trajectories": ["legacy-string", {"trajectory": {"timepoints": "invalid"}}],
    }
    assert atlas_form_trajectories(record) == []


def test_atlas_form_trajectories_falls_back_to_legacy_top_level_trajectory():
    forms = atlas_form_trajectories({
        "gene": "AKT1",
        "trajectory": {"timepoints": [{"timeLabel": "0m", "ptmLog2FC": 0.0}]},
    })
    assert len(forms) == 1
    assert forms[0]["trajectory"]["timepoints"][0]["timeLabel"] == "0m"


def test_json_safe_replaces_non_finite_values_before_fastapi_serialization():
    payload = json_safe({"nan": math.nan, "nested": [math.inf, -math.inf, 1.5]})
    assert payload == {"nan": None, "nested": [None, None, 1.5]}
