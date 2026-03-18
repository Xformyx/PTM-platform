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
                f'<div class="zoomable-image" data-zoom="1">'
                f'<img src="{_escape_html(img_src)}" alt="{_escape_html(alt)}" '
                f'title="Click to zoom. Scroll to zoom in/out.">'
                f'<div class="zoom-controls"><button type="button" class="zoom-btn" data-action="in">+</button>'
                f'<button type="button" class="zoom-btn" data-action="out">−</button>'
                f'<button type="button" class="zoom-btn" data-action="reset">Reset</button></div></div>'
            )
            i += 1
            continue

        # Replace [N] with links (citation numbers)
        def _replace_citation(m):
            n = m.group(1)
            return f'<a href="#ref-{n}" class="ref-link" data-ref="{n}">[{n}]</a>'

        line = re.sub(r'\[(\d+)\]', _replace_citation, line)

        # Paragraph or list
        if stripped:
            if re.match(r'^(\s*)([-*+]|\d+\.)\s+', line):
                is_ul = bool(re.match(r'^(\s*)[-*+]\s+', line))
                tag = 'ul' if is_ul else 'ol'
                html_parts.append(f'<{tag}>')
                while i < len(lines) and re.match(r'^(\s*)([-*+]|\d+\.)\s+', lines[i]):
                    li = re.sub(r'^(\s*)([-*+]|\d+\.)\s+', '', lines[i])
                    html_parts.append(f'<li>{_convert_inline_md(_escape_html(li))}</li>')
                    i += 1
                html_parts.append(f'</{tag}>')
                continue
            else:
                html_parts.append(f'<p>{_convert_inline_md(_escape_html(stripped))}</p>')
        else:
            html_parts.append('')

        i += 1

    return '\n'.join(html_parts)


def _format_references_html(refs: List[Dict], refs_data: Dict[int, Dict]) -> str:
    """Format References section with ids and click handlers."""
    if not refs:
        return ""
    lines = ['<div class="references-section">']
    for r in refs:
        num = r["num"]
        pmid = r.get("pmid", "")
        data = refs_data.get(num, {})
        extra = f' data-pmid="{pmid}"' if pmid else ''
        extra += ' class="ref-entry clickable"' if pmid or data else ''
        raw = r.get("raw", "")
        lines.append(f'<p id="ref-{num}"{extra}>{_convert_inline_md(_escape_html(raw))}</p>')
    lines.append('</div>')
    return '\n'.join(lines)


def _html_template(
    body: str,
    toc: List[Dict],
    refs_data: Dict[int, Dict],
    title: str = "PTM Analysis Report",
) -> str:
    """Full HTML document with sidebar, modal, zoom script."""
    toc_html = '\n'.join(
        f'<a href="#{t["id"]}" class="toc-item toc-h{t["level"]}">{_escape_html(t["title"])}</a>'
        for t in toc
    )
    articles_json = json.dumps(refs_data, ensure_ascii=False)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape_html(title)}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: Georgia, serif; margin: 0; padding: 0; background: #fafafa; }}
.layout {{ display: flex; min-height: 100vh; }}
.sidebar {{ width: 240px; min-width: 240px; background: #1e293b; color: #e2e8f0; padding: 1rem; overflow-y: auto; position: sticky; top: 0; height: 100vh; }}
.sidebar h3 {{ font-size: 0.75rem; text-transform: uppercase; color: #94a3b8; margin: 0 0 0.75rem 0; }}
.toc-item {{ display: block; color: #cbd5e1; text-decoration: none; font-size: 0.8rem; padding: 0.25rem 0; border-bottom: 1px solid #334155; }}
.toc-item:hover {{ color: #fff; }}
.toc-h1 {{ font-weight: 600; }}
.toc-h2 {{ padding-left: 0.5rem; }}
.toc-h3 {{ padding-left: 1rem; font-size: 0.75rem; }}
.main {{ flex: 1; padding: 2rem 3rem; max-width: 900px; }}
.main h1 {{ font-size: 1.75rem; margin-top: 0; }}
.main h2 {{ font-size: 1.25rem; margin-top: 1.5rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.25rem; }}
.main h3 {{ font-size: 1.1rem; margin-top: 1rem; }}
.main p {{ line-height: 1.6; margin: 0.5rem 0; }}
.main ul, .main ol {{ margin: 0.5rem 0; padding-left: 1.5rem; }}
.ref-link {{ color: #2563eb; text-decoration: none; font-weight: 500; }}
.ref-link:hover {{ text-decoration: underline; }}
.ref-entry.clickable {{ cursor: pointer; padding: 0.5rem; border-radius: 4px; }}
.ref-entry.clickable:hover {{ background: #f1f5f9; }}
.zoomable-image {{ position: relative; margin: 1rem 0; overflow: hidden; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; }}
.zoomable-image img {{ display: block; max-width: 100%; cursor: zoom-in; transition: transform 0.2s; }}
.zoom-controls {{ position: absolute; bottom: 8px; right: 8px; display: flex; gap: 4px; }}
.zoom-btn {{ width: 28px; height: 28px; border: 1px solid #cbd5e1; background: #fff; border-radius: 4px; cursor: pointer; font-size: 1rem; line-height: 1; }}
.zoom-btn:hover {{ background: #f1f5f9; }}
#article-modal {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center; padding: 2rem; }}
#article-modal.show {{ display: flex; }}
#article-modal .modal-content {{ background: #fff; max-width: 600px; max-height: 85vh; overflow-y: auto; padding: 1.5rem; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); }}
#article-modal .modal-close {{ float: right; cursor: pointer; font-size: 1.5rem; }}
#article-modal h4 {{ margin-top: 0; }}
#article-modal .abstract {{ font-size: 0.9rem; color: #475569; margin-top: 0.5rem; }}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
<h3>Contents</h3>
<div class="toc">{toc_html}</div>
</aside>
<main class="main">
{body}
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
    if (data.abstract || data.abstract_excerpt) html += '<div class="abstract"><strong>Abstract:</strong><br>' + (data.abstract || data.abstract_excerpt || '') + '</div>';
    body.innerHTML = html;
  }}
  document.getElementById('article-modal').classList.add('show');
}}

document.querySelectorAll('.ref-link').forEach(el => {{
  el.addEventListener('click', e => {{
    e.preventDefault();
    const id = el.getAttribute('data-ref');
    document.getElementById('ref-' + id).scrollIntoView({{ behavior: 'smooth' }});
  }});
}});

document.querySelectorAll('.ref-entry.clickable').forEach(el => {{
  el.addEventListener('click', () => {{
    const pmid = el.getAttribute('data-pmid');
    const num = el.id.replace('ref-','');
    if (articlesData[num]) showArticle(num);
    else if (pmid) fetch('/api/articles/' + pmid).then(r=>r.json()).then(d=>{{
      articlesData[num] = d;
      showArticle(num);
    }}).catch(()=>showArticle(num));
  }});
}});

document.querySelectorAll('.zoomable-image').forEach(container => {{
  const img = container.querySelector('img');
  let scale = 1;
  const setScale = (s) => {{
    scale = Math.max(0.5, Math.min(3, s));
    img.style.transform = 'scale(' + scale + ')';
    img.style.transformOrigin = 'center center';
  }};
  img.addEventListener('click', () => setScale(scale + 0.25));
  container.querySelector('[data-action="in"]').addEventListener('click', e => {{ e.stopPropagation(); setScale(scale + 0.25); }});
  container.querySelector('[data-action="out"]').addEventListener('click', e => {{ e.stopPropagation(); setScale(scale - 0.25); }});
  container.querySelector('[data-action="reset"]').addEventListener('click', e => {{ e.stopPropagation(); setScale(1); }});
  container.addEventListener('wheel', e => {{ e.preventDefault(); setScale(scale - e.deltaY * 0.002); }}, {{ passive: false }});
}});

document.getElementById('article-modal').addEventListener('click', e => {{
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

        html_doc = _html_template(body_html, toc, refs_data, title)

        base_name = os.path.splitext(os.path.basename(md_file_path))[0]
        out_path = os.path.join(output_dir, f"{base_name}.html")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html_doc)

        _logger.info(f"HTML report saved: {out_path}")
        return out_path

    except Exception as e:
        _logger.warning(f"HTML conversion failed: {e}")
        return None
