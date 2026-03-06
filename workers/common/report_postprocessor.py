"""
Report Post-Processor v1.0

Shared post-processing module applied to ALL generated reports.
Handles:
  C1 - Force inline citations [n] into sections that lack them
  C2 - PTM type terminology correction (prevent cross-contamination)
  C3 - Fake/hypothetical reference detection and removal
  HTML entity decoding in reference lists
  Cell Signaling commonality analysis for Discussion enrichment
"""

import html
import logging
import re
from typing import Dict, List, Optional, Tuple


logger = logging.getLogger("ptm-workers.postprocessor")


def _pathway_to_str(p) -> str:
    """Convert pathway item to string (handles dicts from enriched data)."""
    if isinstance(p, str):
        return p
    if isinstance(p, dict):
        return p.get("name") or p.get("pathway") or str(p)
    return str(p)


def _sse_log(message: str, level: str = "INFO"):
    if level == "WARNING":
        logger.warning(message)
    else:
        logger.info(message)


# ============================================================================
# C1: Force inline citations [n] into sections that lack them
# ============================================================================

def force_inline_citations(
    section_text: str,
    section_name: str,
    available_refs: List[Dict],
    ptm_type: str = "phosphorylation"
) -> str:
    """
    If a section has fewer than the minimum required inline citations [n],
    insert citations at appropriate positions based on keyword matching.
    
    available_refs: list of dicts with keys like:
        {'number': 1, 'title': '...', 'keywords': [...], 'text': '...'}
    """
    if not available_refs or not section_text:
        return section_text
    
    # Count existing citations
    existing_citations = set(int(m) for m in re.findall(r'\[(\d+)\]', section_text))
    
    # Minimum citation requirements per section
    min_citations = {
        'Abstract': 2,
        'Introduction': 3,
        'Results': 3,
        'Discussion': 5,
        'Conclusion': 2,
    }
    
    required = min_citations.get(section_name, 2)
    
    if len(existing_citations) >= required:
        _sse_log(f"[PostProcess] {section_name} already has {len(existing_citations)} citations (>= {required})")
        return section_text
    
    _sse_log(f"[PostProcess] {section_name} has only {len(existing_citations)} citations, need {required}. Inserting...")
    
    # Build keyword-to-ref mapping from available references
    ref_keywords = {}
    for ref in available_refs:
        ref_num = ref.get('number', 0)
        if ref_num in existing_citations:
            continue  # Already cited
        
        # Extract keywords from title and text
        title = ref.get('title', '').lower()
        text = ref.get('text', '').lower()
        combined = title + ' ' + text
        
        # Extract meaningful keywords (protein names, pathway names, biological terms)
        keywords = set()
        
        # Protein/gene names (uppercase 2-6 letter words)
        for match in re.finditer(r'\b([A-Z][A-Za-z0-9]{1,8})\b', ref.get('title', '') + ' ' + ref.get('text', '')):
            word = match.group(1)
            if len(word) >= 2 and word not in {'The', 'This', 'That', 'With', 'From', 'Into', 'Upon', 'Through'}:
                keywords.add(word.lower())
        
        # Pathway names
        pathway_patterns = [
            r'(mapk|erk|jnk|p38|pi3k|akt|mtor|wnt|notch|hedgehog|nf-?kb|jak|stat|'
            r'ras|raf|mek|camp|pkg|pkc|pkb|tgf|bmp|vegf|egfr|fgfr|pdgfr|igf|'
            r'apoptosis|autophagy|ubiquitin|proteasome|endocytosis|glycolysis|'
            r'cell.?cycle|dna.?damage|immune|inflammatory|calcium|camp|cgmp)',
        ]
        for pattern in pathway_patterns:
            for m in re.finditer(pattern, combined, re.IGNORECASE):
                keywords.add(m.group(0).lower())
        
        # Biological terms
        bio_terms = [
            'phosphorylation', 'ubiquitylation', 'ubiquitination', 'acetylation',
            'kinase', 'phosphatase', 'ligase', 'proteasome', 'degradation',
            'signaling', 'pathway', 'substrate', 'activation', 'inhibition',
            'regulation', 'expression', 'interaction', 'network', 'cascade',
        ]
        for term in bio_terms:
            if term in combined:
                keywords.add(term)
        
        if keywords:
            ref_keywords[ref_num] = keywords
    
    # Split text into sentences
    sentences = re.split(r'(?<=[.!?])\s+', section_text)
    citations_added = 0
    max_to_add = required - len(existing_citations)
    used_refs = set(existing_citations)
    
    new_sentences = []
    for sentence in sentences:
        if citations_added >= max_to_add:
            new_sentences.append(sentence)
            continue
        
        # Skip sentences that already have citations
        if re.search(r'\[\d+\]', sentence):
            new_sentences.append(sentence)
            continue
        
        # Skip very short sentences or headings
        if len(sentence) < 40 or sentence.startswith('#') or sentence.startswith('**'):
            new_sentences.append(sentence)
            continue
        
        sentence_lower = sentence.lower()
        
        # Find best matching reference for this sentence
        best_ref = None
        best_score = 0
        
        for ref_num, keywords in ref_keywords.items():
            if ref_num in used_refs:
                continue
            score = sum(1 for kw in keywords if kw in sentence_lower)
            if score > best_score:
                best_score = score
                best_ref = ref_num
        
        # Insert citation if we found a good match (at least 2 keyword matches)
        if best_ref and best_score >= 2:
            # Insert before the period at the end of the sentence
            if sentence.rstrip().endswith('.'):
                sentence = sentence.rstrip()[:-1] + f' [{best_ref}].'
            elif sentence.rstrip().endswith(','):
                sentence = sentence.rstrip()[:-1] + f' [{best_ref}],'
            else:
                sentence = sentence.rstrip() + f' [{best_ref}]'
            
            used_refs.add(best_ref)
            citations_added += 1
            _sse_log(f"[PostProcess] Inserted [{best_ref}] into {section_name} (score={best_score})")
        
        new_sentences.append(sentence)
    
    result = ' '.join(new_sentences)
    
    # If still not enough citations, add to sentences with biological claims
    if citations_added < max_to_add:
        claim_patterns = [
            r'(?:has been shown|is known|plays a (?:key|critical|important) role|'
            r'is involved in|contributes to|regulates|mediates|modulates|'
            r'is associated with|is implicated in|is essential for|'
            r'previous studies|recent studies|it has been reported|'
            r'evidence suggests|studies have demonstrated)',
        ]
        
        for pattern in claim_patterns:
            if citations_added >= max_to_add:
                break
            for match in re.finditer(pattern, result, re.IGNORECASE):
                if citations_added >= max_to_add:
                    break
                # Check if there's already a citation nearby
                pos = match.end()
                nearby = result[max(0, pos-5):min(len(result), pos+20)]
                if re.search(r'\[\d+\]', nearby):
                    continue
                
                # Find an unused reference
                for ref_num in ref_keywords:
                    if ref_num not in used_refs:
                        # Insert after the matched phrase
                        insert_pos = match.end()
                        result = result[:insert_pos] + f' [{ref_num}]' + result[insert_pos:]
                        used_refs.add(ref_num)
                        citations_added += 1
                        _sse_log(f"[PostProcess] Inserted [{ref_num}] at claim pattern in {section_name}")
                        break
    
    total_citations = len(set(int(m) for m in re.findall(r'\[(\d+)\]', result)))
    _sse_log(f"[PostProcess] {section_name}: {len(existing_citations)} → {total_citations} citations")
    
    return result


# ============================================================================
# C2: PTM type terminology correction
# ============================================================================

# Mapping of PTM types to their incorrect cross-contamination terms
PTM_TERM_CORRECTIONS = {
    'ubiquitylation': {
        # Terms that should NOT appear in ubiquitylation reports
        'wrong_terms': {
            r'\bphosphorylation sites?\b': 'ubiquitylation sites',
            r'\bphosphorylation levels?\b': 'ubiquitylation levels',
            r'\bphosphorylation changes?\b': 'ubiquitylation changes',
            r'\bphosphorylation dynamics?\b': 'ubiquitylation dynamics',
            r'\bphosphorylation patterns?\b': 'ubiquitylation patterns',
            r'\bphosphorylation events?\b': 'ubiquitylation events',
            r'\bphosphorylation status\b': 'ubiquitylation status',
            r'\bphosphorylation state\b': 'ubiquitylation state',
            r'\bphosphorylation data\b': 'ubiquitylation data',
            r'\bphospho-?\b': 'ubiquityl-',
            r'\bkinase-substrate\b': 'E3 ligase-substrate',
            r'\bkinase enrichment\b': 'E3 ligase enrichment',
            r'\b(\d+)\s+phosphorylation\s+sites\b': r'\1 ubiquitylation sites',
        },
        # Context-aware exceptions: don't replace these
        # NOTE: Patterns must be specific to avoid false positives (e.g., "phosphorylation sites in this ubiquitylation study")
        'exceptions': [
            r'phosphorylation.{0,15}cross.?talk',  # cross-talk between PTMs
            r'cross.?talk.{0,15}(?:between|of).{0,15}phosphorylation',  # cross-talk context
            r'(?:between|of)\s+phosphorylation\s+and\s+ubiquitylation',  # explicit comparison
            r'(?:between|of)\s+ubiquitylation\s+and\s+phosphorylation',  # explicit comparison
            r'phosphorylation-dependent\s+ubiquitylation',  # mechanistic
            r'phospho-?degron',  # specific term
            r'phosphorylation.{0,10}priming',  # priming mechanism
        ],
    },
    'phosphorylation': {
        'wrong_terms': {
            r'\bubiquitylation sites?\b': 'phosphorylation sites',
            r'\bubiquitylation levels?\b': 'phosphorylation levels',
            r'\bubiquitylation changes?\b': 'phosphorylation changes',
            r'\bubiquitylation dynamics?\b': 'phosphorylation dynamics',
            r'\bubiquitylation patterns?\b': 'phosphorylation patterns',
            r'\bubiquitylation events?\b': 'phosphorylation events',
            r'\bubiquitylation status\b': 'phosphorylation status',
            r'\bubiquitylation state\b': 'phosphorylation state',
            r'\bubiquitylation data\b': 'phosphorylation data',
            r'\bE3 ligase-substrate\b': 'kinase-substrate',
            r'\bproteasomal degradation\b': 'dephosphorylation',
            r'\blysine ubiquitylation\b': 'serine/threonine phosphorylation',
        },
        'exceptions': [
            r'ubiquitylation.{0,15}cross.?talk',
            r'cross.?talk.{0,15}(?:between|of).{0,15}ubiquitylation',
            r'(?:between|of)\s+phosphorylation\s+and\s+ubiquitylation',  # explicit comparison
            r'(?:between|of)\s+ubiquitylation\s+and\s+phosphorylation',  # explicit comparison
            r'ubiquitin-?dependent\s+degradation',  # legitimate term
            r'proteasome',  # can appear in phosphorylation context
        ],
    },
}


def correct_ptm_terminology(text: str, ptm_type: str) -> str:
    """
    Correct PTM type terminology cross-contamination.
    
    For ubiquitylation reports: replace incorrect "phosphorylation" terms
    For phosphorylation reports: replace incorrect "ubiquitylation" terms
    
    Context-aware: preserves legitimate cross-talk mentions.
    """
    if not text or ptm_type not in PTM_TERM_CORRECTIONS:
        return text
    
    config = PTM_TERM_CORRECTIONS[ptm_type]
    corrections_made = 0
    
    # Split into paragraphs to check context
    paragraphs = text.split('\n')
    corrected_paragraphs = []
    
    for para in paragraphs:
        # Check if this paragraph contains exception patterns
        has_exception = False
        for exc_pattern in config['exceptions']:
            if re.search(exc_pattern, para, re.IGNORECASE):
                has_exception = True
                break
        
        if has_exception:
            corrected_paragraphs.append(para)
            continue
        
        # Apply corrections
        corrected = para
        for wrong_pattern, replacement in config['wrong_terms'].items():
            matches = list(re.finditer(wrong_pattern, corrected, re.IGNORECASE))
            if matches:
                corrected = re.sub(wrong_pattern, replacement, corrected, flags=re.IGNORECASE)
                corrections_made += len(matches)
        
        corrected_paragraphs.append(corrected)
    
    result = '\n'.join(corrected_paragraphs)
    
    if corrections_made > 0:
        _sse_log(f"[PostProcess] PTM terminology: corrected {corrections_made} cross-contamination terms ({ptm_type})")
    
    return result


# ============================================================================
# C3: Fake/hypothetical reference detection and removal
# ============================================================================

# Patterns that indicate fake/hypothetical references
FAKE_REF_PATTERNS = [
    # Explicit hypothetical language
    r"let'?s\s+assume",
    r"for\s+the\s+sake\s+of\s+example",
    r"hypothetical(?:ly)?",
    r"for\s+illustration\s+purposes?",
    r"as\s+an?\s+example",
    r"imagine\s+that",
    r"suppose\s+that",
    r"let\s+us\s+consider",
    # Generic fake author patterns
    r'\bSmith\s+et\s+al\.\s*\(\d{4}\)',
    r'\bJones\s+et\s+al\.\s*\(\d{4}\)',
    r'\bDoe\s+et\s+al\.\s*\(\d{4}\)',
    r'\bJohnson\s+et\s+al\.\s*\(\d{4}\)',
    r'\bBrown\s+et\s+al\.\s*\(\d{4}\)',
    r'\bWilliams\s+et\s+al\.\s*\(\d{4}\)',
    # Placeholder reference formats
    r'\[Author\s+et\s+al\.',
    r'\[First\s+Author',
    r'\[citation\s+needed\]',
    r'\[ref(?:erence)?\s+needed\]',
    r'\[insert\s+(?:citation|reference)',
]

# Compiled pattern for efficiency
_FAKE_REF_COMPILED = re.compile('|'.join(FAKE_REF_PATTERNS), re.IGNORECASE)

# Patterns for fake inline references like "[1] Smith et al. (2018)" embedded in text
_FAKE_INLINE_REF = re.compile(
    r'\[\d+\]\s*(?:Smith|Jones|Doe|Johnson|Brown|Williams|Author)\s+et\s+al\.\s*\(\d{4}\)[^.]*\.',
    re.IGNORECASE
)


def detect_and_remove_fake_references(text: str) -> str:
    """
    Detect and remove fake/hypothetical references from report text.
    
    Removes:
    - Sentences containing hypothetical language ("let's assume", "for the sake of example")
    - Generic fake author citations (Smith et al., Jones et al.)
    - Placeholder reference text
    """
    if not text:
        return text
    
    lines = text.split('\n')
    cleaned_lines = []
    removed_count = 0
    
    for line in lines:
        # Check for fake reference patterns
        if _FAKE_REF_COMPILED.search(line):
            _sse_log(f"[PostProcess] Removed fake reference line: {line[:100]}...", "WARNING")
            removed_count += 1
            continue
        
        # Remove fake inline references embedded in text
        cleaned_line = _FAKE_INLINE_REF.sub('', line)
        if cleaned_line != line:
            removed_count += 1
            _sse_log(f"[PostProcess] Cleaned fake inline reference from line", "WARNING")
        
        # Remove empty lines that result from removal (but keep intentional blank lines)
        if cleaned_line.strip() or not line.strip():
            cleaned_lines.append(cleaned_line)
    
    if removed_count > 0:
        _sse_log(f"[PostProcess] Removed {removed_count} fake/hypothetical references")
    
    return '\n'.join(cleaned_lines)


# ============================================================================
# HTML Entity Decoding
# ============================================================================

def decode_html_entities(text: str) -> str:
    """
    Decode HTML entities in text, especially in reference lists.
    
    Converts:
    - &amp; → &
    - &#xc1; → Á
    - &lt; → <
    - &gt; → >
    - &quot; → "
    - &#39; → '
    - Other numeric/named HTML entities
    """
    if not text:
        return text
    
    # Count entities before
    entity_count = len(re.findall(r'&(?:#x?[0-9a-fA-F]+|[a-zA-Z]+);', text))
    
    if entity_count == 0:
        return text
    
    # Use Python's html.unescape for comprehensive decoding
    decoded = html.unescape(text)
    
    # Additional cleanup for malformed entities
    # Sometimes entities appear without trailing semicolons
    decoded = re.sub(r'&amp(?!;)', '&', decoded)
    decoded = re.sub(r'&lt(?!;)', '<', decoded)
    decoded = re.sub(r'&gt(?!;)', '>', decoded)
    
    _sse_log(f"[PostProcess] Decoded {entity_count} HTML entities")
    
    return decoded


# ============================================================================
# Cell Signaling Commonality Analysis
# ============================================================================

def build_cell_signaling_analysis(
    results: Dict,
    ptm_type: str = "phosphorylation",
    md_context=None
) -> str:
    """
    Build a Cell Signaling commonality analysis section for Discussion enrichment.
    
    Analyzes:
    - Common signaling pathways shared by activated proteins
    - Hub proteins connecting multiple pathways
    - Temporal coordination of pathway activation
    - Cross-talk between signaling cascades
    
    Returns a formatted text block to be injected into the Discussion prompt.
    """
    
    networks = results.get('networks', {})
    timepoints = sorted(results.get('timepoints', []))
    
    if not networks:
        return ""
    
    # Collect all pathway annotations across timepoints
    pathway_proteins = {}  # pathway -> set of proteins
    protein_pathways = {}  # protein -> set of pathways
    temporal_pathways = {}  # timepoint -> set of active pathways
    
    for tp, net_data in networks.items():
        if not isinstance(net_data, dict):
            continue
        
        active_nodes = net_data.get('active_nodes', [])
        all_nodes = active_nodes + net_data.get('inhibited_nodes', []) + net_data.get('non_ptm_nodes', [])
        
        tp_pathways = set()
        
        for node in all_nodes:
            if not isinstance(node, dict):
                continue
            
            gene = node.get('gene', node.get('name', ''))
            if not gene:
                continue
            
            # Extract pathway info from node
            pathways = []
            pathway_field = node.get('pathway', node.get('pathways', ''))
            if isinstance(pathway_field, str) and pathway_field:
                pathways = [p.strip() for p in pathway_field.split(',') if p.strip()]
            elif isinstance(pathway_field, list):
                pathways = pathway_field
            
            # Also check KEGG pathway annotation
            kegg = node.get('kegg_pathway', '')
            if isinstance(kegg, str) and kegg:
                pathways.extend([p.strip() for p in kegg.split(',') if p.strip()])
            
            for pw in pathways:
                pw_str = _pathway_to_str(pw)
                if pw_str and pw_str.lower() not in ('n/a', 'unknown', 'none', ''):
                    pathway_proteins.setdefault(pw_str, set()).add(gene)
                    protein_pathways.setdefault(gene, set()).add(pw_str)
                    tp_pathways.add(pw_str)
        
        temporal_pathways[tp] = tp_pathways
    
    if not pathway_proteins:
        # Try to extract from MD context
        if md_context and hasattr(md_context, 'kegg_pathways') and md_context.kegg_pathways:
            for pw_info in md_context.kegg_pathways:
                pw_name = pw_info.get('pathway', '')
                ptms = pw_info.get('ptms', [])
                if pw_name and ptms:
                    for ptm in ptms:
                        gene = ptm.split('(')[0].strip() if '(' in ptm else ptm.strip()
                        pathway_proteins.setdefault(pw_name, set()).add(gene)
                        protein_pathways.setdefault(gene, set()).add(pw_name)
    
    if not pathway_proteins:
        return ""
    
    # Analyze commonalities
    analysis_parts = [
        "\n## CELL SIGNALING COMMONALITY ANALYSIS (for Discussion enrichment)\n",
        "The following analysis identifies shared signaling pathways and cross-talk patterns "
        "among the modified proteins. Use this to enrich the Discussion section.\n",
    ]
    
    # 1. Most shared pathways (pathways with most proteins)
    sorted_pathways = sorted(pathway_proteins.items(), key=lambda x: len(x[1]), reverse=True)
    
    analysis_parts.append("\n### Shared Signaling Pathways (ranked by protein count)")
    for pw, proteins in sorted_pathways[:10]:
        protein_list = ', '.join(sorted(proteins)[:8])
        if len(proteins) > 8:
            protein_list += f' (+{len(proteins)-8} more)'
        analysis_parts.append(f"- **{pw}**: {len(proteins)} proteins ({protein_list})")
    
    # 2. Hub proteins (proteins in multiple pathways)
    hub_proteins = {p: pws for p, pws in protein_pathways.items() if len(pws) >= 2}
    if hub_proteins:
        sorted_hubs = sorted(hub_proteins.items(), key=lambda x: len(x[1]), reverse=True)
        analysis_parts.append("\n### Hub Proteins (connecting multiple pathways)")
        for protein, pathways in sorted_hubs[:10]:
            pw_list = ', '.join(sorted(pathways))
            analysis_parts.append(f"- **{protein}**: connects {len(pathways)} pathways ({pw_list})")
    
    # 3. Pathway cross-talk (pathways sharing proteins)
    pathway_list = list(pathway_proteins.keys())
    cross_talk = []
    for i in range(len(pathway_list)):
        for j in range(i+1, len(pathway_list)):
            pw1, pw2 = pathway_list[i], pathway_list[j]
            shared = pathway_proteins[pw1] & pathway_proteins[pw2]
            if shared:
                cross_talk.append((pw1, pw2, shared))
    
    if cross_talk:
        cross_talk.sort(key=lambda x: len(x[2]), reverse=True)
        analysis_parts.append("\n### Pathway Cross-Talk (shared proteins between pathways)")
        for pw1, pw2, shared in cross_talk[:8]:
            shared_list = ', '.join(sorted(shared)[:5])
            analysis_parts.append(f"- **{pw1}** ↔ **{pw2}**: {len(shared)} shared proteins ({shared_list})")
    
    # 4. Temporal pathway activation pattern
    if temporal_pathways and len(temporal_pathways) > 1:
        analysis_parts.append("\n### Temporal Pathway Activation")
        
        # Find pathways active across all timepoints
        all_tp_pathways = list(temporal_pathways.values())
        if all_tp_pathways:
            persistent = set.intersection(*all_tp_pathways) if len(all_tp_pathways) > 1 else all_tp_pathways[0]
            if persistent:
                analysis_parts.append(f"- **Persistently active** (all timepoints): {', '.join(sorted(persistent)[:8])}")
            
            # Early-only pathways
            if len(all_tp_pathways) >= 2:
                early_only = all_tp_pathways[0] - set.union(*all_tp_pathways[1:])
                if early_only:
                    analysis_parts.append(f"- **Early-only activation**: {', '.join(sorted(early_only)[:5])}")
                
                late_only = all_tp_pathways[-1] - set.union(*all_tp_pathways[:-1])
                if late_only:
                    analysis_parts.append(f"- **Late-only activation**: {', '.join(sorted(late_only)[:5])}")
    
    analysis_parts.append("\n### Discussion Integration Instructions")
    analysis_parts.append(
        "When writing the Discussion, you MUST:\n"
        "1. Discuss the most shared pathways and their biological significance\n"
        "2. Highlight hub proteins as potential therapeutic targets or key regulators\n"
        "3. Explain pathway cross-talk and its implications for the cellular response\n"
        "4. Describe the temporal dynamics of pathway activation/deactivation\n"
        "5. Connect these findings to the research questions\n"
    )
    
    return '\n'.join(analysis_parts)


# ============================================================================
# Master Post-Processing Function
# ============================================================================

def postprocess_report(
    report_sections: Dict[str, str],
    ptm_type: str = "phosphorylation",
    available_refs: Optional[List[Dict]] = None,
    results: Optional[Dict] = None,
    md_context=None,
) -> Dict[str, str]:
    """
    Apply ALL post-processing steps to generated report sections.
    
    Steps (in order):
    1. HTML entity decoding
    2. Fake reference detection and removal (C3)
    3. PTM terminology correction (C2)
    4. Force inline citations (C1)
    
    Args:
        report_sections: dict of section_name -> section_text
        ptm_type: 'phosphorylation' or 'ubiquitylation'
        available_refs: list of reference dicts for citation insertion
        results: analysis results dict (for cell signaling analysis)
        md_context: MDContextExtractor instance
    
    Returns:
        dict of section_name -> corrected section_text
    """
    _sse_log(f"[PostProcess] Starting post-processing for {ptm_type} report ({len(report_sections)} sections)")
    
    processed = {}
    
    for section_name, section_text in report_sections.items():
        if not section_text:
            processed[section_name] = section_text
            continue
        
        text = section_text
        
        # Step 1: HTML entity decoding
        text = decode_html_entities(text)
        
        # Step 2: Fake reference removal (C3)
        text = detect_and_remove_fake_references(text)
        
        # Step 3: PTM terminology correction (C2)
        text = correct_ptm_terminology(text, ptm_type)
        
        # Step 4: Force inline citations (C1)
        if available_refs:
            text = force_inline_citations(text, section_name, available_refs, ptm_type)
        
        processed[section_name] = text
    
    _sse_log(f"[PostProcess] Post-processing complete for {len(processed)} sections")
    
    return processed


def postprocess_full_report(
    full_report_text: str,
    ptm_type: str = "phosphorylation",
    crosstalk_metadata: Optional[Dict] = None,
) -> str:
    """
    Apply post-processing to a full report text (not split into sections).
    
    Applies:
    1. HTML entity decoding
    2. Fake reference removal
    3. PTM terminology correction
    4. v85: Duplicate section heading removal
    5. v85: Abstract numerical integrity enforcement (if crosstalk_metadata provided)
    6. v91: UPPERCASE emphasis to bold markdown conversion
    
    Note: Citation insertion requires section-level processing.
    """
    if not full_report_text:
        return full_report_text
    
    _sse_log(f"[PostProcess] Processing full report text ({len(full_report_text)} chars)")
    
    text = full_report_text
    text = decode_html_entities(text)
    text = detect_and_remove_fake_references(text)
    text = correct_ptm_terminology(text, ptm_type)
    
    # v85: Remove duplicate section headings (e.g., ## Introduction followed by **Introduction**)
    text = _remove_duplicate_section_headings(text)
    
    # v85: Enforce Abstract numerical integrity
    if crosstalk_metadata:
        text = _enforce_abstract_numbers(text, crosstalk_metadata)
    
    # v91: Convert UPPERCASE emphasis terms to **bold** markdown
    text = convert_uppercase_emphasis_to_bold(text)
    
    return text


# ============================================================================
# v91: Convert UPPERCASE Emphasis to Bold Markdown
# ============================================================================

# Known signaling/biology terms that LLM outputs in ALL CAPS as emphasis.
# These should be **bold** in the final document, not UPPERCASE.
_UPPERCASE_EMPHASIS_TERMS = [
    # Signal transduction concepts
    "SIGNAL INTEGRATOR NODES", "SIGNAL INTEGRATOR", "SIGNAL INTEGRATORS",
    "SIGNAL AMPLIFICATION", "SIGNAL ATTENUATION", "SIGNAL SWITCHING",
    "SIGNAL INTEGRATION LAYER", "SIGNAL INTEGRATION NETWORK",
    "SIGNAL INTEGRATION NODE", "SIGNAL INTEGRATION NODES",
    "SIGNAL INTEGRATION", "SIGNAL CONVERGENCE HUBS",
    "SIGNAL CONVERGENCE", "SIGNAL PROCESSING NETWORK",
    "SIGNAL PROCESSING LAYER", "SIGNAL PROPAGATION DYNAMICS",
    "SIGNAL PROPAGATION PATHWAY", "SIGNAL PROPAGATION TIMELINE",
    "SIGNAL PROPAGATION ANALYSIS", "SIGNAL PROPAGATION",
    "SIGNAL TRANSDUCTION MODEL", "SIGNAL TRANSDUCTION NETWORK",
    "SIGNAL TRANSDUCTION", "SIGNAL RELAY",
    "SIGNAL PROTECTION", "SIGNALING DIRECTIONALITY",
    "SIGNALING MODE", "SIGNALING CASCADES", "SIGNALING CASCADE",
    "SIGNALING CHANNELS", "SIGNALING CHANNEL",
    "SIGNALING COMPLEX ASSEMBLY", "SIGNALING HIERARCHY",
    "SIGNALING HUBS", "SIGNALING HUB", "SIGNALING SCAFFOLDS",
    "SIGNALING PATTERNS", "SIGNALING PATTERN",
    # Effector/downstream concepts
    "DOWNSTREAM EFFECTOR PROTEINS", "DOWNSTREAM EFFECTORS",
    "DOWNSTREAM EFFECTOR", "EFFECTOR PROTEINS", "EFFECTOR RESPONSE",
    "EFFECTOR PROTEIN",
    "IMMEDIATE EARLY EFFECTORS", "IMMEDIATE EARLY EFFECTOR",
    "DELAYED EFFECTOR RESPONSES", "DELAYED EFFECTORS", "DELAYED EFFECTOR",
    "SUSTAINED EFFECTOR ACTIVATION", "SUSTAINED EFFECTORS",
    "BIPHASIC EFFECTOR DYNAMICS", "BIPHASIC EFFECTORS",
    # Temporal/regulatory concepts
    "TEMPORAL SIGNALING HIERARCHY", "TEMPORAL HIERARCHY",
    "TEMPORAL GATE", "TEMPORAL CAUSALITY ANALYSIS",
    "TEMPORAL SIGNALING",
    # Feedback/circuit concepts
    "POSITIVE FEEDBACK LOOPS", "POSITIVE FEEDBACK LOOP",
    "POSITIVE FEEDBACK", "NEGATIVE FEEDBACK CIRCUITS",
    "NEGATIVE FEEDBACK CIRCUIT", "NEGATIVE FEEDBACK",
    "FEEDFORWARD CIRCUITS", "FEEDFORWARD CIRCUIT",
    "FEEDFORWARD", "FEEDBACK REGULATION",
    "FEEDBACK LOOP", "FEEDBACK LOOPS",
    "SIGNAL AMPLIFICATION CIRCUITS", "SIGNAL AMPLIFICATION CIRCUIT",
    "SIGNAL AMPLIFIER NODES", "SIGNAL AMPLIFIER NODE",
    "SIGNAL ATTENUATION MECHANISMS", "SIGNAL SWITCHING CIRCUITS",
    "SIGNAL SWITCHING NODES", "SIGNAL SWITCHING NODE",
    # Causality/propagation concepts
    "POST-TRANSLATIONAL SIGNAL RELAY", "CAUSAL SIGNAL PROPAGATION",
    "FORWARD SIGNAL PROPAGATION", "CONVERGENT SIGNAL INTEGRATION",
    "RAPID SIGNAL-DEPENDENT PROTEIN TURNOVER",
    "TRANSCRIPTIONAL REPROGRAMMING",
    # Phosphodegron/degradation concepts
    "PHOSPHODEGRON-MEDIATED SIGNAL TERMINATION",
    "PHOSPHODEGRON-MEDIATED DEGRADATION",
    "PROTECTIVE SIGNALING", "COORDINATED SIGNAL AMPLIFICATION",
    "COMPENSATORY SIGNALING MECHANISMS",
    # Kinase/cascade concepts
    "KINASE-FIRST SIGNALING CASCADE", "KINASE RELAY",
    "ALTERNATIVE SIGNALING HIERARCHY",
    # Integration concepts
    "SIGNAL INPUT", "EARLY PTM EVENTS", "PTM CROSS-TALK",
    "CELLULAR OUTCOME", "CELLULAR RESPONSE",
    # Therapeutic
    "THERAPEUTIC TARGETS", "THERAPEUTIC TARGET",
    # General biology
    "DIRECT SIGNAL RELAY",
    "PERSISTENT SIGNALING", "SUSTAINED SIGNALING",
]

# Sort by length descending so longer phrases match first
_UPPERCASE_EMPHASIS_TERMS.sort(key=len, reverse=True)


def convert_uppercase_emphasis_to_bold(text: str) -> str:
    """
    v91: Convert UPPERCASE emphasis terms in LLM output to **bold** markdown.
    
    LLM prompts instruct the model to use specific terms in ALL CAPS for emphasis
    (e.g., SIGNAL INTEGRATOR NODES, SIGNAL AMPLIFICATION). In DOCX output, these
    appear as ugly uppercase text instead of bold formatting.
    
    This function converts known uppercase emphasis terms to **Title Case Bold**
    markdown, which the DOCX converter then renders as proper bold text.
    
    Also handles generic patterns: 3+ word sequences in ALL CAPS that are likely
    emphasis terms (not acronyms or section headers).
    """
    if not text:
        return text
    
    converted = 0
    
    # Phase 1: Convert known terms from the dictionary
    for term in _UPPERCASE_EMPHASIS_TERMS:
        if term in text:
            # Convert to title case bold, preserving hyphens
            title_case = term.title()
            # Fix common title-case issues with hyphens and short words
            title_case = title_case.replace("Ptm", "PTM").replace("Scf", "SCF")
            title_case = title_case.replace("E3 ", "E3 ").replace("E2 ", "E2 ")
            title_case = title_case.replace("-Mediated", "-mediated")
            title_case = title_case.replace("-Dependent", "-dependent")
            title_case = title_case.replace("-Regulated", "-regulated")
            title_case = title_case.replace("-Linked", "-linked")
            bold_text = f"**{title_case}**"
            
            # Don't convert if already inside bold markers
            pattern = re.compile(r'(?<![\*])' + re.escape(term) + r'(?![\*])')
            new_text = pattern.sub(bold_text, text)
            if new_text != text:
                count = text.count(term) - new_text.count(term)
                converted += max(count, 1)
                text = new_text
    
    # Phase 2: Generic pattern - catch remaining ALL CAPS phrases (3+ words)
    def _replace_caps_phrase(match):
        phrase = match.group(0)
        words = phrase.split()
        if len(words) < 3:
            return phrase
        if all(len(w) <= 4 for w in words):
            return phrase
        return f"**{phrase.title()}**"
    
    generic_pattern = re.compile(
        r'(?<![#\*])\b([A-Z][A-Z\-]+(?:\s+[A-Z][A-Z\-]+){2,})\b(?![\*])',
    )
    new_text = generic_pattern.sub(_replace_caps_phrase, text)
    if new_text != text:
        converted += 1
        text = new_text
    
    # Phase 3: Fix double-bold artifacts (****text**** -> **text**)
    text = re.sub(r'\*{4,}([^*]+?)\*{4,}', r'**\1**', text)
    
    if converted > 0:
        _sse_log(f"[PostProcess] v91: Converted {converted} UPPERCASE emphasis terms to **bold** markdown")
    
    return text


# ============================================================================
# v85: Duplicate Section Heading Removal
# ============================================================================

def _remove_duplicate_section_headings(text: str) -> str:
    """
    Remove duplicate section headings where LLM generates a bold title
    immediately after the Markdown heading.
    
    Example:
        ## Introduction\n\n**Introduction**\n  ->  ## Introduction\n\n
        ## Discussion\n\n**Discussion**\n    ->  ## Discussion\n\n
    """
    if not text:
        return text
    
    section_names = [
        'Abstract', 'Introduction', 'Results', 'Discussion', 
        'Conclusion', 'Conclusions', 'Methods', 'References'
    ]
    
    removed = 0
    for name in section_names:
        pattern = re.compile(
            rf'(##\s+{re.escape(name)}\s*\n)'
            rf'(\n?)'
            rf'\*\*{re.escape(name)}[:\.]?\*\*[:\.]?\s*\n?',
            re.IGNORECASE
        )
        new_text = pattern.sub(r'\1\2', text)
        if new_text != text:
            removed += 1
            text = new_text
    
    if removed > 0:
        _sse_log(f"[PostProcess] v85: Removed {removed} duplicate section headings")
    
    return text


# ============================================================================
# v85: Abstract Numerical Integrity Enforcement
# ============================================================================

def _enforce_abstract_numbers(text: str, metadata: Dict) -> str:
    """
    Verify and correct key numerical values in the Abstract section.
    
    If the LLM generated numbers that don't match the actual data,
    replace them with the correct values from metadata.
    
    metadata keys:
        n_dual: int - number of dual-PTM proteins
        n_conc: int - number of concordant proteins
        n_disc: int - number of discordant proteins
        n_gate: int - number of sequential gating events
        n_shared_nonptm: int - number of shared non-PTM interactors
    """
    if not metadata:
        return text
    
    n_dual = metadata.get('n_dual', 0)
    n_conc = metadata.get('n_conc', 0)
    n_disc = metadata.get('n_disc', 0)
    
    # Extract Abstract section
    abstract_match = re.search(
        r'(## Abstract\s*\n)(.*?)(?=\n---\n|\n## )',
        text, re.DOTALL
    )
    if not abstract_match:
        return text
    
    abstract_start = abstract_match.start(2)
    abstract_end = abstract_match.end(2)
    abstract_text = abstract_match.group(2)
    
    corrections = 0
    
    # Pattern 1: "N proteins undergo/exhibit/display dual PTM/modification"
    dual_patterns = [
        (r'(\b)(\d+)(\s+(?:proteins?|genes?)\s+(?:undergo|exhibit|display|carry|bear|harbor|possess|show|with)\s+(?:dual|both|co-))', n_dual),
        (r'(\b)(\d+)(\s+dual[- ]PTM\s+(?:proteins?|genes?|substrates?))', n_dual),
        (r'(identified\s+)(\d+)(\s+(?:proteins?|genes?)\s+(?:carrying|bearing|harboring|with|subject to)\s+both)', n_dual),
        (r'(\b)(\d+)(\s+(?:proteins?|genes?)\s+(?:were|are)\s+(?:identified|found|detected)\s+(?:as|to be)?\s*(?:dual|co-))', n_dual),
        (r'(comprising\s+)(\d+)(\s+dual[- ]PTM)', n_dual),
        (r'(\b)(\d+)(\s+(?:co-modified|dually[- ]modified|dual[- ]modified)\s+(?:proteins?|genes?))', n_dual),
    ]
    
    for pattern, correct_val in dual_patterns:
        match = re.search(pattern, abstract_text, re.IGNORECASE)
        if match:
            found_num = int(match.group(2))
            if found_num != correct_val:
                abstract_text = abstract_text[:match.start(2)] + str(correct_val) + abstract_text[match.end(2):]
                corrections += 1
                _sse_log(f"[PostProcess] v85: Abstract dual-PTM count corrected: {found_num} -> {correct_val}")
                break
    
    # Pattern 2: "N concordant"
    conc_patterns = [
        (r'(\b)(\d+)(\s+(?:proteins?|genes?)?\s*(?:exhibited?|displayed?|showed?|with)\s+concordant)', n_conc),
        (r'(\b)(\d+)(\s+concordant(?:ly)?\s+(?:regulated|co-regulated|modified))', n_conc),
        (r'(concordant\s+(?:co-)?regulation[:\s]+)(\d+)(\s+proteins?)', n_conc),
        (r'(\b)(\d+)(\s+concordant\s+(?:regulatory\s+)?patterns?)', n_conc),
    ]
    
    for pattern, correct_val in conc_patterns:
        match = re.search(pattern, abstract_text, re.IGNORECASE)
        if match:
            found_num = int(match.group(2))
            if found_num != correct_val:
                abstract_text = abstract_text[:match.start(2)] + str(correct_val) + abstract_text[match.end(2):]
                corrections += 1
                _sse_log(f"[PostProcess] v85: Abstract concordant count corrected: {found_num} -> {correct_val}")
                break
    
    # Pattern 3: "N discordant"
    disc_patterns = [
        (r'(\b)(\d+)(\s+(?:proteins?|genes?)?\s*(?:exhibited?|displayed?|showed?|with)\s+discordant)', n_disc),
        (r'(\b)(\d+)(\s+discordant(?:ly)?\s+(?:regulated|modified))', n_disc),
        (r'(discordant\s+(?:regulation|patterns?)[:\s]+)(\d+)(\s+proteins?)', n_disc),
        (r'(\b)(\d+)(\s+discordant\s+(?:regulatory\s+)?patterns?)', n_disc),
    ]
    
    for pattern, correct_val in disc_patterns:
        match = re.search(pattern, abstract_text, re.IGNORECASE)
        if match:
            found_num = int(match.group(2))
            if found_num != correct_val:
                abstract_text = abstract_text[:match.start(2)] + str(correct_val) + abstract_text[match.end(2):]
                corrections += 1
                _sse_log(f"[PostProcess] v85: Abstract discordant count corrected: {found_num} -> {correct_val}")
                break
    
    if corrections > 0:
        text = text[:abstract_start] + abstract_text + text[abstract_end:]
        _sse_log(f"[PostProcess] v85: Abstract integrity enforcement: {corrections} corrections applied")
    else:
        _sse_log(f"[PostProcess] v85: Abstract numbers verified - all correct")
    
    return text


# ============================================================================
# v85/v86: References Relevance Filtering
# ============================================================================

def filter_irrelevant_references(
    chromadb_results: list,
    ptm_types: list = None,
    min_relevance_score: float = 0.35,
    experimental_context: str = "",
) -> list:
    """
    v86 UPDATED: Filter out irrelevant ChromaDB results before they are added to References.
    
    Filters:
    1. Results below minimum relevance score threshold (raised from 0.25 to 0.35)
    2. Results whose source/title contains clearly off-topic keywords (expanded list)
    3. NEW: Results from clearly unrelated biological domains
    
    Args:
        chromadb_results: list of ChromaDB result dicts
        ptm_types: list of PTM types in the analysis (e.g., ['phosphorylation', 'ubiquitylation'])
        min_relevance_score: minimum relevance score to keep (default 0.35, raised from 0.25)
        experimental_context: optional experimental context string to extract domain keywords
    
    Returns:
        Filtered list of results
    """
    if not chromadb_results:
        return chromadb_results
    
    OFF_TOPIC_KEYWORDS = {
        'zebrafish', 'drosophila', 'c. elegans', 'caenorhabditis',
        'cosmetic', 'photosafety', 'nanoparticle', 'silver nanoparticle',
        'lactococcus', 'bacterial genome', 'minimal gene set',
        'mycobacterium', 'mycobacteria',
        'diesel exhaust', 'air pollution',
        'spermatozoa', 'infertile', 'fertility', 'ivf', 'embryo transfer',
        'parturition', 'obstetrics', 'postmenopausal', 'osteoporosis',
        'dental', 'orthodontic',
        'plant polysaccharide', 'freshwater plant', 'artemisia',
        'food safety', 'food additive', 'pork quality', 'meat quality',
        'food deterioration',
        'bovine', 'brahman', 'cattle', 'swine', 'porcine',
        'mink lung', 'canine distemper', 'cdv-infected',
        'chicken melanocortin', 'avian',
        'hiv-1', 'hiv latency', 'sars-cov', 'influenza',
        'antiviral drug target',
        'breast cancer', 'prostate cancer', 'colorectal cancer',
        'hepatocellular carcinoma', 'osteosarcoma', 'tongue cell carcinoma',
        'triple-negative breast', 'herceptin', 'paclitaxel',
        'hepatic glucolipid', 'insulin sensitivity',
        'melanocortin receptor', 'melanocortin-1',
        'glucokinase-expressing', 'staggerer mice',
        'malaria', 'plasmodium',
        'phthalate', 'di-(2-ethylhexyl)',
        'ochratoxin',
        'interferon isoform', 'phagocyte transcriptional',
        'hematopoiesis', 'inflammasome',
        'retinal proteome', 'diabetic retinal',
        'cholangiocarcinoma',
        'nucleolin lactylation', 'rna splicing regulation',
    }
    
    PTM_RELEVANT_KEYWORDS = {
        'phosphorylation', 'ubiquitylation', 'ubiquitination', 'acetylation',
        'sumoylation', 'methylation', 'glycosylation', 'ptm', 'post-translational',
        'kinase', 'phosphatase', 'e3 ligase', 'proteasome', 'ubiquitin',
        'signaling', 'signal transduction', 'pathway', 'proteomics',
        'proteome', 'phosphoproteome', 'mass spectrometry',
        'cell signaling', 'protein modification', 'cross-talk', 'crosstalk',
        'neuron', 'neuronal', 'hippocampal', 'synaptic', 'synapse',
        'neurodegenerative', 'neurodegeneration', 'alzheimer', 'parkinson',
        'tau', 'amyloid', 'axon', 'dendrite', 'microtubule',
        'brain', 'cerebral', 'cortex', 'hippocampus',
        'gsk3', 'cdk5', 'camk', 'mapk', 'erk',
        'stathmin', 'dpysl', 'crmp', 'mapt',
        'chaperone', 'hsp', 'dnaj', 'unfolded protein',
        'autophagy', 'apoptosis', 'cell death',
        'er stress', 'endoplasmic reticulum',
    }
    
    if ptm_types:
        for pt in ptm_types:
            PTM_RELEVANT_KEYWORDS.add(pt.lower())
    
    if experimental_context:
        context_lower = experimental_context.lower()
        domain_terms = set()
        for term in ['neuron', 'hippocampal', 'brain', 'cardiac', 'liver',
                     'kidney', 'muscle', 'immune', 'cancer', 'stem cell']:
            if term in context_lower:
                domain_terms.add(term)
        PTM_RELEVANT_KEYWORDS.update(domain_terms)
    
    original_count = len(chromadb_results)
    filtered = []
    removed_low_score = 0
    removed_off_topic = 0
    
    for r in chromadb_results:
        score = r.get('relevance_score', 0)
        source = r.get('metadata', {}).get('source', '').lower()
        content = r.get('content', '').lower()[:500]
        combined_text = f"{source} {content}"
        
        if score < min_relevance_score:
            removed_low_score += 1
            continue
        
        has_off_topic = any(kw in combined_text for kw in OFF_TOPIC_KEYWORDS)
        has_ptm_relevant = any(kw in combined_text for kw in PTM_RELEVANT_KEYWORDS)
        
        if has_off_topic and not has_ptm_relevant:
            removed_off_topic += 1
            continue
        
        filtered.append(r)
    
    if removed_low_score > 0 or removed_off_topic > 0:
        _sse_log(
            f"[PostProcess] v86: References filtered: {original_count} -> {len(filtered)} "
            f"(removed {removed_low_score} low-score, {removed_off_topic} off-topic)"
        )
    
    return filtered


# ============================================================================
# v85: Conclusion/Discussion Protein Whitelist Enforcement
# ============================================================================

def build_protein_whitelist_from_results(results_text: str) -> list:
    """
    Extract protein names mentioned in the Results section to create
    a whitelist for Conclusion and Discussion sections.
    
    Returns a sorted list of unique protein/gene names found in Results.
    """
    if not results_text:
        return []
    
    gene_pattern = re.compile(r'\b([A-Z][A-Z0-9]{1,}[a-z]?[0-9]*)\b')
    
    EXCLUDE_WORDS = {
        'THE', 'AND', 'FOR', 'NOT', 'BUT', 'ARE', 'WAS', 'HAS', 'HAD',
        'ALL', 'CAN', 'MAY', 'DID', 'ITS', 'OUR', 'USE', 'TWO', 'ONE',
        'NEW', 'OLD', 'SET', 'KEY', 'LOG', 'PTM', 'DNA', 'RNA', 'ATP',
        'GTP', 'GDP', 'ADP', 'AMP', 'NAD', 'FAD', 'COA',
        'BOTH', 'EACH', 'THIS', 'THAT', 'WITH', 'FROM', 'INTO', 'UPON',
        'OVER', 'THAN', 'ALSO', 'ONLY', 'MOST', 'SUCH', 'WHEN', 'THEN',
        'HERE', 'THUS', 'DOES', 'BEEN', 'WERE', 'HAVE', 'WILL', 'THEY',
        'SAME', 'MORE', 'LESS', 'VERY', 'WELL', 'JUST', 'SOME', 'MANY',
        'MUCH', 'LIKE', 'EVEN', 'STILL', 'WHAT', 'WHICH', 'WHERE',
        'FIGURE', 'TABLE', 'SECTION', 'RESULTS', 'DISCUSSION',
        'CONCLUSION', 'ABSTRACT', 'INTRODUCTION', 'METHODS',
        'CONCORDANT', 'DISCORDANT', 'NEUTRAL', 'MIXED',
        'SIGNAL', 'SIGNALING', 'PATHWAY', 'NETWORK', 'ANALYSIS',
        'PROTEIN', 'PROTEINS', 'MODIFICATION', 'REGULATION',
        'TEMPORAL', 'CROSS', 'TALK', 'DUAL', 'SEQUENTIAL',
        'CELL', 'CELLULAR', 'RESPONSE', 'MECHANISM', 'MODEL',
        'DATA', 'TOTAL', 'RATIO', 'PATTERN', 'PATTERNS',
        'IDENTIFIED', 'REVEALED', 'OBSERVED', 'EXHIBITED',
        'AMONG', 'BETWEEN', 'ACROSS', 'WITHIN', 'THROUGH',
        'FIRST', 'SECOND', 'THIRD', 'EARLY', 'LATE', 'RAPID',
        'POST', 'TRANSLATIONAL', 'PHOSPHORYLATION', 'UBIQUITYLATION',
        'UBIQUITINATION', 'KINASE', 'LIGASE', 'PROTEASOME',
        'DEGRADATION', 'ACTIVATION', 'INHIBITION', 'AMPLIFICATION',
        'ATTENUATION', 'FEEDBACK', 'FEEDFORWARD', 'INTEGRATION',
        'CONVERGENCE', 'PROPAGATION', 'RELAY', 'CASCADE',
        'EFFECTOR', 'SCAFFOLD', 'HUB', 'NODE', 'NODES',
        'SCF', 'UPS', 'DUB', 'RING', 'HECT',
    }
    
    matches = gene_pattern.findall(results_text)
    proteins = set()
    for m in matches:
        if m not in EXCLUDE_WORDS and len(m) >= 2:
            if any(c.isdigit() for c in m) or (len(m) <= 8 and m.isupper()):
                proteins.add(m)
    
    return sorted(proteins)


def build_available_refs_from_knowledge_context(knowledge_context: str) -> List[Dict]:
    """
    Parse knowledge_context string to extract available references for citation insertion.
    
    Extracts reference numbers and associated keywords from the context.
    """
    refs = []
    
    if not knowledge_context:
        return refs
    
    # Parse "--- Reference [n] ---" blocks
    blocks = re.split(r'---\s*Reference\s*\[(\d+)\]', knowledge_context)
    
    # blocks[0] is text before first reference, then alternating: ref_num, content
    for i in range(1, len(blocks) - 1, 2):
        try:
            ref_num = int(blocks[i])
            content = blocks[i + 1] if i + 1 < len(blocks) else ''
            
            # Extract title from content
            title = ''
            title_match = re.search(r'(?:Source|Title):\s*(.+?)(?:\n|$)', content)
            if title_match:
                title = title_match.group(1).strip()
            
            refs.append({
                'number': ref_num,
                'title': title,
                'text': content[:500],  # First 500 chars for keyword matching
            })
        except (ValueError, IndexError):
            continue
    
    # Also parse "--- REFERENCE LIST ---" section
    ref_list_match = re.search(r'---\s*REFERENCE\s*LIST\s*---\s*\n(.+?)(?:\n---|\Z)', knowledge_context, re.DOTALL)
    if ref_list_match:
        ref_list_text = ref_list_match.group(1)
        for line in ref_list_text.strip().split('\n'):
            match = re.match(r'\[(\d+)\]\s*(.+)', line.strip())
            if match:
                ref_num = int(match.group(1))
                ref_text = match.group(2)
                # Check if this ref_num already exists
                existing_nums = {r['number'] for r in refs}
                if ref_num not in existing_nums:
                    refs.append({
                        'number': ref_num,
                        'title': ref_text[:100],
                        'text': ref_text,
                    })
    
    return refs
