"""
Report Co-pilot Node — v10.0

Runs after write_sections and before cascade_mediator.
Reviews draft report sections, identifies gaps / inconsistencies,
and generates enhancement suggestions grounded in analysis data.

Per design doc Section 8 note #4, this initial implementation stores
the review as metadata only — draft_addition is NOT auto-inserted into
sections. The review output can be surfaced to users for manual approval.

Pipeline position:
    write_sections → report_copilot → cascade_mediator

Input (from state):
    - sections: Dict[str, str]          (draft report text)
    - enriched_ptm_data: List[dict]
    - global_kinase_modules: dict
    - temporal_kinase_cascade: dict
    - comovement_analysis: dict
    - research_questions: List[str]     (refined RQ2)
    - chromadb_collections: List[str]

Output (to state):
    - sections: Dict[str, str]          (unchanged in v10.0)
    - copilot_review: dict              (review metadata)
"""

import json
import logging
import os

from common.llm_client import LLMClient
from common.system_settings import get_bool

logger = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 3000

# ---------------------------------------------------------------------------
# System / user prompts (design doc Section 3.2)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are POTATO AI operating in **Report Co-pilot Mode**. Your role is to
review a draft PTM analysis report and identify gaps, inconsistencies,
or opportunities for deeper analysis.

You have access to:
1. The draft report sections (Introduction, Results, Discussion)
2. The full enriched PTM dataset summary
3. Kinase module analysis results
4. Signal flow / receptor inference data
5. Temporal co-movement clusters

## CO-PILOT TASKS

### Task 1: Gap Analysis
Identify sections where:
- Claims are made without supporting data references
- Important PTMs from the dataset are not discussed
- Kinase-substrate relationships with high evidence scores are omitted
- Temporal patterns are mentioned but not mechanistically explained

### Task 2: Consistency Check
Verify that:
- Fold-change values cited in text match the actual data
- Pathway assignments are consistent across sections
- Temporal descriptions align with co-movement cluster data
- Receptor → Kinase → Substrate flow is logically coherent

### Task 3: Enhancement Suggestions
For each gap or inconsistency, generate:
- A specific question to investigate
- Which data source to query (enriched PTM, kinase modules, RAG literature)
- A draft paragraph that could fill the gap

### Task 4: Literature Integration
Using available data:
- Find supporting evidence for key claims
- Identify contradictory findings that should be discussed
- Suggest novel connections not yet mentioned in the report

## OUTPUT FORMAT
Return ONLY a valid JSON object (no markdown fences, no commentary):
{
  "overall_quality": "good | needs_improvement | major_gaps",
  "section_reviews": [
    {
      "section": "Results",
      "subsection": "...",
      "issue_type": "gap | inconsistency | enhancement",
      "description": "...",
      "severity": "high | medium | low",
      "suggested_query": "...",
      "data_source": "...",
      "draft_addition": "..."
    }
  ],
  "missing_connections": [
    {
      "from": "...",
      "to": "...",
      "relationship": "...",
      "significance": "..."
    }
  ],
  "literature_suggestions": [
    {
      "claim": "...",
      "novel_insight": "..."
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """\
## Research Questions (Refined)
{research_questions}

## Draft Report Sections

### Introduction
{introduction}

### Results
{results}

### Discussion
{discussion}

## Available Data Summary

### Enriched PTMs: {enriched_ptm_count} total
Top 10 by |fold-change|:
{top_ptms}

### Kinase Modules: {module_count} modules
{kinase_summary}

### Co-movement Clusters: {cluster_count} clusters
{cluster_summary}

### Signal Flow Context
{signal_flow}

## Task
Review the draft report against the available data. Identify gaps,
inconsistencies, and enhancement opportunities. For each issue,
provide a specific suggestion with draft text.
"""


# ---------------------------------------------------------------------------
# Data summary helpers
# ---------------------------------------------------------------------------

def _summarize_top_ptms(enriched: list, n: int = 10) -> str:
    if not enriched:
        return "(No enriched PTM data)"
    scored = []
    for p in enriched:
        gene = p.get("gene_name", p.get("Gene_Name", "?"))
        pos = p.get("position", p.get("Position", "?"))
        fc = p.get("fold_change", p.get("Fold_Change", 0))
        try:
            abs_fc = abs(float(fc))
        except (ValueError, TypeError):
            abs_fc = 0
        scored.append((abs_fc, gene, pos, fc))
    scored.sort(reverse=True)
    lines = []
    for abs_fc, gene, pos, fc in scored[:n]:
        lines.append(f"- {gene}-{pos}: fold-change={fc}")
    return "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _summarize_kinase_modules(state: dict) -> tuple[int, str]:
    gkm = state.get("global_kinase_modules") or {}
    modules = gkm.get("kinase_modules") or []
    if not modules:
        return 0, "(No kinase modules)"
    lines = []
    for m in modules[:10]:
        name = m.get("kinase", m.get("name", "?"))
        subs = m.get("substrates", [])
        score = m.get("evidence_score", m.get("total_evidence", 0))
        lines.append(f"- {name}: {len(subs)} substrates (evidence={score})")
    return len(modules), "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _summarize_clusters(state: dict) -> tuple[int, str]:
    cm = state.get("comovement_analysis") or {}
    clusters = cm.get("clusters") or []
    if not clusters:
        return 0, "(No co-movement clusters)"
    lines = []
    for c in clusters[:10]:
        cid = c.get("cluster_id", c.get("id", "?"))
        pattern = c.get("pattern", c.get("label", ""))
        members = c.get("members", [])
        lines.append(f"- Cluster {cid}: {pattern}, {len(members)} members")
    return len(clusters), "\n".join(lines)[:MAX_SUMMARY_CHARS]


def _parse_llm_json(raw: str) -> dict | None:
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

def run_report_copilot(state: dict) -> dict:
    """Review draft report and generate enhancement suggestions."""
    cb = state.get("progress_callback")
    if cb:
        cb(78, "Report co-pilot reviewing draft")

    sections = state.get("sections") or {}

    if not get_bool("ENABLE_REPORT_COPILOT", True):
        logger.info("[REPORT-COPILOT] Disabled via ENABLE_REPORT_COPILOT=false — pass-through")
        if cb:
            cb(79, "Report co-pilot skipped (disabled)")
        return {"copilot_review": {"skipped": True, "reason": "disabled"}}

    if not sections:
        logger.info("[REPORT-COPILOT] No draft sections — skipping review")
        if cb:
            cb(79, "Report co-pilot skipped (no sections)")
        return {"copilot_review": {"skipped": True, "reason": "no_sections"}}

    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    if not llm.is_available():
        logger.warning("[REPORT-COPILOT] LLM not available — skipping review")
        if cb:
            cb(79, "Report co-pilot skipped (LLM unavailable)")
        return {"copilot_review": {"skipped": True, "reason": "llm_unavailable"}}

    questions = state.get("research_questions") or []
    enriched = state.get("enriched_ptm_data") or []
    module_count, kinase_summary = _summarize_kinase_modules(state)
    cluster_count, cluster_summary = _summarize_clusters(state)
    signal_flow = (state.get("temporal_kinase_cascade_llm_context") or "")[:MAX_SUMMARY_CHARS]

    def _sect(name: str) -> str:
        val = sections.get(name, "")
        return val[:6000] if val else "(Not generated)"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        research_questions="\n".join(f"- {q}" for q in questions) or "(None)",
        introduction=_sect("introduction"),
        results=_sect("results"),
        discussion=_sect("discussion"),
        enriched_ptm_count=len(enriched),
        top_ptms=_summarize_top_ptms(enriched),
        module_count=module_count,
        kinase_summary=kinase_summary,
        cluster_count=cluster_count,
        cluster_summary=cluster_summary,
        signal_flow=signal_flow or "(No signal flow data)",
    )

    logger.info("[REPORT-COPILOT] Sending draft for co-pilot review")

    try:
        raw = llm.generate(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=8192,
        )
    except Exception as e:
        logger.error(f"[REPORT-COPILOT] LLM call failed: {e}")
        if cb:
            cb(79, "Report co-pilot failed — continuing without review")
        return {"copilot_review": {"skipped": True, "reason": f"llm_error: {e}"}}

    parsed = _parse_llm_json(raw)
    if not parsed:
        logger.warning("[REPORT-COPILOT] Failed to parse LLM JSON — skipping review")
        if cb:
            cb(79, "Report co-pilot parse error — continuing")
        return {
            "copilot_review": {
                "skipped": True,
                "reason": "json_parse_error",
                "raw_response": raw[:2000],
            },
        }

    overall = parsed.get("overall_quality", "unknown")
    review_count = len(parsed.get("section_reviews", []))
    missing_count = len(parsed.get("missing_connections", []))

    logger.info(
        f"[REPORT-COPILOT] Review complete: quality={overall}, "
        f"{review_count} section issues, {missing_count} missing connections"
    )

    if cb:
        cb(79, f"Report reviewed (quality: {overall}, {review_count} suggestions)")

    return {
        "copilot_review": {
            "skipped": False,
            "overall_quality": overall,
            "section_reviews": parsed.get("section_reviews", []),
            "missing_connections": parsed.get("missing_connections", []),
            "literature_suggestions": parsed.get("literature_suggestions", []),
        },
    }
