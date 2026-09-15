from ptm_shared.report_mode import resolve_report_mode_contract
from report_generation.core.graph import _compose_observation_only_report_sections, format_citations
from report_generation.core.report_release import resolve_report_release


RESEARCHER_CONFIG = {
    "report_audience": "researcher_manuscript",
    "reader_authoring_mode": "shadow",
    "technical_audit_delivery": "separate_sidecar",
}


def _researcher_state(**extra):
    state = {
        "report_config": dict(RESEARCHER_CONFIG),
        "report_mode_contract": dict(resolve_report_mode_contract(RESEARCHER_CONFIG)),
        "sections": {
            "title": "Generic time-course observations",
            "abstract": "The study asks whether measured PTM abundance changes with linked protein across the sampled intervals.",
            "introduction": "The recorded experiment compares modified precursors and linked proteins.",
            "results": "Measured precursors changed at the sampled intervals without assigning a kinase.",
            "discussion": "The observations remain descriptive and require a paired follow-up measurement.",
            "methods": "Relative contrasts were retained on their original axes.",
            "conclusion": "The next experiment should repeat paired precursor and protein measurements.",
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [{
            "title": "Generic contextual article",
            "authors": "Evidence Author",
            "journal": "Evidence Journal",
            "year": "2025",
            "pmid": "11111111",
        }],
        "temporal_report_evidence_packet": {
            "section_plan": {"observation_only_claim_ceiling": True},
        },
        "biological_synthesis_packet": {
            "candidate_discovery_packet": {
                "selection_summary": {"candidate_capacity": 12, "selected_by_quota": {"A": 0}},
            }
        },
        "writer_effective_mode": "shadow",
    }
    state.update(extra)
    return state


def test_researcher_shadow_contract_is_shared_across_writer_graph_state():
    contract = resolve_report_mode_contract(RESEARCHER_CONFIG)
    assert contract["valid"] is True
    assert contract["effective_reader_mode"] == "shadow"
    result = format_citations(_researcher_state())
    assert result["report_mode_contract"]["effective_reader_mode"] == "shadow"
    assert result["graph_effective_mode"] == "shadow"
    assert "P5 candidate capacity" not in result["final_report"]
    assert "Kinase Footprint Diagnostics" not in result["final_report"]
    assert "Quantitative and provenance framework" not in result["final_report"]


def test_researcher_observation_only_does_not_invoke_legacy_composer(monkeypatch):
    called = {"value": False}

    def forbidden(*args, **kwargs):
        called["value"] = True
        return _compose_observation_only_report_sections(*args, **kwargs)

    monkeypatch.setattr(
        "report_generation.core.graph._compose_observation_only_report_sections",
        forbidden,
    )
    result = format_citations(_researcher_state())
    assert called["value"] is False
    assert "P0–P3 readiness" not in result["final_report"]
    assert "candidate capacity" not in result["final_report"].lower()


def test_researcher_missing_mode_blocks_before_legacy_assembly():
    contract = resolve_report_mode_contract({"report_audience": "researcher_manuscript"})
    assert contract["valid"] is False
    assert "audience_mode_mismatch" in contract["reason_codes"]
    result = format_citations({
        "report_config": {"report_audience": "researcher_manuscript"},
        "sections": {"results": "P5 candidate capacity=1600"},
        "network_analysis": {},
        "collected_references": [],
    })
    assert "configuration mismatch" in result["final_report"].lower()
    assert "P5 candidate capacity" not in result["final_report"]
    assert result["citation_data"]["completion_status"] == "blocked_audience_mode_mismatch"
    assert result["graph_effective_mode"] == "blocked"


def test_technical_legacy_output_is_labelled_and_not_researcher_final():
    config = {
        "report_audience": "technical_audit",
        "reader_authoring_mode": "legacy",
        "technical_audit_delivery": "embedded_technical_report",
    }
    result = format_citations({
        "report_config": config,
        "report_mode_contract": dict(resolve_report_mode_contract(config)),
        "report_title": "PTM Comprehensive Analysis Report",
        "sections": {"title": "PTM Comprehensive Analysis Report", "results": "Observed trajectories were summarized."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [{
            "title": "Technical methods article",
            "authors": "Methods Author",
            "journal": "Methods Journal",
            "year": "2024",
            "pmid": "22222222",
        }],
        "temporal_report_evidence_packet": {"section_plan": {"observation_only_claim_ceiling": False}},
        "biological_synthesis_packet": {},
    })
    assert "Technical Audit" in result["final_report"]
    release = resolve_report_release(
        reader_authoring_shadow=False,
        output_correctness={"status": "release_candidate"},
        report_mode_contract=resolve_report_mode_contract(config),
    )
    assert release["status"] == "technical_audit_ready"
    assert release["publish_as_final"] is False
    assert release["report_audience"] == "technical_audit"


def test_writer_graph_mode_mismatch_blocks_final():
    contract = dict(resolve_report_mode_contract(RESEARCHER_CONFIG))
    release = resolve_report_release(
        reader_authoring_shadow=True,
        output_correctness={"status": "release_candidate"},
        artifact_manifest={"status": "validated", "report_eligible": True, "artifacts": [{"role": "md", "exists": True}], "render_status": "recorded"},
        report_mode_contract=contract,
        writer_effective_mode="legacy",
        graph_effective_mode="shadow",
        phase="pre_export",
    )
    assert "mode_contract_inconsistent" in release["reason_codes"]
    assert release["status"] == "blocked_final"
    assert release["publish_as_final"] is False
