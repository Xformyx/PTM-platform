from __future__ import annotations

import json
from pathlib import Path

from report_generation.core.dynamic_prompt_generator import build_temporal_evidence_packet
from report_generation.core.temporal_sidecar_resolution import (
    resolve_report_temporal_sidecar,
    select_report_heatmap,
)
from ptm_shared.dynamic_cowave_transition import dynamic_transition_config_sha256
from ptm_shared.temporal_optimization_config import (
    DYNAMIC_COWAVE_CONFIG,
    DYNAMIC_COWAVE_CONTRACT_VERSION,
)
from ptm_shared.kinase_evidence_ledger import CONTRACT_VERSION as KINASE_LEDGER_CONTRACT_VERSION
from ptm_shared.species_site_mapping import MAPPING_IMPORTER_CONTRACT_VERSION
from ptm_shared.kinase_relation_evidence import RELATION_IMPORTER_CONTRACT_VERSION
from ptm_shared.kinase_candidate_allocation import ALLOCATION_CONTRACT_VERSION


def _compact(marker: str) -> dict:
    return {
        "shared_engine_contract": "unified_temporal_ptm_protein.v1",
        "marker": marker,
        "cross_layer_edge_count": 3,
        "dynamic_co_wave_transition_status": "computed",
        "dynamic_co_wave_transition_contract_version": DYNAMIC_COWAVE_CONTRACT_VERSION,
        "dynamic_co_wave_transition_config_sha256": dynamic_transition_config_sha256(DYNAMIC_COWAVE_CONFIG),
        "kinase_feature_evidence_ledger_summary": {
            "contract_version": KINASE_LEDGER_CONTRACT_VERSION,
            "mapping_readiness": {
                "mapping_importer_contract_version": MAPPING_IMPORTER_CONTRACT_VERSION,
                "mapping_bundle_status": "not_evaluable",
                "mapping_bundle_sha256": None,
                "mapping_class_counts": {"M0": 0, "M1": 0, "M2": 0, "M3": 0, "M4": 0},
            },
            "relation_readiness": {
                "relation_importer_contract_version": RELATION_IMPORTER_CONTRACT_VERSION,
                "relation_bundle_status": "not_evaluable",
                "relation_bundle_sha256": None,
                "relation_class_counts": {"R0": 0, "R1": 0, "R2": 0, "R3": 0, "R4": 0},
            },
            "candidate_allocation_readiness": {
                "allocation_contract_version": ALLOCATION_CONTRACT_VERSION,
                "allocation_status": "computed_no_eligible_R3_candidate_sets",
                "eligible_feature_count": 0,
                "total_feature_evidence_mass": 0.0,
                "total_allocated_candidate_mass": 0.0,
                "mass_conservation_status": "not_evaluable_or_no_candidate_set",
                "candidate_count_histogram": {},
            },
        },
    }


def _full_sidecar() -> dict:
    return {
        "schema_version": "enrichment_free_temporal_mechanism.v2.sidecar",
        "protein_time_series": [],
        "ptm_protein_pairs": [],
        "cross_layer_edges": [],
        "mechanism_chains": [],
        "hypothesis_evidence_packets": [],
        "mechanism_counterevidence": [],
        "dynamic_co_wave_transition": {
            "status": "computed",
            "contract_version": DYNAMIC_COWAVE_CONTRACT_VERSION,
            "provenance": {"config_sha256": dynamic_transition_config_sha256(DYNAMIC_COWAVE_CONFIG)},
            "summary": {},
        },
        "kinase_feature_evidence_ledger": {
            "contract_version": KINASE_LEDGER_CONTRACT_VERSION,
            "mapping_importer": {
                "mapping_importer_contract_version": MAPPING_IMPORTER_CONTRACT_VERSION,
                "mapping_bundle_status": "not_evaluable",
                "mapping_bundle_sha256": None,
            },
            "relation_importer": {
                "relation_importer_contract_version": RELATION_IMPORTER_CONTRACT_VERSION,
                "relation_bundle_status": "not_evaluable",
                "relation_bundle_sha256": None,
            },
            "candidate_allocation": {
                "allocation_contract_version": ALLOCATION_CONTRACT_VERSION,
                "allocation_status": "computed_no_eligible_R3_candidate_sets",
            },
        },
        "provenance": {"shared_engine_contract": "unified_temporal_ptm_protein.v1"},
    }


def test_db_projection_precedes_chained_config() -> None:
    compact, source, diagnostics = resolve_report_temporal_sidecar(
        db_kinase_analysis_data={"temporal_ptm_protein_analysis": _compact("db")},
        db_kinase_activity_heatmap={"temporal_ptm_protein_analysis": _compact("db_heatmap")},
        config_kinase_analysis_data={"temporal_ptm_protein_analysis": _compact("config")},
        config_kinase_activity_heatmap={"temporal_ptm_protein_analysis": _compact("config_heatmap")},
        artifact_paths=(),
    )
    assert compact["marker"] == "db"
    assert source == "orders.kinase_analysis_data"
    assert diagnostics == []


def test_chained_config_recovers_report_from_db_read_after_write_race() -> None:
    compact, source, diagnostics = resolve_report_temporal_sidecar(
        db_kinase_analysis_data={},
        db_kinase_activity_heatmap={},
        config_kinase_analysis_data={"temporal_ptm_protein_analysis": _compact("config")},
        config_kinase_activity_heatmap={},
        artifact_paths=(),
    )
    assert compact["marker"] == "config"
    assert source == "chained_report_config.kinase_analysis_data"
    assert diagnostics == []


def test_full_production_artifact_recovers_report_only_rerun(tmp_path: Path) -> None:
    artifact = tmp_path / "temporal_ptm_protein_analysis_v2.json"
    artifact.write_text(json.dumps(_full_sidecar()), encoding="utf-8")
    compact, source, diagnostics = resolve_report_temporal_sidecar(
        db_kinase_analysis_data={},
        db_kinase_activity_heatmap={},
        config_kinase_analysis_data={},
        config_kinase_activity_heatmap={},
        artifact_paths=(artifact,),
    )
    assert compact["full_artifact_available"] is True
    assert compact["dynamic_co_wave_transition_status"] == "computed"
    assert source == "production_artifact:temporal_ptm_protein_analysis_v2.json"
    assert diagnostics == []


def test_chained_sidecar_selects_matching_config_heatmap() -> None:
    selected = select_report_heatmap(
        db_kinase_activity_heatmap={"marker": "stale_db"},
        config_kinase_activity_heatmap={"marker": "fresh_config", "tmm_weighted_temporal_cascade": {}},
        sidecar_source="chained_report_config.kinase_analysis_data",
    )
    assert selected["marker"] == "fresh_config"


def test_chained_config_produces_available_packet_when_db_projection_is_missing() -> None:
    """Regression for the observed empty-packet Report: DB miss is not data loss."""
    sidecar = {
        **_compact("fresh_config"),
        "dynamic_transition_supported_wave_count": 2,
        "dynamic_transition_pair_count": 7,
        "dynamic_transition_site_count": 3,
        "dynamic_transition_per_wave": [{"static_wave_id": "W1", "pair_transition_count": 7}],
        "top_cross_layer_edges": [{
            "edge_id": "edge-1",
            "source_wave_id": "W1",
            "target_gene": "TARGET1",
            "direction": "up",
            "onset_lag_minutes": 15,
            "peak_lag_minutes": 30,
            "lag_aware_similarity": 0.8,
            "eligible_for_mechanism_chain": True,
            "causality_status": "not_tested",
        }],
    }
    fresh_heatmap = {
        "tmm_weighted_temporal_cascade": {
            "timepoints": [{
                "timepoint": "15min",
                "active_kinases": [{"kinase": "KIN1", "selected_activity": 0.7}],
            }],
        },
    }
    compact, source, _ = resolve_report_temporal_sidecar(
        db_kinase_analysis_data={},
        db_kinase_activity_heatmap={},
        config_kinase_analysis_data={"temporal_ptm_protein_analysis": sidecar},
        config_kinase_activity_heatmap=fresh_heatmap,
        artifact_paths=(),
    )
    paired_heatmap = select_report_heatmap(
        db_kinase_activity_heatmap={"marker": "stale_db"},
        config_kinase_activity_heatmap=fresh_heatmap,
        sidecar_source=source,
    )
    packet = build_temporal_evidence_packet(compact, kinase_activity_heatmap=paired_heatmap)

    assert source == "chained_report_config.kinase_analysis_data"
    assert packet["status"] == "available"
    assert any(record["evidence_id"] == "DATA-TMM-KINASE-1" for record in packet["records"])
    assert any(record["evidence_id"] == "DATA-CROSS-LAYER-1" for record in packet["records"])


def test_stale_compact_sidecar_is_skipped_for_a_current_chained_config() -> None:
    stale = _compact("stale_db")
    stale["dynamic_co_wave_transition_contract_version"] = "dynamic_co_wave_transition.v1"
    compact, source, diagnostics = resolve_report_temporal_sidecar(
        db_kinase_analysis_data={"temporal_ptm_protein_analysis": stale},
        db_kinase_activity_heatmap={},
        config_kinase_analysis_data={"temporal_ptm_protein_analysis": _compact("fresh_config")},
        config_kinase_activity_heatmap={},
        artifact_paths=(),
    )
    assert compact["marker"] == "fresh_config"
    assert source == "chained_report_config.kinase_analysis_data"
    assert any("stale Dynamic Co-Wave" in item for item in diagnostics)


def test_stale_full_artifact_is_not_recovered_for_report_rerun(tmp_path: Path) -> None:
    artifact = tmp_path / "temporal_ptm_protein_analysis_v2.json"
    stale = _full_sidecar()
    stale["dynamic_co_wave_transition"]["contract_version"] = "dynamic_co_wave_transition.v1"
    artifact.write_text(json.dumps(stale), encoding="utf-8")
    compact, source, diagnostics = resolve_report_temporal_sidecar(
        db_kinase_analysis_data={},
        db_kinase_activity_heatmap={},
        config_kinase_analysis_data={},
        config_kinase_activity_heatmap={},
        artifact_paths=(artifact,),
    )
    assert compact == {}
    assert source == ""
    assert any("stale Dynamic Co-Wave" in item for item in diagnostics)
