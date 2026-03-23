"""
Context Loader Node — loads enriched PTM data, MD reports, and TSV files.
Parses input data and prepares it for downstream graph nodes.
"""

import json
import logging
import re
from pathlib import Path
from typing import List

import pandas as pd

logger = logging.getLogger(__name__)


def run_context_loader(state: dict) -> dict:
    """Load and parse all input data for report generation."""
    cb = state.get("progress_callback")
    if cb:
        cb(2, "Loading enriched PTM data")

    output_dir = state.get("output_dir", "/tmp")
    enriched_data = state.get("enriched_ptm_data", [])

    # Load enriched JSON if path given instead of data
    if not enriched_data:
        enriched_path = state.get("enriched_json_path")
        if enriched_path and Path(enriched_path).exists():
            with open(enriched_path, "r") as f:
                enriched_data = json.load(f)
            logger.info(f"Loaded {len(enriched_data)} enriched PTMs from {enriched_path}")

    # Parse PTMs into structured format
    parsed_ptms = _parse_enriched_ptms(enriched_data)

    # Load report_config from state
    report_config = state.get("report_config", {})
    md_max_chars = report_config.get("md_summary_max_chars", 12000)
    section_limit = report_config.get("section_chars_limit", 1500)

    # Load comprehensive MD report if available
    comprehensive_summary = ""
    md_path = state.get("md_report_path")
    if md_path and Path(md_path).exists():
        comprehensive_summary = _extract_md_summary(md_path, max_chars=md_max_chars, section_limit=section_limit)
        logger.info(f"Loaded comprehensive report summary ({len(comprehensive_summary)} chars) from {md_path}")
    else:
        output_dir_path = Path(output_dir)
        md_candidates = list(output_dir_path.glob("comprehensive_report_*.md"))
        if md_candidates:
            comprehensive_summary = _extract_md_summary(str(md_candidates[0]), max_chars=md_max_chars, section_limit=section_limit)
            logger.info(f"Loaded comprehensive report summary ({len(comprehensive_summary)} chars) from {md_candidates[0]}")

    # Extract or use provided research questions
    questions = state.get("research_questions", [])
    context = state.get("experimental_context", {})
    biological_question = (context.get("biological_question") or "").strip()

    if not questions:
        if biological_question:
            questions = [biological_question]
            auto = _generate_default_questions(parsed_ptms, context)
            for q in auto:
                if q != biological_question and q not in questions:
                    questions.append(q)
        else:
            questions = _generate_default_questions(parsed_ptms, context)

    if cb:
        cb(5, f"Context loaded: {len(parsed_ptms)} PTMs, {len(questions)} questions")

    # Detect dominant ptm_type from parsed data (for downstream nodes)
    ptm_type_counts = {}
    for p in parsed_ptms:
        pt = p.get("ptm_type", "Phosphorylation").lower()
        ptm_type_counts[pt] = ptm_type_counts.get(pt, 0) + 1
    dominant_ptm_type = max(ptm_type_counts, key=ptm_type_counts.get) if ptm_type_counts else "phosphorylation"
    # Also check experimental_context override
    ptm_type_from_context = context.get("ptm_type", "").lower().strip()
    if ptm_type_from_context:
        dominant_ptm_type = ptm_type_from_context
    logger.info(f"Detected ptm_type: {dominant_ptm_type}")

    return {
        "parsed_ptms": parsed_ptms,
        "enriched_ptm_data": enriched_data,
        "research_questions": questions,
        "comprehensive_summary": comprehensive_summary,
        "ptm_type": dominant_ptm_type,
    }


def _parse_enriched_ptms(enriched_data: list) -> list:
    """Normalize enriched PTM data into consistent dicts.

    v4.0 additions:
      - Parses 'trajectory' from rag_enrichment (time-course data)
      - Parses 'condition_data' for multi-condition comparison
      - Parses 'classification' from rag_enrichment (8-category system)
    """
    parsed = []
    for ptm in enriched_data:
        enr = ptm.get("rag_enrichment", {})

        # Parse trajectory data (from ptm_merger or enrichment_pipeline)
        trajectory = _parse_trajectory(ptm, enr)

        # Parse condition_data (from ptm_merger)
        condition_data = ptm.get("condition_data", [])

        # Parse classification (8-category cell-signaling system)
        classification = enr.get("classification", {})

        parsed.append({
            "gene": ptm.get("gene") or ptm.get("Gene.Name", "Unknown"),
            "position": ptm.get("position") or ptm.get("PTM_Position", "Unknown"),
            "ptm_type": ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation"),
            "protein_log2fc": _safe_float(ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC")),
            "ptm_relative_log2fc": _safe_float(ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC")),
            "protein_id": ptm.get("protein_id") or ptm.get("Protein.Group", ""),
            "modified_sequence": ptm.get("Modified.Sequence", ""),
            "condition": ptm.get("Condition", ""),
            "rag_enrichment": enr,
            # v4.0 additions
            "trajectory": trajectory,
            "condition_data": condition_data,
            "classification": classification,
        })
    return parsed


def _parse_trajectory(ptm: dict, enr: dict) -> dict:
    """Parse and normalize trajectory data from enriched PTM entry.

    Trajectory can come from:
      1. ptm['trajectory'] — set by ptm_merger._build_trajectory_from_conditions()
      2. enr['trajectory'] — set by enrichment_pipeline._extract_trajectory()
      3. ptm['condition_data'] — auto-build from multi-condition data

    Timepoints are sorted by extracted time value (not alphabetically).
    """
    # Priority 1: Direct trajectory on PTM (from ptm_merger)
    traj = ptm.get("trajectory")
    if not traj or not isinstance(traj, dict):
        traj = enr.get("trajectory")
    if not traj or not isinstance(traj, dict):
        traj = {"timepoints": [], "trend": "unknown"}

    # If no timepoints but condition_data exists, auto-build
    if not traj.get("timepoints"):
        condition_data = ptm.get("condition_data", [])
        if len(condition_data) >= 2:
            traj = _build_trajectory_from_condition_data(condition_data)

    # Sort timepoints by extracted time value (not alphabetically)
    timepoints = traj.get("timepoints", [])
    if timepoints:
        traj["timepoints"] = sorted(
            timepoints, key=lambda tp: _extract_time_value(tp.get("timeLabel", ""))
        )

    return traj


def _build_trajectory_from_condition_data(condition_data: list) -> dict:
    """Build trajectory from condition_data when no pre-built trajectory exists.

    This is a fallback for cases where ptm_merger didn't generate trajectory
    (e.g., single_time_point=True was incorrectly set).
    """
    timepoints = []
    for cd in condition_data:
        cond = cd.get("condition", "")
        ptm_fc = _safe_float(cd.get("ptm_relative_log2fc"))
        prot_fc = _safe_float(cd.get("protein_log2fc"))
        cls = cd.get("classification", {})
        cls_label = cls.get("short_label", cls.get("level", ""))
        timepoints.append({
            "timeLabel": _extract_time_label(cond),
            "ptmLog2FC": ptm_fc,
            "proteinLog2FC": prot_fc,
            "classification": cls_label,
            "condition": cond,
        })

    # Sort by time value
    timepoints.sort(key=lambda tp: _extract_time_value(tp.get("timeLabel", "")))

    if len(timepoints) < 2:
        return {"timepoints": [], "trend": "unknown"}

    # Determine trend
    first_fc = timepoints[0]["ptmLog2FC"]
    last_fc = timepoints[-1]["ptmLog2FC"]
    peak_fc = max(tp["ptmLog2FC"] for tp in timepoints)
    trough_fc = min(tp["ptmLog2FC"] for tp in timepoints)

    if last_fc > first_fc + 0.5:
        trend = "increasing"
    elif last_fc < first_fc - 0.5:
        trend = "decreasing"
    elif len(timepoints) >= 3:
        # Check for oscillation / transient patterns
        if peak_fc > first_fc + 1.0 and last_fc < peak_fc - 0.5:
            trend = "transient_peak"
        elif trough_fc < first_fc - 1.0 and last_fc > trough_fc + 0.5:
            trend = "transient_dip"
        else:
            # Check for oscillation (middle points deviate from endpoints)
            mid_points = timepoints[1:-1]
            max_mid = max(tp["ptmLog2FC"] for tp in mid_points)
            min_mid = min(tp["ptmLog2FC"] for tp in mid_points)
            if max_mid > first_fc + 0.3 and max_mid > last_fc + 0.3:
                trend = "oscillating"
            elif min_mid < first_fc - 0.3 and min_mid < last_fc - 0.3:
                trend = "oscillating"
            else:
                trend = "stable"
    else:
        trend = "stable"

    return {"timepoints": timepoints, "trend": trend}


def _extract_time_value(label: str) -> float:
    """Extract numeric time value from a time label for sorting.

    Supports: '0h', '6h', '24h', '0min', '30min', '2min', '5min',
    and full condition strings like 'ECM_EPS_6h_vs_Control'.
    Ported from ptm-vector-ai/ragEnrichmentService.ts extractTimeValue().
    """
    if not label:
        return 0.0

    # Try hours first
    hour_match = re.search(r'(\d+(?:\.\d+)?)\s*h', label, re.IGNORECASE)
    if hour_match:
        return float(hour_match.group(1)) * 60.0  # Convert to minutes for consistent sorting

    # Try minutes
    min_match = re.search(r'(\d+(?:\.\d+)?)\s*min', label, re.IGNORECASE)
    if min_match:
        return float(min_match.group(1))

    # Try bare number
    num_match = re.search(r'(\d+(?:\.\d+)?)', label)
    if num_match:
        return float(num_match.group(1))

    return 0.0


def _extract_time_label(condition: str) -> str:
    """Extract time label from condition string.

    'ECM_EPS_0h_vs_Control' -> '0h'
    'ECM_EPS_6h' -> '6h'
    '2min' -> '2min'
    Ported from ptm-vector-ai/ragEnrichmentService.ts extractTimeLabel().
    """
    match = re.search(r'(\d+(?:\.\d+)?\s*(?:h|min))', condition, re.IGNORECASE)
    return match.group(1) if match else condition


def _safe_float(val) -> float:
    try:
        return float(val) if val is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def _generate_default_questions(ptms: list, context: dict) -> list:
    """Generate default research questions from PTM data and context."""
    questions = []
    biological_question = (context.get("biological_question") or "").strip()
    tissue = context.get("tissue", "") or context.get("cell_type", "")
    treatment = context.get("treatment", "")

    upregulated = [p for p in ptms if p["ptm_relative_log2fc"] > 0.5]
    downregulated = [p for p in ptms if p["ptm_relative_log2fc"] < -0.5]

    context_desc = ""
    if tissue:
        context_desc += f" in {tissue}"
    if treatment:
        context_desc += f" under {treatment}"

    if upregulated:
        top_genes = ", ".join(sorted(set(p["gene"] for p in upregulated[:5])))
        questions.append(
            f"What are the key signaling pathways activated by upregulated {context.get('ptm_type', 'phosphorylation')} sites "
            f"({top_genes}){context_desc}?"
        )

    if downregulated:
        top_genes = ", ".join(sorted(set(p["gene"] for p in downregulated[:5])))
        questions.append(
            f"What biological processes are affected by the downregulated PTM sites "
            f"({top_genes}){context_desc}?"
        )

    if upregulated and downregulated:
        questions.append(
            f"How do the opposing PTM changes coordinate to regulate cellular response{context_desc}?"
        )

    if not questions:
        questions.append("What are the key findings from this PTM analysis?")

    if biological_question and biological_question not in questions:
        questions.insert(0, biological_question)

    return questions


def _extract_md_summary(md_path: str, max_chars: int = 12000, section_limit: int = 1500) -> str:
    """Extract key sections from comprehensive MD report for use in LLM prompts.

    Extracts a generous summary (up to max_chars) to provide rich context
    for downstream LLM section writing.
    """
    try:
        text = Path(md_path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Cannot read MD report {md_path}: {e}")
        return ""

    lines = text.split("\n")
    summary_parts = []
    current_section = ""
    section_content: list = []
    # Expanded keyword set to capture more sections from the comprehensive report
    kept_sections = {
        "summary", "overview", "key findings", "significant", "regulation", "signaling",
        "pathway", "expression", "literature", "clinical", "disease", "interaction",
        "network", "kinase", "functional", "biological", "temporal", "time-course",
        "ptm-driven", "hyperactivation", "activation", "global", "individual",
        "drug", "therapeutic", "mechanism", "context", "interpretation",
    }

    for line in lines:
        if line.startswith("## "):
            if current_section and section_content:
                section_text = "\n".join(section_content).strip()
                if section_text and any(k in current_section.lower() for k in kept_sections):
                    summary_parts.append(f"## {current_section}\n{section_text[:section_limit]}")
            current_section = line[3:].strip()
            section_content = []
        elif line.startswith("### ") and len(summary_parts) < 20:
            section_content.append(line)
        elif current_section:
            section_content.append(line)

    if current_section and section_content:
        section_text = "\n".join(section_content).strip()
        if section_text and any(k in current_section.lower() for k in kept_sections):
            summary_parts.append(f"## {current_section}\n{section_text[:section_limit]}")

    result = "\n\n".join(summary_parts)
    if not result and lines:
        # Fallback: take first 200 lines instead of 80
        result = "\n".join(lines[:200])

    logger.info(f"Extracted MD summary: {len(result)} chars from {len(summary_parts)} sections")
    return result[:max_chars]
