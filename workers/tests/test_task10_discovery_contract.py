"""TASK-10 synthetic acceptance fixtures; no experiment or literature retrieval."""
import pytest

from report_generation.core.biological_synthesis import _profile_label
from report_generation.core.reader_authoring import build_authoring_packet


def candidate():
    return {
        "gene": "UNEXPLAINED", "position": "S7", "precursor_id": "precursor-one",
        "trajectory": [{"condition": "5min", "ptm_relative_log2fc": 1.,
                        "ptm_unadjusted_log2fc": 1., "protein_log2fc": 0.}],
        "discovery_rationale": ["observed precursor with unavailable kinase annotation"],
    }


@pytest.mark.parametrize("field", ["selected_cards", "candidate_cards", "cards"])
def test_t10_01_production_and_legacy_candidate_adapter(field):
    packet = build_authoring_packet({}, biological_synthesis_packet={
        "candidate_discovery_packet": {field: [candidate()], "selection_summary": {"selected": 1}},
    })
    cards = [c for c in packet["reader_cards"] if c["category"] == "candidate_discovery"]
    assert len(cards) == 1
    assert "not generated" not in cards[0]["reader_summary"]
    assert cards[0]["feature_identity"]["source_feature_id"] == "precursor-one"
    assert cards[0]["trajectory"][0]["ptm_unadjusted_log2fc"] == 1.
    assert packet["candidate_transfer_audit"]["input_count"] == 1
    assert packet["candidate_transfer_audit"]["reader_card_count"] == 1


@pytest.mark.parametrize("values, expected", [
    ([0., 0., 0.], "stable-near-reference"),
    ([1., 1., 1.], "constant-positive-level"),
    ([-1., -1., -1.], "constant-negative-level"),
    ([1., .1, 1.], "tied-observed-extrema"),
    ([1., None, .1], "partial-observation"),
])
def test_t10_02_flat_tied_and_missing_trajectories_do_not_invent_early_peak(values, expected):
    points = [{"condition": c, "ptm_relative_log2fc": v}
              for c, v in zip(["0min", "5min", "180min"], values)]
    assert _profile_label(points) == expected


def test_flat_producer_does_not_leak_first_condition_as_peak_to_legacy_prompt():
    from report_generation.core.biological_synthesis import _candidate_cards
    rows = [{"gene": "FLAT", "position": "S7", "precursor_id": "flat-form",
             "condition": condition, "ptm_protein_adjusted_log2fc": 1.,
             "ptm_unadjusted_log2fc": 1., "protein_log2fc": 0.}
            for condition in ("5min", "40min", "180min")]
    cards, _ = _candidate_cards(rows, limit=1)
    assert cards[0]["profile_label"] == "constant-positive-level"
    assert cards[0]["peak_condition"] is None


def test_de_novo_display_context_does_not_enter_new_axis_pattern_extrema():
    from report_generation.core.measured_feature_cards import build_feature_observation_cards
    rows = [{"gene": "MIXED", "position": "S7", "precursor_id": "mixed-form",
             "condition": "5min", "ptm_unadjusted_log2fc": .2, "ptm_protein_adjusted_log2fc": .1},
            {"gene": "MIXED", "position": "S7", "precursor_id": "mixed-form",
             "condition": "40min", "ptm_unadjusted_log2fc": 20., "ptm_protein_adjusted_log2fc": 20.,
             "Conventional_Log2FC_NA": True}]
    card = build_feature_observation_cards({"vector_plot_raw_data": rows}, minimum_points=1)[0]
    assert card["axis_patterns"]["adjusted"]["missing_conditions"] == ["40min"]
    assert all(abs(p["value"]) < 1 for p in card["axis_patterns"]["adjusted"]["observed_extrema"])
