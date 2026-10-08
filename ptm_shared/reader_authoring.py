"""Pure serialization extracted from the existing report authoring packet.

Callers supply calculated cards, estimator and study contracts. No writer or LLM.
"""
from __future__ import annotations
import json
from typing import Any, Mapping
from .feature_identity import audit_feature_identities
AUTHORING_PACKET_VERSION = "reader_authoring_packet.v5"

def build_evidence_utilization(cards: list[dict], observation_audit: Mapping[str, Any] | None = None) -> dict:
    """Count source → adapted → selected cards. Absence ≠ adapter failure."""
    by_type: dict[str, dict[str, int]] = {}
    for card in cards:
        evidence_type = str(card.get("evidence_type") or card.get("category") or "unspecified")
        bucket = by_type.setdefault(evidence_type, {
            "adapted": 0, "with_value_records": 0, "with_trajectory": 0,
        })
        bucket["adapted"] += 1
        if card.get("value_records"):
            bucket["with_value_records"] += 1
        if card.get("trajectory_evidence") or card.get("trajectory"):
            bucket["with_trajectory"] += 1
    return {
        "schema_version": "report_evidence_utilization.v2",
        "by_evidence_type": by_type,
        "observation_selection_audit": dict(observation_audit or {}),
        "exclusion_reasons": list((observation_audit or {}).get("exclusions") or []),
    }


def build_module_evidence_index(observations):
    """Thin, complete grouping over existing observation/claim identities.

    Descriptive temporal-pattern groups are not kinase families or causal
    pathways. Section projection resolves included members from the same packet.
    """
    import hashlib
    groups = {}
    for card in observations:
        patterns = tuple((axis, str(summary.get('label') or summary.get('pattern') or 'unknown'))
                         for axis, summary in sorted((card.get('axis_patterns') or {}).items()))
        key = hashlib.sha256(json.dumps(patterns).encode()).hexdigest()[:20]
        group = groups.setdefault(key, {'bundle_id': 'pattern.' + key, 'grouping': 'descriptive_axis_pattern',
            'patterns': patterns, 'study_frame_ref': 'study.frame', 'member_card_ids': [],
            'observation_claim_ids': [], 'parent_protein_ids': [],
            'required_limitations': ['Shared temporal patterns do not establish a regulatory relationship.'],
            'review_status': 'not_independently_reviewed'})
        group['member_card_ids'].append(card['card_id'])
        group['observation_claim_ids'].extend(card.get('evidence_ids') or [])
        group['parent_protein_ids'].extend(card.get('parent_protein_ids') or [])
    for group in groups.values():
        for field in ('member_card_ids', 'observation_claim_ids', 'parent_protein_ids'):
            group[field] = sorted(set(group[field]))
    return {'schema_version': 'module_evidence_index.v1', 'source': 'feature_observation_card.v3',
            'member_count': len(observations), 'bundles': [groups[key] for key in sorted(groups)]}


def build_coverage_inventory(state, observations):
    """Account for every input row separately from literature depth and manuscript space."""
    from ptm_shared.feature_identity import canonical_feature_identity
    card_ids = {(c.get("feature_identity") or {}).get("reader_feature_id") for c in observations}
    retrieval = (state.get("finding_literature_retrieval") or {}).get("records") or {}
    records = []
    for index, row in enumerate(state.get("vector_plot_raw_data") or []):
        identity = canonical_feature_identity(row)
        fid = identity.get("reader_feature_id")
        records.append({"row_index": index, "feature_id": identity.get("feature_id"), "reader_feature_id": fid,
                        "condition": row.get("condition") or row.get("Condition"),
                        "analysis_status": "processed" if fid in card_ids else "not_evaluable",
                        "analysis_reason": None if fid in card_ids else "identity_or_quantitation_unavailable",
                        "deep_review_status": retrieval.get(fid, {}).get("status", "not_searched"),
                        "authoring_destinations": ["appendix"], "authoring_reason": "inventory_retained"})
    return {"schema_version": "report_coverage_inventory.v1", "denominator": "input_vector_rows",
            "input_count": len(records), "accounted_count": len(records), "records": records,
            "analysis_evidence_inventory": state.get("analysis_evidence_inventory"),
            "source_observation_inventory": state.get("source_observation_inventory"),
            "source_inventory_status": "available" if state.get("source_observation_inventory") else "legacy_not_recorded"}


def build_authoring_packet(*, state, observations, question_map, has_traceable_literature, reader_cards, metadata_contract, observation_selection_audit, candidate_transfer_audit, estimator_contract, figure_cards, section_claim_budget, story_contract):
    """Serialize already prepared report evidence without recalculation."""
    return {
        "contract_version": AUTHORING_PACKET_VERSION,
        "report_scope_policy": "inventory_review_authoring.v1",
        "main_finding_word_budget": (state.get("report_config") or {}).get("main_finding_word_budget", 2400),
        "coverage_inventory": build_coverage_inventory(state, observations),
        "module_evidence_index": build_module_evidence_index(observations),
        "required_module_status": {
            "cross_talk": (state.get("cross_talk_data") or state.get("crosstalk_data") or {}).get("evaluation_status", "not_evaluable")
                           if state.get("analysis_mode") == "cross_talk" else "not_requested",
            "drug_repositioning": (state.get("drug_repositioning_results") or {}).get("evaluation_status", "not_evaluable")
                                  if state.get("report_type") == "extended" else "not_requested"},
        "module_evidence": {"biological_unit_crosswalk": state.get('biological_unit_crosswalk') or {'status': 'pairing_not_declared'}, "cross_talk": state.get("cross_talk_data") or state.get("crosstalk_data") or {"evaluation_status": "not_evaluable" if state.get('analysis_mode') == 'cross_talk' else "not_requested"},
                            "cascade_context": {key: (state.get('cascade_context_snapshot') or {}).get(key)
                                                for key in ('evidence_role', 'direct_relation_claim_allowed', 'cascade_pathway_names', 'required_limitations')},
                            "drug_repositioning": {"evidence_role": "candidate_hypothesis_context", "independent_validation": "not_performed",
                                                   "analysis": state.get("drug_repositioning_results") or {"evaluation_status": "not_requested"}}},
        "study_design": dict(state.get("sample_manifest") or {}),
        "research_question_evidence_map": question_map,
        "feature_identity_audit": audit_feature_identities(state.get("vector_plot_raw_data") or []),
        "mode": "citation_complete" if has_traceable_literature else "data_only",
        "reader_cards": reader_cards,
        "study_metadata_contract": metadata_contract,
        "observation_selection_audit": observation_selection_audit,
        "candidate_transfer_audit": candidate_transfer_audit,
        "report_evidence_utilization": build_evidence_utilization(reader_cards, observation_selection_audit),
        "quantitation_estimator_contract": estimator_contract,
        "figure_cards": figure_cards,
        "section_claim_budget": section_claim_budget,
        "section_story_contract": story_contract,
        "authoring_rules": {
            "required_evidence_anchor": "End each factual paragraph with one or more complete evidence markers copied exactly from supplied cards, for example [EVID:study.frame]. Never emit an incomplete marker or a placeholder.",
            "citation_marker": "Use [REF:pmid:*], [REF:doi:*], or [REF:title:*] only for supplied literature cards.",
            "directness": "Do not claim direct kinase–substrate regulation, causal propagation, catalytic activation, isoform-specific attribution, or perturbation outcome.",
            "de_novo": "Control-undetected rows are detection/LOD context only and must not be placed on conventional Log2FC axes or magnitude rankings.",
            "normalization": "Describe the track as protein-abundance-adjusted relative PTM ratio, not absolute occupancy or kinase activity.",
            "measured_features": "Name current-order measured features and report supplied time-resolved values before aggregate counts or availability statements. Do not call a candidate-residue feature a localized phosphosite unless the card does so.",
            "protein_adjustment": estimator_contract.get("authoring_instruction") or "Use the supplied immutable estimator paragraph exactly. The protein-adjusted estimator is a contrast of condition means of sample-wise PTM/protein ratios; it is not generally independent unadjusted Log2FC minus linked protein Log2FC. The reconstructed legacy metric is audit-only and adjustment does not prove biological truth.",
            "study_metadata": "Use only the resolved study metadata label. A user-verified override supersedes stale free text; unresolved identity conflicts prohibit final release. Do not infer lineage, species, receptor status, or engineering history from a cell-model name.",
        },
    }
