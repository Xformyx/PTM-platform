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
        "Network Visualization",
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
        text = self._collapse_repeated_table_separators(text)
        text = self._renumber_research_questions(text)
        text = self._ensure_section_order(text)
        text = self._ensure_conventional_log2fc_reporting_policy(text)
        text = self._normalize_unpersisted_wave_tables(text)
        text = self._normalize_residual_claim_tone(text)
        text = self._enforce_final_artifact_boundaries(text)
        text = self._enforce_section_claim_ceiling(text)

        return text

    def _normalize_unpersisted_wave_tables(self, text: str) -> str:
        """Render fixed trajectory-cluster tables without per-cluster biological claims."""
        headers = {
            "| Temporal Cluster | Peak Time | Key Member(s) | Associated Biological Process |": (
                "| Temporal Cluster | Peak Time | Key Member(s) | Membership interpretation boundary |"
            ),
            "| Co-Wave | Peak Time | Temporal Pattern | Potential Functional Context (based on members) |": (
                "| Temporal Phosphosite Cluster | Peak Time | Trajectory Pattern | Concordance interpretation boundary |"
            ),
        }
        if not any(header in text for header in headers):
            return text
        lines = text.splitlines()
        normalized: list[str] = []
        in_wave_table = False
        for line in lines:
            if line in headers:
                normalized.append(headers[line])
                in_wave_table = True
                continue
            if in_wave_table and line.startswith("|") and line.count("|") >= 5 and not set(line.replace("|", "").strip()) <= {"-", ":"}:
                cells = line.split("|")
                cells[-2] = " not assigned (no persisted per-cluster enrichment) "
                normalized.append("|".join(cells))
                continue
            if in_wave_table and not line.startswith("|"):
                in_wave_table = False
            normalized.append(line)
        return "\n".join(normalized)

    def _ensure_conventional_log2fc_reporting_policy(self, text: str) -> str:
        """Guarantee the measured-contrast versus inference boundary in Methods.

        This deterministic reporting policy cannot be omitted by an LLM section
        writer. It neither changes a numerical threshold nor modifies the
        underlying quantification or candidate-scoring contract.
        """
        policy = (
            "Large conventional Log2FC values are retained as measured numeric contrasts, "
            "but are not used alone to infer biological priority, mechanistic importance, "
            "or direct regulatory strength."
        )
        if policy in text:
            return text
        match = re.search(r"(?m)^## Methods\s*$", text)
        if not match:
            # The LLM can omit a full Methods section. A minimal deterministic
            # Reporting Policy is still required in the final scientific output;
            # insert it before Discussion rather than silently losing the rule.
            discussion = re.search(r"(?m)^## Discussion\s*$", text)
            insertion = f"## Methods\n\n### Reporting Policy\n\n{policy}\n\n"
            if discussion:
                return text[:discussion.start()] + insertion + text[discussion.start():]
            return text.rstrip() + "\n\n" + insertion
        insertion = f"\n\n### Reporting Policy\n\n{policy}\n"
        return text[:match.end()] + insertion + text[match.end():]

    def _normalize_residual_claim_tone(self, text: str) -> str:
        """Lower recurrent unsupported claims without deleting observations.

        The writer receives an explicit evidence-tier policy, but final output is
        additionally normalized for phrases that have repeatedly converted a
        large observed contrast, local co-membership pattern, or candidate
        pathway context into a stronger mechanistic conclusion. Measured values
        and traceable literature citations remain unchanged.
        """
        sentence_splitter = re.compile(r"(?<=[.!?])(?=\s+|$)")
        numeric_contrast = re.compile(r"(?:log\s*(?:2|₂)\s*fc|ptm[^.\n]{0,80}[+-]?\d+\.\d+)", re.IGNORECASE)
        strength_substitutions = [
            (re.compile(r"\bmolecular switch (?:is|was) flipped\b", re.IGNORECASE), "pronounced measured contrast was observed"),
            (re.compile(r"\bpowerful,? rapid signal\b", re.IGNORECASE), "rapid measured contrast"),
            (re.compile(r"\bsubstantially increased\b", re.IGNORECASE), "higher measured abundance"),
            (re.compile(r"\b(?:potent|robust|massive|strong) (?:activation|activity|signal(?:ing)?|response)\b", re.IGNORECASE), "measured contrast"),
            (re.compile(r"\bPTM-driven hyperactivation\b", re.IGNORECASE), "PTM–protein decoupling pattern"),
            (re.compile(r"\bcoupled activation\b", re.IGNORECASE), "coupled measured-abundance pattern"),
        ]
        normalized_sentences = []
        for sentence in sentence_splitter.split(text):
            if numeric_contrast.search(sentence):
                for pattern, replacement in strength_substitutions:
                    sentence = pattern.sub(replacement, sentence)
            normalized_sentences.append(sentence)
        text = "".join(normalized_sentences)
        text = re.sub(
            r"\bsignificant rewiring\b",
            "observed within-cluster concordance-pattern change",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(?:extensive|substantial) rewiring of (?:the )?phosphoproteome\b",
            "observed within-cluster concordance-pattern changes",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bdirect evidence for (?:the )?dynamic assembly and disassembly of signaling modules\b",
            "observed within-cluster trajectory concordance patterns",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\btransient signaling hubs\b",
            "transient within-cluster concordance patterns",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bstable core signaling modules\b",
            "persistent trajectory-concordance patterns",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bkinase switching\b",
            "kinase-switching hypothesis",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bcausal propagation\b",
            "causal-propagation hypothesis",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bextensive evidence for activation of (?:the )?MAPK(?:/ERK)? and SRC(?: family)? kinase signaling\b",
            "observations consistent with MAPK/SRC-associated pathway context",
            text,
            flags=re.IGNORECASE,
        )
        # Supplementary network captions use legacy display labels. Convert
        # them to measured-contrast language without changing any numeric
        # observation or reclassifying the underlying PTM data.
        text = re.sub(
            r"\bTop Activated PTMs\b",
            "Top higher measured PTM-abundance contrasts",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bTop Inhibited PTMs\b",
            "Top lower measured PTM-abundance contrasts",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bTop activated:\s*",
            "Largest positive measured PTM contrasts:",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\bTop inhibited:\s*",
            "Largest negative measured PTM contrasts:",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(\d+) activated PTMs\b",
            r"\1 PTMs with higher measured abundance",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(\d+) inhibited PTMs\b",
            r"\1 PTMs with lower measured abundance",
            text,
            flags=re.IGNORECASE,
        )
        return text

    def _enforce_final_artifact_boundaries(self, text: str) -> str:
        """Apply output-only R1.0 boundaries that must not depend on LLM compliance.

        This deliberately preserves measured counts, conventional contrasts, compact
        P0–P5 diagnostics, and cited background. It removes only legacy report blocks
        that convert numeric salience or local membership into biological priority,
        per-Wave function, or a causal/kinase path.
        """
        lines: list[str] = []
        for line in text.splitlines():
            # Network panel lists are a legacy display-priority path. The raw measured
            # values remain in exported analysis artefacts and figure labels, but they
            # must not be repeated as a Report ranking block.
            if re.match(r"^\s*\*{0,2}Top (?:higher|lower) measured PTM-abundance contrasts\*{0,2}:", line, re.IGNORECASE):
                continue
            line = re.sub(
                r"\s*Largest (?:positive|negative) measured (?:PTM )?contrasts:\s*[^.\n]*(?:\.)?",
                "",
                line,
                flags=re.IGNORECASE,
            )
            lines.append(line)
        text = "\n".join(lines)

        substitutions = [
            (
                r"\bPTM-driven hyperactivation(?: pattern)?\b",
                "PTM–protein decoupling pattern",
            ),
            (
                r"\bThe pathway context diagram \((Figure \d+)\) places these candidate kinases downstream of inferred upstream receptors\.",
                r"The pathway context diagram (\1) places treatment, receptor and candidate-kinase annotations in a shared context without ordering or direct relations.",
            ),
            (
                r"\bThis high number of unique substrates provides strong, data-anchored evidence for a role for ([^.]+)\.",
                r"This unique-substrate composition provides data-anchored candidate footprint context for \1; it does not establish catalytic activity or direct substrate regulation.",
            ),
            (
                r"\bThese events, with their large fold-changes and involvement of key signaling nodes, likely represent critical steps in the propagation of [^.]+\.",
                "These are measured contrasts at named sites; their magnitude does not by itself establish biological priority, pathway placement, or propagation.",
            ),
            (
                r"\bThis delayed onset suggests that ([^.]+) is a (?:secondary|tertiary) event, likely downstream of initial kinase activation cascades\.",
                r"The later sampled contrast for \1 is an observational temporal pattern; upstream pathway placement is not assigned.",
            ),
            (
                r"\bThis transient profile is indicative of a signaling node that is rapidly modulated and then potentially subjected to negative feedback[^.]*\.",
                "This transient profile is a measured temporal pattern; feedback is not inferred from sampled-timepoint membership alone.",
            ),
            (
                r"\bThese dephosphorylation events are as critical to the signaling outcome as phosphorylation, reflecting the potential activation of specific phosphatases or the deactivation of constitutively active kinases[^.]*\.",
                "These lower measured PTM-abundance contrasts are retained as observations; they do not identify phosphatase activity or kinase deactivation.",
            ),
        ]
        for pattern, replacement in substitutions:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _enforce_section_claim_ceiling(self, text: str) -> str:
        """Bound residual LLM claim language in final Results/Q&A/Discussion output.

        This is intentionally section-aware: a cited Introduction can describe a
        canonical literature model, whereas the Order-derived Results, research
        answers, Discussion and Conclusion must retain an observation/candidate/
        hypothesis distinction. The transform preserves measured values and
        citations but replaces unsupported mechanism language with the narrowest
        evidence class that remains valid for a generic PTM Order.
        """
        guarded_sections = {"abstract", "results", "research question answers", "discussion", "conclusion"}
        pieces = re.split(r"(?m)(^#{1,3}\s+.+$)", text)
        active_section = ""

        direct_replacements = [
            (r"\bPTM-driven\s*(?:↑↑|↑|modulation|activation|inactivation|regulation)?\b", "measured PTM-abundance pattern"),
            (r"\b(?:bona fide|direct)\s+(?:signaling|regulatory|functional)\s+(?:regulation|input|response|event)\b", "measured PTM/protein pattern"),
            (r"\b(?:strong and persistent|potent|high-priority|key regulatory|critical)\s+(?:signaling\s+)?(?:input|effect|event|node|nodes|regulation|response)\b", "measured observation"),
            (r"\b(?:phased|temporal)\s+(?:signal(?:ing)?\s+)?propagation\b", "sampled-timepoint temporal pattern"),
            (r"\b(?:signaling|regulatory)\s+cascade(?:s)?\b", "pathway context"),
            (r"\b(?:functional|signaling)\s+modules?\b", "descriptive trajectory clusters"),
            (r"\bsignaling complexes\b", "protein groups"),
            (r"\b(?:co-?regulated|coordinated)\s+(?:groups|modules|patterns)\b", "within-cluster trajectory concordance patterns"),
            (r"\b(?:candidate|key)\s+(?:mediators?|players?|nodes?)\b", "candidate-context annotations"),
            (r"\b(?:directly\s+)?(?:modulates?|impinges upon)\b", "is associated with"),
            (r"\b(?:kinase|phosphatase)\s+activity\b", "substrate-derived candidate context"),
        ]

        def normalize_content(content: str) -> str:
            # Tables are deterministic report content and must not circumvent
            # the narrative ceiling through a legacy classification label.
            content = re.sub(r"\bExample Putative Substrates?\b", "Example motif-context sites (not direct substrates)", content, flags=re.IGNORECASE)
            content = re.sub(r"\bTransition to (?:later )?signaling phase\b", "Later sampled-timepoint measured-abundance pattern", content, flags=re.IGNORECASE)
            content = re.sub(r"\bSustained phosphorylation on key targets\b", "Sustained measured PTM-abundance pattern", content, flags=re.IGNORECASE)

            sentences = re.split(r"(?<=[.!?])(?=\s+|$)", content)
            normalized: list[str] = []

            def bounded_sentence(message: str, original: str) -> str:
                """Retain numeric citation markers when replacing unsafe prose."""
                citations = "".join(re.findall(r"\[\d+\]", original))
                return f"{message}{(' ' + citations) if citations else ''}"

            for sentence in sentences:
                lowered = sentence.lower()
                has_temporal_membership = any(term in lowered for term in ("co-wave", "co wave", "wave tw-", "co-membership", "within-cluster concordance", "trajectory concordance", "transition-supported", "loto", "lot o"))
                has_mechanistic_promotion = any(term in lowered for term in (
                    "common regulator", "kinase activation", "kinase activity", "causal", "cascade", "pathway function",
                    "functional role", "functional significance", "signaling complex", "assembled", "disassembled",
                    "propagation", "upstream", "downstream", "feedback", "reorganization of signaling",
                ))
                if has_temporal_membership and has_mechanistic_promotion and "does not" not in lowered and "not establish" not in lowered:
                    normalized.append(
                        bounded_sentence(
                            "These are observed within-cluster trajectory concordance and sampled-timepoint patterns; "
                            "they do not assign a common regulator, pathway function, complex state, causal order, or kinase switching.",
                            sentence,
                        )
                    )
                    continue

                has_numeric = bool(re.search(r"(?:log\s*(?:2|₂)\s*(?:fc)?|ptm_fc|prot_fc|measured contrast|\b\d+\.\d+)", lowered))
                has_priority_promotion = any(term in lowered for term in (
                    "priority", "critical", "core signaling", "key regulatory", "bona fide", "direct response",
                    "direct signaling", "strong and persistent", "potent effect", "proves", "confirms the engagement",
                ))
                if has_numeric and has_priority_promotion and "not " not in lowered:
                    normalized.append(
                        bounded_sentence(
                            "The reported values are measured PTM/protein contrasts; their magnitude and timing alone do not establish "
                            "biological priority, direct regulation, catalytic activity, pathway placement, or functional consequence.",
                            sentence,
                        )
                    )
                    continue

                has_uncited_mechanism = (
                    "[" not in sentence
                    and any(term in lowered for term in (
                        "feedback mechanism", "direct signaling input", "direct regulatory", "kinase activation",
                        "phosphatase activation", "pathway propagation", "signaling cascade", "causal pathway",
                        "functional consequence", "functional modulation",
                    ))
                    and any(term in lowered for term in ("suggest", "indicate", "reflect", "reveal", "confirm", "demonstrate"))
                    and "does not" not in lowered
                    and "not establish" not in lowered
                )
                if has_uncited_mechanism:
                    normalized.append(
                        bounded_sentence(
                            "The measured pattern is compatible with several mechanisms but does not establish direct regulation, "
                            "feedback, pathway order, kinase activity, or functional consequence.",
                            sentence,
                        )
                    )
                    continue
                for pattern, replacement in direct_replacements:
                    sentence = re.sub(pattern, replacement, sentence, flags=re.IGNORECASE)
                normalized.append(sentence)
            return "".join(normalized)

        for index, piece in enumerate(pieces):
            if index % 2:
                # Only a level-2 heading changes the parent report section.
                # Level-3 headings (e.g., Results subsections, figures, or
                # individual Q&A items) remain covered by their enclosing
                # Results/Discussion/Conclusion claim ceiling.
                if re.match(r"^##\s+", piece):
                    active_section = re.sub(r"^##\s+", "", piece).strip().lower()
                elif re.match(r"^#\s+", piece):
                    active_section = ""
                continue
            if active_section in guarded_sections:
                pieces[index] = normalize_content(piece)
        return "".join(pieces)

    @staticmethod
    def bibliography_blocked_reference_section() -> str:
        """Return the fixed review gate when no publication identity is traceable."""
        return (
            "## References\n\n"
            "**Citation completeness status: blocked for review.** No traceable collection-local or PubMed "
            "reference was resolved for this Report. External biological background, literature comparison, "
            "pathway-function interpretation, and cascade claims are withheld until publication-level metadata "
            "is supplied."
        )

    def _normalize_headings(self, text: str) -> str:
        """Normalize section headings.
        
        - Keep ## (h2) as main section headings
        - Keep ### (h3) as sub-section headings (e.g., ### Figure 1:)
        - Collapse #### and deeper to ### to avoid excessive nesting
        - Fix headings without space after #
        """
        # Only collapse ####+ to ### (keep ### as valid sub-sections)
        text = re.sub(r"^#{4,}\s+", "### ", text, flags=re.MULTILINE)
        # Fix headings without space after #
        text = re.sub(r"^(#{1,3})([A-Z])", r"\1 \2", text, flags=re.MULTILINE)
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
        # Stable-marker resolution can intentionally drop an untraceable
        # citation. Remove the resulting orphan whitespace before punctuation
        # without changing valid citation punctuation such as "work[1].".
        text = re.sub(r"(?<=\w)\s+([.,;:])", r"\1", text)
        # Placeholder-like citation text has no stable paper identity and must
        # never survive as if it were a source. Removing it before punctuation
        # cleanup prevents artifacts such as "prior work ." in final output.
        text = re.sub(r"\[(?:provided function|citation needed|reference needed)\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+([.,;:])", r"\1", text)
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

    def _collapse_repeated_table_separators(self, text: str) -> str:
        """Keep one Markdown separator row per table header."""
        separator = re.compile(r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$")
        result = []
        for line in text.split("\n"):
            if separator.match(line) and result and separator.match(result[-1]):
                continue
            result.append(line)
        return "\n".join(result)

    def _renumber_research_questions(self, text: str) -> str:
        """Renumber batch-local Q headings once after all answer batches are joined."""
        lines = text.split("\n")
        in_questions = False
        next_number = 1
        heading = re.compile(r"^(#{1,3}\s*)(?:Question\s*)?Q\s*\d+(\s*[:.\-].*)$", re.IGNORECASE)
        for index, line in enumerate(lines):
            if line.startswith("## "):
                in_questions = line.strip().lower() == "## research question answers"
                continue
            if not in_questions:
                continue
            match = heading.match(line)
            if match:
                lines[index] = f"{match.group(1)}Q{next_number}{match.group(2)}"
                next_number += 1
        return "\n".join(lines)

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
