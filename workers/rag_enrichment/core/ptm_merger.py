"""
PTM Multi-Condition Merger — merges per-condition PTM rows into unified entries.

When the same gene+position appears in multiple conditions (e.g., AF and mgAF),
this module consolidates them into a single PTM entry with multi-condition data,
enabling:
  - Summary tables that show all condition values side-by-side
  - Automatic trajectory generation from multi-condition data
  - Deduplicated individual PTM sections in the report
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def merge_multi_condition_ptms(enriched_ptms: List[dict], single_time_point: bool = False) -> List[dict]:
    """
    Merge enriched PTM entries that share the same gene+position.

    For each unique (gene, position) pair:
      - Keep the entry with the highest |PTM_Relative_Log2FC| as the primary
      - Attach all condition-specific data as 'condition_data' list
      - Auto-generate trajectory from multi-condition timepoints (skipped when single_time_point)
      - Merge enrichment data (articles, pathways, interactions) from all conditions

    When single_time_point=True, conditions are not treated as timepoints (no trajectory).

    Returns:
        List of merged PTM dicts, each with an added 'condition_data' field.
    """
    if not enriched_ptms:
        return []

    # Group by (gene, position)
    groups: Dict[Tuple[str, str], List[dict]] = {}
    for ptm in enriched_ptms:
        gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
        pos = ptm.get("position") or ptm.get("PTM_Position", "?")
        key = (str(gene), str(pos))
        groups.setdefault(key, []).append(ptm)

    merged = []
    for (gene, pos), entries in groups.items():
        if len(entries) == 1:
            # Single condition — just add condition_data wrapper
            entry = entries[0]
            cond = entry.get("Condition") or entry.get("condition", "")
            ptm_fc = _safe_float(entry.get("PTM_Relative_Log2FC") or entry.get("ptm_relative_log2fc"))
            prot_fc = _safe_float(entry.get("Protein_Log2FC") or entry.get("protein_log2fc"))
            entry["condition_data"] = [{
                "condition": cond,
                "ptm_relative_log2fc": ptm_fc,
                "protein_log2fc": prot_fc,
                "ptm_absolute_log2fc": _safe_float(entry.get("PTM_Absolute_Log2FC") or entry.get("ptm_absolute_log2fc")),
                "classification": entry.get("rag_enrichment", {}).get("classification", {}),
            }]
            merged.append(entry)
        else:
            # Multiple conditions — merge
            primary = _select_primary(entries)
            condition_data = []
            all_articles = {}
            all_pathways = {}
            all_interactions = {}
            all_diseases = set()

            for entry in entries:
                cond = entry.get("Condition") or entry.get("condition", "")
                ptm_fc = _safe_float(entry.get("PTM_Relative_Log2FC") or entry.get("ptm_relative_log2fc"))
                prot_fc = _safe_float(entry.get("Protein_Log2FC") or entry.get("protein_log2fc"))
                ptm_abs_fc = _safe_float(entry.get("PTM_Absolute_Log2FC") or entry.get("ptm_absolute_log2fc"))

                condition_data.append({
                    "condition": cond,
                    "ptm_relative_log2fc": ptm_fc,
                    "protein_log2fc": prot_fc,
                    "ptm_absolute_log2fc": ptm_abs_fc,
                    "classification": entry.get("rag_enrichment", {}).get("classification", {}),
                })

                # Merge enrichment data
                enr = entry.get("rag_enrichment", {})
                for a in enr.get("articles", []):
                    pmid = a.get("pmid", "")
                    if pmid and pmid not in all_articles:
                        all_articles[pmid] = a
                for pw in enr.get("pathways", []):
                    pw_name = pw.get("name", str(pw)) if isinstance(pw, dict) else str(pw)
                    if pw_name not in all_pathways:
                        all_pathways[pw_name] = pw
                for inter in enr.get("string_db", {}).get("interactions", []):
                    partner = inter.get("partner", "")
                    if partner and partner not in all_interactions:
                        all_interactions[partner] = inter
                for d in enr.get("diseases", []):
                    all_diseases.add(str(d) if not isinstance(d, str) else d)

            primary["condition_data"] = condition_data

            # Build trajectory from condition data (skip when single_time_point — no temporal grouping)
            trajectory = _build_trajectory_from_conditions(condition_data) if not single_time_point else {"timepoints": [], "trend": "unknown"}
            if trajectory["timepoints"]:
                primary.setdefault("rag_enrichment", {})["trajectory"] = trajectory

            # Merge enrichment collections (keep primary's enrichment as base)
            enr = primary.get("rag_enrichment", {})
            # Merge articles (deduplicated)
            existing_pmids = {a.get("pmid") for a in enr.get("articles", [])}
            for pmid, article in all_articles.items():
                if pmid not in existing_pmids:
                    enr.setdefault("articles", []).append(article)
            # Merge recent_findings similarly
            existing_rf_pmids = {a.get("pmid") for a in enr.get("recent_findings", [])}
            for pmid, article in all_articles.items():
                if pmid not in existing_rf_pmids:
                    enr.setdefault("recent_findings", []).append({
                        "pmid": article.get("pmid", ""),
                        "title": article.get("title", ""),
                        "journal": article.get("journal", ""),
                        "pub_date": article.get("pub_date", ""),
                        "relevance_score": article.get("relevance_score", 0),
                        "abstract_excerpt": (article.get("abstract") or "")[:300],
                        "abstract": article.get("abstract", ""),
                        "authors": article.get("authors", []),
                        "doi": article.get("doi", ""),
                    })
            # Merge diseases
            existing_diseases = set(str(d) for d in enr.get("diseases", []))
            for d in all_diseases:
                if d not in existing_diseases:
                    enr.setdefault("diseases", []).append(d)

            merged.append(primary)

    # Sort by max |PTM_Relative_Log2FC| descending
    def _sort_key(ptm):
        conds = ptm.get("condition_data", [])
        if conds:
            return max(abs(c.get("ptm_relative_log2fc", 0)) for c in conds)
        return abs(_safe_float(ptm.get("PTM_Relative_Log2FC") or ptm.get("ptm_relative_log2fc")))

    merged.sort(key=_sort_key, reverse=True)

    logger.info(
        f"PTM merger: {len(enriched_ptms)} rows → {len(merged)} unique PTMs "
        f"({len(enriched_ptms) - len(merged)} duplicates removed)"
    )
    return merged


def _select_primary(entries: List[dict]) -> dict:
    """Select the entry with the highest |PTM_Relative_Log2FC| as primary."""
    best = entries[0]
    best_fc = abs(_safe_float(best.get("PTM_Relative_Log2FC") or best.get("ptm_relative_log2fc")))
    for entry in entries[1:]:
        fc = abs(_safe_float(entry.get("PTM_Relative_Log2FC") or entry.get("ptm_relative_log2fc")))
        if fc > best_fc:
            best = entry
            best_fc = fc
    return best


def _build_trajectory_from_conditions(condition_data: List[dict]) -> dict:
    """Build trajectory data from multi-condition entries."""
    if len(condition_data) < 2:
        return {"timepoints": [], "trend": "unknown"}

    # Sort conditions alphabetically (they typically represent time points)
    sorted_conds = sorted(condition_data, key=lambda c: c.get("condition", ""))

    timepoints = []
    for cd in sorted_conds:
        cond = cd.get("condition", "")
        ptm_fc = cd.get("ptm_relative_log2fc", 0)
        prot_fc = cd.get("protein_log2fc", 0)
        cls = cd.get("classification", {})
        cls_label = cls.get("short_label", cls.get("level", ""))
        timepoints.append({
            "timeLabel": cond,
            "ptmLog2FC": ptm_fc,
            "proteinLog2FC": prot_fc,
            "classification": cls_label,
        })

    # Determine trend
    first_fc = timepoints[0]["ptmLog2FC"]
    last_fc = timepoints[-1]["ptmLog2FC"]
    peak_fc = max(tp["ptmLog2FC"] for tp in timepoints)
    trough_fc = min(tp["ptmLog2FC"] for tp in timepoints)

    if last_fc > first_fc + 0.5:
        trend = "increasing"
    elif last_fc < first_fc - 0.5:
        trend = "decreasing"
    elif peak_fc > first_fc + 1.0 and last_fc < peak_fc - 0.5:
        trend = "transient_peak"
    elif trough_fc < first_fc - 1.0 and last_fc > trough_fc + 0.5:
        trend = "transient_dip"
    else:
        trend = "stable"

    return {"timepoints": timepoints, "trend": trend}


def _safe_float(val) -> float:
    """Safely convert a value to float."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
