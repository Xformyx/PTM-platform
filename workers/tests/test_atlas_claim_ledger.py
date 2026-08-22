from ptm_shared.atlas_claim_ledger import (
    build_atlas_claim_ledger,
    build_atlas_claim_ledger_from_site_views,
    format_atlas_claim_ledger_for_llm,
)
from report_generation.core.nodes.atlas_report_node import render_atlas_report


def _record(gene, position, values):
    return {
        "gene": gene,
        "position": position,
        "modified_sequence": f"PEP[{position}]TIDE",
        "precursor_charge": 2,
        "trajectory": {
            "timepoints": [
                {"timeLabel": label, "ptmLog2FC": value}
                for label, value in zip(["0min", "5min", "15min", "30min", "60min", "120min"], values)
            ]
        },
    }


def test_claim_ledger_preserves_quality_boundary_and_shared_llm_context():
    ledger = build_atlas_claim_ledger([
        _record("AKT1", "S473", [0, 1.2, 2.0, 1.0, 0.1, 0]),
        _record("STAT3", "Y705", [0, 0.1, 0.9, 1.5, 1.0, 0.2]),
    ], kinase_activity_heatmap={
        "kinase_scores": [{
            "kinase": "AKT1",
            "substrates": [{"gene": "STAT3", "site": "Y705", "cluster": "dominant"}],
            "self_ptm": [{"site": "S473", "relationship": "concordant"}],
        }],
    })
    assert ledger["contract_version"] == "atlas_claim_ledger.v1"
    assert ledger["summary"]["n_site_claims"] == 2
    assert all("direct kinase-site regulation" in claim["interpretation_boundary"] for claim in ledger["site_claims"])
    llm_context = format_atlas_claim_ledger_for_llm(ledger)
    assert "SHARED ATLAS CLAIM LEDGER" in llm_context
    assert "not causal" in llm_context


def test_api_site_views_receive_deterministic_shared_claim_ids():
    ledger = build_atlas_claim_ledger_from_site_views([{
        "site_key": "AKT1_S473",
        "primary_pattern": "early_single_pulse",
        "onset_minutes": 5.0,
        "atlas_eligible": True,
        "context_evidence": {},
    }])
    assert ledger["site_claims"][0]["claim_id"] == "atlas.site.AKT1_S473.early_single_pulse.5.0"


def test_deterministic_atlas_report_uses_shared_claim_ids_and_boundaries():
    ledger = build_atlas_claim_ledger_from_site_views([{
        "site_key": "AKT1_S473",
        "gene": "AKT1",
        "position": "S473",
        "primary_pattern": "early_single_pulse",
        "onset_minutes": 5.0,
        "amplitude": 2.0,
        "atlas_eligible": True,
        "site_form_count": 1,
        "site_aggregation": {"method": "median_form"},
        "context_evidence": {},
    }])
    rendered = render_atlas_report(ledger)
    assert "Temporal Substrate Dynamics Atlas" in rendered
    assert "atlas.site.AKT1_S473.early_single_pulse.5.0" in rendered
    assert "do not establish direct kinase-site regulation or causality" in rendered
