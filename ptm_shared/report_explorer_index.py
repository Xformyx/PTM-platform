"""Derived joins over sealed report packets. No retrieval or scientific inference.

Only explicit feature/evidence IDs join records. A gene label or citation's
existence never establishes feature-level support. Model prompts are not exposed.
"""
import json
import os
import tempfile
from pathlib import Path
from .analysis_universe import signature
from .report_revision import file_sha256, _atomic_json

VERSION = "report_explorer_index.v2"

# Retrieval records also contain resolved prompts, provider responses and
# transport traces. The reader-facing index exposes only source accounting.
SOURCE_RUN_FIELDS = {
    "schema_version", "reader_feature_id", "feature_id", "query", "queried_at",
    "collections", "status", "reason", "retrieved_count", "review_reason",
    "partial_retrieval_failure", "comparison_failure_type", "resolved_prompt_sha256",
}


def public_source_run(record):
    result = {key:record[key] for key in SOURCE_RUN_FIELDS if key in record}
    for name, fields in {
        "searches": {"layer", "query", "status", "failure_type", "cache_hit", "retrieved_count"},
        "coverage": {"collection", "collection_version", "source_id", "source_sha256"},
        "comparisons": {"source_index", "relationship", "reference_scope"},
        "excluded_comparisons": {"source_index", "reason"},
    }.items():
        if name in record:
            result[name] = [{k:v for k,v in row.items() if k in fields} for row in record[name]]
    return result


def build_report_explorer_index(root, report, destination):
    """Write sealed-report Explorer rows with the same chunked COPY as §5.1.

    구현 대상: docs/BUILD_AND_DEPLOY.md §5.1 report_explorer_index.v2
    사전등록: 해당 없음 (인덱스 작성, 2026-09-21).
    해석 한계: 봉인 패킷 조회 인덱스다. TMM 입력이 아니다.
    주장 금지: 이 파일로 kinase 귀속이나 τ를 논하지 않는다.
    """
    root, destination = Path(root), Path(destination)
    metadata=destination.with_suffix(".manifest.json")
    if metadata.exists():
        result=json.loads(metadata.read_text())
        if result.get("schema_version") != VERSION: raise ValueError("report_index_schema_incompatible")
        if result["sha256"]!=file_sha256(destination): raise ValueError("report_index_integrity_failed")
        return result
    packets, bindings = {}, {}
    roles = {"authoring_packet", "prose_trace", "finding_literature_retrieval", "resolved_references"}
    for artifact in report["artifacts"]:
        if artifact["role"] in roles:
            packets[artifact["role"]] = json.loads((root/artifact["filename"]).read_text())
            bindings[artifact["role"]] = artifact["sha256"]
    rows = []
    def emit(kind, identity, record, feature_id=""):
        rows.append(dict(kind=kind,record_id="report:"+identity,feature_id=feature_id,
            pathway_key="",kinase="",track="",record_json=json.dumps({**record,
            "report_revision":report["revision_id"],"source_snapshot_hashes":bindings},allow_nan=False)))
    evidence_features = {}
    for card in (packets.get("authoring_packet") or {}).get("reader_cards", []):
        fid = (card.get("feature_identity") or {}).get("feature_id") or ""
        for eid in card.get("evidence_ids", []):
            evidence_features.setdefault(eid,set()).add(fid)
            emit("evidence",signature([eid,fid]),{**card,"evidence_id":eid,"source_type":"sealed_authoring_card",
                "binding_scope":"feature" if fid else "context_only"},fid)
    retrieval = packets.get("finding_literature_retrieval") or {}
    searches = retrieval.get("records", {})
    for i, record in enumerate(searches.values() if isinstance(searches,dict) else searches):
        emit("source-runs",signature(record),{**public_source_run(record),"source":"finding_literature",
            "source_run_id":signature(record)},record.get("feature_id") or "")
    references = list(report.get("references", []))
    for values in (packets.get("resolved_references"),retrieval.get("references")):
        if isinstance(values,dict): values=values.get("references", [])
        references.extend(values or [])
    seen_assertions=set()
    for ref in references:
        # Preserve separate references when identity resolution is incomplete.
        rid = ref.get("reference_id") or ref.get("citation_id") or signature(ref)
        for assertion in ref.get("feature_comparisons", []):
            assertion_key=signature([rid,assertion])
            if assertion_key in seen_assertions: continue
            seen_assertions.add(assertion_key)
            fid=assertion.get("feature_id") or ""
            emit("evidence",signature([rid,assertion]),{**assertion,"source_type":"literature_assertion",
                "reference_id":rid,"pmid":ref.get("pmid"),"doi":ref.get("doi"),"title":ref.get("title"),
                "access_scope":ref.get("access_scope") or ref.get("source_scope") or "unrecorded",
                "binding_scope":"feature" if fid else "context_only"},fid)
    for section, trace in (packets.get("prose_trace") or {}).get("sections", {}).items():
        for i, claim in enumerate(trace.get("structured_decode_audit", [])):
            eids=claim.get("evidence_ids") or []
            fids=set().union(*(evidence_features.get(eid,set()) for eid in eids)) if eids else set()
            # The audit's retained state is a software decision, not validation
            # of biology. Keep rejected claims and their reasons accessible.
            record={key:claim[key] for key in ("paragraph_id","paragraph_index","sentence_index","claim_id",
                "evidence_ids","citation_ids","value_tokens","retained","validator_action","reason_code","reason_codes","role","scope") if key in claim}
            record.update(section=section,claim_link_id=signature([report["revision_id"],section,i]),
                source_trace_index=i,binding_scope="feature" if any(fids) else "context_only",
                release_status=report["release"].get("status"))
            for fid in sorted(fids or {""}): emit("report-claims",signature([section,i,fid]),record,fid)
    emit("source-runs","sealed_report",{"source":"sealed_report_packets","status":"available" if packets else "unavailable",
        "reason":None if packets else "no_sealed_evidence_packets","packet_roles":sorted(packets)})
    destination.parent.mkdir(parents=True,exist_ok=True)
    from .signaling_evidence_index import _copy_jsonl_to_parquet
    with tempfile.TemporaryDirectory(dir=destination.parent) as work:
        temporary=Path(work)/"records.jsonl"
        with temporary.open("x") as stream:
            for row in rows: stream.write(json.dumps(row,allow_nan=False)+"\n")
        work_parquet=Path(work)/destination.name
        _copy_jsonl_to_parquet(
            temporary,
            work_parquet,
            {key:"VARCHAR" for key in rows[0]},
            spill=Path(work)/"spill",
        )
        for part in sorted(Path(work).glob(f"{destination.stem}-part-*.parquet")):
            os.replace(part, destination.parent / part.name)
        os.replace(work_parquet,destination)
    result={"schema_version":VERSION,"filename":str(destination.relative_to(root)),"sha256":file_sha256(destination),
        "annotation_snapshot":signature(bindings) if bindings else None,"packet_roles":sorted(packets),
        "source_scope":"sealed_report_packets","record_count":len(rows)}
    _atomic_json(metadata,result)
    return result
