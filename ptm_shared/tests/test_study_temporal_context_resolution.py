"""Tests for generic Order metadata to temporal-context resolution."""

from ptm_shared.study_temporal_context_resolution import resolve_study_temporal_context


TIMEPOINTS = ["1min", "5min", "15min", "30min", "60min", "180min"]


def test_grid_only_context_is_draft_and_does_not_inject_known_relations() -> None:
    context, provenance = resolve_study_temporal_context(
        experimental_context={"treatment": "arbitrary_new_compound"},
        declared_conditions=TIMEPOINTS,
        study_id="order_100",
    )

    assert context is not None
    assert context.study_id == "order_100"
    assert context.pre_registered is False
    assert context.known_relation_registry_path is None
    assert provenance["status"] == "draft_context_inferred_from_declared_grid"
    assert provenance["known_relation_registry_enabled"] is False
    assert provenance["context"]["gp_length_scale_min_minutes"] == 12.0


def test_explicit_context_strips_runner_only_relation_registry() -> None:
    context, provenance = resolve_study_temporal_context(
        experimental_context={
            "temporal_context": {
                "study_id": "drug_x_cell_y",
                "time_unit_label": "minutes",
                "nominal_grid_interval_minutes": 5.0,
                "gp_length_scale_min_minutes": 15.0,
                "synchrony_tau_minutes": 5.0,
                "gp_length_scale_source": "pre-registered study protocol",
                "chemical_holdout_description": "independent replicate cohort",
                "known_relation_registry_path": "benchmarking/known_insulin_relations.json",
                "pre_registered": True,
            }
        },
        declared_conditions=TIMEPOINTS,
        study_id="ignored_when_explicit",
    )

    assert context is not None
    assert context.study_id == "drug_x_cell_y"
    assert context.pre_registered is True
    assert context.known_relation_registry_path is None
    assert provenance["status"] == "explicit_context"
    assert provenance["known_relation_registry_enabled"] is False


def test_single_timepoint_is_explicitly_not_evaluable() -> None:
    context, provenance = resolve_study_temporal_context(
        experimental_context={},
        declared_conditions=["24hr"],
        study_id="snapshot_order",
    )

    assert context is None
    assert provenance["status"] == "not_evaluable_insufficient_declared_timepoints"
