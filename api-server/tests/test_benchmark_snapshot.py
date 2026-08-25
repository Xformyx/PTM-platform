from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services.benchmark_snapshot import create_sanitized_snapshot


def test_snapshot_replaces_source_sample_headers_and_hides_context(tmp_path: Path) -> None:
    pr = tmp_path / "insulin_precursor.tsv"
    pg = tmp_path / "insulin_protein.tsv"
    fasta = tmp_path / "Rat_hir.fasta"
    pr.write_text("Protein\tcontrol.raw\tinsulin_5m.raw\tinsulin_15m.raw\nP1\t1\t2\t3\n", encoding="utf-8")
    pg.write_text("Protein\tcontrol.raw\tinsulin_5m.raw\tinsulin_15m.raw\nP1\t1\t2\t3\n", encoding="utf-8")
    fasta.write_text(">sp|P1|GENE OS=Rattus norvegicus OX=10116 GN=GENE\nMSY\n", encoding="utf-8")
    order = SimpleNamespace(
        pr_matrix_path=str(pr),
        pg_matrix_path=str(pg),
        fasta_path=str(fasta),
        sample_config={
            "samples": [
                {"file_name": "control.raw", "group": "control", "condition": "Control"},
                {"file_name": "insulin_5m.raw", "group": "treated", "condition": "5min"},
                {"file_name": "insulin_15m.raw", "group": "treated", "condition": "15min"},
            ]
        },
    )
    snapshot = create_sanitized_snapshot(source_order=order, blind_context={}, destination_dir=tmp_path / "snapshot")
    text = Path(snapshot.pr_matrix_path).read_text(encoding="utf-8")
    assert "insulin" not in text.lower()
    assert "S001.mzML" in text and "S002.mzML" in text and "S003.mzML" in text
    assert snapshot.condition_map == {"S001.mzML": "Control", "S002.mzML": "5min", "S003.mzML": "15min"}
    assert all(name.endswith(".mzML") for name in snapshot.condition_map)
