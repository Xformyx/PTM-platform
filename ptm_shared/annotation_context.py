"""Annotation lookup is a scoped left join, never a measurement identity."""
from collections import defaultdict
import hashlib
import json
import re

CONTEXT_KEY_VERSION = "annotation_context.v1"
_MISSING = {"", "nan", "null", "none", "na", "n/a"}


def token(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip().lower() not in _MISSING:
            return str(value).strip()
    return ""


def build_annotation_context_key(row):
    gene = token(row, "gene", "Gene.Name", "gene_name").upper()
    site = token(row, "position", "PTM_Position", "site")
    # Do not sort/split multisite forms or invent a residue for a bare number.
    site = site.upper() if re.fullmatch(r"[A-Za-z][1-9][0-9]*", site) else ""
    return (gene, site,
            token(row, "fasta_taxonomy_id", "FASTA_Taxonomy_ID", "taxonomy_id", "taxon_id"),
            token(row, "accession", "FASTA_Accession", "Protein.Ids", "protein_group", "Protein.Group"),
            token(row, "isoform", "Isoform"),
            token(row, "residue_coordinate_system", "coordinate_system"))


class AnnotationIndex:
    def __init__(self, annotations):
        self.by_gene = defaultdict(dict)
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            digest = hashlib.sha256(json.dumps(annotation, sort_keys=True, default=str).encode()).hexdigest()
            key = build_annotation_context_key(annotation)
            self.by_gene[key[0]][digest] = annotation

    def match(self, feature):
        fk = build_annotation_context_key(feature)
        matches, conflicts, weak = [], [], []
        for digest, annotation in sorted(self.by_gene.get(fk[0], {}).items()):
            ak = build_annotation_context_key(annotation)
            if ak[1] and fk[1] and ak[1] != fk[1]:
                continue
            record = {"annotation_id": annotation.get("annotation_id") or f"ANN-{digest}",
                      "source_gene_label": token(annotation, "gene", "Gene.Name"),
                      "source_position_label": token(annotation, "position", "PTM_Position"),
                      "source": annotation, "evidence_scope": annotation.get("evidence_scope", "unverified_context")}
            if any(a and b and a != b for a, b in zip(fk[2:], ak[2:])):
                conflicts.append(record)
                continue
            exact_feature = bool(feature.get("feature_id") and annotation.get("feature_id") == feature["feature_id"])
            # Missing taxon/accession cannot be promoted to site evidence. An
            # explicit isoform on only one side is also unresolved, not inferred.
            site_context = bool(fk[1] and fk[1] == ak[1] and fk[2] and fk[3]
                                and fk[2:4] == ak[2:4] and fk[4:] == ak[4:])
            if exact_feature or site_context:
                record["match_scope"] = "feature" if exact_feature else "site_context"
                matches.append(record)
            else:
                record["match_scope"] = "gene_context"
                weak.append(record)
        chosen = matches or weak
        # Multiple assertions with explicit distinct IDs may legitimately share
        # a site. Reused IDs with different payloads are ambiguous, never overwrite.
        duplicate_identity = len({p["annotation_id"] for p in chosen}) != len(chosen)
        status = "ambiguous" if duplicate_identity or (not matches and conflicts) else "matched" if chosen else "unmatched"
        scope = ("feature" if any(p["match_scope"] == "feature" for p in chosen) else
                 "site_context" if matches else "gene_context" if weak else "none")
        method = "none"
        if chosen:
            exact_labels = all(p["source_gene_label"] == token(feature, "source_gene_label", "gene") and
                               p["source_position_label"] == token(feature, "source_position_label", "position") for p in chosen)
            method = "exact_context" if exact_labels else "normalized_context"
        return {"feature_id": feature.get("feature_id"), "status": status, "match_method": method,
                "match_scope": scope, "annotation_ids": [p["annotation_id"] for p in chosen],
                "context_key_version": CONTEXT_KEY_VERSION,
                "reason_codes": (["annotation_key_collision"] if duplicate_identity else
                                 ["ambiguous_context"] if status == "ambiguous" else
                                 ["context_only"] if weak and not matches else
                                 ["annotation_unmatched"] if not chosen else []),
                "assertions": chosen, "conflicting_contexts": conflicts}
