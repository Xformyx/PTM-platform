"""
LangGraph StateGraph for PTM Report Generation.

Replaces the custom multi-agent orchestrator with a structured state graph.
Flow (19 nodes):
  load_context → generate_questions → research → hypothesize → validate_hypotheses
    → data_verification → network_analysis → temporal_comovement → kinase_annotation
    → rq_refinement → external_coscientist_context → write_sections → report_copilot
    → cascade_mediator → [crosstalk_analysis →] generate_qa_report → drug_repositioning
    → format_citations → edit_report

Each node reads/writes to a shared TypedDict state.
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from common.temporal_utils import condition_sort_key

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

    # v9.13: Global Kinase Modules (kinase-centric, all PTMs)
    global_kinase_modules: dict             # kinase_modules, temporal_cascade, summary (auto-built in pipeline)
    frontend_kinase_analysis: dict          # pre-computed result from DB (optional, skips recomputation)
    temporal_ptm_protein_analysis: dict     # shared production/benchmark temporal sidecar summary; observational only
    temporal_report_evidence_packet: dict  # deterministic Report LLM evidence packet derived from the shared sidecar
    temporal_report_fidelity: dict         # per-section traceability/claim-boundary audit before internal DATA labels are stripped

    # v9.14: Ubiquitylation Analysis Suite (auto-built when ptm_type == 'ubiquitylation')
    ubi_chain_classifications: dict         # Module 1: per-site chain type classification
    ubi_e3_modules: dict                    # Module 2: E3 ligase-centric substrate modules (RING/HECT/RBR)
    ubi_temporal_cascade: dict              # Module 3: Phospho-Ub cross-talk, DUB inference, degradation timeline

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

    # v9.20: Inferred upstream receptors (from vector-plot-data analysis, stored in DB)
    # List of {name, receptor_class, downstream_ptm_count, downstream_ptms, via_kinases, source, ...}
    inferred_receptors: List[dict]
    # v9.33: Signal Flow figures (generated by kinase_annotation_node)
    signal_flow_figures: List[dict]  # [{path, caption, type}]

    # v9.35: LLM fallback tracking
    llm_fallback_sections: List[str]  # sections that used fallback text due to LLM failure

    # v9.48: Kinase Activity Heatmap (CW Groups, per-condition scores, peak sync)
    kinase_activity_heatmap: dict  # {kinase_scores, conditions, peak_sync, cowave_groups}
    signal_propagation_data: dict  # signal propagation analysis from frontend
    substrate_go_localization: dict  # GO cellular-component annotations for Atlas evidence
    atlas_claim_ledger: dict  # shared observational claims for Atlas and integrated report
    atlas_claim_ledger_llm_context: str  # bounded writer context derived from the shared ledger
    atlas_report_path: str  # deterministic standalone Atlas rendered from the shared ledger
    atlas_report_markdown: str

    # v10.0: RQ Refinement + Report Co-pilot
    original_research_questions: List[str]  # preserved user RQ0 before refinement
    rq_refinement_metadata: dict            # LLM refinement diagnostics
    copilot_review: dict                    # report co-pilot review output

    # v10.1: Full vector plot raw data (all PTM + Non-PTM protein FC per condition)
    vector_plot_raw_data: List[dict]  # [{gene, position, condition, ptm_relative_log2fc, protein_log2fc}]
    # v10.1: Pipeline statistics for Methods section
    pipeline_statistics: dict  # {step1_input, step2_quantification, ...}
    # v10.7: Ubiquitin chain linkage analysis (ubi mode only)
    ubiquitin_linkage_data: dict  # {detected, linkage_data, temporal_ratios, summary, chart_data}
    # v11.8: TF Activity Inference from non-PTM protein dynamics
    tf_inference_data: dict  # {inferred_tfs, cross_validated, novel_findings, summary}
    # v12.0: Co-Scientist mode
    co_scientist_context: dict   # multi-source context built by hypothesis_node
    verified_findings: List[dict]  # data-verified findings from data_verification_node

    # v12.1: Optional external PTM-CoScientist Discussion Evidence Packet.
    # These fields remain independent from internal hypothesis / validation state.
    co_scientist_integration: dict
    co_scientist_session_id: Optional[str]
    co_scientist_discussion_packet: Optional[dict]
    co_scientist_status: str  # disabled | ready | skipped | timed_out | failed
    co_scientist_warning: Optional[str]
    co_scientist_integration_mode: str  # addendum | enhanced_discussion
    co_scientist_packet_snapshot: str

    # P2/P3: Discovery remains unbiased. These fields are populated only after
    # temporal analysis for recommendation or user-uploaded follow-up review.
    causal_validation_recommendations: dict
    perturbation_evidence: dict

    # P4 A/B: `legacy` skips Atlas/P1 report context. Missing key is `current`.
    temporal_contract: str

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


def data_verification(state: ReportState) -> dict:
    """Verify co-scientist hypotheses against experimental data (co_scientist mode only)."""
    from .nodes.data_verification_node import run_data_verification
    return run_data_verification(state)


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


def atlas_claim_ledger(state: ReportState) -> dict:
    """Build shared quality-gated temporal claims before any report prose is written."""
    from .nodes.atlas_claim_ledger_node import run_atlas_claim_ledger
    return run_atlas_claim_ledger(state)


def generate_atlas_report(state: ReportState) -> dict:
    """Render the detailed Atlas from the same claims supplied to integrated prose."""
    from .nodes.atlas_report_node import run_atlas_report_generation
    return run_atlas_report_generation(state)


def rq_refinement(state: ReportState) -> dict:
    """v10.0: Refine research questions using discovered signaling architecture."""
    from .nodes.rq_refinement_node import run_rq_refinement
    return run_rq_refinement(state)


def external_coscientist_context(state: ReportState) -> dict:
    """Load an opt-in external Discussion Evidence Packet without blocking the report."""
    from .nodes.external_coscientist_node import run_external_coscientist_context
    return run_external_coscientist_context(state)


def report_copilot(state: ReportState) -> dict:
    """v10.0: Review draft report and suggest enhancements."""
    from .nodes.report_copilot_node import run_report_copilot
    return run_report_copilot(state)


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
    main_section = "\n## Temporal PTM Coordination Analysis\n\n"
    main_section += (
        "The following figures show observed temporal trajectory clustering. Conventional quantified PTM sites "
        "were grouped by similarity of their sampled-timepoint profiles using hierarchical clustering. "
        "Cluster membership is descriptive only and does not assign common regulation, upstream "
        f"{'E3-ligase' if ptm_type.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase'} control, "
        "pathway function, signaling-cascade position, or causality.\n\n"
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
                f"**Legend:** Composite figure of transient {ptm_type} trajectory clusters. "
                "**(a)** Conventional quantified PTM time-series profiles; bold lines indicate conventional-only "
                "cluster means with shaded ranges. **(b)** Conventional peak contrasts ranked descriptively. "
                "**(c)** Conventional cluster mean envelopes across sampled timepoints. De novo observations are "
                "detection/LOD context and are not plotted or ranked on conventional Log2FC axes. "
                "Cluster membership does not assign function, common regulation, cascade position, or causality.\n\n"
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
                "**Legend:** Temporal Log₂FC profiles of cluster members. "
                "Only conventional quantified PTM rows are displayed on the numerical axis; de novo observations "
                "remain detection/LOD context. Solid lines = PTM proteins; dashed lines = linked Non-PTM interactors. "
                "Cluster membership does not assign function, common regulation, or causal order.\n\n"
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
        cf_caption = cf.get("caption", "Temporal Coordination Heatmap")
        if img_ref:
            supp_items.append((
                cf_caption, img_ref,
                "**Legend:** Hierarchical clustering heatmap of PTM temporal profiles. "
                "Rows = conventional quantified PTM sites, columns = time points. Color intensity reflects conventional "
                "Log2FC magnitude. De novo detection/LOD rows are omitted from the numerical colour scale. "
                "Cluster color bars on left sidebar indicate descriptive membership only."
            ))

    # Supplementary: Additional cluster plots
    for cf in supp_cluster_figs:
        img_ref = _resolve_figure_path(cf, Path)
        cf_caption = cf.get("caption", "Cluster Detail")
        if img_ref:
            supp_items.append((
                cf_caption, img_ref,
                "**Legend:** Temporal Log₂FC profiles of cluster members. "
                "Only conventional quantified PTM rows are displayed on the numerical axis; de novo observations "
                "remain detection/LOD context. Solid lines = PTM proteins; dashed lines = linked Non-PTM interactors. "
                "Cluster membership does not assign function, common regulation, or causal order."
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
    from .dynamic_prompt_generator import format_compact_attribution_readiness_for_report
    from .biological_synthesis import format_candidate_discovery_packet_for_report
    from .nodes.network_node import generate_network_figure_section
    import re as _re
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

    section_order = ["abstract", "introduction", "results", "research_question_answers", "discussion", "conclusion"]
    section_headings = {
        "abstract": "## Abstract",
        "introduction": "## Introduction",
        "results": "## Results",
        "research_question_answers": "## Research Question Answers",
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
            # Deterministic aggregate-only evidence appears once in the final
            # document so an LLM omission cannot hide P0–P3 no-call status or
            # P5 discovery selection semantics.
            readiness_section = format_compact_attribution_readiness_for_report(
                state.get("temporal_report_evidence_packet") or {}
            )
            if readiness_section:
                parts.append(readiness_section)
            p5_section = format_candidate_discovery_packet_for_report(
                state.get("biological_synthesis_packet") or {}
            )
            if p5_section:
                parts.append(p5_section)
            try:
                from .nodes.kinase_annotation_node import format_kinase_footprint_diagnostics_for_report
                footprint_section = format_kinase_footprint_diagnostics_for_report(
                    state.get("kinase_activity_heatmap") or {},
                    state.get("ptm_type", "phosphorylation"),
                )
                if footprint_section:
                    parts.append(footprint_section)
            except Exception as footprint_error:
                logger.warning("[FORMAT-CIT] Could not render P0/P1 footprint diagnostics: %s", footprint_error)
            # ═══════════════════════════════════════════════════════════════════
            # v10.3: Figure Placement Overhaul
            # Main Figures:  Fig 1 (Pathway Bar) → Fig 2 (Kinase Heatmap) →
            #                Fig 3 (Context PTM Heatmap) → Fig 4 (Pathway Diagram)
            # Supplementary: Co-movement figures + Signal Flow 4-layer + Cascade
            # ═══════════════════════════════════════════════════════════════════
            comovement_figures = state.get("comovement_figures", [])

            # Step 1: Network section — Fig 1 (Pathway Bar) only as main.
            # Force cascade/cytoscape to supplementary (has_comovement=True always)
            net_main, net_supp = generate_network_figure_section(
                network_analysis,
                supplementary_start=1,
                ptm_type=state.get('ptm_type', 'phosphorylation'),
                has_comovement=True,  # v10.3: always push cascade/cytoscape to supplementary
            )
            if net_main:
                parts.append(net_main)
                logger.info(f"[FORMAT-CIT] Added network main section ({len(net_main)} chars) — Fig 1 only")
            else:
                logger.warning("[FORMAT-CIT] network main section is EMPTY")
            network_supp_section = net_supp  # store for appending at end

            # Step 2 (v10.3): Co-movement → ALL to Supplementary (no main figures)
            if comovement_figures:
                result = _build_comovement_figure_section(comovement_figures, network_analysis, ptm_type=state.get('ptm_type', 'phosphorylation'))
                if result:
                    main_section, supp_items, _next_fig = result
                    # v10.3: Move ALL co-movement figures to supplementary
                    # Parse main_section for any figure images and add them to supp_items
                    if main_section:
                        # Extract image references from main_section and add to supplementary
                        import re as _re_cm
                        cm_figures = _re_cm.findall(r'!\[([^\]]*)\]\(([^)]+)\)', main_section)
                        for cm_cap, cm_path in cm_figures:
                            comovement_supp_items.append((
                                cm_cap or "Temporal PTM Coordination",
                                cm_path,
                                "Temporal Log₂FC profiles of temporally coordinated PTM cluster members. "
                                "Solid lines = PTM proteins; dashed lines = linked Non-PTM interactors."
                            ))
                        logger.info(f"[FORMAT-CIT] v10.3: Moved {len(cm_figures)} co-movement figures to supplementary (was main)")
                    if supp_items:
                        comovement_supp_items.extend(supp_items)

            # Step 3 (v10.3): Signal Flow & Kinase Heatmap figures
            # Main: kinase_heatmap (Fig 2) + pathway_diagram (Fig 4)
            # Supplementary: signal_flow_supplementary, signal_flow (legacy)
            signal_flow_figures = state.get("signal_flow_figures", []) or []
            entity_label = "E3 Ligase" if state.get('ptm_type', 'phosphorylation').lower().strip() in ('ubiquitylation', 'ubiquitination') else "Kinase"
            fig_num = 2  # Fig 1 is Pathway Bar from network_node

            if signal_flow_figures:
                sf_section_parts = []
                sf_supp_items = []  # Collect supplementary items

                # Sort: kinase_heatmap first (Fig 2), then pathway_diagram (Fig 4 — after Fig 3 context PTM)
                kinase_heatmap_figs = [f for f in signal_flow_figures if f.get("type") == "kinase_heatmap"]
                pathway_diagram_figs = [f for f in signal_flow_figures if f.get("type") == "pathway_diagram"]
                other_main_figs = [f for f in signal_flow_figures if f.get("type") not in (
                    "kinase_heatmap", "pathway_diagram", "signal_flow_supplementary", "signal_flow")]
                supp_figs = [f for f in signal_flow_figures if f.get("type") in ("signal_flow_supplementary", "signal_flow")]

                # Fig 2: substrate-derived candidate context score heatmap
                for sf_fig in kinase_heatmap_figs:
                    fig_path = sf_fig.get("path", "")
                    fig_caption = sf_fig.get("caption", "")
                    if not fig_path:
                        continue
                    sf_section_parts.append(
                        f"\n### Figure {fig_num}. Temporal {entity_label} Candidate Context Score Heatmap\n\n"
                        f"Substrate-derived directional score heatmap for candidate {entity_label.lower()} context "
                        f"across experimental conditions. Red and blue summarize the signed substrate score; they do "
                        f"not establish direct {entity_label.lower()} activity or a kinase–site relation. "
                        f"Temporal pattern annotations (right) classify each "
                        f"{entity_label.lower()} as sustained, early-only, late-onset, spike, or reversal. "
                        f"Substrate count (n=N) indicates the number of PTM substrates contributing to each score.\n\n"
                        f"![{fig_caption}]({fig_path})\n\n---\n"
                    )
                    logger.info(f"[FORMAT-CIT] v10.3: Kinase Heatmap inserted as Figure {fig_num}")
                    fig_num += 1

                # Fig 3 placeholder — Context PTM Heatmap will be inserted in Step 4 below
                # We store fig_num for context heatmap and pathway_diagram
                context_ptm_fig_num = fig_num  # This will be Fig 3
                fig_num += 1  # Reserve Fig 3 for context PTM heatmap
                pathway_diagram_fig_num = fig_num  # This will be Fig 4
                fig_num += 1  # Reserve Fig 4 for pathway diagram

                # NOTE: Pathway Diagram (Fig 4) will be inserted AFTER Context PTM (Fig 3)
                # in Step 4 below to maintain correct ordering in the final document.
                pathway_diagram_section = ""
                for sf_fig in pathway_diagram_figs:
                    fig_path = sf_fig.get("path", "")
                    fig_caption = sf_fig.get("caption", "")
                    if not fig_path:
                        continue
                    pathway_diagram_section = (
                        f"\n### Figure {pathway_diagram_fig_num}. Contextual Signaling Map\n\n"
                        f"Compartmentalized context map placing treatment context, literature/pathway-linked receptors, "
                        f"candidate {entity_label.lower()} context, and measured PTM/non-PTM observations in a common view. "
                        f"Dashed connectors denote context association only; they do not encode Order-specific direction, "
                        f"activation, inhibition, direct kinase–substrate regulation, or causality.\n\n"
                        f"![{fig_caption}]({fig_path})\n\n---\n"
                    )
                    logger.info(f"[FORMAT-CIT] v10.3: Pathway Diagram prepared as Figure {pathway_diagram_fig_num}")

                # Other main figures (if any)
                for sf_fig in other_main_figs:
                    fig_path = sf_fig.get("path", "")
                    fig_caption = sf_fig.get("caption", "")
                    if fig_path:
                        sf_section_parts.append(f"\n![{fig_caption}]({fig_path})\n")

                # Supplementary: signal_flow, signal_flow_supplementary
                for sf_fig in supp_figs:
                    fig_path = sf_fig.get("path", "")
                    fig_caption = sf_fig.get("caption", "")
                    if fig_path:
                        sf_supp_items.append((fig_caption, fig_path,
                            f"Detailed context map showing receptor, {entity_label.lower()}, PTM, and non-PTM annotations. "
                            f"Connectors indicate literature/pathway context only and are not direct Order-specific relations."))

                sf_combined = "\n".join(sf_section_parts)
                parts.append(sf_combined)
                logger.info(f"[FORMAT-CIT] Added main signaling figures ({len(sf_combined)} chars)")
                # Add signal flow supplementary items
                if sf_supp_items:
                    comovement_supp_items.extend(sf_supp_items)
                    logger.info(f"[FORMAT-CIT] Moved {len(sf_supp_items)} signal flow figures to supplementary")
            else:
                context_ptm_fig_num = fig_num
                fig_num += 1
                pathway_diagram_section = ""

            # Step 4 (v10.3): Context-aware PTM Heatmap — Fig 3 (post-writing, uses mentioned PTMs)
            try:
                from .nodes.signal_flow_figure import generate_context_aware_ptm_heatmap
                sections_for_ctx = {
                    "results": sections.get("results", ""),
                    "discussion": sections.get("discussion", ""),
                    "abstract": sections.get("abstract", ""),
                    "conclusion": sections.get("conclusion", ""),
                }
                output_dir = state.get("output_dir", "")
                vector_plot_raw_data = state.get("vector_plot_raw_data", [])
                # Get conditions from kinase_activity_heatmap or network_analysis
                kah = state.get("kinase_activity_heatmap", {}) or {}
                ctx_conditions = kah.get("conditions", [])
                if not ctx_conditions:
                    # Fallback: extract from network_analysis timepoints
                    na = state.get("network_analysis", {}) or {}
                    ctx_conditions = na.get("timepoints", [])
                if not ctx_conditions and vector_plot_raw_data:
                    # Fallback: extract unique conditions from raw data
                    ctx_conditions = sorted(set(
                        r.get("condition", "") for r in vector_plot_raw_data if r.get("condition")
                    ), key=condition_sort_key)

                if output_dir and vector_plot_raw_data and ctx_conditions:
                    ctx_heatmap_path = generate_context_aware_ptm_heatmap(
                        sections=sections_for_ctx,
                        vector_plot_raw_data=vector_plot_raw_data,
                        conditions=ctx_conditions,
                        output_dir=output_dir,
                        ptm_type=state.get('ptm_type', 'phosphorylation'),
                    )
                    if ctx_heatmap_path:
                        ctx_fig_section = (
                            f"\n\n### Figure {context_ptm_fig_num}. Key PTM Sites Referenced in This Report\n\n"
                            f"Heatmap showing the temporal conventional Log₂FC profiles of PTM sites "
                            f"specifically discussed in the Results and Discussion sections above. "
                            f"Sites are clustered by temporal pattern similarity. Red/blue encode conventional quantified contrasts; "
                            f"starred de novo sites, where present, use LOD-relative detection context and are excluded from the colour scale.\n\n"
                            f"![Context-aware PTM Heatmap]({ctx_heatmap_path})\n\n---\n"
                        )
                        parts.append(ctx_fig_section)
                        logger.info(f"[FORMAT-CIT] v10.3: Context-aware PTM heatmap inserted as Figure {context_ptm_fig_num}")
                    else:
                        logger.info("[FORMAT-CIT] Context-aware PTM heatmap returned None — skipping")
                else:
                    logger.info(f"[FORMAT-CIT] Skipping context PTM heatmap: output_dir={bool(output_dir)}, "
                                f"raw_data={bool(vector_plot_raw_data)}, conditions={bool(ctx_conditions)}")
            except Exception as ctx_err:
                logger.warning(f"[FORMAT-CIT] Context-aware PTM heatmap generation failed: {ctx_err}")

            # Step 5 (v10.5): Insert Pathway Diagram (Fig 4) AFTER Context PTM (Fig 3)
            # This ensures correct Figure ordering: Fig 2 → Fig 3 → Fig 4
            if signal_flow_figures and pathway_diagram_section:
                parts.append(pathway_diagram_section)
                logger.info(f"[FORMAT-CIT] v10.5: Pathway Diagram inserted as Figure {pathway_diagram_fig_num} (after Fig 3)")

    # The external packet Addendum is deterministic and clearly separated from
    # Results/Discussion observations. Rebuild it here so re-resolved literature
    # can use the same [N] numbering as the final ## References section.
    external_addendum = sections.get("co_scientist_addendum", "")
    if state.get("co_scientist_status") == "ready" and state.get("co_scientist_integration_mode") == "addendum":
        try:
            from .nodes.external_coscientist_node import (
                build_citation_map,
                build_external_coscientist_addendum,
            )
            citation_map = build_citation_map(collected_refs)
            rebuilt = build_external_coscientist_addendum(
                state.get("co_scientist_discussion_packet") or {},
                citation_map=citation_map,
            )
            if rebuilt:
                external_addendum = rebuilt
                sections["co_scientist_addendum"] = rebuilt
                logger.info(
                    "[FORMAT-CIT] Rebuilt Co-Scientist addendum with %d citation keys",
                    len(citation_map),
                )
        except Exception as addendum_err:
            logger.warning("[FORMAT-CIT] Could not rebuild Co-Scientist addendum citations: %s", addendum_err)
    if external_addendum:
        # External addendum citations use the already-global collected-reference
        # index. Convert only this deterministic, globally numbered addendum to
        # stable markers before local LLM numeric citations are fail-closed.
        def _global_ref_marker(match: _re.Match) -> str:
            index = int(match.group(1))
            if not 0 < index <= len(collected_refs):
                return ""
            ref = collected_refs[index - 1]
            pmid = str(ref.get("pmid") or "").strip()
            if pmid:
                return f"[REF:pmid:{pmid.lower()}]"
            doi = str(ref.get("doi") or "").strip().lower()
            if doi:
                return f"[REF:doi:{doi}]"
            title_key = _re.sub(r"[^a-z0-9]", "", str(ref.get("title") or "").lower())[:120]
            return f"[REF:title:{title_key}]" if title_key else ""
        external_addendum = _re.sub(r"\[(\d+)\]", _global_ref_marker, external_addendum)
        parts.append(external_addendum)
        logger.info(f"[FORMAT-CIT] Added external Co-Scientist addendum ({len(external_addendum)} chars)")

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
    # v1.2 Fix: Normalize legacy LLM citation formats to [N].  New sections
    # already use stable [REF:<identity>] markers created by writer_node.
    # LLM sometimes writes [PubMed Ref 1] or [Reference 1] instead of [1]
    all_text = _re.sub(r'\[PubMed Ref\s*(\d+)\]', r'[\1]', all_text)
    all_text = _re.sub(r'\[Reference\s*(\d+)\]', r'[\1]', all_text)
    all_text = _re.sub(r'\[Ref\s*(\d+)\]', r'[\1]', all_text)
    all_text = _re.sub(r'\[ChromaDB Reference\s*(\d+)\]', r'[\1]', all_text)
    logger.info("[FORMAT-CIT] Normalized inline citation formats to [N]")

    logger.info(f"[FORMAT-CIT] collected_references count: {len(collected_refs)}")

    # v10.8: Build Reference objects from collected_references (ChromaDB + PubMed unified)
    # ChromaDB refs are first [1]~[N], PubMed refs follow [N+1]~[N+M]
    ref_objects: list = []
    n_chromadb_refs = 0
    for ref_dict in collected_refs:
        is_chromadb = ref_dict.get("chromadb_ref", False)
        # A Chroma collection/bundle label without paper-level metadata is an
        # internal retrieval provenance label, not a citable publication. Do
        # not let it masquerade as a journal in the final bibliography.
        has_persistent_identifier = bool(str(ref_dict.get("pmid") or "").strip() or str(ref_dict.get("doi") or "").strip())
        has_minimal_publication_identity = bool(
            str(ref_dict.get("authors") or "").strip()
            and str(ref_dict.get("year") or ref_dict.get("pub_date") or "").strip()
            and str(ref_dict.get("journal") or "").strip()
        )
        if is_chromadb and not (has_persistent_identifier or has_minimal_publication_identity):
            logger.info("[FORMAT-CIT] Excluding non-bibliographic Chroma bundle label from references")
            continue
        if is_chromadb:
            n_chromadb_refs += 1
            ref = Reference(
                authors=ref_dict.get("authors", ""),
                title=ref_dict.get("title", "Untitled"),
                journal=ref_dict.get("journal", ""),
                year=str(ref_dict.get("year", "")),
                pmid=str(ref_dict.get("pmid", "")),
                doi=ref_dict.get("doi", ""),
            )
        else:
            ref = Reference(
                authors=ref_dict.get("authors", ""),
                title=ref_dict.get("title", "Untitled"),
                journal=ref_dict.get("journal", ""),
                year=str(ref_dict.get("pub_date", ref_dict.get("year", "")))[:4],
                pmid=str(ref_dict.get("pmid", "")),
                doi=ref_dict.get("doi", ""),
            )
        ref_objects.append(ref)
    logger.info(f"[FORMAT-CIT] Reference breakdown: {n_chromadb_refs} ChromaDB + {len(ref_objects) - n_chromadb_refs} PubMed = {len(ref_objects)} total")

    def _reference_key(ref: Reference, index: int) -> str:
        if ref.pmid:
            return f"pmid:{ref.pmid.lower()}"
        if ref.doi:
            return f"doi:{ref.doi.lower()}"
        title = _re.sub(r"[^a-z0-9]", "", ref.title.lower())[:120]
        return f"title:{title}" if title else f"local:{index}"

    # A bare [N] is section-local LLM numbering and cannot be joined safely to
    # the document-wide bibliography. Remove it before resolving stable
    # markers, whose final [N] representation is assigned below.
    raw_citations = sorted(set(int(value) for value in _re.findall(r"\[(\d+)\]", all_text)))
    if raw_citations:
        logger.warning(
            "[FORMAT-CIT] Removing %d legacy numeric citations without stable markers; "
            "their section-local numbering cannot be safely mapped to the final bibliography.", len(raw_citations),
        )
        all_text = _re.sub(r"\[(\d+(?:\s*(?:,|-)\s*\d+)*)\]", "", all_text)

    # Resolve stable markers in first-appearance order.  This makes every
    # inline citation unambiguous even when individual LLM sections received
    # different RAG subsets and local reference numbering.
    reference_by_key: dict[str, Reference] = {}
    for index, ref in enumerate(ref_objects, 1):
        reference_by_key.setdefault(_reference_key(ref, index), ref)
    cited_keys: list[str] = []

    def _resolve_marker(match: _re.Match) -> str:
        key = str(match.group(1) or "").strip().lower()
        if key not in reference_by_key:
            logger.warning("[FORMAT-CIT] Dropping unresolved stable citation marker: %s", key)
            return ""
        if key not in cited_keys:
            cited_keys.append(key)
        return f"[{cited_keys.index(key) + 1}]"

    all_text = _re.sub(r"\[REF:([^\]]+)\]", _resolve_marker, all_text)
    resolved_refs = [reference_by_key[key] for key in cited_keys]

    # Build the ## References section strictly from successfully resolved
    # collection-local or PubMed references.  This prevents an untraceable
    # text citation from being paired with an unrelated bibliography entry.
    ref_lines = ["## References\n"]
    for idx, ref in enumerate(resolved_refs, 1):
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

    citation_completion_status = "complete" if resolved_refs else "blocked_for_review_missing_traceable_references"
    if resolved_refs:
        reference_section = "\n".join(ref_lines)
    else:
        reference_section = (
            "## References\n\n"
            "**Citation completeness status: blocked for review.** No traceable collection-local or PubMed "
            "reference was resolved for this Report. Literature comparison and external biological background "
            "must be treated as unavailable until traceable reference metadata is supplied."
        )
    logger.info(f"[FORMAT-CIT] Built resolved reference section with {len(resolved_refs)} entries")

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
        # Run all supplementary captions through the same claim/citation/table
        # cleanup as the main body. References are appended only after this so
        # they stay at the physical end of the rendered Markdown/DOCX.
        all_text += supp_combined
        logger.info("[FORMAT-CIT] Appended all supplementary figures at end of report")

    # Process the complete body, including supplementary captions, before
    # appending the bibliography. This prevents supplementary legacy prose from
    # bypassing the R1.0 claim boundary and keeps References as the last section.
    processor = ReportPostProcessor()
    processed = processor.process(all_text)
    if reference_section:
        processed += "\n\n" + reference_section

    return {
        "final_report": processed,
        "citation_data": {
            "total_references": len(resolved_refs),
            "reference_section": reference_section,
            "completion_status": citation_completion_status,
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


def _route_after_validate(state: ReportState) -> str:
    """Route after validate_hypotheses: co_scientist mode inserts data_verification."""
    report_type = state.get("report_type", "comprehensive")
    if report_type == "co_scientist":
        logger.info("[GRAPH] Routing to data_verification (co_scientist mode)")
        return "data_verification"
    return "network_analysis"


def _route_after_kinase_annotation(state: ReportState) -> str:
    """`legacy` skips Atlas ledger/report so the integrated prose matches the old path."""
    from ptm_shared.temporal_contract import resolve_temporal_contract
    if resolve_temporal_contract(state).run_atlas_report:
        return "atlas_claim_ledger"
    logger.info("[GRAPH] Skipping Atlas nodes (temporal_contract=legacy)")
    return "rq_refinement"


def build_report_graph() -> StateGraph:
    """Build the LangGraph StateGraph for report generation.

    Flow (v10.0):
      Standard (ptm_only / ptm_nonptm_network):
        load_context → generate_questions → research → hypothesize
          → validate_hypotheses → network_analysis → temporal_comovement
          → kinase_annotation → rq_refinement → external_coscientist_context → write_sections
          → report_copilot → cascade_mediator → generate_qa_report
          → drug_repositioning → format_citations → edit_report

      Cross-Talk (cross_talk):
        Same as standard but crosstalk_analysis inserted after cascade_mediator.

    v12.0: Co-Scientist mode: data_verification inserted after validate_hypotheses.
           co_scientist_context and verified_findings added to ReportState.
    v10.0: rq_refinement between kinase_annotation and write_sections.
           report_copilot between write_sections and cascade_mediator.
    v9.11: kinase_annotation between temporal_comovement and write_sections.
    v9.0: crosstalk_analysis conditionally inserted after cascade_mediator.
    v8.0: temporal_comovement between network_analysis and write_sections.
    v7.0: cascade_mediator after write_sections for content-driven diagrams.
    """
    graph = StateGraph(ReportState)

    graph.add_node("load_context", load_context)
    graph.add_node("generate_questions", generate_questions)
    graph.add_node("research", research)
    graph.add_node("hypothesize", hypothesize)
    graph.add_node("validate_hypotheses", validate_hypotheses)
    graph.add_node("data_verification", data_verification)
    graph.add_node("network_analysis", network_analysis)
    graph.add_node("temporal_comovement", temporal_comovement)
    graph.add_node("kinase_annotation", kinase_annotation)
    graph.add_node("atlas_claim_ledger", atlas_claim_ledger)
    graph.add_node("generate_atlas_report", generate_atlas_report)
    graph.add_node("rq_refinement", rq_refinement)
    graph.add_node("external_coscientist_context", external_coscientist_context)
    graph.add_node("write_sections", write_sections)
    graph.add_node("report_copilot", report_copilot)
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
    # Conditional: co_scientist mode inserts data_verification after validate_hypotheses
    graph.add_conditional_edges(
        "validate_hypotheses",
        _route_after_validate,
        {
            "data_verification": "data_verification",
            "network_analysis": "network_analysis",
        },
    )
    graph.add_edge("data_verification", "network_analysis")
    graph.add_edge("network_analysis", "temporal_comovement")
    graph.add_edge("temporal_comovement", "kinase_annotation")
    graph.add_conditional_edges(
        "kinase_annotation",
        _route_after_kinase_annotation,
        {
            "atlas_claim_ledger": "atlas_claim_ledger",
            "rq_refinement": "rq_refinement",
        },
    )
    graph.add_edge("atlas_claim_ledger", "generate_atlas_report")
    graph.add_edge("generate_atlas_report", "rq_refinement")
    graph.add_edge("rq_refinement", "external_coscientist_context")
    graph.add_edge("external_coscientist_context", "write_sections")
    graph.add_edge("write_sections", "report_copilot")
    graph.add_edge("report_copilot", "cascade_mediator")

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
