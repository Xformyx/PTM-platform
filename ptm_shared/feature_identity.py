"""Canonical precursor identity shared by quantitation, time analysis and readers.

v2 includes charge and mapping scope. Old PF IDs are diagnostic aliases only:
consumers must rebuild cached evidence/figures instead of rebinding an old ID.
"""
import hashlib
import json

FEATURE_IDENTITY_VERSION = "precursor_identity.v2"
FIELDS = ("gene", "position", "precursor_id", "modified_sequence", "precursor_charge", "protein_group", "fasta_taxonomy_id", "isoform")
ALIASES = (
    ("gene", "Gene.Name", "gene_name"), ("position", "PTM_Position", "site"),
    ("precursor_id", "Precursor.Id", "PrecursorId", "source_feature_id"),
    ("modified_sequence", "Modified.Sequence", "ModifiedSequence"),
    ("precursor_charge", "Precursor.Charge", "PrecursorCharge", "charge"),
    ("protein_group", "Protein.Group", "Protein.Ids"),
    ("fasta_taxonomy_id", "FASTA_Taxonomy_ID", "Annotation_Species_Taxonomy_ID"),
    ("isoform", "Isoform"),
)


def _text(row, keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip().lower() not in {"", "nan", "null", "none", "na", "n/a"}:
            return str(value).strip()
    return ""


def feature_key(row):
    parts = [_text(row, keys) for keys in ALIASES]
    parts[:2] = [v.upper() for v in parts[:2]]
    if parts[4]:
        try:
            charge = float(parts[4])
            if charge.is_integer():
                parts[4] = str(int(charge))
        except ValueError:
            pass
    return tuple(parts)


def canonical_feature_identity(row):
    key = feature_key(row)
    complete = bool(key[2] or (key[3] and key[4]))
    digest = hashlib.sha256(json.dumps([FEATURE_IDENTITY_VERSION, key], separators=(",", ":")).encode()).hexdigest()[:20].upper()
    return {
        **dict(zip(FIELDS, key)), "feature_identity_version": FEATURE_IDENTITY_VERSION,
        "feature_id": f"FEATURE-{digest}" if complete else None,
        "reader_feature_id": f"PF-{digest[:8]}" if complete else None,
        "identity_complete_for_reader_cards": complete,
        "identity_withheld_reason": None if complete else "precursor_identity_unavailable",
        "legacy_reader_feature_id": "PF-" + hashlib.sha1("|".join(key[:4]).encode()).hexdigest()[:8].upper(),
        "identity_migration_policy": "rebuild_cached_evidence_no_implicit_legacy_id_rebinding",
    }


def reader_id(key):
    return "PF-" + hashlib.sha256(json.dumps([FEATURE_IDENTITY_VERSION, list(key)], separators=(",", ":")).encode()).hexdigest()[:8].upper()


def audit_feature_identities(rows):
    crosswalk, missing, variants = {}, [], {}
    for row in rows:
        identity = canonical_feature_identity(row)
        condition = str(row.get("condition") or row.get("Condition") or "")
        if not identity["feature_id"]:
            missing.append({"gene": identity["gene"], "position": identity["position"], "condition": condition,
                            "reason": identity["identity_withheld_reason"]})
            continue
        crosswalk.setdefault(identity["legacy_reader_feature_id"], set()).add(identity["feature_id"])
        key = (identity["feature_id"], condition)
        variants.setdefault(key, set()).add(json.dumps(row, sort_keys=True, default=str))
    return {"schema_version": FEATURE_IDENTITY_VERSION, "migration_policy": "rebuild_cached_evidence_no_implicit_legacy_id_rebinding",
            "unresolved_rows": sorted(missing, key=lambda r: (r["gene"], r["position"], r["condition"])),
            "legacy_crosswalk": {k: sorted(v) for k, v in sorted(crosswalk.items())},
            "ambiguous_legacy_ids": sorted(k for k, v in crosswalk.items() if len(v) > 1),
            "conflicting_feature_conditions": [{"feature_id": k[0], "condition": k[1], "variant_count": len(v)}
                                                for k, v in sorted(variants.items()) if len(v) > 1]}
