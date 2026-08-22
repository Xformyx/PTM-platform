"""Contract tests for the PTM representation learning layers (L1-L4).

Run from the repository root:

    python -m pytest workers/tests/test_ptm_representation_learning.py -v

or inside the preprocessing worker container:

    python -m pytest tests/test_ptm_representation_learning.py -v
"""

import hashlib
import json
import math

import numpy as np
import pandas as pd
import pytest

from ptm_shared.representation import (
    ADOPTION_GATES,
    FROZEN_GATE_SETTINGS,
    GATE_INDUCED_MASK_SEED_SET,
    GATE_JUDGEMENT_THRESHOLDS,
    GATE_PROBE_PARAMETERS,
    PRIMARY_ARM_PREFERENCE,
    PRIMARY_SCORE_INPUTS_LOCKED,
    build_additive_fields,
    build_multiview_input,
    build_trajectory_vectors,
    describe_contract,
    evaluate_adoption_gates,
    fit_masked_temporal_encoder,
    gate_settings_digest,
    handcrafted_representation,
    mask_aware_nmf,
    mask_aware_pca,
    preserved_baseline_layer,
    resolve_layer,
    resolve_variant,
    run_ablation,
    select_primary_variant,
    validate_multiview_input,
)
from ptm_shared.representation.benchmark import DEFAULT_BENCHMARK_CONFIG

try:  # container layout puts the worker packages at the import root
    from preprocessing.core.ptm_representation_learning import PTMRepresentationLearningAnalyzer
except ModuleNotFoundError:  # repository-root layout
    from workers.preprocessing.core.ptm_representation_learning import (
        PTMRepresentationLearningAnalyzer,
    )


# Deliberately irregular spacing, as in the insulin time course.
TIMEPOINTS = ["1min", "2.5min", "5min", "15min", "30min", "60min"]
MINUTES = [1.0, 2.5, 5.0, 15.0, 30.0, 60.0]


def _profile(shape: str, index: int) -> list[float]:
    """Three separable temporal shapes plus a small per-site offset."""
    offset = 0.05 * index
    if shape == "early":
        base = [1.8, 2.4, 2.0, 0.9, 0.3, 0.1]
    elif shape == "late":
        base = [0.1, 0.2, 0.5, 1.4, 2.3, 2.6]
    else:
        base = [-0.4, -0.9, -1.6, -2.1, -1.8, -1.2]
    return [value + offset for value in base]


def _vector_rows(
    *,
    n_per_shape: int = 8,
    missing_sites: tuple[int, ...] = (0, 1),
    track1_sites: tuple[int, ...] = (0, 2, 4, 6, 8, 10),
    unqualified_track1_sites: tuple[int, ...] = (1, 3),
    with_motifs: bool = False,
) -> list[dict]:
    """Build synthetic L1 Quantitative PTM Feature Vector rows."""
    rows: list[dict] = []
    site_index = 0
    for shape in ("early", "late", "down"):
        for member in range(n_per_shape):
            gene = f"{shape.upper()}{member}"
            position = "S100"
            form = f"AAA{shape[0].upper()}{member}TSK"
            profile = _profile(shape, member)
            for time_index, timepoint in enumerate(TIMEPOINTS):
                if site_index in missing_sites and time_index == 2:
                    continue  # unobserved Track 2 timepoint
                tier = "O0"
                occupancy = float("nan")
                if site_index in track1_sites:
                    tier = "O2"
                    occupancy = profile[time_index] * 0.5
                elif site_index in unqualified_track1_sites:
                    # A present number on an unqualified pair must stay out of Track 1.
                    tier = "O0"
                    occupancy = 99.0
                row = {
                    "Protein.Group": f"P{site_index:05d}",
                    "Gene.Name": gene,
                    "PTM_Position": position,
                    "Modified.Sequence": form,
                    "PTM_Type": "Phosphorylation",
                    "Condition": timepoint,
                    "Comparison": f"{timepoint}_vs_Control",
                    "PTM_Relative_Log2FC": profile[time_index],
                    "Protein_Log2FC": 0.1 * profile[time_index],
                    "q_value": 0.01 if abs(profile[time_index]) > 1.0 else 0.4,
                    "p_value": 0.005,
                    "Quantification_Track": "protein_normalized_relative_ptm",
                    "Occupancy_Logit_Delta": occupancy,
                    "Pair_Quality_Tier": tier,
                    "Pair_Missingness": 0.0,
                }
                if with_motifs:
                    row["Matched_Motifs"] = "RXRXXS" if shape == "early" else "SP"
                rows.append(row)
            site_index += 1
    return rows


def _multiview(**kwargs):
    return build_multiview_input(_vector_rows(**kwargs))


# ---------------------------------------------------------------------------
# L1 preservation and naming
# ---------------------------------------------------------------------------


def test_current_ptm_vector_method_is_named_l1_and_marked_unchanged():
    layer = preserved_baseline_layer()
    assert layer.layer_id == "L1"
    assert layer.name == "quantitative_ptm_feature_vector"
    assert layer.display_name == "Quantitative PTM Feature Vector"
    assert layer.produced_by.endswith("PTMQuantificationAnalyzer.create_ptm_vector_data")
    assert layer.artifact == "ptm_vector_data_normalized{file_suffix}.tsv"
    assert layer.replaces_lower_layers is False
    # Legacy wording must resolve to the same named layer.
    assert resolve_layer("ptm_vector") is layer
    assert resolve_layer("L1") is layer
    assert resolve_layer("quantitative_ptm_feature_vector") is layer


def test_learned_embedding_is_a_separate_layer_and_does_not_replace_l1():
    contract = describe_contract()
    ids = [entry["layer_id"] for entry in contract["layers"]]
    assert ids == ["L1", "L2", "L3", "L4"]
    assert all(entry["replaces_lower_layers"] is False for entry in contract["layers"])
    assert contract["preserved_baseline"] == preserved_baseline_layer().method_id
    for locked in ("canonical_co_wave_membership", "tmm_contribution_coefficients", "kinase_ranking"):
        assert locked in PRIMARY_SCORE_INPUTS_LOCKED


def test_all_five_ablation_arms_are_registered():
    contract = describe_contract()
    assert [entry["variant_id"] for entry in contract["variants"]] == ["A", "B", "C", "D", "E"]
    assert resolve_variant("A").learned is False
    assert resolve_variant("B").learned is False
    assert resolve_variant("D").learned is True
    assert resolve_variant("E").learned is True
    assert resolve_variant("C").uses_prior_features is True
    assert resolve_variant("E").uses_prior_features is False


# ---------------------------------------------------------------------------
# L3 input contract
# ---------------------------------------------------------------------------


def test_multiview_input_satisfies_the_contract():
    multiview = _multiview()
    assert validate_multiview_input(multiview) == []
    assert multiview.timepoints == TIMEPOINTS
    assert multiview.n_sites == 24
    assert multiview.target.role == "primary_target"
    assert multiview.protein_context.role == "context"
    assert multiview.track1.role == "gated_optional"


def test_track1_absence_is_masked_and_never_zero_filled():
    multiview = _multiview()
    provenance = multiview.provenance
    assert provenance["track1_policy"] == "availability_masked_never_zero_filled"

    # Sites with a qualified O2 pair are available; O0 rows carrying a number are not.
    available = {
        key for key, flag in zip(multiview.site_keys, multiview.track1_available) if flag
    }
    assert len(available) == 6
    unavailable_rows = ~multiview.track1_available
    assert not multiview.track1.observed[unavailable_rows].any()
    assert np.all(np.isnan(multiview.track1.values[unavailable_rows]))
    # The unqualified 99.0 value must not have leaked into Track 1.
    assert not np.any(multiview.track1.values[multiview.track1.observed] == 99.0)


def test_qvalue_is_a_loss_weight_and_eligibility_mask_not_a_feature_view():
    multiview = _multiview()
    assert multiview.provenance["qvalue_policy"] == (
        "quality_weight_and_eligibility_mask_not_feature"
    )
    assert "q_value" not in multiview.view_names
    assert multiview.view_names[0] == "track2_ptm_relative_log2fc"
    # Confident measurements weigh more than weak ones, and unobserved entries weigh nothing.
    weights = multiview.quality_weight[multiview.target.observed]
    assert weights.min() > 0.0
    assert weights.max() <= 1.0
    assert np.all(multiview.quality_weight[~multiview.target.observed] == 0.0)
    assert len(set(np.round(weights, 6).tolist())) > 1


def test_missing_track2_timepoint_stays_unobserved():
    multiview = _multiview(missing_sites=(0,))
    row = multiview.site_keys.index(
        next(key for key in multiview.site_keys if key.startswith("EARLY0 "))
    )
    assert multiview.target.observed[row].sum() == len(TIMEPOINTS) - 1
    assert math.isnan(float(multiview.target.values[row, 2]))
    assert multiview.missingness_rate()[row] > 0.0


def test_irregular_timepoint_spacing_is_preserved_in_the_time_encoding():
    multiview = _multiview()
    assert list(np.round(multiview.time_minutes, 3)) == MINUTES
    # Δt reflects real gaps, not positional indices.
    assert list(np.round(multiview.delta_minutes[1:], 3)) == [1.5, 2.5, 10.0, 15.0, 30.0]
    encoding = multiview.time_encoding
    assert encoding.shape == (len(TIMEPOINTS), 5)
    gaps = encoding[1:, 2]
    assert gaps[-1] > gaps[0]  # the 30->60 min gap dominates the 1->2.5 min gap
    # An evenly spaced course must produce a different encoding.
    regular = build_multiview_input(
        [
            {**row, "Condition": {"1min": "10min", "2.5min": "20min", "5min": "30min",
                                  "15min": "40min", "30min": "50min", "60min": "60min"}[row["Condition"]]}
            for row in _vector_rows()
        ]
    )
    assert not np.allclose(regular.time_encoding, multiview.time_encoding)


def test_species_context_is_recorded_as_metadata_not_as_a_feature():
    multiview = build_multiview_input(
        _vector_rows(), species_context={"label": "rat_hir", "analysis_species": "rat"}
    )
    assert multiview.provenance["species_context"]["label"] == "rat_hir"
    assert multiview.provenance["species_policy"] == "model_domain_metadata_not_input_feature"
    assert not any("species" in name for name in multiview.view_names)


def test_trajectory_vectors_collapse_to_canonical_site_keys():
    multiview = _multiview()
    series, timepoints, metadata = build_trajectory_vectors(multiview, site_level=True)
    assert timepoints == TIMEPOINTS
    assert all(" " in key and "|" not in key for key in series)
    assert metadata[next(iter(series))]["forms"]


# ---------------------------------------------------------------------------
# R0 baselines
# ---------------------------------------------------------------------------


def test_mask_aware_baselines_ignore_unobserved_entries():
    multiview = _multiview()
    values = multiview.target.values
    observed = multiview.target.observed

    polluted = np.array(values, dtype=float, copy=True)
    polluted[~observed] = 10_000.0

    clean = mask_aware_pca(values, observed, n_components=3)
    dirty = mask_aware_pca(polluted, observed, n_components=3)
    assert np.allclose(clean.embedding, dirty.embedding, atol=1e-8)

    clean_nmf = mask_aware_nmf(values, observed, n_components=3, seed=0)
    dirty_nmf = mask_aware_nmf(polluted, observed, n_components=3, seed=0)
    assert np.allclose(clean_nmf.embedding, dirty_nmf.embedding, atol=1e-8)


def test_handcrafted_arms_reflect_their_declared_views():
    multiview = _multiview(with_motifs=True)
    with_motifs = build_multiview_input(
        _vector_rows(with_motifs=True), config={"include_motif_side_feature": True}
    )
    n_time = multiview.n_timepoints
    arm_a = handcrafted_representation(multiview, "A")
    arm_b = handcrafted_representation(multiview, "B")
    arm_c = handcrafted_representation(with_motifs, "C")

    assert arm_a.embedding.shape[1] == 2 * n_time
    assert arm_b.embedding.shape[1] == 5 * n_time
    assert arm_b.provenance["quality_as_feature"] is True
    assert arm_c.embedding.shape[1] > arm_b.embedding.shape[1]
    assert arm_c.provenance["motif_as_feature"] is True
    with pytest.raises(ValueError):
        handcrafted_representation(multiview, "E")


# ---------------------------------------------------------------------------
# R1 encoder
# ---------------------------------------------------------------------------


def _encoder_config(**overrides):
    config = {"epochs": 60, "latent_dim": 8, "hidden_dim": 24, "seed": 7, "n_perturbations": 3}
    config.update(overrides)
    return config


def test_encoder_is_deterministic_for_a_fixed_seed():
    multiview = _multiview()
    first = fit_masked_temporal_encoder(multiview, config=_encoder_config())
    second = fit_masked_temporal_encoder(multiview, config=_encoder_config())
    assert np.allclose(first.embedding, second.embedding)
    assert first.provenance["config_sha256"] == second.provenance["config_sha256"]
    different = fit_masked_temporal_encoder(multiview, config=_encoder_config(seed=11))
    assert not np.allclose(first.embedding, different.embedding)


def test_encoder_holds_out_entries_even_for_a_short_time_course():
    multiview = _multiview()
    fitted = fit_masked_temporal_encoder(multiview, config=_encoder_config())
    assert fitted.provenance["n_heldout_entries"] >= multiview.n_sites - 2
    assert np.isfinite(fitted.heldout_reconstruction_error)


def test_encoder_holds_out_entries_and_reports_their_error():
    multiview = _multiview()
    fitted = fit_masked_temporal_encoder(multiview, config=_encoder_config(holdout_fraction=0.2))
    assert fitted.provenance["n_heldout_entries"] > 0
    assert fitted.provenance["self_supervision"] == "masked_reconstruction_with_disjoint_holdout"
    assert np.isfinite(fitted.heldout_reconstruction_error)
    assert fitted.embedding.shape == (multiview.n_sites, 8)
    assert fitted.reconstruction.shape == (multiview.n_sites, multiview.n_timepoints)


def test_encoder_declares_secondary_use_and_qvalue_role():
    multiview = _multiview()
    fitted = fit_masked_temporal_encoder(multiview, config=_encoder_config())
    assert fitted.provenance["secondary_use_only"] is True
    assert fitted.provenance["primary_scores_unchanged"] is True
    assert fitted.provenance["qvalue_role"] == "loss_weight_only"
    assert fitted.provenance["track1_branch"] == "availability_gated"
    assert fitted.provenance["primary_target"] == "track2_ptm_relative_log2fc"


def test_permuted_time_order_produces_a_different_representation():
    multiview = _multiview()
    permuted = multiview.with_permuted_time_order(seed=3)
    assert permuted.provenance["time_order"] == "permuted"
    assert permuted.timepoints != multiview.timepoints
    observed = fit_masked_temporal_encoder(multiview, config=_encoder_config())
    shuffled = fit_masked_temporal_encoder(permuted, config=_encoder_config())
    assert not np.allclose(observed.embedding, shuffled.embedding)


def test_track1_only_sites_do_not_gain_fabricated_occupancy_gradients():
    """Disabling the Track 1 branch must change nothing for sites without a pair."""
    multiview = _multiview(track1_sites=())
    with_branch = fit_masked_temporal_encoder(multiview, config=_encoder_config(use_track1=True))
    assert with_branch.provenance["n_track1_observed_entries"] == 0


# ---------------------------------------------------------------------------
# Additive fields
# ---------------------------------------------------------------------------


def test_additive_fields_are_secondary_and_traceable_to_raw_evidence():
    multiview = _multiview()
    fitted = fit_masked_temporal_encoder(multiview, config=_encoder_config())
    series, timepoints, metadata = build_trajectory_vectors(multiview, site_level=True)
    membership = {key: "wave_1" if key.startswith("EARLY") else "wave_2" for key in series}

    additive = build_additive_fields(
        multiview,
        fitted.embedding,
        reconstruction_error=fitted.reconstruction_error,
        perturbed_embeddings=fitted.perturbed_embeddings,
        embedding_uncertainty=fitted.embedding_uncertainty,
        wave_membership=membership,
        exclusive_members={"AKT1": [0, 1, 2, 3], "MAPK1": [8, 9]},
        config={"neighbors": 5},
    )

    assert additive.provenance["changes_primary_scores"] is False
    assert additive.provenance["role"] == "additive_secondary_evidence"
    assert "causality" in additive.provenance["interpretation_limit"]
    assert additive.summary["n_sites"] == multiview.n_sites

    sample = additive.site_fields[multiview.site_keys[0]]
    for field in (
        "site_key",
        "gene",
        "position",
        "modified_sequence",
        "observed_timepoints",
        "track1_available",
        "representation_reconstruction_error",
        "embedding_neighbor_stability",
        "representation_track_concordance",
        "representation_supported",
        "representation_discordant",
    ):
        assert field in sample
    assert additive.kinase_fields["AKT1"]["profile_representational_dispersion"] is not None
    assert additive.kinase_fields["MAPK1"]["n_exclusive_members"] == 2


def test_discordance_requires_a_stable_neighbourhood():
    """Without perturbation refits, stability is unknown and discordance is not claimed."""
    multiview = _multiview()
    fitted = fit_masked_temporal_encoder(multiview, config=_encoder_config(n_perturbations=0))
    membership = {
        str(meta.get("site_key")): f"wave_{index % 7}"
        for index, meta in enumerate(multiview.site_metadata.values())
    }
    additive = build_additive_fields(
        multiview,
        fitted.embedding,
        reconstruction_error=fitted.reconstruction_error,
        perturbed_embeddings=[],
        wave_membership=membership,
        config={"neighbors": 5},
    )
    assert additive.summary["n_representation_discordant"] == 0
    assert all(
        fields["embedding_neighbor_stability"] is None for fields in additive.site_fields.values()
    )


# ---------------------------------------------------------------------------
# Adoption gates
# ---------------------------------------------------------------------------


def _passing_metrics() -> dict:
    return {
        "B": {"variant_id": "B", "learned": False, "raw_evidence_concordance": 0.55,
              "uses_prior_features": False, "n_sites": 24, "embedding_dim": 30},
        "D": {
            "variant_id": "D",
            "learned": True,
            "n_sites": 24,
            "embedding_dim": 8,
            "heldout_reconstruction_error": 0.30,
            "raw_evidence_concordance": 0.72,
            "missingness_r2": 0.05,
            "uses_prior_features": False,
            "time_permutation": {"permuted_heldout_reconstruction_error": 0.55},
            "artificial_masking_probe": {
                "n_masked_entries": 120,
                "pattern_retention_ari": 0.55,
                "induced_missingness_r2": 0.06,
            },
        },
    }


def test_primary_arm_is_the_temporal_learned_arm():
    # The held-out timepoint probe is the only leak-free comparison available,
    # and D is the arm that beats the handcrafted baseline under it.
    assert PRIMARY_ARM_PREFERENCE[0] == "D"
    assert select_primary_variant(["D", "E"]) == "D"
    assert select_primary_variant(["E", "D"]) == "D"


def test_primary_arm_falls_back_when_the_preferred_arm_did_not_fit():
    # A skipped or failed D must not silently leave the gates without a subject.
    assert select_primary_variant(["E"]) == "E"
    assert select_primary_variant([]) == "D"
    assert select_primary_variant(["B"]) == "B"


def test_gates_block_production_influence_without_external_generalization():
    verdict = evaluate_adoption_gates(_passing_metrics())
    assert verdict["production_influence_allowed"] is False
    assert verdict["gates"]["generalization"]["status"] == "not_evaluated"
    assert verdict["gates"]["time_validity"]["passed"] is True
    assert verdict["gates"]["missingness_validity"]["passed"] is True
    assert verdict["gates"]["raw_evidence_concordance"]["passed"] is True
    assert set(verdict["gates_passed"]) == set(ADOPTION_GATES)


def test_gates_allow_influence_only_when_every_gate_passes():
    verdict = evaluate_adoption_gates(
        _passing_metrics(),
        external_evaluations=[{"dataset": "public_insulin_holdout", "improves_baseline": True}],
    )
    assert verdict["n_gates_passed"] == verdict["n_gates_total"]
    assert verdict["production_influence_allowed"] is True


def test_time_validity_fails_when_permuted_order_is_not_worse():
    metrics = _passing_metrics()
    metrics["D"]["time_permutation"] = {"permuted_heldout_reconstruction_error": 0.29}
    verdict = evaluate_adoption_gates(
        metrics,
        external_evaluations=[{"dataset": "holdout", "improves_baseline": True}],
    )
    assert verdict["gates"]["time_validity"]["passed"] is False
    assert verdict["production_influence_allowed"] is False


def test_missingness_gate_fails_when_embedding_encodes_induced_coverage():
    metrics = _passing_metrics()
    metrics["D"]["artificial_masking_probe"]["induced_missingness_r2"] = 0.85
    verdict = evaluate_adoption_gates(
        metrics,
        external_evaluations=[{"dataset": "holdout", "improves_baseline": True}],
    )
    assert verdict["gates"]["missingness_validity"]["passed"] is False
    assert verdict["production_influence_allowed"] is False


def test_missingness_gate_fails_when_masking_destroys_the_temporal_pattern():
    metrics = _passing_metrics()
    metrics["D"]["artificial_masking_probe"]["pattern_retention_ari"] = 0.02
    verdict = evaluate_adoption_gates(
        metrics,
        external_evaluations=[{"dataset": "holdout", "improves_baseline": True}],
    )
    assert verdict["gates"]["missingness_validity"]["passed"] is False


# ---------------------------------------------------------------------------
# Frozen gate settings (design v2 §8.2)
# ---------------------------------------------------------------------------


def test_gate_judgement_thresholds_hold_their_declared_values():
    # docs/integrated_research_design_v2.md §8.2 declared these on 2026-08-20.
    # Changing a value here invalidates every gate verdict already reported.
    assert dict(GATE_JUDGEMENT_THRESHOLDS) == {
        "time_validity_margin": 0.01,
        "missingness_r2_max": 0.25,
        "raw_concordance_min": 0.50,
        "missingness_pattern_ari_min": 0.20,
    }


def test_gate_probe_parameters_hold_their_declared_values():
    # docs/c2_prereg_v1.md §1.1.  These do not appear in a judgement inequality
    # but they determine the quantity being judged, so they are frozen too.
    assert dict(GATE_PROBE_PARAMETERS) == {
        "artificial_mask_fraction": 0.15,
        "cluster_distance_threshold": 0.30,
        "minimum_cluster_size": 2,
        "seed": 0,
    }


def test_induced_mask_seed_set_holds_its_declared_values():
    # docs/c2_prereg_v1.md §1.3.  The gate verdict is the median over these five,
    # so a single lucky seed is not a verdict.
    assert GATE_INDUCED_MASK_SEED_SET == (0, 1, 2, 3, 4)


def test_frozen_gate_settings_digest_is_stable():
    # Pins the digest so a supplement table can be traced back to this exact
    # threshold set.  Recomputing the constant instead of asserting it would
    # defeat the purpose.
    assert gate_settings_digest() == (
        "0e3eda884ef0a888d40e8429d6bb4375dce1250223e13bbb834153616bb4a0e0"
    )


def test_a_preregistered_seed_is_not_a_deviation():
    # The multi-seed protocol must not read as a pre-registration breach.
    for seed in GATE_INDUCED_MASK_SEED_SET:
        verdict = evaluate_adoption_gates(_passing_metrics(), config={"seed": seed})
        conformance = verdict["frozen_gate_settings"]
        assert conformance["conformant"] is True, seed
        assert conformance["induced_mask_seed_used"] == seed


def test_a_seed_outside_the_declared_set_blocks_production():
    # Otherwise the gate could be passed by searching seeds.
    verdict = evaluate_adoption_gates(
        _passing_metrics(),
        external_evaluations=[{"dataset": "holdout", "improves_baseline": True}],
        config={"seed": 17},
    )
    assert verdict["all_gates_passed"] is True
    assert verdict["production_influence_allowed"] is False
    deviation = verdict["frozen_gate_settings"]["deviations"][0]
    assert deviation["setting"] == "seed"
    assert deviation["direction"] == "outside_declared_set"


def test_benchmark_defaults_do_not_redeclare_the_frozen_settings():
    # A second literal copy is how the two drift apart silently.
    for key, declared in FROZEN_GATE_SETTINGS.items():
        assert DEFAULT_BENCHMARK_CONFIG[key] == declared


def test_default_run_is_conformant_and_records_the_digest():
    verdict = evaluate_adoption_gates(_passing_metrics())
    conformance = verdict["frozen_gate_settings"]
    assert conformance["conformant"] is True
    assert conformance["deviations"] == []
    assert verdict["threshold_override_is_exploratory"] is False
    assert verdict["frozen_gate_settings_digest"] == gate_settings_digest()


def test_relaxed_threshold_cannot_open_production_even_at_six_of_six():
    # The point of §8.2: passing by moving the bar must not count.
    metrics = _passing_metrics()
    metrics["D"]["artificial_masking_probe"]["induced_missingness_r2"] = 0.28
    verdict = evaluate_adoption_gates(
        metrics,
        external_evaluations=[{"dataset": "holdout", "improves_baseline": True}],
        config={"missingness_r2_max": 0.30},
    )
    assert verdict["gates"]["missingness_validity"]["passed"] is True
    assert verdict["all_gates_passed"] is True
    assert verdict["production_influence_allowed"] is False
    assert verdict["threshold_override_is_exploratory"] is True
    deviation = verdict["frozen_gate_settings"]["deviations"][0]
    assert deviation["setting"] == "missingness_r2_max"
    assert deviation["declared"] == 0.25
    assert deviation["used"] == 0.30
    assert deviation["direction"] == "relaxed"
    assert deviation["group"] == "judgement_threshold"


def test_tightened_threshold_also_blocks_production():
    # Reporting a stricter-threshold result as the declared-threshold result is
    # equally a pre-registration deviation, so direction is recorded not judged.
    verdict = evaluate_adoption_gates(
        _passing_metrics(),
        external_evaluations=[{"dataset": "holdout", "improves_baseline": True}],
        config={"raw_concordance_min": 0.70},
    )
    assert verdict["all_gates_passed"] is True
    assert verdict["production_influence_allowed"] is False
    assert verdict["frozen_gate_settings"]["deviations"][0]["direction"] == "tightened"


def test_probe_parameter_override_blocks_production_without_touching_a_threshold():
    # Lowering the mask fraction shrinks the induced target's variance, making
    # the gate easier while every judgement inequality stays put.
    verdict = evaluate_adoption_gates(
        _passing_metrics(),
        external_evaluations=[{"dataset": "holdout", "improves_baseline": True}],
        config={"artificial_mask_fraction": 0.05},
    )
    assert verdict["all_gates_passed"] is True
    assert verdict["production_influence_allowed"] is False
    deviation = verdict["frozen_gate_settings"]["deviations"][0]
    assert deviation["setting"] == "artificial_mask_fraction"
    assert deviation["group"] == "probe_parameter"


def test_contract_summary_publishes_the_frozen_gate_settings():
    contract = describe_contract()
    assert contract["frozen_gate_settings"] == dict(sorted(FROZEN_GATE_SETTINGS.items()))
    assert contract["frozen_gate_settings_digest"] == gate_settings_digest()


def test_frozen_gate_settings_are_immutable_mappings():
    with pytest.raises(TypeError):
        GATE_JUDGEMENT_THRESHOLDS["missingness_r2_max"] = 0.9  # type: ignore[index]
    with pytest.raises(TypeError):
        FROZEN_GATE_SETTINGS["artificial_mask_fraction"] = 0.9  # type: ignore[index]


def test_artificial_masking_hides_entries_without_destroying_sites():
    multiview = _multiview()
    masked, induced = multiview.with_additional_target_masking(fraction=0.2, seed=1)
    assert induced.sum() > 0
    assert masked.provenance["artificial_masking"]["n_masked_entries"] == int(induced.sum())
    # Hidden entries become unobserved and carry no loss weight.
    assert not masked.target.observed[induced].any()
    assert np.all(np.isnan(masked.target.values[induced]))
    assert np.all(masked.quality_weight[induced] == 0.0)
    # Every site keeps at least three observed timepoints.
    assert masked.target.observed.sum(axis=1).min() >= 3
    # The original input is untouched.
    assert multiview.target.observed.sum() > masked.target.observed.sum()


def test_ablation_runs_all_arms_and_reports_a_gate_verdict():
    multiview = build_multiview_input(
        _vector_rows(with_motifs=True), config={"include_motif_side_feature": True}
    )
    result = run_ablation(
        multiview,
        encoder_config=_encoder_config(epochs=40, n_perturbations=2),
        config={"leave_one_out": False, "bootstrap_rounds": 3, "neighbors": 5},
    )
    assert result["status"] == "evaluated"
    assert set(result["variants"]) == {"A", "B", "C", "D", "E"}
    assert {"mask_aware_pca", "mask_aware_nmf", "fpca_lite"} <= set(result["r0_baselines"])
    assert result["adoption_gates"]["production_influence_allowed"] is False
    assert result["variants"]["E"]["time_permutation"] is not None
    assert result["variants"]["A"]["time_permutation"] is None
    # E stays in the table as the multi-view arm, but D is what the gates judge.
    assert result["adoption_gates"]["primary_variant"] == "D"
    assert result["primary_arm_preference"] == ["D", "E"]
    # Everything computable from one cohort is actually computed; only
    # cross-dataset generalization needs an external dataset.
    gates = result["adoption_gates"]["gates"]
    assert gates["time_validity"]["status"] == "evaluated"
    assert gates["missingness_validity"]["status"] == "evaluated"
    assert gates["raw_evidence_concordance"]["status"] == "evaluated"
    assert gates["generalization"]["status"] == "not_evaluated"
    assert result["variants"]["E"]["artificial_masking_probe"]["n_masked_entries"] > 0


def test_ablation_reports_insufficient_data_instead_of_guessing():
    multiview = build_multiview_input(_vector_rows(n_per_shape=1))
    result = run_ablation(multiview)
    assert result["status"] == "insufficient_data"
    assert result["adoption_gates"]["production_influence_allowed"] is False


# ---------------------------------------------------------------------------
# Worker integration
# ---------------------------------------------------------------------------


def test_analyzer_writes_additive_artifacts_and_leaves_the_l1_vector_untouched(tmp_path):
    vector_path = tmp_path / "ptm_vector_data_normalized_phospho.tsv"
    pd.DataFrame(_vector_rows()).to_csv(vector_path, sep="\t", index=False)
    digest_before = hashlib.sha256(vector_path.read_bytes()).hexdigest()

    analyzer = PTMRepresentationLearningAnalyzer(
        output_dir=str(tmp_path),
        file_suffix="_phospho",
        config={"epochs": 40, "latent_dim": 8, "hidden_dim": 24, "n_perturbations": 2,
                "benchmark_epochs": 30, "run_ablation": True, "minimum_sites": 8},
    )
    manifest = analyzer.run(vector_path)

    assert manifest["status"] == "completed"
    assert hashlib.sha256(vector_path.read_bytes()).hexdigest() == digest_before
    assert manifest["preserved_baseline"]["layer_id"] == "L1"
    assert manifest["preserved_baseline"]["modified_by_this_step"] is False
    assert manifest["production_influence_allowed"] is False

    embeddings = pd.read_csv(analyzer.embeddings_path, sep="\t")
    assert len(embeddings) == manifest["n_sites_eligible"]
    assert embeddings["Representation_Layer"].unique().tolist() == [
        "L4_learned_temporal_ptm_embedding"
    ]
    for column in (
        "Site_Key",
        "Gene.Name",
        "PTM_Position",
        "Modified.Sequence",
        "Representation_Reconstruction_Error",
        "Embedding_Neighbor_Stability",
        "Representation_Track_Concordance",
        "Representation_Supported",
        "Representation_Discordant",
        "z000",
    ):
        assert column in embeddings.columns

    stored = json.loads(analyzer.manifest_path.read_text(encoding="utf-8"))
    assert stored["layer_contract"]["contract_version"].startswith("ptm_representation_contract")
    assert stored["input_contract_errors"] == []


def test_analyzer_skips_cleanly_when_there_is_no_temporal_depth(tmp_path):
    vector_path = tmp_path / "ptm_vector_data_normalized_phospho.tsv"
    pd.DataFrame(_vector_rows(n_per_shape=1)).to_csv(vector_path, sep="\t", index=False)
    analyzer = PTMRepresentationLearningAnalyzer(output_dir=str(tmp_path), file_suffix="_phospho")
    manifest = analyzer.run(vector_path)
    assert manifest["status"] == "skipped_insufficient_temporal_data"
    assert not analyzer.embeddings_path.exists()


def test_analyzer_reports_a_missing_vector_file_without_raising(tmp_path):
    analyzer = PTMRepresentationLearningAnalyzer(output_dir=str(tmp_path), file_suffix="_phospho")
    manifest = analyzer.run(tmp_path / "does_not_exist.tsv")
    assert manifest["status"] == "skipped_missing_vector_file"
