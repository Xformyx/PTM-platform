from __future__ import annotations

from pathlib import Path

from app.services.benchmark_artifact import build_score_artifact


def test_artifact_uses_only_vector_and_fasta_evidence(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "ptm_vector_data_normalized_phospho.tsv").write_text(
        "Gene.Name\tPTM_Position\tCondition\tPTM_Relative_Log2FC\tq_value\tProtein.Group\tModified.Sequence\tFASTA_Taxonomy_ID\n"
        "GENE\tS2\t5min\t1.2\t0.01\tsp|P1|GENE\tM(S[Phospho])Y\t10116\n"
        "GENE\tS2\t15min\t0.6\t0.03\tsp|P1|GENE\tM(S[Phospho])Y\t10116\n",
        encoding="utf-8",
    )
    fasta = tmp_path / "reference.fasta"
    fasta.write_text(">sp|P1|GENE OS=Rattus norvegicus OX=10116 GN=GENE\nMSY\n", encoding="utf-8")

    artifact = build_score_artifact(
        output_dir=output,
        fasta_path=fasta,
        ptm_type="phosphorylation",
        production_contract={"id": "tmm_full_temporal.v1"},
        tmm_result={"kinase_scores": []},
    )
    evidence = artifact["site_availability"][0]["mapping_evidence"]
    assert evidence["method"] == "sequence_isoform_species"
    assert evidence["sequence_match"] is True
    assert artifact["temporal_wave_contract"]["contract_version"]
    assert artifact["provenance"]["rag_used"] is False
    assert artifact["provenance"]["llm_used"] is False
    assert "insulin" not in str(artifact).lower()
