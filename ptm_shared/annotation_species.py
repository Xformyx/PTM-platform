"""Explicit host and FASTA-native annotation scope; unknown is not mouse."""
import hashlib
import json
import re
from .species_registry import resolve_species_context

VERSION = "annotation_species.v2"
NAMES = {"9606": ("human", "Homo sapiens", "hsa"), "10090": ("mouse", "Mus musculus", "mmu"),
         "10116": ("rat", "Rattus norvegicus", "rno")}


def normalize_species(value):
    raw = str(value or "").strip().lower()
    for taxon, (name, scientific, _) in NAMES.items():
        if raw in {taxon, name, scientific.lower()}:
            return taxon
    if raw:
        try:
            return resolve_species_context(raw).taxonomy_id
        except ValueError:
            pass
    return None


def annotation_scope(row=None, context=None):
    row, context = row or {}, context or {}
    context = {**context, **(context.get("verified_metadata") or context.get("study_metadata_override") or {})}
    host = normalize_species(context.get("host_organism") or context.get("organism") or context.get("species"))
    raw = row.get("FASTA_Taxonomy_ID") or row.get("fasta_taxonomy_id") or row.get("FASTA_Organism") or row.get("fasta_organism") or ""
    parts = raw if isinstance(raw, list) else re.split(r"[;,]", str(raw))
    members = row.get("annotation_feature_provenance") or []
    if members:
        parts = ([part for member in members for part in re.split(r"[;,]", str(member.get("fasta_taxonomy_id") or "unknown")) if part]
                 if any(m.get("fasta_taxonomy_id") for m in members) else [])
    taxa = sorted({normalize_species(v) or "unknown" for v in parts if str(v).strip()})
    effective = taxa[0] if len(taxa) == 1 and taxa[0] != "unknown" else host if not taxa else None
    name, scientific, kegg = NAMES.get(effective, ("unknown", "unknown", None))
    result = {"schema_version": VERSION, "host_taxonomy_id": host,
              "transgene_species": context.get("transgene_species"),
              "feature_taxonomy_ids": taxa, "annotation_taxonomy_id": effective,
              "native_species": name, "scientific_name": scientific, "kegg_organism": kegg,
              "status": "mixed_or_ambiguous" if len(taxa) > 1 else "resolved" if effective else "unknown",
              "source": "fasta_native" if taxa else "explicit_study_metadata" if host else "unavailable",
              "accession_scope": sorted({str(m.get("protein_group") or "") for m in members}) if members else row.get("FASTA_Accession") or row.get("protein_group") or row.get("Protein.Group"),
              "isoform": row.get("isoform") or row.get("Isoform"),
              "database_version": context.get("annotation_database_version", "unavailable")}
    result["cache_namespace"] = VERSION + ":" + hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:20]
    return result


def audit_annotation_species(records, context):
    """Detect stale native annotations; ortholog context is a separate layer."""
    checked, mismatched, unresolved, examples = 0, 0, 0, []
    for row in records or []:
        if not isinstance(row, dict):
            continue
        rag = row.get("rag_enrichment") or {}
        native = row.get("native_species") or rag.get("native_species")
        stored_scope = row.get("annotation_species_scope") or rag.get("annotation_species_scope") or {}
        if not native and not rag and not stored_scope:
            continue
        checked += 1
        expected = annotation_scope(row, context)["annotation_taxonomy_id"]
        actual = stored_scope.get("annotation_taxonomy_id") or normalize_species(native)
        reason = "native_annotation_species_unresolved" if not actual or not expected else "native_annotation_species_mismatch" if str(actual) != str(expected) else None
        if reason:
            unresolved += reason.endswith("unresolved")
            mismatched += reason.endswith("mismatch")
            if len(examples) < 20:
                examples.append({"accession": row.get("FASTA_Accession") or row.get("Protein.Group"), "expected_taxon": expected, "annotation_taxon": actual, "reason": reason})
    return {"schema_version": VERSION, "checked_records": checked, "mismatched_records": mismatched,
            "unresolved_records": unresolved, "examples": examples,
            "status": "review_required" if mismatched or unresolved else "checked" if checked else "not_supplied"}
