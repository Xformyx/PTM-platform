"""
Question Generator Node — generates research questions from PTM data using LLM.

Ported from ptm-chromadb-web/python_backend/llm_question_generator.py.
Adapted to use Ollama instead of Gemini API.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)

QUESTION_GENERATION_PROMPT = """You are an expert PTM (Post-Translational Modification) researcher analyzing {ptm_type_display} data. Your task is to generate insightful, data-driven research questions.

{single_time_point_note}

## CRITICAL INSTRUCTIONS
1. **Read the input data carefully** - Extract experimental conditions, cell types, treatments, and time points from the markdown content
2. **Reference specific PTMs** - Each question MUST mention at least one specific protein and modification site from the data
3. **Be mechanistically precise** - Questions should probe specific molecular mechanisms, not general concepts
4. **Consider temporal dynamics** - If time points exist (and this is NOT a single timepoint experiment), ask about the progression and transition of signaling states

## Question Categories (Generate diverse questions across these types)

### 1. temporal_pathway (Time-dependent pathway analysis)
- Focus on: Which pathways are activated vs inhibited at each time point?
- **SKIP this category if single_time_point_note above is present**

### 2. ecm_context (Extracellular matrix and cell-matrix interactions)
- Focus on: How do ECM components or cell adhesion affect signaling?

### 3. pathway_crosstalk (Inter-pathway communication)
- Focus on: How do different signaling cascades interact or regulate each other?

### 4. kinase_phosphatase (Enzyme-substrate relationships)
- Focus on: Which {enzyme_type} drive the observed PTM changes?

### 5. adaptation_mechanism (Functional consequences)
- Focus on: How do PTM changes relate to cellular adaptation or phenotype?

### 6. network (Systems-level analysis)
- Focus on: Protein interaction networks and hub proteins

### 7. novelty (Unexpected findings)
- Focus on: Unusual patterns or novel regulatory mechanisms

## Input Data (Analyze this carefully)
{markdown_content}

## Output Requirements
Generate exactly {max_questions} questions as a JSON array. Each question object must have:

```json
{{
  "question": "Specific research question ending with ? (MUST reference actual proteins/sites from the data)",
  "category": "One of: temporal_pathway, ecm_context, pathway_crosstalk, kinase_phosphatase, adaptation_mechanism, network, novelty",
  "confidence": 0.0-1.0 (based on how well the data supports this question),
  "rationale": "1-2 sentences explaining WHY this question is important, referencing specific data points"
}}
```

## Quality Checklist (Self-verify before output)
- Each question mentions specific protein names and modification sites from the input data
- Questions are diverse across at least 4 different categories
- Rationales cite specific observations from the data
- Questions are testable and mechanistically focused
- Confidence scores reflect actual data support

Return ONLY the JSON array, no additional text or explanation."""


VALID_CATEGORIES = {
    "temporal_pathway", "ecm_context", "pathway_crosstalk",
    "kinase_phosphatase", "adaptation_mechanism", "network", "novelty",
    "experimental", "pathway", "temporal", "ptm_pattern",
}

# Cross-Talk specific categories
CROSSTALK_CATEGORIES = {
    "concordant_regulation", "discordant_regulation", "sequential_gating",
    "shared_pathway", "kinase_e3_ligase", "proteostasis", "novel_crosstalk",
    # Legacy categories for backward compatibility
    *VALID_CATEGORIES,
}


CROSSTALK_QUESTION_GENERATION_PROMPT = """You are an expert PTM (Post-Translational Modification) researcher specializing in **PTM cross-talk analysis** between phosphorylation and ubiquitylation. You are given TWO datasets:
- **Dataset 1 (Phosphorylation)**: Contains phosphoproteomics data
- **Dataset 2 (Ubiquitylation)**: Contains ubiquitylation proteomics data
Your task is to generate insightful research questions that specifically address the **cross-talk** (interplay, coordination, and regulatory relationships) between these two PTM types.

## CRITICAL INSTRUCTIONS
1. **Analyze BOTH datasets** - Extract proteins, sites, timepoints, and conditions from both files
2. **Focus on cross-talk** - Questions MUST address the relationship BETWEEN phosphorylation and ubiquitylation
3. **Identify shared proteins** - Find proteins that appear in both datasets and ask about their dual regulation
4. **Consider temporal coordination** - If timepoints exist, ask about sequential or coordinated PTM events
5. **Reference specific data** - Each question MUST mention specific proteins/sites from the actual data

## Question Categories for Cross-Talk Analysis

### 1. concordant_regulation (Co-directional PTM changes)
- Focus on: Proteins showing same-direction changes in both Phos and Ub

### 2. discordant_regulation (Opposing PTM changes)
- Focus on: Proteins with opposite Phos vs Ub trends (one up, other down)

### 3. sequential_gating (Temporal PTM ordering)
- Focus on: Whether one PTM precedes and gates the other

### 4. shared_pathway (Pathway-level cross-talk)
- Focus on: Signaling pathways affected by both PTM types

### 5. kinase_e3_ligase (Enzyme cross-talk)
- Focus on: Relationships between kinases (Phos writers) and E3 ligases (Ub writers)

### 6. proteostasis (Protein stability regulation)
- Focus on: How dual PTMs regulate protein turnover

### 7. novel_crosstalk (Unexpected cross-talk patterns)
- Focus on: Surprising or novel cross-talk observations

## Input Data
### Dataset 1: Phosphorylation Data
{primary_markdown_content}

### Dataset 2: Ubiquitylation Data
{secondary_markdown_content}

## Output Requirements
Generate exactly {max_questions} questions as a JSON array. Each question object must have:

```json
{{{{
  "question": "Cross-talk specific question ending with ? (MUST reference proteins/sites from BOTH datasets)",
  "category": "One of: concordant_regulation, discordant_regulation, sequential_gating, shared_pathway, kinase_e3_ligase, proteostasis, novel_crosstalk",
  "confidence": 0.0-1.0 (based on how well BOTH datasets support this question),
  "rationale": "1-2 sentences explaining WHY this cross-talk question is important, citing data from BOTH datasets"
}}}}
```

## Quality Checklist
- Each question addresses the RELATIONSHIP between phosphorylation and ubiquitylation
- Questions reference specific proteins/sites from BOTH datasets
- Questions are diverse across at least 4 different cross-talk categories
- Rationales cite observations from BOTH datasets
- At least 2 questions address shared/overlapping proteins between the datasets
- At least 1 question addresses temporal coordination if timepoints are available

Return ONLY the JSON array, no additional text or explanation."""



def _get_co_scientist_questions(state: dict) -> list:
    """Generate data-driven research questions for co-scientist mode.
    
    Questions are derived from actual data patterns rather than user input:
    - Temporal cascade: kinase activation order
    - Co-wave modules: substrate co-activation groups
    - Autophosphorylation: self-activation markers
    - TMM: kinase-substrate attribution
    """
    questions = []
    
    # Extract data sources
    kad = state.get("frontend_kinase_analysis") or state.get("global_kinase_modules") or {}
    temporal_cascade = kad.get("temporal_cascade", {})
    cascade_flow = temporal_cascade.get("cascade_flow", [])
    
    kah = state.get("kinase_activity_heatmap") or {}
    kinase_scores = kah.get("kinase_scores", [])
    cowave_groups = kah.get("cowave_groups", [])
    
    context = state.get("experimental_context", {})
    tissue = context.get("tissue") or context.get("cell_type") or "the experimental system"
    treatment = context.get("treatment") or "the treatment"
    ptm_type = state.get("ptm_type", "phosphorylation")
    
    # Q1: Temporal cascade — what is the kinase activation order?
    if cascade_flow:
        timepoints = [step.get("timepoint", "") for step in cascade_flow]
        questions.append(
            f"What is the temporal order of kinase activation in {tissue} following {treatment}, "
            f"and how does the signaling cascade progress across {', '.join(timepoints[:4])}?"
        )
    
    # Q2: Top kinases — what are the dominant kinases and their substrates?
    top_ks = sorted(
        [ks for ks in kinase_scores if not ks.get("is_sub_pattern")],
        key=lambda x: abs(x.get("peak_score", 0)), reverse=True
    )[:3]
    if top_ks:
        k_names = ", ".join(ks.get("kinase", "") for ks in top_ks)
        questions.append(
            f"What are the biological roles of the top-activated kinases ({k_names}) "
            f"and which specific substrates do they regulate in {tissue}?"
        )
    
    # Q3: Co-wave modules — what do co-activated substrates have in common?
    if cowave_groups:
        questions.append(
            f"What functional modules are revealed by co-wave analysis — "
            f"do substrates activated simultaneously share common cellular pathways or compartments?"
        )
    
    # Q4: Autophosphorylation — which kinases show self-activation loops?
    auto_kinases = [
        ks.get("kinase", "") for ks in kinase_scores
        if not ks.get("is_sub_pattern") and ks.get("self_ptm")
    ]
    if auto_kinases:
        questions.append(
            f"Which kinases ({', '.join(auto_kinases[:3])}) exhibit autophosphorylation-based "
            f"activation loops, and how does this amplify downstream {ptm_type} signaling?"
        )
    
    # Q5: TMM — how are shared substrates attributed between kinases?
    shared_kinases = [
        ks for ks in kinase_scores
        if not ks.get("is_sub_pattern") and ks.get("tmm_n_shared", 0) > 3
    ]
    if shared_kinases:
        k_names2 = ", ".join(ks.get("kinase", "") for ks in shared_kinases[:3])
        questions.append(
            f"How do kinases ({k_names2}) cooperate through shared substrates, "
            f"and what does the TMM contribution analysis reveal about their relative dominance?"
        )
    
    # Q6: Biological significance — what does this signaling pattern mean?
    bio_q = (context.get("biological_question") or "").strip()
    if bio_q:
        questions.append(bio_q)
    else:
        questions.append(
            f"What is the overall biological significance of the observed {ptm_type} signaling pattern "
            f"in {tissue} following {treatment}, and what are the key mechanistic insights?"
        )
    
    # Fallback: ensure at least 3 questions
    if len(questions) < 3:
        questions.extend(_get_fallback_questions()[:3 - len(questions)])
    
    return questions


def run_question_generation(state: dict) -> dict:
    """Generate AI research questions from comprehensive report and PTM data."""
    cb = state.get("progress_callback")
    if cb:
        cb(6, "Generating AI research questions")

    # v12.0: Co-Scientist mode — auto-generate data-driven questions, skip user input
    report_type = state.get("report_type", "comprehensive")
    if report_type == "co_scientist":
        co_questions = _get_co_scientist_questions(state)
        logger.info(f"[Co-Scientist] Auto-generated {len(co_questions)} data-driven research questions")
        if cb:
            cb(8, f"[Co-Scientist] {len(co_questions)} data-driven questions generated")
        return {"research_questions": co_questions}


    existing_questions = state.get("research_questions", [])
    if existing_questions:
        logger.info(f"Using {len(existing_questions)} user-provided research questions")
        if cb:
            cb(8, f"Using {len(existing_questions)} user-provided research questions")
        return {"research_questions": existing_questions}

    comprehensive_summary = state.get("comprehensive_summary", "")
    parsed_ptms = state.get("parsed_ptms", [])

    if not comprehensive_summary and not parsed_ptms:
        logger.warning("No data available for question generation, using defaults")
        return {"research_questions": _get_fallback_questions()}

    content = _build_content_for_questions(comprehensive_summary, parsed_ptms)

    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    context = state.get("experimental_context", {})
    ptm_type = state.get("ptm_type", "phosphorylation")
    is_ubi = ptm_type.lower().strip() in ("ubiquitylation", "ubiquitination")
    ptm_type_display = "ubiquitylomics" if is_ubi else "phosphoproteomics"
    enzyme_type = "E3 ligases/DUBs" if is_ubi else "kinases/phosphatases"
    if not llm.is_available():
        logger.warning("LLM not available for question generation, using defaults")
        if cb:
            cb(8, "LLM not available — using default questions")
        return {"research_questions": _get_fallback_questions(context.get("single_time_point", False))}
    single_time_point = context.get("single_time_point", False)
    single_time_point_note = (
        "## IMPORTANT: Single Timepoint Experiment\n"
        "This is a **single timepoint experiment** (no temporal/time-course data). "
        "Do NOT generate questions about temporal dynamics, time-course, sequential changes across timepoints, or trajectory patterns. "
        "Skip the temporal_pathway category entirely.\n\n"
        if single_time_point
        else ""
    )

    max_questions = 8
    prompt = QUESTION_GENERATION_PROMPT.format(
        max_questions=max_questions,
        markdown_content=content,
        single_time_point_note=single_time_point_note,
        ptm_type_display=ptm_type_display,
        enzyme_type=enzyme_type,
    )

    try:
        if cb:
            cb(7, f"Calling LLM ({llm.model}) for question generation")

        response = llm.generate(
            prompt,
            system_prompt="You are a PTM research expert. Return ONLY valid JSON.",
            temperature=0.7,
            max_tokens=4096,
        )

        if response.startswith("[LLM Error"):
            logger.warning(f"LLM error during question generation: {response}")
            if cb:
                cb(8, "LLM error — using default questions")
            return {"research_questions": _get_fallback_questions(single_time_point)}

        questions_data = _parse_json_response(response)
        if not questions_data:
            logger.warning("Failed to parse LLM question response")
            if cb:
                cb(8, "Failed to parse questions — using defaults")
            return {"research_questions": _get_fallback_questions(single_time_point)}

        validated = _validate_questions(questions_data, max_questions)
        # Filter out temporal questions when single_time_point
        if single_time_point:
            validated = [q for q in validated if q.get("category") != "temporal_pathway" and "temporal" not in (q.get("category") or "").lower()]
        question_strings = [q["question"] for q in validated]

        logger.info(f"Generated {len(question_strings)} AI research questions")
        if cb:
            cb(8, f"Generated {len(question_strings)} AI research questions")

        return {
            "research_questions": question_strings,
            "ai_questions_metadata": validated,
        }

    except Exception as e:
        logger.error(f"Question generation failed: {e}")
        if cb:
            cb(8, f"Question generation error — using defaults")
        return {"research_questions": _get_fallback_questions(context.get("single_time_point", False))}


def generate_questions_from_content(
    content: str,
    llm_provider: str = "ollama",
    llm_model: Optional[str] = None,
    max_questions: int = 8,
) -> Dict[str, Any]:
    """Standalone function for API endpoint use."""
    llm = LLMClient(provider=llm_provider, model=llm_model)

    if not llm.is_available():
        return {
            "success": False,
            "error": f"LLM model '{llm.model}' not available",
            "questions": _get_fallback_questions_full(),
            "count": 0,
        }

    if len(content) > 15000:
        content = content[:15000] + "\n\n[... content truncated for brevity ...]"

    prompt = QUESTION_GENERATION_PROMPT.format(
        max_questions=max_questions,
        markdown_content=content,
        single_time_point_note="",
    )

    response = llm.generate(
        prompt,
        system_prompt="You are a PTM research expert. Return ONLY valid JSON.",
        temperature=0.7,
        max_tokens=4096,
    )

    if response.startswith("[LLM Error"):
        return {
            "success": False,
            "error": response,
            "questions": _get_fallback_questions_full(),
            "count": 0,
        }

    questions_data = _parse_json_response(response)
    if not questions_data:
        return {
            "success": False,
            "error": "Failed to parse LLM response as JSON",
            "questions": _get_fallback_questions_full(),
            "count": 0,
        }

    validated = _validate_questions(questions_data, max_questions)
    return {
        "success": True,
        "questions": validated,
        "count": len(validated),
    }


def _build_content_for_questions(summary: str, ptms: list) -> str:
    """Build content string from summary and PTM data."""
    parts = []
    if summary:
        parts.append(summary[:10000])
    if ptms:
        ptm_lines = []
        for p in ptms[:30]:
            ptm_lines.append(
                f"- {p['gene']}-{p['position']} ({p['ptm_type']}): "
                f"PTM_FC={p.get('ptm_relative_log2fc', 0):.3f}, "
                f"Prot_FC={p.get('protein_log2fc', 0):.3f}"
            )
        parts.append("## Key PTM Sites\n" + "\n".join(ptm_lines))
    return "\n\n".join(parts)


def _parse_json_response(response_text: str) -> Optional[List[Dict]]:
    """Parse JSON from LLM response, handling various formats."""
    response_text = response_text.strip()
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", response_text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", response_text)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _validate_questions(
    questions: List[Dict], max_questions: int
) -> List[Dict[str, Any]]:
    """Validate and normalize question objects."""
    validated = []
    for q in questions[:max_questions]:
        if not isinstance(q, dict):
            continue
        question_text = q.get("question", "")
        if not question_text or len(question_text) < 10:
            continue
        if not question_text.endswith("?"):
            question_text += "?"

        category = q.get("category", "experimental")
        if category not in VALID_CATEGORIES:
            category = "experimental"

        confidence = q.get("confidence", 0.7)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (ValueError, TypeError):
            confidence = 0.7

        validated.append({
            "question": question_text,
            "category": category,
            "confidence": round(confidence, 2),
            "rationale": q.get("rationale", "Generated by LLM analysis"),
            "included": True,
            "source": "ai",
        })
    return validated


def _get_fallback_questions(single_time_point: bool = False) -> List[str]:
    """Return fallback question strings for pipeline use."""
    base = [
        "What are the key PTM changes observed in the experimental conditions?",
        "Which signaling pathways show the most significant PTM alterations?",
        "What protein-protein interaction networks are affected by the observed PTM changes?",
    ]
    if not single_time_point:
        base.insert(2, "How do PTM patterns change across different timepoints?")
    return base


# -----------------------------------------------------------------------
# Cross-Talk question generation
# -----------------------------------------------------------------------

def run_crosstalk_question_generation(state: dict) -> dict:
    """Generate Cross-Talk research questions from two PTM datasets."""
    cb = state.get("progress_callback")
    if cb:
        cb(6, "Generating Cross-Talk research questions")

    primary_content = state.get("primary_markdown_content", "")
    secondary_content = state.get("secondary_markdown_content", "")

    if not primary_content or not secondary_content:
        logger.warning("Missing one or both datasets for cross-talk question generation")
        return {"research_questions": [q["question"] for q in _get_crosstalk_fallback_questions()]}

    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    if not llm.is_available():
        logger.warning("LLM not available for cross-talk question generation")
        if cb:
            cb(8, "LLM not available — using default cross-talk questions")
        return {"research_questions": [q["question"] for q in _get_crosstalk_fallback_questions()]}

    max_questions = 8
    # Truncate content if too long
    if len(primary_content) > 15000:
        primary_content = primary_content[:15000] + "\n\n[... content truncated ...]\n"
    if len(secondary_content) > 15000:
        secondary_content = secondary_content[:15000] + "\n\n[... content truncated ...]\n"

    prompt = CROSSTALK_QUESTION_GENERATION_PROMPT.format(
        max_questions=max_questions,
        primary_markdown_content=primary_content,
        secondary_markdown_content=secondary_content,
    )

    try:
        if cb:
            cb(7, f"Calling LLM ({llm.model}) for cross-talk question generation")

        response = llm.generate(
            prompt,
            system_prompt="You are a PTM cross-talk research expert. Return ONLY valid JSON.",
            temperature=0.7,
            max_tokens=4096,
        )

        if response.startswith("[LLM Error"):
            logger.warning(f"LLM error during cross-talk question generation: {response}")
            if cb:
                cb(8, "LLM error — using default cross-talk questions")
            return {
                "research_questions": [q["question"] for q in _get_crosstalk_fallback_questions()],
                "ai_questions_metadata": _get_crosstalk_fallback_questions(),
            }

        questions_data = _parse_json_response(response)
        if not questions_data:
            logger.warning("Failed to parse LLM cross-talk question response")
            if cb:
                cb(8, "Failed to parse cross-talk questions — using defaults")
            return {
                "research_questions": [q["question"] for q in _get_crosstalk_fallback_questions()],
                "ai_questions_metadata": _get_crosstalk_fallback_questions(),
            }

        validated = _validate_crosstalk_questions(questions_data, max_questions)
        question_strings = [q["question"] for q in validated]

        logger.info(f"Generated {len(question_strings)} AI cross-talk research questions")
        if cb:
            cb(8, f"Generated {len(question_strings)} AI cross-talk research questions")

        return {
            "research_questions": question_strings,
            "ai_questions_metadata": validated,
        }

    except Exception as e:
        logger.error(f"Cross-talk question generation failed: {e}")
        if cb:
            cb(8, "Cross-talk question generation error — using defaults")
        return {
            "research_questions": [q["question"] for q in _get_crosstalk_fallback_questions()],
            "ai_questions_metadata": _get_crosstalk_fallback_questions(),
        }


def generate_crosstalk_questions_from_content(
    primary_content: str,
    secondary_content: str,
    llm_provider: str = "ollama",
    llm_model: Optional[str] = None,
    max_questions: int = 8,
) -> Dict[str, Any]:
    """Standalone function for Cross-Talk question generation via API endpoint."""
    llm = LLMClient(provider=llm_provider, model=llm_model)

    if not llm.is_available():
        return {
            "success": False,
            "error": f"LLM model '{llm.model}' not available",
            "questions": _get_crosstalk_fallback_questions(),
            "count": 0,
        }

    if len(primary_content) > 15000:
        primary_content = primary_content[:15000] + "\n\n[... content truncated ...]\n"
    if len(secondary_content) > 15000:
        secondary_content = secondary_content[:15000] + "\n\n[... content truncated ...]\n"

    prompt = CROSSTALK_QUESTION_GENERATION_PROMPT.format(
        max_questions=max_questions,
        primary_markdown_content=primary_content,
        secondary_markdown_content=secondary_content,
    )

    response = llm.generate(
        prompt,
        system_prompt="You are a PTM cross-talk research expert. Return ONLY valid JSON.",
        temperature=0.7,
        max_tokens=4096,
    )

    if response.startswith("[LLM Error"):
        return {
            "success": False,
            "error": response,
            "questions": _get_crosstalk_fallback_questions(),
            "count": 0,
        }

    questions_data = _parse_json_response(response)
    if not questions_data:
        return {
            "success": False,
            "error": "Failed to parse LLM response as JSON",
            "questions": _get_crosstalk_fallback_questions(),
            "count": 0,
        }

    validated = _validate_crosstalk_questions(questions_data, max_questions)
    return {
        "success": True,
        "questions": validated,
        "count": len(validated),
    }


def _validate_crosstalk_questions(
    questions: List[Dict], max_questions: int
) -> List[Dict[str, Any]]:
    """Validate and normalize cross-talk question objects."""
    validated = []
    for q in questions[:max_questions]:
        if not isinstance(q, dict):
            continue
        question_text = q.get("question", "")
        if not question_text or len(question_text) < 10:
            continue
        if not question_text.endswith("?"):
            question_text += "?"

        category = q.get("category", "shared_pathway")
        if category not in CROSSTALK_CATEGORIES:
            category = "shared_pathway"

        confidence = q.get("confidence", 0.7)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (ValueError, TypeError):
            confidence = 0.7

        validated.append({
            "question": question_text,
            "category": category,
            "confidence": round(confidence, 2),
            "rationale": q.get("rationale", "Generated by LLM cross-talk analysis"),
            "included": True,
            "source": "ai_crosstalk",
        })
    return validated


def _get_crosstalk_fallback_questions() -> List[Dict[str, Any]]:
    """Return fallback cross-talk questions if LLM fails."""
    return [
        {
            "question": "Which proteins show both significant phosphorylation and ubiquitylation changes, and what does this dual regulation suggest about their functional role?",
            "category": "concordant_regulation",
            "confidence": 0.9,
            "rationale": "Identifying dual-PTM proteins is fundamental to understanding cross-talk mechanisms",
            "included": True,
            "source": "fallback",
        },
        {
            "question": "Are there proteins where phosphorylation increases while ubiquitylation decreases (or vice versa), suggesting antagonistic PTM regulation?",
            "category": "discordant_regulation",
            "confidence": 0.85,
            "rationale": "Opposing PTM changes may indicate phospho-dependent stabilization or degradation switches",
            "included": True,
            "source": "fallback",
        },
        {
            "question": "Does phosphorylation at early timepoints precede and trigger ubiquitylation at later timepoints for key signaling proteins?",
            "category": "sequential_gating",
            "confidence": 0.8,
            "rationale": "Temporal ordering of PTMs reveals gating mechanisms in signaling cascades",
            "included": True,
            "source": "fallback",
        },
        {
            "question": "Which signaling pathways show coordinated changes in both phosphorylation and ubiquitylation across multiple pathway members?",
            "category": "shared_pathway",
            "confidence": 0.75,
            "rationale": "Pathway-level cross-talk provides systems-level understanding of dual PTM regulation",
            "included": True,
            "source": "fallback",
        },
    ]


def _get_fallback_questions_full() -> List[Dict[str, Any]]:
    """Return fallback questions with full metadata for API use."""
    return [
        {
            "question": "What are the key PTM changes observed in the experimental conditions?",
            "category": "experimental",
            "confidence": 0.9,
            "rationale": "Fundamental question to understand treatment effects",
            "included": True,
            "source": "fallback",
        },
        {
            "question": "Which signaling pathways show the most significant PTM alterations?",
            "category": "pathway",
            "confidence": 0.85,
            "rationale": "Pathway analysis reveals functional implications",
            "included": True,
            "source": "fallback",
        },
        {
            "question": "How do PTM patterns change across different timepoints?",
            "category": "temporal",
            "confidence": 0.8,
            "rationale": "Temporal dynamics reveal signaling progression",
            "included": True,
            "source": "fallback",
        },
        {
            "question": "What protein-protein interaction networks are affected by the observed PTM changes?",
            "category": "network",
            "confidence": 0.75,
            "rationale": "Network analysis provides systems-level understanding",
            "included": True,
            "source": "fallback",
        },
    ]
