from __future__ import annotations

import csv

from app.services.benchmark_artifact import build_temporal_request
from ptm_shared.enrichment_free_temporal_sidecar import build_production_temporal_ptm_protein_analysis
from ptm_shared.temporal_sidecar_freshness import full_dynamic_is_current


def _write_vector(path) -> None:
    fields = ["Gene.Name", "PTM_Position", "Condition", "PTM_Relative_Log2FC", "q_value"]
    rows = [
        ["G1", "S1", "1min", "0.0", "0.01"],
        ["G1", "S1", "5min", "1.0", "0.01"],
        ["G1", "S1", "15min", "2.0", "0.01"],
        ["G2", "S2", "1min", "0.1", "0.01"],
        ["G2", "S2", "5min", "1.1", "0.01"],
        ["G2", "S2", "15min", "2.1", "0.01"],
        ["G3", "S3", "1min", "0.2", "0.01"],
        ["G3", "S3", "15min", "2.2", "0.01"],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(fields)
        writer.writerows(rows)


def test_strict_and_production_share_complete_case_wave_universe(tmp_path) -> None:
    _write_vector(tmp_path / "ptm_vector_data_normalized_phospho.tsv")
    conditions = ["1min", "5min", "15min"]
    strict = build_temporal_request(
        output_dir=tmp_path,
        ptm_type="phosphorylation",
        wave_config={"compute_directionality": False},
        site_aggregation="median",
    )
    production_series = {
        key: dict(row["values"])
        for key, row in strict["site_rows"].items()
    }
    production = build_production_temporal_ptm_protein_analysis(
        output_dir=tmp_path,
        ptm_type="phosphorylation",
        ptm_timeseries=production_series,
        conditions=conditions,
        tmm_result={"conditions": conditions, "kinase_scores": [], "relative_site_contribution_matrix": {}},
        enable_dynamic_transition=False,
    )

    strict_projection = strict["wave_contract"]["input_projection_provenance"]
    production_projection = production["temporal_wave_contract"]["input_projection_provenance"]
    strict_members = sorted(
        member
        for wave in strict["wave_contract"].get("waves") or []
        for member in wave.get("members") or []
    )
    production_members = sorted(
        member
        for wave in production["temporal_wave_contract"].get("waves") or []
        for member in wave.get("members") or []
    )

    assert strict_projection["missing_value_policy"] == "complete_case_no_imputation"
    assert strict_projection["eligible_site_count"] == 2
    assert strict_projection["eligible_site_keys_sha256"] == production_projection["eligible_site_keys_sha256"]
    assert strict_members == production_members
    assert "G3_S3" not in strict_members


def test_production_sidecar_without_mapping_bundle_is_explicit_m0_and_current(tmp_path) -> None:
    production = build_production_temporal_ptm_protein_analysis(
        output_dir=tmp_path,
        ptm_type="phosphorylation",
        ptm_timeseries={
            "G1_S1": {"1min": 0.0, "5min": 1.0, "15min": 2.0},
            "G2_S2": {"1min": 0.1, "5min": 1.1, "15min": 2.1},
        },
        conditions=["1min", "5min", "15min"],
        tmm_result={"conditions": ["1min", "5min", "15min"], "kinase_scores": [], "relative_site_contribution_matrix": {}},
        enable_dynamic_transition=True,
    )

    ledger = production["kinase_feature_evidence_ledger"]
    compact = production["kinase_feature_evidence_ledger_summary"]
    assert ledger["contract_version"].endswith(".v5")
    assert ledger["mapping_importer"]["mapping_bundle_status"] == "not_evaluable"
    assert ledger["mapping_importer"]["mapping_bundle_error_code"] == "mapping_source_bundle_not_supplied"
    assert compact["mapping_readiness"]["mapping_class_counts"] == {"M0": 0, "M1": 0, "M2": 0, "M3": 0, "M4": 0}
    assert ledger["relation_importer"]["relation_bundle_status"] == "not_evaluable"
    assert ledger["relation_importer"]["relation_bundle_error_code"] == "relation_source_bundle_not_supplied"
    assert compact["relation_readiness"]["relation_class_counts"] == {"R0": 0, "R1": 0, "R2": 0, "R3": 0, "R4": 0}
    assert compact["candidate_allocation_readiness"]["eligible_feature_count"] == 0
    assert compact["candidate_allocation_readiness"]["mass_conservation_status"] == "passed"
    assert full_dynamic_is_current(production) is True
