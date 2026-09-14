"""Finding-scoped retrieval and quote-anchored comparison using the existing RAG client."""
import hashlib
import json
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Iterable, Mapping

from common.model_json import parse_model_json

VERSION = "finding_retrieval.v3"
FINDING_RETRIEVAL_BACKOFF_SECONDS = 0.25
"""Bounded pause between retrieval layers.

구현 대상: docs/개발_업무지시서_연구자용_PTM_Report의_Identity_Projection·서사·생성.md §4.E-3
사전등록: 2026-09-14 표시 계약.
해석 한계: backoff는 runtime 보호이며 문헌 일치의 증명이 아니다.
주장 금지: 검색 성공을 kinase 귀속으로 해석하지 않는다.
"""
LAYER_RESULT_QUOTA = {
    "literature_background": 8,
    "gene_function_context": 4,
    "direct_site_evidence": 4,
    "counterevidence": 4,
}
QUOTE_BOUND_RELATIONSHIPS = {
    "known_agreement", "disagreement", "direct_site_evidence", "contradictory_evidence",
}
BACKGROUND_RELATIONSHIPS = {
    "literature_background", "gene_function_context", "pathway_context",
    "compatible_pattern", "context_difference",
}
ALLOWED_RELATIONSHIPS = QUOTE_BOUND_RELATIONSHIPS | BACKGROUND_RELATIONSHIPS
CONTEXT_FIELDS = ("species", "cell_type", "insulin_dose", "time", "readout", "perturbation")
PROPERTIES = {key: {"type": "string"} for key in ("quote", "external_finding", "reference_scope", "relationship", *CONTEXT_FIELDS)}
SCHEMA = {"type": "object", "properties": {"comparisons": {"type": "array", "items": {
    "type": "object", "properties": {"source_index": {"type": "integer"}, **PROPERTIES},
    "required": ["source_index", *PROPERTIES], "additionalProperties": False}}},
    "required": ["comparisons"], "additionalProperties": False}


def cards_for_selected_findings(cards: Iterable[Mapping], selected_ids) -> list[dict]:
    """Keep one card per frozen finding ID so discovery context cannot drop search.

    구현 대상: docs/official_temporal_terminology_contract.md § Finding literature
    사전등록: 2026-09-14 표시 계약.
    해석 한계: 검색 대상 선정이지 문헌 일치의 증명이 아니다.
    주장 금지: 검색 성공을 kinase 귀속으로 해석하지 않는다.
    """
    wanted = {str(fid) for fid in (selected_ids or []) if fid}
    chosen: dict[str, Mapping] = {}
    for card in cards or []:
        if not isinstance(card, Mapping):
            continue
        fid = str((card.get("feature_identity") or {}).get("reader_feature_id") or "")
        if fid not in wanted:
            continue
        current = chosen.get(fid)
        if current is None or (
            card.get("category") == "measured_feature_observation"
            and current.get("category") != "measured_feature_observation"
        ):
            chosen[fid] = card
    return [dict(chosen[fid]) for fid in wanted if fid in chosen]


def retrieve_finding_literature(cards, retriever, study, *, llm=None):
    """Search each frozen feature, retaining failures and incomplete comparisons.

    The application verifies literal source anchors and reference scope. A
    model's semantic comparison still requires scientific source review.
    """
    from ptm_shared.annotation_species import annotation_scope
    scope = annotation_scope(context=study)
    study = {**study, "species": scope["native_species"], "annotation_species_scope": scope,
             "cell_type": study.get("cell_type") or study.get("cell_model") or study.get("cell_line")}
    records, references, search_cache = {}, [], {}
    for card in cards:
        identity = card.get("feature_identity") or {}
        fid = identity["reader_feature_id"]
        site_query = " ".join(str(v) for v in (identity.get("gene"), identity.get("candidate_residue_annotation"),
                study.get("cell_type"), study.get("species"), study.get("treatment"), "PTM protein time course") if v)
        opposing_query = " ".join(str(v) for v in (identity.get("gene"), identity.get("candidate_residue_annotation"),
                study.get("cell_type"), study.get("species"), "PTM conflicting or opposing results") if v)
        query = site_query
        record = {"schema_version": VERSION, "reader_feature_id": fid, "feature_id": identity.get("feature_id"),
                  "query": query, "queried_at": datetime.now(timezone.utc).isoformat(),
                  "collections": list(getattr(retriever, "collection_names", []) or []),
                  "status": "not_searched", "retrieved_count": 0, "comparisons": [], "excluded_comparisons": []}
        records[fid] = record
        if not record["collections"]:
            continue
        layers = [
            ("literature_background", " ".join(str(study.get(k) or "") for k in ("treatment", "cell_type", "species")) + " signaling time course"),
            ("gene_function_context", str(identity.get("gene") or "") + " protein function"),
            ("direct_site_evidence", site_query),
            ("counterevidence", opposing_query),
        ]
        hits, seen = [], set()
        record["searches"] = []
        for layer, layer_query in layers:
            key = (layer, layer_query, tuple(record["collections"]))
            cache_hit = key in search_cache
            try:
                if not cache_hit:
                    search_cache[key] = retriever.query(
                        layer_query,
                        n_results=LAYER_RESULT_QUOTA.get(layer, 4),
                        strict=True,
                    )
                    if FINDING_RETRIEVAL_BACKOFF_SECONDS:
                        time.sleep(FINDING_RETRIEVAL_BACKOFF_SECONDS)
                found = deepcopy(search_cache[key])
            except Exception as error:
                record["searches"].append({"layer": layer, "query": layer_query, "status": "retrieval_failed", "failure_type": type(error).__name__})
                continue
            record["searches"].append({"layer": layer, "query": layer_query, "cache_hit": cache_hit, "retrieved_count": len(found)})
            for hit in found:
                hkey = hit.get("source_id") or hit.get("doi") or hit.get("pmid") or hashlib.sha256(str(hit.get("document", "")).encode()).hexdigest()
                if hkey not in seen:
                    hit["retrieval_layer"] = layer
                    hits.append(hit)
                    seen.add(hkey)
        if not hits and all(r.get("status") == "retrieval_failed" for r in record["searches"]):
            record.update(status="retrieval_failed")
            continue
        record["partial_retrieval_failure"] = any(r.get("status") == "retrieval_failed" for r in record["searches"])
        record.update(status="retrieved_comparison_pending", retrieved_count=len(hits))
        record["coverage"] = [{"collection": h.get("collection"), "collection_version": h.get("collection_version"),
                               "source_id": h.get("source_id"), "source_sha256": hashlib.sha256(str(h.get("document", "")).encode()).hexdigest()} for h in hits]
        if not hits:
            record["status"] = "not_explained_by_retrieved_evidence"
            continue
        references.extend(hits)
        if llm is None:
            continue
        prompt = ("Compare this measured feature with the retrieved excerpts. Return JSON only. "
                  "Use exact contiguous source quotes. Paraphrase external_finding within the source scope; do not copy unsupported mechanisms into it. Context fields must be source substrings or empty if unrecorded. "
                  "Do not infer absent species, dose, site or direct regulation. reference_scope is study, pathway, gene or site. "
                  "relationship is known_agreement, disagreement, literature_background, gene_function_context, pathway_context, compatible_pattern, context_difference, direct_site_evidence or contradictory_evidence; condition differences remain context, not proof of a defect. "
                  "Return an empty comparisons array when the excerpts do not support a comparison.\n" +
                  json.dumps({"observation": card.get("reader_summary"), "study": study,
                              "sources": [{"source_index": i, "text": h.get("document"), "metadata": h.get("metadata")} for i, h in enumerate(hits)]}, default=str))
        from common.generation_trace import capture_generation
        started = time.monotonic()
        generation = {"provider_raw_text": None, "resolved_model": getattr(llm, "model", None),
                      "resolved_provider": getattr(llm, "provider", None), "requested_max_tokens": 4096}
        record["comparison_generation"] = generation
        try:
            with capture_generation() as transport:
                generation["transport"] = transport
                generation["provider_raw_text"] = llm.generate(prompt, max_tokens=4096, response_format={"type": "json_schema", "json_schema": {"name": "finding_comparison", "strict": True, "schema": SCHEMA}})
            draft = parse_model_json(generation["provider_raw_text"])
            if not isinstance(draft, dict):
                raise ValueError("comparison_object_required")
            candidates = draft["comparisons"]
            if not isinstance(candidates, list):
                raise ValueError("comparison_array_required")
        except Exception as error:
            record.update(comparison_failure_type=type(error).__name__)
            generation["exception_type"] = type(error).__name__
            continue
        finally:
            generation["latency_seconds"] = time.monotonic() - started
        for candidate in candidates:
            if not isinstance(candidate, dict) or not all(isinstance(candidate.get(k), str) for k in PROPERTIES):
                record["excluded_comparisons"].append({"reason": "invalid_comparison_schema"})
                continue
            index = candidate.get("source_index")
            hit = hits[index] if isinstance(index, int) and 0 <= index < len(hits) else {}
            quote = str(candidate.get("quote") or "")
            document = str(hit.get("document") or "")
            scope = candidate.get("reference_scope")
            site = str(identity.get("candidate_residue_annotation") or "")
            gene = str(identity.get("gene") or "")
            relationship = candidate.get("relationship")
            finding_text = candidate.get("external_finding") or ""
            quote_bound = relationship not in QUOTE_BOUND_RELATIONSHIPS or finding_text in quote
            valid = (quote and quote in document and (scope in {"study", "pathway"} or gene.lower() in quote.lower())
                     and scope in {"study", "pathway", "gene", "site"} and (scope != "site" or site and site.lower() in quote.lower())
                     and relationship in ALLOWED_RELATIONSHIPS
                     and finding_text
                     and quote_bound
                     and (relationship != "direct_site_evidence" or scope == "site")
                     and (hit.get("doi") or hit.get("pmid"))
                     and all(not candidate.get(k) or candidate[k] in quote for k in CONTEXT_FIELDS))
            if not valid:
                record["excluded_comparisons"].append({"source_index": index, "reason": "unbound_quote_context_or_scope"})
                continue
            comparison = {**candidate, "reader_feature_id": fid, "feature_id": identity.get("feature_id"),
                          "observation": card.get("reader_summary"), "source_offset": document.index(quote),
                          "source_sha256": hashlib.sha256(document.encode()).hexdigest(),
                          "condition_differences": [f"Source {k}: {candidate[k]}; current study: {study.get(k, 'unrecorded')}"
                                                    for k in CONTEXT_FIELDS if candidate.get(k) and str(study.get(k, "")) != candidate[k]],
                          "comparison_status": "source_anchored_semantic_review_required", "measured_relation": False}
            hit.setdefault("feature_comparisons", []).append(comparison)
            record["comparisons"].append({"source_index": index, "relationship": comparison["relationship"], "reference_scope": scope})
        relations = {c["relationship"] for c in record["comparisons"] if c["relationship"] in {"known_agreement", "disagreement"}}
        record["status"] = ("agreement_and_disagreement" if len(relations) > 1 else next(iter(relations)) if relations else
                            "context_available" if record["comparisons"] else "retrieved_comparison_pending" if record["excluded_comparisons"] else "not_explained_by_retrieved_evidence")
    return {
        "schema_version": VERSION,
        "records": records,
        "references": references,
        "retrieval_status_card": compact_literature_status_card(records),
    }


def compact_literature_status_card(records: Mapping[str, Mapping] | None) -> dict:
    """One compact reader status for pending/failed retrieval; do not repeat it per finding."""
    rows = list((records or {}).values())
    pending = sum(1 for row in rows if row.get("status") == "retrieved_comparison_pending")
    failed = sum(1 for row in rows if row.get("status") == "retrieval_failed")
    anchored = sum(1 for row in rows if row.get("comparisons"))
    return {
        "card_id": "literature.retrieval_status",
        "category": "traceable_literature",
        "pending_count": pending,
        "failed_count": failed,
        "source_anchored_count": anchored,
        "selected_finding_count": len(rows),
        "reader_summary": (
            f"Literature retrieval: {anchored} source-anchored comparison(s), "
            f"{pending} comparison-pending, {failed} failed of {len(rows)} selected finding(s). "
            "Pending or failed retrieval does not erase measured observations."
        ),
    }
