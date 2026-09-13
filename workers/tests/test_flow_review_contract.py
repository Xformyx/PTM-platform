"""Whole-flow review regressions; synthetic inputs, no external services."""
import pytest
from report_generation.core.report_release import resolve_report_release
from report_generation.core.vector_projection import project_report_vector_row
from report_generation.core.measured_feature_cards import build_feature_observation_cards
from report_generation.core.reader_authoring import build_authoring_packet, deterministic_authoring_plan
from test_task10_joint_patterns import supported_row


@pytest.mark.parametrize("audit,manifest", [
    (None, {"status": "validated", "report_eligible": True}),
    ({"status": "passed"}, {"status": "validated", "report_eligible": False, "render_status": "incomplete"}),
    ({"status": "passed"}, {"status": "validated", "report_eligible": True, "render_status": "incomplete"}),
])
def test_release_requires_audit_and_completed_render(audit, manifest):
    assert not resolve_report_release(reader_authoring_shadow=True, output_correctness=audit,
                                      artifact_manifest=manifest)["publish_as_final"]


def test_structural_block_survives_incompatible_manifest():
    release = resolve_report_release(reader_authoring_shadow=True,
        output_correctness={"status": "blocked_for_review", "reason_codes": ["phantom_figure"]},
        artifact_manifest={"status": "incompatible", "reason_codes": ["changed_source"]})
    assert not release["review_artifact_available"]
    assert {"phantom_figure", "changed_source"} <= set(release["reason_codes"])


def test_charge_fallback_and_protein_group_keep_separate_features():
    rows = [supported_row(precursor="", condition=c, modified_sequence="AS[Phospho]K", precursor_charge=z)
            for z, c in ((2, "5min"), (3, "40min"))]
    projected = [project_report_vector_row(r) for r in rows]
    cards = build_feature_observation_cards({"vector_plot_raw_data": projected}, minimum_points=1)
    assert len(cards) == 2
    assert len({c["feature_identity"]["reader_feature_id"] for c in cards}) == 2
    assert {c["feature_identity"]["precursor_charge"] for c in cards} == {"2", "3"}
    rows = [supported_row(protein_group=pg) for pg in ("PG1", "PG2")]
    assert len(build_feature_observation_cards({"vector_plot_raw_data": rows}, minimum_points=1)) == 2
    from ptm_shared.temporal_feature_input import build_temporal_feature_inputs
    packet = build_temporal_feature_inputs(rows)
    assert set(packet["features"]) == {c["feature_identity"]["feature_id"] for c in build_feature_observation_cards({"vector_plot_raw_data": rows}, minimum_points=1)}


def test_identity_conflict_is_local_and_legacy_crosswalk_is_ambiguous():
    from ptm_shared.feature_identity import audit_feature_identities
    rows = [supported_row(condition="5min"), supported_row(condition="5min", ptm_unadjusted_log2fc=9), supported_row(condition="40min")]
    cards = build_feature_observation_cards({"vector_plot_raw_data": rows}, minimum_points=1)
    assert len(cards) == 1
    assert cards[0]["axis_patterns"]["unadjusted"]["missing_conditions"] == ["5min"]
    assert audit_feature_identities(rows)["conflicting_feature_conditions"]
    ambiguous = [supported_row(protein_group=group) for group in ("PG1", "PG2")]
    audit = audit_feature_identities(ambiguous)
    assert len(audit["ambiguous_legacy_ids"]) == 1
    assert audit == audit_feature_identities(ambiguous[::-1])


def test_absent_row_has_same_missing_grid_as_explicit_null():
    rows = [supported_row(condition=c) for c in ("1min", "15min")]
    rows.append(supported_row(precursor="other", condition="5min"))
    cards = build_feature_observation_cards({"vector_plot_raw_data": rows}, maximum=5, minimum_points=1)
    target = next(c for c in cards if c["feature_identity"]["source_feature_id"] == "P1")
    assert target["axis_patterns"]["adjusted"]["missing_conditions"] == ["5min"]
    assert not target["clustering_eligible"]
    assert next(p for p in target["trajectory"] if p["condition"] == "5min")["axes"]["adjusted"]["value"] is None


def test_generic_reference_does_not_imply_feature_was_searched():
    packet = build_authoring_packet({"vector_plot_raw_data": [supported_row(condition=c) for c in ("5min", "40min")]},
                                   references=[{"doi": "10.1000/background", "title": "General background"}])
    finding = deterministic_authoring_plan(packet)["key_findings"][0]
    assert finding["literature_comparison"]["status"] in {"not_searched", "retrieval_unavailable"}


def test_technical_injections_do_not_create_high_biological_support():
    rows = [supported_row(condition=c, **{f"ptm_unadjusted_{g}_sample_ids": [f"{g}{i}" for i in range(3)]
                                        for g in ("control", "treatment")}) for c in ("5min", "40min")]
    manifest = {"samples": [{"sample_id": f"{g}{i}", "biological_unit": "one", "technical_injection": i}
                            for g in ("control", "treatment") for i in range(3)]}
    card = build_feature_observation_cards({"vector_plot_raw_data": rows, "sample_manifest": manifest})[0]
    assert card["narrative_quality_tier"] != "high"


def test_conflict_normalization_does_not_mutate_input_and_cache_tracks_values():
    from copy import deepcopy
    from ptm_shared.vector_plot import normalize_plot_records, project_plot_row, quantitative_cache_key
    rows = [project_plot_row(supported_row(ptm_unadjusted_log2fc=value)) for value in (1, -1)]
    original = deepcopy(rows)
    normalized = normalize_plot_records(rows)
    assert rows == original
    assert normalized[0]["ptm_unadjusted_log2fc"] is None
    assert quantitative_cache_key(rows) == quantitative_cache_key(rows[::-1])
    assert quantitative_cache_key(rows) != quantitative_cache_key(normalized)
