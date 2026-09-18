"""Server-owned analysis universe. View and literature budgets are not inputs."""
import hashlib
import json
from collections import defaultdict
from .feature_identity import FEATURE_IDENTITY_VERSION
from .plot_selection import ordered_conditions, representation_value
from .temporal_feature_input import build_temporal_feature_inputs

ANALYSIS_UNIVERSE_VERSION = "full_eligible_precursor.v1"


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalize_candidate_modules(modules):
    """Preserve all memberships/weights/hierarchy; reject contradictory duplicates."""
    merged = {}
    for module in modules:
        name = str(module.get("canonical") or module.get("kinase") or "").strip().upper()
        if not name:
            continue
        metadata = {k: v for k, v in module.items() if k not in {"members", "ptms", "canonical", "kinase"}}
        entry = merged.setdefault(name, {"canonical": name, "kinase": name, **metadata, "members": {}})
        if any(k in entry and entry[k] != v for k, v in metadata.items()):
            raise ValueError(f"conflicting candidate module metadata: {name}")
        for member in module.get("members", module.get("ptms", [])):
            key = member.get("temporal_feature_key") or member.get("feature_id") or member.get("key")
            if not key:
                key = signature(member)
            if key in entry["members"] and entry["members"][key] != member:
                raise ValueError(f"conflicting candidate membership: {name}")
            entry["members"][key] = member
    return [{**m, "members": [m["members"][k] for k in sorted(m["members"])]} for _, m in sorted(merged.items())]


def build_analysis_manifest(snapshot, *, candidate_modules=(), sample_manifest=None, study_context=None,
                            reference_snapshots=None, config=None, scope="full_eligible", subset_ids=None, subset_reason=None):
    if scope not in {"full_eligible", "explicit_subset"}:
        raise ValueError("unknown analysis scope")
    if scope == "explicit_subset" and (not subset_ids or not subset_reason):
        raise ValueError("explicit subset requires feature IDs and a selection reason")
    rows = snapshot["rows"]
    known = {r["feature_id"] for r in rows if r.get("feature_id")}
    selected = set(subset_ids or ()) if scope == "explicit_subset" else known
    if selected - known:
        raise ValueError("subset includes features absent from measurement snapshot")
    modules = normalize_candidate_modules(candidate_modules)
    modules = [{**m, "members": [x for x in m["members"] if (x.get("temporal_feature_key") or x.get("feature_id") or x.get("key")) in selected]} for m in modules]
    modules = [m for m in modules if m["members"]]
    inputs = build_temporal_feature_inputs([
        {**row, "log2fc": representation_value(row, "adjusted"), "q_value": row.get("ptm_protein_adjusted_q_value"),
         "is_denovo": bool(row.get("conventional_log2fc_na"))}
        for row in rows if row.get("feature_id") in selected
    ])
    eligible = {fid for fid, values in inputs["ptm_timeseries"].items() if values}
    membership = defaultdict(list)
    for module in modules:
        for member in module["members"]:
            fid = member.get("temporal_feature_key") or member.get("feature_id") or member.get("key")
            if fid in selected:
                membership[fid].append(module["canonical"])
    manifest = {"schema_version": ANALYSIS_UNIVERSE_VERSION, "feature_identity_version": FEATURE_IDENTITY_VERSION,
                "measurement_revision": snapshot["measurement_revision"], "analysis_scope": scope,
                "input_scope": snapshot.get("input_scope", {}),
                "analysis_feature_ids": sorted(selected), "eligible_feature_ids": sorted(eligible),
                "subset_reason": subset_reason if scope == "explicit_subset" else None,
                "conditions": ordered_conditions(rows), "candidate_modules": modules,
                "sample_manifest": sample_manifest or {}, "study_context": study_context or {},
                "reference_snapshots": reference_snapshots or {}, "candidate_sources": snapshot.get("candidate_sources", {}), "config": config or {},
                "input_sha256": inputs["input_sha256"],
                "inventory": [{"feature_id": fid, "evaluation_status": "eligible" if fid in eligible else "not_evaluable",
                               "candidate_status": "mapped" if membership[fid] else "unassigned",
                               "candidate_ids": sorted(set(membership[fid]))} for fid in sorted(selected)],
                "coverage": {"source_rows": snapshot["source_rows"], "identified_features": len(known),
                             "identity_unresolved_rows": sum(r.get("source_row_count", 1) for r in rows if not r.get("feature_id")),
                             "quarantined_rows": len(snapshot.get("quarantine", [])),
                             "analysis_features": len(selected), "eligible_features": len(eligible),
                             "mapped_features": sum(bool(membership[fid]) for fid in selected)}}
    manifest["analysis_manifest_id"] = "ANALYSIS-" + signature(manifest)
    return manifest, inputs


def build_full_candidate_modules(snapshot, *, mapping_manifest=None, mapping_root=None, relation_manifest=None, relation_root=None):
    """Batch existing P0/P1/P2 adapters plus residue-anchored preprocessing motifs.

    Missing local bundles produce explicit source status and unassigned features;
    literature/LLM subset membership is never used as the population boundary.
    """
    from .kinase_evidence_ledger import build_feature_provenance_ledger, _feature_id, _site_key
    from .species_site_mapping import attach_mapping_context, map_feature_records
    from .kinase_relation_evidence import attach_relation_evidence, map_feature_relations
    rows = snapshot["rows"]
    raw = [r.get("source_record", r) for r in rows]
    ledger = build_feature_provenance_ledger(raw, ordered_conditions(rows))
    mapping = map_feature_records(ledger, manifest_path=mapping_manifest, snapshot_root=mapping_root)
    ledger = attach_mapping_context(ledger, mapping)
    relation = map_feature_relations(ledger, manifest_path=relation_manifest, snapshot_root=relation_root)
    ledger = attach_relation_evidence(ledger, relation)
    by_ledger_id = {record["feature_id"]: record for record in ledger.get("feature_records", [])}
    modules = defaultdict(dict)
    for row in rows:
        fid = row.get("feature_id")
        if not fid:
            continue
        source = row.get("source_record", row)
        candidates = []
        if source.get("Motif_Evidence_Policy") == "modified_residue_anchor.v1":
            for name in str(source.get("Predicted_Regulator") or "").split(";"):
                if name.strip() and name.strip().lower() not in {"unknown", "none", "nan", "no match", "n/a"}:
                    candidates.append((name.strip(), "sequence_candidate_not_direct_relation", "preprocessing_motif"))
        ledger_id = _feature_id(source, _site_key(source))
        for record in [by_ledger_id.get(ledger_id, {})]:
            p2 = record.get("relation_evidence", {})
            if p2.get("relation_class_code") == "R3":
                for edge in p2.get("candidate_edges", []):
                    name = edge.get("kinase_gene") or edge.get("kinase_accession")
                    if name:
                        candidates.append((name, "curated_site_candidate", edge.get("edge_id")))
        for name, tier, source_id in candidates:
            canonical = name.upper()
            member = modules[canonical].setdefault(fid, {"key": fid, "temporal_feature_key": fid, "feature_id": fid,
                "gene": row["gene"], "position": row["position"], "precursor_id": row["precursor_id"],
                "membership": "inferred", "evidence_roles": [], "source_ids": []})
            member["evidence_roles"] = sorted(set(member["evidence_roles"] + [tier]))
            member["source_ids"] = sorted(set(member["source_ids"] + [source_id]))
    result = [{"canonical": name, "kinase": name, "members": list(members.values()), "sources": ["full_quantitative_candidate_ledger"]}
              for name, members in sorted(modules.items())]
    return normalize_candidate_modules(result), {"mapping": mapping, "relation": relation, "feature_ledger": ledger}
