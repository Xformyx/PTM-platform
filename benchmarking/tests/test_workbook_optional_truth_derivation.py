from pathlib import Path

import pytest

from benchmarking.workbook_optional_truth_derivation import (
    derive_optional_truth_from_workbook,
    derive_workbook_mechanism_chains,
)
from benchmarking.v2_truth_adapter import build_additive_v2_truth


def test_derives_only_curated_kinase_output_pairs() -> None:
    rows = derive_workbook_mechanism_chains(
        [
            {
                "Kinase_ID": "K1",
                "Kinase_or_complex": "KINASE1",
                "Direct_or_preferred_outputs": "TARGET1; TARGET2; PIP3",
                "Source_IDs": "PMID:1",
            }
        ]
    )
    assert [row["Target_gene"] for row in rows] == ["TARGET1", "TARGET2"]
    assert all(row["Reference_origin"] == "workbook_kinase_reference_direct_or_preferred_outputs" for row in rows)
    assert all("cross-layer" in row["Notes"] for row in rows)


def test_curated_output_parser_excludes_prose_and_ptm_position_fragments() -> None:
    rows = derive_workbook_mechanism_chains(
        [
            {
                "Kinase_ID": "K1",
                "Kinase_or_complex": "KINASE1",
                "Direct_or_preferred_outputs": (
                    "PIP3-dependent recruitment of AKT; PDK1-mediated p-AKT T308; "
                    "p-S6K1 T229; RPS6; 4E-BP1; downstream anchors"
                ),
                "Source_IDs": "PMID:1",
            }
        ]
    )
    assert [row["Target_gene"] for row in rows] == ["4E-BP1", "AKT", "RPS6", "S6K1"]


def test_refuses_workbook_hash_mismatch(tmp_path: Path) -> None:
    workbook = tmp_path / "reference.xlsx"
    workbook.write_bytes(b"not-a-real-workbook")
    truth = {"source_workbook_sha256": "mismatch", "kinase_reference": []}
    with pytest.raises(ValueError, match="SHA-256"):
        derive_optional_truth_from_workbook(truth, workbook_path=workbook)


def test_derived_explicit_rows_become_evaluable_additive_truth() -> None:
    additive = build_additive_v2_truth(
        {
            "dataset_id": "runner-only",
            "kinase_reference": [],
            "additive_v2_reference": {
                "protein_effectors": [],
                "cross_layer_relations": [],
                "mechanism_chains": [
                    {
                        "Chain_ID": "WORKBOOK_KINASE_OUTPUT_1",
                        "Kinase_ID": "K1",
                        "Kinase_or_complex": "KINASE1",
                        "Target_gene": "TARGET1",
                        "Required_output_tokens": "TARGET1",
                        "Reference_origin": "workbook_kinase_reference_direct_or_preferred_outputs",
                    }
                ],
                "counterexamples": [],
            },
        }
    )
    assert additive["evaluability"]["mechanism"] == "explicit_reference_available"
    assert additive["mechanism_reference"][0]["target_gene"] == "TARGET1"
