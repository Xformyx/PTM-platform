"""
Editor Node — compiles sections into the final Markdown report.
Ported from multi_agent_system/agents/editor.py.

Assembles all sections, adds metadata, network figures, and references.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def run_editor(state: dict) -> dict:
    """Compile final report from generated sections or use pre-formatted report."""
    cb = state.get("progress_callback")
    if cb:
        cb(90, "Compiling final report")

    output_dir = state.get("output_dir", "/tmp")
    title = state.get("report_title", "PTM Comprehensive Analysis Report")

    network_analysis = state.get("network_analysis", {})

    # Use pre-formatted report from format_citations if available
    pre_formatted = state.get("final_report")
    if pre_formatted and isinstance(pre_formatted, str) and len(pre_formatted.strip()) > 100:
        report = pre_formatted
    else:
        sections = state.get("sections", {})
        hypotheses = state.get("validated_hypotheses", [])
        context = state.get("experimental_context", {})
        questions = state.get("research_questions", [])
        dr_results = state.get("drug_repositioning_results", {})
        collected_references = state.get("collected_references", [])
        report = _compile_report(title, sections, hypotheses, network_analysis, context, questions, dr_results, collected_references)

    # Save report
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_file = output_path / "final_report.md"
    report_file.write_text(report, encoding="utf-8")
    logger.info(f"Final report saved: {report_file}")

    report_files = [str(report_file)]

    # Copy network images to output
    for label, img_path in network_analysis.get("network_images", {}).items():
        if img_path and Path(img_path).exists():
            report_files.append(img_path)

    if cb:
        cb(100, "Report generation complete")

    return {
        "final_report": report,
        "report_files": report_files,
    }


def _compile_report(
    title: str, sections: dict, hypotheses: list,
    network: dict, context: dict, questions: list,
    dr_results: dict = None,
    collected_references: list = None,
) -> str:
    """Assemble all sections into a single Markdown report."""
    collected_references = collected_references or []
    lines = []

    # Title & metadata
    lines.append(f"# {title}\n")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

    # Experimental context
    if context:
        lines.append("## Experimental Context\n")
        for key in ("tissue", "organism", "treatment", "condition", "cell_type", "biological_question", "special_conditions"):
            val = context.get(key)
            if val:
                lines.append(f"- **{key.replace('_', ' ').title()}**: {val}")
        lines.append("")

    # Research questions
    if questions:
        lines.append("## Research Questions\n")
        for i, q in enumerate(questions, 1):
            lines.append(f"{i}. {q}")
        lines.append("")

    # Abstract
    abstract = sections.get("abstract", "")
    if abstract:
        lines.append("## Abstract\n")
        lines.append(abstract)
        lines.append("")

    # Introduction
    intro = sections.get("introduction", "")
    if intro:
        lines.append("## Introduction\n")
        lines.append(intro)
        lines.append("")

    # Results
    results = sections.get("results", "")
    if results:
        lines.append("## Results\n")
        lines.append(results)
        lines.append("")

    # Network Analysis Figure
    network_images = network.get("network_images", {})
    legend = network.get("legends", {})
    if network_images or legend:
        lines.append("## Network Analysis\n")
        if network_images:
            for label, path in network_images.items():
                fname = Path(path).name if path else ""
                lines.append(f"![PTM Signaling Network — {label}]({fname})\n")
        full_legend = legend.get("full_legend", "")
        if full_legend:
            lines.append(full_legend)
        lines.append("")

    # Discussion
    discussion = sections.get("discussion", "")
    if discussion:
        lines.append("## Discussion\n")
        lines.append(discussion)
        lines.append("")

    # Hypotheses summary
    if hypotheses:
        lines.append("## Hypotheses\n")
        lines.append("| ID | Condition | Prediction | Confidence | Status |")
        lines.append("|-----|-----------|------------|------------|--------|")
        for h in hypotheses:
            cond = h.get("condition", "")[:60]
            pred = h.get("prediction", "")[:60]
            conf = h.get("confidence", 0)
            status = h.get("status", "generated")
            lines.append(f"| {h.get('id', '?')} | {cond} | {pred} | {conf:.2f} | {status} |")
        lines.append("")

    # Conclusion
    conclusion = sections.get("conclusion", "")
    if conclusion:
        lines.append("## Conclusion\n")
        lines.append(conclusion)
        lines.append("")

    # Drug Repositioning (Extended Report)
    if dr_results and dr_results.get("success") and dr_results.get("report_sections"):
        lines.append("---\n")
        lines.append("# Part II: Drug Repositioning Analysis\n")
        lines.append(dr_results["report_sections"])
        lines.append("")

    # References
    if collected_references:
        lines.append("## References\n")
        for idx, ref in enumerate(collected_references, 1):
            pmid = ref.get("pmid", "")
            title_str = ref.get("title", "Untitled")
            journal = ref.get("journal", "")
            pub_date = ref.get("pub_date", "")
            gene = ref.get("gene", "")

            ref_line = f"{idx}. {title_str}"
            if journal:
                ref_line += f" *{journal}*"
            if pub_date:
                ref_line += f" ({pub_date})."
            if pmid:
                ref_line += f" PMID: {pmid}."
            if gene:
                ref_line += f" [Related: {gene}]"
            lines.append(ref_line)
        lines.append("")

    # Methods note
    lines.append("## Methods\n")
    lines.append(
        "Post-translational modifications were identified using mass spectrometry-based proteomics. "
        "Data was processed through the PTM Analysis Platform preprocessing pipeline. "
        "Literature enrichment was performed using PubMed, UniProt, KEGG, and STRING-DB databases. "
        "Hypotheses were generated and validated against the literature using ChromaDB vector search. "
        "Report sections were written with LLM assistance and reviewed for scientific accuracy."
    )
    if network.get("cytoscape_connected"):
        lines.append(
            " Network visualizations were generated using Cytoscape with force-directed layout "
            "and exported at 300 DPI resolution."
        )
    lines.append("")

    # Footer
    lines.append("---\n")
    lines.append(f"*Report generated by PTM Analysis Platform v1.0*")

    return "\n".join(lines)
