from __future__ import annotations

from types import SimpleNamespace

from app.services.benchmark_blind_context import (
    build_blind_context,
    source_snapshot,
    validate_benchmark_eligibility,
)


MANIFEST = {
    "manifest_sha256": "a" * 64,
    "production_contract": {
        "id": "tmm_full_temporal.v1",
        "representation_learning_in_primary_score": False,
    },
    "blind_policy": {"rag_policy": "disabled_for_strict_primary"},
}


def _order() -> SimpleNamespace:
    return SimpleNamespace(
        id=41,
        order_code="insulin_hidden_source",
        ptm_type="phosphorylation",
        species="Rat_hir",
        pr_matrix_path="/secret/insulin_source_pr.tsv",
        pg_matrix_path="/secret/insulin_source_pg.tsv",
        fasta_path="/secret/Rat_hir.fasta",
        sample_config={
            "samples": [
                {"file_name": "c.raw", "group": "control", "condition": "Control"},
                {"file_name": "a.raw", "group": "treated", "condition": "1min"},
                {"file_name": "b.raw", "group": "treated", "condition": "5min"},
                {"file_name": "d.raw", "group": "treated", "condition": "15min"},
            ]
        },
    )


def test_blind_context_excludes_source_identity_and_keeps_lineage_only() -> None:
    context = build_blind_context(lineage_class="fibroblast_like", manifest=MANIFEST)
    assert context["treatment_label"] == "Treatment A"
    assert context["research_questions"] == []
    assert context["rag_policy"] == "disabled"
    assert context["cell_context"]["source_cell_line_hidden"] is True
    assert "insulin" not in str(context).lower()


def test_snapshot_hashes_source_paths_without_exposing_source_order_code_or_paths() -> None:
    snapshot = source_snapshot(_order(), manifest=MANIFEST)
    assert snapshot["timepoint_count"] == 3
    assert "insulin_hidden_source" not in str(snapshot)
    assert "/secret/" not in str(snapshot)
    assert not validate_benchmark_eligibility(_order(), manifest=MANIFEST)
