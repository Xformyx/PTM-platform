"""
Markdown to HTML Converter for PTM Analysis Reports
Generates final_report.html with:
- Reference links: [N] -> jump to reference
- Reference click -> Article Cache modal
- Cytoscape image zoom
- Sidebar with document outline
"""

import re
import os
import base64
import json
import html
from pathlib import Path
from typing import List, Dict, Any, Optional

import logging
_logger = logging.getLogger("ptm-workers.markdown-to-html")


def _escape_html(text: str) -> str:
    return html.escape(text, quote=True)


def _convert_inline_md(text: str) -> str:
    """Convert inline markdown (bold, italic, code) to HTML."""
    # Bold **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Italic *text*
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # Inline code `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Links [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text


def _parse_references_section(md: str) -> tuple[str, List[Dict[str, Any]]]:
    """
    Extract References section and parse numbered references.
    Returns (md_without_refs, ref_list) where ref_list has {num, pmid, title, ...}.
    """
    refs = []
    ref_section_match = re.search(r'\n## References\n(.*?)(?=\n## |\n---|\Z)', md, re.DOTALL)
    if not ref_section_match:
        return md, refs

    ref_block = ref_section_match.group(1)
    # Split by "N. " pattern
    for m in re.finditer(r'^(\d+)\.\s+(.+?)(?=^\d+\.\s|\Z)', ref_block, re.MULTILINE | re.DOTALL):
        num = int(m.group(1))
        rest = m.group(2).strip()
        pmid_match = re.search(r'PMID:\s*(?:\[)?(\d+)(?:\]\([^)]+\))?', rest)
        pmid = pmid_match.group(1) if pmid_match else ""
        title_match = re.match(r'^(.+?)(?:\s+\*[^*]+\*|\s+\([^)]+\)\.)', rest)
        title = title_match.group(1).strip() if title_match else rest[:150]
        refs.append({"num": num, "pmid": pmid, "title": title, "raw": rest})
    return md, refs


def _build_toc(md: str) -> List[Dict[str, str]]:
    """Extract headings for table of contents."""
    toc = []
    for m in re.finditer(r'^(#{1,4})\s+(.+)$', md, re.MULTILINE):
        level = len(m.group(1))
        title = m.group(2).strip()
        slug = re.sub(r'[^\w\s-]', '', title.lower())
        slug = re.sub(r'[-\s]+', '-', slug).strip('-')[:50]
        toc.append({"level": level, "title": title, "id": slug or f"h-{len(toc)}"})
    return toc


def _build_collapsible_toc_html(toc: List[Dict]) -> str:
    """Build TOC HTML with collapsible h2 sections (Abstract, Introduction, Results, etc.). Skip h1 (title)."""
    if not toc:
        return ""
    # Filter out h1 (main title - user requested no title at top of sidebar)
    toc = [t for t in toc if t["level"] > 1]
    if not toc:
        return ""
    parts = []
    i = 0
    while i < len(toc):
        t = toc[i]
        if t["level"] == 2:  # Major section (## Abstract, ## Introduction, etc.)
            # Collect children (h3, h4) until next h2
            children = []
            j = i + 1
            while j < len(toc) and toc[j]["level"] > 2:
                children.append(toc[j])
                j += 1
            if children:
                child_html = "".join(
                    f'<a href="#{c["id"]}" class="toc-item toc-h{c["level"]}">{_escape_html(c["title"])}</a>'
                    for c in children
                )
                parts.append(
                    f'<details class="toc-section" open><summary class="toc-h2">{_escape_html(t["title"])}</summary>'
                    f'<div class="toc-children">{child_html}</div></details>'
                )
            else:
                parts.append(
                    f'<a href="#{t["id"]}" class="toc-item toc-h2">{_escape_html(t["title"])}</a>'
                )
            i = j
        else:
            # orphan h3/h4 - render as plain link
            parts.append(
                f'<a href="#{t["id"]}" class="toc-item toc-h{t["level"]}">{_escape_html(t["title"])}</a>'
            )
            i += 1
    return "\n".join(parts)


def _parse_markdown_table(lines: List[str], start_idx: int) -> tuple:
    """Parse markdown table starting at start_idx. Returns (rows, end_idx)."""
    rows = []
    i = start_idx
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith('|') or '|' not in line[1:]:
            break
        # Skip separator row (|---|---| or |:---|:---:|---:|)
        if re.match(r'^\|[\s\-:]+\|', line):
            i += 1
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if cells:
            rows.append(cells)
        i += 1
    return rows, i


def _format_table_html(rows: List[List[str]]) -> str:
    """Convert table rows to styled HTML table (like docx)."""
    if not rows:
        return ""

    def _cite(m):
        inner = m.group(1).strip()
        nums = [n.strip() for n in re.split(r'[,\s]+', inner) if n.strip() and n.strip().isdigit()]
        if not nums:
            return m.group(0)
        links = ', '.join(
            f'<a href="#ref-{n}" class="ref-link" data-ref="{n}">[{n}]</a>' for n in nums
        )
        return f'[{links}]'

    num_cols = max(len(r) for r in rows)
    parts = ['<div class="md-table-wrap"><table class="md-table">']
    for ri, row in enumerate(rows):
        tag = "th" if ri == 0 else "td"
        parts.append("<tr>")
        for ci in range(num_cols):
            cell = row[ci] if ci < len(row) else ""
            cell_escaped = _escape_html(cell)
            cell_with_refs = re.sub(r'\[([\d,\s]+)\]', _cite, cell_escaped)
            cell_html = _convert_inline_md(cell_with_refs)
            parts.append(f"<{tag}>{cell_html}</{tag}>")
        parts.append("</tr>")
    parts.append("</table></div>")
    return "\n".join(parts)


def _convert_md_to_html_body(
    md: str,
    output_dir: str,
    refs_by_num: Dict[int, Dict],
    parsed_refs: List[Dict],
    api_base_url: str = "",
) -> str:
    """Convert markdown content to HTML body with ref links and zoomable images."""
    lines = md.split('\n')
    html_parts = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Headings
        h_match = re.match(r'^(#{1,4})\s+(.+)$', line)
        if h_match:
            level = len(h_match.group(1))
            title = h_match.group(2).strip()
            slug = re.sub(r'[^\w\s-]', '', title.lower())
            slug = re.sub(r'[-\s]+', '-', slug).strip('-')[:50] or f"h-{i}"
            html_parts.append(f'<h{level} id="{slug}">{_escape_html(title)}</h{level}>')
            if "References" in title and parsed_refs:
                html_parts.append(_format_references_html(parsed_refs, refs_by_num))
                i += 1
                while i < len(lines) and not re.match(r'^#{1,4}\s+', lines[i]) and not re.match(r'^---+\s*$', lines[i]):
                    i += 1
                continue
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^---+\s*$', line) or re.match(r'^\*\*\*+\s*$', line):
            html_parts.append('<hr>')
            i += 1
            continue

        # Image: ![alt](src)
        img_match = re.match(r'^!\[([^\]]*)\]\((.+)\)\s*$', stripped)
        if img_match:
            alt, src = img_match.group(1), img_match.group(2)
            if src.startswith('data:'):
                img_src = src
            else:
                abs_path = Path(src) if Path(src).is_absolute() else Path(output_dir) / src
                if abs_path.exists():
                    with open(abs_path, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode('utf-8')
                    img_src = f"data:image/png;base64,{b64}"
                else:
                    img_src = src
            html_parts.append(
                f'<div class="zoomable-image">'
                f'<div class="zoomable-image-inner">'
                f'<img src="{_escape_html(img_src)}" alt="{_escape_html(alt)}" '
                f'title="Click to zoom. Scroll to zoom. Drag to pan.">'
                f'</div>'
                f'<div class="zoom-controls"><button type="button" class="zoom-btn" data-action="in">+</button>'
                f'<button type="button" class="zoom-btn" data-action="out">−</button>'
                f'<button type="button" class="zoom-btn" data-action="reset">Reset</button></div></div>'
            )
            i += 1
            continue

        # Markdown table: | col1 | col2 | col3 |
        if stripped.startswith('|') and '|' in stripped[1:]:
            table_rows, end_i = _parse_markdown_table(lines, i)
            if table_rows:
                html_parts.append(_format_table_html(table_rows))
                i = end_i
                continue

        # Replace [N] and [N, M, ...] with links (citation numbers)
        def _replace_citation(m):
            inner = m.group(1).strip()
            nums = [n.strip() for n in re.split(r'[,\s]+', inner) if n.strip() and n.strip().isdigit()]
            if not nums:
                return m.group(0)
            links = ', '.join(
                f'<a href="#ref-{n}" class="ref-link" data-ref="{n}">[{n}]</a>' for n in nums
            )
            return f'[{links}]'

        # Paragraph or list
        if stripped:
            if re.match(r'^(\s*)([-*+]|\d+\.)\s+', line):
                is_ul = bool(re.match(r'^(\s*)[-*+]\s+', line))
                tag = 'ul' if is_ul else 'ol'
                html_parts.append(f'<{tag}>')
                while i < len(lines) and re.match(r'^(\s*)([-*+]|\d+\.)\s+', lines[i]):
                    li = re.sub(r'^(\s*)([-*+]|\d+\.)\s+', '', lines[i])
                    li_escaped = _escape_html(li)
                    li_with_refs = re.sub(r'\[([\d,\s]+)\]', _replace_citation, li_escaped)
                    html_parts.append(f'<li>{_convert_inline_md(li_with_refs)}</li>')
                    i += 1
                html_parts.append(f'</{tag}>')
                continue
            else:
                para_escaped = _escape_html(stripped)
                para_with_refs = re.sub(r'\[([\d,\s]+)\]', _replace_citation, para_escaped)
                html_parts.append(f'<p>{_convert_inline_md(para_with_refs)}</p>')
        else:
            html_parts.append('')

        i += 1

    return '\n'.join(html_parts)


def _format_references_html(refs: List[Dict], refs_data: Dict[int, Dict]) -> str:
    """Format References section with ids, numbers, and click handlers."""
    if not refs:
        return ""
    lines = ['<div class="references-section">']
    for r in refs:
        num = r["num"]
        pmid = r.get("pmid", "")
        data = refs_data.get(num, {})
        extra = f' data-pmid="{pmid}"' if pmid else ''
        extra += ' class="ref-entry clickable"'
        raw = r.get("raw", "")
        lines.append(
            f'<p id="ref-{num}"{extra}>'
            f'<span class="ref-num">[{num}]</span> {_convert_inline_md(_escape_html(raw))}'
            f'</p>'
        )
    lines.append('</div>')
    return '\n'.join(lines)


def _html_template(
    body: str,
    toc: List[Dict],
    refs_data: Dict[int, Dict],
    title: str = "PTM Analysis Report",
    api_base_url: str = "/api",
) -> str:
    """Full HTML document with sidebar, modal, zoom script."""
    toc_html = _build_collapsible_toc_html(toc)
    articles_json = json.dumps(refs_data, ensure_ascii=False)
    api_base = api_base_url.rstrip("/") or "/api"

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape_html(title)}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: Georgia, serif; margin: 0; padding: 0; background: #fafafa; }}
.layout {{ display: flex; min-height: 100vh; width: 100%; }}
.sidebar {{ width: 240px; min-width: 120px; max-width: 480px; background: #1e293b; color: #e2e8f0; padding: 1rem; overflow-y: auto; position: sticky; top: 0; height: 100vh; flex-shrink: 0; }}
.sidebar-resize {{ width: 6px; cursor: col-resize; background: #334155; flex-shrink: 0; user-select: none; }}
.sidebar-resize:hover {{ background: #475569; }}
.toc-section {{ margin-bottom: 0.25rem; }}
.toc-section summary {{ cursor: pointer; font-weight: 600; font-size: 0.85rem; padding: 0.35rem 0; color: #e2e8f0; list-style: none; }}
.toc-section summary::-webkit-details-marker {{ display: none; }}
.toc-section summary::before {{ content: '\\25B6'; font-size: 0.6rem; margin-right: 0.35rem; display: inline-block; transition: transform 0.2s; }}
.toc-section[open] summary::before {{ transform: rotate(90deg); }}
.toc-children {{ padding-left: 0.75rem; margin-top: 0.5rem; }}
.toc-item {{ display: block; color: #cbd5e1; text-decoration: none; font-size: 0.8rem; padding: 0.25rem 0; border-bottom: 1px solid #334155; }}
.toc-item:hover {{ color: #fff; }}
.toc-h1 {{ font-weight: 600; }}
.toc-h2 {{ padding-left: 0.5rem; font-weight: 600; }}
.toc-h3 {{ padding-left: 1rem; font-size: 0.75rem; }}
.main {{ flex: 1; min-width: 0; padding: 2rem 3rem; max-width: none; }}
.main-inner {{ max-width: 900px; margin: 0 auto; }}
.main h1 {{ font-size: 1.75rem; margin-top: 0; }}
.main h2 {{ font-size: 1.25rem; margin-top: 1.5rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.25rem; }}
.main h3 {{ font-size: 1.1rem; margin-top: 1rem; }}
.main p {{ line-height: 1.6; margin: 0.5rem 0; }}
.main ul, .main ol {{ margin: 0.5rem 0; padding-left: 1.5rem; }}
.ref-link {{ color: #2563eb; text-decoration: none; font-weight: 500; cursor: pointer; }}
.ref-link:hover {{ text-decoration: underline; }}
.ref-num {{ font-weight: 600; margin-right: 0.35rem; color: #475569; }}
.ref-entry {{ padding: 0.5rem; border-radius: 4px; margin: 0.25rem 0; }}
.ref-entry.clickable {{ cursor: pointer; }}
.ref-entry.clickable:hover {{ background: #f1f5f9; }}
.zoomable-image {{ position: relative; margin: 1rem 0; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; cursor: grab; }}
.zoomable-image.dragging {{ cursor: grabbing; }}
.zoomable-image-inner {{ display: inline-block; transform-origin: 0 0; }}
.zoomable-image img {{ display: block; max-width: 100%; }}
.zoom-controls {{ position: absolute; bottom: 8px; right: 8px; display: flex; gap: 4px; }}
.zoom-btn {{ width: 28px; height: 28px; border: 1px solid #cbd5e1; background: #fff; border-radius: 4px; cursor: pointer; font-size: 1rem; line-height: 1; }}
.zoom-btn:hover {{ background: #f1f5f9; }}
.md-table-wrap {{ margin: 1rem 0; overflow-x: auto; }}
.md-table {{ width: 100%; border-collapse: collapse; border: 1px solid #e2e8f0; font-size: 0.9rem; background: #fff; }}
.md-table th, .md-table td {{ border: 1px solid #e2e8f0; padding: 0.5rem 0.75rem; text-align: left; }}
.md-table th {{ background: #f1f5f9; font-weight: 600; color: #1e293b; }}
.md-table tr:nth-child(even) {{ background: #f8fafc; }}
.md-table tr:hover {{ background: #f1f5f9; }}
#article-modal {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center; padding: 2rem; }}
#article-modal.show {{ display: flex; }}
#article-modal .modal-content {{ background: #fff; max-width: 640px; max-height: 85vh; overflow-y: auto; padding: 1.5rem; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); }}
#article-modal .modal-close {{ float: right; cursor: pointer; font-size: 1.5rem; }}
#article-modal h4 {{ margin-top: 0; }}
#article-modal .abstract {{ font-size: 0.9rem; color: #475569; margin-top: 0.5rem; line-height: 1.5; }}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar" id="sidebar">
<div class="toc">{toc_html}</div>
</aside>
<div class="sidebar-resize" id="sidebar-resize" title="Drag to resize"></div>
<main class="main">
<div class="main-inner">{body}</div>
</main>
</div>

<div id="article-modal">
<div class="modal-content">
<span class="modal-close" onclick="closeArticleModal()">&times;</span>
<div id="article-modal-body"></div>
</div>
</div>

<script>
const articlesData = {articles_json};
const API_BASE = "{_escape_html(api_base)}";

function closeArticleModal() {{
  document.getElementById('article-modal').classList.remove('show');
}}

function showArticle(num) {{
  const data = articlesData[num];
  const body = document.getElementById('article-modal-body');
  if (!data) {{
    body.innerHTML = '<p>Article data not available.</p>';
  }} else {{
    let html = '<h4>' + (data.title || 'Untitled') + '</h4>';
    if (data.authors) html += '<p><em>' + (Array.isArray(data.authors) ? data.authors.join(', ') : data.authors) + '</em></p>';
    if (data.journal) html += '<p>' + data.journal + (data.pub_date ? ' (' + data.pub_date + ')' : '') + '</p>';
    if (data.pmid) html += '<p><a href="https://pubmed.ncbi.nlm.nih.gov/' + data.pmid + '/" target="_blank">PMID: ' + data.pmid + '</a></p>';
    const summary = data.abstract || data.abstract_excerpt || data.summary || '';
    if (summary) html += '<div class="abstract"><strong>Summary:</strong><br>' + summary + '</div>';
    body.innerHTML = html;
  }}
  document.getElementById('article-modal').classList.add('show');
}}

document.querySelectorAll('.ref-link').forEach(function(link) {{
  link.addEventListener('click', function(e) {{
    e.preventDefault();
    const id = link.getAttribute('data-ref');
    const target = document.getElementById('ref-' + id);
    if (target) target.scrollIntoView({{ behavior: 'smooth' }});
  }});
}});

document.querySelectorAll('.ref-entry').forEach(function(entry) {{
  entry.addEventListener('click', function() {{
    const num = entry.id.replace('ref-','');
    const pmid = entry.getAttribute('data-pmid');
    if (articlesData[num]) {{ showArticle(num); return; }}
    if (pmid) {{
      fetch(API_BASE + '/articles/' + pmid).then(function(r){{ return r.json(); }}).then(function(d){{
        articlesData[num] = d;
        showArticle(num);
      }}).catch(function(){{ showArticle(num); }});
    }} else {{
      showArticle(num);
    }}
  }});
}});

document.querySelectorAll('.zoomable-image').forEach(function(container) {{
  const inner = container.querySelector('.zoomable-image-inner');
  const img = container.querySelector('img');
  let scale = 1, tx = 0, ty = 0;
  const apply = function() {{
    inner.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
  }};
  const setScale = function(s) {{
    scale = Math.max(0.5, Math.min(3, s));
    apply();
  }};
  const reset = function() {{ scale = 1; tx = 0; ty = 0; apply(); }};
  var dragStartX, dragStartY, dragStartTx, dragStartTy, didDrag;
  inner.addEventListener('mousedown', function(e) {{
    if (e.button !== 0) return;
    dragStartX = e.clientX; dragStartY = e.clientY;
    dragStartTx = tx; dragStartTy = ty;
    didDrag = false;
    container.classList.add('dragging');
    function onMove(e2) {{
      var dx = e2.clientX - dragStartX, dy = e2.clientY - dragStartY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) didDrag = true;
      tx = dragStartTx + dx;
      ty = dragStartTy + dy;
      apply();
    }}
    function onUp() {{
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      container.classList.remove('dragging');
      if (!didDrag) setScale(scale + 0.25);
    }}
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }});
  container.querySelector('[data-action="in"]').addEventListener('click', function(e) {{ e.stopPropagation(); setScale(scale + 0.25); }});
  container.querySelector('[data-action="out"]').addEventListener('click', function(e) {{ e.stopPropagation(); setScale(scale - 0.25); }});
  container.querySelector('[data-action="reset"]').addEventListener('click', function(e) {{ e.stopPropagation(); reset(); }});
  container.addEventListener('wheel', function(e) {{ e.preventDefault(); setScale(scale - e.deltaY * 0.002); }}, {{ passive: false }});
}});

var resizeStartX, resizeStartW;
document.getElementById('sidebar-resize').addEventListener('mousedown', function(e) {{
  resizeStartX = e.clientX;
  resizeStartW = document.getElementById('sidebar').offsetWidth;
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
  function onMove(e2) {{
    var dx = e2.clientX - resizeStartX;
    var w = Math.max(120, Math.min(480, resizeStartW + dx));
    document.getElementById('sidebar').style.width = w + 'px';
  }}
  function onUp() {{
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }}
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}});

document.getElementById('article-modal').addEventListener('click', function(e) {{
  if (e.target.id === 'article-modal') closeArticleModal();
}});
</script>
</body>
</html>'''


def convert_report_to_html(
    md_file_path: str,
    output_dir: str = None,
    references: List[Dict[str, Any]] = None,
    api_base_url: str = "",
) -> Optional[str]:
    """
    Convert markdown report to HTML with interactive features.

    Args:
        md_file_path: Path to final_report.md
        output_dir: Output directory (default: same as md file)
        references: List of ref dicts with pmid, title, abstract, etc. (for article modal)
        api_base_url: Base URL for API (e.g. /api) when fetching article by PMID

    Returns:
        Path to final_report.html or None
    """
    try:
        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        if output_dir is None:
            output_dir = os.path.dirname(md_file_path)
        output_dir = os.path.abspath(output_dir)

        # Parse references from markdown
        md_body, parsed_refs = _parse_references_section(md_content)
        toc = _build_toc(md_content)

        # Build refs_data from references param (indexed by 1-based num)
        refs_data = {}
        if references:
            for idx, ref in enumerate(references, 1):
                refs_data[idx] = {
                    "pmid": ref.get("pmid", ""),
                    "title": ref.get("title", ""),
                    "authors": ref.get("authors", []),
                    "journal": ref.get("journal", ""),
                    "pub_date": ref.get("pub_date", ""),
                    "abstract": ref.get("abstract", ""),
                    "abstract_excerpt": ref.get("abstract_excerpt", ""),
                }

        # Merge with parsed refs (for PMID when not in references)
        for r in parsed_refs:
            num = r["num"]
            if num not in refs_data:
                refs_data[num] = {"pmid": r.get("pmid", ""), "title": r.get("title", ""), "raw": r.get("raw", "")}

        body_html = _convert_md_to_html_body(md_body, output_dir, refs_data, parsed_refs, api_base_url)

        title = "PTM Analysis Report"
        h1 = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
        if h1:
            title = h1.group(1).strip()

        html_doc = _html_template(body_html, toc, refs_data, title, api_base_url=api_base_url or "/api")

        base_name = os.path.splitext(os.path.basename(md_file_path))[0]
        out_path = os.path.join(output_dir, f"{base_name}.html")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html_doc)

        _logger.info(f"HTML report saved: {out_path}")
        return out_path

    except Exception as e:
        _logger.warning(f"HTML conversion failed: {e}")
        return None
