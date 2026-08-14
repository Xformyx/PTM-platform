"""Canonical observation-first multisite PTM divergence contract.

This module is shared by API and report workers.  It deliberately separates
measured same-protein site trajectories from biological interpretation:

* ``same_peak_coordination`` is an observed same-peak pattern, not proof of a
  single processive kinase.
* ``temporally_separated_same_direction`` and
  ``temporally_separated_opposite_direction`` are observed patterns, not proof
  of independent kinases, activation/inhibition, feedback, or causality.
* DirectedTemporalRelationship supplies optional temporal-precedence evidence.
* TMM contribution divergence is an optional condition-specific attribution
  layer and never changes the observed site trajectories.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np

from ptm_shared.directed_temporal_relationship import analyze_directed_temporal_relationship, timepoint_to_minutes


CONTRACT_VERSION = "multisite_ptm_divergence.v2"

PATTERN_LABELS = {
    "same_peak_coordination": "Same-peak site coordination",
    "temporally_separated_same_direction": "Temporally separated same-direction site response",
    "temporally_separated_opposite_direction": "Temporally separated opposite-direction site response",
}

LEGACY_PATTERN_MAP = {
    "multisite_coordination": "same_peak_coordination",
    "sequential_regulation": "temporally_separated_same_direction",
    "signal_attenuation": "temporally_separated_opposite_direction",
}

LEGACY_FROM_CANONICAL = {value: key for key, value in LEGACY_PATTERN_MAP.items()}
PATTERN_PRIORITY = {
    "temporally_separated_opposite_direction": 0,
    "temporally_separated_same_direction": 1,
    "same_peak_coordination": 2,
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if np.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _site_short(label: str) -> str:
    parts = str(label).rsplit(" ", 1)
    return parts[-1] if len(parts) == 2 else str(label)


def _bh_qvalues(p_values: Sequence[Optional[float]]) -> List[Optional[float]]:
    indexed = [(index, float(value)) for index, value in enumerate(p_values) if value is not None and np.isfinite(value)]
    if not indexed:
        return [None for _ in p_values]
    count = len(indexed)
    ordered = sorted(indexed, key=lambda item: item[1])
    adjusted = [None for _ in p_values]
    running = 1.0
    for rank in range(count, 0, -1):
        index, p_value = ordered[rank - 1]
        running = min(running, p_value * count / rank)
        adjusted[index] = round(running, 6)
    return adjusted


def _normalise_contribution_map(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    parsed = {str(key).upper(): max(0.0, _as_float(score)) for key, score in value.items()}
    total = sum(parsed.values())
    return {key: round(score / total, 6) for key, score in parsed.items()} if total > 0 else {}


def compare_tmm_contributions(site_a: str, site_b: str, site_contributions: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Compare normalized per-site kinase contribution vectors using TV distance."""
    matrix = site_contributions or {}
    left = _normalise_contribution_map(matrix.get(site_a) or matrix.get(site_a.replace(" ", "_")))
    right = _normalise_contribution_map(matrix.get(site_b) or matrix.get(site_b.replace(" ", "_")))
    if not left or not right:
        return {
            "available": False,
            "classification": "unavailable",
            "total_variation_distance": None,
            "shared_top_kinases": [],
            "siteA_contributions": left,
            "siteB_contributions": right,
        }
    kinases = sorted(set(left) | set(right))
    distance = 0.5 * sum(abs(left.get(kinase, 0.0) - right.get(kinase, 0.0)) for kinase in kinases)
    if distance <= 0.25:
        classification = "concordant_kinase_mixture"
    elif distance >= 0.50:
        classification = "divergent_kinase_mixture"
    else:
        classification = "partially_divergent_kinase_mixture"
    shared = sorted(set(left) & set(right), key=lambda kinase: min(left[kinase], right[kinase]), reverse=True)[:5]
    return {
        "available": True,
        "classification": classification,
        "total_variation_distance": round(float(distance), 6),
        "shared_top_kinases": shared,
        "siteA_contributions": left,
        "siteB_contributions": right,
    }


@dataclass
class TemporalDivergencePair:
    protein: str
    siteA: str
    siteB: str
    pattern: str
    peak_condA: str
    peak_condB: str
    temporal_lag: int
    fcA: float
    fcB: float
    fc_ratio: float
    is_denovoA: bool
    is_denovoB: bool
    clusterA: Optional[str] = None
    clusterB: Optional[str] = None
    shared_pathways: List[str] = field(default_factory=list)
    ks_kinasesA: List[str] = field(default_factory=list)
    ks_kinasesB: List[str] = field(default_factory=list)
    motifA: str = ""
    motifB: str = ""
    ptm_type: str = "phosphorylation"
    directionality: Dict[str, Any] = field(default_factory=dict)
    directionality_tier: str = "D0_unresolved"
    effect_size: float = 0.0
    confidence_tier: str = "Low"
    fdr_q_value: Optional[float] = None
    resolution_warning: Optional[str] = None
    tmm_contribution_divergence: Dict[str, Any] = field(default_factory=dict)
    evidence_eligible_for_ai: bool = False
    evidence_eligible_for_receptor: bool = False
    evidence_gate_reasons: List[str] = field(default_factory=list)
    contract_version: str = CONTRACT_VERSION
    interpretation_boundary: str = "Observed site-specific temporal pattern; no causal mechanism is established."
    legacy_pattern: Optional[str] = None

    def __post_init__(self) -> None:
        self.pattern = LEGACY_PATTERN_MAP.get(self.pattern, self.pattern)
        self.legacy_pattern = self.legacy_pattern or LEGACY_FROM_CANONICAL.get(self.pattern)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TemporalDivergencePair":
        known = set(cls.__dataclass_fields__)
        payload = {key: value for key, value in dict(data).items() if key in known}
        return cls(**payload)

    def to_viz_edge(self) -> Dict[str, Any]:
        return {
            "source": f"{self.protein}_{_site_short(self.siteA)}_{self.peak_condA}",
            "target": f"{self.protein}_{_site_short(self.siteB)}_{self.peak_condB}",
            "type": PATTERN_LABELS.get(self.pattern, self.pattern),
            "temporal_lag": self.temporal_lag,
            "directionality_tier": self.directionality_tier,
            "evidence_eligible": self.evidence_eligible_for_ai,
        }

    def to_ai_sentence(self) -> str:
        site_a, site_b = _site_short(self.siteA), _site_short(self.siteB)
        base = (
            f"{self.protein} has a {PATTERN_LABELS.get(self.pattern, self.pattern).lower()}: "
            f"{site_a} peaks at {self.peak_condA} (FC={self.fcA:+.2f}) and "
            f"{site_b} peaks at {self.peak_condB} (FC={self.fcB:+.2f})."
        )
        direction = self.directionality.get("direction")
        if direction == "source_precedes_target":
            base += f" The observed {site_a}→{site_b} temporal precedence is {self.directionality_tier}."
        elif direction == "target_precedes_source":
            base += f" The observed {site_b}→{site_a} temporal precedence is {self.directionality_tier}."
        else:
            base += " Directionality is unresolved or simultaneous at the available time resolution."
        tmm = self.tmm_contribution_divergence
        if tmm.get("available"):
            base += f" TMM kinase-mixture comparison: {tmm.get('classification')} (TV={tmm.get('total_variation_distance'):.2f})."
        return base + " No causal intervention was evaluated."

    def to_ai_questions(self) -> List[str]:
        site_a, site_b = _site_short(self.siteA), _site_short(self.siteB)
        questions = [
            f"Which site-specific domain, motif, and kinase-context differences could explain the observed {site_a}/{site_b} temporal pattern on {self.protein}?"
        ]
        if self.tmm_contribution_divergence.get("classification") == "divergent_kinase_mixture":
            questions.append(f"Do {site_a} and {site_b} receive distinct condition-specific kinase mixtures despite residing on the same protein?")
        if self.directionality_tier in {"D2_reproducible_directionality", "D3_mechanistically_supported_directionality"}:
            questions.append(f"What post-analysis site-specific validation assay would best test the reproducible temporal precedence between {site_a} and {site_b}?")
        return questions


def _pattern(first_fc: float, second_fc: float, first_index: int, second_index: int) -> str:
    if first_index == second_index:
        return "same_peak_coordination"
    if (first_fc > 0 and second_fc < 0) or (first_fc < 0 and second_fc > 0):
        return "temporally_separated_opposite_direction"
    return "temporally_separated_same_direction"


def _context(enriched: Mapping[str, Any]) -> Tuple[str, List[str], List[str]]:
    motif = str(enriched.get("Enhanced_Matched_Motifs") or enriched.get("Matched_Motifs") or enriched.get("Motifs") or "")[:120]
    rag = enriched.get("rag_enrichment") or {}
    regulation = rag.get("regulation") if isinstance(rag, Mapping) else {}
    records = regulation.get("kinase_substrate", []) if isinstance(regulation, Mapping) else []
    kinases = [str(item.get("kinase") if isinstance(item, Mapping) else item) for item in records if item][:8]
    pathways = rag.get("pathways", []) if isinstance(rag, Mapping) else []
    return motif, kinases, [str(item) for item in pathways if item][:8]


def _gate(pair: TemporalDivergencePair) -> Tuple[bool, bool, List[str]]:
    reasons: List[str] = []
    if pair.confidence_tier == "Low":
        reasons.append("low_effect_size_confidence")
    if pair.resolution_warning:
        reasons.append("insufficient_time_resolution")
    if pair.directionality_tier == "D0_unresolved":
        reasons.append("directionality_unresolved")
    if pair.fdr_q_value is None or pair.fdr_q_value > 0.05:
        reasons.append("temporal_order_fdr_not_supported")
    ai_eligible = not reasons
    receptor_eligible = (
        ai_eligible
        and pair.directionality_tier in {"D2_reproducible_directionality", "D3_mechanistically_supported_directionality"}
        and bool(pair.shared_pathways or set(pair.ks_kinasesA) & set(pair.ks_kinasesB))
    )
    if ai_eligible and not receptor_eligible:
        reasons.append("receptor_context_not_supported")
    return ai_eligible, receptor_eligible, reasons


def compute_divergence_pairs(
    ptm_time_matrix: Mapping[str, Mapping[str, float]],
    ordered_conditions: Sequence[str],
    ptm_activity_class: Mapping[str, str],
    ptm_is_denovo: Set[str],
    enriched_lookup: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ptm_cluster_map: Optional[Mapping[str, Any]] = None,
    ptm_type: str = "phosphorylation",
    *,
    tmm_site_contributions: Optional[Mapping[str, Any]] = None,
    site_replicates: Optional[Mapping[str, Mapping[str, Sequence[Any]]]] = None,
) -> Tuple[List[TemporalDivergencePair], Dict[str, float]]:
    """Return canonical same-protein site pairs and conservative receptor boosts."""
    if len(ordered_conditions) < 3:
        return [], {}
    enriched = enriched_lookup or {}
    clusters = ptm_cluster_map or {}
    by_gene: Dict[str, List[str]] = {}
    for label in ptm_time_matrix:
        parts = str(label).rsplit(" ", 1)
        if len(parts) == 2:
            by_gene.setdefault(parts[0], []).append(str(label))

    all_values = [abs(_as_float(values.get(condition))) for values in ptm_time_matrix.values() for condition in ordered_conditions]
    all_values = [value for value in all_values if value > 0.01]
    median = float(np.median(all_values)) if all_values else 0.0
    mad = max(float(np.median([abs(value - median) for value in all_values])) if all_values else 0.0, 0.1)
    pairs: List[TemporalDivergencePair] = []
    for gene, sites in by_gene.items():
        for left_index in range(len(sites)):
            for right_index in range(left_index + 1, len(sites)):
                site_a, site_b = sites[left_index], sites[right_index]
                if ptm_activity_class.get(site_a, "minor") == "minor" and ptm_activity_class.get(site_b, "minor") == "minor":
                    continue
                values_a = {condition: _as_float(ptm_time_matrix[site_a].get(condition)) for condition in ordered_conditions}
                values_b = {condition: _as_float(ptm_time_matrix[site_b].get(condition)) for condition in ordered_conditions}
                peak_a_index = int(np.argmax(np.abs([values_a[condition] for condition in ordered_conditions])))
                peak_b_index = int(np.argmax(np.abs([values_b[condition] for condition in ordered_conditions])))
                if peak_a_index <= peak_b_index:
                    early_site, late_site, early_values, late_values, early_index, late_index = site_a, site_b, values_a, values_b, peak_a_index, peak_b_index
                else:
                    early_site, late_site, early_values, late_values, early_index, late_index = site_b, site_a, values_b, values_a, peak_b_index, peak_a_index
                early_fc = early_values[ordered_conditions[early_index]]
                late_fc = late_values[ordered_conditions[late_index]]
                motif_a, kinases_a, pathways_a = _context(enriched.get(early_site, {}))
                motif_b, kinases_b, pathways_b = _context(enriched.get(late_site, {}))
                support = {
                    "kinase_substrate_consistent": bool(set(kinases_a) & set(kinases_b)),
                    "motif_consistent": bool(motif_a and motif_b and motif_a.lower() == motif_b.lower()),
                    "ppi_consistent": False,
                    "chromadb_consistent": bool(set(pathways_a) & set(pathways_b)),
                }
                relation = analyze_directed_temporal_relationship(
                    {"key": early_site, "temporal_values": early_values, "replicates": (site_replicates or {}).get(early_site)},
                    {"key": late_site, "temporal_values": late_values, "replicates": (site_replicates or {}).get(late_site)},
                    ordered_conditions,
                    biological_support=support,
                )
                resolution_warning = None
                if len(ordered_conditions) <= 3:
                    resolution_warning = f"LOW RESOLUTION: only {len(ordered_conditions)} timepoints are available."
                effect_size = abs(early_fc - late_fc) / mad
                confidence = "High" if effect_size >= 2.0 else "Medium" if effect_size >= 1.0 else "Low"
                pair = TemporalDivergencePair(
                    protein=gene,
                    siteA=early_site,
                    siteB=late_site,
                    pattern=_pattern(early_fc, late_fc, early_index, late_index),
                    peak_condA=str(ordered_conditions[early_index]),
                    peak_condB=str(ordered_conditions[late_index]),
                    temporal_lag=late_index - early_index,
                    fcA=round(early_fc, 4),
                    fcB=round(late_fc, 4),
                    fc_ratio=round(abs(late_fc) / max(abs(early_fc), 0.01), 4),
                    is_denovoA=early_site in ptm_is_denovo,
                    is_denovoB=late_site in ptm_is_denovo,
                    clusterA=clusters.get(early_site),
                    clusterB=clusters.get(late_site),
                    shared_pathways=sorted(set(pathways_a) & set(pathways_b))[:5],
                    ks_kinasesA=kinases_a,
                    ks_kinasesB=kinases_b,
                    motifA=motif_a,
                    motifB=motif_b,
                    ptm_type=ptm_type,
                    directionality=relation,
                    directionality_tier=str(relation.get("directionality_tier", "D0_unresolved")),
                    effect_size=round(effect_size, 4),
                    confidence_tier=confidence,
                    resolution_warning=resolution_warning,
                    tmm_contribution_divergence=compare_tmm_contributions(early_site, late_site, tmm_site_contributions),
                )
                pairs.append(pair)

    q_values = _bh_qvalues([pair.directionality.get("evidence_profile", {}).get("time_permutation_p_value") for pair in pairs])
    boosts: Dict[str, float] = {}
    for pair, q_value in zip(pairs, q_values):
        pair.fdr_q_value = q_value
        pair.evidence_eligible_for_ai, pair.evidence_eligible_for_receptor, pair.evidence_gate_reasons = _gate(pair)
        if pair.evidence_eligible_for_receptor:
            if pair.is_denovoA:
                boosts[pair.siteA] = max(boosts.get(pair.siteA, 0.0), 0.5)
            if pair.is_denovoB:
                boosts[pair.siteB] = max(boosts.get(pair.siteB, 0.0), 0.5)
    pairs.sort(key=lambda pair: (not pair.evidence_eligible_for_ai, PATTERN_PRIORITY.get(pair.pattern, 9), -pair.effect_size))
    return pairs, boosts


def build_ai_divergence_summary(pairs: Sequence[TemporalDivergencePair], max_pairs: int = 15, *, evidence_only: bool = True) -> str:
    selected = [pair for pair in pairs if pair.evidence_eligible_for_ai] if evidence_only else list(pairs)
    selected = selected[:max_pairs]
    if not selected:
        return ""
    lines = ["## MULTISITE PTM TEMPORAL DIVERGENCE (EVIDENCE-GATED)"]
    lines.append("These are observed site-specific temporal patterns. They do not establish a single kinase, feedback loop, functional activation/inhibition, or causality.")
    for pair in selected:
        lines.append(f"- {pair.to_ai_sentence()}")
    return "\n".join(lines)
