"""
Editor Node — compiles sections into the final Markdown report.
Ported from multi_agent_system/agents/editor.py.

Assembles all sections, adds metadata, network figures (Base64 embedded), and references.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from report_generation.core.nodes.network_node import generate_network_figure_section

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
    logger.info(
        f"[EDITOR] pre_formatted: type={type(pre_formatted).__name__}, "
        f"len={len(pre_formatted.strip()) if pre_formatted and isinstance(pre_formatted, str) else 0}, "
        f"has_network_viz={'## Network Visualization' in pre_formatted if pre_formatted else False}"
    )
    if pre_formatted and isinstance(pre_formatted, str) and len(pre_formatted.strip()) > 100:
        report = pre_formatted
        logger.info(f"[EDITOR] Using pre-formatted report ({len(report)} chars)")
    else:
        sections = state.get("sections", {})
        hypotheses = state.get("validated_hypotheses", [])
        context = state.get("experimental_context", {})
        questions = state.get("research_questions", [])
        dr_results = state.get("drug_repositioning_results", {})
        collected_references = state.get("collected_references", [])
        ptm_type = state.get("ptm_type", "phosphorylation")
        report = _compile_report(title, sections, hypotheses, network_analysis, context, questions, dr_results, collected_references, ptm_type=ptm_type)

    # Save report: [Order_name]_report_[YYMMDD_HHMM].md
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    order_code = output_path.name or "report"
    ts = datetime.now().strftime("%y%m%d_%H%M")
    report_base = f"{order_code}_report_{ts}"
    report_file = output_path / f"{report_base}.md"
    report_file.write_text(report, encoding="utf-8")
    logger.info(f"Final report saved: {report_file}")

    report_files = [str(report_file)]

    # Copy network images to output
    net_images = network_analysis.get("network_images", {})
    logger.info(f"[EDITOR] network_images to copy: {dict(net_images) if net_images else 'EMPTY'}")
    for label, img_path in net_images.items():
        if img_path and Path(img_path).exists():
            report_files.append(img_path)
            logger.info(f"[EDITOR] Network image added to report_files: {label} -> {img_path}")
        else:
            logger.warning(f"[EDITOR] Network image missing: {label} -> {img_path}")

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
    ptm_type: str = "phosphorylation",
) -> str:
    """Assemble all sections into a single Markdown report."""
    collected_references = collected_references or []
    lines = []

    # ═══════════════════════════════════════════════════════════════════════
    # v10.1: Revised report structure (academic standard)
    #   Title → Abstract → Introduction → Methods → Results → Network Figures
    #   → Discussion (incl. Hypotheses) → Conclusion → Drug Repositioning
    #   → Suggested Validation Experiments → References
    # ═══════════════════════════════════════════════════════════════════════

    # Title — use LLM-generated title if available, otherwise fallback to report_title
    llm_title = sections.get("title", "").strip()
    final_title = llm_title if llm_title else title
    lines.append(f"# {final_title}\n")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

    # ── Abstract ──
    abstract = sections.get("abstract", "")
    if abstract:
        lines.append("## Abstract\n")
        lines.append(abstract)
        lines.append("")

    # ── Introduction ──
    intro = sections.get("introduction", "")
    if intro:
        lines.append("## Introduction\n")
        lines.append(intro)
        lines.append("")

    # ── Methods (moved before Results — academic standard) ──
    methods = sections.get("methods", "")
    if methods:
        lines.append("## Methods\n")
        lines.append(methods)
        lines.append("")
    else:
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

    # ── Results ──
    results = sections.get("results", "")
    if results:
        lines.append("## Results\n")
        lines.append(results)
        lines.append("")

    # ── Network Analysis Figures ──
    network_figure_section = generate_network_figure_section(network, ptm_type=ptm_type)
    if network_figure_section:
        lines.append(network_figure_section)
    else:
        # Fallback: file-referenced images + text legend
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

    # ── Discussion ──
    discussion = sections.get("discussion", "")
    if discussion:
        lines.append("## Discussion\n")
        lines.append(discussion)
        lines.append("")

    # ── Hypotheses (as subsection after Discussion) ──
    if hypotheses:
        lines.append("### Generated Hypotheses\n")
        lines.append("| ID | Condition | Prediction | Confidence | Status |")
        lines.append("|-----|-----------|------------|------------|--------|")
        for h in hypotheses:
            cond = h.get("condition", "")[:60]
            pred = h.get("prediction", "")[:60]
            conf = h.get("confidence", 0)
            status = h.get("status", "generated")
            lines.append(f"| {h.get('id', '?')} | {cond} | {pred} | {conf:.2f} | {status} |")
        lines.append("")

    # ── Conclusion ──
    conclusion = sections.get("conclusion", "")
    if conclusion:
        lines.append("## Conclusion\n")
        lines.append(conclusion)
        lines.append("")

    # ── Drug Repositioning (Extended Report) ──
    if dr_results and dr_results.get("success") and dr_results.get("report_sections"):
        lines.append("---\n")
        lines.append("## Drug Repositioning Analysis\n")
        lines.append(dr_results["report_sections"])
        lines.append("")

    # ── Suggested Validation Experiments ──
    suggestion = sections.get("suggestion", "")
    if suggestion:
        lines.append("## Suggested Validation Experiments\n")
        lines.append(suggestion)
        lines.append("")

    # P2/P3: These deterministic appendices remain separate from discovery
    # Results/Discussion so a proposed or condition-scoped intervention cannot
    # be mistaken for an observed causal conclusion.
    causal_validation = sections.get("causal_validation_recommendations", "")
    if causal_validation:
        lines.append("## Post-Analysis Causal Validation Recommendations\n")
        lines.append(causal_validation)
        lines.append("")

    perturbation_evidence = sections.get("perturbation_evidence", "")
    if perturbation_evidence:
        lines.append("## User-Uploaded Perturbation Evidence\n")
        lines.append(perturbation_evidence)
        lines.append("")

    # ── References ──
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

    # Footer
    lines.append("---\n")
    lines.append(f"*Report generated by PTM Analysis Platform v10.1*")

    return "\n".join(lines)
