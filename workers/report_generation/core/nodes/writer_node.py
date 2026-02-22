"""
Writer Node — generates report sections using LLM + literature RAG.
Ported from multi_agent_system/agents/section_writers.py.

Generates: Abstract, Introduction, Results, Discussion, Conclusion.
Each section uses LLM with published literature context for integration.
"""

import logging
from typing import Dict, List

from common.llm_client import LLMClient
from report_generation.core.rag_retriever import RAGRetriever

logger = logging.getLogger(__name__)

SECTION_ORDER = ["introduction", "results", "discussion", "conclusion", "abstract"]

SECTION_MAX_TOKENS = {
    "abstract": 4096,
    "introduction": 8192,
    "results": 12288,
    "discussion": 8192,
    "conclusion": 4096,
}

SYSTEM_PROMPT = (
    "You are a scientific writer specializing in post-translational modification (PTM) analysis. "
    "Write in formal academic English. Use flowing prose, not bullet points. "
    "Cite references using numbered brackets (e.g., [1], [2]) matching the provided reference list. "
    "Include as many relevant citations as possible to support your statements. "
    "NEVER mention 'ChromaDB' or 'knowledge base'. "
    "Be precise with PTM site nomenclature (e.g., 'phosphorylation at Ser165 of MAPK3'). "
    "Write detailed, comprehensive content that thoroughly covers the topic."
)


def run_section_writing(state: dict) -> dict:
    """Write all report sections using LLM."""
    cb = state.get("progress_callback")
    if cb:
        cb(70, "Writing report sections")

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
            all_references,
        )

        max_tok = SECTION_MAX_TOKENS.get(section_type, 8192)
        content = llm.generate(prompt, system_prompt=SYSTEM_PROMPT, temperature=0.6, max_tokens=max_tok)

        if content.startswith("[LLM Error"):
            content = _fallback_section(section_type, research_results, validated_hypotheses, parsed_ptms)

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
) -> str:
    """Build LLM prompt for a specific report section."""
    all_references = all_references or []

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
    rag_results = retriever.search_for_section(section_type, keywords)
    if rag_results:
        ref_lines = []
        for idx, r in enumerate(rag_results[:10], 1):
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

    # PTM summary (with recent findings)
    ptm_summary = _ptm_summary_text(ptms[:30])
    hyp_summary = _hypothesis_summary_text(hypotheses[:5])

    tissue = context.get("tissue") or context.get("cell_type") or "the experimental system"
    treatment = context.get("treatment", "the applied treatment")
    biological_question = (context.get("biological_question") or "").strip()
    questions_str = "\n".join(f"  Q{i+1}: {q}" for i, q in enumerate(questions))
    bio_focus_line = f"\nResearch focus (Biological Question): {biological_question}\n" if biological_question else ""

    combined_lit = lit_context + pubmed_context

    if section_type == "abstract":
        intro = prev_sections.get("introduction", "")[:800]
        results = prev_sections.get("results", "")[:1200]
        discussion = prev_sections.get("discussion", "")[:800]
        return f"""Write an Abstract (~300-400 words) for this PTM analysis report.

Experimental System: {tissue}, {treatment}{bio_focus_line}
Research Questions:
{questions_str}

Summary of Introduction: {intro}
Summary of Results: {results}
Summary of Discussion: {discussion}

The abstract should include: background, methods overview, key findings, and significance.
Write a comprehensive abstract that captures all major findings. Include specific PTM sites and their significance.
{combined_lit}"""

    elif section_type == "introduction":
        return f"""Write a comprehensive Introduction section (~1000-1500 words) for this PTM analysis report.

Experimental System: {tissue}, {treatment}{bio_focus_line}
Research Questions:
{questions_str}

Key PTM sites identified:
{ptm_summary}

Structure (5-7 paragraphs):
1. Background on post-translational modifications and their critical role in cellular signaling
2. Specific background on {ptm_type_label} and its regulatory importance
3. Relevance of the experimental system ({tissue}, {treatment})
4. Current understanding and knowledge gaps in this area (cite the provided references)
5. PTM analysis methodology including mass spectrometry-based proteomics
6. Research questions and specific objectives of this study

IMPORTANT: Write a thorough, detailed introduction. Cite as many of the provided references as possible to establish context. Discuss the biological significance of each research question.
{combined_lit}"""

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
                research_str += "  Enriched pathways: " + ", ".join(p["pathway"] for p in enriched) + "\n"

        network_info = ""
        net = network or {}
        if net.get("legends", {}).get("full_legend"):
            network_info = f"\n\nNetwork Analysis:\n{net['legends']['full_legend'][:800]}"

        comp_ctx = ""
        if comprehensive_summary:
            comp_ctx = f"\n\nDetailed Analysis Context (from prior comprehensive analysis):\n{comprehensive_summary[:3000]}\n"

        return f"""Write a detailed Results section (~2000-3000 words) for this PTM analysis report.

Research Findings:
{research_str}

PTM Data:
{ptm_summary}

{hyp_summary}
{network_info}
{comp_ctx}

Structure:
- Present results for each research question as subsections with ### headings
- For each PTM site, describe: the specific modification, fold-change values, known biological function, pathway involvement, and disease relevance
- Include specific PTM sites with Log2FC values and their biological functions
- Reference enriched pathways and protein interactions
- Describe network relationships and regulatory mechanisms
- Discuss disease relevance where applicable
- Compare your findings with the published literature provided below

IMPORTANT: Be thorough and detailed. Discuss each significant PTM site individually. Include quantitative data (Log2FC values). Cite the provided references to support your findings. This is the most important section of the report.
{combined_lit}"""

    elif section_type == "discussion":
        results_text = prev_sections.get("results", "")[:2000]
        comp_disc = ""
        if comprehensive_summary:
            comp_disc = f"\n\nDetailed Analysis Context:\n{comprehensive_summary[:2000]}\n"

        return f"""Write a comprehensive Discussion section (~1200-1800 words) for this PTM analysis report.

Results Summary:
{results_text}

Validated Hypotheses:
{hyp_summary}

PTM Biological Context:
{ptm_summary}
{comp_disc}

Structure (4-5 core topics):
1. Primary Finding: The main PTM signaling mechanism identified — discuss in detail how the observed modifications form a coherent signaling response
2. Mechanistic Insight: How specific PTM sites contribute to the observed response — relate each key site to known kinase-substrate relationships and signaling cascades
3. Comparison with Literature: Compare and contrast your findings with published studies (use the provided references extensively)
4. Broader Implications: Relevance to disease pathology or therapeutic targeting — discuss potential clinical significance
5. Limitations and Future Directions: Acknowledge limitations and propose follow-up experiments

IMPORTANT: For each discussion point, provide evidence from your data AND from the literature. Cite the provided references extensively. Discuss alternative interpretations where appropriate.
{combined_lit}"""

    elif section_type == "conclusion":
        return f"""Write a Conclusion section (~400-600 words) for this PTM analysis report.

Research Questions:
{questions_str}

Key Hypotheses:
{hyp_summary}

PTM Summary:
{ptm_summary}

Summarize:
1. Key findings and how they answer the research questions
2. Novel insights revealed by this analysis
3. Biological and clinical significance
4. Limitations of the current study
5. Specific future research directions

IMPORTANT: Be specific about findings — mention key PTM sites and their implications. Cite relevant references.
{combined_lit}"""

    return f"Write the {section_type} section for a PTM analysis report.\n{ptm_summary}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_all_references(ptms: list) -> list:
    """Collect all unique PubMed references from enriched PTM data."""
    seen_pmids = set()
    refs = []
    for ptm in ptms:
        enr = ptm.get("rag_enrichment", {})
        for finding in enr.get("recent_findings", []):
            pmid = finding.get("pmid", "")
            if pmid and pmid not in seen_pmids:
                seen_pmids.add(pmid)
                refs.append({
                    "pmid": pmid,
                    "title": finding.get("title", ""),
                    "journal": finding.get("journal", ""),
                    "pub_date": finding.get("pub_date", ""),
                    "abstract_excerpt": finding.get("abstract_excerpt", "")[:400],
                    "relevance_score": finding.get("relevance_score", 0),
                    "gene": ptm.get("gene", ""),
                })
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
        entry = f"--- PubMed Ref [{idx}] (PMID: {ref['pmid']}) ---"
        entry += f"\nTitle: {ref['title']}"
        entry += f"\nJournal: {ref['journal']} ({ref['pub_date']})"
        entry += f"\nRelated gene: {ref['gene']}"
        if ref.get("abstract_excerpt"):
            entry += f"\nExcerpt: {ref['abstract_excerpt']}"
        lines.append(entry)

    return (
        f"\n\n**PubMed Literature References ({len(selected)} papers):**\n"
        "The following are published studies from PubMed that are directly relevant to "
        "the PTM sites analyzed in this study. Cite these using their reference numbers "
        "(e.g., [PubMed Ref 1]). Integrate findings from these papers into your writing "
        "to provide comprehensive biological context.\n\n"
        + "\n\n".join(lines)
    )


def _ptm_summary_text(ptms: list) -> str:
    lines = []
    for i, p in enumerate(ptms):
        line = f"  {p['gene']}-{p['position']} ({p['ptm_type']}): PTM_FC={p['ptm_relative_log2fc']:.3f}, Prot_FC={p.get('protein_log2fc', 0):.3f}"
        enr = p.get("rag_enrichment", {})
        if i < 15 and enr:
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
    return ""
