"""Stale-heatmap companions. Scores stay unchanged."""
import copy
import json

from ptm_shared.evidence_record_contract import typed_record
from report_generation.core.companion_evidence import (
    attach_missing_trajectory_evidence,
    atlas_cards,
    cluster_profile_cards,
    dual_track_cards,
    multiform_cards,
    paired_fraction_cards,
    typed_concordance_records,
)
from report_generation.core.quantitative_claims import quantitative_records, value_token_catalog
from report_generation.core.reader_authoring import (
    _kinase_context_cards,
    build_authoring_packet,
    deterministic_authoring_plan,
    render_reader_section_fallback,
    restore_kinase_interval_sentences,
    restore_missing_finding_paragraphs,
    validate_and_repair_sections,
)
from report_generation.core.research_questions import build_question_map, unresolved_question_paragraphs
from report_generation.core.report_artifact_manifest import persist_report_packets
from report_generation.core.research_questions import classify_question_intent


CONDITIONS = ["1min", "5min", "15min", "30min"]


def _vector_rows():
    series = {
        "MAPK1_Y187": [0.0, 1.0, 1.5, 0.5],
        "IRS1_S307": [0.1, 0.9, 1.4, 0.4],
        "IRS1_Y612": [0.2, 1.1, 1.6, 0.6],
    }
    rows = []
    for key, values in series.items():
        gene, position = key.split("_", 1)
        for condition, value in zip(CONDITIONS, values):
            rows.append({
                "gene": gene,
                "position": position,
                "condition": condition,
                "log2fc": value,
                "ptm_unadjusted_log2fc": value,
            })
    return rows


def _stale_heatmap():
    return {
        "conditions": list(CONDITIONS),
        "kinase_scores": [{
            "canonical": "MAPK1",
            "peak_score": 1.23,
            "peak_condition": "15min",
            "weighted_up_sums": {"1min": 1.0, "5min": 2.0},
            "weighted_down_sums": {"1min": 0.0, "5min": -0.5},
            "tmm_top_contributions": [
                {"ptm_key": "MAPK1_Y187"},
                {"ptm_key": "IRS1_S307"},
                {"ptm_key": "IRS1_Y612"},
            ],
        }],
    }


def test_stale_heatmap_gains_trajectory_without_score_change():
    heatmap = _stale_heatmap()
    before = copy.deepcopy(heatmap["kinase_scores"][0])
    attach_missing_trajectory_evidence(heatmap, _vector_rows())
    after = heatmap["kinase_scores"][0]
    assert after["peak_score"] == before["peak_score"]
    assert after["weighted_up_sums"] == before["weighted_up_sums"]
    assert after["weighted_down_sums"] == before["weighted_down_sums"]
    evidence = after["trajectory_evidence"]
    assert evidence["contract_version"] == "kinase_trajectory_evidence.v1"
    assert evidence["attached_after_storage"] is True
    assert "nnls_ratio" in evidence["does_not_modify"]
    assert evidence["support_status"] == "computed"


def _complete_identity_rows():
    rows = []
    series = {
        "MAPK1_Y187": [0.0, 1.0, 1.5, 0.5],
        "IRS1_S307": [0.1, 0.9, 1.4, 0.4],
        "IRS1_Y612": [0.2, 1.1, 1.6, 0.6],
    }
    for key, values in series.items():
        gene, position = key.split("_", 1)
        for condition, value in zip(CONDITIONS, values):
            rows.append({
                "gene": gene,
                "position": position,
                "condition": condition,
                "log2fc": value,
                "ptm_unadjusted_log2fc": value,
                "precursor_id": f"{gene}-{position}-z2",
                "modified_sequence": f"PEPTIDE{position}",
                "precursor_charge": 2,
            })
    return rows


def test_feature_identity_aliases_match_gene_site_heatmap_keys():
    heatmap = _stale_heatmap()
    attach_missing_trajectory_evidence(heatmap, _complete_identity_rows())
    evidence = heatmap["kinase_scores"][0]["trajectory_evidence"]
    assert evidence["support_status"] == "computed"
    assert evidence["n_targets_evaluable"] >= 1


def test_not_evaluable_stored_trajectory_is_recomputed():
    heatmap = _stale_heatmap()
    heatmap["kinase_scores"][0]["trajectory_evidence"] = {
        "contract_version": "kinase_trajectory_evidence.v1",
        "support_status": "not_evaluable",
        "unavailable_reason": "no_evaluable_signed_interval_comparison",
    }
    attach_missing_trajectory_evidence(heatmap, _vector_rows())
    assert heatmap["kinase_scores"][0]["trajectory_evidence"]["support_status"] == "computed"


def test_computed_trajectory_is_not_overwritten():
    heatmap = _stale_heatmap()
    stored = {
        "contract_version": "kinase_trajectory_evidence.v1",
        "support_status": "computed",
        "median_direction_concordance_fraction": 0.42,
        "n_targets_evaluable": 9,
    }
    heatmap["kinase_scores"][0]["trajectory_evidence"] = dict(stored)
    attach_missing_trajectory_evidence(heatmap, _vector_rows())
    assert heatmap["kinase_scores"][0]["trajectory_evidence"]["n_targets_evaluable"] == 9
    assert heatmap["kinase_scores"][0]["trajectory_evidence"]["median_direction_concordance_fraction"] == 0.42


def test_fallback_results_include_kinase_cards():
    packet = build_authoring_packet({
        "kinase_activity_heatmap": _stale_heatmap(),
        "vector_plot_raw_data": _vector_rows(),
    })
    plan = deterministic_authoring_plan(packet)
    # Kinase context is intentionally supporting evidence, not a named
    # measured-feature finding that could be mistaken for direct attribution.
    assert not any(finding.get("category") == "kinase_context" for finding in plan["key_findings"])
    assert any(context.get("category") == "kinase_context" for context in plan["supporting_contexts"])
    results = render_reader_section_fallback("results", packet)
    assert "direction concordance fraction" in results.lower()
    assert "supplementary figure 2" in results.lower()


def test_identical_family_scores_emit_one_card():
    heatmap = _stale_heatmap()
    row = dict(heatmap["kinase_scores"][0])
    heatmap["kinase_scores"] = [
        {**row, "canonical": "CDK"},
        {**row, "canonical": "MAPK"},
        {**row, "canonical": "MAPK14"},
    ]
    attach_missing_trajectory_evidence(heatmap, _vector_rows())
    cards = _kinase_context_cards({"kinase_activity_heatmap": heatmap})
    candidates = [card for card in cards if str(card.get("card_id")).startswith("kinase.") and card.get("card_id") != "kinase.context_availability"]
    assert len(candidates) == 1
    assert "CDK" in candidates[0]["reader_summary"]
    assert "MAPK" in candidates[0]["reader_summary"]


def test_truncated_live_prose_regains_interval_numbers_after_validation():
    """Replay the 2026-09-14 11:33 report: family names stayed, 0.80 did not."""
    packet = build_authoring_packet({
        "kinase_activity_heatmap": _stale_heatmap(),
        "vector_plot_raw_data": _vector_rows(),
    })
    truncated = (
        "UBE3C modified-precursor feature with candidate residue annotation T121 (PF-02033E16). "
        "Independent and protein-adjusted PTM contrasts were higher while linked protein remained near the reference level.\n\n"
        "A stored CDK family ranking provided kinase-family candidate context. "
        "Independent footprint diagnostics were not evaluable on this stored heatmap. "
        "The supplied evidence supports descriptive observations and candidate context; "
        "it does not establish direct regulation. Interval concordance is not a catalytic rate."
    )
    repaired, _ = validate_and_repair_sections({"results": truncated}, packet)
    recovered, _ = restore_missing_finding_paragraphs("results", repaired["results"], packet)
    assert "direction concordance fraction" in recovered.lower()


def test_dropped_interval_numbers_are_restored():
    packet = build_authoring_packet({
        "kinase_activity_heatmap": _stale_heatmap(),
        "vector_plot_raw_data": _vector_rows(),
    })
    restored, audit = restore_kinase_interval_sentences(
        "results",
        "A stored CDK family ranking provided kinase-family candidate context.",
        packet,
    )
    assert audit
    assert "direction concordance fraction" in restored.lower()


def test_cluster_question_does_not_emit_ssb_unresolved():
    mapping = {
        "questions": [{
            "feature_ids": [],
            "evidence_ids": ["cluster.profile.1"],
            "entities": ["SSB"],
            "intent": "cluster_concordance",
            "answerability": "observational_only",
        }],
    }
    assert unresolved_question_paragraphs(mapping) == []


def test_cluster_token_is_not_an_entity():
    mapping = build_question_map(
        [{"text": "Does the observed Temporal Profile Cluster TW-05 change?", "origin": "user"}],
        [{"category": "temporal_profile", "evidence_ids": ["cluster.profile.1"], "feature_identity": {}}],
    )
    assert "TW" not in mapping["questions"][0]["entities"]


def test_kinase_cards_emit_without_computed_footprint():
    heatmap = _stale_heatmap()
    attach_missing_trajectory_evidence(heatmap, _vector_rows())
    cards = _kinase_context_cards({"kinase_activity_heatmap": heatmap})
    ids = [card["card_id"] for card in cards]
    assert "kinase.context_availability" in ids
    assert "kinase.1" in ids
    candidate = next(card for card in cards if card["card_id"] == "kinase.1")
    assert candidate["trajectory_evidence"]["support_status"] == "computed"
    assert any(record["record_type"] == "kinase_trajectory" for record in candidate["value_records"])


def test_p2_cards_and_typed_dispatch():
    observations = [
        {"feature_identity": {"gene": "IRS1", "reader_feature_id": "PF-AAAAAAAA"}},
        {"feature_identity": {"gene": "IRS1", "reader_feature_id": "PF-BBBBBBBB"}},
    ]
    state = {
        "kinase_activity_heatmap": {
            "kinase_scores": [{
                "canonical": "AKT1",
                "dual_track_evidence": {
                    "classification": "direction_discordant",
                    "correlation": 0.12,
                },
            }],
        },
        "vector_plot_raw_data": [{
            "gene": "IRS1",
            "condition": "5min",
            "occupancy_logit_delta": 0.4,
            "pair_quality_tier": "O2",
            "occupancy_calibration_type": "none",
        }],
        "atlas_claim_ledger": {
            "site_claims": [{
                "claim_id": "atlas.site.IRS1_Y612.early.1",
                "claim_type": "observed_site_temporal_pattern",
                "site": {"gene": "IRS1", "site_key": "IRS1_Y612", "primary_pattern": "early_rise"},
                "interpretation_boundary": "Observed trajectory shape only.",
            }],
        },
        "comovement_analysis": {
            "clusters": [{
                "cluster_id": "cluster-a",
                "pattern": "early_rise",
                "member_details": [{"gene": "IRS1", "site": "Y612"}],
            }],
        },
    }
    cards = (
        dual_track_cards(state)
        + paired_fraction_cards(state)
        + multiform_cards(observations)
        + atlas_cards(state)
        + cluster_profile_cards(state)
    )
    types = {record["record_type"] for card in cards for record in card.get("value_records") or []}
    assert types >= {
        "dual_track",
        "paired_peptide_fraction",
        "multiform_comparison",
        "atlas_observation",
        "cluster_profile",
    }
    packet = {"reader_cards": cards, "figure_cards": []}
    catalog = value_token_catalog(packet)
    assert catalog
    assert classify_question_intent("Did the paired-peptide fraction change?") == "paired_peptide"
    assert classify_question_intent("Which multiform comparisons are available?") == "multiform"


def test_typed_concordance_binds_integer_counts():
    records = typed_concordance_records([{
        "cluster_id": "cluster-a",
        "from_window": "1min",
        "to_window": "5min",
        "denominator": 10,
        "gain": 2,
        "loss": 1,
        "retained": 6,
        "source": "temporal_ptm_protein_analysis.dynamic_transition_per_wave",
    }])
    assert {row["metric_id"] for row in records} == {"gain_count", "loss_count", "retained_count"}
    assert all(row["denominator"] == 10 for row in records)


def test_utilization_is_persisted_from_authoring_packet(tmp_path):
    persist_report_packets({
        "authoring_packet": {
            "report_evidence_utilization": {"schema_version": "report_evidence_utilization.v1", "by_evidence_type": {}},
        },
    }, tmp_path)
    path = tmp_path / "report_report_evidence_utilization.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "report_evidence_utilization.v1"


def test_authoring_packet_keeps_kinase_cards_on_stale_heatmap():
    packet = build_authoring_packet({
        "kinase_activity_heatmap": _stale_heatmap(),
        "vector_plot_raw_data": _vector_rows(),
    })
    ids = [card["card_id"] for card in packet["reader_cards"]]
    assert any(card_id.startswith("kinase.") and card_id != "kinase.context_availability" for card_id in ids)
    assert packet["report_evidence_utilization"]["schema_version"] == "report_evidence_utilization.v1"


def test_new_typed_record_is_catalogued():
    record = typed_record(
        record_type="dual_track",
        entity_id="AKT1",
        metric_id="track_correlation",
        value=0.12,
        unit="pearson_r",
        estimator="tmm_dual_track_evidence.v2",
        support_status="computed",
        evidence_id="kinase.dual_track.AKT1",
    )
    records = quantitative_records({
        "value_records": [record],
        "reader_summary": "AKT1 had a dual-track comparison.",
    })
    assert records[0]["record_type"] == "dual_track"
