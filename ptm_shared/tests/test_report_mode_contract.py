from ptm_shared.report_mode import (
    apply_report_mode_contract,
    is_reader_mode,
    resolve_report_mode_contract,
)


def test_researcher_with_shadow_is_valid():
    contract = resolve_report_mode_contract({
        "report_audience": "researcher_manuscript",
        "reader_authoring_mode": "shadow",
        "technical_audit_delivery": "separate_sidecar",
    })
    assert contract["valid"] is True
    assert contract["effective_reader_mode"] == "shadow"
    assert contract["report_audience"] == "researcher_manuscript"
    assert is_reader_mode(contract) is True


def test_researcher_missing_mode_is_mismatch():
    contract = resolve_report_mode_contract({"report_audience": "researcher_manuscript"})
    assert contract["valid"] is False
    assert "audience_mode_mismatch" in contract["reason_codes"]
    assert is_reader_mode({"report_audience": "researcher_manuscript"}) is False


def test_researcher_legacy_mode_is_mismatch():
    contract = resolve_report_mode_contract({
        "report_audience": "researcher_manuscript",
        "reader_authoring_mode": "legacy",
    })
    assert contract["valid"] is False
    assert "audience_mode_mismatch" in contract["reason_codes"]


def test_technical_legacy_is_valid_and_labelled():
    contract = resolve_report_mode_contract({
        "report_audience": "technical_audit",
        "reader_authoring_mode": "legacy",
        "technical_audit_delivery": "embedded_technical_report",
        "technical_audit_explicit": True,
    })
    assert contract["valid"] is True
    assert contract["effective_reader_mode"] == "legacy"
    assert is_reader_mode(contract) is False


def test_technical_shadow_is_rejected_as_mode_mismatch():
    contract = resolve_report_mode_contract({
        "report_audience": "technical_audit",
        "reader_authoring_mode": "shadow",
        "technical_audit_explicit": True,
    })
    assert contract["valid"] is False
    assert "technical_audience_with_shadow_renderer" in contract["reason_codes"]
    assert contract["report_audience"] == "technical_audit"


def test_unknown_enum_is_schema_error():
    contract = resolve_report_mode_contract({
        "report_audience": "scientist",
        "reader_authoring_mode": "shadow",
    })
    assert contract["valid"] is False
    assert "schema_validation_error" in contract["reason_codes"]


def test_historical_shadow_only_migrates_to_researcher():
    contract = resolve_report_mode_contract({"reader_authoring_mode": "shadow"})
    assert contract["valid"] is True
    assert contract["report_audience"] == "researcher_manuscript"
    assert contract["effective_reader_mode"] == "shadow"
    assert "historical_shadow_migrated_to_researcher_manuscript" in contract["reason_codes"]


def test_missing_audience_fails_closed_and_never_assumes_technical():
    contract = resolve_report_mode_contract({})
    assert contract["valid"] is False
    assert contract["report_audience"] == ""
    assert contract["effective_reader_mode"] == ""
    assert "missing_report_audience_contract" in contract["reason_codes"]


def test_historical_implicit_legacy_contract_is_rejected_on_replay():
    contract = resolve_report_mode_contract({
        "contract_version": "report_audience_mode.v1",
        "report_audience": "technical_audit",
        "requested_reader_mode": "legacy",
        "effective_reader_mode": "legacy",
        "technical_audit_delivery": "embedded_technical_report",
        "valid": True,
        "reason_codes": ["historical_legacy_default"],
        "migration_rule": "historical_legacy_default",
    })
    assert contract["valid"] is False
    assert contract["report_audience"] == ""
    assert "implicit_legacy_contract_rejected" in contract["reason_codes"]


def test_legacy_technical_fields_without_explicit_intent_are_rejected():
    contract = resolve_report_mode_contract({
        "report_audience": "technical_audit",
        "reader_authoring_mode": "legacy",
        "technical_audit_delivery": "embedded_technical_report",
    })
    assert contract["valid"] is False
    assert "technical_audit_intent_not_explicit" in contract["reason_codes"]


def test_apply_writes_canonical_fields():
    effective, contract = apply_report_mode_contract({
        "md_summary_max_chars": 4000,
        "reader_authoring_mode": "opt_in_shadow",
    })
    assert effective["report_audience"] == "researcher_manuscript"
    assert effective["reader_authoring_mode"] == "opt_in_shadow"
    assert effective["technical_audit_delivery"] == "separate_sidecar"
    assert effective["md_summary_max_chars"] == 4000
    assert contract["valid"] is True
