import json

import pytest

from benchmarking.blind_trial_ledger import (
    BlindTrialLedgerError,
    append_trial,
    registry_document,
    verify_ledger,
)


HASHES = {
    "quant_matrix_primary": "a" * 64,
    "quant_matrix_normalizer": "b" * 64,
    "sequence_database": "c" * 64,
}
CONFIG = {
    "site_aggregation": "median",
    "wave.correlation_threshold": 0.7,
    "tmm.target_transform": "magnitude",
}


def test_append_trial_builds_verifiable_hash_chain(tmp_path) -> None:
    path = tmp_path / "trials.jsonl"
    first = append_trial(
        path,
        trial_id="trial-001",
        phase="artifact_integrity",
        code_commit="abc123",
        input_hashes=HASHES,
        variable_config=CONFIG,
        objective={"duplicate_key_count": 0},
        fold_metrics=[],
        decision="continue",
        decision_reason="canonical key contract passed",
        created_at="2026-08-26T00:00:00+00:00",
    )
    second = append_trial(
        path,
        trial_id="trial-002",
        phase="activity_ablation",
        code_commit="abc124",
        input_hashes=HASHES,
        variable_config={**CONFIG, "activity.effect_size": "weighted_mean"},
        objective={"holdout_residual": 0.7},
        fold_metrics=[{"fold": 0, "holdout_residual": 0.72}],
        decision="select",
        decision_reason="truth-free fold objective improved",
        parent_config_sha256=first["config_sha256"],
        created_at="2026-08-26T00:01:00+00:00",
    )
    records = verify_ledger(path)
    assert len(records) == 2
    assert second["previous_record_sha256"] == first["record_sha256"]
    assert all(record["truth_used_for_selection"] is False for record in records)


@pytest.mark.parametrize(
    "field,value",
    [
        ("stimulus", "neutral"),
        ("notes", "insulin-specific expected kinase"),
        ("reference_workbook_hash", "d" * 64),
    ],
)
def test_ledger_rejects_truth_or_identity_content(tmp_path, field, value) -> None:
    with pytest.raises(BlindTrialLedgerError):
        append_trial(
            tmp_path / "trials.jsonl",
            trial_id="trial-forbidden",
            phase="blind_selection",
            code_commit="abc123",
            input_hashes=HASHES,
            variable_config=CONFIG,
            objective={field: value},
            fold_metrics=[],
            decision="reject",
            decision_reason="boundary test",
        )


def test_registry_is_versioned_and_hashable() -> None:
    document = registry_document()
    assert document["schema_version"] == "strict_blind_temporal_variables.v1"
    assert len(document["registry_sha256"]) == 64
    assert "activity.effect_size" in document["variables"]
