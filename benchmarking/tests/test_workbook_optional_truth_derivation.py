from pathlib import Path

import pytest

from benchmarking.workbook_optional_truth_derivation import (
    derive_optional_truth_from_workbook,
    derive_workbook_mechanism_chains,
)


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


def test_refuses_workbook_hash_mismatch(tmp_path: Path) -> None:
    workbook = tmp_path / "reference.xlsx"
    workbook.write_bytes(b"not-a-real-workbook")
    truth = {"source_workbook_sha256": "mismatch", "kinase_reference": []}
    with pytest.raises(ValueError, match="SHA-256"):
        derive_optional_truth_from_workbook(truth, workbook_path=workbook)
