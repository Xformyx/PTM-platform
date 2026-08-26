from __future__ import annotations

from ptm_shared.enrichment_free_temporal_sidecar import (
    DEFAULT_CROSS_LAYER_CONFIG,
    build_cross_layer_edges,
    build_kinase_timing_predictions,
    build_mechanism_evidence,
    build_production_temporal_ptm_protein_analysis,
    build_ptm_protein_pairs,
    summarize_temporal_ptm_protein_analysis,
)
from ptm_shared.temporal_optimization_config import CROSS_LAYER_CONFIG

from app.services.benchmark_artifact import attach_v2_extensions


def test_ptm_protein_pair_is_observational_and_not_causal() -> None:
    pairs = build_ptm_protein_pairs(
        [
            {
                "gene": "GENE1",
                "site": "S10",
                "peak_timepoint": "5min",
                "peak_minutes": 5.0,
                "peak_log2fc": 2.0,
                "phosphorylation_direction": "up",
            }
        ],
        [
            {
                "gene": "GENE1",
                "protein_group": "P1",
                "accessions": ["P1"],
                "peak_timepoint": "30min",
                "peak_minutes": 30.0,
                "peak_log2fc": 1.2,
                "peak_direction": "up",
            }
        ],
    )
    assert len(pairs) == 1
    assert pairs[0]["peak_lag_minutes"] == 25.0
    assert pairs[0]["ptm_precedes_protein"] is True
    assert pairs[0]["causality_status"] == "not_tested"
    assert pairs[0]["temporal_interpretation"] == "observational_peak_order_only"


def test_pair_requires_same_gene_protein_trajectory() -> None:
    pairs = build_ptm_protein_pairs(
        [{"gene": "GENE1", "site": "S10", "peak_minutes": 5.0}],
        [{"gene": "GENE2", "peak_minutes": 30.0}],
    )
    assert pairs == []


def test_attach_v2_extensions_preserves_v1_top_level_fields(tmp_path) -> None:
    source = {
        "schema_version": "ptm_blind_analysis_artifact.v1",
        "site_observations": [],
        "site_availability": [{"gene": "G", "site": "S1"}],
        "temporal_wave_contract": {"waves": []},
        "tmm_full_temporal": {"kinase_scores": []},
    }
    augmented = attach_v2_extensions(
        source,
        output_dir=tmp_path,
        ptm_type="phosphorylation",
    )
    for key, value in source.items():
        assert augmented[key] == value
    assert augmented["compatibility"]["v1_top_level_fields_preserved"] is True
    assert augmented["v2_extensions"]["schema_version"].endswith("v2.sidecar")


def test_cross_layer_edge_remains_non_causal() -> None:
    edges, summary = build_cross_layer_edges(
        {
            "timepoints": ["1min", "5min", "15min", "30min", "60min", "180min"],
            "waves": [
                {
                    "wave_id": "TW-01",
                    "member_count": 10,
                    "mean_profile": {"1min": 2.0, "5min": 1.5, "15min": 0.5, "30min": 0.2, "60min": 0.1, "180min": 0.0},
                }
            ],
        },
        [
            {
                "gene": "EFFECTOR1",
                "protein_group": "P1",
                "accessions": ["P1"],
                "has_measured_ptm": False,
                "values": {"1min": 0.0, "5min": 0.2, "15min": 1.8, "30min": 1.4, "60min": 0.4, "180min": 0.1},
                "peak_timepoint": "15min",
                "peak_log2fc": 1.8,
            }
        ],
        config={"minimum_absolute_change": 0.3, "minimum_lag_aware_similarity": 0.3},
    )
    assert summary["evaluated_pair_count"] == 1
    assert all(row["causality_status"] == "not_tested" for row in edges)
    assert all(row["network_support_status"] == "not_evaluated" for row in edges)


def test_zero_direct_timing_denominator_is_not_evaluable() -> None:
    predictions, summary = build_kinase_timing_predictions(
        {
            "conditions": ["1min", "5min"],
            "kinase_scores": [
                {
                    "kinase": "K1",
                    "tmm_profile_type": "gaussian_fallback",
                    "tmm_profile_values": {"1min": 0.2, "5min": 1.0},
                    "tmm_input_evidence": {"evidence_tier": "motif_only_seed", "sources": ["motif_only_seed"]},
                }
            ],
        }
    )
    assert len(predictions) == 1
    assert summary["data_anchored_prediction_count"] == 0
    assert summary["data_anchored_timing_status"] == "not_evaluable"


def test_mechanism_chain_keeps_temporal_candidate_boundary() -> None:
    chains, counterevidence, packets = build_mechanism_evidence(
        {"waves": [{"wave_id": "TW-01", "members": ["G1_S1"]}]},
        {"relative_site_contribution_matrix": {"G1_S1": {"K1": 1.0}}},
        [
            {
                "source_wave_id": "TW-01",
                "target_gene": "P1",
                "direction": "source_precedes_target",
                "directionality_tier": "D1_temporal_precedence",
                "eligible_for_mechanism_chain": True,
                "network_support_status": "not_evaluated",
            }
        ],
        [{"kinase": "K1", "data_anchored": False, "evidence_class": "prior_assisted"}],
    )
    assert chains[0]["mechanism_status"] == "temporal_candidate"
    assert chains[0]["causality_status"] == "not_tested"
    assert counterevidence[0]["status"] == "insufficient_evidence"
    assert packets[0]["literature_status"] == "not_requested_in_numeric_benchmark"


def test_production_order_uses_shared_v2_sidecar_contract_without_truth(tmp_path) -> None:
    protein_source = tmp_path / "all_protein_level_changes_normalized_phospho.tsv"
    protein_source.write_text(
        "Gene.Name\tCondition\tLog2FC\tProtein.Group\tProtein.Name\tHas_PTM\n"
        "EFFECTOR1\t1min\t0.0\tP1\tEffector 1\tfalse\n"
        "EFFECTOR1\t5min\t0.2\tP1\tEffector 1\tfalse\n"
        "EFFECTOR1\t15min\t1.8\tP1\tEffector 1\tfalse\n",
        encoding="utf-8",
    )
    timepoints = ["1min", "5min", "15min"]
    ptm_timeseries = {
        "G1_S1": {"1min": 2.0, "5min": 1.5, "15min": 0.3},
        "G2_S2": {"1min": 1.9, "5min": 1.4, "15min": 0.2},
        "G3_S3": {"1min": 2.1, "5min": 1.6, "15min": 0.4},
        "G4_S4": {"1min": 2.0, "5min": 1.3, "15min": 0.2},
    }
    sidecar = build_production_temporal_ptm_protein_analysis(
        output_dir=tmp_path,
        ptm_type="phosphorylation",
        ptm_timeseries=ptm_timeseries,
        conditions=timepoints,
        tmm_result={"conditions": timepoints, "kinase_scores": [], "relative_site_contribution_matrix": {}},
    )
    summary = summarize_temporal_ptm_protein_analysis(sidecar, artifact_path="temporal_ptm_protein_analysis_v2.json")

    assert DEFAULT_CROSS_LAYER_CONFIG == CROSS_LAYER_CONFIG
    assert sidecar["schema_version"].endswith("v2.sidecar")
    assert sidecar["provenance"]["analysis_mode"] == "production"
    assert sidecar["provenance"]["shared_engine_contract"] == "unified_temporal_ptm_protein.v1"
    assert sidecar["temporal_wave_contract"]["analysis_scope"] == "production_observed_only_complete_ptm_vectors"
    assert sidecar["provenance"]["benchmark_truth_used"] is False
    assert all(row["causality_status"] == "not_tested" for row in sidecar["ptm_protein_pairs"])
    assert summary["full_artifact_available"] is True
    assert summary["artifact_path"] == "temporal_ptm_protein_analysis_v2.json"
    assert "primary_score" not in summary
