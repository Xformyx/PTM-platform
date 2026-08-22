"""Shared, non-causal temporal evidence ledger for Atlas and integrated reports."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .atlas_context import build_atlas_context_evidence
from .site_form_provenance import aggregate_site_form_trajectories, form_identity
from .substrate_temporal_dynamics import SiteKineticConfig, compute_site_kinetic_profile
from .time_varying_comovement import compute_time_varying_comovement


CONTRACT_VERSION = "atlas_claim_ledger.v1"


def _site_key(record: Mapping[str, Any]) -> str:
    return f"{record.get('gene') or record.get('Gene.Name') or ''}_{record.get('position') or record.get('PTM_Position') or ''}"


def _forms_for_records(records: Iterable[Mapping[str, Any]]) -> list[dict]:
    by_key: Dict[str, dict] = {}
    for record in records:
        forms = record.get("site_form_trajectories") or [{
            **form_identity(record),
            "trajectory": record.get("trajectory") or {},
        }]
        for form in forms:
            key = str(form.get("site_form_key") or form_identity(record)["site_form_key"])
            entry = by_key.setdefault(key, dict(form))
            if entry is not form:
                current = entry.setdefault("trajectory", {"timepoints": []})
                current.setdefault("timepoints", []).extend(
                    (form.get("trajectory") or {}).get("timepoints") or []
                )
    return list(by_key.values())


def _claim_id(site_key: str, profile: Any) -> str:
    onset = "na" if profile.onset_minutes is None else str(profile.onset_minutes)
    return f"atlas.site.{site_key}.{profile.primary_pattern}.{onset}"


def claim_id_from_site_view(site: Mapping[str, Any]) -> str:
    """Return the deterministic claim ID shared by API and report consumers."""
    onset = "na" if site.get("onset_minutes") is None else str(site.get("onset_minutes"))
    return f"atlas.site.{site.get('site_key', 'unknown')}.{site.get('primary_pattern', 'unresolved')}.{onset}"


def build_atlas_claim_ledger_from_site_views(
    site_views: Iterable[Mapping[str, Any]],
    *,
    transition_map: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Build canonical observational claims from already-computed Atlas site views."""
    claims = []
    for view in site_views or []:
        claims.append({
            "claim_id": claim_id_from_site_view(view),
            "claim_type": "observed_site_temporal_pattern",
            "site": dict(view),
            "context_evidence": dict(view.get("context_evidence") or {}),
            "interpretation_boundary": (
                "Observed trajectory shape and context alignment only; this claim does not establish direct kinase-site regulation or causality."
            ),
        })
    transition_map = dict(transition_map or {
        "status": "unavailable", "reason": "transition_not_computed"
    })
    transition_claims = []
    for index, transition in enumerate(transition_map.get("transitions") or [], 1):
        transition_claims.append({
            "claim_id": f"atlas.transition.{transition.get('transition_id') or index}",
            "claim_type": "observed_comovement_transition",
            "transition": dict(transition),
            "interpretation_boundary": "Observed membership transition, not kinase switching or causal signal propagation.",
        })
    return {
        "contract_version": CONTRACT_VERSION,
        "site_claims": claims,
        "transition_claims": transition_claims,
        "transition_map": transition_map,
        "summary": {
            "n_site_claims": len(claims),
            "n_atlas_eligible_site_claims": sum(1 for claim in claims if claim["site"].get("atlas_eligible")),
            "n_transition_claims": len(transition_claims),
        },
    }


def build_atlas_claim_ledger(
    enriched_ptms: Iterable[Mapping[str, Any]],
    *,
    kinase_activity_heatmap: Optional[Mapping[str, Any]] = None,
    signal_propagation_data: Optional[Mapping[str, Any]] = None,
    substrate_go_localization: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Build quality-gated observed site and transition claims from enriched output.

    The ledger intentionally contains no causal claims.  It is safe to hand to
    both an Atlas renderer and the integrated report writer.
    """
    grouped: Dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for ptm in enriched_ptms or []:
        key = _site_key(ptm)
        if key != "_":
            grouped[key].append(ptm)

    config = SiteKineticConfig(run_loto=True, run_threshold_sensitivity=True)
    site_views: list[dict] = []
    profiles: Dict[str, Any] = {}
    trajectories_by_labels: Dict[tuple[str, ...], Dict[str, list]] = defaultdict(dict)

    for site_key, records in grouped.items():
        forms = _forms_for_records(records)
        aggregation = aggregate_site_form_trajectories(forms)
        timepoints = aggregation.get("timepoints") or []
        labels = [str(tp.get("timeLabel") or "") for tp in timepoints]
        values = [tp.get("ptmLog2FC") for tp in timepoints]
        if len(labels) < 3 or all(value is None for value in values):
            continue
        try:
            profile = compute_site_kinetic_profile(labels, values, config=config)
        except Exception:
            continue
        representative = records[0]
        view = {
            "site_key": site_key,
            "gene": representative.get("gene") or representative.get("Gene.Name") or "",
            "position": representative.get("position") or representative.get("PTM_Position") or "",
            "site_form_count": len(forms),
            "site_aggregation": aggregation,
            "timepoint_labels": labels,
            "values": values,
            "primary_pattern": profile.primary_pattern,
            "candidate_pattern": profile.candidate_pattern,
            "pattern_modifiers": profile.pattern_modifiers,
            "atlas_eligible": profile.atlas_eligible,
            "atlas_eligibility_reasons": profile.atlas_eligibility_reasons,
            "quality_gate_passed": profile.quality_gate_passed,
            "loto_pattern_stability": profile.loto_pattern_stability,
            "threshold_sensitivity_flag": profile.threshold_sensitivity_flag,
            "qvalue_coverage": profile.qvalue_coverage,
            "observed_timepoints": profile.observed_timepoints_count,
            "missing_timepoints": profile.missing_timepoints_count,
            "onset_minutes": profile.onset_minutes,
            "peak_minutes": profile.peak_minutes,
            "amplitude": profile.amplitude,
            "auc_signed": profile.auc_signed,
            "return_to_baseline": profile.return_to_baseline,
        }
        site_views.append(view)
        profiles[site_key] = profile
        trajectories_by_labels[tuple(labels)][site_key] = values

    context_by_site = build_atlas_context_evidence(
        site_views,
        kinase_activity_heatmap=kinase_activity_heatmap,
        signal_propagation_data=signal_propagation_data,
        substrate_go_localization=substrate_go_localization,
    )
    for view in site_views:
        view["context_evidence"] = context_by_site.get(view["site_key"], {})

    transition_map: dict = {"status": "unavailable", "reason": "no_label_consistent_cohort"}
    if trajectories_by_labels:
        labels, trajectories = max(trajectories_by_labels.items(), key=lambda item: len(item[1]))
        if len(trajectories) >= 2:
            transition_map = compute_time_varying_comovement(
                list(labels), trajectories,
                profiles={key: profiles[key] for key in trajectories},
            ).to_dict()
            transition_map["status"] = "ok"
            transition_map["cohort_timepoint_labels"] = list(labels)
            transition_map["observed_transition_semantics"] = "membership transitions, not causal arrows"

    return build_atlas_claim_ledger_from_site_views(site_views, transition_map=transition_map)


def format_atlas_claim_ledger_for_llm(ledger: Mapping[str, Any], *, max_site_claims: int = 20) -> str:
    """Produce bounded, evidence-first context for Results/RQ/Discussion writers."""
    if not ledger or not ledger.get("site_claims"):
        return ""
    eligible = [claim for claim in ledger["site_claims"] if claim["site"].get("atlas_eligible")]
    ranked = sorted(eligible, key=lambda claim: abs(float(claim["site"].get("amplitude") or 0)), reverse=True)
    lines = [
        "=== SHARED ATLAS CLAIM LEDGER (OBSERVATIONAL EVIDENCE ONLY) ===",
        "Use only the claim details below for detailed temporal statements. Do not display claim IDs in prose.",
        "These claims are not causal: do not turn co-movement, TMM, self-PTM candidates, or later non-PTM changes into direct regulation or causality.",
    ]
    for claim in ranked[:max_site_claims]:
        site = claim["site"]
        lines.append(
            f"[{claim['claim_id']}] {site['gene']} {site['position']} | {site['primary_pattern']} "
            f"| onset={site['onset_minutes']} min | peak={site['peak_minutes']} min | amp={site['amplitude']:+.3f} "
            f"| forms={site['site_form_count']} | LOTO={site['loto_pattern_stability']} "
            f"| q-coverage={site['qvalue_coverage']}"
        )
        context = claim.get("context_evidence") or {}
        for self_ptm in context.get("self_ptm_candidates") or []:
            lines.append(f"  self-PTM candidate: {self_ptm.get('kinase')} {self_ptm.get('site')} ({self_ptm.get('relationship')})")
        for kinase in context.get("kinase_context") or []:
            lines.append(f"  kinase-context candidate: {kinase.get('kinase')} ({kinase.get('evidence_type')})")
        nuclear = context.get("nuclear_context") or {}
        if nuclear.get("nucleus_annotated"):
            lines.append("  nuclear context: GO cellular-component annotation includes nucleus")
        for effector in context.get("non_ptm_follow_through") or []:
            lines.append(f"  non-PTM context: {effector.get('gene')} ({effector.get('evidence_type')})")
    for claim in (ledger.get("transition_claims") or [])[:12]:
        transition = claim.get("transition") or {}
        lines.append(
            f"[transition] {transition.get('transition_type')} | {transition.get('from_window')} → {transition.get('to_window')} "
            f"| members={transition.get('members') or transition.get('site_keys') or []}"
        )
    lines.append("=== END SHARED ATLAS CLAIM LEDGER ===")
    return "\n".join(lines)
