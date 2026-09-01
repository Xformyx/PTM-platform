"""P3 candidate bookkeeping must preserve ambiguity and direct no-call status."""

from __future__ import annotations

import json
import math
import ast

from ptm_shared.kinase_candidate_allocation import (
    P3_FRACTIONAL_ALLOCATION,
    P3_INVALID_CANDIDATE_SET,
    P3_NO_CANDIDATE_SET,
    allocate_candidate_sets,
    attach_candidate_allocation,
)
from ptm_shared.kinase_evidence_ledger import compact_summary


def _edge(*, edge_id: str, kinase: str) -> dict:
    return {
        "edge_id": edge_id,
        "kinase_accession": kinase,
        "kinase_taxonomy_id": 9606,
        "substrate_accession": "P06213",
        "substrate_taxonomy_id": 9606,
        "residue": "Y",
        "position": 1150,
        "substrate_isoform_or_sequence_id": "iPTMnet-release-6.2:P06213",
        "source_identity_scope": "accession_site_exact_iPTMnet_release_6_2",
    }


def _record(*, feature_id: str = "feature-a", relation_code: str = "R3", candidates: list[dict] | None = None) -> dict:
    return {
        "feature_id": feature_id,
        "relation_evidence": {
            "relation_class_code": relation_code,
            "candidate_edges": list(candidates or []),
        },
        "direct_kinase_attribution": {
            "status": "no_call",
            "evidence_tier": "E_direct_kinase_no_call",
            "reasons": ["curated_kinase_candidate_set_requires_p3_allocation_policy"],
        },
        "unmatched_reason_masks": {},
    }


def _ledger(records: list[dict]) -> dict:
    return {"contract_version": "ptm_kinase_feature_provenance.v5", "feature_records": records, "summary": {}}


def test_r3_candidate_set_receives_equal_conserved_mass_without_single_call() -> None:
    ledger = _ledger([_record(candidates=[_edge(edge_id="edge-b", kinase="KIN2"), _edge(edge_id="edge-a", kinase="KIN1")])])
    context = allocate_candidate_sets(ledger)
    attached = attach_candidate_allocation(ledger, context)
    allocation = attached["feature_records"][0]["allocation_evidence"]
    masses = [row["fractional_feature_evidence_mass"] for row in allocation["allocated_candidate_edges"]]
    assert allocation["allocation_status"] == P3_FRACTIONAL_ALLOCATION
    assert [row["kinase_accession"] for row in allocation["allocated_candidate_edges"]] == ["KIN1", "KIN2"]
    assert masses == [0.5, 0.5]
    assert math.isclose(allocation["total_allocated_mass"], 1.0, abs_tol=1e-12)
    assert allocation["candidate_ambiguity_entropy_nats"] == math.log(2)
    assert attached["feature_records"][0]["direct_kinase_attribution"]["status"] == "no_call"
    assert "fractional_curated_candidate_bookkeeping_not_a_direct_single_kinase_attribution" in attached["feature_records"][0]["direct_kinase_attribution"]["reasons"]


def test_multifeature_allocation_conserves_mass_and_compact_hides_candidate_identities() -> None:
    records = [
        _record(feature_id="feature-b", candidates=[_edge(edge_id="edge-1", kinase="KIN1")]),
        _record(feature_id="feature-a", candidates=[_edge(edge_id="edge-3", kinase="KIN3"), _edge(edge_id="edge-2", kinase="KIN2"), _edge(edge_id="edge-4", kinase="KIN4")]),
    ]
    attached = attach_candidate_allocation(_ledger(records), allocate_candidate_sets(_ledger(records)))
    compact = compact_summary(attached)
    allocation = compact["candidate_allocation_readiness"]
    assert allocation["eligible_feature_count"] == 2
    assert allocation["total_feature_evidence_mass"] == 2.0
    assert math.isclose(allocation["total_allocated_candidate_mass"], 2.0, abs_tol=1e-12)
    assert allocation["mass_conservation_status"] == "passed"
    assert allocation["candidate_count_histogram"] == {"1": 1, "3": 1}
    encoded = json.dumps(compact, sort_keys=True)
    for token in ("KIN1", "KIN2", "P06213", "1150", "edge-1"):
        assert token not in encoded


def test_non_r3_or_invalid_r3_candidate_sets_receive_no_mass_and_remain_no_call() -> None:
    records = [
        _record(feature_id="r0", relation_code="R0"),
        _record(feature_id="r1", relation_code="R1"),
        _record(feature_id="r2", relation_code="R2"),
        _record(feature_id="r4", relation_code="R4"),
        _record(feature_id="empty-r3", relation_code="R3"),
        _record(feature_id="duplicate-kinase", candidates=[_edge(edge_id="e1", kinase="KIN1"), _edge(edge_id="e2", kinase="KIN1")]),
    ]
    attached = attach_candidate_allocation(_ledger(records), allocate_candidate_sets(_ledger(records)))
    evidence = {record["feature_id"]: record["allocation_evidence"] for record in attached["feature_records"]}
    assert evidence["r0"]["allocation_status"] == P3_NO_CANDIDATE_SET
    assert evidence["r1"]["allocation_status"] == P3_NO_CANDIDATE_SET
    assert evidence["r2"]["allocation_status"] == P3_NO_CANDIDATE_SET
    assert evidence["r4"]["allocation_status"] == P3_NO_CANDIDATE_SET
    assert evidence["empty-r3"]["allocation_status"] == P3_INVALID_CANDIDATE_SET
    assert evidence["duplicate-kinase"]["allocation_status"] == P3_INVALID_CANDIDATE_SET
    assert all(record["direct_kinase_attribution"]["status"] == "no_call" for record in attached["feature_records"])
    compact = compact_summary(attached)
    assert compact["candidate_allocation_readiness"]["eligible_feature_count"] == 0
    assert compact["candidate_allocation_readiness"]["mass_conservation_status"] == "not_evaluable_or_no_candidate_set"


def test_candidate_input_order_does_not_change_feature_allocation() -> None:
    forward = _ledger([_record(candidates=[_edge(edge_id="e2", kinase="KIN2"), _edge(edge_id="e1", kinase="KIN1")])])
    reverse = _ledger([_record(candidates=[_edge(edge_id="e1", kinase="KIN1"), _edge(edge_id="e2", kinase="KIN2")])])
    forward_allocation = allocate_candidate_sets(forward)["feature_allocations"]["feature-a"]
    reverse_allocation = allocate_candidate_sets(reverse)["feature_allocations"]["feature-a"]
    assert forward_allocation == reverse_allocation


def test_p3_module_has_no_network_benchmark_rag_or_llm_dependency() -> None:
    from pathlib import Path

    code = (Path(__file__).resolve().parents[1] / "kinase_candidate_allocation.py").read_text(encoding="utf-8").lower()
    tree = ast.parse(code)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.lower())
    assert not any(
        token in imported
        for token in ("requests", "httpx", "urllib", "benchmark", "locked_score", "rag", "llm")
        for imported in imports
    )
