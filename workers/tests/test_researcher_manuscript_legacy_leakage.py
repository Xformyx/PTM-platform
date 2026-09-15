from report_generation.core.reader_authoring import (
    READER_SAFE_LIMITATIONS,
    adapt_discovery_candidates,
    audit_reader_technical_leakage,
    build_authoring_packet,
    render_reader_section_fallback,
)
from report_generation.core.report_release import resolve_report_release


def _synthetic_observation_only_state():
    return {
        "experimental_context": {
            "cell_type": "generic cultured cells",
            "treatment": "soluble ligand",
            "timepoints": ["1min", "15min", "60min"],
        },
        "vector_plot_raw_data": [
            {
                "gene": "GENEA",
                "position": "S10",
                "condition": "1min",
                "Precursor.Id": "PRECURSOR-A",
                "Modified.Sequence": "AA(UniMod:21)SEQA",
                "Precursor.Charge": 2,
                "ptm_unadjusted_log2fc": 0.4,
                "ptm_protein_adjusted_log2fc": 0.3,
                "protein_log2fc": 0.1,
            },
            {
                "gene": "GENEA",
                "position": "S10",
                "condition": "15min",
                "Precursor.Id": "PRECURSOR-A",
                "Modified.Sequence": "AA(UniMod:21)SEQA",
                "Precursor.Charge": 2,
                "ptm_unadjusted_log2fc": 0.2,
                "ptm_protein_adjusted_log2fc": 0.1,
                "protein_log2fc": 0.1,
            },
        ],
        "temporal_report_evidence_packet": {
            "section_plan": {"observation_only_claim_ceiling": True},
            "records": [
                {
                    "evidence_id": "DATA-TEMPORAL-SUMMARY",
                    "reader_summary": "status=not_evaluable LOTO n_eff=0 TW-01 pair-window denominator",
                    "text": "status=not_evaluable LOTO n_eff=0 TW-01",
                }
            ],
        },
        "biological_synthesis_packet": {
            "candidate_discovery_packet": {
                "contract_version": "synthetic_no_eligible.v1",
                "selected_cards": [],
                "selection_summary": {"candidate_capacity": 24, "selected_by_quota": {}},
            }
        },
        "kinase_activity_heatmap": {"kinase_scores": []},
        "report_config": {
            "report_audience": "researcher_manuscript",
            "reader_authoring_mode": "shadow",
        },
    }


def test_researcher_fallback_uses_reader_safe_limitations_not_raw_diagnostics():
    packet = build_authoring_packet(_synthetic_observation_only_state())
    results = render_reader_section_fallback("results", packet)
    discussion = render_reader_section_fallback("discussion", packet)
    body = results + "\n\n" + discussion
    leakage = audit_reader_technical_leakage(body, audience="researcher_manuscript")
    assert leakage["status"] == "clean"
    assert READER_SAFE_LIMITATIONS["candidate_family_unavailable"] in " ".join(
        card["reader_summary"] for card in packet["reader_cards"]
    )
    assert "P5" not in body
    assert "TW-01" not in body
    assert "LOTO" not in body
    assert "candidate capacity" not in body.lower()
    assert "not evaluable" not in body.lower()


def test_technical_sidecar_retains_diagnostic_records():
    cards, audit = adapt_discovery_candidates(
        {
            "candidate_discovery_packet": {
                "selection_summary": {"candidate_capacity": 24},
                "selected_cards": [],
            }
        }
    )
    assert cards == []
    assert audit["status"] in {"not_supplied", "no_eligible_candidates"}
    leakage = audit_reader_technical_leakage(
        "P5 candidate capacity=24; P0–P3 readiness/no-call; LOTO; TW-01",
        audience="technical_audit",
    )
    assert leakage["status"] == "not_applicable"


def test_researcher_leak_blocks_final_release():
    leakage = audit_reader_technical_leakage(
        "P5 candidate capacity=12 and LOTO were reported.",
        audience="researcher_manuscript",
    )
    assert leakage["status"] == "leak_detected"
    release = resolve_report_release(
        reader_authoring_shadow=True,
        output_correctness={
            "status": "blocked_for_review",
            "reason_codes": leakage["reason_codes"],
            "technical_leakage_audit": leakage,
        },
        artifact_manifest={"status": "validated", "report_eligible": True, "artifacts": [{"role": "md", "exists": True}]},
        report_mode_contract={
            "report_audience": "researcher_manuscript",
            "effective_reader_mode": "shadow",
            "valid": True,
            "reason_codes": [],
            "contract_version": "report_audience_mode.v1",
        },
        writer_effective_mode="shadow",
        graph_effective_mode="shadow",
        phase="pre_export",
    )
    assert "researcher_technical_leakage" in release["reason_codes"]
    assert release["publish_as_final"] is False
