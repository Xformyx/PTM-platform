"""
RQ Refinement Node — v10.0

Runs after kinase_annotation and before write_sections.
Refines the user's original research questions (RQ0) into specific,
data-grounded sub-questions (RQ2) using analysis results discovered by
upstream nodes (network_analysis, temporal_comovement, kinase_annotation).

Pipeline position:
    kinase_annotation → rq_refinement → write_sections

Input (from state):
    - research_questions: List[str]  (original user questions, RQ0)
    - temporal_kinase_cascade: dict  (cross-timepoint kinase inference)
    - global_kinase_modules: dict    (kinase-centric modules)
    - comovement_analysis: dict      (co-movement clusters)
    - inferred_receptors: List[dict] (upstream receptor inference)
    - experimental_context: dict
    - enriched_ptm_data: List[dict]

Output (to state):
    - research_questions: List[str]         (refined RQ2 — overwrites original)
    - original_research_questions: List[str] (preserved RQ0 for tracking)
    - rq_refinement_metadata: dict          (full LLM response + diagnostics)
"""

import json
import logging
import os

from common.llm_client import LLMClient
from common.system_settings import get_bool

logger = logging.getLogger(__name__)

MAX_REFINED_QUESTIONS = 5
MAX_SUMMARY_CHARS = 3000

# ---------------------------------------------------------------------------
# System / user prompts (design doc Section 4.4 — Stage 2 Refinement)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a cell signaling expert. The PTM analysis pipeline has completed
network analysis, temporal co-movement clustering, and kinase annotation.
You now have a complete picture of the signaling architecture.

Your task: Elevate the research questions from "what changed" to
"how the signaling cascade operates" using the discovered architecture.

## RULES
1. Every refined question must reference a specific signaling chain:
   Receptor → Kinase → Substrate (→ Effector)
2. Incorporate temporal information:
   - Which events happen first? (co-movement cluster peak times)
   - Are there sequential dependencies? (cross-timepoint inference)
3. Connect upstream causes to downstream effects
4. Include at least one "predictive" question:
   - "If kinase X is inhibited, which downstream PTMs would be affected?"
   - "Does the temporal delay between Module A and Module B suggest
     a feedback mechanism?"
5. Maximum 5 refined questions (quality over quantity)

## OUTPUT FORMAT
Return ONLY a valid JSON object (no markdown fences, no commentary):
{
  "refined_questions": [
    {
      "question": "...",
      "category": "temporal | mechanistic | predictive | integrative",
      "signaling_chain": "EGFR → SRC → VIM-S56",
      "temporal_context": "SRC active at 2-5min, VIM-S56 peaks at 5min",
      "priority": "high | medium"
    }
  ],
  "key_discovery": "One-sentence summary of the most surprising finding",
  "suggested_experiments": [
    "Validation experiment that could confirm the key finding"
  ]
}
"""

USER_PROMPT_TEMPLATE = """\
## Original Research Questions
{research_questions}

## Experimental Context
- PTM type: {ptm_type}
- Species: {species}
- Cell type: {cell_type}
- Treatment: {treatment}
- Time points: {time_points}

## Discovered Signaling Architecture

### Inferred Upstream Receptors
{receptor_summary}

### Active Kinase Modules
{kinase_module_summary}

### Temporal Co-movement Clusters
{comovement_summary}

### Cross-Timepoint Kinase Inference
{cross_timepoint_summary}

### Signal Flow Summary
{signal_flow_summary}

## Task
Refine the original research questions using the discovered signaling
architecture above. Generate 3-5 specific sub-questions that are directly
grounded in this data.
"""


# ---------------------------------------------------------------------------
# Data extraction helpers — each returns a truncated text summary
# ---------------------------------------------------------------------------

def _extract_receptor_summary(state: dict) -> str:
    receptors = state.get("inferred_receptors") or []
    if not receptors:
        return "(No upstream receptors inferred)"
    lines = []
    for r in receptors[:10]:
        name = r.get("name", "?")
        src = r.get("source", "")
        ptm_cnt = r.get("downstream_ptm_count", 0)
        kinases = ", ".join(r.get("via_kinases", [])[:5])
        lines.append(f"- {name} (source: {src}, downstream PTMs: {ptm_cnt}, via kinases: {kinases})")
    return "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _extract_kinase_module_summary(state: dict) -> str:
    gkm = state.get("global_kinase_modules") or {}
    modules = gkm.get("kinase_modules") or []
    if not modules:
        return "(No kinase modules detected)"
    lines = []
    for m in modules[:15]:
        name = m.get("kinase", m.get("name", "?"))
        substrates = m.get("substrates", [])
        score = m.get("evidence_score", m.get("total_evidence", 0))
        sub_names = ", ".join(
            f"{s.get('gene', '?')}-{s.get('position', '?')}" for s in substrates[:5]
        )
        lines.append(f"- {name}: {len(substrates)} substrates (evidence={score}), top: {sub_names}")
    return "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _extract_comovement_summary(state: dict) -> str:
    cm = state.get("comovement_analysis") or {}
    clusters = cm.get("clusters") or []
    if not clusters:
        return "(No co-movement clusters detected)"
    lines = []
    for c in clusters[:10]:
        cid = c.get("cluster_id", c.get("id", "?"))
        pattern = c.get("pattern", c.get("label", ""))
        peak = c.get("peak_time", c.get("peak_timepoint", ""))
        members = c.get("members", [])
        pathway = c.get("dominant_pathway", c.get("enriched_pathways", [""])[0] if c.get("enriched_pathways") else "")
        rho = c.get("mean_rho", c.get("avg_correlation", ""))
        lines.append(
            f"- Cluster {cid}: pattern={pattern}, peak={peak}, "
            f"{len(members)} members, pathway={pathway}, rho={rho}"
        )
    return "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _extract_cross_timepoint_summary(state: dict) -> str:
    cascade = state.get("temporal_kinase_cascade") or {}
    cross_tp = cascade.get("cross_timepoint_inferences") or cascade.get("cross_tp_inferences") or []
    if not cross_tp:
        return "(No cross-timepoint inferences)"
    lines = []
    for inf in cross_tp[:10]:
        if isinstance(inf, dict):
            kinase = inf.get("kinase", "?")
            substrate = inf.get("substrate", "?")
            lag = inf.get("time_lag", inf.get("lag", ""))
            lines.append(f"- {kinase} (late) → {substrate} (early), lag={lag}")
        else:
            lines.append(f"- {inf}")
    return "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _extract_signal_flow_summary(state: dict) -> str:
    cascade = state.get("temporal_kinase_cascade") or {}
    llm_ctx = state.get("temporal_kinase_cascade_llm_context") or ""
    if llm_ctx:
        return llm_ctx[:MAX_SUMMARY_CHARS]

    tp_map = cascade.get("timepoint_kinase_map") or {}
    if not tp_map:
        return "(No signal flow data available)"
    lines = []
    for tp, kinases in list(tp_map.items())[:6]:
        k_names = ", ".join(str(k) for k in kinases[:5]) if isinstance(kinases, list) else str(kinases)
        lines.append(f"- Timepoint {tp}: {k_names}")
    return "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _parse_llm_json(raw: str) -> dict | None:
    """Best-effort JSON parsing from LLM output."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_rq_refinement(state: dict) -> dict:
    """Refine research questions using analysis results from upstream nodes."""
    cb = state.get("progress_callback")
    if cb:
        cb(67, "Refining research questions")

    original_questions = list(state.get("research_questions") or [])

    if not get_bool("ENABLE_RQ_REFINEMENT", True):
        logger.info("[RQ-REFINEMENT] Disabled via ENABLE_RQ_REFINEMENT=false — pass-through")
        if cb:
            cb(69, "RQ refinement skipped (disabled)")
        return {
            "original_research_questions": original_questions,
            "rq_refinement_metadata": {"skipped": True, "reason": "disabled"},
        }

    if not original_questions:
        logger.info("[RQ-REFINEMENT] No research questions provided — skipping")
        if cb:
            cb(69, "RQ refinement skipped (no questions)")
        return {
            "original_research_questions": [],
            "rq_refinement_metadata": {"skipped": True, "reason": "no_questions"},
        }

    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    if not llm.is_available():
        logger.warning("[RQ-REFINEMENT] LLM not available — keeping original questions")
        if cb:
            cb(69, "RQ refinement skipped (LLM unavailable)")
        return {
            "original_research_questions": original_questions,
            "rq_refinement_metadata": {"skipped": True, "reason": "llm_unavailable"},
        }

    ctx = state.get("experimental_context") or {}
    user_prompt = USER_PROMPT_TEMPLATE.format(
        research_questions="\n".join(f"- {q}" for q in original_questions),
        ptm_type=state.get("ptm_type", ctx.get("ptm_type", "phosphorylation")),
        species=ctx.get("species", "N/A"),
        cell_type=ctx.get("cell_type", ctx.get("cell_line", "N/A")),
        treatment=ctx.get("treatment", "N/A"),
        time_points=ctx.get("time_points", ctx.get("timepoints", "N/A")),
        receptor_summary=_extract_receptor_summary(state),
        kinase_module_summary=_extract_kinase_module_summary(state),
        comovement_summary=_extract_comovement_summary(state),
        cross_timepoint_summary=_extract_cross_timepoint_summary(state),
        signal_flow_summary=_extract_signal_flow_summary(state),
    )

    logger.info(f"[RQ-REFINEMENT] Sending {len(original_questions)} question(s) to LLM for refinement")

    try:
        raw = llm.generate(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.5,
            max_tokens=4096,
        )
    except Exception as e:
        logger.error(f"[RQ-REFINEMENT] LLM call failed: {e}")
        if cb:
            cb(69, "RQ refinement failed — keeping original questions")
        return {
            "original_research_questions": original_questions,
            "rq_refinement_metadata": {"skipped": True, "reason": f"llm_error: {e}"},
        }

    parsed = _parse_llm_json(raw)
    if not parsed or "refined_questions" not in parsed:
        logger.warning("[RQ-REFINEMENT] Failed to parse LLM JSON — keeping original questions")
        if cb:
            cb(69, "RQ refinement parse error — keeping original questions")
        return {
            "original_research_questions": original_questions,
            "rq_refinement_metadata": {
                "skipped": True,
                "reason": "json_parse_error",
                "raw_response": raw[:2000],
            },
        }

    refined_items = parsed["refined_questions"][:MAX_REFINED_QUESTIONS]
    refined_questions = [item["question"] for item in refined_items if item.get("question")]

    if not refined_questions:
        logger.warning("[RQ-REFINEMENT] LLM returned no valid questions — keeping originals")
        refined_questions = original_questions

    logger.info(
        f"[RQ-REFINEMENT] Refined {len(original_questions)} → {len(refined_questions)} questions"
    )
    for i, q in enumerate(refined_questions, 1):
        logger.info(f"  RQ{i}: {q[:120]}")

    if cb:
        cb(69, f"Research questions refined ({len(refined_questions)} questions)")

    return {
        "research_questions": refined_questions,
        "original_research_questions": original_questions,
        "rq_refinement_metadata": {
            "skipped": False,
            "original_count": len(original_questions),
            "refined_count": len(refined_questions),
            "refined_items": refined_items,
            "key_discovery": parsed.get("key_discovery", ""),
            "suggested_experiments": parsed.get("suggested_experiments", []),
        },
    }
