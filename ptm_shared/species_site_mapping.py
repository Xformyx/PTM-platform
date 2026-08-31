"""Local, versioned species/site mapping provenance for PTM-Vector P1.

This module is deliberately a mapper rather than a kinase attribution engine.
It accepts only local, checksum-validated source bundles and never imports
network clients, a kinase-relation registry, benchmark truth, RAG, or an LLM.
Its M0--M4 records are full-sidecar provenance; callers must use
``compact_mapping_summary`` for Report/RAG handoff.
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


MAPPING_IMPORTER_CONTRACT_VERSION = "ptm_species_site_mapping.v1"
SOURCE_BUNDLE_CONTRACT_VERSION = "ptm_species_site_mapping_source_bundle.v1"
M0_NOT_EVALUABLE = "M0_not_evaluable_missing_or_incompatible_snapshot"
M1_EXACT = "M1_exact_sequence_site"
M2_ALIGNED_ONE_TO_ONE = "M2_aligned_one_to_one_ortholog_site"
M3_GENE_ONLY = "M3_gene_only_context"
M4_UNMAPPED_OR_AMBIGUOUS = "M4_unmapped_or_ambiguous"
_POSITION_RE = re.compile(r"^([STY])(\d+)$", flags=re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CIGAR_RE = re.compile(r"(\d+)([MID])")


class MappingSourceBundleError(ValueError):
    """Raised only for invalid local mapping source-bundle provenance."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class FastaEntry:
    """Minimal local FASTA entry needed for deterministic coordinate checks."""

    primary_id: str
    accessions: tuple[str, ...]
    sequence: str
    taxonomy_id: int | None
    gene_symbol: str | None


@dataclass(frozen=True)
class FastaIndex:
    """Read-only indices for an already checksum-validated FASTA file."""

    by_accession: Mapping[str, tuple[FastaEntry, ...]]
    by_primary_id: Mapping[str, FastaEntry]
    by_sequence: Mapping[str, tuple[FastaEntry, ...]]


@dataclass(frozen=True)
class MappingSourceBundle:
    """Private runtime representation of a validated local source bundle."""

    bundle_id: str
    manifest_sha256: str
    source_taxonomy_id: int
    target_taxonomy_id: int
    analysis_fasta: Path
    reference_fastas: Mapping[int, Path]
    orthology_path: Path
    release: str
    orthology_rows: tuple[Mapping[str, Any], ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _required_text(container: Mapping[str, Any], key: str, *, context: str) -> str:
    value = str(container.get(key) or "").strip()
    if not value:
        raise MappingSourceBundleError("required_field_missing", f"{context}.{key} is required")
    return value


def _trusted_file(root: Path, relative_path: Any, expected_sha256: Any, *, label: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise MappingSourceBundleError("required_file_path_missing", f"{label}.relative_path is required")
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise MappingSourceBundleError("absolute_path_disallowed", f"{label} must be relative to snapshot root")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved_root != resolved and resolved_root not in resolved.parents:
        raise MappingSourceBundleError("snapshot_path_escape", f"{label} escapes snapshot root")
    expected = str(expected_sha256 or "").lower()
    if not _SHA256_RE.fullmatch(expected):
        raise MappingSourceBundleError("invalid_sha256", f"{label}.sha256 must be a lowercase SHA-256")
    if not resolved.is_file():
        raise MappingSourceBundleError("snapshot_file_missing", f"{label} is not present beneath snapshot root")
    if _sha256(resolved) != expected:
        raise MappingSourceBundleError("snapshot_sha256_mismatch", f"{label} SHA-256 does not match manifest")
    return resolved


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open("r", encoding="utf-8")


def _entry_from_header(header: str, sequence: str) -> FastaEntry:
    text = header.strip().lstrip(">")
    first = text.split(maxsplit=1)[0] if text else ""
    pipe = first.split("|")
    primary = pipe[1] if len(pipe) >= 2 and pipe[0].lower() in {"sp", "tr"} else first
    accessions = {primary.upper(), first.upper()}
    if len(pipe) >= 3:
        accessions.add(pipe[2].upper())
    for token in re.findall(r"(?:accession|protein_id):([^\s;]+)", text, flags=re.IGNORECASE):
        accessions.add(token.upper())
    taxonomy_match = re.search(r"(?:OX=|taxonomy:)(\d+)", text, flags=re.IGNORECASE)
    gene_match = re.search(r"(?:GN=|gene:)([^\s;]+)", text, flags=re.IGNORECASE)
    return FastaEntry(
        primary_id=primary.upper(),
        accessions=tuple(sorted(accessions)),
        sequence=sequence.upper(),
        taxonomy_id=_int(taxonomy_match.group(1)) if taxonomy_match else None,
        gene_symbol=gene_match.group(1).upper() if gene_match else None,
    )


def _load_fasta_index(path: Path) -> FastaIndex:
    by_accession: dict[str, list[FastaEntry]] = defaultdict(list)
    by_primary: dict[str, FastaEntry] = {}
    by_sequence: dict[str, list[FastaEntry]] = defaultdict(list)
    header: str | None = None
    sequence_parts: list[str] = []

    def emit() -> None:
        if header is None:
            return
        sequence = "".join(sequence_parts).strip().upper()
        if not sequence:
            return
        entry = _entry_from_header(header, sequence)
        by_primary[entry.primary_id] = entry
        for accession in entry.accessions:
            by_accession[accession].append(entry)
        by_sequence[entry.sequence].append(entry)

    with _open_text(path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                emit()
                header = line
                sequence_parts = []
            else:
                sequence_parts.append(line)
    emit()
    return FastaIndex(
        by_accession={key: tuple(value) for key, value in by_accession.items()},
        by_primary_id=by_primary,
        by_sequence={key: tuple(value) for key, value in by_sequence.items()},
    )


def _read_orthology_rows(path: Path) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    required = {
        "source_ensembl_gene_id", "target_ensembl_gene_id",
        "source_ensembl_protein_id", "target_ensembl_protein_id",
        "homology_type", "is_high_confidence",
        "source_taxonomy_id", "target_taxonomy_id",
        "source_sequence", "target_sequence",
        "source_aligned", "target_aligned", "cigar_line",
    }
    with _open_text(path) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise MappingSourceBundleError("orthology_snapshot_invalid_json", f"orthology row {line_number} is not JSON") from error
            if not isinstance(row, Mapping) or required - set(row):
                raise MappingSourceBundleError("orthology_snapshot_schema_invalid", f"orthology row {line_number} misses required fields")
            rows.append(dict(row))
    return tuple(rows)


def load_mapping_source_bundle(
    manifest_path: str | Path,
    *,
    snapshot_root: str | Path,
) -> MappingSourceBundle:
    """Load a fully local source bundle or raise a machine-readable validation error."""

    root = Path(snapshot_root)
    manifest = Path(manifest_path)
    if not root.is_dir():
        raise MappingSourceBundleError("snapshot_root_missing", "mapping snapshot root is not available")
    if not manifest.is_file():
        raise MappingSourceBundleError("bundle_manifest_missing", "mapping source-bundle manifest is not available")
    resolved_root = root.resolve()
    resolved_manifest = manifest.resolve()
    if resolved_root != resolved_manifest and resolved_root not in resolved_manifest.parents:
        raise MappingSourceBundleError("bundle_manifest_outside_snapshot_root", "mapping source-bundle manifest must reside beneath snapshot root")
    try:
        raw_manifest = manifest.read_bytes()
        payload = json.loads(raw_manifest.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MappingSourceBundleError("bundle_manifest_invalid", "mapping source-bundle manifest is not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise MappingSourceBundleError("bundle_manifest_invalid", "mapping source-bundle manifest must be an object")
    if payload.get("contract_version") != SOURCE_BUNDLE_CONTRACT_VERSION:
        raise MappingSourceBundleError("bundle_contract_mismatch", "mapping source-bundle contract is not supported")

    analysis = payload.get("analysis_reference")
    references = payload.get("reference_fastas")
    orthology = payload.get("orthology_snapshot")
    if not isinstance(analysis, Mapping) or not isinstance(references, Mapping) or not isinstance(orthology, Mapping):
        raise MappingSourceBundleError("bundle_schema_invalid", "analysis reference, reference FASTAs and orthology snapshot are required")
    source_taxonomy_id = _int(orthology.get("source_taxonomy_id"))
    target_taxonomy_id = _int(orthology.get("target_taxonomy_id"))
    if not source_taxonomy_id or not target_taxonomy_id or source_taxonomy_id == target_taxonomy_id:
        raise MappingSourceBundleError("bundle_taxonomy_invalid", "orthology source and target taxonomy IDs must be distinct integers")
    release = _required_text(orthology, "release", context="orthology_snapshot")
    analysis_path = _trusted_file(root, analysis.get("relative_path"), analysis.get("sha256"), label="analysis_reference")
    reference_paths: dict[int, Path] = {}
    for label, reference in references.items():
        if not isinstance(reference, Mapping):
            raise MappingSourceBundleError("reference_schema_invalid", f"reference_fastas.{label} must be an object")
        taxon = _int(reference.get("taxonomy_id"))
        if not taxon:
            raise MappingSourceBundleError("reference_taxonomy_missing", f"reference_fastas.{label}.taxonomy_id is required")
        if str(reference.get("release") or "") != release:
            raise MappingSourceBundleError("reference_release_mismatch", f"reference_fastas.{label} release differs from orthology snapshot")
        reference_paths[taxon] = _trusted_file(root, reference.get("relative_path"), reference.get("sha256"), label=f"reference_fastas.{label}")
    if source_taxonomy_id not in reference_paths or target_taxonomy_id not in reference_paths:
        raise MappingSourceBundleError("required_reference_missing", "source and target reference FASTAs are both required")
    orthology_path = _trusted_file(root, orthology.get("relative_path"), orthology.get("sha256"), label="orthology_snapshot")
    rows = _read_orthology_rows(orthology_path)
    for row in rows:
        if _int(row.get("source_taxonomy_id")) != source_taxonomy_id or _int(row.get("target_taxonomy_id")) != target_taxonomy_id:
            raise MappingSourceBundleError("orthology_taxonomy_mismatch", "orthology row taxonomy differs from bundle manifest")
    return MappingSourceBundle(
        bundle_id=_required_text(payload, "bundle_id", context="manifest"),
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        source_taxonomy_id=source_taxonomy_id,
        target_taxonomy_id=target_taxonomy_id,
        analysis_fasta=analysis_path,
        reference_fastas=reference_paths,
        orthology_path=orthology_path,
        release=release,
        orthology_rows=rows,
    )


def _bundle_diagnostic(code: str, detail: str) -> dict[str, Any]:
    return {
        "mapping_importer_contract_version": MAPPING_IMPORTER_CONTRACT_VERSION,
        "mapping_bundle_status": "not_evaluable",
        "mapping_bundle_error_code": code,
        "mapping_bundle_error_detail": detail,
        "mapping_class": M0_NOT_EVALUABLE,
        "mapping_class_code": "M0",
    }


def _position(record: Mapping[str, Any]) -> tuple[str, int] | None:
    identity = record.get("identity_provenance") or {}
    tokens = list(identity.get("all_reported_ptm_positions") or [])
    if len(tokens) != 1:
        return None
    matched = _POSITION_RE.fullmatch(str(tokens[0]).strip())
    return (matched.group(1).upper(), int(matched.group(2))) if matched else None


def _feature_gene(record: Mapping[str, Any]) -> str:
    aggregate = str(record.get("nominal_aggregate_key") or "")
    return aggregate.rsplit("_", 1)[0].upper() if "_" in aggregate else ""


def _normalized_peptide(record: Mapping[str, Any]) -> str:
    sequence = str((record.get("identity_provenance") or {}).get("modified_sequence") or "")
    sequence = re.sub(r"\([^)]*\)", "", sequence)
    sequence = re.sub(r"\[[^\]]*\]", "", sequence)
    return "".join(re.findall(r"[A-Za-z]", sequence)).upper()


def _peptide_window_verified(sequence: str, peptide: str, position: int, residue: str) -> bool:
    if not peptide:
        return False
    start = 0
    while True:
        found = sequence.find(peptide, start)
        if found < 0:
            return False
        for index, amino_acid in enumerate(peptide, start=1):
            if found + index == position and amino_acid == residue:
                return True
        start = found + 1


def _unique_entries(entries: Iterable[FastaEntry]) -> tuple[FastaEntry, ...]:
    unique = {entry.primary_id: entry for entry in entries}
    return tuple(unique[key] for key in sorted(unique))


def _reference_entry(index: FastaIndex, primary_id: Any) -> FastaEntry | None:
    key = str(primary_id or "").strip().upper()
    return index.by_primary_id.get(key)


def _validate_alignment(row: Mapping[str, Any]) -> bool:
    source = str(row.get("source_sequence") or "").upper()
    target = str(row.get("target_sequence") or "").upper()
    source_aligned = str(row.get("source_aligned") or "").upper()
    target_aligned = str(row.get("target_aligned") or "").upper()
    cigar = str(row.get("cigar_line") or "")
    if not source or not target or len(source_aligned) != len(target_aligned):
        return False
    if source_aligned.replace("-", "") != source or target_aligned.replace("-", "") != target:
        return False
    operations = _CIGAR_RE.findall(cigar)
    return bool(operations) and "".join(f"{n}{op}" for n, op in operations) == cigar and sum(int(n) for n, _ in operations) == len(source_aligned)


def _aligned_target_position(row: Mapping[str, Any], source_position: int) -> tuple[int, str, str] | None:
    source_aligned = str(row.get("source_aligned") or "").upper()
    target_aligned = str(row.get("target_aligned") or "").upper()
    source_count = 0
    target_count = 0
    for source_residue, target_residue in zip(source_aligned, target_aligned):
        if source_residue != "-":
            source_count += 1
        if target_residue != "-":
            target_count += 1
        if source_count == source_position and source_residue != "-":
            if target_residue == "-":
                return None
            return target_count, source_residue, target_residue
    return None


def _record_mapping(
    *,
    mapping_class: str,
    status: str,
    bundle: MappingSourceBundle | None,
    source: Mapping[str, Any] | None = None,
    target: Mapping[str, Any] | None = None,
    orthology: Mapping[str, Any] | None = None,
    reason: str | None = None,
    candidate_count: int | None = None,
) -> dict[str, Any]:
    code = mapping_class.split("_", 1)[0]
    result: dict[str, Any] = {
        "mapping_importer_contract_version": MAPPING_IMPORTER_CONTRACT_VERSION,
        "mapping_bundle_status": "validated" if bundle else "not_evaluable",
        "mapping_bundle_id": bundle.bundle_id if bundle else None,
        "mapping_bundle_sha256": bundle.manifest_sha256 if bundle else None,
        "mapping_class": mapping_class,
        "mapping_class_code": code,
        "mapping_status": status,
        "promotion_guard": "mapping_evidence_alone_cannot_create_or_rank_a_direct_kinase_edge",
    }
    if source:
        result["source"] = dict(source)
    if target:
        result["target"] = dict(target)
    if orthology:
        result["orthology"] = dict(orthology)
    if reason:
        result["reason"] = reason
    if candidate_count is not None:
        result["candidate_count"] = candidate_count
    return result


def _map_feature(record: Mapping[str, Any], bundle: MappingSourceBundle, indices: Mapping[Any, FastaIndex]) -> dict[str, Any]:
    identity = record.get("identity_provenance") or {}
    accessions = [str(value).upper() for value in identity.get("protein_accession_tokens") or [] if str(value).strip()]
    position = _position(record)
    if len(accessions) != 1:
        return _record_mapping(mapping_class=M4_UNMAPPED_OR_AMBIGUOUS, status="unmapped_no_unique_source_accession", bundle=bundle, reason="source_accession_missing_or_ambiguous")
    if position is None:
        return _record_mapping(mapping_class=M4_UNMAPPED_OR_AMBIGUOUS, status="unmapped_no_unique_reported_site", bundle=bundle, reason="reported_site_missing_or_ambiguous")
    source_candidates = _unique_entries(indices["analysis"].by_accession.get(accessions[0], ()))
    if len(source_candidates) != 1:
        return _record_mapping(mapping_class=M4_UNMAPPED_OR_AMBIGUOUS, status="unmapped_source_accession_not_unique_in_analysis_fasta", bundle=bundle, reason="analysis_fasta_source_entry_missing_or_ambiguous", candidate_count=len(source_candidates))
    source_entry = source_candidates[0]
    declared_taxon = _int(identity.get("fasta_taxonomy_id"))
    source_taxon = source_entry.taxonomy_id or declared_taxon or bundle.source_taxonomy_id
    residue, source_position = position
    peptide = _normalized_peptide(record)
    source_ok = (
        0 < source_position <= len(source_entry.sequence)
        and source_entry.sequence[source_position - 1] == residue
        and _peptide_window_verified(source_entry.sequence, peptide, source_position, residue)
    )
    source_summary = {
        "analysis_accession": accessions[0],
        "fasta_taxonomy_id": source_taxon,
        "residue": residue,
        "position": source_position,
        "sequence_verified": source_ok,
        "peptide_window_verified": source_ok,
    }
    if not source_ok:
        return _record_mapping(mapping_class=M4_UNMAPPED_OR_AMBIGUOUS, status="unmapped_source_residue_or_peptide_not_verified", bundle=bundle, source=source_summary, reason="source_sequence_site_verification_failed")
    if declared_taxon and source_entry.taxonomy_id and declared_taxon != source_entry.taxonomy_id:
        return _record_mapping(mapping_class=M4_UNMAPPED_OR_AMBIGUOUS, status="unmapped_source_taxonomy_conflict", bundle=bundle, source=source_summary, reason="feature_and_analysis_fasta_taxonomy_conflict")

    # A deliberate human transgene remains a human source. It is not routed
    # through rat-to-human orthology merely because the order is rat.
    if source_taxon == bundle.target_taxonomy_id:
        return _record_mapping(
            mapping_class=M1_EXACT,
            status="exact_same_species_analysis_source_site_verified",
            bundle=bundle,
            source=source_summary,
            target={
                "taxonomy_id": source_taxon,
                "target_accession": accessions[0],
                "residue": residue,
                "position": source_position,
                "sequence_verified": True,
            },
            reason="same_species_explicit_analysis_fasta_entry",
        )
    target_identical = _unique_entries(indices[bundle.target_taxonomy_id].by_sequence.get(source_entry.sequence, ()))
    if len(target_identical) == 1:
        target_entry = target_identical[0]
        return _record_mapping(
            mapping_class=M1_EXACT,
            status="exact_source_target_sequence_site_verified",
            bundle=bundle,
            source=source_summary,
            target={
                "taxonomy_id": bundle.target_taxonomy_id,
                "ensembl_protein_id": target_entry.primary_id,
                "residue": residue,
                "position": source_position,
                "sequence_verified": True,
            },
        )

    gene_candidate_rows = [
        row for row in bundle.orthology_rows
        if str(row.get("source_gene_symbol") or "").upper() == _feature_gene(record)
    ]
    candidate_rows: list[Mapping[str, Any]] = []
    for row in bundle.orthology_rows:
        if str(row.get("source_sequence") or "").upper() != source_entry.sequence:
            continue
        source_reference = _reference_entry(indices[bundle.source_taxonomy_id], row.get("source_ensembl_protein_id"))
        target_reference = _reference_entry(indices[bundle.target_taxonomy_id], row.get("target_ensembl_protein_id"))
        if not source_reference or not target_reference:
            continue
        if source_reference.sequence != source_entry.sequence or target_reference.sequence != str(row.get("target_sequence") or "").upper():
            continue
        candidate_rows.append(row)
    mapped_m2: list[tuple[Mapping[str, Any], int]] = []
    for row in candidate_rows:
        if row.get("homology_type") != "ortholog_one2one" or row.get("is_high_confidence") is not True or not _validate_alignment(row):
            continue
        aligned = _aligned_target_position(row, source_position)
        if not aligned:
            continue
        target_position, source_residue, target_residue = aligned
        if source_residue != residue or target_residue != residue:
            continue
        mapped_m2.append((row, target_position))
    unique_m2 = {
        (str(row.get("target_ensembl_protein_id")), target_position): (row, target_position)
        for row, target_position in mapped_m2
    }
    if len(unique_m2) == 1:
        row, target_position = next(iter(unique_m2.values()))
        return _record_mapping(
            mapping_class=M2_ALIGNED_ONE_TO_ONE,
            status="mapped_context_only_no_direct_edge_promotion",
            bundle=bundle,
            source=source_summary,
            target={
                "taxonomy_id": bundle.target_taxonomy_id,
                "ensembl_protein_id": str(row.get("target_ensembl_protein_id")),
                "residue": residue,
                "position": target_position,
                "sequence_verified": True,
            },
            orthology={
                "homology_type": "ortholog_one2one",
                "high_confidence": True,
                "aligned_residue_verified": True,
            },
        )
    if len(unique_m2) > 1:
        return _record_mapping(mapping_class=M4_UNMAPPED_OR_AMBIGUOUS, status="ambiguous_multiple_site_verified_ortholog_targets", bundle=bundle, source=source_summary, reason="multiple_equally_eligible_target_sites", candidate_count=len(unique_m2))

    target_genes = {
        str(row.get("target_ensembl_gene_id"))
        for row in gene_candidate_rows
        if str(row.get("target_ensembl_gene_id") or "").strip()
    }
    if len(target_genes) == 1:
        target_gene = next(iter(target_genes))
        return _record_mapping(
            mapping_class=M3_GENE_ONLY,
            status="gene_context_only_no_direct_edge_promotion",
            bundle=bundle,
            source=source_summary,
            target={"taxonomy_id": bundle.target_taxonomy_id, "ensembl_gene_id": target_gene},
            orthology={"aligned_residue_verified": False},
            reason="site_mapping_not_verified_but_unique_gene_context_available",
        )
    return _record_mapping(mapping_class=M4_UNMAPPED_OR_AMBIGUOUS, status="unmapped_no_eligible_site_or_gene_context", bundle=bundle, source=source_summary, reason="no_unique_site_or_gene_mapping_candidate", candidate_count=len(gene_candidate_rows))


def map_feature_records(
    ledger: Mapping[str, Any],
    *,
    manifest_path: str | Path | None = None,
    snapshot_root: str | Path | None = None,
) -> dict[str, Any]:
    """Map P0 feature records from a local bundle or emit an explicit M0 result."""

    records = [record for record in ledger.get("feature_records") or [] if isinstance(record, Mapping)]
    if manifest_path is None or snapshot_root is None:
        diagnostic = _bundle_diagnostic("mapping_source_bundle_not_supplied", "no local mapping source bundle was supplied")
        return {
            **diagnostic,
            "feature_mappings": {str(record.get("feature_id")): dict(diagnostic) for record in records if record.get("feature_id")},
        }
    try:
        bundle = load_mapping_source_bundle(manifest_path, snapshot_root=snapshot_root)
        indices: dict[Any, FastaIndex] = {"analysis": _load_fasta_index(bundle.analysis_fasta)}
        for taxon, path in bundle.reference_fastas.items():
            indices[taxon] = _load_fasta_index(path)
    except MappingSourceBundleError as error:
        diagnostic = _bundle_diagnostic(error.code, error.detail)
        return {
            **diagnostic,
            "feature_mappings": {str(record.get("feature_id")): dict(diagnostic) for record in records if record.get("feature_id")},
        }
    feature_mappings = {
        str(record.get("feature_id")): _map_feature(record, bundle, indices)
        for record in records
        if record.get("feature_id")
    }
    return {
        "mapping_importer_contract_version": MAPPING_IMPORTER_CONTRACT_VERSION,
        "mapping_bundle_status": "validated",
        "mapping_bundle_id": bundle.bundle_id,
        "mapping_bundle_sha256": bundle.manifest_sha256,
        "mapping_bundle_release": bundle.release,
        "feature_mappings": feature_mappings,
    }


def compact_mapping_summary(mapping_context: Mapping[str, Any], feature_records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return aggregate-only mapping readiness suitable for Report/RAG handoff."""

    counts = Counter()
    for record in feature_records:
        evidence = record.get("mapping_evidence") or {}
        code = str(evidence.get("mapping_class_code") or "M0")
        counts[code] += 1
    return {
        "mapping_importer_contract_version": MAPPING_IMPORTER_CONTRACT_VERSION,
        "mapping_bundle_status": mapping_context.get("mapping_bundle_status", "not_evaluable"),
        "mapping_bundle_sha256": mapping_context.get("mapping_bundle_sha256"),
        "mapping_bundle_error_code": mapping_context.get("mapping_bundle_error_code"),
        "mapping_class_counts": {code: counts.get(code, 0) for code in ("M0", "M1", "M2", "M3", "M4")},
        "direct_kinase_attribution_status": "no_call_without_p2_curated_edge_and_p0_readiness",
        "claim_boundary": "Mapping-class counts are provenance only and do not identify a kinase or establish a direct relation.",
        "excluded_fields": ["feature_id", "accession", "sequence", "peptide", "coordinate", "orthology_ids", "source_file_path"],
    }


def attach_mapping_context(ledger: Mapping[str, Any], mapping_context: Mapping[str, Any]) -> dict[str, Any]:
    """Attach M0--M4 evidence without changing the P0 direct-kinase no-call tier."""

    result = {key: value for key, value in dict(ledger).items() if key not in {"feature_records", "summary"}}
    mappings = mapping_context.get("feature_mappings") or {}
    records: list[dict[str, Any]] = []
    for raw_record in ledger.get("feature_records") or []:
        record = dict(raw_record)
        mapping = dict(mappings.get(str(record.get("feature_id"))) or _bundle_diagnostic("mapping_result_missing", "no feature-level mapping result was emitted"))
        evidence = dict(record.get("mapping_evidence") or {})
        evidence.update(mapping)
        record["mapping_evidence"] = evidence
        masks = dict(record.get("unmatched_reason_masks") or {})
        mapping_code = mapping.get("mapping_class_code")
        masks["F3_rat_to_human_exact_sequence_site_mapping_failure"] = {
            "M0": "not_evaluable_missing_or_incompatible_mapping_snapshot",
            "M1": "passed_exact_sequence_site_mapping",
            "M2": "mapped_aligned_one_to_one_ortholog_context_only",
            "M3": "mapped_gene_only_context_not_direct",
            "M4": "flagged_unmapped_or_ambiguous",
        }.get(mapping_code, "not_evaluable_missing_mapping_result")
        record["unmatched_reason_masks"] = masks
        direct = dict(record.get("direct_kinase_attribution") or {})
        reasons = [reason for reason in direct.get("reasons") or [] if reason != "feature_level_exact_mapping_and_curated_edge_provenance_absent"]
        if mapping_code == "M1":
            reasons.append("curated_kinase_edge_provenance_absent")
        elif mapping_code == "M2":
            reasons.append("aligned_ortholog_context_does_not_permit_direct_kinase_attribution")
        elif mapping_code == "M3":
            reasons.append("gene_only_context_does_not_permit_direct_kinase_attribution")
        elif mapping_code == "M4":
            reasons.append("feature_level_mapping_unmapped_or_ambiguous")
        else:
            reasons.append("feature_level_mapping_not_evaluable")
        direct["status"] = "no_call"
        direct["evidence_tier"] = "E_direct_kinase_no_call"
        direct["reasons"] = sorted(set(reasons))
        direct["promotion_guard"] = "tmm_rag_llm_and_mapping_context_cannot_promote_direct_kinase_evidence_tier"
        record["direct_kinase_attribution"] = direct
        records.append(record)
    result["feature_records"] = records
    result["mapping_importer"] = {
        key: value
        for key, value in mapping_context.items()
        if key != "feature_mappings"
    }
    result["mapping_importer"]["compact_summary"] = compact_mapping_summary(mapping_context, records)
    from ptm_shared.kinase_evidence_ledger import compact_summary

    result["summary"] = compact_summary(result)
    return result


__all__ = [
    "MAPPING_IMPORTER_CONTRACT_VERSION",
    "SOURCE_BUNDLE_CONTRACT_VERSION",
    "M0_NOT_EVALUABLE",
    "M1_EXACT",
    "M2_ALIGNED_ONE_TO_ONE",
    "M3_GENE_ONLY",
    "M4_UNMAPPED_OR_AMBIGUOUS",
    "MappingSourceBundleError",
    "attach_mapping_context",
    "compact_mapping_summary",
    "load_mapping_source_bundle",
    "map_feature_records",
]
