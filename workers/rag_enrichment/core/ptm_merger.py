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

from ptm_shared.site_form_provenance import (
    aggregate_site_form_trajectories,
    form_identity,
)

logger = logging.getLogger(__name__)


def collapse_ptm_rows_for_enrichment(
    ptm_rows: List[dict],
    single_time_point: bool = False,
) -> List[dict]:
    """Create one trajectory-preserving RAG work item per selected gene/site.

    The normalized vector TSV has one row per condition/timepoint.  RAG
    enrichment is site-level work: querying the same structured databases and
    literature once for every condition row is both redundant and obscures the
    PTM Selection Mode universe.  This helper keeps the row with the largest
    absolute relative PTM change as the representative while retaining every
    selected condition in ``condition_data`` and ``trajectory``.
    """
    if not ptm_rows:
        return []

    groups: Dict[Tuple[str, str], List[dict]] = {}
    for ptm in ptm_rows:
        gene = ptm.get("gene") or ptm.get("Gene.Name", "?")
        pos = ptm.get("position") or ptm.get("PTM_Position", "?")
        groups.setdefault((str(gene), str(pos)), []).append(ptm)

    collapsed: List[dict] = []
    for entries in groups.values():
        primary = dict(_select_primary(entries))
        condition_data = []
        for entry in entries:
            condition_data.append({
                "condition": entry.get("Condition") or entry.get("condition", ""),
                "ptm_relative_log2fc": _safe_float(
                    entry.get("PTM_Relative_Log2FC")
                    if entry.get("PTM_Relative_Log2FC") is not None
                    else entry.get("ptm_relative_log2fc")
                ),
                "protein_log2fc": _safe_float(
                    entry.get("Protein_Log2FC")
                    if entry.get("Protein_Log2FC") is not None
                    else entry.get("protein_log2fc")
                ),
                "ptm_absolute_log2fc": _safe_float(
                    entry.get("PTM_Absolute_Log2FC")
                    if entry.get("PTM_Absolute_Log2FC") is not None
                    else entry.get("ptm_absolute_log2fc")
                ),
                "q_value": entry.get("q_value"),
                "control_pseudocount_used": entry.get("Control_Pseudocount_Used"),
                "denovo_confidence": entry.get("DeNovo_Confidence") or entry.get("denovo_confidence"),
                "detection_control": entry.get("Detection_Control") or entry.get("detection_control"),
                "detection_treatment": entry.get("Detection_Treatment") or entry.get("detection_treatment"),
                "detection_pattern": entry.get("Detection_Pattern") or entry.get("detection_pattern"),
                "lod_relative_log2": _safe_float(entry.get("LOD_Relative_Log2") or entry.get("lod_relative_log2")),
                "normalized_log2_intensity": _safe_float(
                    entry.get("Normalized_Log2_Intensity") or entry.get("normalized_log2_intensity")
                ),
                "conventional_log2fc_na": entry.get("Conventional_Log2FC_NA") or entry.get("conventional_log2fc_na"),
                "ranking_score": _safe_float(entry.get("Ranking_Score") or entry.get("ranking_score")),
                "peak_condition": entry.get("Peak_Condition") or entry.get("peak_condition"),
                "onset_condition": entry.get("Onset_Condition") or entry.get("onset_condition"),
                "reliable_onset_condition": entry.get("Reliable_Onset_Condition") or entry.get("reliable_onset_condition"),
                "shared_peptide": entry.get("Shared_Peptide") or entry.get("shared_peptide"),
                "detection_n": entry.get("Detection_N") or entry.get("detection_n"),
                "detection_expected": entry.get("Detection_Expected") or entry.get("detection_expected"),
            })

        primary["condition_data"] = condition_data
        primary["rag_source_row_count"] = len(entries)
        first_cd = condition_data[0] if condition_data else {}
        primary.setdefault("denovo_confidence", first_cd.get("denovo_confidence") or primary.get("DeNovo_Confidence"))
        primary.setdefault("detection_control", first_cd.get("detection_control") or primary.get("Detection_Control"))
        primary.setdefault("detection_pattern", first_cd.get("detection_pattern") or primary.get("Detection_Pattern"))
        primary.setdefault("lod_relative_log2", first_cd.get("lod_relative_log2") or primary.get("LOD_Relative_Log2"))
        primary.setdefault("conventional_log2fc_na", first_cd.get("conventional_log2fc_na") or primary.get("Conventional_Log2FC_NA"))
        primary.setdefault("ranking_score", first_cd.get("ranking_score") or primary.get("Ranking_Score"))
        primary.setdefault("peak_condition", first_cd.get("peak_condition") or primary.get("Peak_Condition"))
        primary.setdefault("onset_condition", first_cd.get("onset_condition") or primary.get("Onset_Condition"))
        primary.setdefault("reliable_onset_condition", first_cd.get("reliable_onset_condition") or primary.get("Reliable_Onset_Condition"))
        primary.setdefault("shared_peptide", first_cd.get("shared_peptide") or primary.get("Shared_Peptide"))
        form_trajectories = _build_site_form_trajectories(entries, single_time_point)
        primary["site_form_trajectories"] = form_trajectories
        site_aggregate = aggregate_site_form_trajectories(form_trajectories)
        primary["site_aggregation"] = site_aggregate
        primary["trajectory"] = (
            _build_trajectory_from_timepoints(site_aggregate["timepoints"])
            if not single_time_point
            else {"timepoints": [], "trend": "unknown"}
        )
        collapsed.append(primary)

    collapsed.sort(key=_ranking_sort_key, reverse=True)
    logger.info(
        "RAG input collapse: %s selected condition rows -> %s unique PTM sites",
        len(ptm_rows), len(collapsed),
    )
    return collapsed


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
            # A pre-enrichment collapse already carries every selected condition
            # and a trajectory. Preserve it rather than replacing it with only
            # the representative row during the post-enrichment report merge.
            if entry.get("condition_data"):
                trajectory = entry.get("trajectory")
                if trajectory and trajectory.get("timepoints"):
                    entry.setdefault("rag_enrichment", {})["trajectory"] = trajectory
                merged.append(entry)
                continue
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

    merged.sort(key=_ranking_sort_key, reverse=True)

    logger.info(
        f"PTM merger: {len(enriched_ptms)} rows → {len(merged)} unique PTMs "
        f"({len(enriched_ptms) - len(merged)} duplicates removed)"
    )
    return merged


def _ranking_sort_key(ptm: dict) -> float:
    """Sort by contract ranking_score. De novo does not use |pseudo-Log2FC|."""
    score = _safe_float(ptm.get("Ranking_Score") if ptm.get("Ranking_Score") is not None else ptm.get("ranking_score"))
    if score:
        return score
    conds = ptm.get("condition_data") or []
    cond_scores = [
        _safe_float(c.get("ranking_score"))
        for c in conds
        if _safe_float(c.get("ranking_score"))
    ]
    if cond_scores:
        return max(cond_scores)
    is_denovo = bool(
        ptm.get("Conventional_Log2FC_NA")
        or ptm.get("conventional_log2fc_na")
        or ptm.get("Control_Pseudocount_Used")
        or ptm.get("control_pseudocount_used")
    )
    if is_denovo:
        return 0.0
    if conds:
        return max(abs(_safe_float(c.get("ptm_relative_log2fc"))) for c in conds)
    return abs(_safe_float(ptm.get("PTM_Relative_Log2FC") or ptm.get("ptm_relative_log2fc")))


def _select_primary(entries: List[dict]) -> dict:
    """Select the representative condition row by contract ranking, not |pseudo-Log2FC|.

    구현 대상: docs/de_novo_representation_contract_v1.md §7–§8
    사전등록: 2026-08-23. 탐색적.
    해석 한계: primary는 RAG 대표 행이다. 생물학적 peak가 아닐 수 있다.
    주장 금지: 이 선택을 정확한 fold-change 최댓값으로 서술하지 않는다.
    """
    peak_wanted = None
    for entry in entries:
        peak_wanted = entry.get("Peak_Condition") or entry.get("peak_condition") or peak_wanted
    if peak_wanted:
        for entry in entries:
            cond = entry.get("Condition") or entry.get("condition", "")
            if str(cond) == str(peak_wanted):
                return entry
    return max(entries, key=_ranking_sort_key)


def _build_site_form_trajectories(entries: List[dict], single_time_point: bool) -> List[dict]:
    """Preserve each modified sequence/charge trajectory before site aggregation."""
    grouped: Dict[str, List[dict]] = {}
    identities: Dict[str, dict] = {}
    for entry in entries:
        identity = form_identity(entry)
        key = identity["site_form_key"]
        grouped.setdefault(key, []).append(entry)
        identities[key] = identity

    forms: List[dict] = []
    for key in sorted(grouped):
        condition_data = []
        for entry in grouped[key]:
            condition_data.append({
                "condition": entry.get("Condition") or entry.get("condition", ""),
                "ptm_relative_log2fc": _safe_float(
                    entry.get("PTM_Relative_Log2FC")
                    if entry.get("PTM_Relative_Log2FC") is not None
                    else entry.get("ptm_relative_log2fc")
                ),
                "protein_log2fc": _safe_float(
                    entry.get("Protein_Log2FC")
                    if entry.get("Protein_Log2FC") is not None
                    else entry.get("protein_log2fc")
                ),
                "q_value": entry.get("q_value"),
                "control_pseudocount_used": entry.get("Control_Pseudocount_Used") or entry.get("control_pseudocount_used"),
                "conventional_log2fc_na": entry.get("Conventional_Log2FC_NA") or entry.get("conventional_log2fc_na"),
                "lod_relative_log2": _safe_float(entry.get("LOD_Relative_Log2") or entry.get("lod_relative_log2")),
                "detection_treatment": entry.get("Detection_Treatment") or entry.get("detection_treatment"),
            })
        forms.append({
            **identities[key],
            "trajectory": (
                _build_trajectory_from_conditions(condition_data)
                if not single_time_point
                else {"timepoints": [], "trend": "unknown"}
            ),
        })
    return forms


def _build_trajectory_from_conditions(condition_data: List[dict]) -> dict:
    """Build trajectory data from multi-condition entries.

    v4.0: Sort by extracted time value (not alphabetically) for correct
    temporal ordering (e.g., '2min' < '5min' < '1h' < '24h').
    """
    if len(condition_data) < 2:
        return {"timepoints": [], "trend": "unknown"}

    # Sort conditions by extracted time value (not alphabetically)
    sorted_conds = sorted(condition_data, key=lambda c: _extract_time_value(c.get("condition", "")))

    timepoints = []
    for cd in sorted_conds:
        cond = cd.get("condition", "")
        is_denovo = bool(cd.get("conventional_log2fc_na") or cd.get("control_pseudocount_used"))
        lod_rel = _safe_float(cd.get("lod_relative_log2"))
        ptm_fc = lod_rel if is_denovo else cd.get("ptm_relative_log2fc", 0)
        prot_fc = cd.get("protein_log2fc", 0)
        cls = cd.get("classification", {})
        cls_label = cls.get("short_label", cls.get("level", ""))
        timepoints.append({
            "timeLabel": cond,
            "ptmLog2FC": ptm_fc,
            "proteinLog2FC": prot_fc,
            "q_value": cd.get("q_value"),
            "classification": cls_label,
            "lodRelativeLog2": lod_rel if is_denovo else None,
            "conventionalLog2FCNA": is_denovo,
            "detection": cd.get("detection_treatment"),
        })

    return _build_trajectory_from_timepoints(timepoints)


def _build_trajectory_from_timepoints(timepoints: List[dict]) -> dict:
    """Attach the legacy trend label to a pre-sorted set of aggregated points."""
    if len(timepoints) < 2:
        return {"timepoints": list(timepoints), "trend": "unknown"}

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

    return {"timepoints": list(timepoints), "trend": trend}


def _extract_time_value(label: str) -> float:
    """Extract numeric time value from a condition/time label for sorting.

    Supports: '0h', '6h', '24h', '0min', '30min', '2min', '5min',
    and full condition strings like 'ECM_EPS_6h_vs_Control'.
    Returns value in minutes for consistent sorting.
    """
    import re
    if not label:
        return 0.0
    # Try hours first
    hour_match = re.search(r'(\d+(?:\.\d+)?)\s*h', label, re.IGNORECASE)
    if hour_match:
        return float(hour_match.group(1)) * 60.0
    # Try minutes
    min_match = re.search(r'(\d+(?:\.\d+)?)\s*min', label, re.IGNORECASE)
    if min_match:
        return float(min_match.group(1))
    # Try bare number
    num_match = re.search(r'(\d+(?:\.\d+)?)', label)
    if num_match:
        return float(num_match.group(1))
    return 0.0


def _safe_float(val) -> float:
    """Safely convert a value to float."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
