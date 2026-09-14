"""Canonical precursor identity shared by quantitation, time analysis and readers.

v2 includes charge and mapping scope. Old PF IDs are diagnostic aliases only:
consumers must rebuild cached evidence/figures instead of rebinding an old ID.

Reader display fields are a projection of the same precursor unit. They do not
merge distinct precursor forms or replace hidden binding identifiers.
"""
import hashlib
import json
import re
import string

FEATURE_IDENTITY_VERSION = "precursor_identity.v2"
READER_TECHNICAL_ID_LEAK_RE = re.compile(r"\b(?:PF-[A-F0-9]{8}|FEATURE-[A-F0-9]+)\b", re.I)
"""Public-prose leak detector for hidden feature identifiers.

구현 대상: docs/개발_업무지시서_연구자용_PTM_Report의_Identity_Projection·서사·생성.md §4.A-1
사전등록: 2026-09-14 표시 계약. 측정 착수 전 선언.
해석 한계: leak 부재는 관측 단위가 맞다는 증명이 아니다.
주장 금지: 식별자 비노출을 kinase 귀속 정확도로 해석하지 않는다.
"""
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


def project_reader_display_identity(
    row,
    *,
    reader_measurement_unit=None,
    disambiguator=None,
    gene_ambiguous=False,
):
    """Build the public reader label for one precursor without exposing PF/FEATURE IDs.

    구현 대상: docs/개발_업무지시서_연구자용_PTM_Report의_Identity_Projection·서사·생성.md §4.A-1
    사전등록: 2026-09-14 표시 계약. 측정 공식 변경 아님.
    해석 한계: gene/residue는 reader projection이며 서로 다른 precursor를 한 측정치로 합치지 않는다.
    주장 금지: 이 라벨로 localization 확실성, occupancy, 또는 kinase 귀속을 주장하지 않는다.
    """
    if isinstance(row, dict):
        key = feature_key(row)
        gene, position = key[0], key[1]
        if not gene:
            gene = str(row.get("gene") or "").strip().upper()
        if not position:
            position = str(row.get("position") or row.get("candidate_residue_annotation") or "").strip().upper()
    else:
        gene = str((row or ("",))[0] if row else "").strip().upper()
        position = str((row or ("", ""))[1] if row and len(row) > 1 else "").strip().upper()
    unit = str(reader_measurement_unit or "").strip()
    if gene_ambiguous or not gene or gene in {"?", "UNKNOWN", "UNMAPPED"}:
        label = "protein-group modified-precursor feature"
    elif unit == "localized_ptm_site_feature" and position:
        label = f"{gene} {position} phosphopeptide feature"
    elif position:
        label = f"{gene} modified-precursor feature annotated at {position}"
    else:
        label = f"{gene} modified-precursor feature"
    if disambiguator:
        label = f"{label} {disambiguator}"
    return label


def technical_crosswalk_reference(identity):
    """Full precursor/charge/source lookup retained for technical audit only."""
    record = dict(identity or {})
    return {
        "feature_id": record.get("feature_id"),
        "reader_feature_id": record.get("reader_feature_id"),
        "legacy_reader_feature_id": record.get("legacy_reader_feature_id"),
        "precursor_id": record.get("precursor_id") or record.get("source_feature_id"),
        "modified_sequence": record.get("modified_sequence"),
        "precursor_charge": record.get("precursor_charge"),
        "protein_group": record.get("protein_group"),
        "fasta_taxonomy_id": record.get("fasta_taxonomy_id"),
        "isoform": record.get("isoform"),
    }


def assign_local_disambiguators(identities):
    """Assign render-local form A/B labels when the same gene/residue has distinct precursors.

    The suffix is not a canonical identity. Distinct feature_id values stay unmerged.
    """
    groups = {}
    for identity in identities:
        record = dict(identity or {})
        gene = str(record.get("gene") or "").strip().upper()
        residue = str(record.get("candidate_residue_annotation") or record.get("position") or "").strip().upper()
        groups.setdefault((gene, residue), []).append(record)
    assigned = []
    for members in groups.values():
        distinct = []
        seen = set()
        for member in members:
            token = member.get("feature_id") or member.get("reader_feature_id") or json.dumps(
                [member.get("precursor_id"), member.get("modified_sequence"), member.get("precursor_charge")],
                separators=(",", ":"),
            )
            if token in seen:
                distinct.append((member, None))
                continue
            seen.add(token)
            distinct.append((member, token))
        unique_tokens = [token for _, token in distinct if token]
        use_forms = len(set(unique_tokens)) > 1
        form_by_token = {}
        next_index = 0
        for member, token in distinct:
            disambiguator = None
            if use_forms and token:
                if token not in form_by_token:
                    form_by_token[token] = f"form {string.ascii_uppercase[next_index % 26]}"
                    next_index += 1
                disambiguator = form_by_token[token]
            assigned.append({**member, "reader_disambiguator": disambiguator})
    return assigned


def scan_reader_technical_id_leaks(text):
    """Return public-prose PF/FEATURE leaks. Hidden IDs are valid in technical audit only."""
    return [match.group(0).upper() for match in READER_TECHNICAL_ID_LEAK_RE.finditer(str(text or ""))]


def canonical_feature_identity(row):
    key = feature_key(row)
    complete = bool(key[2] or (key[3] and key[4]))
    digest = hashlib.sha256(json.dumps([FEATURE_IDENTITY_VERSION, key], separators=(",", ":")).encode()).hexdigest()[:20].upper()
    unit = None
    if isinstance(row, dict):
        unit = row.get("reader_measurement_unit") or (row.get("measurement_provenance") or {}).get("reader_measurement_unit")
    display = project_reader_display_identity(row if isinstance(row, dict) else dict(zip(FIELDS, key)), reader_measurement_unit=unit)
    identity = {
        **dict(zip(FIELDS, key)), "feature_identity_version": FEATURE_IDENTITY_VERSION,
        "feature_id": f"FEATURE-{digest}" if complete else None,
        "reader_feature_id": f"PF-{digest[:8]}" if complete else None,
        "reader_display_identity": display,
        "reader_disambiguator": None,
        "identity_complete_for_reader_cards": complete,
        "identity_withheld_reason": None if complete else "precursor_identity_unavailable",
        "legacy_reader_feature_id": "PF-" + hashlib.sha1("|".join(key[:4]).encode()).hexdigest()[:8].upper(),
        "identity_migration_policy": "rebuild_cached_evidence_no_implicit_legacy_id_rebinding",
        "main_named_finding_eligible": complete and bool(key[0]) and key[0] not in {"?", "UNKNOWN", "UNMAPPED"},
    }
    identity["technical_crosswalk_reference"] = technical_crosswalk_reference(identity)
    return identity


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
