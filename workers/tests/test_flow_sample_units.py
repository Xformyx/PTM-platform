import pandas as pd
import pytest
from ptm_shared.sample_manifest import validate_sample_manifest, unit_test_inputs, compare_sample_units
from test_observation_denominator_contract import analyzer_for, quantify


def test_real_quantitation_keeps_effect_but_withholds_technical_only_p():
    analyzer = analyzer_for([100, 110, 210], [1000, 1000, 1000])
    analyzer.sample_columns = ["c1", "c2", "t1", "t2"]
    analyzer.condition_map["t2"] = "5min"
    analyzer.pr_matrix_normalized["t2"] = 200
    analyzer.pg_matrix_normalized["t2"] = 1000
    before = quantify(analyzer)[2].iloc[0]
    analyzer.sample_manifest = {"pairing": "unpaired", "samples": [
        {"sample_id": sid, "condition": cond, "biological_unit": cond, "technical_injection": sid}
        for sid, cond in analyzer.condition_map.items()]}
    after = quantify(analyzer)[2].iloc[0]
    assert after["PTM_Unadjusted_Log2FC"] == before["PTM_Unadjusted_Log2FC"]
    assert after["PTM_ProteinAdjusted_Log2FC"] == before["PTM_ProteinAdjusted_Log2FC"]
    assert pd.isna(after["PTM_Unadjusted_P_Value"]) and pd.isna(after["q_value"])
    assert after["PTM_Unadjusted_Statistical_Unit"] == "biological_unit"
    assert "test_unavailable" in after["PTM_ProteinAdjusted_Test_Status"]


def test_unit_aggregation_and_pairing_are_filename_invariant():
    manifest = {"pairing": "paired", "samples": [{"sample_id": s, "biological_unit": u} for s, u in
                [("z", "A"), ("a", "A"), ("b", "B"), ("t1", "A"), ("t2", "B")]]}
    inputs = unit_test_inputs({"z": 8, "a": 12, "b": 100}, {"t1": 20, "t2": 400}, manifest)
    assert inputs["control"] == [10, 100] and inputs["treatment"] == [20, 400]
    assert inputs["paired_units"] == ["A", "B"]
    manifest["samples"][0]["sample_id"] = "renamed"
    assert unit_test_inputs({"renamed": 8, "a": 12, "b": 100}, {"t1": 20, "t2": 400}, manifest) == inputs


def test_manifest_checks_explicit_columns_and_conditions():
    missing = validate_sample_manifest(None)
    assert validate_sample_manifest(missing) == missing
    manifest = {"samples": [{"sample_id": "c", "condition": "Control", "biological_unit": "A"}]}
    assert validate_sample_manifest(manifest, {"c": "Control"}, ["c"], ["c"])["status"] == "validated"
    for condition_map, columns in [({"c": "5min"}, ["c"]), ({"c": "Control"}, ["different"])]:
        with pytest.raises(ValueError):
            validate_sample_manifest(manifest, condition_map, columns, ["c"])
