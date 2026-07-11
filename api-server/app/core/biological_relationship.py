"""
Biological Relationship Objects — v1.0
======================================
Defines TemporalDivergencePair, a first-class biological entity representing
time-resolved PTM site pairs on the same protein with divergent temporal dynamics.

Architecture:
    compute_divergence_pairs() → List[TemporalDivergencePair]
                                         ↓                ↓
                                  Viz Layer           AI Layer
                             (to_viz_edge)    (to_ai_sentence, to_ai_layer)

Consumers:
  - workers/common/receptor_inference.py           (de_novo boost scoring)
  - workers/report_generation/.../temporal_comovement_node.py  (AI narrative)
  - workers/common/biological_relationship.py (source — keep in sync)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Set, Tuple

_PATTERN_LABELS: Dict[str, str] = {
    "signal_attenuation": "Signal Attenuation",
    "sequential_regulation": "Sequential Regulation",
    "multisite_coordination": "Multisite Coordination",
}

_PATTERN_PRIORITY: Dict[str, int] = {
    "signal_attenuation": 0,
    "sequential_regulation": 1,
    "multisite_coordination": 2,
}


@dataclass
class TemporalDivergencePair:
    """
    A time-resolved biological relationship between two PTM sites on the same protein.

    Each instance carries sufficient context for two independent consumers:
      - Visualization layer  → to_viz_edge() / to_viz_node_pair()
      - AI interpretation    → to_ai_sentence() / to_ai_questions() / to_ai_layer()

    Example::

        pair = TemporalDivergencePair(
            protein="SPAG9", siteA="SPAG9 S597", siteB="SPAG9 S594",
            pattern="signal_attenuation",
            peak_condA="6h", peak_condB="24h",
            temporal_lag=2, fcA=23.8, fcB=-4.2, fc_ratio=0.18,
            is_denovoA=True, is_denovoB=False,
        )
        print(pair.to_ai_sentence())
        # SPAG9 S597 phosphorylation (de novo — not detected in control) peaked ...
    """

    # ── Core identity ──────────────────────────────────────────────────────────
    protein: str            # Gene symbol, e.g. "SPAG9"
    siteA: str              # Full label "SPAG9 S597"
    siteB: str              # Full label "SPAG9 S594"
    pattern: str            # "signal_attenuation" | "sequential_regulation" | "multisite_coordination"

    # ── Temporal evidence ──────────────────────────────────────────────────────
    peak_condA: str         # condition at peak for siteA, e.g. "6h"
    peak_condB: str         # condition at peak for siteB, e.g. "24h"
    temporal_lag: int       # index difference between peaks (0 = simultaneous)
    fcA: float              # log2FC at peak for siteA
    fcB: float              # log2FC at peak for siteB
    fc_ratio: float         # abs(fcB) / abs(fcA)

    # ── Site properties ────────────────────────────────────────────────────────
    is_denovoA: bool        # siteA absent in control → de novo
    is_denovoB: bool        # siteB absent in control → de novo

    # ── Biological context (optional — enriched at compute time) ──────────────
    clusterA: Optional[str] = None
    clusterB: Optional[str] = None
    shared_pathways: List[str] = field(default_factory=list)
    ks_kinasesA: List[str] = field(default_factory=list)
    ks_kinasesB: List[str] = field(default_factory=list)
    motifA: str = ""
    motifB: str = ""

    # ── Metadata ───────────────────────────────────────────────────────────────
    ptm_type: str = "phosphorylation"

    # ─────────────────────────────────────────────────────────────────────────
    # Serialization
    # ─────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TemporalDivergencePair":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    # ─────────────────────────────────────────────────────────────────────────
    # Visualization Layer
    # ─────────────────────────────────────────────────────────────────────────

    def to_viz_edge(self) -> dict:
        """Edge object consumed by the frontend visualization layer."""
        return {
            "source": f"{self.protein}_{self._site_short(self.siteA)}_{self.peak_condA}",
            "target": f"{self.protein}_{self._site_short(self.siteB)}_{self.peak_condB}",
            "type": _PATTERN_LABELS.get(self.pattern, self.pattern),
            "temporal_lag": self.temporal_lag,
            "fc_ratio": self.fc_ratio,
            "is_denovo_involved": self.is_denovoA or self.is_denovoB,
        }

    def to_viz_node_pair(self) -> List[dict]:
        """Two node objects consumed by the frontend visualization layer."""
        nodes = []
        for site_label, cond, fc, is_dn in [
            (self.siteA, self.peak_condA, self.fcA, self.is_denovoA),
            (self.siteB, self.peak_condB, self.fcB, self.is_denovoB),
        ]:
            short = self._site_short(site_label)
            nodes.append({
                "id": f"{self.protein}_{short}_{cond}",
                "protein": self.protein,
                "site": short,
                "time": cond,
                "fc": round(fc, 2),
                "de_novo": is_dn,
            })
        return nodes

    # ─────────────────────────────────────────────────────────────────────────
    # AI Layer
    # ─────────────────────────────────────────────────────────────────────────

    def to_ai_sentence(self) -> str:
        """
        One-sentence biological narrative suitable for LLM injection.

        Encodes temporal causality as a human-readable string, e.g.::

            "SPAG9 S597 phosphorylation (de novo — not detected in control) peaked
             strongly at 6h (FC=+23.80), followed by an inhibitory signal at S594 at 24h
             (FC=-4.20). This 2-timepoint lag is consistent with a negative feedback or
             signal attenuation mechanism on SPAG9."
        """
        pt = self.ptm_type
        sA = self._site_short(self.siteA)
        sB = self._site_short(self.siteB)
        dn_note = " (de novo — not detected in control)" if self.is_denovoA else ""

        if self.pattern == "signal_attenuation":
            opp = "inhibitory" if self.fcA > 0 else "activating"
            return (
                f"{self.protein} {sA} {pt}{dn_note} peaked strongly at "
                f"{self.peak_condA} (FC={self.fcA:+.2f}), followed by an {opp} "
                f"signal at {sB} at {self.peak_condB} (FC={self.fcB:+.2f}). "
                f"This {self.temporal_lag}-timepoint lag is consistent with a "
                f"negative feedback or signal attenuation mechanism on {self.protein}."
            )
        elif self.pattern == "sequential_regulation":
            direction = "activating" if self.fcA > 0 else "inhibitory"
            return (
                f"{self.protein} shows sequential {direction} {pt}: "
                f"{sA}{dn_note} peaks at {self.peak_condA} (FC={self.fcA:+.2f}), "
                f"followed by {sB} at {self.peak_condB} (FC={self.fcB:+.2f}). "
                f"The {self.temporal_lag}-timepoint sequential pattern suggests "
                f"two independent regulatory events on {self.protein}."
            )
        else:  # multisite_coordination
            return (
                f"{self.protein} {sA}{dn_note} and {sB} both peak at "
                f"{self.peak_condA} (FC={self.fcA:+.2f} and {self.fcB:+.2f}), "
                f"suggesting co-regulation by a single enzyme or scaffold-mediated "
                f"multisite {pt}."
            )

    def to_ai_questions(self) -> List[str]:
        """Biologically motivated research questions for this specific pair."""
        sA = self._site_short(self.siteA)
        sB = self._site_short(self.siteB)
        pt = self.ptm_type
        questions: List[str] = []

        if self.pattern == "signal_attenuation":
            if self.is_denovoA:
                questions.append(
                    f"Does {sA} act as a trigger site for {self.protein} "
                    f"signaling cascade remodeling?"
                )
            questions.append(
                f"Could the delayed {sB} suppression at {self.peak_condB} represent "
                f"negative feedback inhibition downstream of {sA}?"
            )
            if self.ks_kinasesA:
                questions.append(
                    f"Which upstream kinases ({', '.join(self.ks_kinasesA[:3])}) are most "
                    f"consistent with the {sA} temporal profile?"
                )
            else:
                questions.append(
                    f"Which kinase is responsible for {sA} {pt} at {self.peak_condA}?"
                )

        elif self.pattern == "sequential_regulation":
            questions.append(
                f"Do {sA} and {sB} represent a processive {pt} cascade on "
                f"{self.protein}, or two independent kinase events?"
            )
            questions.append(
                f"What structural feature of {self.protein} allows sequential "
                f"access to {sA} and {sB}?"
            )
            if self.shared_pathways:
                questions.append(
                    f"Given shared pathway context ({', '.join(self.shared_pathways[:2])}), "
                    f"could a common scaffold mediate the sequential {pt}?"
                )

        else:  # multisite_coordination
            questions.append(
                f"Does the simultaneous {sA}/{sB} peak suggest a kinase "
                f"with multisite processivity on {self.protein}?"
            )
            questions.append(
                f"Could a scaffold protein mediate co-regulation of {sA} and {sB} "
                f"at {self.peak_condA}?"
            )

        if self.is_denovoA or self.is_denovoB:
            dn_site = sA if self.is_denovoA else sB
            questions.append(
                f"Is {dn_site} a condition-specific {pt} site, and what structural "
                f"accessibility change enables its modification?"
            )

        return questions

    def to_ai_layer(self) -> dict:
        """
        Complete AI interpretation layer dict.

        Structure mirrors the two-layer architecture::

            {
              "protein": "SPAG9",
              "pair": "S597 → S594",
              "pattern": "Signal Attenuation",
              "narrative": "SPAG9 S597 phosphorylation ...",
              "key_events": [...],
              "key_relationship": {...},
              "confidence": {...},
              "ai_questions": [...],
            }
        """
        sA = self._site_short(self.siteA)
        sB = self._site_short(self.siteB)
        return {
            "protein": self.protein,
            "pair": f"{sA} → {sB}",
            "pattern": _PATTERN_LABELS.get(self.pattern, self.pattern),
            "narrative": self.to_ai_sentence(),
            "key_events": [
                {
                    "site": sA,
                    "time": self.peak_condA,
                    "fc": round(self.fcA, 2),
                    "de_novo": self.is_denovoA,
                    "role": self._role_label(self.fcA, self.is_denovoA, "A"),
                },
                {
                    "site": sB,
                    "time": self.peak_condB,
                    "fc": round(self.fcB, 2),
                    "de_novo": self.is_denovoB,
                    "role": self._role_label(self.fcB, self.is_denovoB, "B"),
                },
            ],
            "key_relationship": {
                "pair": f"{sA} → {sB}",
                "pattern": _PATTERN_LABELS.get(self.pattern, self.pattern),
                "lag": f"{self.temporal_lag} timepoint{'s' if self.temporal_lag != 1 else ''}",
                "fc_ratio": round(self.fc_ratio, 3),
                "shared_pathways": self.shared_pathways[:3],
                "kinase_candidates": list(
                    dict.fromkeys(self.ks_kinasesA[:3] + self.ks_kinasesB[:3])
                ),
            },
            "confidence": self.confidence(),
            "ai_questions": self.to_ai_questions(),
        }

    def confidence(self) -> dict:
        """
        Evidence quality across three dimensions.

        Returns a dict with keys: temporal_evidence, statistical, biological_prior.
        Each is "strong" | "moderate" | "weak" (or "supported" | "limited").
        """
        combined_fc = abs(self.fcA) + abs(self.fcB)
        if self.temporal_lag >= 2 and combined_fc >= 4.0:
            temporal = "strong"
        elif self.temporal_lag >= 1 and combined_fc >= 2.0:
            temporal = "moderate"
        else:
            temporal = "weak"

        stat_score = 0
        if self.is_denovoA or self.is_denovoB:
            stat_score += 2
        if abs(self.fcA) >= 2.0:
            stat_score += 1
        if abs(self.fcB) >= 1.0:
            stat_score += 1
        statistical = "strong" if stat_score >= 3 else ("moderate" if stat_score >= 2 else "weak")

        has_context = bool(self.shared_pathways or self.ks_kinasesA or self.ks_kinasesB)
        biological = "supported" if has_context else "limited"

        return {
            "temporal_evidence": temporal,
            "statistical": statistical,
            "biological_prior": biological,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _site_short(self, label: str) -> str:
        """'SPAG9 S597' → 'S597'"""
        parts = label.rsplit(" ", 1)
        return parts[-1] if len(parts) == 2 else label

    def _role_label(self, fc: float, is_denovo: bool, which: str) -> str:
        prefix = "de novo " if is_denovo else ""
        if self.pattern == "signal_attenuation":
            return (
                f"{prefix}early {'activating' if fc > 0 else 'inhibitory'} event"
                if which == "A"
                else f"delayed {'inhibitory' if fc < 0 else 'activating'} response"
            )
        elif self.pattern == "sequential_regulation":
            order = "first" if which == "A" else "second"
            return f"{order} {prefix}{'activating' if fc > 0 else 'inhibitory'} event"
        else:
            return f"{prefix}co-regulated site"


# ─────────────────────────────────────────────────────────────────────────────
# Shared Computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_divergence_pairs(
    ptm_time_matrix: Dict[str, Dict[str, float]],
    ordered_conditions: List[str],
    ptm_activity_class: Dict[str, str],
    ptm_is_denovo: Set[str],
    enriched_lookup: Optional[Dict] = None,
    ptm_cluster_map: Optional[Dict] = None,
    ptm_type: str = "phosphorylation",
) -> Tuple[List[TemporalDivergencePair], Dict[str, float]]:
    """
    Compute multi-site temporal divergence pairs from a PTM time matrix.

    Args:
        ptm_time_matrix:   {ptm_label: {condition: log2fc}}
        ordered_conditions: conditions sorted chronologically
        ptm_activity_class: {ptm_label: "de_novo"|"regulated"|"minor"}
        ptm_is_denovo:      set of de_novo ptm_labels
        enriched_lookup:    optional {ptm_label: enriched_data_dict}
                            (provides motif / pathway / kinase context)
        ptm_cluster_map:    optional {ptm_label: cluster_id}
        ptm_type:           "phosphorylation" | "ubiquitylation" | etc.

    Returns:
        (pairs, divergence_boost_map)
        - pairs: sorted List[TemporalDivergencePair]
        - divergence_boost_map: {ptm_label: boosted_de_novo_weight (0.5–0.7)}
    """
    pairs: List[TemporalDivergencePair] = []
    divergence_boost: Dict[str, float] = {}

    if len(ordered_conditions) < 3:
        return pairs, divergence_boost

    el = enriched_lookup or {}
    cm = ptm_cluster_map or {}

    # Group PTMs by gene
    gene_sites: Dict[str, List[str]] = {}
    for lbl in ptm_time_matrix:
        parts = lbl.rsplit(" ", 1)
        if len(parts) == 2:
            gene = parts[0]
            gene_sites.setdefault(gene, []).append(lbl)

    for gene, sites in gene_sites.items():
        if len(sites) < 2:
            continue

        # Compute peak (condition, fc, index) per site
        site_peaks: Dict[str, dict] = {}
        for s in sites:
            ts = ptm_time_matrix[s]
            best_fc, best_cond, best_idx = 0.0, None, 0
            for ci, c in enumerate(ordered_conditions):
                fv = ts.get(c, 0.0)
                if abs(fv) > abs(best_fc):
                    best_fc, best_cond, best_idx = fv, c, ci
            site_peaks[s] = {
                "peak_cond": best_cond or ordered_conditions[0],
                "peak_fc": best_fc,
                "peak_idx": best_idx,
                "is_denovo": s in ptm_is_denovo,
            }

        for i in range(len(sites)):
            for j in range(i + 1, len(sites)):
                sA, sB = sites[i], sites[j]
                pA, pB = site_peaks[sA], site_peaks[sB]
                clsA = ptm_activity_class.get(sA, "minor")
                clsB = ptm_activity_class.get(sB, "minor")
                if clsA == "minor" and clsB == "minor":
                    continue

                fcA, fcB = pA["peak_fc"], pB["peak_fc"]
                idxA, idxB = pA["peak_idx"], pB["peak_idx"]

                # Ensure A is always the earlier-peaking site
                if idxA > idxB:
                    sA, sB = sB, sA
                    pA, pB = pB, pA
                    fcA, fcB = fcB, fcA
                    idxA, idxB = idxB, idxA

                # Pattern classification
                if idxA == idxB:
                    pattern = "multisite_coordination"
                elif (fcA > 0 and fcB < 0) or (fcA < 0 and fcB > 0):
                    pattern = "signal_attenuation"
                else:
                    pattern = "sequential_regulation"

                # Enrichment context
                enA, enB = el.get(sA, {}), el.get(sB, {})
                motifA = str(enA.get("Enhanced_Matched_Motifs") or enA.get("Matched_Motifs", ""))[:80]
                motifB = str(enB.get("Enhanced_Matched_Motifs") or enB.get("Matched_Motifs", ""))[:80]
                ragA = enA.get("rag_enrichment", {}) or {}
                ragB = enB.get("rag_enrichment", {}) or {}
                _reg_A = ragA.get("regulation", {})
                _reg_B = ragB.get("regulation", {})
                ksA = _reg_A.get("kinase_substrate", []) if isinstance(_reg_A, dict) else []
                ksB = _reg_B.get("kinase_substrate", []) if isinstance(_reg_B, dict) else []
                pathA = set(ragA.get("pathways", []) if isinstance(ragA.get("pathways"), list) else [])
                pathB = set(ragB.get("pathways", []) if isinstance(ragB.get("pathways"), list) else [])

                pair = TemporalDivergencePair(
                    protein=gene,
                    siteA=sA,
                    siteB=sB,
                    pattern=pattern,
                    peak_condA=pA["peak_cond"],
                    peak_condB=pB["peak_cond"],
                    temporal_lag=idxB - idxA,
                    fcA=round(fcA, 4),
                    fcB=round(fcB, 4),
                    fc_ratio=round(abs(fcB) / max(abs(fcA), 0.01), 3),
                    is_denovoA=pA["is_denovo"],
                    is_denovoB=pB["is_denovo"],
                    clusterA=cm.get(sA),
                    clusterB=cm.get(sB),
                    shared_pathways=list(pathA & pathB)[:5],
                    ks_kinasesA=[
                        k.get("kinase", k) if isinstance(k, dict) else str(k)
                        for k in (ksA or [])
                    ][:5],
                    ks_kinasesB=[
                        k.get("kinase", k) if isinstance(k, dict) else str(k)
                        for k in (ksB or [])
                    ][:5],
                    motifA=motifA,
                    motifB=motifB,
                    ptm_type=ptm_type,
                )
                pairs.append(pair)

                # De novo divergence boost weights for receptor confidence scoring
                if pattern == "signal_attenuation":
                    if pB["is_denovo"] and fcB < 0:
                        divergence_boost[sB] = 0.7
                    if pA["is_denovo"] and fcA > 0:
                        divergence_boost[sA] = 0.6
                elif pattern == "sequential_regulation":
                    if pA["is_denovo"]:
                        divergence_boost[sA] = 0.5
                    if pB["is_denovo"]:
                        divergence_boost[sB] = 0.5

    # Sort: Signal Attenuation first, then by combined |FC|, de_novo involvement
    pairs.sort(key=lambda p: (
        _PATTERN_PRIORITY.get(p.pattern, 3),
        -(abs(p.fcA) + abs(p.fcB)),
        -int(p.is_denovoA or p.is_denovoB),
    ))

    return pairs, divergence_boost


def build_ptm_time_matrix_from_enriched(
    enriched_data: List[dict],
) -> Tuple[Dict[str, Dict[str, float]], Set[str]]:
    """
    Build ptm_time_matrix from enriched_data entries that have condition_data.

    Used by workers that receive the enriched JSON format (one entry per PTM
    with a nested condition_data list) rather than the flattened vector_data
    format (one row per PTM×condition) used by the API server.

    Returns:
        (ptm_time_matrix, ptm_is_denovo)
    """
    ptm_time_matrix: Dict[str, Dict[str, float]] = {}
    ptm_is_denovo: Set[str] = set()

    for r in (enriched_data or []):
        gene = r.get("gene") or r.get("Gene.Name", "")
        pos = r.get("position") or r.get("PTM_Position", "")
        if not gene or not pos:
            continue
        lbl = f"{gene} {pos}".strip()
        if r.get("control_pseudocount_used"):
            ptm_is_denovo.add(lbl)
        for cd in (r.get("condition_data") or []):
            cond = cd.get("condition", "")
            fc_val = cd.get("ptm_relative_log2fc") or cd.get("log2fc") or 0
            if cond and fc_val is not None:
                ptm_time_matrix.setdefault(lbl, {})[cond] = float(fc_val)

    return ptm_time_matrix, ptm_is_denovo


def build_ai_divergence_summary(
    pairs: List[TemporalDivergencePair],
    max_pairs: int = 15,
) -> str:
    """
    Build a structured multi-paragraph AI context block from a list of pairs.

    This is the top-level function for injecting divergence analysis into LLM prompts.
    Groups pairs by pattern, generates narrative sentences and research questions.

    Args:
        pairs:     sorted List[TemporalDivergencePair]
        max_pairs: total pairs to include (most significant first)

    Returns:
        A formatted string block ready for LLM injection.
    """
    if not pairs:
        return ""

    limited = pairs[:max_pairs]
    ptm_type = limited[0].ptm_type if limited else "phosphorylation"

    lines: List[str] = []
    lines.append("\n## MULTI-SITE TEMPORAL DIVERGENCE ANALYSIS\n")
    lines.append(
        f"The following proteins contain multiple {ptm_type} sites with "
        "divergent temporal dynamics. These intra-protein site pairs reveal "
        "distinct regulatory mechanisms operating on the same protein substrate:\n"
    )

    pattern_order = ["signal_attenuation", "sequential_regulation", "multisite_coordination"]
    pattern_labels = _PATTERN_LABELS

    for pat in pattern_order:
        pat_pairs = [p for p in limited if p.pattern == pat]
        if not pat_pairs:
            continue

        lines.append(f"### {pattern_labels[pat]}")
        for pair in pat_pairs[:8]:
            lines.append(f"- {pair.to_ai_sentence()}")
            dn_flags = []
            if pair.is_denovoA:
                dn_flags.append(f"⚡ {pair._site_short(pair.siteA)} is de novo")
            if pair.is_denovoB:
                dn_flags.append(f"⚡ {pair._site_short(pair.siteB)} is de novo")
            if dn_flags:
                lines.append(f"  [{', '.join(dn_flags)}]")
        lines.append("")

    lines.append("### Research Questions Generated from Divergence Patterns\n")
    seen_questions: set = set()
    q_count = 0
    for pair in limited:
        for q in pair.to_ai_questions():
            if q not in seen_questions and q_count < 12:
                lines.append(f"- {q}")
                seen_questions.add(q)
                q_count += 1

    lines.append(
        "\n   Incorporate the above intra-protein site divergence findings into the "
        "biological interpretation. Prioritize Signal Attenuation pairs as evidence "
        "for negative feedback mechanisms. Use the Research Questions as a framework "
        "for discussing kinase candidates, scaffold function, and regulatory timing.\n"
    )

    return "\n".join(lines)
