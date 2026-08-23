"""Graph-aware pathway expansion: Direct NES, not Σ|Log2FC|.

구현 대상: docs/graph_aware_pathway_expansion_contract_v1.md §2–§9
사전등록: 2026-08-23 선언. 탐색적 — Figure 1 Σ|Log2FC| 편향을 본 뒤 고정.
해석 한계: Direct NES는 pathway 소속 정량 단백질의 enrichment다.
          activation·kinase 활성·인과가 아니다.
주장 금지: STRING support나 Insulin canonical overlap으로 pathway를
          발견했다고 쓰지 않는다. de novo를 Direct universe에 넣지 않는다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np

from ptm_shared.de_novo_representation import (
    is_majority_detection,
    narrative_eligible_denovo,
    DetectionCount,
)


L_SHARED = 0.50
"""Shared peptide 귀속 가중. 계약 §3. 2026-08-23."""

L_UNVERIFIED = 0.30
"""Localization unverified 귀속 가중. 계약 §3. 2026-08-23."""

S_SIG = 1.00
S_MISSING = 0.70
S_NS = 0.50
Q_SIG = 0.05

GSEA_WEIGHT_P = 1
N_PERM = 500
PERM_SEED = 20260823
MIN_DIRECT_GENES = 2
MIN_UNIVERSE = 15

STRING_CONF_MIN = 0.70
NETWORK_HOPS = 1
NETWORK_ALPHA = 0.15
"""STRING 1-hop 가중 α. 계약 §7. 권고 0.1–0.2의 중앙. 2026-08-23."""

DIRECTION_CONSISTENCY_MIN = 0.75
MIN_ANNOTATED_SITES = 2

# Exploratory functional signs. Ranking prior가 아니다. 계약 §8.
_FUNCTIONAL_SIGN: Dict[Tuple[str, str], int] = {
    ("MAPK1", "T185"): 1,
    ("MAPK1", "Y187"): 1,
    ("MAPK3", "T202"): 1,
    ("MAPK3", "Y204"): 1,
    ("GSK3A", "S21"): -1,
    ("GSK3B", "S9"): -1,
    ("AKT1", "S473"): 1,
    ("AKT1", "T308"): 1,
    ("AKT2", "S474"): 1,
    ("AKT2", "T309"): 1,
    ("RPS6KB1", "T389"): 1,
    ("IRS1", "S522"): 0,
}

_SITE_RE = re.compile(r"(?:P)?(?:SER|THR|TYR|S|T|Y)(\d+)", re.I)
_SITE_AA = {"SER": "S", "THR": "T", "TYR": "Y", "S": "S", "T": "T", "Y": "Y"}
_CONTROL_RE = re.compile(r"^(control|ctrl|vehicle|untreated|dmso)", re.I)


@dataclass
class SiteEvidence:
    gene: str
    position: str
    timepoint: str
    is_denovo: bool
    E: Optional[float]
    M: Optional[float]
    R: float
    L: float
    S: float
    denovo_support: bool
    high_confidence_denovo: bool
    functional_sign: int


@dataclass
class PathwayTimeScore:
    pathway: str
    timepoint: str
    nes: Optional[float]
    es: Optional[float]
    p_value: Optional[float]
    q_value: Optional[float]
    n_direct: int
    n_universe: int
    protein_support: float
    network_support: float
    denovo_support_count: int
    high_confidence_denovo_count: int
    coherence: Optional[float]
    coverage: Optional[float]
    connectedness: Optional[float]
    temporal_order: Optional[float]
    direction_consistency: Optional[float]
    term: str
    source: str = "direct"


@dataclass
class PathwaySummary:
    pathway: str
    peak_timepoint: Optional[str]
    peak_nes: Optional[float]
    peak_q: Optional[float]
    n_direct: int
    protein_support_peak: float
    network_support_peak: float
    denovo_support_count: int
    high_confidence_denovo_count: int
    coherence: Optional[float]
    term: str
    time_scores: List[PathwayTimeScore] = field(default_factory=list)
    direct_genes: List[str] = field(default_factory=list)


@dataclass
class PathwayExpansionResult:
    universe_size: int
    timepoints: List[str]
    summaries: List[PathwaySummary]
    n_perm: int
    seed: int
    method: str = "direct_nes_v1"

    def to_payload(self) -> Dict[str, Any]:
        """감사·writer용 직렬화. 합성 FinalScore는 없다."""
        return {
            "method": self.method,
            "universe_size": self.universe_size,
            "timepoints": list(self.timepoints),
            "n_perm": self.n_perm,
            "seed": self.seed,
            "summaries": [summary_to_record(s) for s in self.summaries],
        }


def normalize_site(position: Any) -> str:
    text = str(position or "").upper().replace(" ", "")
    match = _SITE_RE.search(text)
    if match:
        token = match.group(0)
        aa = "S"
        for key, letter in _SITE_AA.items():
            if token.startswith(key) or token.startswith("P" + key):
                aa = letter
                break
        return f"{aa}{match.group(1)}"
    return text.strip()


def functional_sign(gene: str, position: str) -> int:
    """탐색적 site 부호. ranking에 쓰지 않는다. 계약 §8."""
    return _FUNCTIONAL_SIGN.get((str(gene).upper(), normalize_site(position)), 0)


def is_control_label(label: str) -> bool:
    return bool(_CONTROL_RE.match(str(label or "").strip()))


def attribution_weight(*, shared_peptide: bool, localization_unverified: bool) -> float:
    if localization_unverified:
        return L_UNVERIFIED
    if shared_peptide:
        return L_SHARED
    return 1.0


def statistic_weight(q_value: Optional[float]) -> float:
    if q_value is None or not math.isfinite(q_value):
        return S_MISSING
    if q_value < Q_SIG:
        return S_SIG
    return S_NS


def reproducibility_weight(detected: Optional[float], expected: Optional[float], cv: Optional[float]) -> float:
    if expected and expected > 0 and detected is not None:
        frac = max(0.0, min(1.0, float(detected) / float(expected)))
    else:
        frac = 1.0
    if cv is not None and math.isfinite(cv) and cv > 0:
        frac = frac / (1.0 + float(cv))
    return float(frac)


def site_evidence_score(
    *,
    log2fc: Optional[float],
    is_denovo: bool,
    detected: Optional[float] = None,
    expected: Optional[float] = None,
    cv: Optional[float] = None,
    q_value: Optional[float] = None,
    shared_peptide: bool = False,
    localization_unverified: bool = False,
) -> Tuple[Optional[float], float, float, float]:
    """E=M×R×L×S. de novo는 E=None. 계약 §3–§4.

    구현 대상: docs/graph_aware_pathway_expansion_contract_v1.md §3
    사전등록: 2026-08-23. 탐색적.
    해석 한계: E는 Direct GSEA 입력이다. 활성화 크기가 아니다.
    주장 금지: de novo에 M를 넣지 않는다.
    """
    R = reproducibility_weight(detected, expected, cv)
    L = attribution_weight(shared_peptide=shared_peptide, localization_unverified=localization_unverified)
    S = statistic_weight(q_value)
    if is_denovo or log2fc is None or not math.isfinite(log2fc):
        return None, R, L, S
    return float(log2fc) * R * L * S, R, L, S


def protein_capped_score(site_scores: Sequence[float]) -> Optional[float]:
    """한 단백질은 |E| 최대 site 하나. 계약 §5."""
    finite = [float(v) for v in site_scores if v is not None and math.isfinite(v)]
    if not finite:
        return None
    return max(finite, key=abs)


def weighted_enrichment_score(
    ranked_genes: Sequence[str],
    scores: Mapping[str, float],
    hit_set: Set[str],
) -> float:
    """Weighted KS enrichment. p=1. 계약 §6."""
    hits = [g for g in ranked_genes if g in hit_set]
    n = len(ranked_genes)
    n_hit = len(hits)
    if n_hit == 0 or n_hit == n or n == 0:
        return 0.0
    nr = sum(abs(float(scores.get(g, 0.0))) ** GSEA_WEIGHT_P for g in hits)
    if nr <= 0:
        return 0.0
    running = 0.0
    peak = 0.0
    miss = 1.0 / float(n - n_hit)
    for gene in ranked_genes:
        if gene in hit_set:
            running += (abs(float(scores.get(gene, 0.0))) ** GSEA_WEIGHT_P) / nr
        else:
            running -= miss
        if abs(running) > abs(peak):
            peak = running
    return float(peak)


def bh_qvalues(pvalues: Sequence[Optional[float]]) -> List[Optional[float]]:
    pairs = [(i, float(p)) for i, p in enumerate(pvalues) if p is not None and math.isfinite(p)]
    q_out: List[Optional[float]] = [None] * len(pvalues)
    n = len(pairs)
    if n == 0:
        return q_out
    pairs.sort(key=lambda x: x[1])
    q_sorted = [0.0] * n
    min_so_far = 1.0
    for rank in range(n, 0, -1):
        idx = rank - 1
        q = pairs[idx][1] * n / rank
        min_so_far = min(min_so_far, q)
        q_sorted[idx] = min(1.0, min_so_far)
    for (orig_i, _), q in zip(pairs, q_sorted):
        q_out[orig_i] = float(q)
    return q_out


def nes_with_fdr(
    scores: Mapping[str, float],
    membership: Mapping[str, Set[str]],
    *,
    timepoint_index: int = 0,
) -> Dict[str, Dict[str, Optional[float]]]:
    """시점 하나, 여러 pathway의 NES와 BH-FDR. 계약 §6."""
    universe = [g for g, v in scores.items() if v is not None and math.isfinite(v) and v != 0.0]
    universe.sort(key=lambda g: (-scores[g], g))
    n_u = len(universe)
    raw: Dict[str, Dict[str, Optional[float]]] = {}
    if n_u < MIN_UNIVERSE:
        for name, hits in membership.items():
            hit = {g for g in hits if g in scores}
            raw[name] = {
                "nes": None,
                "es": None,
                "p_value": None,
                "n_direct": float(len(hit)),
                "n_universe": float(n_u),
            }
        return raw

    score_map = {g: float(scores[g]) for g in universe}
    items = []
    for p_idx, (name, hits) in enumerate(sorted(membership.items())):
        hit = {g for g in hits if g in score_map}
        if len(hit) < MIN_DIRECT_GENES:
            raw[name] = {
                "nes": None,
                "es": None,
                "p_value": None,
                "n_direct": float(len(hit)),
                "n_universe": float(n_u),
            }
            continue
        es = weighted_enrichment_score(universe, score_map, hit)
        rng = np.random.RandomState(PERM_SEED + 1000 * timepoint_index + p_idx)
        null_abs = []
        size = len(hit)
        for _ in range(N_PERM):
            idx = rng.choice(n_u, size=size, replace=False)
            random_hits = {universe[i] for i in idx}
            null_abs.append(abs(weighted_enrichment_score(universe, score_map, random_hits)))
        mean_null = float(np.mean(null_abs)) if null_abs else 0.0
        nes = float(es / mean_null) if mean_null > 0 else 0.0
        n_extreme = sum(1 for v in null_abs if v >= abs(es))
        p_val = (1.0 + n_extreme) / (1.0 + N_PERM)
        items.append((name, es, nes, p_val, len(hit)))

    qvals = bh_qvalues([it[3] for it in items])
    for (name, es, nes, p_val, n_hit), q in zip(items, qvals):
        raw[name] = {
            "nes": nes,
            "es": es,
            "p_value": p_val,
            "q_value": q,
            "n_direct": float(n_hit),
            "n_universe": float(n_u),
        }
    return raw


def network_support_score(
    direct_genes: Set[str],
    protein_E: Mapping[str, float],
    edges: Sequence[Tuple[str, str, float]],
    *,
    alpha: float = NETWORK_ALPHA,
    conf_min: float = STRING_CONF_MIN,
) -> float:
    """Degree-normalized 1-hop support. Direct hit에 넣지 않는다. 계약 §7."""
    adj: Dict[str, Dict[str, float]] = {}
    for a, b, conf in edges:
        if conf < conf_min or not a or not b or a == b:
            continue
        adj.setdefault(a, {})
        adj.setdefault(b, {})
        adj[a][b] = max(adj[a].get(b, 0.0), float(conf))
        adj[b][a] = max(adj[b].get(a, 0.0), float(conf))
    degree = {n: len(nbrs) for n, nbrs in adj.items()}
    total = 0.0
    seen = set()
    for i in direct_genes:
        e_i = protein_E.get(i)
        if e_i is None:
            continue
        for j, conf in adj.get(i, {}).items():
            if j in direct_genes:
                continue
            pair = tuple(sorted((i, j)))
            if pair in seen:
                continue
            seen.add(pair)
            di = max(degree.get(i, 1), 1)
            dj = max(degree.get(j, 1), 1)
            total += alpha * conf * float(e_i) / math.sqrt(di * dj)
    return float(total)


def protein_support_score(direct_genes: Set[str], protein_log2fc: Mapping[str, float]) -> float:
    """직접 소속 단백질의 mean |Protein Log2FC|. 순위가 아니다. 계약 §2."""
    vals = [abs(float(protein_log2fc[g])) for g in direct_genes if g in protein_log2fc]
    if not vals:
        return 0.0
    return float(np.mean(vals))


def geometric_mean(values: Sequence[Optional[float]]) -> Optional[float]:
    nums = [float(v) for v in values if v is not None and math.isfinite(v) and v > 0]
    if not nums:
        return None
    return float(np.exp(np.mean(np.log(np.asarray(nums, dtype=np.float64)))))


def classify_term(
    *,
    n_direct: int,
    n_annotated: int,
    direction_consistency: Optional[float],
    peak_nes: Optional[float],
    network_support: float,
) -> str:
    """계약 §8 용어. 주석이 부족하면 modulated."""
    if n_direct < MIN_DIRECT_GENES:
        return "network-associated" if abs(network_support) > 0 else "modulated"
    if (
        n_annotated >= MIN_ANNOTATED_SITES
        and direction_consistency is not None
        and direction_consistency >= DIRECTION_CONSISTENCY_MIN
        and peak_nes is not None
    ):
        if peak_nes > 0:
            return "activated"
        if peak_nes < 0:
            return "inhibited"
    return "modulated"


def extract_sites(parsed_ptms: Sequence[Mapping[str, Any]]) -> List[SiteEvidence]:
    """parsed_ptms → site×time evidence. de novo는 E=None."""
    sites: List[SiteEvidence] = []
    for ptm in parsed_ptms:
        gene = str(ptm.get("gene") or ptm.get("Gene.Name") or "").strip().upper()
        pos = normalize_site(ptm.get("position") or ptm.get("PTM_Position") or "")
        if not gene:
            continue
        is_denovo = bool(
            ptm.get("conventional_log2fc_na")
            or ptm.get("Conventional_Log2FC_NA")
            or ptm.get("control_pseudocount_used")
            or ptm.get("Control_Pseudocount_Used")
            or ptm.get("activity_class") == "de_novo"
        )
        shared = bool(ptm.get("shared_peptide") or ptm.get("Shared_Peptide"))
        loc_unverified = bool(ptm.get("localization_unverified"))
        confidence = str(ptm.get("denovo_confidence") or ptm.get("DeNovo_Confidence") or "")
        rows = ptm.get("condition_data") or []
        if not rows:
            rows = [{
                "condition": ptm.get("condition") or ptm.get("Condition") or "treatment",
                "ptm_relative_log2fc": ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC"),
                "q_value": ptm.get("q_value"),
                "detection_n": ptm.get("detection_n") or ptm.get("Detection_N"),
                "detection_expected": ptm.get("detection_expected") or ptm.get("Detection_Expected"),
                "cv": ptm.get("treatment_cv") or ptm.get("Treatment_CV"),
                "detection_treatment": ptm.get("detection_treatment") or ptm.get("Detection_Treatment"),
            }]
        for row in rows:
            cond = str(row.get("condition") or row.get("Condition") or "").strip()
            if not cond or is_control_label(cond):
                continue
            fc = _opt_float(row.get("ptm_relative_log2fc") if row.get("ptm_relative_log2fc") is not None else row.get("PTM_Relative_Log2FC"))
            if fc is None and not is_denovo:
                fc = _opt_float(ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC"))
            det, exp = _parse_detection(row)
            E, R, L, S = site_evidence_score(
                log2fc=fc,
                is_denovo=is_denovo,
                detected=det,
                expected=exp,
                cv=_opt_float(row.get("cv") or row.get("Treatment_CV")),
                q_value=_opt_float(row.get("q_value") or ptm.get("q_value")),
                shared_peptide=shared,
                localization_unverified=loc_unverified,
            )
            majority = False
            if det is not None and exp:
                majority = is_majority_detection(DetectionCount(cond, int(det), int(exp)))
            sites.append(SiteEvidence(
                gene=gene,
                position=pos,
                timepoint=cond,
                is_denovo=is_denovo,
                E=E,
                M=None if is_denovo else fc,
                R=R,
                L=L,
                S=S,
                denovo_support=bool(is_denovo and majority),
                high_confidence_denovo=bool(
                    is_denovo
                    and narrative_eligible_denovo(confidence)
                    and str(confidence).lower().startswith("high")
                ),
                functional_sign=functional_sign(gene, pos),
            ))
    return sites


def extract_direct_membership(enriched_data: Sequence[Mapping[str, Any]]) -> Dict[str, Set[str]]:
    """KEGG + Reactome 직접 소속만. STRING indirect 제외. 계약 §6."""
    membership: Dict[str, Set[str]] = {}
    for item in enriched_data:
        gene = str(item.get("gene") or item.get("Gene.Name") or "").strip().upper()
        if not gene:
            continue
        enr = item.get("rag_enrichment") or {}
        for pw in enr.get("pathways") or []:
            name = _pathway_name(pw)
            if name:
                membership.setdefault(name, set()).add(gene)
        reactome = enr.get("reactome") or {}
        for pw in reactome.get("signaling_pathways") or []:
            name = _pathway_name(pw)
            if name:
                membership.setdefault(name, set()).add(gene)
    return membership


def extract_string_edges(network_data: Mapping[str, Any]) -> List[Tuple[str, str, float]]:
    edges = []
    for edge in network_data.get("edges") or []:
        ev = str(edge.get("evidence_type") or "")
        if ev not in {"STRING", "BioGRID"}:
            continue
        src = str(edge.get("source") or "").split("-")[0].strip().upper()
        tgt = str(edge.get("target") or "").split("-")[0].strip().upper()
        conf = _opt_float(edge.get("confidence"))
        if conf is None:
            conf = 0.7 if ev == "STRING" else 0.65
        if src and tgt:
            edges.append((src, tgt, float(conf)))
    return edges


def extract_kegg_pairs(network_data: Mapping[str, Any]) -> List[Tuple[str, str]]:
    pairs = []
    for edge in network_data.get("edges") or []:
        if str(edge.get("evidence_type") or "") != "KEGG":
            continue
        src = str(edge.get("source") or "").split("-")[0].strip().upper()
        tgt = str(edge.get("target") or "").split("-")[0].strip().upper()
        if src and tgt and src != tgt:
            pairs.append((src, tgt))
    return pairs


def score_pathways(
    parsed_ptms: Sequence[Mapping[str, Any]],
    enriched_data: Sequence[Mapping[str, Any]],
    network_data: Optional[Mapping[str, Any]] = None,
    protein_log2fc: Optional[Mapping[str, float]] = None,
) -> PathwayExpansionResult:
    """Direct NES 1차, protein/network는 보조 열.

    구현 대상: docs/graph_aware_pathway_expansion_contract_v1.md §9
    사전등록: 2026-08-23. 탐색적.
    해석 한계: 순위는 Direct NES다. 합성 FinalScore를 만들지 않는다.
    주장 금지: canonical template overlap을 점수에 넣지 않는다.
    """
    sites = extract_sites(parsed_ptms)
    membership = extract_direct_membership(enriched_data)
    edges = extract_string_edges(network_data or {})
    kegg_pairs = extract_kegg_pairs(network_data or {})
    protein_fc = {str(k).upper(): float(v) for k, v in (protein_log2fc or {}).items()}

    timepoints = sorted({s.timepoint for s in sites}, key=_time_key)
    by_time_gene: Dict[str, Dict[str, List[float]]] = {}
    denovo_by_pw_time: Dict[Tuple[str, str], List[SiteEvidence]] = {}
    gene_to_pathways: Dict[str, Set[str]] = {}
    for name, genes in membership.items():
        for g in genes:
            gene_to_pathways.setdefault(g, set()).add(name)

    peak_time_by_gene: Dict[str, str] = {}
    peak_abs_by_gene: Dict[str, float] = {}

    for site in sites:
        if site.E is not None:
            by_time_gene.setdefault(site.timepoint, {}).setdefault(site.gene, []).append(site.E)
            abs_e = abs(site.E)
            if abs_e >= peak_abs_by_gene.get(site.gene, -1.0):
                peak_abs_by_gene[site.gene] = abs_e
                peak_time_by_gene[site.gene] = site.timepoint
        if site.is_denovo:
            for pw in gene_to_pathways.get(site.gene, ()):
                denovo_by_pw_time.setdefault((pw, site.timepoint), []).append(site)

    protein_E_by_time: Dict[str, Dict[str, float]] = {}
    for tp, gene_map in by_time_gene.items():
        protein_E_by_time[tp] = {}
        for gene, values in gene_map.items():
            capped = protein_capped_score(values)
            if capped is not None:
                protein_E_by_time[tp][gene] = capped

    summaries: Dict[str, PathwaySummary] = {}
    for t_idx, tp in enumerate(timepoints):
        scores = protein_E_by_time.get(tp, {})
        nes_map = nes_with_fdr(scores, membership, timepoint_index=t_idx)
        for name, hits in membership.items():
            direct_here = {g for g in hits if g in scores}
            stats = nes_map.get(name, {})
            prot = protein_support_score(direct_here, protein_fc)
            net = network_support_score(direct_here, scores, edges)
            dn_sites = denovo_by_pw_time.get((name, tp), [])
            dn_support = len({(s.gene, s.position) for s in dn_sites if s.denovo_support})
            dn_high = len({(s.gene, s.position) for s in dn_sites if s.high_confidence_denovo})
            coverage = _coverage(direct_here, hits, set(scores))
            connected = _connectedness(direct_here, kegg_pairs)
            temporal = _temporal_order(direct_here, kegg_pairs, peak_time_by_gene, timepoints)
            dcons, n_ann = _direction_consistency(sites, hits, tp)
            nes = stats.get("nes")
            term = classify_term(
                n_direct=len(direct_here),
                n_annotated=n_ann,
                direction_consistency=dcons,
                peak_nes=nes,
                network_support=net,
            )
            row = PathwayTimeScore(
                pathway=name,
                timepoint=tp,
                nes=nes,
                es=stats.get("es"),
                p_value=stats.get("p_value"),
                q_value=stats.get("q_value"),
                n_direct=int(stats.get("n_direct") or len(direct_here)),
                n_universe=int(stats.get("n_universe") or len(scores)),
                protein_support=prot,
                network_support=net,
                denovo_support_count=dn_support,
                high_confidence_denovo_count=dn_high,
                coherence=geometric_mean([coverage, connected, temporal, dcons]),
                coverage=coverage,
                connectedness=connected,
                temporal_order=temporal,
                direction_consistency=dcons,
                term=term,
            )
            summary = summaries.setdefault(name, PathwaySummary(
                pathway=name,
                peak_timepoint=None,
                peak_nes=None,
                peak_q=None,
                n_direct=0,
                protein_support_peak=0.0,
                network_support_peak=0.0,
                denovo_support_count=0,
                high_confidence_denovo_count=0,
                coherence=None,
                term="modulated",
                direct_genes=sorted(hits),
            ))
            summary.time_scores.append(row)

    for summary in summaries.values():
        ranked = [r for r in summary.time_scores if r.nes is not None]
        if ranked:
            best = max(ranked, key=lambda r: r.nes if r.nes is not None else float("-inf"))
        elif summary.time_scores:
            best = max(summary.time_scores, key=lambda r: r.n_direct)
        else:
            continue
        summary.peak_timepoint = best.timepoint
        summary.peak_nes = best.nes
        summary.peak_q = best.q_value
        summary.n_direct = max(r.n_direct for r in summary.time_scores)
        summary.protein_support_peak = best.protein_support
        summary.network_support_peak = best.network_support
        summary.denovo_support_count = max(r.denovo_support_count for r in summary.time_scores)
        summary.high_confidence_denovo_count = max(r.high_confidence_denovo_count for r in summary.time_scores)
        summary.coherence = best.coherence
        summary.term = classify_term(
            n_direct=summary.n_direct,
            n_annotated=_direction_consistency(
                sites, set(summary.direct_genes), best.timepoint
            )[1],
            direction_consistency=best.direction_consistency,
            peak_nes=summary.peak_nes,
            network_support=summary.network_support_peak,
        )

    ordered = sorted(
        summaries.values(),
        key=lambda s: (
            s.peak_nes is None,
            -(s.peak_nes if s.peak_nes is not None else float("-inf")),
            -(s.n_direct),
            s.pathway,
        ),
    )
    universe_sizes = [len(protein_E_by_time.get(tp, {})) for tp in timepoints]
    return PathwayExpansionResult(
        universe_size=max(universe_sizes) if universe_sizes else 0,
        timepoints=timepoints,
        summaries=ordered,
        n_perm=N_PERM,
        seed=PERM_SEED,
    )


def _coverage(direct: Set[str], pathway_genes: Set[str], universe: Set[str]) -> Optional[float]:
    in_u = pathway_genes & universe
    if not in_u:
        return None
    return float(len(direct & in_u) / len(in_u))


def _connectedness(direct: Set[str], pairs: Sequence[Tuple[str, str]]) -> Optional[float]:
    nodes = list(direct)
    if len(nodes) < 2:
        return None
    undirected = {tuple(sorted(p)) for p in pairs}
    possible = 0
    hit = 0
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            possible += 1
            if tuple(sorted((a, b))) in undirected:
                hit += 1
    return float(hit / possible) if possible else None


def _temporal_order(
    direct: Set[str],
    directed_pairs: Sequence[Tuple[str, str]],
    peak_time: Mapping[str, str],
    timepoints: Sequence[str],
) -> Optional[float]:
    order = {tp: i for i, tp in enumerate(timepoints)}
    scored = 0
    ok = 0
    for src, tgt in directed_pairs:
        if src not in direct or tgt not in direct:
            continue
        t0 = peak_time.get(src)
        t1 = peak_time.get(tgt)
        if t0 is None or t1 is None:
            continue
        scored += 1
        if order.get(t0, 10**9) <= order.get(t1, 10**9):
            ok += 1
    if scored == 0:
        return None
    return float(ok / scored)


def _direction_consistency(
    sites: Sequence[SiteEvidence],
    pathway_genes: Set[str],
    timepoint: str,
) -> Tuple[Optional[float], int]:
    labelled = [
        s for s in sites
        if s.gene in pathway_genes and s.timepoint == timepoint and s.functional_sign != 0 and s.E is not None
    ]
    if not labelled:
        return None, 0
    ok = sum(1 for s in labelled if s.E * s.functional_sign > 0)
    return float(ok / len(labelled)), len(labelled)


def summary_to_record(summary: PathwaySummary) -> Dict[str, Any]:
    return {
        "pathway": summary.pathway,
        "peak_timepoint": summary.peak_timepoint,
        "peak_nes": summary.peak_nes,
        "peak_q": summary.peak_q,
        "n_direct": summary.n_direct,
        "protein_support": summary.protein_support_peak,
        "network_support": summary.network_support_peak,
        "denovo_support_count": summary.denovo_support_count,
        "high_confidence_denovo_count": summary.high_confidence_denovo_count,
        "coherence": summary.coherence,
        "term": summary.term,
        "direct_genes": list(summary.direct_genes),
        "time_scores": [
            {
                "timepoint": row.timepoint,
                "nes": row.nes,
                "es": row.es,
                "p_value": row.p_value,
                "q_value": row.q_value,
                "n_direct": row.n_direct,
                "n_universe": row.n_universe,
                "protein_support": row.protein_support,
                "network_support": row.network_support,
                "denovo_support_count": row.denovo_support_count,
                "high_confidence_denovo_count": row.high_confidence_denovo_count,
                "coherence": row.coherence,
                "term": row.term,
            }
            for row in summary.time_scores
        ],
    }


def _pathway_name(pw: Any) -> str:
    if isinstance(pw, dict):
        raw = str(pw.get("name") or pw.get("pathway") or "").strip()
    else:
        raw = str(pw or "").strip()
    if " - " in raw:
        raw = raw.split(" - ")[0].strip()
    if raw and raw == raw.upper():
        raw = raw.title()
    return raw


def _parse_detection(row: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    det = _opt_float(row.get("detection_n") or row.get("Detection_N"))
    exp = _opt_float(row.get("detection_expected") or row.get("Detection_Expected"))
    text = str(row.get("detection_treatment") or row.get("Detection_Treatment") or "")
    if (det is None or exp is None) and "/" in text:
        left, right = text.split("/", 1)
        det = _opt_float(left)
        exp = _opt_float(right)
    return det, exp


def _opt_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _time_key(label: str) -> Tuple[float, str]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(min|m|h|hr|hour)", str(label), re.I)
    if not match:
        return (float("inf"), str(label).lower())
    value = float(match.group(1))
    unit = match.group(2).lower()
    minutes = value * 60.0 if unit.startswith("h") else value
    return (minutes, str(label).lower())
