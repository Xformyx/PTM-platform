import sys
from pathlib import Path

from ptm_shared.kinase_evidence_ledger import (
    DIRECT_NO_CALL_TIER,
    TEMPORAL_ASSOCIATION_TIER,
    attach_temporal_context,
    build_feature_provenance_ledger,
    compact_summary,
)
from ptm_shared.enrichment_free_temporal_sidecar import summarize_temporal_ptm_protein_analysis


def _rows():
    return [
        {
            "gene": "MAPK1", "position": "Y185", "condition": "1min", "log2fc": 0.8,
            "protein_group": "P28482;Q9TEST", "modified_sequence": "AA(Phospho)BB(Phospho)CC",
            "precursor_charge": "2", "precursor_id": "precursor-a",
        },
        {
            "gene": "MAPK1", "position": "Y185", "condition": "5min", "log2fc": None,
            "protein_group": "P28482;Q9TEST", "modified_sequence": "AA(Phospho)BB(Phospho)CC",
            "precursor_charge": "2", "precursor_id": "precursor-a",
        },
        {
            "gene": "GAB2", "position": "S498", "condition": "1min", "log2fc": 0.5,
            "protein_group": "Q9Z0W4", "modified_sequence": "AA(Phospho)BBCC",
            "precursor_charge": "2", "precursor_id": "precursor-b",
            "localization_probability": "0.99",
        },
        {
            "gene": "GAB2", "position": "S498", "condition": "5min", "log2fc": 0.4,
            "protein_group": "Q9Z0W4", "modified_sequence": "AA(Phospho)BBCC",
            "precursor_charge": "2", "precursor_id": "precursor-b",
            "localization_probability": "0.99",
        },
    ]


def test_ledger_preserves_masks_without_assigning_a_primary_f1_f8_reason():
    ledger = build_feature_provenance_ledger(_rows(), ["1min", "5min"])
    first = next(row for row in ledger["feature_records"] if row["nominal_aggregate_key"] == "MAPK1_Y185")
    assert first["unmatched_reason_masks"]["F1_protein_accession_or_group_ambiguous"] == "flagged"
    assert first["unmatched_reason_masks"]["F2_multi_phosphorylated_or_localization_ambiguous"] == "flagged_multi_phosphorylated"
    assert first["unmatched_reason_masks"]["F5_quantitative_time_data_insufficient"] == "flagged"
    assert first["unmatched_reason_primary"] == "not_assigned_without_approved_f1_f8_priority_policy"
    assert first["direct_kinase_attribution"]["evidence_tier"] == DIRECT_NO_CALL_TIER


def test_wave_context_does_not_promote_direct_kinase_tier_and_compact_summary_hides_identity():
    ledger = build_feature_provenance_ledger(_rows(), ["1min", "5min"])
    enriched = attach_temporal_context(
        ledger,
        {"waves": [{"members": ["GAB2_S498"]}]},
        {"GAB2_S498": {"candidate": "context only"}},
    )
    gab2 = next(row for row in enriched["feature_records"] if row["nominal_aggregate_key"] == "GAB2_S498")
    assert gab2["temporal_evidence"]["evidence_tier"] == TEMPORAL_ASSOCIATION_TIER
    assert gab2["direct_kinase_attribution"]["evidence_tier"] == DIRECT_NO_CALL_TIER
    summary = compact_summary(enriched)
    assert "feature_records" not in summary
    assert "modified_sequence" in summary["excluded_fields"]
    assert summary["feature_record_count"] == 2


def test_compact_sidecar_summary_releases_ledger_counts_but_not_feature_identity():
    ledger = attach_temporal_context(
        build_feature_provenance_ledger(_rows(), ["1min", "5min"]),
        {"waves": [{"members": ["GAB2_S498"]}]},
    )
    summary = summarize_temporal_ptm_protein_analysis({
        "schema_version": "test",
        "provenance": {},
        "kinase_feature_evidence_ledger": ledger,
        "kinase_feature_evidence_ledger_summary": compact_summary(ledger),
    })
    released = summary["kinase_feature_evidence_ledger_summary"]
    assert released["release_scope"] == "aggregate_only_report_rag_safe_summary"
    assert "feature_records" not in released
    assert "Modified.Sequence" not in str(released)


def test_report_packet_receives_aggregate_no_call_readiness_only():
    workers_path = Path(__file__).resolve().parents[2] / "workers"
    if str(workers_path) not in sys.path:
        sys.path.insert(0, str(workers_path))
    from report_generation.core.dynamic_prompt_generator import build_temporal_evidence_packet

    ledger = attach_temporal_context(
        build_feature_provenance_ledger(_rows(), ["1min", "5min"]),
        {"waves": [{"members": ["GAB2_S498"]}]},
    )
    compact = compact_summary(ledger)
    packet = build_temporal_evidence_packet({
        "protein_trajectory_count": 0,
        "ptm_protein_pair_count": 0,
        "cross_layer_edge_count": 0,
        "temporally_eligible_edge_count": 0,
        "mechanism_chain_count": 0,
        "evidence_supported_mechanism_count": 0,
        "kinase_feature_evidence_ledger_summary": compact,
    })
    readiness = next(row for row in packet["records"] if row["evidence_id"] == "DATA-KINASE-ATTRIBUTION-READINESS")
    assert readiness["claim_level"] == "L1_provenance_no_call"
    assert "direct kinase attribution status" in readiness["text"]
    assert "MAPK1" not in readiness["text"]
    assert "modified_sequence" not in readiness["text"]


def test_empty_nonproduction_sidecar_does_not_emit_empty_ledger_summary():
    from ptm_shared.enrichment_free_temporal_sidecar import build_v2_sidecar

    # The early disabled branch avoids computation requiring an output dataset;
    # the ledger behavior is independent of biological analysis content.
    sidecar = build_v2_sidecar(
        output_dir=Path("/tmp"),
        ptm_type="phosphorylation",
        site_observations=[],
        enable_dynamic_transition=False,
        wave_contract={},
    )
    assert sidecar["kinase_feature_evidence_ledger"] == {}
    assert sidecar["kinase_feature_evidence_ledger_summary"] == {}
