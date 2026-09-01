"""Local P2 curated kinase--substrate relation provenance for PTM-Vector.

P2 accepts only a licence-declared, checksum-validated local snapshot.  It is
not a live database client, kinase-score model, benchmark scorer, or direct
single-kinase attribution engine.  A compatible exact relation remains a full
ledger candidate set that requires the separately governed P3 allocation step.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


RELATION_IMPORTER_CONTRACT_VERSION = "ptm_kinase_relation_evidence.v1"
RELATION_SOURCE_BUNDLE_CONTRACT_VERSION = "ptm_kinase_relation_source_bundle.v1"
RELATION_ROW_SCHEMA_VERSION = "ptm_kinase_relation_rows.v1"
R0_NOT_EVALUABLE = "R0_not_evaluable"
R1_INELIGIBLE = "R1_ineligible_feature_or_mapping"
R2_NO_EXACT_EDGE = "R2_no_exact_curated_edge"
R3_CANDIDATE_SET = "R3_exact_curated_candidate_set_pending_p3"
R4_CONFLICTING = "R4_conflicting_or_ambiguous_curated_edge"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RelationSourceBundleError(ValueError):
    """Machine-readable validation error for a local P2 source bundle."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class RelationSourceBundle:
    """Validated local relation evidence, never exposed to compact consumers."""

    bundle_id: str
    manifest_sha256: str
    source_name: str
    release_or_retrieval_date: str
    relation_path: Path
    relation_rows: tuple[Mapping[str, Any], ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _required_text(container: Mapping[str, Any], key: str, *, context: str) -> str:
    value = _text(container.get(key))
    if not value:
        raise RelationSourceBundleError("required_field_missing", f"{context}.{key} is required")
    return value


def _trusted_file(root: Path, relative_path: Any, expected_sha256: Any, *, label: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise RelationSourceBundleError("required_file_path_missing", f"{label}.relative_path is required")
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise RelationSourceBundleError("absolute_path_disallowed", f"{label} must be relative to snapshot root")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved_root != resolved and resolved_root not in resolved.parents:
        raise RelationSourceBundleError("snapshot_path_escape", f"{label} escapes snapshot root")
    expected = _text(expected_sha256).lower()
    if not _SHA256_RE.fullmatch(expected):
        raise RelationSourceBundleError("invalid_sha256", f"{label}.sha256 must be a lowercase SHA-256")
    if not resolved.is_file():
        raise RelationSourceBundleError("snapshot_file_missing", f"{label} is not present beneath snapshot root")
    if _sha256(resolved) != expected:
        raise RelationSourceBundleError("snapshot_sha256_mismatch", f"{label} SHA-256 does not match manifest")
    return resolved


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open("r", encoding="utf-8")


def _normalized_accession(value: Any) -> str:
    return _text(value).upper()


def _row_join_key(row: Mapping[str, Any]) -> tuple[str, int, str, int, str, str, int]:
    substrate_taxonomy = _positive_int(row.get("substrate_taxonomy_id"))
    kinase_taxonomy = _positive_int(row.get("kinase_taxonomy_id"))
    position = _positive_int(row.get("position"))
    assert substrate_taxonomy and kinase_taxonomy and position
    return (
        _normalized_accession(row.get("substrate_accession")),
        substrate_taxonomy,
        _text(row.get("residue")).upper(),
        position,
        _text(row.get("substrate_isoform_or_sequence_id")),
        _normalized_accession(row.get("kinase_accession")),
        kinase_taxonomy,
    )


def _validate_relation_row(row: Mapping[str, Any], line_number: int) -> dict[str, Any]:
    required = {
        "edge_id", "relation_type", "kinase_accession", "kinase_taxonomy_id",
        "substrate_accession", "substrate_taxonomy_id", "residue", "position",
        "substrate_isoform_or_sequence_id", "evidence_reference_ids", "source_provenance",
    }
    if required - set(row):
        raise RelationSourceBundleError("relation_snapshot_schema_invalid", f"relation row {line_number} misses required fields")
    normalized = dict(row)
    if _text(normalized.get("relation_type")) != "kinase_substrate_phosphorylation":
        raise RelationSourceBundleError("relation_type_unsupported", f"relation row {line_number} is not a phosphorylation edge")
    if not _normalized_accession(normalized.get("kinase_accession")) or not _normalized_accession(normalized.get("substrate_accession")):
        raise RelationSourceBundleError("relation_accession_missing", f"relation row {line_number} has no canonical kinase/substrate accession")
    if not _positive_int(normalized.get("kinase_taxonomy_id")) or not _positive_int(normalized.get("substrate_taxonomy_id")):
        raise RelationSourceBundleError("relation_taxonomy_invalid", f"relation row {line_number} has invalid taxonomy ID")
    residue = _text(normalized.get("residue")).upper()
    if residue not in {"S", "T", "Y"} or not _positive_int(normalized.get("position")):
        raise RelationSourceBundleError("relation_site_invalid", f"relation row {line_number} lacks one valid S/T/Y residue coordinate")
    isoform = _text(normalized.get("substrate_isoform_or_sequence_id"))
    if not isoform or isoform.lower() == "canonical_unspecified":
        raise RelationSourceBundleError("relation_isoform_or_sequence_missing", f"relation row {line_number} lacks a source-versioned substrate isoform/sequence ID")
    reference_ids = normalized.get("evidence_reference_ids")
    if not isinstance(reference_ids, list) or not any(_text(value) for value in reference_ids):
        raise RelationSourceBundleError("relation_reference_missing", f"relation row {line_number} has no evidence reference identifier")
    if not isinstance(normalized.get("source_provenance"), Mapping):
        raise RelationSourceBundleError("relation_source_provenance_invalid", f"relation row {line_number} has no source provenance object")
    normalized.update({
        "edge_id": _required_text(normalized, "edge_id", context=f"relation row {line_number}"),
        "kinase_accession": _normalized_accession(normalized.get("kinase_accession")),
        "substrate_accession": _normalized_accession(normalized.get("substrate_accession")),
        "kinase_taxonomy_id": int(normalized["kinase_taxonomy_id"]),
        "substrate_taxonomy_id": int(normalized["substrate_taxonomy_id"]),
        "residue": residue,
        "position": int(normalized["position"]),
        "substrate_isoform_or_sequence_id": isoform,
        "evidence_reference_ids": sorted({_text(value) for value in reference_ids if _text(value)}),
        "source_provenance": dict(normalized["source_provenance"]),
    })
    return normalized


def _read_relation_rows(path: Path) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    edge_ids: set[str] = set()
    join_keys: set[tuple[str, int, str, int, str, str, int]] = set()
    with _open_text(path) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                decoded = json.loads(line)
            except json.JSONDecodeError as error:
                raise RelationSourceBundleError("relation_snapshot_invalid_json", f"relation row {line_number} is not JSON") from error
            if not isinstance(decoded, Mapping):
                raise RelationSourceBundleError("relation_snapshot_schema_invalid", f"relation row {line_number} is not an object")
            row = _validate_relation_row(decoded, line_number)
            if row["edge_id"] in edge_ids:
                raise RelationSourceBundleError("relation_edge_id_duplicate", f"relation row {line_number} duplicates edge_id {row['edge_id']}")
            key = _row_join_key(row)
            if key in join_keys:
                raise RelationSourceBundleError("relation_edge_duplicate", f"relation row {line_number} duplicates one exact kinase/site/isoform edge")
            edge_ids.add(row["edge_id"])
            join_keys.add(key)
            rows.append(row)
    return tuple(rows)


def load_relation_source_bundle(
    manifest_path: str | Path,
    *,
    snapshot_root: str | Path,
) -> RelationSourceBundle:
    """Load a fully local P2 relation bundle or raise a validation error."""

    root = Path(snapshot_root)
    manifest = Path(manifest_path)
    if not root.is_dir():
        raise RelationSourceBundleError("snapshot_root_missing", "relation snapshot root is not available")
    if not manifest.is_file():
        raise RelationSourceBundleError("bundle_manifest_missing", "relation source-bundle manifest is not available")
    resolved_root = root.resolve()
    resolved_manifest = manifest.resolve()
    if resolved_root != resolved_manifest and resolved_root not in resolved_manifest.parents:
        raise RelationSourceBundleError("bundle_manifest_outside_snapshot_root", "relation manifest must reside beneath snapshot root")
    try:
        raw_manifest = manifest.read_bytes()
        payload = json.loads(raw_manifest.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RelationSourceBundleError("bundle_manifest_invalid", "relation source-bundle manifest is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise RelationSourceBundleError("bundle_manifest_invalid", "relation source-bundle manifest must be an object")
    if payload.get("contract_version") != RELATION_SOURCE_BUNDLE_CONTRACT_VERSION:
        raise RelationSourceBundleError("bundle_contract_mismatch", "relation source-bundle contract is not supported")
    for key in (
        "bundle_id", "source_name", "source_url", "license_spdx_or_text",
        "license_evidence_url", "release_or_retrieval_date", "transform_description",
    ):
        _required_text(payload, key, context="manifest")
    relation_snapshot = payload.get("relation_snapshot")
    if not isinstance(relation_snapshot, Mapping):
        raise RelationSourceBundleError("bundle_schema_invalid", "relation_snapshot is required")
    if relation_snapshot.get("schema_version") != RELATION_ROW_SCHEMA_VERSION:
        raise RelationSourceBundleError("relation_schema_version_mismatch", "relation snapshot schema version is not supported")
    relation_path = _trusted_file(
        root,
        relation_snapshot.get("relative_path"),
        relation_snapshot.get("sha256"),
        label="relation_snapshot",
    )
    rows = _read_relation_rows(relation_path)
    return RelationSourceBundle(
        bundle_id=_required_text(payload, "bundle_id", context="manifest"),
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        source_name=_required_text(payload, "source_name", context="manifest"),
        release_or_retrieval_date=_required_text(payload, "release_or_retrieval_date", context="manifest"),
        relation_path=relation_path,
        relation_rows=rows,
    )


def _diagnostic(code: str, detail: str) -> dict[str, Any]:
    return {
        "relation_importer_contract_version": RELATION_IMPORTER_CONTRACT_VERSION,
        "relation_bundle_status": "not_evaluable",
        "relation_bundle_error_code": code,
        "relation_bundle_error_detail": detail,
        "relation_class": R0_NOT_EVALUABLE,
        "relation_class_code": "R0",
        "promotion_guard": "curated_relation_evidence_cannot_create_or_rank_a_direct_kinase_edge_without_p3",
    }


def _p0_ready(record: Mapping[str, Any]) -> tuple[bool, str | None]:
    identity = record.get("identity_provenance") or {}
    if identity.get("protein_accession_status") != "single_accession_observed":
        return False, "p0_protein_accession_not_unique"
    if identity.get("reported_ptm_position_count") != 1:
        return False, "p0_reported_site_not_unique"
    if identity.get("phosphorylation_form_status") != "single_or_unspecified_modification":
        return False, "p0_multi_phosphorylated_precursor"
    if identity.get("localization_status") != "recorded_class_I_or_higher":
        return False, "p0_localization_not_class_I"
    return True, None


def _p1_exact_target(record: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    mapping = record.get("mapping_evidence") or {}
    if mapping.get("mapping_class_code") != "M1":
        return None, "p1_mapping_is_not_M1_exact_sequence_site"
    target = mapping.get("target") or {}
    accession = _normalized_accession(target.get("target_relation_accession") or target.get("target_accession"))
    taxonomy = _positive_int(target.get("taxonomy_id"))
    relation_sequence_id = _text(target.get("target_relation_isoform_or_sequence_id"))
    if not accession or not taxonomy or not relation_sequence_id:
        return None, "p1_target_relation_identity_not_source_versioned"
    return {
        "accession": accession,
        "taxonomy_id": taxonomy,
        "isoform_or_sequence_id": relation_sequence_id,
    }, None


def _record_relation(
    *,
    relation_class: str,
    status: str,
    bundle: RelationSourceBundle | None,
    reason: str | None = None,
    candidates: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    candidate_rows = [dict(row) for row in candidates]
    code = relation_class.split("_", 1)[0]
    result: dict[str, Any] = {
        "relation_importer_contract_version": RELATION_IMPORTER_CONTRACT_VERSION,
        "relation_bundle_status": "validated" if bundle else "not_evaluable",
        "relation_bundle_id": bundle.bundle_id if bundle else None,
        "relation_bundle_sha256": bundle.manifest_sha256 if bundle else None,
        "relation_class": relation_class,
        "relation_class_code": code,
        "relation_status": status,
        "candidate_count": len(candidate_rows),
        "promotion_guard": "curated_relation_evidence_cannot_create_or_rank_a_direct_kinase_edge_without_p3",
    }
    if reason:
        result["reason"] = reason
    if candidate_rows:
        result["candidate_edges"] = candidate_rows
    return result


def _map_relation(record: Mapping[str, Any], bundle: RelationSourceBundle, index: Mapping[tuple[str, int, str, int, str], tuple[Mapping[str, Any], ...]]) -> dict[str, Any]:
    ready, p0_reason = _p0_ready(record)
    if not ready:
        return _record_relation(relation_class=R1_INELIGIBLE, status="p0_readiness_not_eligible_for_exact_relation_join", bundle=bundle, reason=p0_reason)
    target, p1_reason = _p1_exact_target(record)
    if target is None:
        return _record_relation(relation_class=R1_INELIGIBLE, status="p1_mapping_not_eligible_for_exact_relation_join", bundle=bundle, reason=p1_reason)
    positions = list((record.get("identity_provenance") or {}).get("all_reported_ptm_positions") or [])
    position_token = _text(positions[0]) if positions else ""
    residue = position_token[:1].upper()
    site = _positive_int(position_token[1:])
    if residue not in {"S", "T", "Y"} or not site:
        return _record_relation(relation_class=R1_INELIGIBLE, status="p0_site_token_not_joinable", bundle=bundle, reason="p0_reported_site_invalid")
    key = (target["accession"], target["taxonomy_id"], residue, site, target["isoform_or_sequence_id"])
    candidates = list(index.get(key, ()))
    if not candidates:
        return _record_relation(relation_class=R2_NO_EXACT_EDGE, status="no_exact_local_curated_relation_edge", bundle=bundle)
    kinase_identities = {(row["kinase_accession"], row["kinase_taxonomy_id"]) for row in candidates}
    if len(kinase_identities) != len(candidates):
        return _record_relation(relation_class=R4_CONFLICTING, status="conflicting_duplicate_kinase_candidates_after_bundle_validation", bundle=bundle, candidates=candidates)
    return _record_relation(
        relation_class=R3_CANDIDATE_SET,
        status="relation_supported_candidate_set_pending_p3",
        bundle=bundle,
        candidates=candidates,
    )


def map_feature_relations(
    ledger: Mapping[str, Any],
    *,
    manifest_path: str | Path | None = None,
    snapshot_root: str | Path | None = None,
) -> dict[str, Any]:
    """Map only P0-ready, P1-M1 features to a local curated relation snapshot."""

    records = [record for record in ledger.get("feature_records") or [] if isinstance(record, Mapping)]
    if manifest_path is None or snapshot_root is None:
        diagnostic = _diagnostic("relation_source_bundle_not_supplied", "no local curated relation source bundle was supplied")
        return {**diagnostic, "feature_relations": {str(row.get("feature_id")): dict(diagnostic) for row in records if row.get("feature_id")}}
    try:
        bundle = load_relation_source_bundle(manifest_path, snapshot_root=snapshot_root)
    except RelationSourceBundleError as error:
        diagnostic = _diagnostic(error.code, error.detail)
        return {**diagnostic, "feature_relations": {str(row.get("feature_id")): dict(diagnostic) for row in records if row.get("feature_id")}}
    index: dict[tuple[str, int, str, int, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in bundle.relation_rows:
        key = _row_join_key(row)[:5]
        index[key].append(row)
    return {
        "relation_importer_contract_version": RELATION_IMPORTER_CONTRACT_VERSION,
        "relation_bundle_status": "validated",
        "relation_bundle_id": bundle.bundle_id,
        "relation_bundle_sha256": bundle.manifest_sha256,
        "relation_bundle_source_name": bundle.source_name,
        "relation_bundle_release_or_retrieval_date": bundle.release_or_retrieval_date,
        "feature_relations": {
            str(row.get("feature_id")): _map_relation(row, bundle, index)
            for row in records if row.get("feature_id")
        },
    }


def compact_relation_summary(relation_context: Mapping[str, Any], feature_records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return aggregate-only P2 readiness allowed in Report/RAG handoff."""

    counts = Counter(
        _text((row.get("relation_evidence") or {}).get("relation_class_code")) or "R0"
        for row in feature_records
    )
    return {
        "relation_importer_contract_version": RELATION_IMPORTER_CONTRACT_VERSION,
        "relation_bundle_status": relation_context.get("relation_bundle_status", "not_evaluable"),
        "relation_bundle_sha256": relation_context.get("relation_bundle_sha256"),
        "relation_bundle_error_code": relation_context.get("relation_bundle_error_code"),
        "relation_class_counts": {code: counts.get(code, 0) for code in ("R0", "R1", "R2", "R3", "R4")},
        "direct_kinase_attribution_status": "no_call_candidate_set_requires_p3_allocation",
        "claim_boundary": "Relation readiness is aggregate-only provenance; it does not identify one kinase, establish direct regulation, or support causal/perturbation claims.",
        "excluded_fields": ["feature_id", "candidate_kinase", "accession", "sequence", "peptide", "coordinate", "isoform", "edge_id", "reference_id", "license_text", "source_file_path"],
    }


def attach_relation_evidence(ledger: Mapping[str, Any], relation_context: Mapping[str, Any]) -> dict[str, Any]:
    """Attach P2 candidate provenance while preserving direct kinase no-call."""

    result = {key: value for key, value in dict(ledger).items() if key not in {"feature_records", "summary"}}
    relations = relation_context.get("feature_relations") or {}
    records: list[dict[str, Any]] = []
    for raw_record in ledger.get("feature_records") or []:
        record = dict(raw_record)
        evidence = dict(relations.get(str(record.get("feature_id"))) or _diagnostic("relation_result_missing", "no feature-level relation result was emitted"))
        record["relation_evidence"] = evidence
        masks = dict(record.get("unmatched_reason_masks") or {})
        code = evidence.get("relation_class_code")
        masks["F4_exact_mapping_success_but_no_curated_kinase_edge"] = {
            "R0": "not_evaluable_missing_or_incompatible_curated_relation_snapshot",
            "R1": "feature_or_mapping_not_eligible_for_exact_curated_relation_join",
            "R2": "no_exact_curated_relation_edge",
            "R3": "exact_curated_candidate_set_present_pending_p3",
            "R4": "conflicting_or_ambiguous_curated_relation_edge",
        }.get(code, "not_evaluable_missing_relation_result")
        masks["F7_multiple_candidate_kinases_prevent_single_attribution"] = (
            "flagged_candidate_set_requires_p3_allocation"
            if code == "R3" else "not_assessed_or_no_exact_candidate_set"
        )
        masks["F8_direct_match_success"] = "not_assessed_p3_allocation_not_implemented"
        record["unmatched_reason_masks"] = masks
        direct = dict(record.get("direct_kinase_attribution") or {})
        reasons = [
            reason for reason in direct.get("reasons") or []
            if reason not in {"curated_kinase_edge_provenance_absent", "feature_level_exact_mapping_and_curated_edge_provenance_absent"}
        ]
        reasons.append({
            "R0": "curated_relation_snapshot_not_evaluable",
            "R1": "feature_or_M1_mapping_ineligible_for_curated_relation_join",
            "R2": "exact_curated_kinase_edge_not_found",
            "R3": "curated_kinase_candidate_set_requires_p3_allocation_policy",
            "R4": "curated_kinase_edge_conflicting_or_ambiguous",
        }.get(code, "curated_relation_result_not_evaluable"))
        direct["status"] = "no_call"
        direct["evidence_tier"] = "E_direct_kinase_no_call"
        direct["reasons"] = sorted(set(reasons))
        direct["promotion_guard"] = "p0_p1_p2_tmm_rag_llm_cannot_promote_direct_kinase_evidence_tier_without_p3"
        record["direct_kinase_attribution"] = direct
        records.append(record)
    result["feature_records"] = records
    result["relation_importer"] = {key: value for key, value in relation_context.items() if key != "feature_relations"}
    result["relation_importer"]["compact_summary"] = compact_relation_summary(relation_context, records)
    from ptm_shared.kinase_evidence_ledger import compact_summary

    result["summary"] = compact_summary(result)
    return result


__all__ = [
    "RELATION_IMPORTER_CONTRACT_VERSION", "RELATION_SOURCE_BUNDLE_CONTRACT_VERSION", "RELATION_ROW_SCHEMA_VERSION",
    "R0_NOT_EVALUABLE", "R1_INELIGIBLE", "R2_NO_EXACT_EDGE", "R3_CANDIDATE_SET", "R4_CONFLICTING",
    "RelationSourceBundleError", "attach_relation_evidence", "compact_relation_summary",
    "load_relation_source_bundle", "map_feature_relations",
]
