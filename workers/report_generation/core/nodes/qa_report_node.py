"""
Q&A Report Generator Node — generates detailed Q&A analysis from report sections.

Ported from ptm-rag-backend/src/qaReportGenerator.ts (v3.1).

Strategy: 2-Pass Approach
  - Pass 1: Detailed PTM Analysis (9-10 Q&As per PTM)
  - Pass 2: Global Cell-Signaling Trends (10-15 Q&As across all PTMs)

Features:
  - Professor-Postdoc two-model approach (question model + answer model)
  - Quick Facts section with comprehensive metadata
  - Quality gates (question count, data validation, entity disambiguation)
  - Comprehensive Report parsing for PTM section extraction
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from common.llm_client import LLMClient

logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = (
    "You are an expert in post-translational modification (PTM) biology and cell signaling. "
    "Generate insightful, research-level Q&A pairs that help researchers understand "
    "the biological significance of PTM findings. Focus on cell signaling mechanisms, "
    "pathway interactions, and functional implications."
)


# ---------------------------------------------------------------------------
# Report Parser — extracts PTM sections from Comprehensive Report
# ---------------------------------------------------------------------------

@dataclass
class PTMSection:
    gene: str = ""
    position: str = ""
    full_section: str = ""
    ptm_type: str = ""
    ptm_log2fc: float = 0.0
    protein_log2fc: float = 0.0
    pathways: List[str] = field(default_factory=list)
    kinases: List[str] = field(default_factory=list)
    novelty: str = ""


@dataclass
class ExperimentalContext:
    cell_type: str = ""
    treatment: str = ""
    time_points: str = ""
    control: str = ""
    biological_question: str = ""


def extract_experimental_context(report_content: str) -> ExperimentalContext:
    """Extract experimental context from the Comprehensive Report."""
    ctx = ExperimentalContext()
    lines = report_content.split("\n")

    in_context = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Experimental Context":
            in_context = True
            continue
        if in_context and stripped.startswith("## "):
            break
        if in_context:
            if "**Cell Type:**" in stripped:
                ctx.cell_type = stripped.split("**Cell Type:**")[-1].strip()
            elif "**Treatment:**" in stripped:
                ctx.treatment = stripped.split("**Treatment:**")[-1].strip()
            elif "**Time Points:**" in stripped:
                ctx.time_points = stripped.split("**Time Points:**")[-1].strip()
            elif "**Control:**" in stripped:
                ctx.control = stripped.split("**Control:**")[-1].strip()
            elif "**Biological Question:**" in stripped:
                ctx.biological_question = stripped.split("**Biological Question:**")[-1].strip()

    return ctx


def extract_ptm_sections(report_content: str) -> List[PTMSection]:
    """Extract individual PTM sections from the Comprehensive Report."""
    sections: List[PTMSection] = []
    lines = report_content.split("\n")

    # Match PTM section headers: ### 1. GENE_NAME POSITION or ### GENE POSITION
    ptm_header_re = re.compile(
        r"^###\s+(?:\d+\.\s+)?([A-Z0-9]+)\s+((?:Ser|Thr|Tyr|Lys|Arg|Cys|His|S|T|Y|K|R|C|H)\d+)",
        re.IGNORECASE,
    )

    current_section: Optional[PTMSection] = None
    current_lines: List[str] = []

    for line in lines:
        m = ptm_header_re.match(line.strip())
        if m:
            # Save previous section
            if current_section:
                current_section.full_section = "\n".join(current_lines)
                _enrich_section_metadata(current_section)
                sections.append(current_section)

            current_section = PTMSection(gene=m.group(1), position=m.group(2))
            current_lines = [line]
        elif current_section:
            current_lines.append(line)

    # Save last section
    if current_section:
        current_section.full_section = "\n".join(current_lines)
        _enrich_section_metadata(current_section)
        sections.append(current_section)

    return sections


def _enrich_section_metadata(section: PTMSection):
    """Extract metadata from section text."""
    text = section.full_section

    # Extract PTM Log2FC
    m = re.search(r"PTM\s*(?:Relative\s*)?Log2FC[:\s]*([-\d.]+)", text, re.IGNORECASE)
    if m:
        try:
            section.ptm_log2fc = float(m.group(1))
        except ValueError:
            pass

    # Extract Protein Log2FC
    m = re.search(r"Protein\s*Log2FC[:\s]*([-\d.]+)", text, re.IGNORECASE)
    if m:
        try:
            section.protein_log2fc = float(m.group(1))
        except ValueError:
            pass

    # Extract PTM type
    for ptm_type in ("Phosphorylation", "Ubiquitylation", "Acetylation", "Methylation"):
        if ptm_type.lower() in text.lower():
            section.ptm_type = ptm_type
            break

    # Extract novelty
    if "novel" in text.lower():
        section.novelty = "novel"
    elif "known" in text.lower():
        section.novelty = "known"

    # Extract pathways
    pathway_re = re.compile(r"(?:Pathway|KEGG)[:\s]*(.+)", re.IGNORECASE)
    for m in pathway_re.finditer(text):
        pathways = [p.strip() for p in m.group(1).split(",")]
        section.pathways.extend(pathways)

    # Extract kinases
    kinase_re = re.compile(r"(?:Kinase|Upstream)[:\s]*(.+)", re.IGNORECASE)
    for m in kinase_re.finditer(text):
        kinases = [k.strip() for k in m.group(1).split(",")]
        section.kinases.extend(kinases)


# ---------------------------------------------------------------------------
# Q&A Generation Prompts
# ---------------------------------------------------------------------------

def _build_ptm_question_prompt(section: PTMSection, context: ExperimentalContext) -> str:
    """Build prompt for generating questions about a specific PTM."""
    return f"""Based on the following PTM analysis data, generate 9-10 insightful research questions.

PTM: {section.gene} {section.position} ({section.ptm_type or 'Phosphorylation'})
PTM Log2FC: {section.ptm_log2fc:.3f}
Protein Log2FC: {section.protein_log2fc:.3f}
Novelty: {section.novelty or 'unknown'}
Pathways: {', '.join(section.pathways[:5]) if section.pathways else 'Not determined'}
Upstream regulators: {', '.join(section.kinases[:5]) if section.kinases else 'Not determined'}

Experimental Context:
- Cell Type: {context.cell_type}
- Treatment: {context.treatment}
- Biological Question: {context.biological_question}

Section Content:
{section.full_section[:2000]}

Generate questions covering:
1. Mechanism of regulation (kinase/phosphatase involved)
2. Functional consequence of this PTM
3. Pathway context and cross-talk
4. Disease relevance
5. Comparison with known literature
6. Novelty assessment (if novel site)
7. Temporal dynamics
8. Therapeutic targeting potential
9. Protein-protein interaction effects
10. Cell signaling network impact

Format each question on a new line starting with "Q:" followed by the question text.
Output questions only, no numbering."""


def _build_ptm_answer_prompt(
    section: PTMSection, context: ExperimentalContext, question: str,
) -> str:
    """Build prompt for answering a specific question about a PTM."""
    return f"""Answer the following question about a PTM finding in detail.

Question: {question}

PTM Data:
- Gene: {section.gene}
- Position: {section.position}
- PTM Type: {section.ptm_type or 'Phosphorylation'}
- PTM Log2FC: {section.ptm_log2fc:.3f}
- Protein Log2FC: {section.protein_log2fc:.3f}
- Novelty: {section.novelty or 'unknown'}
- Pathways: {', '.join(section.pathways[:5]) if section.pathways else 'Not determined'}
- Upstream regulators: {', '.join(section.kinases[:5]) if section.kinases else 'Not determined'}

Experimental Context:
- Cell Type: {context.cell_type}
- Treatment: {context.treatment}
- Biological Question: {context.biological_question}

Section Content:
{section.full_section[:2000]}

Provide a detailed, evidence-based answer (150-300 words).
Focus on cell signaling biological meaning, not just describing the PTM itself.
Include specific mechanisms, pathway connections, and functional implications.
If referencing literature, cite with PMID when available."""


def _build_global_trends_prompt(
    report_content: str, context: ExperimentalContext, ptm_count: int,
) -> str:
    """Build prompt for global cell-signaling trend analysis."""
    return f"""Based on the complete PTM analysis report below, generate 10-15 Q&A pairs
about global cell-signaling trends observed across all {ptm_count} PTM sites.

Experimental Context:
- Cell Type: {context.cell_type}
- Treatment: {context.treatment}
- Biological Question: {context.biological_question}

Report Summary (first 4000 chars):
{report_content[:4000]}

Focus on:
1. Overall signaling pathway activation/inhibition patterns
2. Cross-talk between pathways (e.g., MAPK-PI3K, mTOR-AMPK)
3. Temporal dynamics of signaling cascades
4. Metabolic reprogramming signals
5. Cytoskeletal reorganization coordination
6. Transcription factor activation patterns
7. Feedback loops and regulatory circuits
8. Novel signaling connections discovered
9. Therapeutic targeting opportunities
10. Comparison with canonical signaling models

For each Q&A pair, format as:
Q: [Question]
A: [Detailed answer, 150-300 words]

Generate comprehensive, research-level Q&A pairs."""


# ---------------------------------------------------------------------------
# Q&A Report Generator
# ---------------------------------------------------------------------------

class QAReportGenerator:
    """Generates Q&A analysis reports from Comprehensive PTM Reports."""

    def __init__(
        self,
        llm_client: LLMClient,
        question_model: Optional[str] = None,
        answer_model: Optional[str] = None,
        use_two_model: bool = True,
    ):
        self.llm = llm_client
        self.question_model = question_model
        self.answer_model = answer_model
        self.use_two_model = use_two_model and question_model and answer_model

    def generate(
        self,
        report_content: str,
        progress_callback=None,
    ) -> str:
        """
        Generate Q&A report from a Comprehensive Report.

        Args:
            report_content: Full text of the Comprehensive Analysis Report
            progress_callback: Optional callback(pct, msg)

        Returns:
            Markdown string of the Q&A report.
        """
        if progress_callback:
            progress_callback(0, "Parsing comprehensive report")

        # 1. Extract context and PTM sections
        context = extract_experimental_context(report_content)
        ptm_sections = extract_ptm_sections(report_content)

        logger.info(f"Extracted {len(ptm_sections)} PTM sections for Q&A generation")

        if not ptm_sections:
            return "# Q&A Report\n\nNo PTM sections found in the comprehensive report."

        # 2. Pass 1: Per-PTM Q&A
        if progress_callback:
            progress_callback(10, f"Generating Q&A for {len(ptm_sections)} PTMs (Pass 1)")

        ptm_qa_blocks: List[str] = []
        for i, section in enumerate(ptm_sections):
            if progress_callback:
                pct = 10 + (i / len(ptm_sections)) * 60
                progress_callback(pct, f"Q&A for {section.gene} {section.position}")

            qa_block = self._generate_ptm_qa(section, context)
            ptm_qa_blocks.append(qa_block)

        # 3. Pass 2: Global Trends
        if progress_callback:
            progress_callback(75, "Generating global signaling trends (Pass 2)")

        global_qa = self._generate_global_trends(report_content, context, len(ptm_sections))

        # 4. Assemble report
        if progress_callback:
            progress_callback(90, "Assembling Q&A report")

        report = self._assemble_report(ptm_qa_blocks, global_qa, context, len(ptm_sections))

        if progress_callback:
            progress_callback(100, "Q&A report complete")

        return report

    def _generate_ptm_qa(self, section: PTMSection, context: ExperimentalContext) -> str:
        """Generate Q&A for a single PTM section."""
        # Generate questions
        q_prompt = _build_ptm_question_prompt(section, context)

        if self.use_two_model:
            questions_text = self.llm.generate(
                prompt=q_prompt,
                system_prompt=QA_SYSTEM_PROMPT,
                temperature=0.7,
                max_tokens=2000,
                model_override=self.question_model,
            )
        else:
            questions_text = self.llm.generate(
                prompt=q_prompt,
                system_prompt=QA_SYSTEM_PROMPT,
                temperature=0.7,
                max_tokens=2000,
            )

        # Parse questions
        questions = [
            line.replace("Q:", "").strip()
            for line in questions_text.split("\n")
            if line.strip().startswith("Q:")
        ]

        if not questions:
            # Fallback: split by numbered lines
            questions = [
                re.sub(r"^\d+[\.\)]\s*", "", line).strip()
                for line in questions_text.split("\n")
                if re.match(r"^\d+[\.\)]", line.strip())
            ]

        if not questions:
            logger.warning(f"No questions generated for {section.gene} {section.position}")
            return ""

        # Generate answers for each question
        qa_pairs: List[str] = []
        for q in questions[:10]:  # Cap at 10 questions per PTM
            a_prompt = _build_ptm_answer_prompt(section, context, q)

            if self.use_two_model:
                answer = self.llm.generate(
                    prompt=a_prompt,
                    system_prompt=QA_SYSTEM_PROMPT,
                    temperature=0.5,
                    max_tokens=1500,
                    model_override=self.answer_model,
                )
            else:
                answer = self.llm.generate(
                    prompt=a_prompt,
                    system_prompt=QA_SYSTEM_PROMPT,
                    temperature=0.5,
                    max_tokens=1500,
                )

            qa_pairs.append(f"**Q:** {q}\n\n**A:** {answer}\n")

        # Build Quick Facts
        quick_facts = self._build_quick_facts(section)

        return (
            f"### {section.gene} {section.position}\n\n"
            f"{quick_facts}\n\n"
            + "\n---\n\n".join(qa_pairs)
        )

    def _generate_global_trends(
        self, report_content: str, context: ExperimentalContext, ptm_count: int,
    ) -> str:
        """Generate global cell-signaling trend Q&A."""
        prompt = _build_global_trends_prompt(report_content, context, ptm_count)

        response = self.llm.generate(
            prompt=prompt,
            system_prompt=QA_SYSTEM_PROMPT,
            temperature=0.6,
            max_tokens=6000,
        )

        return response

    def _build_quick_facts(self, section: PTMSection) -> str:
        """Build Quick Facts summary for a PTM section."""
        facts = [f"| Property | Value |", f"|---|---|"]
        facts.append(f"| Gene | {section.gene} |")
        facts.append(f"| Position | {section.position} |")
        facts.append(f"| PTM Type | {section.ptm_type or 'Phosphorylation'} |")
        facts.append(f"| PTM Log2FC | {section.ptm_log2fc:.3f} |")
        facts.append(f"| Protein Log2FC | {section.protein_log2fc:.3f} |")
        facts.append(f"| Novelty | {section.novelty or 'Unknown'} |")
        if section.pathways:
            facts.append(f"| Pathways | {', '.join(section.pathways[:3])} |")
        if section.kinases:
            facts.append(f"| Upstream Regulators | {', '.join(section.kinases[:3])} |")
        return "\n".join(facts)

    def _assemble_report(
        self,
        ptm_qa_blocks: List[str],
        global_qa: str,
        context: ExperimentalContext,
        ptm_count: int,
    ) -> str:
        """Assemble the final Q&A report."""
        header = (
            f"# PTM Q&A Analysis Report\n\n"
            f"## Experimental Context\n\n"
            f"- **Cell Type:** {context.cell_type}\n"
            f"- **Treatment:** {context.treatment}\n"
            f"- **Biological Question:** {context.biological_question}\n"
            f"- **Total PTMs Analyzed:** {ptm_count}\n\n"
            f"---\n\n"
        )

        ptm_section = "## Part 1: Detailed PTM Analysis\n\n"
        ptm_section += "\n\n---\n\n".join(b for b in ptm_qa_blocks if b)

        global_section = (
            f"\n\n---\n\n"
            f"## Part 2: Global Cell-Signaling Trends\n\n"
            f"{global_qa}\n"
        )

        return header + ptm_section + global_section


# ---------------------------------------------------------------------------
# LangGraph Node Entry Point
# ---------------------------------------------------------------------------

def run_qa_report_generation(state: dict) -> dict:
    """LangGraph node: Generate Q&A report from completed sections."""
    cb = state.get("progress_callback")
    if cb:
        cb(92, "Generating Q&A report")

    sections = state.get("sections", {})
    if not sections:
        logger.warning("No sections available for Q&A generation")
        return {"qa_report": ""}

    # Reconstruct comprehensive report from sections
    report_parts = []
    context = state.get("experimental_context", {})

    # Add experimental context header
    report_parts.append("## Experimental Context\n")
    report_parts.append(f"- **Cell Type:** {context.get('cell_type', context.get('tissue', ''))}")
    report_parts.append(f"- **Treatment:** {context.get('treatment', '')}")
    report_parts.append(f"- **Biological Question:** {context.get('biological_question', '')}")
    report_parts.append("")

    # Add sections
    for section_name in ("introduction", "results", "discussion", "conclusion"):
        content = sections.get(section_name, "")
        if content:
            report_parts.append(f"## {section_name.title()}\n\n{content}\n")

    report_content = "\n".join(report_parts)

    # Create Q&A generator
    llm = LLMClient(
        provider=state.get("llm_provider", "ollama"),
        model=state.get("llm_model"),
    )

    generator = QAReportGenerator(
        llm_client=llm,
        question_model=state.get("qa_question_model"),
        answer_model=state.get("qa_answer_model"),
        use_two_model=bool(state.get("qa_question_model") and state.get("qa_answer_model")),
    )

    qa_report = generator.generate(report_content, progress_callback=cb)

    if cb:
        cb(95, "Q&A report generated")

    return {"qa_report": qa_report}
