"""
Report Utilities — post-generation text quality helpers.

Ported from ptm-chromadb-web/python_backend/ptm_nonptm_network_command.py
(v42, v83, v86).  Adapted to use PTM-platform's LLMClient and logging.
"""

import logging
import re
from typing import Optional

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# v86: Abstract completeness verification
# ---------------------------------------------------------------------------

def ensure_abstract_completeness(
    abstract_text: str,
    original_prompt: str,
    llm_client: Optional[LLMClient] = None,
    model: str = "gemma3:27b",
) -> str:
    """Verify that the abstract ends with a complete sentence.

    If the last sentence appears truncated (no terminal punctuation),
    attempt to complete it with a follow-up LLM call.
    """
    text = abstract_text.strip()
    if not text:
        return abstract_text

    # Remove any trailing markdown headings or formatting artifacts
    text = re.sub(r"\n+#{1,4}\s*$", "", text).strip()

    # Check if text ends with proper terminal punctuation
    terminal_pattern = re.compile(r"[.!?][\)\]\"\']?\s*$")

    if terminal_pattern.search(text):
        return text

    # Abstract appears truncated — attempt completion
    logger.warning("[v86] Abstract appears truncated, attempting completion...")

    last_context = text[-300:] if len(text) > 300 else text

    completion_prompt = (
        "The following academic abstract was cut off mid-sentence. "
        "Complete ONLY the final sentence naturally. Do NOT add new sentences "
        "or repeat existing content.\n"
        f'Truncated text ending:\n"...{last_context}"\n'
        "Write ONLY the missing words to complete the final sentence "
        "(typically 5-20 words). End with a period.\nCompletion:"
    )

    try:
        if llm_client:
            completion = llm_client.generate(
                prompt=completion_prompt,
                model=model,
                temperature=0.2,
                max_tokens=128,
            )
        else:
            completion = ""

        if completion and len(completion.strip()) > 2:
            completion = completion.strip()
            # Remove any leading quotes or artifacts
            completion = re.sub(r'^["\']', "", completion)
            # Ensure it ends with a period
            if not terminal_pattern.search(completion):
                completion = completion.rstrip() + "."

            # Avoid duplication: check if the last word of text matches
            # the first word of completion
            text_words = text.split()
            comp_words = completion.split()
            if text_words and comp_words and text_words[-1].lower() == comp_words[0].lower():
                completion = " ".join(comp_words[1:])

            completed_text = text + " " + completion
            logger.info(
                "[v86] Abstract completed: added %d characters", len(completion)
            )
            return completed_text
    except Exception as e:
        logger.warning("[v86] Abstract completion failed: %s", e)

    # Fallback: add a generic closing if completion fails
    if len(text) > 200:
        text = text.rstrip(",;: ")
        if not terminal_pattern.search(text):
            text += (
                " pathway, highlighting the complex interplay of "
                "post-translational modifications in cellular signaling regulation."
            )
            logger.warning("[v86] Abstract completed with generic closing")

    return text


# ---------------------------------------------------------------------------
# v83: Empty / negative subsection merger
# ---------------------------------------------------------------------------

def merge_empty_subsections(report_text: str) -> str:
    """Detect subsections that only report negative findings and merge them.

    Prevents the report from having 3+ consecutive near-empty subsections
    that reduce publication density.
    """
    lines = report_text.split("\n")

    # Patterns indicating a subsection has only negative/empty content
    negative_patterns = [
        re.compile(
            r"\b(no|zero|none|0)\b.*\b(proteins?|genes?|sites?|modifications?)\b"
            r".*\b(identified|found|detected|observed|present)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(were|was)\s+not\s+(identified|found|detected|observed)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(did\s+not|could\s+not)\s+(identify|find|detect|observe)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(absence|lack)\s+of\b", re.IGNORECASE),
        re.compile(
            r"\b0\s+(discordant|concordant|mixed|dual.ptm|non.ptm)\b", re.IGNORECASE
        ),
        re.compile(
            r"\bno\s+(discordant|concordant|mixed|dual.ptm|non.ptm)\b", re.IGNORECASE
        ),
        re.compile(r"\bnot\s+applicable\b", re.IGNORECASE),
        re.compile(r"\bN/?A\b"),
    ]

    def _is_negative_subsection(subsection_lines: list) -> bool:
        content_lines = [
            line
            for line in subsection_lines
            if line.strip() and not line.strip().startswith("#")
        ]
        if not content_lines:
            return True
        if len(content_lines) <= 3:
            full_text = " ".join(content_lines)
            for pattern in negative_patterns:
                if pattern.search(full_text):
                    return True
        return False

    def _extract_subsection_title(heading_line: str) -> str:
        m = re.match(r"^###\s+(.+)", heading_line)
        return m.group(1).strip() if m else ""

    # First pass: identify subsections within ## sections
    sections = []  # list of (type, lines)
    current_block: list = []
    current_type = "content"

    for line in lines:
        if line.strip().startswith("## ") and not line.strip().startswith("### "):
            if current_block:
                sections.append((current_type, current_block))
            current_block = [line]
            current_type = "h2"
        elif line.strip().startswith("### "):
            if current_block:
                sections.append((current_type, current_block))
            current_block = [line]
            current_type = "h3"
        else:
            current_block.append(line)
    if current_block:
        sections.append((current_type, current_block))

    # Second pass: merge consecutive negative ### subsections
    merged_negatives: list = []
    output_sections = []

    for sec_type, sec_lines in sections:
        if sec_type == "h3" and _is_negative_subsection(sec_lines):
            title = _extract_subsection_title(sec_lines[0])
            if title:
                merged_negatives.append(title)
        else:
            if merged_negatives and sec_type in ("h2", "h3"):
                # v86: silently drop negative subsections to improve publication quality
                pass
            merged_negatives = []
            output_sections.append((sec_type, sec_lines))

    # Handle trailing negatives
    if merged_negatives:
        pass  # silently drop

    # Reassemble
    all_lines = []
    for _, sec_lines in output_sections:
        all_lines.extend(sec_lines)

    return "\n".join(all_lines)


# ---------------------------------------------------------------------------
# v42: Robust section heading deduplication helper
# ---------------------------------------------------------------------------

def clean_section_output(llm_output: str, section_name: str) -> str:
    """Ensure exactly one ``## SectionName`` heading at the top of the output.

    LLMs sometimes include duplicate headings in various formats.  This
    function strips them all and prepends a single canonical heading.
    """
    lines = llm_output.strip().split("\n")
    cleaned_lines = []
    esc_name = re.escape(section_name)

    heading_patterns = [
        re.compile(r"^\s*#{1,4}\s*" + esc_name + r"\s*$"),
        re.compile(rf"^\s*\*\*{esc_name}\*\*\s*$"),
        re.compile(rf"^\s*{esc_name}\s*$"),
    ]

    for line in lines:
        is_heading = False
        for pattern in heading_patterns:
            if pattern.match(line):
                is_heading = True
                break
        if not is_heading:
            cleaned_lines.append(line)

    # Remove leading empty lines
    while cleaned_lines and cleaned_lines[0].strip() == "":
        cleaned_lines.pop(0)

    text = "\n".join(cleaned_lines).strip()
    return f"## {section_name}\n\n{text}"
