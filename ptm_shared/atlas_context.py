"""Narrative-ready but non-causal evidence joins for the Temporal Atlas.

The Atlas joins already persisted analysis artifacts to a site record.  It does
not recompute kinase attribution, infer localization, or create causal edges.
Every context item preserves its original evidence type so report generation
can describe temporal alignment without converting it into direct regulation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, Mapping, Optional


CONTRACT_VERSION = "atlas_context_evidence.v1"


def _site_key(record: Mapping[str, Any]) -> str:
    gene = record.get("gene") or record.get("Gene.Name") or ""
    position = record.get("position") or record.get("PTM_Position") or record.get("site") or ""
    return f"{gene}_{position}"


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _iter_non_ptm_effectors(signal_propagation: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for key in ("nonptm_effectors", "non_ptm_effectors", "non_ptm_nodes"):
        values = signal_propagation.get(key) or []
        if isinstance(values, list):
            for value in values:
                if isinstance(value, Mapping):
                    yield value


def build_atlas_context_evidence(
    sites: Iterable[Mapping[str, Any]],
    *,
    kinase_activity_heatmap: Optional[Mapping[str, Any]] = None,
    signal_propagation_data: Optional[Mapping[str, Any]] = None,
    substrate_go_localization: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Join persisted context artifacts to Atlas sites with explicit evidence tiers."""
    heatmap = _mapping_or_empty(kinase_activity_heatmap)
    propagation = _mapping_or_empty(signal_propagation_data)
    localization = _mapping_or_empty(substrate_go_localization)
    localizations = _mapping_or_empty(localization.get("gene_localizations"))

    site_context: Dict[str, Dict[str, Any]] = {}
    for site in sites:
        key = str(site.get("site_key") or _site_key(site))
        gene = str(site.get("gene") or "")
        position = str(site.get("position") or "")
        location_terms = [str(term) for term in (localizations.get(gene) or localizations.get(gene.upper()) or [])]
        site_context[key] = {
            "contract_version": CONTRACT_VERSION,
            "kinase_context": [],
            "self_ptm_candidates": [],
            "nuclear_context": {
                "localization_terms": location_terms,
                "nucleus_annotated": any("nucleus" in term.lower() for term in location_terms),
                "evidence_type": "go_cellular_component_annotation" if location_terms else "unavailable",
            },
            "non_ptm_follow_through": [],
            "interpretation_boundary": (
                "Context entries describe persisted candidate attribution, localization, or later abundance evidence; "
                "they do not establish direct kinase-site regulation or causality."
            ),
        }

    for score in heatmap.get("kinase_scores") or []:
        if not isinstance(score, Mapping) or score.get("is_sub_pattern"):
            continue
        kinase = str(score.get("kinase") or "")
        for substrate in score.get("substrates") or []:
            if not isinstance(substrate, Mapping):
                continue
            key = _site_key(substrate)
            if key not in site_context:
                continue
            entry = {
                "kinase": kinase,
                "evidence_type": "kinase_module_substrate_membership",
                "cluster": substrate.get("cluster"),
                "peak_condition": score.get("peak_condition"),
                "kinase_confidence": score.get("confidence"),
                "tmm_evidence": score.get("tmm_evidence"),
                "tmm_profile_type": score.get("tmm_profile_type"),
            }
            if substrate.get("nuclear_tier") is not None:
                entry["nuclear_tier"] = substrate.get("nuclear_tier")
            site_context[key]["kinase_context"].append(entry)

        for self_ptm in score.get("self_ptm") or []:
            if not isinstance(self_ptm, Mapping):
                continue
            self_key = f"{kinase}_{self_ptm.get('site') or ''}"
            if self_key not in site_context:
                continue
            site_context[self_key]["self_ptm_candidates"].append({
                "kinase": kinase,
                "site": self_ptm.get("site"),
                "evidence_type": "regulator_self_ptm_temporal_candidate",
                "relationship": self_ptm.get("relationship"),
                "correlation_with_activity": self_ptm.get("correlation_with_activity"),
                "peak_condition": self_ptm.get("peak_condition"),
                "peak_fc": self_ptm.get("peak_fc"),
            })

    effectors_by_gene: Dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for effector in _iter_non_ptm_effectors(propagation):
        gene = str(effector.get("gene") or effector.get("name") or "")
        if gene:
            effectors_by_gene[gene.upper()].append(effector)
    for key, context in site_context.items():
        gene = key.rsplit("_", 1)[0].upper()
        for effector in effectors_by_gene.get(gene, []):
            context["non_ptm_follow_through"].append({
                "gene": effector.get("gene") or effector.get("name"),
                "evidence_type": "persisted_non_ptm_temporal_context",
                "temporal": effector.get("temporal") or effector.get("timeseries"),
                "protein_log2fc": effector.get("protein_log2fc") or effector.get("log2fc"),
                "role": effector.get("role") or effector.get("effector_type"),
            })
    return site_context
