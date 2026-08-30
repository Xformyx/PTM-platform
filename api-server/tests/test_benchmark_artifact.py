from __future__ import annotations

from pathlib import Path

from app.services.benchmark_artifact import build_score_artifact, build_temporal_request


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


def test_artifact_uses_trusted_fasta_taxonomy_when_vector_has_no_taxonomy_column(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "ptm_vector_data_normalized_phospho.tsv").write_text(
        "Gene.Name\tPTM_Position\tCondition\tPTM_Relative_Log2FC\tq_value\tProtein.Group\tModified.Sequence\n"
        "HUMAN_TRANSGENE\tY2\t5min\t1.2\t0.01\tsp|H1|HUMAN_TRANSGENE\tM(Y[Phospho])Y\n",
        encoding="utf-8",
    )
    fasta = tmp_path / "mixed_reference.fasta"
    fasta.write_text(
        ">sp|H1|HUMAN_TRANSGENE OS=Homo sapiens OX=9606 GN=HUMAN_TRANSGENE\nMYY\n",
        encoding="utf-8",
    )

    artifact = build_score_artifact(
        output_dir=output,
        fasta_path=fasta,
        ptm_type="phosphorylation",
        production_contract={"id": "tmm_full_temporal.v1"},
        tmm_result={"kinase_scores": []},
    )

    evidence = artifact["site_availability"][0]["mapping_evidence"]
    assert evidence["method"] == "sequence_isoform_species"
    assert evidence["taxonomy_id"] == "9606"
    assert evidence["species_provenance"] == "trusted_fasta_record"


def test_blank_ptm_log2fc_remains_missing_for_complete_case_projection(tmp_path: Path) -> None:
    (tmp_path / "ptm_vector_data_normalized_phospho.tsv").write_text(
        "Gene.Name\tPTM_Position\tCondition\tPTM_Relative_Log2FC\tq_value\n"
        "G1\tS1\t1min\t0.0\t0.01\n"
        "G1\tS1\t5min\t\t0.01\n"
        "G1\tS1\t15min\t1.2\t0.01\n"
        "G2\tS2\t1min\t0.0\t0.01\n"
        "G2\tS2\t5min\t0.4\t0.01\n"
        "G2\tS2\t15min\t1.2\t0.01\n",
        encoding="utf-8",
    )
    request = build_temporal_request(
        output_dir=tmp_path,
        ptm_type="phosphorylation",
        site_aggregation="median",
        wave_config={"compute_directionality": False},
    )
    assert "5min" not in request["site_rows"]["G1_S1"]["values"]
    projection = request["wave_input_projection_provenance"]
    assert projection["missing_value_policy"] == "complete_case_no_imputation"
    assert projection["eligible_site_count"] == 1
