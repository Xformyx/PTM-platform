from report_generation.core.measured_feature_cards import (
    build_feature_observation_cards,
    build_quantitation_comparison_cards,
)


def _row(
    gene,
    position,
    condition,
    unadjusted,
    adjusted,
    protein,
    *,
    precursor=None,
    conventional_na=False,
    reconstructed=99.0,
    control_n=None,
    treatment_n=None,
    q_value=None,
    sequence="AS(UniMod:21)TYK",
):
    return {
        "gene": gene,
        "position": position,
        "condition": condition,
        "Precursor.Id": precursor or f"{gene}_{position}",
        "Modified.Sequence": sequence,
        "Protein.Group": f"P_{gene}",
        "ptm_unadjusted_log2fc": unadjusted,
        "ptm_protein_adjusted_log2fc": adjusted,
        "ptm_relative_log2fc": adjusted,
        "protein_log2fc": protein,
        "ptm_reconstructed_log2fc": reconstructed,
        "ptm_unadjusted_conventional_log2fc_na": conventional_na,
        "control_pseudocount_used": conventional_na,
        "ptm_unadjusted_control_n": control_n,
        "ptm_unadjusted_treatment_n": treatment_n,
        "ptm_unadjusted_q_value": q_value,
    }


def _state():
    return {
        "vector_plot_raw_data": [
            _row("GENE1", "S2", "1min", 0.2, 0.1, 0.1),
            _row("GENE1", "S2", "5min", 1.4, 0.8, 0.6),
            _row("GENE1", "S2", "15min", 0.3, -0.2, 0.5),
            _row("GENE2", "T7", "1min", -0.1, -0.2, 0.1),
            _row("GENE2", "T7", "5min", -0.8, -1.1, 0.3),
            _row("GENE2", "T7", "15min", -0.2, -0.3, 0.1),
            _row("GENE3", "Y9", "5min", None, 32.0, 0.0, conventional_na=True),
        ],
    }


def test_feature_cards_name_current_order_features_and_report_time_resolved_values():
    cards = build_feature_observation_cards(_state(), maximum=3)

    assert cards
    assert cards[0]["contract_version"] == "feature_observation_card.v3"
    assert cards[0]["category"] == "measured_feature_observation"
    assert "GENE" in cards[0]["reader_summary"]
    assert "1min" in cards[0]["reader_summary"]
    assert "protein-adjusted PTM" in cards[0]["reader_summary"]
    assert cards[0]["selection_rule"].endswith("no magnitude ranking")
    assert cards[0]["claim_tier"] == "O1"
    assert "direct kinase attribution" in cards[0]["forbidden_interpretations"]
    assert cards[0]["trajectory_shape_fact"]["classification"] in {
        "non_monotonic", "monotonic_increase", "monotonic_decrease", "approximately_stable_within_descriptive_band"
    }


def test_feature_cards_do_not_call_candidate_residue_features_localized_sites_without_localization_evidence():
    cards = build_feature_observation_cards(_state(), maximum=3)
    labels = [card["feature_label"] for card in cards]

    assert any("candidate residue annotation" in label for label in labels)
    assert all("localized phosphorylation feature" not in label for label in labels)


def test_quantitation_comparison_uses_independent_axis_and_excludes_de_novo_and_reconstructed_values():
    cards = build_quantitation_comparison_cards(_state(), maximum=8)

    assert cards
    assert all(card["ptm_unadjusted_log2fc"] is not None for card in cards)
    assert all(card["reconstructed_metric_excluded_from_comparison"] is True for card in cards)
    assert all("GENE3" not in card["feature_label"] for card in cards)
    assert all("+99.000" not in card["reader_summary"] for card in cards)
    assert any(card["comparison_class"] == "direction_changed_after_protein_adjustment" for card in cards)


def test_quantitation_comparison_does_not_claim_that_adjustment_is_biologically_truer():
    cards = build_quantitation_comparison_cards(_state(), maximum=2)

    assert all("does not prove that the adjusted value is biologically truer" in card["counterevidence"] for card in cards)
    assert all(card["claim_tier"] == "O1" for card in cards)


def test_phase2_card_builders_fail_closed_for_legacy_rows_without_independent_unadjusted_values():
    legacy_state = {
        "vector_plot_raw_data": [{
            "gene": "GENE1",
            "position": "S2",
            "condition": "5min",
            "ptm_relative_log2fc": 1.0,
            "protein_log2fc": 0.2,
            "ptm_absolute_log2fc": 1.2,
        }]
    }

    assert build_quantitation_comparison_cards(legacy_state) == []


def test_named_feature_cards_withhold_rows_without_modified_precursor_identity():
    state = {
        "vector_plot_raw_data": [{
            "gene": "AMBIGUOUS", "position": "S10", "condition": "5min",
            "ptm_unadjusted_log2fc": 0.5, "ptm_protein_adjusted_log2fc": 0.3,
            "protein_log2fc": 0.1, "identity_complete_for_reader_cards": False,
        }]
    }

    assert build_feature_observation_cards(state) == []
    assert build_quantitation_comparison_cards(state) == []


def test_named_feature_cards_withhold_duplicate_feature_condition_rows():
    duplicated = _row("GENE1", "S2", "5min", 0.4, 0.3, 0.1, precursor="shared_precursor")
    state = {
        "vector_plot_raw_data": [
            _row("GENE1", "S2", "1min", 0.1, 0.1, 0.0, precursor="shared_precursor"),
            duplicated,
            {**duplicated, "ptm_unadjusted_log2fc": 0.8, "ptm_protein_adjusted_log2fc": 0.7},
        ]
    }

    assert build_feature_observation_cards(state) == []
    assert build_quantitation_comparison_cards(state) == []


def test_non_monotonic_trajectory_fact_prevents_continued_rise_summary():
    state = {
        "vector_plot_raw_data": [
            _row("GENEX", "Y70", "5min", 0.5, 0.496, 0.0, precursor="px"),
            _row("GENEX", "Y70", "15min", 0.1, 0.032, 0.0, precursor="px"),
            _row("GENEX", "Y70", "30min", 0.7, 0.679, 0.0, precursor="px"),
            _row("GENEX", "Y70", "180min", 0.8, 0.751, 0.0, precursor="px"),
        ]
    }
    card = build_feature_observation_cards(state, maximum=1)[0]
    assert card["trajectory_shape_fact"]["classification"] == "non_monotonic"
    assert card["trajectory_shape_fact"]["monotonic_claim_allowed"] is False
    assert "non-monotonic" in card["reader_summary"]


def test_small_sign_change_remains_descriptive_and_reports_shared_protein_adjustment():
    state = {
        "vector_plot_raw_data": [
            _row("GENEA", "S1", "180min", -0.485, 0.157, -0.634, precursor="pa"),
            _row("GENEA", "S2", "180min", -0.300, 0.200, -0.634, precursor="pb"),
        ]
    }
    cards = build_quantitation_comparison_cards(state)
    assert cards
    assert all(card["biological_direction_inference_allowed"] is False for card in cards)
    assert all(card["shared_linked_protein_record_count"] == 2 for card in cards)
    assert all("shared by 2" in card["reader_summary"] for card in cards)


def test_same_gene_residue_different_precursors_are_never_stitched_into_one_trajectory():
    state = {
        "vector_plot_raw_data": [
            _row("GENEA", "S88", "1min", 0.4, 0.3, 0.1, precursor="FORM_CHARGE2", sequence="AS(UniMod:21)TYK"),
            _row("GENEA", "S88", "5min", 1.1, 0.9, 0.2, precursor="FORM_CHARGE3", sequence="AAS(UniMod:21)TYK"),
        ]
    }
    assert build_feature_observation_cards(state) == []


def test_high_quality_incomplete_grid_feature_can_be_reported_without_becoming_cluster_eligible():
    state = {
        "vector_plot_raw_data": [
            _row("CONTEXT", "T185Y187", "5min", 1.0, 0.8, 0.2, precursor="CONTEXT_FORM2", control_n=3, treatment_n=3, q_value=0.01),
            _row("CONTEXT", "T185Y187", "15min", 1.3, 1.0, 0.3, precursor="CONTEXT_FORM2", control_n=3, treatment_n=3, q_value=0.02),
            _row("COMPLETE", "S1", "1min", 0.1, 0.1, 0.0, precursor="COMPLETE_FORM2"),
            _row("COMPLETE", "S1", "5min", 0.2, 0.2, 0.0, precursor="COMPLETE_FORM2"),
            _row("COMPLETE", "S1", "15min", 0.3, 0.3, 0.0, precursor="COMPLETE_FORM2"),
        ]
    }
    cards = build_feature_observation_cards(state, maximum=2)
    context = next(card for card in cards if card["feature_identity"]["gene"] == "CONTEXT")
    assert context["narrative_quality_tier"] == "high"
    assert context["display_eligible"] is True
    assert context["clustering_eligible"] is False
    assert cards[0]["feature_identity"]["gene"] == "CONTEXT"


def test_corrupt_legacy_enriched_site_aggregate_is_not_used_as_card_source():
    state = {
        "enriched_ptm_data": [{
            "gene": "LEGACY", "position": "S1", "Precursor.Id": "FORM2", "Modified.Sequence": "AS(UniMod:21)TYK",
            "site_form_trajectories": [{"site_form_key": "LEGACY_S1|seq=A|z=nan"}],
            "site_aggregation": {"form_count": 1},
            "site_form_provenance_audit": {"status": "incompatible", "report_eligible": False},
            "report_eligible_temporal_site_aggregation": False,
            "condition_data": [
                {"condition": "1min", "ptm_relative_log2fc": 0.2},
                {"condition": "5min", "ptm_relative_log2fc": 0.8},
            ],
        }]
    }
    assert build_feature_observation_cards(state) == []
