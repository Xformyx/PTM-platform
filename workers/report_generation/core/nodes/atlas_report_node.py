"""Render a deterministic, evidence-first Temporal Substrate Dynamics Atlas."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def _text(value: Any) -> str:
    if value is None or value == "":
        return "not available"
    return str(value)


def render_atlas_report(ledger: Mapping[str, Any], *, order_id: int | None = None) -> str:
    """Render every shared claim without adding unsourced biological assertions."""
    summary = ledger.get("summary") or {}
    lines = [
        "# Temporal Substrate Dynamics Atlas",
        "",
        f"*Shared claim ledger contract: `{ledger.get('contract_version', 'unknown')}`*",
        "",
        "## Interpretation Boundary",
        "",
        "This Atlas records observed PTM trajectory shapes, quality provenance, co-movement membership transitions, and persisted context annotations. "
        "Co-movement, candidate kinase context, self-PTM candidates, and later non-PTM changes are observational evidence only; they do not establish direct kinase-site regulation or causality.",
        "",
        "## Coverage",
        "",
        f"- Site claims: {summary.get('n_site_claims', 0)}",
        f"- Atlas-eligible site claims: {summary.get('n_atlas_eligible_site_claims', 0)}",
        f"- Observed transition claims: {summary.get('n_transition_claims', 0)}",
        "",
        "## Quality-gated Site Dynamics",
        "",
    ]
    claims = ledger.get("site_claims") or []
    eligible = [claim for claim in claims if (claim.get("site") or {}).get("atlas_eligible")]
    ineligible = [claim for claim in claims if not (claim.get("site") or {}).get("atlas_eligible")]
    for claim in eligible:
        site = claim.get("site") or {}
        lines.extend([
            f"### {site.get('gene', 'unknown')} {site.get('position', '')}",
            "",
            f"- **Claim ID:** `{claim.get('claim_id')}`",
            f"- **Observed pattern:** {_text(site.get('primary_pattern'))}"
            + (f"; candidate shape: {_text(site.get('candidate_pattern'))}" if site.get("candidate_pattern") else ""),
            f"- **Timing:** onset={_text(site.get('onset_minutes'))} min; peak={_text(site.get('peak_minutes'))} min; amplitude={_text(site.get('amplitude'))}; signed AUC={_text(site.get('auc_signed'))}",
            f"- **Form provenance:** {site.get('site_form_count', 0)} form(s); explicit aggregation={_text((site.get('site_aggregation') or {}).get('method'))}",
            f"- **Quality:** LOTO stability={_text(site.get('loto_pattern_stability'))}; threshold-sensitive={_text(site.get('threshold_sensitivity_flag'))}; q-value coverage={_text(site.get('qvalue_coverage'))}; observed={_text(site.get('observed_timepoints'))}; missing={_text(site.get('missing_timepoints'))}",
        ])
        context = claim.get("context_evidence") or {}
        if context.get("self_ptm_candidates"):
            lines.append("- **Self-PTM candidates:** " + "; ".join(
                f"{_text(item.get('kinase'))} {_text(item.get('site'))} ({_text(item.get('relationship'))})"
                for item in context["self_ptm_candidates"]
            ))
        if context.get("kinase_context"):
            lines.append("- **Kinase context candidates:** " + "; ".join(
                f"{_text(item.get('kinase'))} [{_text(item.get('evidence_type'))}]"
                for item in context["kinase_context"]
            ))
        nuclear = context.get("nuclear_context") or {}
        if nuclear.get("nucleus_annotated"):
            lines.append("- **Nuclear context:** cellular-component annotation includes nucleus.")
        if context.get("non_ptm_follow_through"):
            lines.append("- **Non-PTM follow-through context:** " + "; ".join(
                f"{_text(item.get('gene'))} [{_text(item.get('evidence_type'))}]"
                for item in context["non_ptm_follow_through"]
            ))
        lines.extend([f"- **Boundary:** {claim.get('interpretation_boundary')}", ""])

    if ineligible:
        lines.extend(["## Trajectories Excluded from Narrative", ""])
        for claim in ineligible:
            site = claim.get("site") or {}
            lines.append(
                f"- {site.get('gene', 'unknown')} {site.get('position', '')}: "
                f"{', '.join(site.get('atlas_eligibility_reasons') or ['quality gate not passed'])}"
            )
        lines.append("")

    lines.extend(["## Time-varying Co-movement Transitions", ""])
    transition_claims = ledger.get("transition_claims") or []
    if not transition_claims:
        lines.append("No quality-gated observed transition was available for the largest label-consistent cohort.")
    for claim in transition_claims:
        transition = claim.get("transition") or {}
        lines.extend([
            f"### {_text(transition.get('transition_type'))}: {_text(transition.get('from_window'))} → {_text(transition.get('to_window'))}",
            "",
            f"- **Claim ID:** `{claim.get('claim_id')}`",
            f"- **Observed members:** {', '.join(transition.get('members') or transition.get('site_keys') or [])}",
            f"- **Boundary:** {claim.get('interpretation_boundary')}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def run_atlas_report_generation(state: dict) -> dict:
    from ptm_shared.temporal_contract import resolve_temporal_contract
    if not resolve_temporal_contract(state).run_atlas_report:
        return {"atlas_report_path": "", "atlas_report_markdown": ""}
    ledger = state.get("atlas_claim_ledger") or {}
    output_dir = state.get("output_dir")
    if not output_dir:
        return {"atlas_report_path": "", "atlas_report_markdown": ""}
    rendered = render_atlas_report(ledger, order_id=state.get("order_id"))
    path = Path(output_dir) / "temporal_substrate_dynamics_atlas.md"
    path.write_text(rendered, encoding="utf-8")
    return {"atlas_report_path": str(path), "atlas_report_markdown": rendered}
