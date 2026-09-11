import json

from report_generation.core.report_artifact_manifest import build_report_artifact_manifest


def _write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def test_same_run_manifest_requires_all_artifacts_and_validated_temporal_provenance(tmp_path):
    vector = _write(tmp_path / "vector.tsv", "Precursor.Id\tCondition\nFORM2\t5min\n")
    enriched = _write(
        tmp_path / "enriched.json",
        json.dumps([{
            "site_form_trajectories": [{"site_form_key": "GENE_S1|precursor=FORM2|z=2"}],
            "site_aggregation": {"form_count": 1},
            "site_form_provenance_audit": {"status": "validated"},
            "report_eligible_temporal_site_aggregation": True,
        }]),
    )
    temporal = _write(
        tmp_path / "temporal_ptm_protein_analysis_v2.json",
        json.dumps({
            "provenance": {"temporal_input": {
                "site_form_provenance_audit": {"status": "validated"},
                "enriched_vector_crosswalk_audit": {"status": "validated"},
                "feature_provenance_input": {"path": str(vector)},
            }}
        }),
    )
    evidence = _write(tmp_path / "evidence_and_reproducibility_audit.md", "# Audit\n")
    prose = _write(tmp_path / "report_prose_trace.json", "{}")
    correctness = _write(tmp_path / "report_output_correctness_audit.json", "{}")
    report = _write(tmp_path / "report.md", "# Report\n")

    manifest = build_report_artifact_manifest(
        order_id=101,
        output_dir=tmp_path,
        report_markdown_paths=[report],
        vector_path=vector,
        enriched_path=enriched,
        temporal_sidecar_path=temporal,
        evidence_audit_path=evidence,
        prose_trace_path=prose,
        output_correctness_path=correctness,
        report_config={"reader_authoring_mode": "shadow"},
        temporal_required=True,
    )
    assert manifest["status"] == "validated"
    assert manifest["report_eligible"] is True
    assert len(manifest["report_run_fingerprint"]) == 64
    assert all(item["sha256"] for item in manifest["artifacts"])


def test_same_run_manifest_blocks_legacy_temporal_sidecar_without_charge_crosswalk_audits(tmp_path):
    vector = _write(tmp_path / "vector.tsv", "Precursor.Id\tCondition\nFORM2\t5min\n")
    enriched = _write(
        tmp_path / "enriched.json",
        json.dumps([{
            "site_form_trajectories": [{"site_form_key": "GENE_S1|z=nan"}],
            "site_aggregation": {"form_count": 1},
            "site_form_provenance_audit": {"status": "incompatible"},
            "report_eligible_temporal_site_aggregation": False,
        }]),
    )
    temporal = _write(tmp_path / "temporal_ptm_protein_analysis_v2.json", json.dumps({"provenance": {}}))
    evidence = _write(tmp_path / "evidence_and_reproducibility_audit.md", "# Audit\n")
    prose = _write(tmp_path / "report_prose_trace.json", "{}")
    correctness = _write(tmp_path / "report_output_correctness_audit.json", "{}")
    report = _write(tmp_path / "report.md", "# Report\n")
    manifest = build_report_artifact_manifest(
        order_id=102, output_dir=tmp_path, report_markdown_paths=[report], vector_path=vector,
        enriched_path=enriched, temporal_sidecar_path=temporal, evidence_audit_path=evidence,
        prose_trace_path=prose, output_correctness_path=correctness, report_config={}, temporal_required=True,
    )
    assert manifest["status"] == "incompatible"
    assert "enriched_site_form_provenance_not_validated" in manifest["reason_codes"]
    assert "temporal_site_form_and_vector_provenance_not_validated" in manifest["reason_codes"]
