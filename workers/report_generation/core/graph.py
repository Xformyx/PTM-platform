"""
LangGraph StateGraph for PTM Report Generation.

Replaces the custom multi-agent orchestrator with a structured state graph.
Flow (v7.0):
  load_context → research → hypothesize → validate_hypotheses
    → network_analysis → write_sections → cascade_mediator → edit_report

Each node reads/writes to a shared TypedDict state.
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class ReportState(TypedDict, total=False):
    """Shared state flowing through the report generation graph."""

    # Inputs
    order_id: int
    enriched_ptm_data: List[dict]
    md_report_path: str
    tsv_data_path: str
    experimental_context: dict
    research_questions: List[str]
    chromadb_collections: List[str]
    output_dir: str

    # Configuration
    llm_provider: str
    llm_model: str
    report_title: str
    report_config: dict

    # Intermediate results
    comprehensive_summary: str
    ai_questions_metadata: List[dict]
    parsed_ptms: List[dict]
    research_results: List[dict]
    hypotheses: List[dict]
    validated_hypotheses: List[dict]
    network_analysis: dict
    network_results: dict
    pathway_candidates: dict          # v7.0: scored pathway candidates for mediator
    sections: Dict[str, str]
    collected_references: List[dict]
    cascade_diagrams: Dict[str, str]  # v7.0: condition → diagram path (from mediator)
    cascade_pathway_names: Dict[str, list]  # v7.0: condition → pathway names (from mediator)

    # v8.0: Temporal co-movement analysis
    comovement_analysis: dict              # clusters, singletons, summary
    comovement_figures: List[dict]         # [{path, caption, type}]
    comovement_llm_context: str            # structured text for LLM

    # Drug repositioning (extended report)
    report_type: str
    drug_repositioning_results: dict

    # Q&A Report
    qa_report: str
    qa_questions: List[dict]

    # Citation tracking
    citation_data: dict

    # Output
    final_report: str
    report_files: List[str]

    # Progress tracking
    progress_callback: Any
    error: Optional[str]


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------

def load_context(state: ReportState) -> dict:
    """Load enriched PTM data and prepare context for downstream nodes."""
    from .nodes.context_loader import run_context_loader
    return run_context_loader(state)


def generate_questions(state: ReportState) -> dict:
    """Generate AI research questions from PTM data and comprehensive report."""
    from .nodes.question_generator import run_question_generation
    return run_question_generation(state)


def research(state: ReportState) -> dict:
    """Analyze PTM data for each research question."""
    from .nodes.research_node import run_research
    return run_research(state)


def hypothesize(state: ReportState) -> dict:
    """Generate hypotheses from research findings."""
    from .nodes.hypothesis_node import run_hypothesis_generation
    return run_hypothesis_generation(state)


def validate_hypotheses(state: ReportState) -> dict:
    """Validate hypotheses against ChromaDB literature."""
    from .nodes.validation_node import run_validation
    return run_validation(state)


def network_analysis(state: ReportState) -> dict:
    """Analyze temporal networks and generate Cytoscape visualizations."""
    from .nodes.network_node import run_network_analysis
    return run_network_analysis(state)


def write_sections(state: ReportState) -> dict:
    """Write report sections using LLM."""
    from .nodes.writer_node import run_section_writing
    return run_section_writing(state)


def temporal_comovement(state: ReportState) -> dict:
    """v8.0: Detect co-moving PTM clusters and generate temporal analysis."""
    from .nodes.temporal_comovement_node import run_temporal_comovement
    return run_temporal_comovement(state)


def cascade_mediator(state: ReportState) -> dict:
    """v7.0: Extract discussed pathways from LLM text and generate cascade diagrams."""
    from .nodes.cascade_mediator_node import run_cascade_mediator
    return run_cascade_mediator(state)


def drug_repositioning(state: ReportState) -> dict:
    """Run drug repositioning pipeline for extended reports."""
    from .nodes.drug_repositioning_node import run_drug_repositioning
    return run_drug_repositioning(state)


def generate_qa_report(state: ReportState) -> dict:
    """Generate Q&A format report from PTM data."""
    from .nodes.qa_report_node import run_qa_report_generation
    return run_qa_report_generation(state)


def _build_comovement_figure_section(comovement_figures: list, network_analysis: dict) -> str:
    """v8.5: Build the co-movement figure section for the report.

    Figure ordering:
        Fig 1 = Canonical Pathway Distribution (from network_node, inserted separately)
        Fig 2 = Transient Burst Composite (Nature-style, panels a/b/c)
        Fig 3-6 = Individual cluster time-series plots
        Supplementary = Heatmap
    """
    import base64
    from pathlib import Path

    if not comovement_figures:
        return ""

    # Separate figure types
    burst_figs = [f for f in comovement_figures if f.get("type") == "transient_burst_composite"]
    cluster_figs = [f for f in comovement_figures if f.get("type") == "cluster_detail"]
    heatmap_figs = [f for f in comovement_figures if f.get("type") == "heatmap"]

    section = "\n## Temporal PTM Co-movement Analysis\n\n"
    section += (
        "The following figures show the results of temporal co-movement clustering analysis. "
        "PTM sites with correlated temporal dynamics were grouped into clusters using "
        "hierarchical clustering of their Log2FC time-series profiles. "
        "Co-moving PTMs within the same cluster suggest coordinated regulation, "
        "potentially sharing upstream kinases or participating in the same signaling cascade.\n\n"
    )

    # v8.5: Figure 2 = Transient Burst Composite (Fig 1 is Pathway from network_node)
    fig_num = 2

    for cf in burst_figs:
        img_ref = _resolve_figure_path(cf, Path)
        if img_ref:
            cf_caption = cf.get("caption", "Transient Burst Dynamics")
            section += f"### Figure {fig_num}. {cf_caption}\n\n"
            section += f"![{cf_caption}]({img_ref})\n\n"
            section += (
                "**Legend:** Nature-style composite figure of transient phosphorylation burst clusters. "
                "**(a)** Individual PTM time-series profiles colored by cluster membership; "
                "bold lines indicate cluster means with shaded min-max envelopes. "
                "**(b)** HPLC-style peak chromatogram showing Log\u2082FC amplitude ranked by magnitude. "
                "**(c)** Cluster mean temporal envelopes showing activation-recovery kinetics. "
                "Color palette: Nature Reviews-inspired colorblind-safe scheme.\n\n"
            )
            section += "---\n\n"
            fig_num += 1
            logger.info(f"[COMOVEMENT] Inserted transient burst as Figure 2")

    # v8.5: Figures 3-6+ = Individual cluster detail plots
    for cf in cluster_figs:
        img_ref = _resolve_figure_path(cf, Path)
        cf_caption = cf.get("caption", "Cluster Detail")

        if img_ref:
            section += f"### Figure {fig_num}. {cf_caption}\n\n"
            section += f"![{cf_caption}]({img_ref})\n\n"
            section += (
                "**Legend:** Temporal Log\u2082FC profiles of cluster members. "
                "Solid lines = PTM proteins; dashed lines = linked Non-PTM interactors. "
                "Shaded area = cluster envelope (min-max range).\n\n"
            )
            section += "---\n\n"
            fig_num += 1
        else:
            logger.warning(f"[COMOVEMENT] Cluster figure not found: {cf.get('path')}")

    # v8.5: Heatmap → Supplementary Figure
    supp_num = 1
    for cf in heatmap_figs:
        img_ref = _resolve_figure_path(cf, Path)
        cf_caption = cf.get("caption", "Co-movement Heatmap")

        if img_ref:
            section += f"### Supplementary Figure {supp_num}. {cf_caption}\n\n"
            section += f"![{cf_caption}]({img_ref})\n\n"
            section += (
                "**Legend:** Hierarchical clustering heatmap of PTM temporal profiles. "
                "Rows = PTM sites, columns = time points. Color intensity reflects Log2FC magnitude. "
                "Cluster color bars on left sidebar indicate membership.\n\n"
            )
            section += "---\n\n"
            supp_num += 1

    return section, fig_num, supp_num


def _resolve_figure_path(cf: dict, Path) -> str | None:
    """Resolve a figure dict to an image reference (filename or base64)."""
    import base64 as _b64
    cf_path = cf.get("path", "")
    path_obj = Path(cf_path) if cf_path else None
    if path_obj and path_obj.exists() and path_obj.stat().st_size > 1000:
        return path_obj.name
    elif path_obj and path_obj.exists():
        try:
            with open(path_obj, "rb") as f:
                b64 = _b64.b64encode(f.read()).decode()
            return f"data:image/png;base64,{b64}"
        except Exception:
            return None
    return None


def format_citations(state: ReportState) -> dict:
    """Format citations and generate reference list. Includes network figures (Cytoscape) between Results and Discussion.

    Fix v1.1: Convert collected_references (PubMed format from writer_node) into
    CitationFormatter-compatible format, and build a complete References section
    that maps LLM inline citations [N] back to the actual PubMed papers.
    """
    from .citation_formatter import CitationFormatter, Reference, ReportPostProcessor
    from .nodes.network_node import generate_network_figure_section
    logger.info("Formatting citations and post-processing report")

    sections = state.get("sections", {})
    collected_refs = state.get("collected_references", [])
    network_analysis = state.get("network_analysis", {})

    # v7.0: Inject cascade_mediator results into network_analysis for figure insertion.
    # The mediator generates cascade diagrams AFTER write_sections, storing them in state.
    cascade_diagrams = state.get("cascade_diagrams", {})
    cascade_pathway_names = state.get("cascade_pathway_names", {})
    if cascade_diagrams:
        logger.info(f"[FORMAT-CIT] Injecting mediator cascade diagrams: {list(cascade_diagrams.keys())}")
        if "combined" in cascade_diagrams:
            network_analysis["cascade_diagram_path"] = cascade_diagrams["combined"]
        else:
            network_analysis["cascade_diagram_paths"] = cascade_diagrams
        network_analysis["cascade_pathway_names"] = cascade_pathway_names

    # Build report: Title → Abstract → Introduction → Results → Network → Discussion → Conclusion
    # Title is rendered as # heading, other sections as ## headings
    title_text = sections.get("title", "").strip()
    report_title = state.get("report_title", "PTM Comprehensive Analysis Report")
    if not title_text:
        title_text = report_title
    logger.info(f"[FORMAT-CIT] Report title: {title_text}")

    from datetime import datetime as _dt
    header_parts = [
        f"# {title_text}\n",
        f"*Generated: {_dt.now().strftime('%Y-%m-%d %H:%M')}*\n",
    ]

    section_order = ["abstract", "introduction", "results", "discussion", "conclusion"]
    section_headings = {
        "abstract": "## Abstract",
        "introduction": "## Introduction",
        "results": "## Results",
        "discussion": "## Discussion",
        "conclusion": "## Conclusion",
    }
    parts = header_parts[:]

    logger.info(
        f"[FORMAT-CIT] sections keys: {list(sections.keys())}, "
        f"network_analysis keys: {list(network_analysis.keys()) if network_analysis else 'EMPTY'}"
    )
    if network_analysis:
        logger.info(
            f"[FORMAT-CIT] network_analysis.network_images: "
            f"{list(network_analysis.get('network_images', {}).keys()) if network_analysis.get('network_images') else 'EMPTY'}"
        )

    for key in section_order:
        if key in sections and sections[key]:
            heading = section_headings.get(key, f"## {key.capitalize()}")
            parts.append(f"{heading}\n")
            parts.append(sections[key])
            logger.info(f"[FORMAT-CIT] Added section: {key} ({len(sections[key])} chars)")
        if key == "results":
            # v8.0: Insert co-movement figures BEFORE network section
            comovement_figures = state.get("comovement_figures", [])
            last_main_fig = 1  # Fig 1 = Pathway (from network_node)
            supp_start = 1
            if comovement_figures:
                result = _build_comovement_figure_section(comovement_figures, network_analysis)
                if result:
                    if isinstance(result, tuple):
                        comovement_section, last_main_fig, supp_start = result
                    else:
                        comovement_section = result  # backward compat
                    if comovement_section:
                        parts.append(comovement_section)
                        logger.info(f"[FORMAT-CIT] Added co-movement section ({len(comovement_section)} chars), last_fig={last_main_fig}")
            # v8.5: Cascade/Cytoscape → Supplementary Figures
            network_section = generate_network_figure_section(network_analysis, supplementary_start=supp_start)
            if network_section:
                parts.append(network_section)
                logger.info(f"[FORMAT-CIT] Added network section ({len(network_section)} chars)")
            else:
                logger.warning("[FORMAT-CIT] network_section is EMPTY — not included in report")

    all_text = "\n\n".join(parts)

    # -----------------------------------------------------------------------
    # v1.1 Fix: Build References section directly from collected_references
    # instead of relying on CitationFormatter's auto-cite heuristic.
    #
    # The LLM writes inline citations [1], [2], ... that correspond to the
    # reference numbers provided in the prompt (PubMed Ref [N] and ChromaDB
    # Reference [N]).  We build a canonical reference list from
    # collected_references and emit a ## References section.
    # -----------------------------------------------------------------------
    import re as _re

    # v1.2 Fix: Normalize LLM citation formats to [N]
    # LLM sometimes writes [PubMed Ref 1] or [Reference 1] instead of [1]
    all_text = _re.sub(r'\[PubMed Ref\s*(\d+)\]', r'[\1]', all_text)
    all_text = _re.sub(r'\[Reference\s*(\d+)\]', r'[\1]', all_text)
    all_text = _re.sub(r'\[Ref\s*(\d+)\]', r'[\1]', all_text)
    all_text = _re.sub(r'\[ChromaDB Reference\s*(\d+)\]', r'[\1]', all_text)
    logger.info("[FORMAT-CIT] Normalized inline citation formats to [N]")

    # Discover which citation numbers the LLM actually used in the text
    cited_numbers = sorted(set(int(m) for m in _re.findall(r'\[(\d+)\]', all_text)))
    logger.info(f"[FORMAT-CIT] LLM inline citation numbers found: {cited_numbers[:20]}{'...' if len(cited_numbers) > 20 else ''} (total {len(cited_numbers)})")
    logger.info(f"[FORMAT-CIT] collected_references count: {len(collected_refs)}")

    # Build Reference objects from collected_references (PubMed papers)
    ref_objects: list = []
    for ref_dict in collected_refs:
        ref = Reference(
            authors=ref_dict.get("authors", ""),
            title=ref_dict.get("title", "Untitled"),
            journal=ref_dict.get("journal", ""),
            year=str(ref_dict.get("pub_date", ""))[:4],
            pmid=str(ref_dict.get("pmid", "")),
            doi=ref_dict.get("doi", ""),
        )
        ref_objects.append(ref)

    # Build the ## References section
    # Strategy: include all collected references so that every [N] the LLM
    # used has a matching entry.  References beyond what the LLM cited are
    # also included as supporting literature.
    ref_lines = ["## References\n"]
    for idx, ref in enumerate(ref_objects, 1):
        entry_parts = []
        if ref.authors:
            entry_parts.append(ref.authors.rstrip("."))
        if ref.title:
            entry_parts.append(f"{ref.title.rstrip('.')}.")
        journal_part = ""
        if ref.journal:
            journal_part = f"*{ref.journal}*"
        if ref.year:
            journal_part += f" ({ref.year})"
        if journal_part:
            entry_parts.append(journal_part.strip() + ".")
        links = []
        if ref.pmid:
            links.append(f"PMID: [{ref.pmid}](https://pubmed.ncbi.nlm.nih.gov/{ref.pmid}/)")
        if ref.doi:
            doi_url = ref.doi if ref.doi.startswith("http") else f"https://doi.org/{ref.doi}"
            links.append(f"DOI: [{ref.doi}]({doi_url})")
        line = f"{idx}. " + " ".join(entry_parts)
        if links:
            line += " " + " | ".join(links)
        ref_lines.append(line)

    reference_section = "\n".join(ref_lines) if ref_objects else ""
    logger.info(f"[FORMAT-CIT] Built reference section with {len(ref_objects)} entries")

    # Post-process the body text (heading normalization, dedup, table fixes)
    processor = ReportPostProcessor()
    processed = processor.process(all_text)

    # Append references
    if reference_section:
        processed += "\n\n" + reference_section

    return {
        "final_report": processed,
        "citation_data": {
            "total_references": len(ref_objects),
            "reference_section": reference_section,
        },
    }


def edit_report(state: ReportState) -> dict:
    """Compile and edit the final report."""
    from .nodes.editor_node import run_editor
    return run_editor(state)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_report_graph() -> StateGraph:
    """Build the LangGraph StateGraph for report generation.

    Flow (v8.0):
      load_context → generate_questions → research → hypothesize
        → validate_hypotheses → network_analysis → temporal_comovement
        → write_sections → cascade_mediator → generate_qa_report
        → drug_repositioning → format_citations → edit_report

    v8.0: temporal_comovement inserted between network_analysis and
    write_sections to detect co-moving PTM clusters and provide
    structured context for LLM section writing.
    v7.0: cascade_mediator after write_sections for content-driven diagrams.
    """
    graph = StateGraph(ReportState)

    graph.add_node("load_context", load_context)
    graph.add_node("generate_questions", generate_questions)
    graph.add_node("research", research)
    graph.add_node("hypothesize", hypothesize)
    graph.add_node("validate_hypotheses", validate_hypotheses)
    graph.add_node("network_analysis", network_analysis)
    graph.add_node("temporal_comovement", temporal_comovement)
    graph.add_node("write_sections", write_sections)
    graph.add_node("cascade_mediator", cascade_mediator)
    graph.add_node("generate_qa_report", generate_qa_report)
    graph.add_node("drug_repositioning", drug_repositioning)
    graph.add_node("format_citations", format_citations)
    graph.add_node("edit_report", edit_report)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "generate_questions")
    graph.add_edge("generate_questions", "research")
    graph.add_edge("research", "hypothesize")
    graph.add_edge("hypothesize", "validate_hypotheses")
    graph.add_edge("validate_hypotheses", "network_analysis")
    graph.add_edge("network_analysis", "temporal_comovement")
    graph.add_edge("temporal_comovement", "write_sections")
    graph.add_edge("write_sections", "cascade_mediator")
    graph.add_edge("cascade_mediator", "generate_qa_report")
    graph.add_edge("generate_qa_report", "drug_repositioning")
    graph.add_edge("drug_repositioning", "format_citations")
    graph.add_edge("format_citations", "edit_report")
    graph.add_edge("edit_report", END)

    return graph.compile()
