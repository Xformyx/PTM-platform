from __future__ import annotations

from benchmarking.publication_bundle import build_publication_sources, write_publication_bundle


def test_strict_primary_publication_bundle_emits_only_figures_1_to_4(tmp_path) -> None:
    score_result = {
        "metrics": {"canonical_weighted_score": 0.75},
        "metric_numerators": {"canonical_weighted_score": 3},
        "metric_denominators": {"canonical_weighted_score": 4},
        "anchor_results": [
            {
                "anchor_id": "A1",
                "tier": "Tier 1",
                "branch": "PI3K–AKT",
                "is_measurable": True,
                "detected": True,
                "regulated": True,
                "direction_correct": True,
                "peak_window_correct": True,
            }
        ],
    }
    artifact = {
        "site_availability": [{"mapping_evidence": {"method": "sequence_isoform_species"}}],
        "temporal_wave_contract": {"waves": [{"wave_id": 1, "peak_timepoint": "5min", "members": ["AKT1_S473"]}]},
        "tmm_full_temporal": {
            "conditions": ["5min"],
            "kinase_scores": [{"canonical": "AKT", "up_sums": {"5min": 1.0}, "tmm_weighted_up_sums": {"5min": 0.7}, "tmm_evidence": {"confidence": "high"}}],
            "tmm_site_contribution_matrix": {"AKT1_S473": {"AKT": 1.0}},
            "tmm_weighted_temporal_cascade": {"timepoints": [{"timepoint": "5min", "active_kinases": [{"kinase": "AKT", "tmm_weighted_activity": 0.7}]}]},
            "tmm_kinase_pair_directionality": [],
        },
        "provenance": {"timepoints": ["0min", "5min"], "production_contract": {"id": "tmm_full_temporal.v1"}},
    }
    publication = build_publication_sources(score_result, artifact, {"source_snapshot": {"sample_count": 6}})
    assert publication["scope"]["included"] == ["Fig1", "Fig2", "Fig3", "Fig4"]
    assert publication["scope"]["excluded"] == ["Fig5_and_later"]
    written = write_publication_bundle(tmp_path, publication)
    for number in range(1, 5):
        assert (tmp_path / "figures" / f"Fig{number}.svg").is_file()
        assert (tmp_path / "source_data" / f"Fig{number}_source_data.tsv").is_file()
    assert not (tmp_path / "figures" / "Fig5.svg").exists()
    assert (tmp_path / "benchmark_source_data.zip").is_file()
    assert "source_data_zip" in written
