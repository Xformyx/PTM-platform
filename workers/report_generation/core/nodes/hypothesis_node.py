"""
Hypothesis Node — generates structured hypotheses from research results.
Ported from multi_agent_system/agents/hypothesis_generator.py.

Generates IF-THEN-BECAUSE hypotheses with supporting PTMs and testable predictions.
Uses LLM when available, falls back to rule-based generation.
"""

import logging
import os
import uuid
from typing import List

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)


def run_hypothesis_generation(state: dict) -> dict:
    """Generate hypotheses from research results."""
    cb = state.get("progress_callback")
    if cb:
        cb(30, "Generating hypotheses")

    research_results = state.get("research_results", [])
    context = state.get("experimental_context", {})

    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    hypotheses = []
    for i, result in enumerate(research_results):
        if cb:
            pct = 30 + (i / max(len(research_results), 1)) * 10
            cb(pct, f"Hypothesis for Q{i+1}")

        new_hyps = _generate_hypotheses(result, context, llm)
        hypotheses.extend(new_hyps)

    if cb:
        cb(40, f"Generated {len(hypotheses)} hypotheses")

    return {"hypotheses": hypotheses}


def _generate_hypotheses(research: dict, context: dict, llm: LLMClient) -> list:
    """Generate hypotheses for a single research result."""
    if llm.is_available():
        return _generate_with_llm(research, context, llm)
    return _generate_rule_based(research, context)


def _generate_with_llm(research: dict, context: dict, llm: LLMClient) -> list:
    """Use LLM to generate structured hypotheses."""
    activated = research.get("activated", [])
    inhibited = research.get("inhibited", [])
    pathways = research.get("enriched_pathways", [])
    patterns = research.get("regulatory_patterns", [])

    activated_str = ", ".join(f"{p['gene']}-{p['position']} (Log2FC={p['ptm_relative_log2fc']})" for p in activated[:5])
    inhibited_str = ", ".join(f"{p['gene']}-{p['position']} (Log2FC={p['ptm_relative_log2fc']})" for p in inhibited[:5])
    pathway_str = ", ".join(p["pathway"] for p in pathways[:5])

    tissue = context.get("tissue") or context.get("cell_type") or "the given experimental system"
    treatment = context.get("treatment", "the applied treatment")
    biological_question = (context.get("biological_question") or "").strip()
    bio_focus = f"\nResearch focus (Biological Question): {biological_question}\n" if biological_question else ""

    prompt = f"""Based on the following PTM analysis results, generate 1-2 testable hypotheses.

Research Question: {research['question']}{bio_focus}

Key Upregulated PTMs: {activated_str or 'None'}
Key Downregulated PTMs: {inhibited_str or 'None'}
Enriched Pathways: {pathway_str or 'None'}
Experimental Context: {tissue}, {treatment}

For each hypothesis, provide:
1. IF: The observed condition
2. THEN: The predicted biological outcome
3. BECAUSE: The proposed mechanism
4. Supporting PTMs: List the relevant PTM sites
5. Testable Prediction: A specific experiment to test this

Format each hypothesis as:
HYPOTHESIS:
IF: ...
THEN: ...
BECAUSE: ...
SUPPORTING: ...
PREDICTION: ...
CONFIDENCE: (0.0-1.0)
"""

    response = llm.generate(
        prompt,
        system_prompt="You are a molecular biology expert specializing in post-translational modifications.",
        temperature=0.5,
    )

    return _parse_llm_hypotheses(response, research)


def _parse_llm_hypotheses(response: str, research: dict) -> list:
    """Parse LLM response into structured hypotheses."""
    hypotheses = []
    blocks = response.split("HYPOTHESIS:")

    for block in blocks[1:]:
        lines = block.strip().split("\n")
        hyp = {
            "id": str(uuid.uuid4())[:8],
            "question": research["question"],
            "condition": "",
            "prediction": "",
            "mechanism": "",
            "supporting_ptms": [],
            "testable_prediction": "",
            "confidence": 0.5,
            "status": "generated",
        }

        for line in lines:
            line = line.strip()
            if line.startswith("IF:"):
                hyp["condition"] = line[3:].strip()
            elif line.startswith("THEN:"):
                hyp["prediction"] = line[5:].strip()
            elif line.startswith("BECAUSE:"):
                hyp["mechanism"] = line[8:].strip()
            elif line.startswith("SUPPORTING:"):
                hyp["supporting_ptms"] = [s.strip() for s in line[11:].split(",") if s.strip()]
            elif line.startswith("PREDICTION:"):
                hyp["testable_prediction"] = line[11:].strip()
            elif line.startswith("CONFIDENCE:"):
                try:
                    hyp["confidence"] = float(line[11:].strip())
                except ValueError:
                    pass

        if hyp["condition"] and hyp["prediction"]:
            hypotheses.append(hyp)

    if not hypotheses:
        return _generate_rule_based(research, {})

    return hypotheses


def _generate_rule_based(research: dict, context: dict) -> list:
    """Fallback: generate hypotheses from rules."""
    hypotheses = []
    activated = research.get("activated", [])
    inhibited = research.get("inhibited", [])
    pathways = research.get("enriched_pathways", [])

    if activated and pathways:
        top = activated[0]
        pw = pathways[0]["pathway"]
        hypotheses.append({
            "id": str(uuid.uuid4())[:8],
            "question": research["question"],
            "condition": f"Phosphorylation of {top['gene']} at {top['position']} is upregulated (Log2FC={top['ptm_relative_log2fc']})",
            "prediction": f"The {pw} pathway is activated",
            "mechanism": f"{top['gene']} {top['position']} phosphorylation activates downstream signaling through {pw}",
            "supporting_ptms": [f"{top['gene']}-{top['position']}"],
            "testable_prediction": f"Inhibition of {top['gene']} phosphorylation should reduce {pw} pathway activity",
            "confidence": min(0.7, research.get("confidence", 0.5)),
            "status": "generated",
        })

    if activated and inhibited:
        up = activated[0]
        down = inhibited[0]
        hypotheses.append({
            "id": str(uuid.uuid4())[:8],
            "question": research["question"],
            "condition": f"{up['gene']} is upregulated while {down['gene']} is downregulated",
            "prediction": f"A signaling switch from {down['gene']} to {up['gene']} axis is occurring",
            "mechanism": f"Reciprocal regulation of {up['gene']} and {down['gene']} indicates a coordinated signaling transition",
            "supporting_ptms": [f"{up['gene']}-{up['position']}", f"{down['gene']}-{down['position']}"],
            "testable_prediction": f"Restoring {down['gene']} activity should attenuate {up['gene']} phosphorylation",
            "confidence": 0.5,
            "status": "generated",
        })

    return hypotheses
