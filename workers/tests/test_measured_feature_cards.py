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
):
    return {
        "gene": gene,
        "position": position,
        "condition": condition,
        "Precursor.Id": precursor or f"{gene}_{position}",
        "Modified.Sequence": "AS(UniMod:21)TYK",
        "Protein.Group": f"P_{gene}",
        "ptm_unadjusted_log2fc": unadjusted,
        "ptm_protein_adjusted_log2fc": adjusted,
        "ptm_relative_log2fc": adjusted,
        "protein_log2fc": protein,
        "ptm_reconstructed_log2fc": reconstructed,
        "ptm_unadjusted_conventional_log2fc_na": conventional_na,
        "control_pseudocount_used": conventional_na,
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
    assert cards[0]["contract_version"] == "feature_observation_card.v1"
    assert cards[0]["category"] == "measured_feature_observation"
    assert "GENE" in cards[0]["reader_summary"]
    assert "1min" in cards[0]["reader_summary"]
    assert "protein-adjusted PTM" in cards[0]["reader_summary"]
    assert cards[0]["selection_rule"].endswith("no magnitude ranking")
    assert cards[0]["claim_tier"] == "O1"
    assert "direct kinase attribution" in cards[0]["forbidden_interpretations"]


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
