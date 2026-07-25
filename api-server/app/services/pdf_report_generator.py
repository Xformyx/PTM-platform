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


# Known comparative-report section titles (ko/en) — used to split glued headings.
_SECTION_TITLE_PATTERNS = [
    r"Temporal Substrate Activity\s*비교",
    r"Temporal Signaling Cascade\s*비교",
    r"Co-Wave\s*기반\s*Upstream Regulator\s*비교",
    r"공통\s*Signaling Mechanism",
    r"물질\s*특이적\s*반응\s*및\s*작용기전",
    r"Kinase Activity\s*정량\s*비교",
    r"Signaling Divergence\s*분기점",
    r"종합\s*결론\s*및\s*치료적\s*함의",
    r"Temporal Substrate Activity Comparison",
    r"Temporal Signaling Cascade Comparison",
    r"Co-Wave[- ]Based Upstream Regulator Comparison",
    r"Shared Signaling Mechanisms?",
    r"Condition[- ]Specific Responses?(?:\s+and\s+Mechanisms?)?",
    r"Quantitative Kinase Activity Comparison",
    r"Signaling Divergence(?:\s+Branch\s*Points?)?",
    r"Conclusions?(?:\s+and\s+Therapeutic Implications?)?",
]
_SECTION_TITLE_RE = re.compile(
    r"(?:%s)" % "|".join(f"(?:{p})" for p in _SECTION_TITLE_PATTERNS),
    re.IGNORECASE,
)


def _paragraphize_body(body: str) -> str:
    """Insert paragraph breaks into a wall-of-text body."""
    body = body.strip()
    if not body:
        return ""
    # Already has structure — only lightly normalize
    if body.count("\n") >= 2:
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body

    # Korean sentence end → new paragraph
    body = re.sub(r"([다요임음석]\.|다\.)\s*(?=[가-힣A-Za-z(\[])", r"\1\n\n", body)
    # English sentence end (.!?) followed by capital / digit / (
    body = re.sub(r"([.!?])\s+(?=[\(\[]?[A-Z0-9])", r"\1\n\n", body)
    # Bullet-like fragments glued mid-text: "있다.- SPAG9" or "있다.• "
    body = re.sub(r"([^\n])\s*([•▪‣])\s*", r"\1\n\n- ", body)
    body = re.sub(r"([.다요임음])\s*-\s+(?=[A-Za-z가-힣])", r"\1\n\n- ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _normalize_markdown_spacing(markdown_text: str) -> str:
    """Repair LLM markdown that often arrives as a single line with glued headings.

    Observed model output::
        ## 1. Temporal Substrate Activity 비교시간대별로...있다.##2. Temporal...

    We split section headings, detach titles from bodies, and paragraphize.
    """
    text = (markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    # Normalize "##2." / "##  2." / "# # 2." → "## 2. "
    text = re.sub(r"#{1,4}\s*(\d+)\.\s*", r"## \1. ", text)

    # Force newline before every numbered ## heading (even mid-string).
    # Do NOT match bare "#{1,4} " — that would split "##" into "#\n\n#".
    text = re.sub(r"(?<!\n)(## \d+\. )", r"\n\n\1", text)

    parts = re.split(r"(?=## \d+\. )", text)
    out: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(## \d+\. )([\s\S]*)", part)
        if not m:
            out.append(_paragraphize_body(part))
            continue
        prefix, rest = m.group(1), m.group(2)
        title_match = _SECTION_TITLE_RE.match(rest)
        if title_match:
            title = title_match.group(0).strip()
            body = rest[title_match.end():].strip()
        else:
            # Fallback: take up to ~80 chars or until Hangul/Latin body cue
            soft = re.match(
                r"^(.{5,80}?)(?=(?:실험|시간|두 |본 |A |B |In |The |This |Based |Overall ))",
                rest,
            )
            if soft:
                title = soft.group(1).strip()
                body = rest[soft.end():].strip()
            else:
                # Last resort: first 40 chars as title
                title = rest[:40].strip()
                body = rest[40:].strip()
                # Prefer breaking at last space in title window
                sp = title.rfind(" ")
                if sp > 10:
                    body = (title[sp + 1:] + body).strip()
                    title = title[:sp].strip()
        out.append(f"{prefix}{title}\n\n{_paragraphize_body(body)}".rstrip())

    text = "\n\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _is_prose_line(line: str) -> bool:
    """True if line is ordinary paragraph text (not structural markdown)."""
    s = line.strip()
    if not s:
        return False
    if s.startswith("```"):
        return False
    if s.startswith("|"):
        return False
    if s.startswith("> "):
        return False
    if re.match(r"^#{1,4}\s", s):
        return False
    if re.match(r"^[-*]\s", s):
        return False
    if re.match(r"^\d+\.\s", s):
        return False
    if re.match(r"^---+$", s):
        return False
    return True


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
    - Paragraph breaks (blank lines / consecutive prose lines)
    """
    markdown_text = _normalize_markdown_spacing(markdown_text)
    lines = markdown_text.split("\n")
    result = []
    in_table = False
    table_rows = []
    in_code_block = False
    code_lang = ""
    prev_was_prose = False

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
            prev_was_prose = False
            continue

        if in_code_block:
            # Escape specials so raw report snippets can't break Typst markup
            result.append(_escape_typst_markup(line))
            prev_was_prose = False
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
            prev_was_prose = False
            continue
        elif in_table:
            # Flush table
            result.append(_convert_table(table_rows))
            result.append("")
            in_table = False
            table_rows = []

        # Headings — handle #, ##, ###, ####
        heading_match = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading_match:
            level = len(heading_match.group(1))  # 1-4
            heading_text = heading_match.group(2)
            # Remove numbering like "1. Title" or "1.1. Title"
            heading_text = re.sub(r"^\d+(\.\d+)*\.?\s*", "", heading_text)
            # Typst heading: = (level 1), == (level 2), === (level 3)
            # Map markdown # → =, ## → =, ### → ==, #### → ===
            # Since our template uses heading numbering, map:
            # # → = (section), ## → = (section), ### → == (subsection), #### → === (subsubsection)
            if level <= 2:
                typst_prefix = "="
            elif level == 3:
                typst_prefix = "=="
            else:
                typst_prefix = "==="
            if result and result[-1] != "":
                result.append("")
            result.append(f"{typst_prefix} {_convert_inline(heading_text.strip())}")
            result.append("")
            prev_was_prose = False
            continue

        # Blockquotes
        if line.startswith("> "):
            if result and result[-1] != "":
                result.append("")
            result.append(f"#quote[{_convert_inline(line[2:])}]")
            result.append("")
            prev_was_prose = False
            continue

        # Unordered lists
        if re.match(r"^\s*[-*]\s", line):
            indent = len(line) - len(line.lstrip())
            text = re.sub(r"^\s*[-*]\s+", "", line)
            prefix = "  " * (indent // 2)
            if prev_was_prose and result and result[-1] != "":
                result.append("")
            result.append(f"{prefix}- {_convert_inline(text)}")
            prev_was_prose = False
            continue

        # Ordered lists
        if re.match(r"^\s*\d+\.\s", line):
            indent = len(line) - len(line.lstrip())
            text = re.sub(r"^\s*\d+\.\s+", "", line)
            prefix = "  " * (indent // 2)
            if prev_was_prose and result and result[-1] != "":
                result.append("")
            result.append(f"{prefix}+ {_convert_inline(text)}")
            prev_was_prose = False
            continue

        # Horizontal rule
        if re.match(r"^---+$", line.strip()):
            result.append("")
            result.append("#line(length: 100%, stroke: 0.5pt + rgb(\"#e2e8f0\"))")
            result.append("")
            prev_was_prose = False
            continue

        # Blank line → paragraph break
        if not line.strip():
            if result and result[-1] != "":
                result.append("")
            prev_was_prose = False
            continue

        # Regular paragraph — force break between consecutive prose lines
        # so single-newline LLM output does not collapse into one wall of text
        converted = _convert_inline(line)
        if prev_was_prose and result and result[-1] != "":
            result.append("")
        result.append(converted)
        prev_was_prose = _is_prose_line(line)

    # Flush remaining table
    if in_table:
        result.append(_convert_table(table_rows))

    # Trim trailing blank lines but keep internal paragraph breaks
    while result and result[-1] == "":
        result.pop()
    return "\n".join(result) + "\n"


def _escape_typst_markup(text: str) -> str:
    """Escape characters that have special meaning in Typst markup mode.

    Notably, bare '<' starts a label (`<label>`) and causes 'unclosed label'
    when used in scientific text such as 'p < 0.05'.
    """
    return re.sub(r"([\\#<>@$_*\[\]])", r"\\\1", text)


def _convert_inline(text: str) -> str:
    """Convert inline markdown formatting to Typst, escaping special chars."""
    protected: list[str] = []

    def _protect(replacement: str) -> str:
        protected.append(replacement)
        return f"\x00{len(protected) - 1}\x00"

    # Inline code: `text` → raw escaped text in backticks
    def _code_repl(m: re.Match) -> str:
        return _protect(f"`{_escape_typst_markup(m.group(1))}`")

    text = re.sub(r"`([^`]+)`", _code_repl, text)

    # Links: [text](url) → #link("url")[text]
    def _link_repl(m: re.Match) -> str:
        label = _escape_typst_markup(m.group(1))
        url = m.group(2).replace("\\", "\\\\").replace('"', '\\"')
        return _protect(f'#link("{url}")[{label}]')

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_repl, text)

    # Bold: **text** → *text*
    def _bold_repl(m: re.Match) -> str:
        return _protect(f"*{_escape_typst_markup(m.group(1))}*")

    text = re.sub(r"\*\*(.+?)\*\*", _bold_repl, text)

    # Italic: _text_ → _text_ (Typst emphasis)
    def _italic_repl(m: re.Match) -> str:
        return _protect(f"_{_escape_typst_markup(m.group(1))}_")

    text = re.sub(r"(?<!\*)_(.+?)_(?!\*)", _italic_repl, text)

    # Escape remaining markup-mode specials (p < 0.05, #tags, gene_names, etc.)
    text = _escape_typst_markup(text)

    # Restore protected intentional Typst markup
    for i, replacement in enumerate(protected):
        text = text.replace(f"\x00{i}\x00", replacement)

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
    # Include system font paths to ensure CJK fonts are found
    font_paths = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        str(TEMPLATE_DIR),  # for any bundled fonts
    ]
    typst_cmd = ["typst", "compile"]
    for fp in font_paths:
        typst_cmd.extend(["--font-path", fp])
    typst_cmd.extend([str(typ_path), str(output_path)])

    try:
        result = subprocess.run(
            typst_cmd,
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
