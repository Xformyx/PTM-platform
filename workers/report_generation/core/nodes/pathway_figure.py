"""Figure 1 and pathway candidates from Direct NES.

구현 대상: docs/graph_aware_pathway_expansion_contract_v1.md §2, §10
사전등록: 2026-08-23. 탐색적 — Σ|Log2FC| Figure 1을 본 뒤 고정.
해석 한계: Direct NES는 소속 정량 단백질의 enrichment다. activation이 아니다.
주장 금지: STRING 열이나 Insulin template overlap으로 pathway를 발견했다고
          쓰지 않는다. 합성 FinalScore를 만들지 않는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ptm_shared.pathway_expansion import (
    PathwayExpansionResult,
    PathwaySummary,
    score_pathways,
)

logger = logging.getLogger(__name__)

_DISEASE_KEYWORDS = (
    "infection", "virus", "viral", "cancer", "carcinogenesis",
    "lupus", "amoebiasis", "leishmaniasis", "tuberculosis",
    "hepatitis", "influenza", "measles", "pertussis",
    "shigellosis", "salmonella", "pathogenic", "disease",
    "diabetes", "cardiomyopathy", "alzheimer", "parkinson",
    "huntington", "prion", "asthma", "glioma", "melanoma",
    "leukemia", "lymphoma",
)

_TERM_COLOR = {
    "activated": "#C0392B",
    "inhibited": "#2471A3",
    "modulated": "#7F8C8D",
    "network-associated": "#1E8449",
}

FIG1_TITLE = (
    "Time-resolved Direct PTM Pathway Enrichment "
    "with Independent Protein and Network Support"
)


def is_disease_pathway(name: str) -> bool:
    """표시 필터. 점수 prior가 아니다."""
    lower = str(name or "").lower()
    return any(kw in lower for kw in _DISEASE_KEYWORDS)


def collect_protein_log2fc(
    parsed_ptms: Sequence[Mapping[str, Any]],
    enriched_data: Sequence[Mapping[str, Any]],
    output_dir: str,
    load_unified: Optional[Callable[..., Dict[str, float]]],
) -> Dict[str, float]:
    protein_fc: Dict[str, float] = {}
    if output_dir and callable(load_unified):
        protein_fc.update(load_unified(output_dir))
    for row in list(parsed_ptms) + list(enriched_data):
        gene = str(row.get("gene") or row.get("Gene.Name") or "").strip().upper()
        if not gene:
            continue
        raw = row.get("protein_log2fc")
        if raw is None:
            raw = row.get("Protein_Log2FC")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if gene not in protein_fc or abs(value) > abs(protein_fc[gene]):
            protein_fc[gene] = value
    return protein_fc


def run_pathway_expansion(
    parsed_ptms: Sequence[Mapping[str, Any]],
    enriched_data: Sequence[Mapping[str, Any]],
    network_data: Mapping[str, Any],
    output_dir: str,
    load_unified: Optional[Callable[..., Dict[str, float]]],
) -> PathwayExpansionResult:
    protein_fc = collect_protein_log2fc(parsed_ptms, enriched_data, output_dir, load_unified)
    result = score_pathways(parsed_ptms, enriched_data, network_data or {}, protein_fc)
    if output_dir:
        path = Path(output_dir) / "pathway_expansion.json"
        try:
            path.write_text(json.dumps(result.to_payload(), indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("[PATHWAY-EXP] Could not write %s: %s", path, exc)
    logger.info(
        "[PATHWAY-EXP] Direct NES scored %s pathways (universe=%s, timepoints=%s)",
        len(result.summaries),
        result.universe_size,
        result.timepoints,
    )
    return result


def display_summaries(result: PathwayExpansionResult, *, limit: int = 25) -> List[PathwaySummary]:
    rows = [s for s in result.summaries if not is_disease_pathway(s.pathway)]
    rows = [s for s in rows if s.peak_nes is not None or s.n_direct >= 2]
    return rows[:limit]


def build_pathway_candidates(
    parsed_ptms: list,
    enriched_data: list,
    network_data: dict,
    output_dir: str,
    expansion: Optional[PathwayExpansionResult] = None,
    load_unified: Optional[Callable[..., Dict[str, float]]] = None,
) -> dict:
    """Cascade mediator용 후보. 1차 순위는 Direct NES.

    template 키는 배치 메타데이터로만 남긴다. 점수에 넣지 않는다.
    """
    if expansion is None:
        expansion = run_pathway_expansion(
            parsed_ptms, enriched_data, network_data, output_dir, load_unified
        )

    try:
        from .signaling_cascade import _match_pathway_to_template
    except ImportError:
        try:
            from report_generation.core.nodes.signaling_cascade import _match_pathway_to_template
        except ImportError:
            _match_pathway_to_template = lambda _name: None  # noqa: E731

    gene_info: Dict[str, dict] = {}
    raw_nodes = network_data.get("nodes", {})
    node_list = list(raw_nodes.values()) if isinstance(raw_nodes, dict) else (raw_nodes or [])
    for node in node_list:
        if not isinstance(node, dict):
            continue
        gene = str(node.get("gene") or node.get("id") or "").strip().upper()
        if not gene:
            continue
        fc = node.get("ptm_log2fc") or node.get("value") or 0.0
        gene_info[gene] = {
            "fc": fc,
            "protein_log2fc": node.get("protein_log2fc") or 0.0,
            "type": node.get("type", "Non-PTM"),
            "site": node.get("site", ""),
            "gene": node.get("gene", gene),
        }

    candidates = []
    for summary in expansion.summaries:
        if is_disease_pathway(summary.pathway):
            continue
        peak_nes = summary.peak_nes
        candidates.append({
            "name": summary.pathway,
            "composite_score": peak_nes if peak_nes is not None else float("-inf"),
            "peak_nes": peak_nes,
            "peak_q": summary.peak_q,
            "peak_timepoint": summary.peak_timepoint,
            "genes": list(summary.direct_genes),
            "gene_count": summary.n_direct,
            "protein_support": summary.protein_support_peak,
            "network_support": summary.network_support_peak,
            "coherence": summary.coherence,
            "term": summary.term,
            "denovo_support_count": summary.denovo_support_count,
            "high_confidence_denovo_count": summary.high_confidence_denovo_count,
            "fc_score": summary.protein_support_peak,
            "diversity": 0,
            "template": _match_pathway_to_template(summary.pathway),
        })

    candidates.sort(key=lambda c: (
        c["peak_nes"] is None,
        -(c["peak_nes"] if c["peak_nes"] is not None else float("-inf")),
        -(c["gene_count"]),
        c["name"],
    ))
    logger.info(
        "[PATHWAY-EXP] Built %s NES-ranked candidates (top: %s)",
        len(candidates),
        candidates[0]["name"] if candidates else "none",
    )
    return {
        "candidates": candidates,
        "gene_data": gene_info,
        "expansion": expansion.to_payload(),
    }


def generate_pathway_distribution_graph(
    parsed_ptms: list,
    enriched_data: list,
    network_data: dict,
    output_dir: str,
    expansion: Optional[PathwayExpansionResult] = None,
    load_unified: Optional[Callable[..., Dict[str, float]]] = None,
) -> Tuple[Optional[str], List[str], Optional[Dict[str, Any]]]:
    """Direct NES 막대. STRING Σ|FC|를 같은 축에 놓지 않는다."""
    if expansion is None:
        expansion = run_pathway_expansion(
            parsed_ptms, enriched_data, network_data, output_dir, load_unified
        )
    payload = expansion.to_payload()
    rows = display_summaries(expansion)
    if not rows:
        logger.warning("[PATHWAY-EXP] No Direct NES pathways — skipping Figure 1")
        return None, [], payload

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not available — skipping pathway NES graph")
        return None, [s.pathway for s in rows], payload

    plot_rows = list(reversed(rows))
    fig, ax = plt.subplots(figsize=(18, max(7, len(plot_rows) * 0.55)))
    y_pos = np.arange(len(plot_rows))
    values = [s.peak_nes if s.peak_nes is not None else 0.0 for s in plot_rows]
    colors = [_TERM_COLOR.get(s.term, "#7F8C8D") for s in plot_rows]
    bars = ax.barh(y_pos, values, color=colors, alpha=0.88, edgecolor="white", linewidth=0.5)
    ax.axvline(0.0, color="#2C3E50", linewidth=0.8)

    labels = []
    for summary in plot_rows:
        name = summary.pathway
        if len(name) > 72:
            name = name[:69] + "..."
        peak = f" @ {summary.peak_timepoint}" if summary.peak_timepoint else ""
        labels.append(f"{name}{peak}")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Direct NES (signed, peak timepoint)", fontsize=11, fontweight="bold")
    ax.set_title(FIG1_TITLE, fontsize=13, fontweight="bold", pad=15)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", alpha=0.3, linestyle="--")

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=color, label=term)
        for term, color in _TERM_COLOR.items()
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.9, title="Term")

    span = max(abs(v) for v in values) if values else 1.0
    offset = span * 0.02 + 0.05
    for bar, summary, value in zip(bars, plot_rows, values):
        q_txt = f"q={summary.peak_q:.3f}" if summary.peak_q is not None else "q=NA"
        coh = f"{summary.coherence:.2f}" if summary.coherence is not None else "NA"
        note = (
            f"{value:.2f}  {q_txt}  n={summary.n_direct}  "
            f"dn={summary.denovo_support_count}/{summary.high_confidence_denovo_count}  "
            f"prot={summary.protein_support_peak:.2f}  "
            f"net={summary.network_support_peak:.2f}  coh={coh}"
        )
        x = value + offset if value >= 0 else value - offset
        ha = "left" if value >= 0 else "right"
        ax.text(
            x,
            bar.get_y() + bar.get_height() / 2,
            note,
            va="center",
            ha=ha,
            fontsize=6.5,
            color="#2C3E50",
        )

    plt.tight_layout()
    output_path = Path(output_dir) / "pathway_distribution.png"
    fig.savefig(str(output_path), dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    fig1_names = [s.pathway for s in rows]
    logger.info(
        "[PATHWAY-EXP] Figure 1 saved: %s (%s pathways, top NES=%s)",
        output_path,
        len(rows),
        rows[0].peak_nes if rows else None,
    )
    return str(output_path), fig1_names, payload
