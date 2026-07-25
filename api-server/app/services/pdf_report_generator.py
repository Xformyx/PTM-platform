"""
PTM Comparative Analysis PDF Report Generator.

Converts LLM-generated markdown report to Typst format and compiles to PDF.
Uses the comparative_report template for professional scientific layout.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates" / "comparative_report"


def markdown_to_typst(markdown_text: str) -> str:
    """Convert LLM-generated markdown to Typst markup.

    Handles:
    - Headings (## → =)
    - Bold (**text** → *text*)
    - Italic (*text* → _text_)  — careful not to conflict with bold
    - Tables (pipe tables → Typst tables)
    - Code blocks
    - Lists
    - Blockquotes
    """
    lines = markdown_text.split("\n")
    result = []
    in_table = False
    table_rows = []
    in_code_block = False
    code_lang = ""

    for line in lines:
        # Code blocks
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = line.strip()[3:].strip()
                result.append(f"```{code_lang}")
            else:
                in_code_block = False
                result.append("```")
            continue

        if in_code_block:
            result.append(line)
            continue

        # Tables
        if "|" in line and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # Skip separator rows (---|----|---)
            if all(re.match(r"^[-:]+$", c) for c in cells):
                continue
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(cells)
            continue
        elif in_table:
            # Flush table
            result.append(_convert_table(table_rows))
            in_table = False
            table_rows = []

        # Headings
        if line.startswith("## "):
            # Remove numbering like "## 1. Title" → "= Title"
            heading_text = re.sub(r"^##\s*\d+\.\s*", "", line)
            if heading_text == line:
                heading_text = line[3:]
            result.append(f"= {_convert_inline(heading_text.strip())}")
            result.append("")
            continue
        elif line.startswith("### "):
            heading_text = re.sub(r"^###\s*\d+\.\d+\.?\s*", "", line)
            if heading_text == line:
                heading_text = line[4:]
            result.append(f"== {_convert_inline(heading_text.strip())}")
            result.append("")
            continue
        elif line.startswith("#### "):
            heading_text = line[5:]
            result.append(f"=== {_convert_inline(heading_text.strip())}")
            result.append("")
            continue

        # Blockquotes
        if line.startswith("> "):
            result.append(f"#quote[{_convert_inline(line[2:])}]")
            continue

        # Unordered lists
        if re.match(r"^\s*[-*]\s", line):
            indent = len(line) - len(line.lstrip())
            text = re.sub(r"^\s*[-*]\s+", "", line)
            prefix = "  " * (indent // 2)
            result.append(f"{prefix}- {_convert_inline(text)}")
            continue

        # Ordered lists
        if re.match(r"^\s*\d+\.\s", line):
            indent = len(line) - len(line.lstrip())
            text = re.sub(r"^\s*\d+\.\s+", "", line)
            prefix = "  " * (indent // 2)
            result.append(f"{prefix}+ {_convert_inline(text)}")
            continue

        # Horizontal rule
        if re.match(r"^---+$", line.strip()):
            result.append("#line(length: 100%, stroke: 0.5pt + rgb(\"#e2e8f0\"))")
            continue

        # Regular paragraph
        result.append(_convert_inline(line))

    # Flush remaining table
    if in_table:
        result.append(_convert_table(table_rows))

    return "\n".join(result)


def _convert_inline(text: str) -> str:
    """Convert inline markdown formatting to Typst."""
    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Italic: *text* (single) → _text_ (but not inside bold)
    # Be careful: after bold conversion, single * is Typst bold
    # We handle _text_ style italic from markdown
    text = re.sub(r"(?<!\*)_(.+?)_(?!\*)", r"_\1_", text)
    # Inline code: `text` → `text` (same in Typst)
    # Links: [text](url) → #link("url")[text]
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'#link("\2")[\1]', text)
    # Subscript/superscript for scientific notation
    # Gene names with positions like S473, Y705 are fine as-is
    return text


def _convert_table(rows: list[list[str]]) -> str:
    """Convert markdown table rows to Typst table."""
    if not rows:
        return ""

    num_cols = max(len(r) for r in rows)
    header = rows[0] if rows else []
    data_rows = rows[1:] if len(rows) > 1 else []

    lines = []
    lines.append("#table(")
    lines.append(f"  columns: {num_cols},")
    lines.append("  align: (left,) * " + str(num_cols) + ",")
    lines.append("  stroke: 0.4pt + rgb(\"#e2e8f0\"),")
    lines.append("  inset: 5pt,")

    # Header row (bold) - use table.header(...) wrapping all header cells
    header_cells = ", ".join(f"[*{_convert_inline(cell.strip())}*]" for cell in header)
    # Pad header if fewer cells
    for _ in range(num_cols - len(header)):
        header_cells += ", []"
    lines.append(f"  table.header({header_cells}),")

    # Data rows
    for row in data_rows:
        for i, cell in enumerate(row):
            if i < num_cols:
                lines.append(f"  [{_convert_inline(cell.strip())}],")
        # Pad if row has fewer cells
        for _ in range(num_cols - len(row)):
            lines.append("  [],")

    lines.append(")")
    return "\n".join(lines)


def generate_report_pdf(
    markdown_content: str,
    experiment_a: str,
    experiment_b: str,
    species: str = "",
    ptm_type: str = "",
    output_path: Optional[Path] = None,
) -> Path:
    """Generate a PDF report from LLM markdown output.

    Args:
        markdown_content: The LLM-generated markdown report text
        experiment_a: Name/description of experiment A
        experiment_b: Name/description of experiment B
        species: Species name
        ptm_type: PTM type (e.g., phosphorylation)
        output_path: Optional output path for the PDF. If None, uses temp dir.

    Returns:
        Path to the generated PDF file.
    """
    # Convert markdown to Typst body content
    typst_body = markdown_to_typst(markdown_content)

    # Build the full Typst document
    template_path = TEMPLATE_DIR / "template.typ"

    # Escape strings for Typst
    def _escape(s: str) -> str:
        return s.replace('"', '\\"').replace("\\", "\\\\")

    typst_document = f"""#import "template.typ": ptm-report, key-finding, comparison-box, stat-highlight

#show: ptm-report.with(
  title: "PTM Comparative Analysis Report",
  experiment-a: "{_escape(experiment_a)}",
  experiment-b: "{_escape(experiment_b)}",
  species: "{_escape(species)}",
  ptm-type: "{_escape(ptm_type)}",
)

{typst_body}
"""

    # Write to temp file and compile
    if output_path is None:
        output_path = Path(tempfile.mkdtemp()) / "comparative_report.pdf"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the .typ source in the same directory as the template
    # so that relative imports work correctly
    typ_path = TEMPLATE_DIR / "_generated_report.typ"
    typ_path.write_text(typst_document, encoding="utf-8")

    # Compile with typst
    try:
        result = subprocess.run(
            ["typst", "compile", str(typ_path), str(output_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Typst compilation failed: {result.stderr}")
    finally:
        # Clean up generated .typ file
        typ_path.unlink(missing_ok=True)

    return output_path


def generate_report_pdf_from_saved(
    report_markdown: str,
    order_a_name: str,
    order_b_name: str,
    species: str,
    ptm_type: str,
    output_dir: Path,
    filename: str = "comparative_report.pdf",
) -> Path:
    """Generate PDF from a saved comparison report markdown.

    This is the main entry point called from the API endpoint.
    """
    output_path = output_dir / filename
    return generate_report_pdf(
        markdown_content=report_markdown,
        experiment_a=order_a_name,
        experiment_b=order_b_name,
        species=species,
        ptm_type=ptm_type,
        output_path=output_path,
    )
