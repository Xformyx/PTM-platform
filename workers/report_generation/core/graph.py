"""
LangGraph StateGraph for PTM Report Generation.

Replaces the custom multi-agent orchestrator with a structured state graph.
Flow:
  load_context → research → hypothesize → validate_hypotheses
    → network_analysis → write_sections → edit_report

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
    sections: Dict[str, str]
    collected_references: List[dict]

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


def drug_repositioning(state: ReportState) -> dict:
    """Run drug repositioning pipeline for extended reports."""
    from .nodes.drug_repositioning_node import run_drug_repositioning
    return run_drug_repositioning(state)


def generate_qa_report(state: ReportState) -> dict:
    """Generate Q&A format report from PTM data."""
    from .nodes.qa_report_node import run_qa_report_generation
    return run_qa_report_generation(state)


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

    # Build report with network section between Results and Discussion
    section_order = ["introduction", "results", "discussion", "conclusion", "abstract"]
    parts = []

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
            parts.append(sections[key])
            logger.info(f"[FORMAT-CIT] Added section: {key} ({len(sections[key])} chars)")
        if key == "results":
            network_section = generate_network_figure_section(network_analysis)
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

    Flow:
      load_context → generate_questions → research → hypothesize
        → validate_hypotheses → network_analysis → write_sections
        → generate_qa_report → drug_repositioning → format_citations
        → edit_report
    """
    graph = StateGraph(ReportState)

    graph.add_node("load_context", load_context)
    graph.add_node("generate_questions", generate_questions)
    graph.add_node("research", research)
    graph.add_node("hypothesize", hypothesize)
    graph.add_node("validate_hypotheses", validate_hypotheses)
    graph.add_node("network_analysis", network_analysis)
    graph.add_node("write_sections", write_sections)
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
    graph.add_edge("network_analysis", "write_sections")
    graph.add_edge("write_sections", "generate_qa_report")
    graph.add_edge("generate_qa_report", "drug_repositioning")
    graph.add_edge("drug_repositioning", "format_citations")
    graph.add_edge("format_citations", "edit_report")
    graph.add_edge("edit_report", END)

    return graph.compile()
