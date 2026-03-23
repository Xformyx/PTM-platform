"""
Writer Node — generates report sections using LLM + literature RAG.
Ported from multi_agent_system/agents/section_writers.py.

Generates: Abstract, Introduction, Results, Discussion, Conclusion.
Each section uses LLM with published literature context for integration.
"""

import logging
import re
from typing import Dict, List

from common.llm_client import LLMClient
from common.report_postprocessor import validate_llm_output_against_data, postprocess_log2fc_formatting
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

SYSTEM_PROMPT = (
    "You are a scientific writer specializing in post-translational modification (PTM) analysis. "
    "Write in formal academic English. Use flowing prose, not bullet points. "
    "Cite references using numbered brackets (e.g., [1], [2]) matching the provided reference list. "
    "Include as many relevant citations as possible to support your statements. "
    "NEVER mention 'ChromaDB' or 'knowledge base'. "
    "Be precise with PTM site nomenclature (e.g., 'phosphorylation at Ser165 of GENE_NAME'). "
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

    sections: Dict[str, str] = {}
    prev_sections: Dict[str, str] = {}

    for i, section_type in enumerate(SECTION_ORDER):
        if cb:
            pct = 70 + (i / len(SECTION_ORDER)) * 20
            cb(pct, f"Writing {section_type}")

        prompt = _build_section_prompt(
            section_type, research_results, validated_hypotheses,
            network_analysis, parsed_ptms, context, questions,
            prev_sections, retriever, comprehensive_summary,
            all_references, ptm_detail_count=ptm_detail_count,
            chromadb_results=chromadb_results,
        )

        # v98: Enhance prompt with anti-hallucination directives
        if v98_directive and section_type in ("results", "discussion"):
            prompt = v98_directive + "\n\n" + v98_structured_data + "\n\n" + prompt
            if v98_writing_example and section_type == "results":
                prompt += "\n\n" + v98_writing_example

        # GAP A: Inject 5 auxiliary data blocks for Results section
        if section_type == "results":
            aux_blocks = []
            ptm_data_summary = build_ptm_data_summary(parsed_ptms, ptm_type=ptm_type)
            if ptm_data_summary:
                aux_blocks.append(ptm_data_summary)
            nonptm_temporal = build_nonptm_temporal_analysis(network_results, timepoints, ptm_type=ptm_type)
            if nonptm_temporal:
                aux_blocks.append(nonptm_temporal)
            timelag_analysis = build_ptm_protein_timelag_analysis(network_results, timepoints, ptm_type=ptm_type)
            if timelag_analysis:
                aux_blocks.append(timelag_analysis)
            pathway_ctx = build_pathway_context_for_llm(parsed_ptms)
            if pathway_ctx:
                aux_blocks.append(pathway_ctx)
            signal_prop = build_signal_propagation_json(network_results, timepoints, ptm_type=ptm_type)
            if signal_prop:
                aux_blocks.append(signal_prop)
            if aux_blocks:
                prompt += "\n\n" + "\n\n".join(aux_blocks)
                logger.info(f"[GAP-A] Injected {len(aux_blocks)} auxiliary data blocks into Results prompt")

        # Inject figure context for Results/Discussion so LLM can reference figures
        if figure_gen.has_figures() and section_type in ("results", "discussion"):
            figure_ctx = figure_gen.generate_figure_context_for_llm(section_type)
            prompt += "\n\n" + figure_ctx

        max_tok = section_max_tokens.get(section_type, 8192)
        content = llm.generate(prompt, system_prompt=SYSTEM_PROMPT, temperature=llm_temperature, max_tokens=max_tok)

        if content.startswith("[LLM Error"):
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


        sections[section_type] = content
        prev_sections[section_type] = content

    if cb:
        cb(90, "All sections written")

    return {"sections": sections, "collected_references": all_references}


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
    keywords = [
        context.get("tissue") or context.get("cell_type", ""),
        context.get("treatment", ""),
        (context.get("biological_question") or "")[:80],
        ptm_type_label,
        "signaling",
    ]
    keywords = [k for k in keywords if k and isinstance(k, str)]
    rag_results = retriever.search_for_section(section_type, keywords, n_results=chromadb_results)
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
        f"- Example: Instead of 'the applied treatment induced phosphorylation', write "
        f"'{treatment} induced phosphorylation in {tissue}'.\n"
    )

    # v8.10: PTM-type-specific interpretation framework
    if ptm_type_label.lower().strip() in ("ubiquitylation", "ubiquitination"):
        analysis_context_block += (
            f"\n**UBIQUITYLATION-SPECIFIC INTERPRETATION FRAMEWORK (CRITICAL):**\n"
            f"Ubiquitylation is NOT solely a degradation signal. You MUST distinguish\n"
            f"the functional outcome based on chain type, linkage, and biological context:\n\n"
            f"| Chain Type | Primary Function | Biological Process |\n"
            f"|------------|------------------|--------------------|\n"
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
            f"1. When a ubiquitylated protein shows INCREASED modification + DECREASED protein level → likely K48 proteasomal degradation\n"
            f"2. When a ubiquitylated protein shows INCREASED modification + STABLE protein level → likely non-degradative signaling (K63, M1, mono-Ub)\n"
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

    combined_lit = lit_context + pubmed_context

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
- Highlight the cell signaling commonalities among activated proteins based on PTM Vector values.
- Write a comprehensive abstract that captures ALL major findings. Be specific about PTM sites (e.g., phosphorylation at Ser165 of GENE_NAME).
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

Structure (6-8 paragraphs):
1. Background on post-translational modifications and their critical role in cellular signaling
2. Specific background on {ptm_type_label} and its regulatory importance
3. Relevance of the experimental system ({tissue}, {treatment}) — use the ChromaDB literature references below extensively
4. Current understanding and knowledge gaps in this area — cite the provided references heavily
5. PTM analysis methodology including mass spectrometry-based proteomics
6. Overview of the key PTM sites identified and their known biological roles — cross-reference with ChromaDB literature
7. Research questions and specific objectives of this study

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

        return f"""Write a detailed Results section (MINIMUM 1500 words, target 3000-5000 words) for this PTM analysis report.
{analysis_context_block}
{single_tp_directive}
{treatment_emphasis}
{fig1_pw_results}
Research Findings:
{research_str}

PTM Data:
{ptm_summary}

{hyp_summary}
{network_info}
{comp_ctx}
{rq_answer_structure}

Structure:
- Present results for each research question as subsections with ### headings
- For EACH research question, provide: (1) Direct Answer, (2) Time Course Table, (3) Functional Interpretation, (4) Alternative Explanations, (5) Testable Prediction
- For each PTM site, describe: the specific modification, fold-change values, known biological function, pathway involvement, and disease relevance
- Include specific PTM sites with Log2FC values and their biological functions
- Reference enriched pathways and protein interactions
- Describe network relationships and regulatory mechanisms
- Discuss disease relevance where applicable
- Compare your findings with the published literature provided below

IMPORTANT: Be thorough and detailed. Discuss each significant PTM site individually. Include quantitative data (Log2FC values). Cite the provided references to support your findings. This is the most important section of the report.
- You MUST explicitly name the treatment/stimulus ({treatment}) when describing PTM responses. Never use generic terms like 'the treatment'.
{combined_lit}"""

    elif section_type == "discussion":
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

        return f"""Write a comprehensive Discussion section (MINIMUM 1500 words, target 2000-3000 words) for this PTM analysis report.
{analysis_context_block}
{single_tp_directive}
{treatment_emphasis_disc}
Results Summary:
{results_text}

Validated Hypotheses:
{hyp_summary}

PTM Biological Context:
{ptm_summary}
{comp_disc}
{cell_signaling_block}

Structure (7 core topics):
1. Primary Finding: The main PTM signaling mechanism identified — discuss in detail how the observed modifications form a coherent signaling response
2. Mechanistic Insight: How specific PTM sites contribute to the observed response — relate each key site to known kinase-substrate relationships and signaling cascades
3. Non-PTM Effector Signaling: Discuss the signaling roles of Non-PTM effector proteins (upstream regulators, scaffold/adaptors, transducers, downstream effectors). For each key Non-PTM protein, explain: (a) its relationship directionality with PTM proteins (upstream/downstream/feedback), (b) the canonical signaling pathway it belongs to, (c) how its temporal dynamics relate to PTM changes
4. Cell Signaling Commonality: Discuss shared pathway memberships and cross-pathway interactions among the identified PTMs (use the Cell Signaling Commonality Analysis above). Explain whether signaling cascades represent signal amplification, relay, or termination
5. Comparison with Literature: Compare and contrast your findings with published studies (use the provided references extensively)
6. Broader Implications: Relevance to disease pathology or therapeutic targeting — discuss potential clinical significance
7. Limitations and Future Directions: Acknowledge limitations and propose follow-up experiments

IMPORTANT: For each discussion point, provide evidence from your data AND from the literature. Cite the provided references extensively. Discuss alternative interpretations where appropriate. When discussing Non-PTM proteins, always classify their signaling role and explain their relationship directionality with PTM-modified proteins.
- You MUST explicitly name the treatment/stimulus ({treatment}) throughout the Discussion. Never use generic terms.
{combined_lit}"""

    elif section_type == "conclusion":
        results_text = prev_sections.get("results", "")[:2000]
        discussion_text = prev_sections.get("discussion", "")[:2000]

        return f"""Write a Conclusion section (MINIMUM 500 words, target 600-1000 words) for this PTM analysis report.
{analysis_context_block}
{single_tp_directive}
Research Questions:
{questions_str}

Key Hypotheses:
{hyp_summary}

PTM Summary:
{ptm_summary}

Results Summary:
{results_text}

Discussion Summary:
{discussion_text}

Summarize:
1. Key findings and how they answer each research question
2. Novel insights revealed by this analysis — what is new compared to existing literature
3. Biological and clinical significance of the identified PTM changes
4. Potential therapeutic implications
5. Limitations of the current study
6. Specific future research directions with concrete experimental suggestions

IMPORTANT: Be specific about findings — mention key PTM sites and their implications. Reference the results and discussion sections. Cite relevant references.
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

        return f"""Write a detailed Methods section (~800-1500 words) for this PTM analysis report.
{single_tp_directive}
Experimental System:
- Organism: {organism}
- Tissue/Cell type: {tissue_str}
- Treatment: {treatment_str}
- PTM type analyzed: {ptm_type_str}
- Total PTM sites: {n_ptms}
- Number of conditions: {n_conditions}

The Methods section MUST cover:
1. **Sample Preparation and Mass Spectrometry**: Describe the general proteomics workflow for {ptm_type_str} analysis (enrichment strategy, LC-MS/MS, database search)
2. **PTM Data Processing**: Describe how PTM sites were quantified (Log2FC calculation, normalization, filtering criteria)
3. **Bioinformatics Analysis Pipeline**:
   a. Literature enrichment using PubMed, UniProt, KEGG, and STRING-DB databases
   b. Kinase-substrate prediction using KEA3 (Kinase Enrichment Analysis 3)
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
1. **Western Blot Validation**: Specific antibodies (e.g., anti-phospho-{ptm_type_label} antibody for the specific site)
2. **Functional Assay**: How to test the biological consequence of the modification (e.g., site-directed mutagenesis, kinase assay)
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
- Follow academic paper title conventions (e.g., "Comprehensive Phosphoproteomic Analysis Reveals ...").
- Include the PTM type ({ptm_type_label}), the experimental system ({tissue}), and the treatment ({treatment}).
- The title should reflect the overall narrative: temporal {ptm_type_label} dynamics in {tissue} in response to {treatment}.
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
    if not hypotheses:
        return ""
    lines = ["\nHypotheses:"]
    for h in hypotheses:
        conf = h.get("confidence", 0)
        lines.append(f"  H{h.get('id', '?')}: IF {h.get('condition', '')[:100]} THEN {h.get('prediction', '')[:100]} (confidence={conf:.2f})")
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
