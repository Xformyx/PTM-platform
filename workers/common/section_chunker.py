"""
Section-Aware Semantic Chunker (v2)
Ported from ptm-chromadb-web/python_backend/document_embedder.py.

Detects paper sections (Abstract, Introduction, Methods, Results, Discussion)
and splits text at sentence boundaries preserving semantic coherence.
Section metadata is preserved in each chunk for better retrieval.
"""

import re
from typing import Dict, List, Tuple

SECTION_PATTERNS = [
    (r'(?:^|\n)\s*(?:ABSTRACT|Abstract)\s*(?:\n|$)', 'abstract'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:INTRODUCTION|Introduction)\s*(?:\n|$)', 'introduction'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:BACKGROUND|Background)\s*(?:\n|$)', 'introduction'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:LITERATURE\s+REVIEW|Literature\s+Review)\s*(?:\n|$)', 'introduction'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:MATERIALS?\s+AND\s+METHODS?|Materials?\s+and\s+Methods?)\s*(?:\n|$)', 'methods'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:METHODS?|Methods?)\s*(?:\n|$)', 'methods'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:EXPERIMENTAL\s+(?:PROCEDURES?|SECTION)|Experimental\s+(?:Procedures?|Section))\s*(?:\n|$)', 'methods'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:RESULTS?|Results?)\s*(?:\n|$)', 'results'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:RESULTS?\s+AND\s+DISCUSSION|Results?\s+and\s+Discussion)\s*(?:\n|$)', 'results_discussion'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:DISCUSSION|Discussion)\s*(?:\n|$)', 'discussion'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:CONCLUSION|Conclusion|CONCLUSIONS|Conclusions)\s*(?:\n|$)', 'conclusion'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:SUPPLEMENTARY|Supplementary|SUPPORTING\s+INFORMATION|Supporting\s+Information)\s*(?:\n|$)', 'supplementary'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:REFERENCES?|References?|BIBLIOGRAPHY|Bibliography)\s*(?:\n|$)', 'references'),
    (r'(?:^|\n)\s*(?:\d+\.?\s*)?(?:ACKNOWLEDGEMENTS?|Acknowledgements?|ACKNOWLEDGMENTS?|Acknowledgments?)\s*(?:\n|$)', 'acknowledgements'),
]

SKIP_SECTIONS = {"references", "acknowledgements", "supplementary"}


def detect_sections(text: str) -> List[Tuple[str, str, int, int]]:
    matches = []
    for pattern, label in SECTION_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.append((match.group().strip(), label, match.start(), match.end()))
    matches.sort(key=lambda x: x[2])
    filtered = []
    for m in matches:
        if not filtered or m[2] > filtered[-1][3] + 10:
            filtered.append(m)
    return filtered


def split_into_sections(text: str) -> List[Dict[str, str]]:
    sections = detect_sections(text)
    if not sections:
        return [{"section": "fulltext", "title": "Full Text", "text": text}]

    result = []
    if sections[0][2] > 100:
        preamble = text[:sections[0][2]].strip()
        if preamble:
            result.append({"section": "preamble", "title": "Preamble", "text": preamble})

    for i, (header, label, start, end) in enumerate(sections):
        section_text = (text[end:sections[i + 1][2]] if i + 1 < len(sections) else text[end:]).strip()
        if section_text:
            result.append({"section": label, "title": header.strip(), "text": section_text})

    return result


def semantic_sentence_split(text: str, max_chunk_size: int = 2000, overlap_sentences: int = 2) -> List[str]:
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-Z\d\(])'
    sentences = [s.strip() for s in re.split(sentence_pattern, text) if s.strip()]
    if not sentences:
        return [text] if text.strip() else []

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_size = 0

    for sentence in sentences:
        sentence_size = len(sentence)
        if sentence_size > max_chunk_size:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk, current_size = [], 0
            for j in range(0, len(sentence), max_chunk_size - 200):
                sub = sentence[j:j + max_chunk_size]
                if sub.strip():
                    chunks.append(sub.strip())
            continue

        if current_size + sentence_size + 1 > max_chunk_size and current_chunk:
            chunks.append(" ".join(current_chunk))
            if overlap_sentences > 0 and len(current_chunk) > overlap_sentences:
                overlap = current_chunk[-overlap_sentences:]
                current_chunk = overlap.copy()
                current_size = sum(len(s) for s in current_chunk) + len(current_chunk) - 1
            else:
                current_chunk, current_size = [], 0

        current_chunk.append(sentence)
        current_size += sentence_size + 1

    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks


def section_aware_chunk(
    text: str,
    max_chunk_size: int = 2000,
    overlap_sentences: int = 2,
    source: str = "",
) -> List[Dict]:
    """
    Chunk text with section awareness. Returns list of dicts with keys:
      text, section, section_title, section_chunk_index, chunking_method, source
    """
    sections = split_into_sections(text)
    all_chunks: List[Dict] = []

    for sec in sections:
        if sec["section"] in SKIP_SECTIONS:
            continue
        sec_text = sec["text"]
        if not sec_text.strip():
            continue

        if len(sec_text) <= max_chunk_size:
            all_chunks.append({
                "text": sec_text,
                "section": sec["section"],
                "section_title": sec["title"],
                "section_chunk_index": 0,
                "chunking_method": "section_whole",
                "source": source,
            })
        else:
            sub_chunks = semantic_sentence_split(sec_text, max_chunk_size, overlap_sentences)
            for idx, chunk_text in enumerate(sub_chunks):
                all_chunks.append({
                    "text": chunk_text,
                    "section": sec["section"],
                    "section_title": sec["title"],
                    "section_chunk_index": idx,
                    "chunking_method": "section_semantic",
                    "source": source,
                })

    if not all_chunks:
        sub_chunks = semantic_sentence_split(text, max_chunk_size, overlap_sentences)
        for idx, chunk_text in enumerate(sub_chunks):
            all_chunks.append({
                "text": chunk_text,
                "section": "fulltext",
                "section_title": "Full Text",
                "section_chunk_index": idx,
                "chunking_method": "semantic_fallback",
                "source": source,
            })

    return all_chunks
