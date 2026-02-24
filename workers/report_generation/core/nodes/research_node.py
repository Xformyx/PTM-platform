"""
Research Node — analyzes PTM data for each research question.
Ported from multi_agent_system/agents/research_agent.py.

Identifies activated/inhibited PTMs, pathway enrichment, regulatory patterns,
and temporal dynamics per question.
"""

import logging
import re
from collections import Counter, defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)


def run_research(state: dict) -> dict:
    """Execute research analysis for all questions."""
    cb = state.get("progress_callback")
    if cb:
        cb(10, "Analyzing PTM data")

    questions = state.get("research_questions", [])
    parsed_ptms = state.get("parsed_ptms", [])
    results = []

    for i, question in enumerate(questions):
        if cb:
            pct = 10 + (i / max(len(questions), 1)) * 20
            cb(pct, f"Researching: {question[:60]}...")

        result = _analyze_question(question, parsed_ptms, state.get("experimental_context", {}))
        results.append(result)

    if cb:
        cb(30, f"Research complete: {len(results)} analyses")

    return {"research_results": results}


def _analyze_question(question: str, ptms: list, context: dict) -> dict:
    """Analyze PTM data for a specific research question."""
    keywords = _extract_keywords(question)
    relevant_ptms = _filter_relevant_ptms(ptms, keywords)

    if not relevant_ptms:
        relevant_ptms = ptms[:20]

    activated = [p for p in relevant_ptms if p["ptm_relative_log2fc"] > 0]
    inhibited = [p for p in relevant_ptms if p["ptm_relative_log2fc"] < 0]

    pathways = _analyze_pathway_enrichment(relevant_ptms)
    patterns = _analyze_regulatory_patterns(relevant_ptms)
    stats = _compute_statistics(relevant_ptms)

    return {
        "question": question,
        "keywords": keywords,
        "relevant_ptm_count": len(relevant_ptms),
        "activated": [_ptm_summary(p) for p in sorted(activated, key=lambda x: -x["ptm_relative_log2fc"])[:10]],
        "inhibited": [_ptm_summary(p) for p in sorted(inhibited, key=lambda x: x["ptm_relative_log2fc"])[:10]],
        "enriched_pathways": pathways,
        "regulatory_patterns": patterns,
        "statistics": stats,
        "confidence": min(1.0, len(relevant_ptms) / 10),
    }


def _extract_keywords(question: str) -> list:
    """Extract meaningful keywords from a research question."""
    stop_words = {
        "what", "are", "the", "key", "how", "do", "does", "is", "in", "by",
        "of", "to", "and", "or", "for", "from", "with", "this", "that", "a", "an",
    }
    words = re.findall(r"[A-Za-z0-9]+", question.lower())
    return [w for w in words if w not in stop_words and len(w) > 2]


def _filter_relevant_ptms(ptms: list, keywords: list) -> list:
    """Filter PTMs relevant to the question keywords."""
    relevant = []
    for ptm in ptms:
        enr = ptm.get("rag_enrichment", {})
        pathways_raw = enr.get("pathways", [])
        pathways_str = " ".join(
            p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in pathways_raw
        ).lower()
        diseases_raw = enr.get("diseases", [])
        diseases_str = " ".join(
            d.get("name", str(d)) if isinstance(d, dict) else str(d) for d in diseases_raw
        ).lower()
        text = " ".join([
            ptm.get("gene", ptm.get("Gene.Name", "")).lower(),
            ptm.get("ptm_type", ptm.get("PTM_Type", "")).lower(),
            pathways_str,
            diseases_str,
            enr.get("function_summary", "").lower(),
        ])
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            ptm["_relevance_score"] = score
            relevant.append(ptm)

    relevant.sort(key=lambda p: p.get("_relevance_score", 0), reverse=True)
    return relevant


def _analyze_pathway_enrichment(ptms: list) -> list:
    """Find enriched pathways across PTMs."""
    pathway_counts: Dict[str, int] = Counter()
    for ptm in ptms:
        for pw in ptm.get("rag_enrichment", {}).get("pathways", []):
            pathway_counts[pw] += 1

    return [
        {"pathway": pw, "count": cnt, "fraction": round(cnt / max(len(ptms), 1), 2)}
        for pw, cnt in pathway_counts.most_common(10)
        if cnt >= 2
    ]


def _analyze_regulatory_patterns(ptms: list) -> list:
    """Identify regulatory patterns from enriched data."""
    patterns = []
    upstream_counts = Counter()
    for ptm in ptms:
        reg = ptm.get("rag_enrichment", {}).get("regulation", {})
        for u in reg.get("upstream_regulators", []):
            upstream_counts[u] += 1

    for regulator, count in upstream_counts.most_common(5):
        if count >= 2:
            patterns.append({
                "type": "upstream_hub",
                "regulator": regulator,
                "target_count": count,
                "description": f"{regulator} regulates {count} PTM sites",
            })

    q1 = [p for p in ptms if p["ptm_relative_log2fc"] > 0 and p.get("protein_log2fc", 0) > 0]
    q2 = [p for p in ptms if p["ptm_relative_log2fc"] > 0 and p.get("protein_log2fc", 0) < 0]
    if len(q2) >= 2:
        patterns.append({
            "type": "active_ptm_regulation",
            "description": f"{len(q2)} sites show active PTM upregulation despite protein decrease (Q2)",
            "sites": [f"{p['gene']}-{p['position']}" for p in q2[:5]],
        })

    return patterns


def _compute_statistics(ptms: list) -> dict:
    fcs = [p["ptm_relative_log2fc"] for p in ptms if p["ptm_relative_log2fc"] != 0]
    if not fcs:
        return {}
    return {
        "total": len(ptms),
        "upregulated": sum(1 for f in fcs if f > 0),
        "downregulated": sum(1 for f in fcs if f < 0),
        "max_log2fc": round(max(fcs), 3),
        "min_log2fc": round(min(fcs), 3),
        "mean_log2fc": round(sum(fcs) / len(fcs), 3),
    }


def _ptm_summary(ptm: dict) -> dict:
    return {
        "gene": ptm["gene"],
        "position": ptm["position"],
        "ptm_type": ptm["ptm_type"],
        "ptm_relative_log2fc": round(ptm["ptm_relative_log2fc"], 3),
        "protein_log2fc": round(ptm.get("protein_log2fc", 0), 3),
        "pathways": ptm.get("rag_enrichment", {}).get("pathways", [])[:3],
    }
