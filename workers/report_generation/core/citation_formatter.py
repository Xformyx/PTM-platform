"""
Citation & Reference Formatter — formats in-text citations and reference lists.

Ported from ptm-rag-backend/src/citationFormatter.ts and referenceFormatter.ts.

Features:
  - In-text citation numbering and formatting
  - Vancouver-style reference list generation
  - Duplicate reference merging
  - PMID / DOI link embedding
  - Markdown reference section output
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class Reference:
    """A single bibliographic reference."""
    authors: str = ""
    title: str = ""
    journal: str = ""
    year: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    pmid: str = ""
    doi: str = ""
    url: str = ""
    source_collection: str = ""  # ChromaDB collection it came from

    @property
    def key(self) -> str:
        """Unique key for deduplication (title-based)."""
        return re.sub(r"[^a-z0-9]", "", self.title.lower())[:80]


@dataclass
class CitationResult:
    """Result of citation processing."""
    text: str = ""  # Processed text with [N] citations
    references: List[Reference] = field(default_factory=list)
    reference_section: str = ""  # Formatted reference list as Markdown


# ---------------------------------------------------------------------------
# Citation Formatter
# ---------------------------------------------------------------------------

class CitationFormatter:
    """Formats in-text citations and generates reference lists."""

    def __init__(self):
        self._ref_map: Dict[str, int] = {}  # ref_key -> citation number
        self._references: List[Reference] = []

    def reset(self):
        """Reset citation state for a new document."""
        self._ref_map = {}
        self._references = []

    def add_reference(self, ref: Reference) -> int:
        """
        Add a reference and return its citation number.
        Deduplicates by title.
        """
        key = ref.key
        if key in self._ref_map:
            return self._ref_map[key]

        num = len(self._references) + 1
        self._ref_map[key] = num
        self._references.append(ref)
        return num

    def get_citation_number(self, ref: Reference) -> int:
        """Get or assign a citation number for a reference."""
        return self.add_reference(ref)

    def format_inline_citation(self, refs: List[Reference]) -> str:
        """
        Format inline citation for one or more references.
        Returns: "[1]", "[1,2]", "[1-3]", etc.
        """
        numbers = sorted(set(self.add_reference(r) for r in refs))

        if not numbers:
            return ""

        # Group consecutive numbers into ranges
        ranges = []
        start = numbers[0]
        end = numbers[0]

        for n in numbers[1:]:
            if n == end + 1:
                end = n
            else:
                ranges.append((start, end))
                start = n
                end = n
        ranges.append((start, end))

        parts = []
        for s, e in ranges:
            if s == e:
                parts.append(str(s))
            elif e == s + 1:
                parts.append(f"{s},{e}")
            else:
                parts.append(f"{s}-{e}")

        return f"[{','.join(parts)}]"

    def process_text(
        self,
        text: str,
        rag_results: List[Dict],
    ) -> CitationResult:
        """
        Process report text by:
          1. Finding citation placeholders (e.g., [REF:pmid], [CITE:title])
          2. Replacing them with numbered citations
          3. Appending references from RAG results

        Also auto-cites RAG evidence that appears in the text.

        Args:
            text: Report text (Markdown)
            rag_results: RAG retrieval results with metadata

        Returns:
            CitationResult with processed text and reference list
        """
        self.reset()

        # Build references from RAG results
        rag_refs: Dict[str, Reference] = {}
        for r in rag_results:
            meta = r.get("metadata", {})
            ref = Reference(
                authors=meta.get("authors", ""),
                title=meta.get("title", r.get("title", "")),
                journal=meta.get("journal", meta.get("source", "")),
                year=str(meta.get("year", "")),
                volume=meta.get("volume", ""),
                pages=meta.get("pages", ""),
                pmid=str(meta.get("pmid", "")),
                doi=meta.get("doi", ""),
                source_collection=r.get("collection", ""),
            )
            if ref.title:
                rag_refs[ref.key] = ref

        # Replace explicit citation placeholders
        processed = text

        # Pattern: [REF:pmid_or_title]
        def _replace_ref(match):
            ref_id = match.group(1).strip()
            # Try to find matching reference
            for key, ref in rag_refs.items():
                if ref.pmid == ref_id or ref_id.lower() in ref.title.lower():
                    num = self.add_reference(ref)
                    return f"[{num}]"
            return match.group(0)  # Keep original if not found

        processed = re.sub(r"\[REF:([^\]]+)\]", _replace_ref, processed)
        processed = re.sub(r"\[CITE:([^\]]+)\]", _replace_ref, processed)

        # Auto-cite: find sentences that closely match RAG evidence
        for key, ref in rag_refs.items():
            if ref.title and len(ref.title) > 20:
                # Check if title or key phrases appear in text
                title_words = set(ref.title.lower().split())
                # Only auto-cite if not already cited
                if key not in self._ref_map:
                    # Simple heuristic: if author name + year appears
                    if ref.authors and ref.year:
                        author_last = ref.authors.split(",")[0].split()[-1] if ref.authors else ""
                        if author_last and author_last.lower() in processed.lower():
                            self.add_reference(ref)

        # Generate reference section
        ref_section = self.format_reference_list()

        return CitationResult(
            text=processed,
            references=list(self._references),
            reference_section=ref_section,
        )

    def format_reference_list(self) -> str:
        """
        Format the complete reference list in Vancouver style.

        Returns:
            Markdown-formatted reference list
        """
        if not self._references:
            return ""

        lines = ["## References\n"]

        for i, ref in enumerate(self._references, 1):
            entry = self._format_vancouver(i, ref)
            lines.append(entry)

        return "\n".join(lines)

    def _format_vancouver(self, num: int, ref: Reference) -> str:
        """Format a single reference in Vancouver style."""
        parts = []

        # Authors
        if ref.authors:
            parts.append(ref.authors.rstrip("."))

        # Title
        if ref.title:
            title = ref.title.rstrip(".")
            parts.append(f"{title}.")

        # Journal, Year, Volume
        journal_part = ""
        if ref.journal:
            journal_part = f"*{ref.journal}*"
        if ref.year:
            journal_part += f" ({ref.year})"
        if ref.volume:
            journal_part += f"; {ref.volume}"
            if ref.issue:
                journal_part += f"({ref.issue})"
        if ref.pages:
            journal_part += f": {ref.pages}"
        if journal_part:
            parts.append(journal_part.strip() + ".")

        # Links
        links = []
        if ref.pmid:
            links.append(f"PMID: [{ref.pmid}](https://pubmed.ncbi.nlm.nih.gov/{ref.pmid}/)")
        if ref.doi:
            doi_url = ref.doi if ref.doi.startswith("http") else f"https://doi.org/{ref.doi}"
            links.append(f"DOI: [{ref.doi}]({doi_url})")

        entry = f"{num}. " + " ".join(parts)
        if links:
            entry += " " + " | ".join(links)

        return entry


# ---------------------------------------------------------------------------
# Comprehensive Report Parser (post-processing)
# ---------------------------------------------------------------------------

class ReportPostProcessor:
    """
    Post-processes generated reports for quality and consistency.

    Ported from ptm-rag-backend/src/comprehensiveReportParser.ts.

    Features:
      - Section heading normalization
      - Empty section removal
      - Citation consistency check
      - Table formatting validation
      - Duplicate paragraph detection
    """

    EXPECTED_SECTIONS = [
        "Abstract",
        "Introduction",
        "Results",
        "Time-Course Analysis",
        "Discussion",
        "Conclusion",
        "References",
    ]

    def process(self, markdown_text: str) -> str:
        """Apply all post-processing steps."""
        text = markdown_text

        text = self._normalize_headings(text)
        text = self._remove_empty_sections(text)
        text = self._fix_citation_format(text)
        text = self._remove_duplicate_paragraphs(text)
        text = self._fix_table_formatting(text)
        text = self._ensure_section_order(text)

        return text

    def _normalize_headings(self, text: str) -> str:
        """Normalize section headings to ## level."""
        # Fix inconsistent heading levels
        text = re.sub(r"^#{3,}\s+", "## ", text, flags=re.MULTILINE)
        # Fix headings without space after #
        text = re.sub(r"^(#{1,2})([A-Z])", r"\1 \2", text, flags=re.MULTILINE)
        return text

    def _remove_empty_sections(self, text: str) -> str:
        """Remove sections with no content."""
        lines = text.split("\n")
        result = []
        i = 0

        while i < len(lines):
            line = lines[i]
            if line.startswith("## "):
                # Look ahead for content
                j = i + 1
                has_content = False
                while j < len(lines) and not lines[j].startswith("## "):
                    if lines[j].strip():
                        has_content = True
                        break
                    j += 1

                if has_content:
                    result.append(line)
                else:
                    logger.info(f"Removing empty section: {line.strip()}")
                    i = j
                    continue
            else:
                result.append(line)
            i += 1

        return "\n".join(result)

    def _fix_citation_format(self, text: str) -> str:
        """Fix common citation formatting issues."""
        # Fix double brackets: [[1]] -> [1]
        text = re.sub(r"\[\[(\d+(?:,\d+)*)\]\]", r"[\1]", text)
        # Fix space before citation: word [1] -> word[1] (optional style)
        # Fix citations without closing bracket
        text = re.sub(r"\[(\d+)\s*$", r"[\1]", text, flags=re.MULTILINE)
        return text

    def _remove_duplicate_paragraphs(self, text: str) -> str:
        """Remove duplicate paragraphs (common LLM artifact)."""
        paragraphs = text.split("\n\n")
        seen = set()
        unique = []

        for para in paragraphs:
            normalized = re.sub(r"\s+", " ", para.strip()).lower()
            if len(normalized) < 50:  # Keep short paragraphs (headings, etc.)
                unique.append(para)
                continue
            if normalized not in seen:
                seen.add(normalized)
                unique.append(para)
            else:
                logger.info(f"Removing duplicate paragraph: {normalized[:60]}...")

        return "\n\n".join(unique)

    def _fix_table_formatting(self, text: str) -> str:
        """Fix common Markdown table issues."""
        lines = text.split("\n")
        result = []

        for i, line in enumerate(lines):
            if "|" in line and line.strip().startswith("|"):
                # Ensure table separator row exists
                if i + 1 < len(lines) and "|" in lines[i + 1]:
                    cells = line.count("|") - 1
                    if not re.match(r"^\|[\s:-]+\|", lines[i + 1]):
                        result.append(line)
                        # Check if next line is data, not separator
                        if not re.match(r"^\|[-:\s|]+\|$", lines[i + 1]):
                            sep = "|" + "|".join(["---"] * max(cells, 1)) + "|"
                            result.append(sep)
                        continue
            result.append(line)

        return "\n".join(result)

    def _ensure_section_order(self, text: str) -> str:
        """
        Ensure sections appear in the expected order.
        Only reorders if all expected sections are present.
        """
        # Extract sections
        section_pattern = re.compile(r"^## (.+)$", re.MULTILINE)
        sections = {}
        current_heading = None
        current_content = []

        for line in text.split("\n"):
            match = section_pattern.match(line)
            if match:
                if current_heading is not None:
                    sections[current_heading] = "\n".join(current_content)
                current_heading = match.group(1).strip()
                current_content = [line]
            else:
                current_content.append(line)

        if current_heading is not None:
            sections[current_heading] = "\n".join(current_content)

        # Only reorder if we have most expected sections
        found = [s for s in self.EXPECTED_SECTIONS if s in sections]
        if len(found) < 3:
            return text  # Not enough sections to reorder

        # Preamble (content before first section)
        first_section_pos = text.find("## ")
        preamble = text[:first_section_pos].strip() if first_section_pos > 0 else ""

        # Rebuild in order
        ordered_parts = []
        if preamble:
            ordered_parts.append(preamble)

        for expected in self.EXPECTED_SECTIONS:
            if expected in sections:
                ordered_parts.append(sections[expected])

        # Append any sections not in expected list
        for heading, content in sections.items():
            if heading not in self.EXPECTED_SECTIONS:
                ordered_parts.append(content)

        return "\n\n".join(ordered_parts)
