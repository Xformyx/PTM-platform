"""
Writer Node — generates report sections using LLM + literature RAG.
Ported from multi_agent_system/agents/section_writers.py.

Generates: Abstract, Introduction, Results, Discussion, Conclusion.
Each section uses LLM with published literature context for integration.
"""

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from common.llm_client import LLMClient
from common.report_postprocessor import validate_llm_output_against_data, postprocess_log2fc_formatting
from common.ptm_vocabulary import get_vocabulary, get_system_prompt_for_ptm, build_vocabulary_prompt_block, get_normalized_ptm_type
from report_generation.core.rag_retriever import RAGRetriever
from report_generation.core.dynamic_prompt_generator import (
    build_anti_hallucination_directive,
    build_dynamic_writing_example,
    build_structured_protein_data_for_llm,
    build_ptm_data_summary,
    build_nonptm_temporal_analysis,
    build_ptm_protein_timelag_analysis,
    build_pathway_context_for_llm,
    build_signal_propagation_json,
    format_condition_display_name,
)
from report_generation.core.figure_context import FigureInformationGenerator

logger = logging.getLogger(__name__)

SECTION_ORDER = ["introduction", "results", "discussion", "conclusion", "methods", "suggestion", "abstract", "title"]

SECTION_MAX_TOKENS = {
    "abstract": 6144,
    "introduction": 12288,
    "results": 16384,
    "discussion": 16384,
    "conclusion": 8192,
    "methods": 8192,
    "suggestion": 8192,
    "title": 512,
}

# v9.31: Per-section prompt budget (characters).
# v9.32: Increased budgets — co-wave + temporal kinase + receptor are now ESSENTIAL.
# Gemini 2.5 Flash supports ~1M tokens; quality is acceptable up to ~120K chars.
SECTION_PROMPT_BUDGET = {
    "abstract": 40_000,
    "introduction": 60_000,
    "results": 120_000,
    "discussion": 100_000,
    "conclusion": 50_000,
    "methods": 30_000,
    "suggestion": 40_000,
    "title": 10_000,
}
MAX_PROMPT_CHARS = 200_000  # absolute safety cap

# Minimum word counts for generate_with_retry per section
SECTION_MIN_WORDS = {
    "abstract": 200,
    "introduction": 800,
    "results": 1200,
    "discussion": 1000,
    "conclusion": 300,
    "methods": 400,
    "suggestion": 400,
    "title": 3,
}

# Legacy SYSTEM_PROMPT kept as fallback; prefer get_system_prompt_for_ptm(ptm_type)
SYSTEM_PROMPT = (
    "You are a scientific writer specializing in post-translational modification (PTM) analysis. "
    "Write in formal academic English. Use flowing prose, not bullet points. "
    "Cite references using numbered brackets (e.g., [1], [2]) matching the provided reference list. "
    "Include as many relevant citations as possible to support your statements. "
    "NEVER mention 'ChromaDB' or 'knowledge base'. "
    "Be precise with PTM site nomenclature. For phosphorylation use e.g. 'phosphorylation at Ser165 of GENE_NAME'; for ubiquitylation use e.g. 'ubiquitylation at Lys48 of GENE_NAME'. Match the PTM type being analyzed. "
    "CRITICAL: Use ONLY proteins and PTM sites from the actual data provided in the prompt. "
    "Never use example or placeholder proteins (e.g., ACC1, MAPK3, Ser79) from prompt templates — they are for illustration only. "
    "Write detailed, comprehensive content that thoroughly covers the topic. "
    "Do NOT include a top-level section heading (e.g., '## Results' or '## Discussion') — "
    "the heading will be added automatically. You may use ### sub-headings within your text."
)


def run_section_writing(state: dict) -> dict:
    """Write all report sections using LLM."""
    cb = state.get("progress_callback")
    if cb:
        cb(70, "Writing report sections")

    # Load report_config from state for dynamic settings
    report_config = state.get("report_config", {})
    llm_tokens_cfg = report_config.get("llm_tokens", {})
    section_max_tokens = {
        "abstract": llm_tokens_cfg.get("abstract", SECTION_MAX_TOKENS["abstract"]),
        "introduction": llm_tokens_cfg.get("introduction", SECTION_MAX_TOKENS["introduction"]),
        "results": llm_tokens_cfg.get("results", SECTION_MAX_TOKENS["results"]),
        "time_course": llm_tokens_cfg.get("time_course", 8192),
        "discussion": llm_tokens_cfg.get("discussion", SECTION_MAX_TOKENS["discussion"]),
        "conclusion": llm_tokens_cfg.get("conclusion", SECTION_MAX_TOKENS["conclusion"]),
    }
    llm_temperature = report_config.get("llm_temperature", 0.6)
    ptm_detail_count = report_config.get("ptm_detail_count", 30)
    chromadb_results = report_config.get("chromadb_results_per_section", 10)

    logger.info(f"Report config: tokens={section_max_tokens}, temp={llm_temperature}, "
                f"ptm_detail={ptm_detail_count}, chromadb_results={chromadb_results}")

    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    if not llm.is_available():
        logger.error(
            f"LLM not available: provider='{llm.provider}', model='{llm.model}', url='{llm.base_url}'. "
            "All sections will use fallback text. Check that Ollama is running and the model is installed."
        )
        if cb:
            cb(72, f"WARNING: LLM model '{llm.model}' not available — using fallback text")

    collections = state.get("chromadb_collections", [])
    retriever = RAGRetriever(collection_names=collections)

    research_results = state.get("research_results", [])
    validated_hypotheses = state.get("validated_hypotheses", [])
    network_analysis = state.get("network_analysis", {})
    parsed_ptms = state.get("parsed_ptms", [])
    context = state.get("experimental_context", {})
    questions = state.get("research_questions", [])
    comprehensive_summary = state.get("comprehensive_summary", "")

    all_references = _collect_all_references(parsed_ptms)
    logger.info(f"Collected {len(all_references)} unique PubMed references from enriched PTM data")

    # Figure context for LLM — enables natural figure references in Results/Discussion
    # v8.0: Pass co-movement analysis results to figure context
    comovement_analysis = state.get("comovement_analysis", {})
    comovement_figures = state.get("comovement_figures", [])
    comovement_llm_context = state.get("comovement_llm_context", "")
    temporal_kinase_cascade_llm_context = state.get("temporal_kinase_cascade_llm_context", "")

    # v9.20: Build inferred receptor context for LLM
    inferred_receptors = state.get("inferred_receptors", []) or []
    receptor_llm_context = ""
    if inferred_receptors:
        lines = [
            "=== INFERRED UPSTREAM RECEPTORS (from Reactome pathway mapping + treatment context) ===",
            "The following upstream receptors were computationally inferred based on the active kinases",
            "detected in this experiment. Use this information to contextualize the signaling cascade",
            "from ligand/receptor activation down to the observed PTM changes.",
            "",
        ]
        for i, rec in enumerate(inferred_receptors[:15], 1):  # top 15
            name = rec.get("name", "Unknown")
            rec_class = rec.get("receptor_class", "")
            ptm_count = rec.get("downstream_ptm_count", 0)
            downstream = rec.get("downstream_ptms", [])[:5]
            via_kinases = rec.get("via_kinases", [])[:5]
            pathway = rec.get("signaling_pathway") or rec.get("pathway", "")
            source = rec.get("source", "")
            source_label = {
                "treatment_context": "Treatment context (curated)",
                "treatment_context_uniprot": "Treatment context (UniProt)",
                "reactome": "Reactome pathway mapping",
                "literature": "Literature (upstream regulators)",
            }.get(source, source)
            line = f"{i}. {name} [{rec_class}] — {ptm_count} downstream PTMs"
            if via_kinases:
                line += f" | via kinases: {', '.join(via_kinases)}"
            if pathway:
                line += f" | pathway: {pathway}"
            if downstream:
                line += f" | key PTMs: {', '.join(downstream[:3])}"
            line += f" | source: {source_label}"
            lines.append(line)
        lines.append("")
        lines.append("=== END INFERRED UPSTREAM RECEPTORS ===")
        receptor_llm_context = "\n".join(lines)
        logger.info(f"[v9.20] Built receptor context: {len(inferred_receptors)} receptors, {len(receptor_llm_context)} chars")
    figure_gen = FigureInformationGenerator(
        network_analysis, parsed_ptms,
        comovement_analysis=comovement_analysis,
        comovement_figures=comovement_figures,
        comovement_llm_context=comovement_llm_context,
    )
    if figure_gen.has_figures():
        logger.info(f"Figure context available: {len(figure_gen.figure_map)} figures")
    else:
        logger.info("No Cytoscape figures available — skipping figure context")

    # v98: Build structured protein data for anti-hallucination
    ptm_type = state.get("ptm_type", "phosphorylation")
    network_results = state.get("network_results", {})
    timepoints = sorted(network_results.get("timepoints", []))
    v98_structured_data, v98_protein_names, v98_log2fc_values = build_structured_protein_data_for_llm(
        network_results, timepoints, ptm_type=ptm_type
    )
    v98_directive = build_anti_hallucination_directive(
        v98_protein_names, section_name="the PTM analysis report"
    )
    v98_writing_example = build_dynamic_writing_example(
        network_results, timepoints, ptm_type=ptm_type
    )
    logger.info(f"[v98] Built structured data: {len(v98_protein_names)} proteins, {len(v98_log2fc_values)} values")

    _LLM_WORKERS = int(os.getenv("REPORT_LLM_WORKERS", "2"))

    sections: Dict[str, str] = {}
    prev_sections: Dict[str, str] = {}

    # v10.1: Load vector_plot_raw_data and pipeline_statistics from state
    vector_plot_raw_data = state.get("vector_plot_raw_data", []) or []
    pipeline_statistics = state.get("pipeline_statistics", {}) or {}

    # v10.1: Build full vector plot context for LLM (all PTM + Non-PTM FC values)
    aux_vector_plot_full = ""
    if vector_plot_raw_data:
        vp_lines = [
            "=== FULL VECTOR PLOT DATA (All PTM sites + Non-PTM protein abundance) ===",
            "This table contains the complete quantitative data for ALL measured PTM sites and proteins.",
            "Use this data to answer specific questions about individual proteins or PTM sites.",
            "",
            "| Gene | Position | Condition | PTM_Relative_Log2FC | Protein_Log2FC |",
            "|------|----------|-----------|---------------------|----------------|",
        ]
        # Sort by absolute PTM FC for relevance, include all
        sorted_vp = sorted(
            vector_plot_raw_data,
            key=lambda x: abs(float(x.get("ptm_relative_log2fc", 0) or 0)),
            reverse=True
        )
        for row in sorted_vp:
            gene = row.get("gene", "")
            pos = row.get("position", "")
            cond = row.get("condition", "")
            ptm_fc = row.get("ptm_relative_log2fc", "")
            prot_fc = row.get("protein_log2fc", "")
            ptm_fc_str = f"{float(ptm_fc):+.3f}" if ptm_fc not in (None, "", "NA") else "NA"
            prot_fc_str = f"{float(prot_fc):+.3f}" if prot_fc not in (None, "", "NA") else "NA"
            vp_lines.append(f"| {gene} | {pos} | {cond} | {ptm_fc_str} | {prot_fc_str} |")
        vp_lines.append("")
        vp_lines.append("=== END FULL VECTOR PLOT DATA ===")
        aux_vector_plot_full = "\n".join(vp_lines)
        logger.info(f"[v10.1] Built full vector plot context: {len(vector_plot_raw_data)} rows, {len(aux_vector_plot_full):,} chars")

    # Inject pipeline_statistics into experimental_context for Methods prompt
    if pipeline_statistics:
        context["pipeline_statistics"] = pipeline_statistics

    # v9.31: Pre-build auxiliary blocks once (reuse across sections)
    aux_ptm_data_summary = build_ptm_data_summary(parsed_ptms, ptm_type=ptm_type)
    aux_nonptm_temporal = build_nonptm_temporal_analysis(network_results, timepoints, ptm_type=ptm_type)
    aux_timelag = build_ptm_protein_timelag_analysis(network_results, timepoints, ptm_type=ptm_type)
    aux_pathway_ctx = build_pathway_context_for_llm(parsed_ptms)
    aux_signal_prop = build_signal_propagation_json(network_results, timepoints, ptm_type=ptm_type)
    logger.info(
        f"[v9.31] Aux block sizes: ptm_data={len(aux_ptm_data_summary):,}, "
        f"nonptm_temporal={len(aux_nonptm_temporal):,}, timelag={len(aux_timelag):,}, "
        f"pathway_ctx={len(aux_pathway_ctx):,}, signal_prop={len(aux_signal_prop):,}, "
        f"v98_directive={len(v98_directive):,}, v98_structured={len(v98_structured_data):,}, "
        f"v98_example={len(v98_writing_example):,}, "
        f"temporal_kinase={len(temporal_kinase_cascade_llm_context):,}, "
        f"receptor={len(receptor_llm_context):,}"
    )

    # ── Per-section writer (extracted for parallel execution) ──
    def _write_one(section_type, snap_prev):
        prompt = _build_section_prompt(
            section_type, research_results, validated_hypotheses,
            network_analysis, parsed_ptms, context, questions,
            snap_prev, retriever, comprehensive_summary,
            all_references, ptm_detail_count=ptm_detail_count,
            chromadb_results=chromadb_results,
            temporal_kinase_cascade=state.get("temporal_kinase_cascade"),
            inferred_receptors=state.get("inferred_receptors"),
        )

        # v9.31: Budget-aware prompt enhancement
        # Build supplementary blocks with priority, respecting per-section budget
        budget = SECTION_PROMPT_BUDGET.get(section_type, 60_000)
        base_len = len(prompt)

        # v9.32: Priority-ordered supplementary blocks — temporal coordination, temporal kinase,
        # receptor, and non-PTM are now ESSENTIAL (Priority 1-2) for PTM activity profile interpretation.
        supplement_blocks = []
        if section_type == "results":
            # Priority 1 (ESSENTIAL — PTM activity profile core): temporal coordination + temporal kinase + receptor + non-PTM effector
            # v9.35: nonptm_temporal promoted to Priority 1 — effector proteins are integral
            # to the receptor→kinase→substrate→effector signal flow narrative.
            supplement_blocks.append(("comovement", comovement_llm_context))
            supplement_blocks.append(("temporal_kinase", temporal_kinase_cascade_llm_context))
            supplement_blocks.append(("receptor_ctx", receptor_llm_context))
            supplement_blocks.append(("nonptm_temporal", aux_nonptm_temporal))
            # Priority 2 (important): v98 + structured data
            supplement_blocks.append(("v98_directive", v98_directive))
            supplement_blocks.append(("v98_structured_data", v98_structured_data))
            # Priority 3 (supporting): pathway, signal propagation, timelag
            supplement_blocks.append(("pathway_ctx", aux_pathway_ctx))
            supplement_blocks.append(("signal_prop", aux_signal_prop))
            supplement_blocks.append(("timelag", aux_timelag))
            supplement_blocks.append(("ptm_data_summary", aux_ptm_data_summary))
            # Priority 4 (vector plot full data): complete quantitative reference
            supplement_blocks.append(("vector_plot_full", aux_vector_plot_full))
            # Priority 5 (lowest): figure context, writing example
            if figure_gen.has_figures():
                supplement_blocks.append(("figure_ctx", figure_gen.generate_figure_context_for_llm(section_type)))
            supplement_blocks.append(("v98_writing_example", v98_writing_example))

        elif section_type == "discussion":
            # Priority 1 (ESSENTIAL): temporal coordination + temporal kinase + receptor + non-PTM
            supplement_blocks.append(("comovement", comovement_llm_context))
            supplement_blocks.append(("temporal_kinase", temporal_kinase_cascade_llm_context))
            supplement_blocks.append(("receptor_ctx", receptor_llm_context))
            supplement_blocks.append(("nonptm_temporal", aux_nonptm_temporal))
            # Priority 2: v98 directive + structured data
            supplement_blocks.append(("v98_directive", v98_directive))
            supplement_blocks.append(("v98_structured_data", v98_structured_data))
            # Priority 3: vector plot full data
            supplement_blocks.append(("vector_plot_full", aux_vector_plot_full))
            # Priority 4: figure context
            if figure_gen.has_figures():
                supplement_blocks.append(("figure_ctx", figure_gen.generate_figure_context_for_llm(section_type)))

        elif section_type == "introduction":
            supplement_blocks.append(("receptor_ctx", receptor_llm_context))

        elif section_type in ("conclusion", "abstract"):
            # v9.32: Conclusion/Abstract also need temporal coordination summary for comprehensive coverage
            supplement_blocks.append(("comovement", comovement_llm_context))
            supplement_blocks.append(("temporal_kinase", temporal_kinase_cascade_llm_context))

        # v9.31: Add blocks respecting budget
        current_len = base_len
        added_blocks = []
        skipped_blocks = []
        for block_name, block_text in supplement_blocks:
            if not block_text:
                continue
            block_len = len(block_text)
            if current_len + block_len + 4 <= budget:  # +4 for "\n\n"
                prompt += "\n\n" + block_text
                current_len += block_len + 2
                added_blocks.append(f"{block_name}({block_len:,})")
            else:
                skipped_blocks.append(f"{block_name}({block_len:,})")

        if added_blocks:
            logger.info(f"[v9.31] {section_type}: added {len(added_blocks)} blocks: {', '.join(added_blocks)}")
        if skipped_blocks:
            logger.warning(f"[v9.31] {section_type}: SKIPPED {len(skipped_blocks)} blocks (budget {budget:,}): {', '.join(skipped_blocks)}")

        # v9.31: Cascading failure prevention — if Results used fallback,
        # inject direct data context for Discussion/Conclusion/Abstract
        results_is_fallback = (
            snap_prev.get("results", "").startswith("The PTM analysis")
            and len(snap_prev.get("results", "").split()) < 200
        )
        if results_is_fallback and section_type in ("discussion", "conclusion", "abstract"):
            ptm_summary_for_cascade = _ptm_summary_text(parsed_ptms[:30], detail_count=20)
            cascade_supplement = (
                f"\n\n=== DIRECT PTM DATA (Results section was incomplete) ===\n"
                f"{ptm_summary_for_cascade}\n"
                f"=== END DIRECT PTM DATA ===\n"
            )
            remaining = budget - len(prompt)
            if remaining > len(cascade_supplement):
                prompt += cascade_supplement
                logger.info(f"[v9.31] Injected direct PTM data into {section_type} (cascade failure prevention)")

        max_tok = section_max_tokens.get(section_type, 8192)

        # v9.31: Final safety truncation (should rarely trigger with budget system)
        prompt_len = len(prompt)
        if prompt_len > MAX_PROMPT_CHARS:
            logger.warning(
                f"[v9.31] {section_type} prompt exceeds absolute limit ({prompt_len:,} > {MAX_PROMPT_CHARS:,}). "
                f"Truncating."
            )
            prompt = prompt[:MAX_PROMPT_CHARS] + "\n\n[... prompt truncated for context window limit ...]"
        logger.info(
            f"[v9.31] {section_type}: final_prompt={len(prompt):,} chars (budget={budget:,}), "
            f"max_tokens={max_tok}, provider={llm.provider}, model={llm.model}"
        )

        # v9.1: Use PTM-aware system prompt from vocabulary dictionary
        ptm_system_prompt = get_system_prompt_for_ptm(ptm_type)

        # v9.30: Use generate_with_retry for robust LLM calls
        min_words = SECTION_MIN_WORDS.get(section_type, 100)
        content = llm.generate_with_retry(
            prompt,
            system_prompt=ptm_system_prompt,
            temperature=llm_temperature,
            max_tokens=max_tok,
            min_words=min_words,
            section_name=section_type.capitalize(),
            max_retries=2,
        )

        if content is None or content.startswith("[LLM Error"):
            error_detail = content if content else "generate_with_retry returned None"
            logger.error(
                f"[v9.30] LLM FAILED for section '{section_type}': {error_detail}. "
                f"Using fallback text. Provider={llm.provider}, Model={llm.model}, "
                f"Prompt size={prompt_len:,} chars, max_tokens={max_tok}"
            )
            if cb:
                cb(70, f"WARNING: LLM failed for {section_type} — using fallback text")
            content = _fallback_section(section_type, research_results, validated_hypotheses, parsed_ptms)

        # Strip self-generated section headings from LLM output
        # LLM sometimes adds its own ## headings (e.g., "## Results Discussion")
        # which conflicts with the report assembly logic
        content = _strip_llm_section_heading(content, section_type)

        # Title post-processing: clean up LLM output to extract pure title text
        if section_type == "title":
            import re as _title_re
            # Remove common prefixes like "Title:" or "# "
            content = _title_re.sub(r'^(?:Title\s*:\s*|#\s+)', '', content.strip())
            # Remove surrounding quotes
            content = content.strip('"\'“”‘’')
            # Take only the first line if LLM generated multiple lines
            content = content.split('\n')[0].strip()
            logger.info(f"[TITLE] Generated title: {content}")

        # v98d: Fix Log2FC decimal fragmentation and strip protective brackets
        if section_type in ("results", "discussion", "conclusion"):
            try:
                content = postprocess_log2fc_formatting(content)
            except Exception as e:
                logger.warning(f"[v98d] Log2FC formatting postprocess failed (non-fatal): {e}")

        # v98: Post-processing validation for results and discussion
        if v98_protein_names and section_type in ("results", "discussion"):
            try:
                validation = validate_llm_output_against_data(
                    content, v98_protein_names, v98_log2fc_values,
                    section_name=section_type.capitalize(), strict_mode=False
                )
                if validation["hallucinated_proteins"]:
                    logger.warning(
                        f"[v98] {section_type}: {len(validation['hallucinated_proteins'])} "
                        f"hallucinated proteins detected (not removed): "
                        f"{', '.join(validation['hallucinated_proteins'][:5])}"
                    )
                logger.info(f"[v98] {section_type} validation score: {validation['validation_score']:.1%}")
            except Exception as e:
                logger.warning(f"[v98] {section_type} validation failed (non-fatal): {e}")


        return section_type, content

    # ── Phase 1: independent sections (parallel) ──
    phase1_set = {"introduction", "results", "methods"}
    phase1_sections = [s for s in SECTION_ORDER if s in phase1_set]
    phase2_sections = [s for s in SECTION_ORDER if s not in phase1_set]

    workers = min(_LLM_WORKERS, len(phase1_sections))
    logger.info(f"[writer] Phase 1: writing {phase1_sections} in parallel ({workers} workers)")
    if cb:
        cb(70, f"Writing {len(phase1_sections)} sections in parallel")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_write_one, st, {}): st for st in phase1_sections}
        for fut in as_completed(futs):
            st, content = fut.result()
            sections[st] = content
            prev_sections[st] = content
            if cb:
                cb(74, f"Section {st} done")
            logger.info(f"[writer] Phase 1 done: {st} ({len(content):,} chars)")

    # ── Phase 2: dependent sections (sequential) ──
    logger.info(f"[writer] Phase 2: writing {phase2_sections} sequentially")
    for i, section_type in enumerate(phase2_sections):
        if cb:
            pct = 76 + (i / max(len(phase2_sections), 1)) * 14
            cb(pct, f"Writing {section_type}")
        st, content = _write_one(section_type, dict(prev_sections))
        sections[st] = content
        prev_sections[st] = content

    if cb:
        cb(90, "All sections written")

    # v9.35: Track which sections used fallback (LLM failure detection)
    fallback_sections = [s for s in sections if sections[s] == _fallback_section(s, research_results, validated_hypotheses, parsed_ptms)]
    if fallback_sections:
        logger.warning(
            f"[v9.35] LLM FALLBACK DETECTED: {len(fallback_sections)}/{len(sections)} sections "
            f"used fallback text: {fallback_sections}. "
            f"Provider={llm.provider}, Model={llm.model}"
        )

    return {
        "sections": sections,
        "collected_references": all_references,
        "llm_fallback_sections": fallback_sections,
    }


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_section_prompt(
    section_type: str, research_results: list, hypotheses: list,
    network: dict, ptms: list, context: dict, questions: list,
    prev_sections: dict, retriever: RAGRetriever,
    comprehensive_summary: str = "",
    all_references: list = None,
    ptm_detail_count: int = 30,
    chromadb_results: int = 10,
    temporal_kinase_cascade: dict = None,
    inferred_receptors: list = None,
) -> str:
    """Build LLM prompt for a specific report section."""
    all_references = all_references or []

    single_time_point = context.get("single_time_point", False)
    single_tp_directive = (
        "\n**IMPORTANT: Single timepoint experiment** — This is NOT a time-course study. "
        "Do NOT discuss temporal dynamics, time-course, sequential changes across timepoints, trajectory patterns, or progression over time. "
        "Focus on the observed PTM changes at this single timepoint.\n\n"
        if single_time_point
        else ""
    )

    # --- ChromaDB vector-search literature ---
    lit_context = ""
    ptm_type_label = context.get("ptm_type", "phosphorylation")
    ptm_type_str = ptm_type_label  # alias for backward compat across all sections
    keywords = [
        context.get("tissue") or context.get("cell_type", ""),
        context.get("treatment", ""),
        (context.get("biological_question") or "")[:80],
        ptm_type_label,
        "signaling",
    ]
    keywords = [k for k in keywords if k and isinstance(k, str)]
    # Introduction has its own dedicated (larger) Chroma search — skip the generic one
    rag_results = (
        retriever.search_for_section(section_type, keywords, n_results=chromadb_results)
        if section_type != "introduction" else []
    )
    if rag_results:
        ref_lines = []
        for idx, r in enumerate(rag_results[:chromadb_results], 1):
            title = r.get("title", "Unknown")
            ref_lines.append(f"--- Reference [{idx}] ---\nSource: {title}\n{r['document'][:400]}")
        lit_context = (
            "\n\n**Published Literature Context (Vector Search):**\n"
            "The following excerpts are from previously published studies. "
            "Each excerpt is labeled with a reference number [n]. When citing, use brackets "
            "(e.g., 'as previously reported [1]'). NEVER mention 'ChromaDB' or 'knowledge base'.\n\n"
            + "\n\n".join(ref_lines)
        )

    # v9.35: Cascade-specific ChromaDB search — pathway-level evidence
    cascade_lit_context = ""
    if section_type in ("results", "discussion") and temporal_kinase_cascade:
        cascade_results = retriever.search_for_cascade_pathways(
            temporal_kinase_cascade=temporal_kinase_cascade,
            inferred_receptors=inferred_receptors,
            ptm_type=ptm_type_label,
            n_results_per_query=3,
            max_queries=5,
        )
        if cascade_results:
            # Number cascade refs starting after general refs
            start_idx = len(rag_results) + 1 if rag_results else 1
            cascade_lines = []
            for idx, r in enumerate(cascade_results[:8], start_idx):
                title = r.get("title", "Unknown")
                cascade_ctx = r.get("cascade_context", "")
                cascade_lines.append(
                    f"--- Reference [{idx}] (Cascade: {cascade_ctx}) ---\n"
                    f"Source: {title}\n{r['document'][:400]}"
                )
            cascade_lit_context = (
                "\n\n**Pathway-Specific Literature Evidence (Cascade Search):**\n"
                "The following references were retrieved specifically for the kinase\u2192substrate "
                "signaling cascades identified in this experiment. Use these to provide "
                "pathway-level evidence when describing each signaling cascade.\n\n"
                + "\n\n".join(cascade_lines)
            )
            logger.info(f"[v9.35] Added {len(cascade_results)} cascade-specific references for {section_type}")

    # --- PubMed references from enriched PTM data ---
    pubmed_context = _format_pubmed_references(all_references, section_type, ptms)

    # PTM summary (with recent findings) — configurable detail count
    ptm_summary = _ptm_summary_text(ptms[:50], detail_count=ptm_detail_count)
    hyp_summary = _hypothesis_summary_text(hypotheses[:5])

    tissue = context.get("tissue") or context.get("cell_type") or "the experimental system"
    treatment = context.get("treatment", "the applied treatment")
    biological_question = (context.get("biological_question") or "").strip()
    organism = context.get("organism", "")
    timepoints_raw = context.get("timepoints") or context.get("conditions") or []
    special_conditions = context.get("special_conditions", "")
    questions_str = "\n".join(f"  Q{i+1}: {q}" for i, q in enumerate(questions))
    bio_focus_line = f"\nResearch focus (Biological Question): {biological_question}\n" if biological_question else ""

    # v8.6: Analysis Context Block — injected into every section prompt
    tp_str = ", ".join(str(t) for t in timepoints_raw) if timepoints_raw else "not specified"
    analysis_context_block = (
        f"\n\n========== ANALYSIS CONTEXT (MUST GUIDE ALL WRITING) ==========\n"
        f"Cell type / Tissue: {tissue}\n"
    )
    if organism:
        analysis_context_block += f"Organism: {organism}\n"
    analysis_context_block += (
        f"Treatment / Stimulus: {treatment}\n"
        f"Time points: {tp_str}\n"
    )
    if biological_question:
        analysis_context_block += f"Biological Question: {biological_question}\n"
    if special_conditions:
        analysis_context_block += f"Special Conditions: {special_conditions}\n"
    analysis_context_block += (
        f"PTM type: {ptm_type_label}\n"
        f"=============================================================\n\n"
        f"**BIOLOGICAL SCOPE CONSTRAINT (CRITICAL):**\n"
        f"- ALL interpretations MUST remain within the biological context of {tissue} responding to {treatment}.\n"
        f"- Do NOT discuss biological processes, pathways, or disease contexts that are biologically distant from this experimental system.\n"
        f"- For example, if the study is about osteocyte signaling, do NOT extensively discuss neuronal signaling, immune cell-specific pathways, or cancer biology unless directly relevant to the observed PTM changes.\n"
        f"- Every paragraph must logically connect back to: How does {treatment} affect {ptm_type_label} in {tissue}?\n"
        f"- Limit your interpretation to: (1) the experimental data (TSV/MD files), (2) ChromaDB literature, and (3) PubMed references provided below.\n"
        f"- Do NOT fabricate connections to unrelated biological systems.\n"
        f"\n"
        f"**NAMING RULE (MANDATORY):**\n"
        f"- ALWAYS use the ACTUAL names: '{tissue}' for cell type, '{treatment}' for treatment.\n"
        f"- NEVER use generic placeholders like 'the experimental system', 'the applied treatment', "
        f"'the stimulus', 'the biological system', or 'the treatment condition'.\n"
        f"- Every mention of the cell type or treatment MUST use the real name.\n"
        f"- Example: Instead of 'the applied treatment induced {ptm_type_label}', write "
        f"'{treatment} induced {ptm_type_label} in {tissue}'.\n"
    )

    # v9.1: PTM-type-specific interpretation framework (from vocabulary dictionary)
    normalized_ptm = get_normalized_ptm_type(ptm_type_label)
    if normalized_ptm in ("ubiquitylation",):
        analysis_context_block += (
            f"\n**UBIQUITYLATION-SPECIFIC INTERPRETATION FRAMEWORK (CRITICAL):**\n"
            f"Ubiquitylation is NOT solely a degradation signal. You MUST distinguish\n"
            f"the functional outcome based on chain type, linkage, and biological context:\n\n"
            f"| Chain Type | Primary Function | Biological Process |\n"
            f"|------------|------------------|-----------------------|\n"
            f"| K48 polyUb | Proteasomal degradation | Protein turnover, quality control |\n"
            f"| K63 polyUb | Non-degradative signaling | NF-kB signaling, DNA damage response, endosomal sorting |\n"
            f"| K11 polyUb | Cell cycle regulation, ERAD | Mitotic degradation, ER-associated degradation |\n"
            f"| K27 polyUb | Innate immune signaling | STING/MAVS pathway, interferon response |\n"
            f"| K29 polyUb | Wnt signaling regulation | Proteasomal & lysosomal degradation |\n"
            f"| K33 polyUb | Kinase regulation | TCR signaling, AMPK regulation, intracellular trafficking |\n"
            f"| K6 polyUb  | DNA repair | Mitophagy, BRCA1/BARD1-mediated DNA repair |\n"
            f"| M1 (linear) | NF-kB activation | LUBAC-mediated immune signaling, TNF response |\n"
            f"| Mono-Ub   | Signaling & trafficking | Histone regulation, endocytosis, membrane protein sorting |\n"
            f"| Multi-mono | Endocytosis | Receptor internalization, lysosomal targeting |\n\n"
            f"**Interpretation Rules:**\n"
            f"1. When a ubiquitylated protein shows INCREASED modification + DECREASED protein level \u2192 likely K48 proteasomal degradation\n"
            f"2. When a ubiquitylated protein shows INCREASED modification + STABLE protein level \u2192 likely non-degradative signaling (K63, M1, mono-Ub)\n"
            f"3. When interpreting ubiquitylation of signaling proteins (kinases, receptors), consider:\n"
            f"   - Is this activating (K63-linked) or degradative (K48-linked)?\n"
            f"   - Does the protein's known biology suggest trafficking (mono-Ub) or signal amplification (K63)?\n"
            f"4. For nuclear proteins: consider histone ubiquitylation (H2A-K119, H2B-K120) and its role in transcription regulation\n"
            f"5. For mitochondrial proteins: consider mitophagy signaling (PINK1/Parkin, K6/K63 chains)\n"
            f"6. ALWAYS state which functional category you are interpreting (degradation vs signaling vs trafficking vs DNA repair vs immune response)\n"
            f"7. If chain type is unknown from the data, discuss the MOST LIKELY functional outcome based on:\n"
            f"   - The substrate protein's known biology\n"
            f"   - Whether protein abundance changes correlate with ubiquitylation changes\n"
            f"   - The biological context of {tissue} responding to {treatment}\n"
            f"\n"
            f"**Key E3 Ligase / DUB Interpretation:**\n"
            f"- If upstream E3 ligase is identified, discuss its substrate specificity and chain type preference\n"
            f"- If DUB (deubiquitylase) activity is implied (decreased ubiquitylation), discuss which DUB family may be responsible\n"
            f"- E3-substrate relationships are analogous to kinase-substrate relationships in phosphorylation\n"
        )

    # v9.1: Inject PTM vocabulary block for ALL PTM types (not just ubiquitylation)
    # This is the primary mechanism to prevent cross-contamination
    vocab_block = build_vocabulary_prompt_block(ptm_type_label)
    analysis_context_block += vocab_block

    combined_lit = lit_context + cascade_lit_context + pubmed_context

    if section_type == "abstract":
        intro = prev_sections.get("introduction", "")[:1500]
        results = prev_sections.get("results", "")[:2000]
        discussion = prev_sections.get("discussion", "")[:1500]
        conclusion = prev_sections.get("conclusion", "")[:800]

        # Build ChromaDB high-confidence matching context for Abstract
        chromadb_abstract_context = ""
        if rag_results:
            high_confidence = [r for r in rag_results if r.get("relevance", 0) >= 0.6 or r.get("combined_score", 0) >= 0.6]
            if high_confidence:
                match_lines = []
                for idx, r in enumerate(high_confidence[:8], 1):
                    title_str = r.get("title", "Unknown")
                    score = r.get("combined_score", r.get("relevance", 0))
                    match_lines.append(
                        f"  [{idx}] (Confidence: {score:.2f}) {title_str}\n"
                        f"      Key finding: {r['document'][:300]}"
                    )
                chromadb_abstract_context = (
                    "\n\n**High-Confidence Literature Matches for Research Questions:**\n"
                    "The following literature entries showed strong relevance to the research questions. "
                    "Incorporate these findings into the abstract to highlight validated results and their significance.\n\n"
                    + "\n\n".join(match_lines)
                )

        return f"""Write an Abstract (~300-400 words) for this PTM analysis report.
{analysis_context_block}
{single_tp_directive}
Experimental System: {tissue}, {treatment}{bio_focus_line}
Research Questions:
{questions_str}

Summary of Introduction:
{intro}

Summary of Results:
{results}

Summary of Discussion:
{discussion}

Summary of Conclusion:
{conclusion}
{chromadb_abstract_context}

INSTRUCTIONS:
- The abstract MUST include: background context, methods overview, key findings with specific PTM sites, and significance.
- You MUST mention the treatment/stimulus ({treatment}) by name in the abstract. Never use generic terms like 'the treatment'.
- For each Research Question, identify the most significant PTM findings and their biological implications.
- If high-confidence literature matches are provided above, explicitly mention how the experimental results align with or diverge from published literature.
- **PTM Activity Profile Framework**: Frame the abstract through the PTM activity profile approach — describe how PTM activation states reveal the signaling logic of the cellular response.
- **Temporal signaling**: Briefly describe the receptor → kinase → substrate → effector cascade and its temporal evolution. Mention that Non-PTM downstream interactors provided concordant validation evidence for the identified signaling axes.
- **Temporally coordinated groups**: Mention the major temporally coordinated substrate groups and their biological significance.
- Highlight the cell signaling commonalities among activated proteins based on PTM activity profile values.
- Write a comprehensive abstract that captures ALL major findings. Be specific about PTM sites using the correct terminology: '{get_vocabulary(ptm_type_label)["modification_at_site"].format(site=get_vocabulary(ptm_type_label)["site_prefixes"][0] + "48", gene="GENE_NAME")}'. NEVER use terminology from a different PTM type.
{combined_lit}"""

    elif section_type == "introduction":
        comp_intro = ""
        if comprehensive_summary:
            comp_intro = f"\n\nDetailed Analysis Context (from prior comprehensive analysis):\n{comprehensive_summary[:4000]}\n"

        # Enhanced ChromaDB context for Introduction — retrieve MORE results from ChromaDB
        # For introduction, we fetch double the normal amount to provide richer background
        intro_rag_results = retriever.search_for_section("introduction", keywords, n_results=chromadb_results * 2)
        intro_chromadb_emphasis = ""
        if intro_rag_results:
            intro_ref_lines = []
            for idx, r in enumerate(intro_rag_results[:min(chromadb_results * 2, 20)], 1):
                title_str = r.get("title", "Unknown")
                source_type = r.get("source_type", "research_article")
                intro_ref_lines.append(
                    f"--- ChromaDB Reference [{idx}] ({source_type}) ---\n"
                    f"Source: {title_str}\n{r['document'][:500]}"
                )
            intro_chromadb_emphasis = (
                "\n\n**CRITICAL — Published Literature from Collection (ChromaDB Vector Search):**\n"
                "The following excerpts are from review papers, textbooks, and research articles in the collection. "
                "You MUST heavily reference these in the Introduction to establish the scientific background. "
                "Cite using numbered brackets (e.g., [1], [2]). NEVER mention 'ChromaDB' or 'knowledge base'. "
                "Use these references to:\n"
                "  - Explain the biological context of the experimental system\n"
                "  - Describe known signaling pathways relevant to the research questions\n"
                "  - Identify current knowledge gaps that this study addresses\n"
                "  - Provide background on key proteins and PTM sites identified in the data\n\n"
                + "\n\n".join(intro_ref_lines)
            )

        return f"""Write a comprehensive Introduction section (~1500-2500 words) for this PTM analysis report.
{analysis_context_block}
{single_tp_directive}
Experimental System: {tissue}, {treatment}{bio_focus_line}
Research Questions:
{questions_str}

Key PTM sites identified:
{ptm_summary}
{comp_intro}

Structure (7-9 paragraphs):
1. Background on post-translational modifications and their critical role in cellular signaling
2. Specific background on {ptm_type_label} and its regulatory importance
3. The PTM activity profile approach: Introduce the concept of using PTM modification states as activity profiles to interpret proteomics data. Explain how PTM Log2FC values serve as indicators of signaling pathway activation direction and magnitude.
4. Relevance of the experimental system ({tissue}, {treatment}) — use the ChromaDB literature references below extensively
5. Current understanding and knowledge gaps in this area — cite the provided references heavily
6. PTM analysis methodology including mass spectrometry-based proteomics
7. Overview of the key PTM sites identified and their known biological roles — cross-reference with ChromaDB literature
8. The importance of temporal analysis: receptor → kinase → substrate → effector cascade and temporally coordinated substrate group analysis for understanding signal propagation dynamics
9. Research questions and specific objectives of this study

IMPORTANT: Write a thorough, detailed introduction. The ChromaDB collection references below are your PRIMARY source for background information. Cite as many of them as possible to establish context. Discuss the biological significance of each research question. Use the comprehensive analysis context provided above to enrich your writing with specific PTM data and findings.
{intro_chromadb_emphasis}
{pubmed_context}"""

    elif section_type == "results":
        research_str = ""
        for i, r in enumerate(research_results):
            stats = r.get("statistics", {})
            research_str += f"\nQ{i+1}: {r['question']}\n"
            research_str += f"  Relevant PTMs: {r.get('relevant_ptm_count', 0)}\n"
            research_str += f"  Upregulated: {stats.get('upregulated', 0)}, Downregulated: {stats.get('downregulated', 0)}\n"
            top_act = r.get("activated", [])[:5]
            if top_act:
                research_str += "  Key activated: " + ", ".join(f"{p['gene']}-{p['position']}(FC={p['ptm_relative_log2fc']})" for p in top_act) + "\n"
            enriched = r.get("enriched_pathways", [])[:5]
            if enriched:
                research_str += "  Enriched pathways: " + ", ".join(
                    p.get("pathway", p.get("name", str(p))) if isinstance(p, dict) else str(p)
                    for p in enriched
                ) + "\n"

        network_info = ""
        net = network or {}
        if net.get("legends", {}).get("full_legend"):
            network_info = f"\n\nNetwork Analysis:\n{net['legends']['full_legend'][:800]}"

        comp_ctx = ""
        if comprehensive_summary:
            comp_ctx = f"\n\nDetailed Analysis Context (from prior comprehensive analysis):\n{comprehensive_summary[:6000]}\n"

        # GAP C: Build RQ direct-answer structure
        rq_answer_structure = ""
        if questions:
            rq_lines = ["\n## RESEARCH QUESTION DIRECT ANSWER STRUCTURE"]
            rq_lines.append("For EACH research question, you MUST provide a subsection (### heading) that includes:")
            rq_lines.append("1. **Direct Answer**: A clear 1-2 sentence answer to the question")
            rq_lines.append("2. **Time Course Table** (if multi-timepoint): Show how key PTMs change across timepoints")
            rq_lines.append("3. **Functional Interpretation**: What the PTM changes mean biologically")
            rq_lines.append("4. **Alternative Explanations**: Other possible interpretations of the data")
            rq_lines.append("5. **Testable Prediction**: A specific prediction that could validate the finding")
            rq_lines.append("")
            for i, q in enumerate(questions, 1):
                rq_lines.append(f"### Q{i}: {q}")
                rq_lines.append(f"  → You MUST start with: 'In direct response to Q{i}, ...'")
                rq_lines.append(f"  → Then provide the 5 elements listed above.")
                rq_lines.append("")
            rq_answer_structure = "\n".join(rq_lines)

        # Build treatment emphasis directive
        treatment_emphasis = ""
        if treatment and treatment != "the applied treatment":
            treatment_emphasis = (
                f"\n\n**CRITICAL \u2014 TREATMENT CONTEXT:**\n"
                f"The treatment/stimulus in this study is: **{treatment}**\n"
                f"You MUST mention '{treatment}' by name throughout the Results section when describing PTM changes. "
                f"Do NOT use generic phrases like 'the treatment' or 'the stimulus' \u2014 always use the specific name '{treatment}'. "
                f"Frame all PTM changes as responses to {treatment} stimulation.\n"
            )

        # v8.9.1: Inject Fig 1 pathway list into Results prompt
        fig1_pw_results = ""
        fig1_pw_list = network.get("fig1_pathway_names", []) if network else []
        if fig1_pw_list:
            pw_numbered = "\n".join(f"  {i}. {pw}" for i, pw in enumerate(fig1_pw_list[:20], 1))
            fig1_pw_results = (
                f"\n\n**FIGURE 1 — 3-LAYER PATHWAY ENRICHMENT RESULTS (KEGG + Reactome + STRING Indirect):**\n"
                f"The following signaling pathways were identified through multi-source enrichment analysis "
                f"and are displayed in Figure 1 (Canonical Pathway Distribution), ranked by cumulative |Log2FC| score:\n"
                f"{pw_numbered}\n\n"
                f"CRITICAL INSTRUCTIONS FOR RESULTS SECTION:\n"
                f"1. You MUST explicitly discuss the TOP 5 pathways from this list by name in the Results section.\n"
                f"2. For each top pathway, explain which PTM proteins contribute to it and their functional significance.\n"
                f"3. Reference 'Figure 1' when discussing pathway enrichment patterns.\n"
                f"4. Do NOT claim a pathway is 'enriched in our analysis' if it is not in this list.\n"
                f"5. If a pathway like 'PI3K-Akt signaling' or 'MAPK signaling' appears in this list, "
                f"it MUST be prominently discussed as a key finding.\n"
            )

        entity_label = "E3 Ligase" if ptm_type_label.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"
        entity_label_lower = entity_label.lower()

        return f"""Write a detailed Results section (MINIMUM 1500 words, target 3000-5000 words) for this PTM analysis report.
{analysis_context_block}
{single_tp_directive}
{treatment_emphasis}
{fig1_pw_results}

=== PTM ACTIVITY PROFILE INTERPRETATION FRAMEWORK (CORE METHODOLOGY) ===
This report uses the **PTM activity profile** approach: interpreting proteomics data through the lens of
PTM-modified protein activation states. The key principle is that PTM changes (e.g., phosphorylation
Log2FC) serve as activity indicators showing the direction and magnitude of signaling pathway activation.

You MUST interpret ALL findings through this framework:
1. **Activation-centric interpretation**: PTM Log2FC values indicate activation (+) or inhibition (-)
   of the modified protein. Use these as primary evidence for signaling pathway activity.
2. **Receptor → {entity_label} → Substrate → Non-PTM cascade**: Trace the signal flow from upstream
   receptors through {entity_label_lower}s to their substrates, and finally to non-PTM effector proteins.
   Describe HOW the signal propagates through each layer at each timepoint.
   **Non-PTM proteins as VALIDATION EVIDENCE**: When describing each {entity_label_lower}-substrate relationship,
   INLINE mention the Non-PTM effector proteins that support it as concordant downstream evidence.
   The NUMBER of concordant Non-PTM proteins strengthens confidence in the {entity_label_lower}-substrate axis.
   Do NOT list Non-PTM proteins separately — weave them into {entity_label_lower}-substrate discussions.
3. **Temporal signal propagation**: At each timepoint, describe which layer of the cascade
   is most active. Early timepoints often show receptor/{entity_label_lower} activation; later timepoints
   show substrate modification and non-PTM effector changes.
4. **Temporally coordinated substrate group analysis**: PTMs that change together across timepoints
   form temporally coordinated groups. For each group, explain:
   - What biological process or pathway unites the group members
   - How the group's temporal pattern (early transient, sustained, delayed) relates to its function
   - What distinguishes this group from other temporally coordinated groups
   - How these temporal patterns change across timepoints (which groups activate first, which follow)
5. **Quantitative evidence**: Always cite specific Log2FC values when making claims about
   activation or inhibition. Use the PTM activity profile magnitude to rank the importance of findings.
=== END PTM ACTIVITY PROFILE FRAMEWORK ===

Research Findings:
{research_str}

PTM Data:
{ptm_summary}

{network_info}
{comp_ctx}
{rq_answer_structure}

{hyp_summary}
(NOTE: The above hypotheses are AUXILIARY context only — do NOT structure Results around them.
Results must be driven by the experimental data and the receptor→{entity_label_lower}→substrate→effector
signal flow evidence. Hypotheses may be referenced in Discussion for interpretive context.)

Structure (Figure-Centric, Nature Style):
Organize the Results section around the analytical figures and data, NOT around hypotheses.
Each major subsection should correspond to a key analytical output (figure or data table).

### Part 1: Pathway Enrichment Landscape (Figure 1)
- Present the top enriched signaling pathways from Figure 1 (3-Layer Pathway Enrichment)
- For each top pathway, identify which PTM proteins contribute and their Log2FC values
- Highlight pathway convergence: where do multiple PTMs converge on the same signaling axis?

### Part 2: {entity_label} Temporal Activity Analysis (Figure 2 — {entity_label} Activity Heatmap)
- Describe the temporal activation patterns visible in the {entity_label} Activity Heatmap
- Group {entity_label_lower}s by their temporal pattern: sustained activation, early-only, late-onset, spike, reversal
- For each pattern group, explain the biological significance:
  * Sustained: persistent signaling (e.g., stress response, proliferation)
  * Early-only: immediate-early response (e.g., MAPK cascade)
  * Late-onset: secondary/adaptive response
  * Spike: transient burst (e.g., checkpoint activation)
  * Reversal: feedback inhibition or pathway switching
- Quantify: number of co-activated substrates and sum FC for key {entity_label_lower}s
- Describe how temporally coordinated substrate groups relate to {entity_label_lower} activation timing

### Part 3: Signaling Pathway Cascade (Figure 3 — Pathway Diagram)
- Describe the inferred signaling pathway from upstream receptors through {entity_label_lower}s to substrates
- Trace the signal flow as a narrative: which receptor is activated first, which {entity_label_lower}s relay the signal,
  and which substrates/effectors are the final targets
- At each timepoint, describe which signaling layer is most active
- For each {entity_label_lower}-substrate axis, INLINE mention the number of concordant Non-PTM downstream
  interactors as validation evidence (e.g., 'supported by N concordant downstream effectors')
- Describe the evidence strength for each cascade connection:
  * Strong: confirmed {entity_label_lower}-substrate + concordant effectors + literature support
  * Moderate: predicted {entity_label_lower}-substrate + some effector concordance
  * Inferred: motif-based prediction only
- IMPORTANT: Describe the pathway in text as well (e.g., '{treatment} → EGFR → RAS/RAF → MEK1/2 → ERK1/2 → substrate {ptm_type_label}')

### Part 4: Key PTM Site Dynamics (Figure 4 — Context PTM Heatmap)
- For the most important PTM sites discussed in Parts 1-3, describe their temporal profiles in detail
- Group sites by functional category ({entity_label_lower} substrates, transcription factors, cytoskeletal, metabolic)
- Quantify: exact Log2FC values at each timepoint for key sites
- Highlight any unexpected patterns (e.g., a known activation site showing inhibition)

### Part 5: Research Question Integration
- For EACH research question, provide a dedicated subsection (### heading) that integrates
  findings from Parts 1-4 above:
  (1) Direct Answer framed through PTM activity profile activation
  (2) Evidence Summary: which figures/data support this answer
  (3) Testable Prediction based on the observed signaling cascade

IMPORTANT: Be thorough and detailed. Discuss each significant PTM site individually.
Include quantitative data (Log2FC values). Cite the provided references to support your findings.
This is the most important section of the report.
- You MUST explicitly name the treatment/stimulus ({treatment}) when describing PTM responses.
  Never use generic terms like 'the treatment'.
- ALL answers to research questions MUST be framed through the PTM activity profile / activation-centric perspective.
- Each Part should flow naturally into the next, building a coherent signaling narrative.

=== MANDATORY FIGURE REFERENCE RULES (v10.3) ===
You MUST include explicit inline figure references in the text using the format '(Figure N)'.
The report contains these main figures:
  - **Figure 1**: Canonical Pathway Distribution Bar Graph (pathway enrichment landscape)
  - **Figure 2**: Temporal {entity_label} Activity Heatmap (activation/inhibition direction per condition)
  - **Figure 3**: Context-Relevant PTM Site Heatmap (key PTM sites discussed in this report)
  - **Figure 4**: Inferred Signaling Pathway Diagram (receptor → {entity_label_lower} → substrate cascade)

For EACH Part, you MUST reference the corresponding figure AT LEAST ONCE:
  - Part 1 → '(Figure 1)' or 'As shown in Figure 1, ...'
  - Part 2 → '(Figure 2)' or 'The {entity_label_lower} temporal heatmap (Figure 2) reveals ...'
  - Part 3 → '(Figure 4)' or 'The pathway diagram (Figure 4) illustrates ...'
  - Part 4 → '(Figure 3)' or 'The PTM site heatmap (Figure 3) shows ...'

Do NOT omit figure references. Every analytical claim about pathway enrichment, {entity_label_lower} activity,
signaling cascades, or PTM dynamics MUST be anchored to its corresponding figure.
=== END FIGURE REFERENCE RULES ===
{combined_lit}"""

    elif section_type == "discussion":
        ptm_type_str = context.get("ptm_type", "phosphorylation")
        results_text = prev_sections.get("results", "")[:4000]
        comp_disc = ""
        if comprehensive_summary:
            comp_disc = f"\n\nDetailed Analysis Context:\n{comprehensive_summary[:4000]}\n"

        # GAP E: Inject Cell Signaling Commonality Analysis
        # v8.9.1: Use Fig 1 KEGG pathway names (from network_analysis) as primary source.
        # Fallback to DEFAULT_PATHWAYS keyword matching only if Fig 1 data is unavailable.
        cell_signaling_block = ""
        fig1_pw_names = network.get("fig1_pathway_names", []) if network else []
        if fig1_pw_names:
            # Use actual pathway names from Figure 1 (3-Layer: KEGG + Reactome + STRING Indirect)
            cs_lines = ["\n## CELL SIGNALING COMMONALITY ANALYSIS (from Figure 1 — 3-Layer Pathway Enrichment)"]
            cs_lines.append("The following signaling pathways were identified through multi-source enrichment ")
            cs_lines.append("(KEGG + Reactome + STRING Indirect) and displayed in Figure 1, ")
            cs_lines.append("ranked by cumulative |Log2FC| score:")
            for i, pw_name in enumerate(fig1_pw_names[:15], 1):
                cs_lines.append(f"  {i}. **{pw_name}**")
            cs_lines.append("")
            cs_lines.append("CRITICAL INSTRUCTIONS FOR DISCUSSION:")
            cs_lines.append("1. You MUST dedicate a subsection to 'Signaling Pathway Convergence' that discusses ")
            cs_lines.append("   how the top pathways from Figure 1 are interconnected.")
            cs_lines.append("2. For canonical signaling pathways (e.g., PI3K-Akt, MAPK, mTOR, Focal adhesion), ")
            cs_lines.append("   explain their biological significance in the context of this experiment.")
            cs_lines.append("3. Discuss how the PTM proteins in this study converge on these pathways ")
            cs_lines.append("   to produce coordinated cellular responses.")
            cs_lines.append("4. If you discuss pathways NOT in Figure 1, explicitly note they are from literature.")
            cs_lines.append("5. Reference 'Figure 1' when discussing pathway enrichment findings.")
            cs_lines.append("")
            cell_signaling_block = "\n".join(cs_lines)
        elif ptms:
            # Fallback: DEFAULT_PATHWAYS keyword matching
            from report_generation.core.dynamic_prompt_generator import classify_gene_pathway, DEFAULT_PATHWAYS
            pathway_counts: Dict[str, int] = {}
            for ptm in ptms:
                gene = ptm.get("gene", "")
                matched = classify_gene_pathway(gene, DEFAULT_PATHWAYS)
                for pw in matched:
                    pathway_counts[pw] = pathway_counts.get(pw, 0) + 1
            if pathway_counts:
                top_pathways = sorted(pathway_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                cs_lines = ["\n## CELL SIGNALING COMMONALITY ANALYSIS"]
                cs_lines.append("The following pathways are most represented among the identified PTMs:")
                for pw, cnt in top_pathways:
                    desc = DEFAULT_PATHWAYS.get(pw, {}).get("description", "")
                    cs_lines.append(f"- **{pw}** ({cnt} PTMs): {desc}")
                cs_lines.append("")
                cs_lines.append("INSTRUCTION: Discuss how these shared pathway memberships suggest ")
                cs_lines.append("coordinated signaling responses. Identify cross-pathway interactions ")
                cs_lines.append("and potential signal integration points.")
                cs_lines.append("")
                cell_signaling_block = "\n".join(cs_lines)

        # Build treatment emphasis for Discussion
        treatment_emphasis_disc = ""
        if treatment and treatment != "the applied treatment":
            treatment_emphasis_disc = (
                f"\n\n**CRITICAL \u2014 TREATMENT CONTEXT:**\n"
                f"The treatment/stimulus is: **{treatment}**\n"
                f"You MUST refer to '{treatment}' by name when discussing PTM responses. "
                f"Never use generic terms like 'the treatment'.\n"
            )

        entity_label = "E3 Ligase" if ptm_type_str.lower().strip() in ("ubiquitylation", "ubiquitination") else "Kinase"
        entity_label_lower = entity_label.lower()

        return f"""Write a comprehensive Discussion section (MINIMUM 1500 words, target 2000-3000 words) for this PTM analysis report.
{analysis_context_block}
{single_tp_directive}
{treatment_emphasis_disc}

=== PTM ACTIVITY PROFILE DISCUSSION FRAMEWORK ===
This report uses the **PTM activity profile** approach. In the Discussion, you MUST:
- Interpret all findings through the lens of PTM activation states as signaling activity profiles
- Discuss the receptor → {entity_label_lower} → substrate → non-PTM effector cascade and how it evolves over time
- Analyze temporally coordinated substrate groups: what unites members of each group, how groups differ,
  and how temporal coordination patterns shift across timepoints
- Compare the observed signaling cascade with known canonical pathways from the literature
- Discuss whether the temporal signal propagation pattern suggests signal amplification,
  relay, feedback, or termination at each stage
- **Non-PTM proteins as VALIDATION EVIDENCE**: When discussing each {entity_label_lower}-substrate relationship,
  INLINE mention the Non-PTM effector proteins that support it. The number of concordant
  Non-PTM proteins strengthens confidence in the {entity_label_lower}-substrate axis. Use temporal concordance
  (time-lag between substrate PTM peak and Non-PTM protein change) as directional evidence.
  Do NOT create a separate section for Non-PTM proteins — weave them into {entity_label_lower}-substrate discussions.
=== END PTM ACTIVITY PROFILE DISCUSSION FRAMEWORK ===

Results Summary:
{results_text}

Interpretive Hypotheses (for contextualizing findings — not for structuring discussion):
{hyp_summary}

PTM Biological Context:
{ptm_summary}
{comp_disc}
{cell_signaling_block}

Structure (8 core topics):
1. **Primary Signaling Mechanism (PTM Activity Profile Perspective)**: Interpret the main PTM signaling mechanism through the PTM activity profile framework. How do the observed PTM activation profiles form a coherent signaling response? Trace the signal from receptor to {entity_label_lower} to substrate to effector.
2. **Temporal Signal Propagation**: Discuss how the signaling cascade evolves over time. Which signaling layers (receptor/{entity_label_lower}/substrate/effector) are active at each timepoint? Where are the signal relay and amplification points? How does the signal terminate or sustain?
3. **Temporally Coordinated Substrate Group Interpretation**: For each temporally coordinated group identified in the Results:
   - What is the biological commonality (shared pathway, function, or subcellular localization)?
   - How does this group's temporal pattern (early transient, sustained, delayed) relate to its function?
   - What distinguishes this group from other temporally coordinated groups?
   - How do these temporal coordination patterns change across timepoints (which groups lead, which follow)?
4. **Mechanistic Insight**: How specific PTM sites contribute to the observed response — relate each key site to known {('E3 ligase-substrate' if ptm_type_str.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'kinase-substrate')} relationships and signaling cascades
5. **Non-PTM Validation Evidence** (IMPORTANT — NOT a standalone section): When discussing each {entity_label_lower}-substrate relationship in topics 1-4 above, INLINE mention the Non-PTM effector proteins that support it. For example: 'The MAPK1→STAT3(S727) axis is further validated by concordant changes in N downstream interactors (e.g., HSP90, CDC37).' The NUMBER of concordant Non-PTM proteins strengthens the confidence in each {entity_label_lower}-substrate relationship. Use temporal concordance (time-lag) as evidence 
of signal directionality. Do NOT create a separate subsection for Non-PTM proteins — weave them into the {entity_label_lower}-substrate discussions above
6. **Cell Signaling Commonality**: Discuss shared pathway memberships and cross-pathway interactions. Explain whether signaling cascades represent signal amplification, relay, or termination
7. **Comparison with Literature**: Compare and contrast your findings with published studies. Specifically compare the observed PTM activity profiles with known signaling models from the literature.
8. **Limitations and Future Directions**: Acknowledge limitations and propose follow-up experiments

IMPORTANT: For each discussion point, provide evidence from your data AND from the literature. Cite the provided references extensively. ALL interpretations must be grounded in the PTM activity profile framework — activation states as signaling activity profiles.
- You MUST explicitly name the treatment/stimulus ({treatment}) throughout the Discussion. Never use generic terms.

=== MANDATORY FIGURE REFERENCE RULES (v10.5) ===
You MUST reference ALL four main figures in the Discussion. This is NON-NEGOTIABLE:
  - **Figure 1** (Pathway Distribution): Reference when discussing pathway convergence or enrichment.
  - **Figure 2** ({entity_label} Activity Heatmap): Reference when discussing temporal {entity_label_lower} patterns.
  - **Figure 3** (Context PTM Heatmap): Reference when discussing specific PTM site dynamics.
    You MUST write something like: 'The temporal dynamics of these key sites are visualized in Figure 3,
    which confirms the [pattern] observed across [timepoints].'
  - **Figure 4** (Pathway Diagram): Reference when discussing the receptor→{entity_label_lower}→substrate cascade.
    You MUST write something like: 'The inferred signaling cascade (Figure 4) illustrates how
    [receptor] signals propagate through [{entity_label_lower}] to [substrate].'

Use the format '(Figure N)' or 'as illustrated in Figure N'. Each figure MUST be referenced
at least once in the Discussion. If a figure is not referenced, the Discussion is INCOMPLETE.
=== END FIGURE REFERENCE RULES ===

=== MANDATORY SUPPLEMENTARY DISCUSSION (v10.5) ===
The Supplementary Figures contain temporally coordinated substrate groups (cluster analysis).
Even though these are in the Supplementary section, you MUST discuss them in the Discussion:
  - Mention that temporally coordinated substrate groups were identified (Supplementary Figures).
  - Discuss the biological significance of the major temporal coordination patterns observed.
  - Explain how these temporally coordinated groups support or extend the main findings.
  - Reference them as '(Supplementary Figures 1-N)' when discussing temporal coordination patterns.
This ensures the Discussion provides a comprehensive interpretation of ALL analytical results.
=== END SUPPLEMENTARY DISCUSSION ===
{combined_lit}"""

    elif section_type == "conclusion":
        results_text = prev_sections.get("results", "")[:2000]
        discussion_text = prev_sections.get("discussion", "")[:2000]

        return f"""Write a Conclusion section (MINIMUM 500 words, target 600-1000 words) for this PTM analysis report.
{analysis_context_block}
{single_tp_directive}
Research Questions:
{questions_str}

Interpretive Hypotheses (reference only):
{hyp_summary}

PTM Summary:
{ptm_summary}

Results Summary:
{results_text}

Discussion Summary:
{discussion_text}

Summarize through the PTM activity profile framework:
1. Key findings and how they answer each research question — framed through PTM activation vectors
2. **Temporal signaling narrative**: Summarize the receptor → kinase → substrate → effector cascade and how it evolves over time. Mention how Non-PTM downstream interactors provided validation evidence for key kinase-substrate relationships
3. **Temporally coordinated group summary**: Briefly describe the major temporally coordinated substrate groups, their biological significance, and how they relate to each other temporally
4. Novel insights revealed by this analysis — what is new compared to existing literature
5. Biological and clinical significance of the identified PTM changes
6. Potential therapeutic implications based on the identified signaling cascade
7. Limitations of the current study
8. Specific future research directions with concrete experimental suggestions

IMPORTANT: Be specific about findings — mention key PTM sites and their implications. The conclusion must capture the PTM activity profile interpretation: how PTM activation states reveal the signaling logic of the cellular response to {treatment}. Reference the results and discussion sections. Cite relevant references.
{combined_lit}"""

    # GAP B: Methods section
    elif section_type == "methods":
        # Collect methodology details from context
        organism = context.get("organism", "")
        tissue_str = context.get("tissue") or context.get("cell_type", "")
        treatment_str = context.get("treatment", "")
        ptm_type_str = context.get("ptm_type", "phosphorylation")
        n_ptms = len(ptms)
        n_conditions = len(set(p.get("condition", "") for p in ptms if p.get("condition")))
        has_network = bool(network and network.get("cytoscape_connected"))

        # v10.1: Build pipeline statistics block for Methods
        pipeline_stats = context.get("pipeline_statistics", {})
        stats_block = ""
        if pipeline_stats:
            step1 = pipeline_stats.get("step1_input", {})
            step2 = pipeline_stats.get("step2_quantification", {})
            step3 = pipeline_stats.get("step3_filtering", {})
            metadata = pipeline_stats.get("metadata", {})
            ptm_filt = step2.get("ptm_filtering", {})
            stats_lines = ["\nPipeline Processing Statistics (from actual preprocessing):"]
            if step1.get("total_proteins"):
                stats_lines.append(f"- Input proteins: {step1['total_proteins']}")
            if step1.get("total_ptm_sites"):
                stats_lines.append(f"- Input PTM sites: {step1['total_ptm_sites']}")
            if step1.get("conditions"):
                stats_lines.append(f"- Conditions: {', '.join(step1['conditions']) if isinstance(step1['conditions'], list) else step1['conditions']}")
            if ptm_filt.get("ptm_sites"):
                stats_lines.append(f"- PTM sites after filtering: {ptm_filt['ptm_sites']}")
            if ptm_filt.get("proteins_with_ptm"):
                stats_lines.append(f"- Proteins with PTM: {ptm_filt['proteins_with_ptm']}")
            if step3:
                if step3.get("significant_sites"):
                    stats_lines.append(f"- Significant PTM sites (|Log2FC| > threshold): {step3['significant_sites']}")
                if step3.get("fc_threshold"):
                    stats_lines.append(f"- Log2FC threshold: {step3['fc_threshold']}")
            if metadata.get("normalization_method"):
                stats_lines.append(f"- Normalization: {metadata['normalization_method']}")
            stats_block = "\n".join(stats_lines)

        return f"""Write a detailed Methods section (~800-1500 words) for this PTM analysis report.
{single_tp_directive}
Experimental System:
- Organism: {organism}
- Tissue/Cell type: {tissue_str}
- Treatment: {treatment_str}
- PTM type analyzed: {ptm_type_str}
- Total PTM sites: {n_ptms}
- Number of conditions: {n_conditions}
{stats_block}

The Methods section MUST cover:
1. **Sample Preparation and Mass Spectrometry**: Describe the general proteomics workflow for {ptm_type_str} analysis (enrichment strategy, LC-MS/MS, database search)
2. **PTM Data Processing**: Describe how PTM sites were quantified (Log2FC calculation, normalization, filtering criteria)
3. **Bioinformatics Analysis Pipeline**:
   a. Literature enrichment using PubMed, UniProt, KEGG, and STRING-DB databases
   b. {'E3 ligase-substrate prediction using UbiBrowser and literature mining' if ptm_type_str.lower().strip() in ('ubiquitylation', 'ubiquitination') else 'Kinase-substrate prediction using KEA3 (Kinase Enrichment Analysis 3)'}
   c. ChromaDB vector search for published literature context
   d. Hypothesis generation and validation against literature
4. **Network Analysis**: {'Cytoscape-based network visualization with force-directed layout, exported at 300 DPI' if has_network else 'Network analysis was performed to identify protein-protein interactions'}
5. **Statistical Analysis**: Describe significance thresholds and multiple testing correction
6. **Report Generation**: LLM-assisted scientific writing with anti-hallucination validation

IMPORTANT: Write in past tense. Be specific about computational tools and databases used. Do NOT include results or interpretations."""

    # GAP F: Suggestion section (validation experiments)
    elif section_type == "suggestion":
        results_text = prev_sections.get("results", "")[:3000]
        discussion_text = prev_sections.get("discussion", "")[:2000]
        conclusion_text = prev_sections.get("conclusion", "")[:1500]

        # Extract top PTMs for specific suggestions
        top_ptms_str = ""
        sorted_ptms = sorted(ptms, key=lambda x: abs(float(x.get("ptm_relative_log2fc", 0))), reverse=True)
        for p in sorted_ptms[:10]:
            gene = p.get("gene", "?")
            pos = p.get("position", "?")
            fc = float(p.get("ptm_relative_log2fc", 0))
            top_ptms_str += f"  - {gene}-{pos}: PTM Log2FC={fc:.2f}\n"

        return f"""Write a Suggested Validation Experiments section (~800-1200 words) for this PTM analysis report.
{single_tp_directive}
Key Findings Summary:
{results_text[:1500]}

Discussion Summary:
{discussion_text[:1000]}

Conclusion Summary:
{conclusion_text[:800]}

Top PTM sites to validate:
{top_ptms_str}

For EACH of the top 5-8 PTM findings, suggest:
1. **Western Blot Validation**: Specific antibodies for the {ptm_type_str} modification site. Use appropriate detection methods for {ptm_type_str} (e.g., site-specific antibodies, anti-{ptm_type_str} antibodies).
2. **Functional Assay**: How to test the biological consequence of the {ptm_type_str} modification. Use assays appropriate for {ptm_type_str} (e.g., {get_vocabulary(ptm_type_str)['enzyme_substrate_term']} analysis, {get_vocabulary(ptm_type_str)['enzyme_writer_generic']} identification).
3. **Pharmacological Intervention**: Specific inhibitors or activators to test the pathway (name actual drugs/compounds)
4. **In Vivo Validation**: Animal model or clinical sample approaches
5. **Time-Course Experiment**: Specific timepoints and conditions to validate temporal dynamics

Also include:
- **High-Throughput Validation**: Suggest multiplexed approaches (e.g., SILAC, TMT labeling)
- **Computational Follow-up**: Additional bioinformatics analyses (e.g., molecular dynamics, structural modeling)
- **Clinical Translation**: Steps toward therapeutic application if applicable

IMPORTANT: Be SPECIFIC — name actual antibodies, inhibitors, cell lines, and experimental conditions. Generic suggestions are not useful.
{combined_lit}"""

    if section_type == "title":
        intro = prev_sections.get("introduction", "")[:600]
        results = prev_sections.get("results", "")[:600]
        abstract = prev_sections.get("abstract", "")[:600]
        conclusion = prev_sections.get("conclusion", "")[:400]
        return f"""Generate a concise, specific academic paper title for this PTM analysis report.
{analysis_context_block}
Experimental System: {tissue}, {treatment}{bio_focus_line}
Research Questions:
{questions_str}

Abstract Summary: {abstract}
Introduction Summary: {intro}
Results Summary: {results}
Conclusion Summary: {conclusion}

INSTRUCTIONS:
- Output ONLY the title text, nothing else. No quotes, no "Title:" prefix, no explanation.
- The title should be BROAD enough to encompass ALL major findings in the report (temporal dynamics, transient burst, sustained changes, pathway analysis, network interactions).
- Do NOT make the title too narrow (e.g., focusing only on one pathway or one PTM site).
- Follow academic paper title conventions. Use the correct omics term for this PTM type: '{get_vocabulary(ptm_type_label)["omics_name"]}'. Example: 'Comprehensive {get_vocabulary(ptm_type_label)["omics_name"]} Analysis Reveals ...'. NEVER use an omics term from a different PTM type.
- Include the PTM type ({ptm_type_label}), the experimental system ({tissue}), and the treatment ({treatment}).
- The title should reflect the PTM activity profile approach: temporal {ptm_type_label} activation dynamics and signaling cascade analysis in {tissue} in response to {treatment}.
- Keep it under 25 words."""

    return f"Write the {section_type} section for a PTM analysis report.\n{single_tp_directive}{ptm_summary}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_llm_section_heading(content: str, section_type: str) -> str:
    """Remove self-generated ## headings from LLM output.

    LLMs sometimes prepend their own section heading (e.g., '## Results Discussion',
    '## Introduction') which conflicts with the report assembly logic that adds
    headings separately. This strips the first ## heading if it matches the
    section type, and converts any remaining ## headings to ### to avoid
    section-order conflicts in post-processing.
    """
    if not content:
        return content

    lines = content.split("\n")
    cleaned = []
    first_heading_stripped = False

    # Aliases that LLMs commonly generate for each section
    section_aliases = {
        "introduction": ["introduction", "background"],
        "results": ["results", "results and analysis", "results discussion", "findings"],
        "discussion": ["discussion", "results discussion", "results and discussion"],
        "conclusion": ["conclusion", "conclusions", "concluding remarks", "summary and conclusion"],
        "abstract": ["abstract", "summary"],
        "title": ["title"],
    }
    aliases = section_aliases.get(section_type, [section_type])

    for line in lines:
        stripped = line.strip()
        # Match ## heading lines
        heading_match = re.match(r'^##\s+(.+)$', stripped)
        if heading_match:
            heading_text = heading_match.group(1).strip().rstrip(":.")
            heading_lower = heading_text.lower()

            # Strip the first heading if it matches the section type
            if not first_heading_stripped and heading_lower in aliases:
                first_heading_stripped = True
                logger.debug(f"Stripped LLM self-generated heading: '{stripped}' from {section_type}")
                continue  # Skip this line entirely

            # Convert remaining ## headings to ### to avoid section-order conflicts
            # (but keep ### and deeper headings as-is)
            cleaned.append(line.replace("## ", "### ", 1))
            continue

        cleaned.append(line)

    result = "\n".join(cleaned).strip()
    return result


# Off-topic organism keywords that indicate non-mammalian studies
_OFF_TOPIC_KEYWORDS = [
    "arabidopsis", "rice ", "plant ", "plants ", "maize", "wheat",
    "drosophila", "c. elegans", "caenorhabditis", "zebrafish",
    "yeast", "saccharomyces", "schizosaccharomyces",
    "tobacco", "soybean", "barley", "tomato",
    "cattle", "beef cattle", "bovine", "porcine", "poultry",
    "insect", "nematode", "fungal", "fungi",
]


def _is_off_topic_reference(ref: dict) -> bool:
    """Check if a reference is off-topic based on title/journal/abstract keywords."""
    text = (
        (ref.get("title", "") + " " + ref.get("journal", "") + " " + ref.get("abstract_excerpt", ""))
        .lower()
    )
    for kw in _OFF_TOPIC_KEYWORDS:
        if kw in text:
            return True
    return False


def _collect_all_references(ptms: list) -> list:
    """Collect all unique PubMed references from enriched PTM data.
    
    v7.1: Added off-topic filtering to remove non-mammalian studies
    (plant biology, veterinary, invertebrate) and low-relevance references.
    """
    seen_pmids = set()
    refs = []
    filtered_count = 0
    for ptm in ptms:
        enr = ptm.get("rag_enrichment", {})
        for finding in enr.get("recent_findings", []):
            pmid = finding.get("pmid", "")
            if pmid and pmid not in seen_pmids:
                seen_pmids.add(pmid)
                ref_entry = {
                    "pmid": pmid,
                    "title": finding.get("title", ""),
                    "journal": finding.get("journal", ""),
                    "pub_date": finding.get("pub_date", ""),
                    "abstract_excerpt": finding.get("abstract_excerpt", "")[:400],
                    "relevance_score": finding.get("relevance_score", 0),
                    "gene": ptm.get("gene", ""),
                }
                # Filter out off-topic references (non-mammalian organisms)
                if _is_off_topic_reference(ref_entry):
                    filtered_count += 1
                    continue
                refs.append(ref_entry)
    if filtered_count > 0:
        logger.info(f"Filtered {filtered_count} off-topic references (non-mammalian/irrelevant)")
    refs.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)
    return refs


def _format_pubmed_references(all_refs: list, section_type: str, ptms: list) -> str:
    """Format PubMed references as prompt context, selecting the most relevant for each section."""
    if not all_refs:
        return ""

    n_refs = {"introduction": 20, "results": 25, "discussion": 20, "conclusion": 10, "abstract": 10}
    max_refs = n_refs.get(section_type, 15)
    selected = all_refs[:max_refs]

    lines = []
    for idx, ref in enumerate(selected, 1):
        entry = f"--- Reference [{idx}] (PMID: {ref['pmid']}) ---"
        entry += f"\nTitle: {ref['title']}"
        entry += f"\nJournal: {ref['journal']} ({ref['pub_date']})"
        entry += f"\nRelated gene: {ref['gene']}"
        if ref.get("abstract_excerpt"):
            entry += f"\nExcerpt: {ref['abstract_excerpt']}"
        lines.append(entry)

    return (
        f"\n\n**PubMed Literature References ({len(selected)} papers):**\n"
        "The following are published studies from PubMed that are directly relevant to "
        "the PTM sites analyzed in this study. Cite these using numbered brackets "
        "(e.g., [1], [2]) matching the reference numbers below. "
        "Integrate findings from these papers into your writing "
        "to provide comprehensive biological context.\n\n"
        + "\n\n".join(lines)
    )


def _ptm_summary_text(ptms: list, detail_count: int = 30) -> str:
    # Detect extreme Log2FC values and build warning
    extreme_ptms = []
    for p in ptms:
        fc = abs(p.get("ptm_relative_log2fc", 0))
        if fc > 15:
            extreme_ptms.append(f"{p['gene']}-{p['position']} (Log2FC={p['ptm_relative_log2fc']:.1f})")

    lines = []
    if extreme_ptms:
        lines.append(
            f"\n**IMPORTANT NOTE ON EXTREME LOG2FC VALUES:**\n"
            f"The following PTM sites show Log2FC > 15: {', '.join(extreme_ptms[:10])}\n"
            f"These extreme values likely represent binary ON/OFF events (absent→present or present→absent) "
            f"rather than proportional fold-changes. When discussing these PTMs, describe them as "
            f"'binary activation/deactivation events' or 'switch-like responses' rather than implying "
            f"a >30,000-fold change in abundance. This is a common artifact of mass spectrometry-based "
            f"quantification where a peptide is detected in one condition but not in the control.\n"
        )

    for i, p in enumerate(ptms):
        fc_val = p['ptm_relative_log2fc']
        fc_note = " [BINARY EVENT]" if abs(fc_val) > 15 else ""
        line = f"  {p['gene']}-{p['position']} ({p['ptm_type']}): PTM_FC={fc_val:.3f}, Prot_FC={p.get('protein_log2fc', 0):.3f}{fc_note}"
        enr = p.get("rag_enrichment", {})
        if i < detail_count and enr:
            if enr.get("function_summary"):
                line += f"\n    Function: {enr['function_summary'][:300]}"
            pathways = enr.get("pathways", [])
            if pathways:
                line += f"\n    Pathways: {', '.join(str(pw) for pw in pathways[:5])}"
            reg = enr.get("regulation", {})
            upstreams = reg.get("upstream_regulators", [])
            if upstreams:
                line += f"\n    Upstream regulators: {', '.join(str(u) for u in upstreams[:4])}"
            targets = reg.get("downstream_targets", [])
            if targets:
                line += f"\n    Downstream targets: {', '.join(str(t) for t in targets[:4])}"
            interactions = enr.get("string_interactions", [])
            if interactions:
                partners = [str(x.get("partner", x) if isinstance(x, dict) else x) for x in interactions[:4]]
                line += f"\n    Interactors: {', '.join(partners)}"
            diseases = enr.get("diseases", [])
            if diseases:
                line += f"\n    Disease relevance: {', '.join(str(d) for d in diseases[:3])}"
            findings = enr.get("recent_findings", [])
            if findings:
                finding_titles = [f.get("title", "")[:80] for f in findings[:2] if f.get("title")]
                if finding_titles:
                    line += f"\n    Related studies: {'; '.join(finding_titles)}"
        lines.append(line)
    return "\n".join(lines)


def _hypothesis_summary_text(hypotheses: list) -> str:
    """v9.35: Enhanced hypothesis summary — includes signaling pathway context,
    mechanism, supporting PTMs, and evidence strength instead of bare IF-THEN.
    Format: H1: <Pathway> (<cascade>) — confidence=0.xx
    """
    if not hypotheses:
        return ""
    lines = ["\nHypotheses (Signaling Pathway Context):"]
    for h in hypotheses:
        conf = h.get("confidence", 0)
        hid = h.get("id", "?")
        # Extract pathway/mechanism for concise signaling context
        mechanism = h.get("mechanism", "").strip()
        prediction = h.get("prediction", "").strip()
        condition = h.get("condition", "").strip()
        supporting = h.get("supporting_ptms", [])
        # Build pathway-centric summary
        ptm_str = ", ".join(str(p) for p in supporting[:4]) if supporting else ""
        # Validation evidence summary
        validation = h.get("validation", {})
        ev_count = validation.get("evidence_count", 0)
        sup_count = len(validation.get("supporting_evidence", []))
        validity = validation.get("validity_score", 0)
        ev_tag = ""
        if ev_count > 0:
            ev_tag = f" [literature: {sup_count}/{ev_count} supporting, validity={validity:.2f}]"
        # Compose: pathway-focused one-liner + mechanism
        line = f"  H{hid}: {prediction[:120]} (confidence={conf:.2f}){ev_tag}"
        if mechanism:
            line += f"\n        Mechanism: {mechanism[:200]}"
        if ptm_str:
            line += f"\n        Key PTMs: {ptm_str}"
        lines.append(line)
    return "\n".join(lines)


def _fallback_section(section_type: str, research_results: list, hypotheses: list, ptms: list) -> str:
    """Generate a basic section without LLM."""
    if section_type == "abstract":
        return f"This study analyzed {len(ptms)} post-translational modification sites. " \
               f"Analysis identified {len(hypotheses)} testable hypotheses."
    elif section_type == "introduction":
        return "Post-translational modifications (PTMs) play critical roles in cellular signaling."
    elif section_type == "results":
        lines = [f"A total of {len(ptms)} PTM sites were analyzed."]
        for r in research_results:
            lines.append(f"\n### {r['question']}\n{r.get('relevant_ptm_count', 0)} relevant PTMs were identified.")
        return "\n".join(lines)
    elif section_type == "discussion":
        return "The PTM analysis revealed significant regulatory changes."
    elif section_type == "conclusion":
        return "This analysis provides insights into PTM-mediated signaling."
    elif section_type == "title":
        return "Comprehensive Post-Translational Modification Analysis Report"
    return ""
