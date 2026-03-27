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
    ptm_type: str  # v8.10: detected from data or experimental_context

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

    # v9.11: Temporal kinase cascade (multi-source annotation)
    temporal_kinase_cascade: dict           # timepoint_order, timepoint_kinase_map, cross-tp inferences
    temporal_kinase_cascade_llm_context: str  # structured text for LLM signaling interpretation

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

    # Cross-talk analysis (Phos x Ub)
    analysis_mode: str                         # "ptm_only" | "ptm_nonptm_network" | "cross_talk"
    secondary_results: dict                    # secondary PTM network_results
    secondary_ptm_type: str                    # e.g. "ubiquitylation"
    secondary_md_content: str                  # secondary comprehensive_report md
    secondary_tsv_path: str                    # secondary enriched TSV path
    primary_results: dict                      # alias for network_results (primary)
    primary_ptm_type: str                      # alias for ptm_type (primary)
    primary_md_content: str                    # alias for md_content (primary)
    primary_tsv_path: str                      # primary enriched TSV path
    crosstalk_data: dict                       # cross-talk analysis output
    crosstalk_report: str                      # cross-talk full report text
    cross_talk_data: dict                      # cross-talk data for DB storage
    report_file: str                           # final report file path
    collection_names: List[str]                # ChromaDB collection names

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


def kinase_annotation(state: ReportState) -> dict:
    """v9.11: Multi-source kinase annotation + temporal cascade for co-wave clusters."""
    from .nodes.kinase_annotation_node import run_kinase_annotation
    return run_kinase_annotation(state)


def cascade_mediator(state: ReportState) -> dict:
    """v7.0: Extract discussed pathways from LLM text and generate cascade diagrams."""
    from .nodes.cascade_mediator_node import run_cascade_mediator
    return run_cascade_mediator(state)


def crosstalk_analysis(state: ReportState) -> dict:
    """Run Cross-Talk (Phos x Ub) analysis pipeline."""
    from .nodes.crosstalk_node import run_crosstalk_analysis
    return run_crosstalk_analysis(state)


def drug_repositioning(state: ReportState) -> dict:
    """Run drug repositioning pipeline for extended reports."""
    from .nodes.drug_repositioning_node import run_drug_repositioning
    return run_drug_repositioning(state)


def generate_qa_report(state: ReportState) -> dict:
    """Generate Q&A format report from PTM data."""
    from .nodes.qa_report_node import run_qa_report_generation
    return run_qa_report_generation(state)


def _build_comovement_figure_section(comovement_figures: list, network_analysis: dict, ptm_type: str = "phosphorylation") -> tuple:
    """v8.7: Build the co-movement figure section for the report.

    Returns (main_section, supplementary_section, next_fig_num, next_supp_num).

    Figure ordering:
        Fig 1 = Canonical Pathway Distribution (from network_node, inserted separately)
        Fig 2 = Transient Burst Composite (Nature-style, panels a/b/c)
        Fig 3-6 = Top 4 non-burst cluster time-series plots
        Supplementary = Heatmap + remaining cluster plots
    """
    from pathlib import Path

    if not comovement_figures:
        return "", "", 2, 1

    # Separate figure types
    burst_figs = [f for f in comovement_figures if f.get("type") == "transient_burst_composite"]
    cluster_figs = [f for f in comovement_figures if f.get("type") == "cluster_detail"]
    supp_cluster_figs = [f for f in comovement_figures if f.get("type") == "supplementary_cluster"]
    heatmap_figs = [f for f in comovement_figures if f.get("type") in ("heatmap", "supplementary_heatmap")]

    # ── Main Figures Section ──
    main_section = "\n## Temporal PTM Co-movement Analysis\n\n"
    main_section += (
        "The following figures show the results of temporal co-movement clustering analysis. "
        "PTM sites with correlated temporal dynamics were grouped into clusters using "
        "hierarchical clustering of their Log2FC time-series profiles. "
        "Co-moving PTMs within the same cluster suggest coordinated regulation, "
        f"potentially sharing upstream {'E3 ligases' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinases'} or participating in the same signaling cascade.\n\n"
    )

    fig_num = 2  # Fig 1 is Canonical Pathway from network_node

    # Figure 2: Transient Burst Composite
    for cf in burst_figs:
        img_ref = _resolve_figure_path(cf, Path)
        if img_ref:
            cf_caption = cf.get("caption", "Transient Burst Dynamics")
            main_section += f"### Figure {fig_num}. {cf_caption}\n\n"
            main_section += f"![{cf_caption}]({img_ref})\n\n"
            main_section += (
                f"**Legend:** Composite figure of transient {ptm_type} burst clusters. "
                "**(a)** Individual PTM time-series profiles colored by cluster membership; "
                "bold lines indicate cluster means with shaded min-max envelopes. "
                "**(b)** Peak amplitude profiles showing Log\u2082FC magnitude ranked by intensity. "
                "**(c)** Cluster mean temporal envelopes showing activation-recovery kinetics. "
                "Color palette: colorblind-safe scheme.\n\n"
            )
            main_section += "---\n\n"
            fig_num += 1
            logger.info(f"[COMOVEMENT] Inserted transient burst as Figure 2")

    # Figures 3-6: Main cluster detail plots
    for cf in cluster_figs:
        img_ref = _resolve_figure_path(cf, Path)
        cf_caption = cf.get("caption", "Cluster Detail")

        if img_ref:
            main_section += f"### Figure {fig_num}. {cf_caption}\n\n"
            main_section += f"![{cf_caption}]({img_ref})\n\n"
            main_section += (
                "**Legend:** Temporal Log\u2082FC profiles of cluster members. "
                "Solid lines = PTM proteins; dashed lines = linked Non-PTM interactors. "
                "Shaded area = cluster envelope (min-max range).\n\n"
            )
            main_section += "---\n\n"
            fig_num += 1
        else:
            logger.warning(f"[COMOVEMENT] Cluster figure not found: {cf.get('path')}")

    # ── Supplementary Figures (returned as list for later numbering) ──
    supp_items = []  # list of (caption, img_ref, legend_text)

    # Supplementary: Heatmap
    for cf in heatmap_figs:
        img_ref = _resolve_figure_path(cf, Path)
        cf_caption = cf.get("caption", "Co-movement Heatmap")
        if img_ref:
            supp_items.append((
                cf_caption, img_ref,
                "**Legend:** Hierarchical clustering heatmap of PTM temporal profiles. "
                "Rows = PTM sites, columns = time points. Color intensity reflects Log2FC magnitude. "
                "Cluster color bars on left sidebar indicate membership."
            ))

    # Supplementary: Additional cluster plots
    for cf in supp_cluster_figs:
        img_ref = _resolve_figure_path(cf, Path)
        cf_caption = cf.get("caption", "Cluster Detail")
        if img_ref:
            supp_items.append((
                cf_caption, img_ref,
                "**Legend:** Temporal Log\u2082FC profiles of cluster members. "
                "Solid lines = PTM proteins; dashed lines = linked Non-PTM interactors. "
                "Shaded area = cluster envelope (min-max range)."
            ))

    return main_section, supp_items, fig_num


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
    comovement_supp_items = []  # v8.7: collect supplementary items for end of report
    network_supp_section = ""  # v8.7: network supplementary (cascade/cytoscape)

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
            # v8.7: Figure ordering: Fig 1 (Pathway) → Fig 2-6 (Co-movement) → Supplementary at end
            # v9.4: When co-movement is absent (< 3 timepoints), promote cascade/cytoscape to main figures
            comovement_figures = state.get("comovement_figures", [])
            has_comovement = bool(comovement_figures)

            # Step 1: Network section (Fig 1 = Pathway; cascade/cytoscape = main or supp based on co-movement)
            net_main, net_supp = generate_network_figure_section(
                network_analysis,
                supplementary_start=1,
                ptm_type=state.get('ptm_type', 'phosphorylation'),
                has_comovement=has_comovement,
            )
            if net_main:
                parts.append(net_main)
                logger.info(f"[FORMAT-CIT] Added network main section ({len(net_main)} chars, has_comovement={has_comovement})")
            else:
                logger.warning("[FORMAT-CIT] network main section is EMPTY")
            network_supp_section = net_supp  # store for appending at end (empty when promoted to main)

            # Step 2: Co-movement MAIN figures (Fig 2 = Burst, Fig 3-6 = Clusters)
            if comovement_figures:
                result = _build_comovement_figure_section(comovement_figures, network_analysis, ptm_type=state.get('ptm_type', 'phosphorylation'))
                if result:
                    main_section, supp_items, _next_fig = result
                    if main_section:
                        parts.append(main_section)
                        logger.info(f"[FORMAT-CIT] Added co-movement main section ({len(main_section)} chars)")
                    comovement_supp_items = supp_items

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

    # v8.7: Append ALL supplementary figures at the very end
    supp_combined = "\n\n## Supplementary Figures\n\n"
    has_supp = False

    # Co-movement supplementary (heatmap, extra clusters)
    if comovement_supp_items:
        for si, (caption, img_ref, legend) in enumerate(comovement_supp_items, 1):
            supp_combined += f"### Supplementary Figure {si}. {caption}\n\n"
            supp_combined += f"![{caption}]({img_ref})\n\n"
            supp_combined += f"{legend}\n\n---\n\n"
        has_supp = True
        logger.info(f"[FORMAT-CIT] Collected {len(comovement_supp_items)} co-movement supplementary figures")

    # Network supplementary (cascade diagrams, cytoscape networks)
    # Re-number network supplementary figures to continue after comovement supp
    if network_supp_section:
        import re as _re_supp
        comovement_supp_count = len(comovement_supp_items) if comovement_supp_items else 0
        if comovement_supp_count > 0:
            # Offset all "Supplementary Figure N" in network_supp_section
            def _renumber_supp(match):
                old_num = match.group(1)
                # Handle panel suffixes like "1A", "1B"
                num_part = ''.join(c for c in old_num if c.isdigit())
                suffix = ''.join(c for c in old_num if not c.isdigit())
                new_num = int(num_part) + comovement_supp_count
                return f"Supplementary Figure {new_num}{suffix}"
            network_supp_section = _re_supp.sub(
                r'Supplementary Figure (\d+[A-Z]?)',
                _renumber_supp,
                network_supp_section
            )
        supp_combined += network_supp_section
        has_supp = True
        logger.info(f"[FORMAT-CIT] Collected network supplementary section ({len(network_supp_section)} chars), offset by {comovement_supp_count}")

    if has_supp:
        processed += supp_combined
        logger.info("[FORMAT-CIT] Appended all supplementary figures at end of report")

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

def _route_after_cascade(state: ReportState) -> str:
    """Route after cascade_mediator: if cross_talk mode, go to crosstalk_analysis; else continue."""
    mode = state.get("analysis_mode", "ptm_only")
    if mode == "cross_talk":
        logger.info("[GRAPH] Routing to crosstalk_analysis (cross_talk mode)")
        return "crosstalk_analysis"
    return "generate_qa_report"


def build_report_graph() -> StateGraph:
    """Build the LangGraph StateGraph for report generation.

    Flow (v9.11):
      Standard (ptm_only / ptm_nonptm_network):
        load_context → generate_questions → research → hypothesize
          → validate_hypotheses → network_analysis → temporal_comovement
          → kinase_annotation → write_sections → cascade_mediator
          → generate_qa_report → drug_repositioning → format_citations
          → edit_report

      Cross-Talk (cross_talk):
        load_context → generate_questions → research → hypothesize
          → validate_hypotheses → network_analysis → temporal_comovement
          → kinase_annotation → write_sections → cascade_mediator
          → crosstalk_analysis → generate_qa_report → drug_repositioning
          → format_citations → edit_report

    v9.11: kinase_annotation between temporal_comovement and write_sections.
    v9.0: crosstalk_analysis conditionally inserted after cascade_mediator
    when analysis_mode == "cross_talk".
    v8.0: temporal_comovement between network_analysis and write_sections.
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
    graph.add_node("kinase_annotation", kinase_annotation)
    graph.add_node("write_sections", write_sections)
    graph.add_node("cascade_mediator", cascade_mediator)
    graph.add_node("crosstalk_analysis", crosstalk_analysis)
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
    graph.add_edge("temporal_comovement", "kinase_annotation")
    graph.add_edge("kinase_annotation", "write_sections")
    graph.add_edge("write_sections", "cascade_mediator")

    # Conditional: cross_talk mode inserts crosstalk_analysis before qa_report
    graph.add_conditional_edges(
        "cascade_mediator",
        _route_after_cascade,
        {
            "crosstalk_analysis": "crosstalk_analysis",
            "generate_qa_report": "generate_qa_report",
        },
    )
    graph.add_edge("crosstalk_analysis", "generate_qa_report")

    graph.add_edge("generate_qa_report", "drug_repositioning")
    graph.add_edge("drug_repositioning", "format_citations")
    graph.add_edge("format_citations", "edit_report")
    graph.add_edge("edit_report", END)

    return graph.compile()
