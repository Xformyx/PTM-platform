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

    # Load comprehensive MD report if available
    comprehensive_summary = ""
    md_path = state.get("md_report_path")
    if md_path and Path(md_path).exists():
        comprehensive_summary = _extract_md_summary(md_path)
        logger.info(f"Loaded comprehensive report summary ({len(comprehensive_summary)} chars) from {md_path}")
    else:
        output_dir_path = Path(output_dir)
        md_candidates = list(output_dir_path.glob("comprehensive_report_*.md"))
        if md_candidates:
            comprehensive_summary = _extract_md_summary(str(md_candidates[0]))
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

    return {
        "parsed_ptms": parsed_ptms,
        "enriched_ptm_data": enriched_data,
        "research_questions": questions,
        "comprehensive_summary": comprehensive_summary,
    }


def _parse_enriched_ptms(enriched_data: list) -> list:
    """Normalize enriched PTM data into consistent dicts."""
    parsed = []
    for ptm in enriched_data:
        parsed.append({
            "gene": ptm.get("gene") or ptm.get("Gene.Name", "Unknown"),
            "position": ptm.get("position") or ptm.get("PTM_Position", "Unknown"),
            "ptm_type": ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation"),
            "protein_log2fc": _safe_float(ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC")),
            "ptm_relative_log2fc": _safe_float(ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC")),
            "protein_id": ptm.get("protein_id") or ptm.get("Protein.Group", ""),
            "modified_sequence": ptm.get("Modified.Sequence", ""),
            "condition": ptm.get("Condition", ""),
            "rag_enrichment": ptm.get("rag_enrichment", {}),
        })
    return parsed


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
            f"What are the key signaling pathways activated by upregulated phosphorylation sites "
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


def _extract_md_summary(md_path: str, max_chars: int = 12000) -> str:
    """Extract key sections from comprehensive MD report for use in LLM prompts.

    Extracts a generous summary (up to 12000 chars) to provide rich context
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
                    # Allow up to 1500 chars per section (was 600)
                    summary_parts.append(f"## {current_section}\n{section_text[:1500]}")
            current_section = line[3:].strip()
            section_content = []
        elif line.startswith("### ") and len(summary_parts) < 20:
            section_content.append(line)
        elif current_section:
            section_content.append(line)

    if current_section and section_content:
        section_text = "\n".join(section_content).strip()
        if section_text and any(k in current_section.lower() for k in kept_sections):
            summary_parts.append(f"## {current_section}\n{section_text[:1500]}")

    result = "\n\n".join(summary_parts)
    if not result and lines:
        # Fallback: take first 200 lines instead of 80
        result = "\n".join(lines[:200])

    logger.info(f"Extracted MD summary: {len(result)} chars from {len(summary_parts)} sections")
    return result[:max_chars]
