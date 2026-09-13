"""Finding-scoped retrieval and quote-anchored comparison using the existing RAG client."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

VERSION = "finding_retrieval.v1"
CONTEXT_FIELDS = ("species", "cell_type", "insulin_dose", "time", "readout", "perturbation")
PROPERTIES = {key: {"type": "string"} for key in ("quote", "external_finding", "reference_scope", "relationship", *CONTEXT_FIELDS)}
SCHEMA = {"type": "object", "properties": {"comparisons": {"type": "array", "items": {
    "type": "object", "properties": {"source_index": {"type": "integer"}, **PROPERTIES},
    "required": ["source_index", *PROPERTIES], "additionalProperties": False}}},
    "required": ["comparisons"], "additionalProperties": False}


def retrieve_finding_literature(cards, retriever, study, *, llm=None):
    """Search each frozen feature, retaining failures and incomplete comparisons.

    The application verifies literal source anchors and reference scope. A
    model's semantic comparison still requires scientific source review.
    """
    records, references = {}, []
    for card in cards:
        identity = card.get("feature_identity") or {}
        fid = identity["reader_feature_id"]
        query = " ".join(str(v) for v in (identity.get("gene"), identity.get("candidate_residue_annotation"),
                study.get("cell_type"), study.get("species"), study.get("treatment"), "PTM protein time course opposing results") if v)
        record = {"schema_version": VERSION, "reader_feature_id": fid, "feature_id": identity.get("feature_id"),
                  "query": query, "queried_at": datetime.now(timezone.utc).isoformat(),
                  "collections": list(getattr(retriever, "collection_names", []) or []),
                  "status": "not_searched", "retrieved_count": 0, "comparisons": [], "excluded_comparisons": []}
        records[fid] = record
        if not record["collections"]:
            continue
        try:
            hits = deepcopy(retriever.query(query, n_results=4, strict=True))
        except Exception as error:
            record.update(status="retrieval_failed", failure_type=type(error).__name__)
            continue
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
                  "Use exact contiguous source quotes; external_finding and each context field must be a literal substring of its quote, or empty if unrecorded. "
                  "Do not infer absent species, dose, site or direct regulation. reference_scope is gene or site. "
                  "relationship is known_agreement or disagreement; condition differences remain context, not proof of a defect. "
                  "Return an empty comparisons array when the excerpts do not support a comparison.\n" +
                  json.dumps({"observation": card.get("reader_summary"), "study": study,
                              "sources": [{"source_index": i, "text": h.get("document"), "metadata": h.get("metadata")} for i, h in enumerate(hits)]}, default=str))
        try:
            draft = json.loads(llm.generate(prompt, max_tokens=4096, response_format={"type": "json_schema", "json_schema": {"name": "finding_comparison", "strict": True, "schema": SCHEMA}}))
            candidates = draft["comparisons"]
            if not isinstance(candidates, list):
                raise ValueError("comparison_array_required")
        except Exception as error:
            record.update(comparison_failure_type=type(error).__name__)
            continue
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
            valid = (quote and quote in document and gene.lower() in quote.lower()
                     and scope in {"gene", "site"} and (scope != "site" or site and site.lower() in quote.lower())
                     and candidate.get("relationship") in {"known_agreement", "disagreement"}
                     and candidate.get("external_finding") and candidate["external_finding"] in quote
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
        relations = {c["relationship"] for c in record["comparisons"]}
        record["status"] = ("agreement_and_disagreement" if len(relations) > 1 else next(iter(relations)) if relations else
                            "retrieved_comparison_pending" if record["excluded_comparisons"] else "not_explained_by_retrieved_evidence")
    return {"schema_version": VERSION, "records": records, "references": references}
