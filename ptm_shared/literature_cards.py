"""Existing reference-card serialization shared by legacy report and Astra."""
from __future__ import annotations
import re
from typing import Any, Iterable, Mapping

_INTERNAL_TERM_RE = re.compile(
    r"\b(?:P[0-5]|M[0-4]|R[0-4]|TW-\d+|wave_[\w-]+|cowave_[\w-]+|"
    r"DATA-[A-Z0-9_-]+|computed_no_eligible_[\w-]+|not_recorded|"
    r"packet unavailable|n_eff|LOTO|p=None)\b",
    flags=re.IGNORECASE,
)


def _as_mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _clean_text(value: Any) -> str:
    """Return compact reader-facing text without transport or diagnostic labels."""
    text = str(value or "").strip()
    text = re.sub(r"\[?DATA-[A-Z0-9_-]+\]?", "", text, flags=re.IGNORECASE)
    text = _INTERNAL_TERM_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip(" -;,")


def is_traceable_reference(reference: Mapping[str, Any] | None) -> bool:
    """Return True only for publication identities that may enter a bibliography.

    구현 대상: docs/official_temporal_terminology_contract.md reader-facing
    Report wording; 2026-09-07 implementation_log reader-authoring repair.
    사전등록: 2026-09-07 표시 계약. 결과 기반 primary 승격 아님.
    해석 한계: 추적 가능한 서지 식별자의 존재는 현재 Order 관측을 입증하지 않는다.
    주장 금지: title-only Chroma bundle label을 문헌 합의나 kinase 근거로 쓰지 않는다.
    """
    ref = _as_mapping(reference)
    if str(ref.get("pmid") or "").strip() or str(ref.get("doi") or "").strip():
        return True
    return bool(
        str(ref.get("title") or "").strip()
        and str(ref.get("authors") or "").strip()
        and str(ref.get("year") or ref.get("pub_date") or "").strip()
        and str(ref.get("journal") or "").strip()
    )


def references_are_citation_complete(references: Iterable[Mapping[str, Any]] | None) -> bool:
    """True when at least one supplied record is a traceable publication identity."""
    return any(is_traceable_reference(item) for item in (references or []) if isinstance(item, Mapping))


def _stable_reference_id(reference: Mapping[str, Any]) -> str:
    pmid = str(reference.get("pmid") or "").strip().lower()
    if pmid:
        return f"pmid:{pmid}"
    doi = str(reference.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    title = re.sub(r"[^a-z0-9]", "", str(reference.get("title") or "").lower())[:120]
    return f"title:{title}" if title else ""


def _literature_cards(references: Iterable[Mapping[str, Any]]) -> list[dict]:
    cards: list[dict] = []
    emitted: set[str] = set()
    for index, reference in enumerate(references or [], 1):
        ref = _as_mapping(reference)
        stable_id = _stable_reference_id(ref)
        title = _clean_text(ref.get("title"))
        if not stable_id or stable_id in emitted or not title or not is_traceable_reference(ref):
            continue
        emitted.add(stable_id)
        authors = _clean_text(ref.get("authors"))
        year = _clean_text(ref.get("year") or ref.get("pub_date"))[:4]
        identity = ", ".join(value for value in (authors, year) if value)
        excerpt = _clean_text(ref.get("reader_excerpt") or ref.get("excerpt") or ref.get("document"))
        # A short source excerpt lets the scientific author write actual
        # literature context rather than an uninformative bibliography list.
        # It remains bound to the supplied publication identity and is never a
        # current-order observation.
        anchors = [str(c.get("quote")) for c in ref.get("feature_comparisons") or [] if c.get("quote")]
        excerpt = " ".join(dict.fromkeys(anchors)) if anchors else excerpt
        source_excerpt = excerpt
        if len(excerpt) > 1800:
            # Bound quotes and unbound background share the same display cap.
            selected_sentences = []
            for sentence in _split_sentences(excerpt):
                if selected_sentences and sum(map(len, selected_sentences)) + len(sentence) > 1800:
                    break
                selected_sentences.append(sentence)
            excerpt = " ".join(selected_sentences)
        contextual_summary = (
            f"Selected literature reported the following relevant external context: {excerpt}"
            if excerpt
            else f"Selected literature provides external context through {title}"
        )
        cards.append({
            "card_id": f"literature.{index}",
            "category": "traceable_literature",
            "reader_summary": contextual_summary + (f" ({identity})." if identity else "."),
            "claim_tier": "L1",
            "evidence_ids": [f"literature.{stable_id}"],
            "citation_ids": [stable_id],
            "excerpt_selection": {"rule": "comparison_source_anchors" if anchors else "complete_background_sentences", "source_characters": len(source_excerpt), "selected_characters": len(excerpt)},
            "allowed_verbs": ["reported", "described", "provided context for", "was consistent with"],
            "forbidden_interpretations": ["proved the current observation", "established a current direct relationship"],
            "counterevidence": "Literature context does not convert a prior relationship into a current-order observation.",
        })
    return cards


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text or "") if sentence.strip()]
