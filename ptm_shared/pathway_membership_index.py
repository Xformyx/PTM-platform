"""Full-input canonical membership and descriptive contrasts, independent of RAG.

The local reference is an explicit immutable snapshot, never a pathway-name
heuristic. Protein membership is not a functional site or causal relationship.
"""
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import median, mean
from .analysis_universe import signature
from .temporal_feature_input import finite
from .report_revision import file_sha256

REFERENCE_VERSION = "canonical_pathway_reference.v1"
RESULT_VERSION = "full_input_pathway_contrast.v1"


def read_pathway_reference(path):
    if not path or not Path(path).is_file():
        return [], {"status": "unavailable", "reason": "missing_reference", "sha256": None}
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != REFERENCE_VERSION:
        raise ValueError("incompatible_pathway_reference")
    pathways = []
    seen = set()
    for row in payload.get("pathways", []):
        if any(not row.get(k) for k in ("provider", "native_id", "taxon", "release", "name")):
            raise ValueError("incomplete_pathway_identity")
        identity = {k: str(row[k]) for k in ("provider", "native_id", "taxon", "release")}
        key = "PW-" + signature(identity)
        if key in seen:
            raise ValueError("duplicate_pathway_identity")
        seen.add(key)
        if not isinstance(row.get("protein_accessions"), list):
            raise ValueError("pathway_accessions_required")
        pathways.append({**row, **identity, "pathway_key": key})
    return sorted(pathways, key=lambda p: p["pathway_key"]), {
        "status": "available" if pathways else "empty", "reason": None,
        "sha256": file_sha256(path), "schema_version": REFERENCE_VERSION,
        "pathway_count": len(pathways)}


def build_pathway_result(manifest, inputs, pathways, source):
    index = defaultdict(list)
    for pathway in pathways:
        for accession in set(pathway["protein_accessions"]):
            index[(pathway["taxon"], accession)].append(pathway["pathway_key"])
    memberships, summaries, mapped = [], [], set()
    features = inputs["features"]
    by_pathway = defaultdict(list)
    background = defaultdict(set)
    for fid, identity in sorted(features.items()):
        taxon = str(identity.get("fasta_taxonomy_id") or "")
        proteins = sorted(set(p.strip() for p in re.split(r"[;,]", identity.get("protein_group") or "") if p.strip()))
        ambiguous = len(proteins) != 1 or not taxon
        for condition, value in inputs["ptm_timeseries"].get(fid, {}).items():
            if finite(value) is not None and not ambiguous:
                background[condition].add((taxon, proteins[0], identity.get("isoform", "")))
        for protein in proteins:
            for key in index.get((taxon, protein), []):
                # Isoform-specific references must explicitly include the
                # isoform accession; a parent accession is context only.
                scope_ambiguous = ambiguous or bool(identity.get("isoform") and identity["isoform"] != protein)
                record = dict(feature_id=fid, pathway_key=key, protein_accession=protein,
                    gene=identity.get("gene"),
                    taxon=taxon, relation_type="protein_member_of_pathway",
                    evidence_scope="protein_context", mapping_status="ambiguous" if scope_ambiguous else "matched",
                    quantitative_eligible=not scope_ambiguous,
                    source_sha256=source["sha256"], functional_site_claim=False)
                memberships.append(record)
                by_pathway[key].append(record)
                mapped.add(fid)
    for pathway in pathways:
        records = by_pathway[pathway["pathway_key"]]
        time_scores = []
        for condition in manifest["conditions"]:
            protein_values = defaultdict(list)
            observed = set()
            for record in records:
                value = finite(inputs["ptm_timeseries"].get(record["feature_id"], {}).get(condition))
                if value is not None and record["quantitative_eligible"]:
                    protein_values[record["protein_accession"]].append(value)
                    observed.add(record["feature_id"])
            values = [median(v) for v in protein_values.values()]
            time_scores.append(dict(condition=condition, value=mean(values) if values else None,
                up_proteins=sum(v > 0 for v in values), down_proteins=sum(v < 0 for v in values),
                evaluated_features=len(observed), hit_proteins=len(values),
                background_proteins=sum(taxon == pathway["taxon"] for taxon, _, _ in background[condition]),
                p_value=None, q_value=None, statistical_test_status="not_requested",
                evaluation_status="evaluated" if values else "not_evaluable",
                reason=None if values else "no_unambiguous_adjusted_observations"))
        summaries.append({k: v for k, v in pathway.items() if k != "protein_accessions"} | dict(
            member_feature_count=len({r["feature_id"] for r in records}),
            ambiguous_feature_count=len({r["feature_id"] for r in records if not r["quantitative_eligible"]}),
            reference_protein_count=len(set(pathway["protein_accessions"])), scores=time_scores,
            metric="mean_of_protein_median_adjusted_contrast", unit="log2_contrast", track="relative",
            method=RESULT_VERSION, statistical_unit="protein", within_protein_summary="median_of_precursors",
            interpretation="descriptive_member_contrast_not_pathway_activation"))
    return {"schema_version": RESULT_VERSION, "source": source, "pathways": summaries,
            "memberships": memberships, "unmapped_feature_ids": sorted(set(features)-mapped),
            "coverage": {"identified_features": len(features), "pathway_mapped_features": len(mapped) if source["status"] in {"available", "empty"} else None,
                         "pathway_unmapped_features": len(features)-len(mapped) if source["status"] in {"available", "empty"} else None,
                         "mapping_evaluation_status": "evaluated" if source["status"] in {"available", "empty"} else "not_evaluable"}}
