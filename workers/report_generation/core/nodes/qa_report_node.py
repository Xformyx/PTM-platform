"""
Q&A Report Generator Node — System-Level Thematic Q&A (v11.9).

Restructured from per-PTM Q&A (220+ LLM calls) to system-level thematic analysis
(15-20 LLM calls total). Uses the full report + co-movement + kinase cascade +
TF inference data as context for each theme.

Strategy: 5 Themes × 3-4 Q&A pairs (parallel execution via ThreadPoolExecutor)
  Theme 1: Signaling Cascade & Temporal Dynamics
  Theme 2: Cross-talk & Co-regulation
  Theme 3: Mechanism of Action (Drug/Treatment)
  Theme 4: Therapeutic Implications
  Theme 5: Validation & Limitations

Features:
  - System-level analysis (not per-PTM)
  - Full context injection (report + kinase + TF + co-movement)
  - Parallel execution (5 themes simultaneously, configurable via QA_LLM_WORKERS env var)
  - Structured Q&A with evidence-based answers
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

QA_SYSTEM_PROMPT = """\
You are an expert in post-translational modification (PTM) biology, cell signaling,
and systems pharmacology. You are reviewing a comprehensive PTM analysis report
and generating research-level Q&A pairs that help researchers understand the
biological significance of the findings at a SYSTEMS level.

Key principles:
- Focus on signaling MECHANISMS, not just descriptions of individual PTMs
- Connect observations to upstream/downstream pathway logic
- Reference specific data points (fold-changes, timepoints, kinase scores)
- Distinguish between established knowledge and novel findings
- Be critical about limitations and alternative interpretations
"""


# ---------------------------------------------------------------------------
# Theme Definitions
# ---------------------------------------------------------------------------

THEMES = [
    {
        "id": "signaling_cascade",
        "title": "Signaling Cascade & Temporal Dynamics",
        "n_questions": 4,
        "focus": """\
Focus on the temporal ORDER of signaling events:
- Which kinases/pathways are activated first vs. later?
- How do early phosphorylation events propagate to downstream effectors?
- What do co-movement clusters reveal about coordinated signaling modules?
- Are there temporal delays suggesting transcriptional vs. post-translational regulation?
- How does the kinase cascade data support or contradict canonical pathway models?
""",
    },
    {
        "id": "crosstalk_coregulation",
        "title": "Cross-talk & Co-regulation",
        "n_questions": 4,
        "focus": """\
Focus on INTERACTIONS between pathways:
- Which kinase modules share substrates or show coordinated activity?
- What does co-movement clustering reveal about pathway cross-talk?
- Are there opposing pathways (e.g., pro-survival vs. apoptotic) simultaneously active?
- How do transcription factor (TF) activity patterns correlate with kinase modules?
- What novel cross-talk relationships are suggested by the data?
""",
    },
    {
        "id": "mechanism_of_action",
        "title": "Mechanism of Action",
        "n_questions": 4,
        "focus": """\
Focus on the DRUG/TREATMENT mechanism:
- What is the primary signaling target based on the earliest PTM changes?
- How does the observed kinase activity pattern explain the treatment's mechanism?
- Which off-target effects are suggested by unexpected pathway activations?
- How do the inferred upstream receptors connect to the treatment's known pharmacology?
- What compensatory/resistance mechanisms are suggested by late-stage PTM changes?
""",
    },
    {
        "id": "therapeutic_implications",
        "title": "Therapeutic Implications",
        "n_questions": 3,
        "focus": """\
Focus on TRANSLATIONAL significance:
- Which identified kinases/pathways represent actionable drug targets?
- What combination therapy strategies are suggested by the cross-talk data?
- Are there biomarker candidates (early-responding PTMs) for treatment monitoring?
- How do the TF activity changes suggest potential resistance mechanisms?
- What patient stratification strategies are implied by the signaling patterns?
""",
    },
    {
        "id": "validation_limitations",
        "title": "Validation & Limitations",
        "n_questions": 3,
        "focus": """\
Focus on DATA QUALITY and INTERPRETATION LIMITS:
- Which findings are well-supported by multiple evidence sources vs. single-source?
- What are the key assumptions in the kinase inference that could affect conclusions?
- Which novel PTM sites lack literature validation and require experimental confirmation?
- How might the experimental design (timepoints, cell type) limit generalizability?
- What orthogonal experiments would strengthen the key conclusions?
""",
    },
]


# ---------------------------------------------------------------------------
# Context Builders
# ---------------------------------------------------------------------------

MAX_SECTION_CHARS = 5000
MAX_CONTEXT_CHARS = 3000


def _build_report_summary(sections: Dict[str, str]) -> str:
    """Build a condensed report summary from written sections."""
    parts = []
    for name in ("introduction", "results", "discussion", "conclusion"):
        content = sections.get(name, "")
        if content:
            # Take first N chars of each section
            truncated = content[:MAX_SECTION_CHARS]
            if len(content) > MAX_SECTION_CHARS:
                truncated += "\n[... truncated ...]"
            parts.append(f"### {name.title()}\n{truncated}")
    return "\n\n".join(parts) if parts else "(No report sections available)"


def _build_kinase_context(state: dict) -> str:
    """Build kinase cascade + module context."""
    lines = []

    # Kinase cascade LLM context (already formatted)
    cascade_ctx = state.get("temporal_kinase_cascade_llm_context", "")
    if cascade_ctx:
        lines.append("=== TEMPORAL KINASE CASCADE ===")
        lines.append(cascade_ctx[:MAX_CONTEXT_CHARS])

    # Global kinase modules summary
    gkm = state.get("global_kinase_modules") or {}
    modules = gkm.get("kinase_modules") or []
    if modules:
        lines.append("\n=== KINASE MODULES (top 10) ===")
        for m in modules[:10]:
            name = m.get("kinase", m.get("name", "?"))
            subs = m.get("substrates", [])
            score = m.get("evidence_score", m.get("total_evidence", 0))
            sources = m.get("sources", [])
            lines.append(
                f"- {name}: {len(subs)} substrates, evidence={score}, "
                f"sources={','.join(sources[:3]) if sources else 'N/A'}"
            )

    return "\n".join(lines) if lines else ""


def _build_comovement_context(state: dict) -> str:
    """Build co-movement cluster context."""
    ctx = state.get("comovement_llm_context", "")
    if ctx:
        return ctx[:MAX_CONTEXT_CHARS]

    # Fallback: build from comovement_analysis
    cm = state.get("comovement_analysis") or {}
    clusters = cm.get("clusters") or []
    if not clusters:
        return ""

    lines = ["=== CO-MOVEMENT CLUSTERS ==="]
    for c in clusters[:8]:
        cid = c.get("cluster_id", c.get("id", "?"))
        pattern = c.get("pattern", c.get("label", ""))
        members = c.get("members", [])
        member_str = ", ".join(m.get("label", str(m)) if isinstance(m, dict) else str(m) for m in members[:5])
        lines.append(f"- Cluster {cid} ({pattern}): {len(members)} members [{member_str}...]")
    return "\n".join(lines)


def _build_tf_context(state: dict) -> str:
    """Build TF activity inference context."""
    tf_data = state.get("tf_inference_data") or {}
    if not tf_data:
        return ""

    lines = ["=== TF ACTIVITY INFERENCE (DoRothEA + TRRUST) ==="]

    inferred = tf_data.get("inferred_tfs") or []
    if inferred:
        lines.append(f"Total inferred TFs: {len(inferred)}")
        for tf in inferred[:10]:
            name = tf.get("tf_name", tf.get("name", "?"))
            pval = tf.get("p_value", tf.get("pval", "N/A"))
            targets_hit = tf.get("targets_hit", tf.get("overlap", 0))
            direction = tf.get("direction", "")
            lines.append(f"- {name}: p={pval}, targets_hit={targets_hit}, direction={direction}")

    cross_val = tf_data.get("cross_validated") or []
    if cross_val:
        lines.append(f"\nCross-validated TF-Kinase links: {len(cross_val)}")
        for cv in cross_val[:5]:
            lines.append(f"- {cv.get('tf', '?')} ↔ {cv.get('kinase', '?')}: {cv.get('mechanism', '')}")

    novel = tf_data.get("novel_findings") or []
    if novel:
        lines.append(f"\nNovel findings: {len(novel)}")
        for nf in novel[:3]:
            lines.append(f"- {nf.get('description', str(nf)[:100])}")

    return "\n".join(lines)


def _build_experimental_context(state: dict) -> str:
    """Build experimental context summary."""
    ctx = state.get("experimental_context") or {}
    if not ctx:
        return ""

    lines = ["=== EXPERIMENTAL CONTEXT ==="]
    for key in ("cell_type", "tissue", "treatment", "time_points", "control", "biological_question", "organism"):
        val = ctx.get(key, "")
        if val:
            lines.append(f"- {key.replace('_', ' ').title()}: {val}")
    return "\n".join(lines)


def _build_crosstalk_context(state: dict) -> str:
    """Build cross-talk analysis context (if available)."""
    ct = state.get("crosstalk_data") or state.get("cross_talk_data") or {}
    if not ct:
        return ""

    lines = ["=== CROSS-TALK ANALYSIS ==="]
    summary = ct.get("summary", "")
    if summary:
        lines.append(summary[:1500])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Q&A Generation
# ---------------------------------------------------------------------------

def _build_theme_prompt(
    theme: dict,
    report_summary: str,
    experimental_ctx: str,
    kinase_ctx: str,
    comovement_ctx: str,
    tf_ctx: str,
    crosstalk_ctx: str,
) -> str:
    """Build the prompt for generating Q&A pairs for a specific theme."""
    n_q = theme["n_questions"]

    prompt = f"""## Theme: {theme['title']}

{theme['focus']}

Generate exactly {n_q} Q&A pairs for this theme based on the data below.

### FORMAT REQUIREMENTS
For each Q&A pair, use this exact format:
Q: [Specific, data-grounded question]
A: [Detailed answer (200-400 words) citing specific data points, fold-changes, timepoints, and kinase/pathway names from the provided context]

---

## AVAILABLE DATA

{experimental_ctx}

## REPORT CONTENT
{report_summary}

"""
    # Add supplementary context blocks (only non-empty ones)
    if kinase_ctx:
        prompt += f"\n{kinase_ctx}\n"
    if comovement_ctx:
        prompt += f"\n{comovement_ctx}\n"
    if tf_ctx:
        prompt += f"\n{tf_ctx}\n"
    if crosstalk_ctx:
        prompt += f"\n{crosstalk_ctx}\n"

    prompt += f"""
---

## INSTRUCTIONS
- Generate exactly {n_q} Q&A pairs for the theme "{theme['title']}"
- Each answer MUST reference specific data from the context above
- Do NOT repeat information already covered in the report — add NEW analytical depth
- Focus on SYSTEMS-LEVEL interpretation, not individual PTM descriptions
- Be critical: acknowledge uncertainties and alternative interpretations
"""
    return prompt


def _parse_qa_pairs(text: str) -> List[Dict[str, str]]:
    """Parse Q&A pairs from LLM response."""
    pairs = []
    lines = text.split("\n")
    current_q = ""
    current_a_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Q:") or stripped.startswith("**Q:**"):
            # Save previous pair
            if current_q and current_a_lines:
                pairs.append({
                    "question": current_q,
                    "answer": "\n".join(current_a_lines).strip(),
                })
            current_q = stripped.replace("**Q:**", "").replace("Q:", "").strip()
            current_a_lines = []
        elif stripped.startswith("A:") or stripped.startswith("**A:**"):
            answer_start = stripped.replace("**A:**", "").replace("A:", "").strip()
            current_a_lines = [answer_start]
        elif current_a_lines is not None and current_q:
            # Continue accumulating answer text
            current_a_lines.append(line)

    # Save last pair
    if current_q and current_a_lines:
        pairs.append({
            "question": current_q,
            "answer": "\n".join(current_a_lines).strip(),
        })

    return pairs


# ---------------------------------------------------------------------------
# Main Generator Class
# ---------------------------------------------------------------------------

class SystemLevelQAGenerator:
    """Generates system-level thematic Q&A reports (v11.9)."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def generate(
        self,
        state: dict,
        progress_callback=None,
    ) -> str:
        """
        Generate system-level Q&A report from pipeline state.

        Args:
            state: Full LangGraph state dict with all analysis results
            progress_callback: Optional callback(pct, msg)

        Returns:
            Markdown string of the Q&A report.
        """
        if progress_callback:
            progress_callback(0, "Building context for system-level Q&A")

        # 1. Build context blocks from state
        sections = state.get("sections") or {}
        report_summary = _build_report_summary(sections)
        experimental_ctx = _build_experimental_context(state)
        kinase_ctx = _build_kinase_context(state)
        comovement_ctx = _build_comovement_context(state)
        tf_ctx = _build_tf_context(state)
        crosstalk_ctx = _build_crosstalk_context(state)

        logger.info(
            f"[QA-v11.9] Context sizes: report={len(report_summary)}, "
            f"kinase={len(kinase_ctx)}, comovement={len(comovement_ctx)}, "
            f"tf={len(tf_ctx)}, crosstalk={len(crosstalk_ctx)}"
        )

        # 2. Generate Q&A for all themes in parallel (ThreadPoolExecutor)
        # v11.10: Parallelized — 5 themes have no cross-dependencies
        _QA_WORKERS = int(os.getenv("QA_LLM_WORKERS", "5"))
        total_themes = len(THEMES)
        total_calls = 0

        # Pre-build all prompts (thread-safe, no shared mutable state)
        theme_prompts = []
        for theme in THEMES:
            prompt = _build_theme_prompt(
                theme=theme,
                report_summary=report_summary,
                experimental_ctx=experimental_ctx,
                kinase_ctx=kinase_ctx,
                comovement_ctx=comovement_ctx,
                tf_ctx=tf_ctx,
                crosstalk_ctx=crosstalk_ctx,
            )
            theme_prompts.append((theme, prompt))

        if progress_callback:
            progress_callback(5, f"Generating Q&A: {total_themes} themes in parallel ({_QA_WORKERS} workers)")

        logger.info(f"[QA-v11.10] Starting parallel Q&A generation: {total_themes} themes, {_QA_WORKERS} workers")

        def _generate_one_theme(theme_prompt_pair):
            """Generate Q&A for a single theme (thread-safe)."""
            theme, prompt = theme_prompt_pair
            response = self.llm.generate(
                prompt=prompt,
                system_prompt=QA_SYSTEM_PROMPT,
                temperature=0.5,
                max_tokens=4000,
            )
            if response.startswith("[LLM Error"):
                logger.error(f"[QA-v11.10] LLM error for theme '{theme['title']}': {response[:200]}")
                return {
                    "theme": theme,
                    "qa_pairs": [],
                    "raw_response": response,
                    "error": True,
                }
            qa_pairs = _parse_qa_pairs(response)
            logger.info(f"[QA-v11.10] Theme '{theme['title']}': {len(qa_pairs)} Q&A pairs parsed")
            return {
                "theme": theme,
                "qa_pairs": qa_pairs,
                "raw_response": response,
                "error": False,
            }

        # Preserve original theme order in results
        all_theme_results: List[Dict] = [None] * total_themes
        workers = min(_QA_WORKERS, total_themes)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_idx = {
                pool.submit(_generate_one_theme, tp): idx
                for idx, tp in enumerate(theme_prompts)
            }
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                result = fut.result()
                all_theme_results[idx] = result
                total_calls += 1
                if progress_callback:
                    pct = 5 + (total_calls / total_themes) * 85
                    progress_callback(pct, f"Q&A done: {result['theme']['title']}")
                logger.info(
                    f"[QA-v11.10] Completed {total_calls}/{total_themes}: {result['theme']['title']}"
                )

        # 3. Assemble final report
        if progress_callback:
            progress_callback(92, "Assembling Q&A report")

        report = self._assemble_report(all_theme_results, state)

        logger.info(
            f"[QA-v11.9] Complete: {total_calls} LLM calls, "
            f"{sum(len(r['qa_pairs']) for r in all_theme_results)} total Q&A pairs"
        )

        if progress_callback:
            progress_callback(100, "Q&A report complete")

        return report

    def _assemble_report(self, theme_results: List[Dict], state: dict) -> str:
        """Assemble the final Q&A report from theme results."""
        ctx = state.get("experimental_context") or {}

        header = (
            "# System-Level Q&A Analysis Report\n\n"
            "## Experimental Context\n\n"
            f"- **Cell Type:** {ctx.get('cell_type', ctx.get('tissue', 'N/A'))}\n"
            f"- **Treatment:** {ctx.get('treatment', 'N/A')}\n"
            f"- **Biological Question:** {ctx.get('biological_question', 'N/A')}\n\n"
            "> This Q&A report provides system-level analysis across 5 thematic areas,\n"
            "> integrating kinase cascade, co-movement, TF inference, and cross-talk data.\n\n"
            "---\n\n"
        )

        body_parts = []
        for result in theme_results:
            theme = result["theme"]
            qa_pairs = result["qa_pairs"]

            section = f"## {theme['title']}\n\n"

            if result.get("error"):
                section += "> ⚠️ Q&A generation failed for this theme. See logs for details.\n\n"
            elif not qa_pairs:
                # Fallback: include raw response if parsing failed
                raw = result.get("raw_response", "")
                if raw and not raw.startswith("[LLM Error"):
                    section += raw + "\n\n"
                else:
                    section += "> No Q&A pairs generated for this theme.\n\n"
            else:
                for j, pair in enumerate(qa_pairs, 1):
                    section += f"### Q{j}: {pair['question']}\n\n"
                    section += f"{pair['answer']}\n\n"

            body_parts.append(section)

        return header + "\n---\n\n".join(body_parts)


# ---------------------------------------------------------------------------
# LangGraph Node Entry Point
# ---------------------------------------------------------------------------

def run_qa_report_generation(state: dict) -> dict:
    """LangGraph node: Generate system-level thematic Q&A report (v11.9)."""
    cb = state.get("progress_callback")
    if cb:
        cb(92, "Generating system-level Q&A report")

    sections = state.get("sections", {})
    if not sections:
        logger.warning("[QA-v11.9] No sections available for Q&A generation")
        return {"qa_report": ""}

    # Create LLM client
    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    generator = SystemLevelQAGenerator(llm_client=llm)

    # Remap internal 0-100% progress to the 92-95% overall range
    def _qa_inner_cb(pct, msg):
        if cb:
            mapped = 92 + (pct / 100) * 3
            cb(mapped, msg)

    qa_report = generator.generate(state, progress_callback=_qa_inner_cb)

    if cb:
        cb(95, "Q&A report generated")

    return {"qa_report": qa_report}
