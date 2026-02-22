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

    # Intermediate results
    comprehensive_summary: str
    ai_questions_metadata: List[dict]
    parsed_ptms: List[dict]
    research_results: List[dict]
    hypotheses: List[dict]
    validated_hypotheses: List[dict]
    network_analysis: dict
    sections: Dict[str, str]
    collected_references: List[dict]

    # Drug repositioning (extended report)
    report_type: str
    drug_repositioning_results: dict

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


def edit_report(state: ReportState) -> dict:
    """Compile and edit the final report."""
    from .nodes.editor_node import run_editor
    return run_editor(state)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_report_graph() -> StateGraph:
    """Build the LangGraph StateGraph for report generation."""
    graph = StateGraph(ReportState)

    graph.add_node("load_context", load_context)
    graph.add_node("generate_questions", generate_questions)
    graph.add_node("research", research)
    graph.add_node("hypothesize", hypothesize)
    graph.add_node("validate_hypotheses", validate_hypotheses)
    graph.add_node("network_analysis", network_analysis)
    graph.add_node("write_sections", write_sections)
    graph.add_node("drug_repositioning", drug_repositioning)
    graph.add_node("edit_report", edit_report)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "generate_questions")
    graph.add_edge("generate_questions", "research")
    graph.add_edge("research", "hypothesize")
    graph.add_edge("hypothesize", "validate_hypotheses")
    graph.add_edge("validate_hypotheses", "network_analysis")
    graph.add_edge("network_analysis", "write_sections")
    graph.add_edge("write_sections", "drug_repositioning")
    graph.add_edge("drug_repositioning", "edit_report")
    graph.add_edge("edit_report", END)

    return graph.compile()
