"""Tests for study_temporal_context.py and the generalised timepoint parser.

Covers:
  - _parse_timepoint_label / _timepoints_to_minutes for all study types
  - compute_gp_length_scale_from_grid
  - infer_context_from_grid
  - StudyTemporalContext.validate()
  - Pre-registered insulin context
"""

from __future__ import annotations

import math
import warnings

import pytest

from ptm_shared.probabilistic_cowave import (
    _parse_timepoint_label,
    _timepoints_to_minutes,
)
from ptm_shared.study_temporal_context import (
    CELL_CYCLE_TEMPORAL_CONTEXT_DRAFT,
    EGF_TEMPORAL_CONTEXT_DRAFT,
    HYPOXIA_TEMPORAL_CONTEXT_DRAFT,
    INSULIN_TEMPORAL_CONTEXT,
    StudyTemporalContext,
    compute_gp_length_scale_from_grid,
    get_context_for_study,
    infer_context_from_grid,
)


# ── _parse_timepoint_label ────────────────────────────────────────────────

class TestParseTimepointLabel:
    def test_minutes_min_suffix(self):
        assert _parse_timepoint_label("15min") == pytest.approx(15.0)

    def test_minutes_m_suffix(self):
        assert _parse_timepoint_label("5m") == pytest.approx(5.0)

    def test_minutes_bare_number(self):
        assert _parse_timepoint_label("30") == pytest.approx(30.0)

    def test_minutes_with_space(self):
        assert _parse_timepoint_label("15 min") == pytest.approx(15.0)

    def test_hours_hr_suffix(self):
        assert _parse_timepoint_label("2hr") == pytest.approx(120.0)

    def test_hours_h_suffix(self):
        assert _parse_timepoint_label("4h") == pytest.approx(240.0)

    def test_hours_hour_suffix(self):
        assert _parse_timepoint_label("1hour") == pytest.approx(60.0)

    def test_hours_hours_suffix(self):
        assert _parse_timepoint_label("8hours") == pytest.approx(480.0)

    def test_days_day_suffix(self):
        assert _parse_timepoint_label("1day") == pytest.approx(1440.0)

    def test_days_d_suffix(self):
        assert _parse_timepoint_label("3d") == pytest.approx(4320.0)

    def test_seconds_s_suffix(self):
        assert _parse_timepoint_label("30s") == pytest.approx(0.5)

    def test_seconds_sec_suffix(self):
        assert _parse_timepoint_label("60sec") == pytest.approx(1.0)

    def test_zero_minute(self):
        assert _parse_timepoint_label("0min") == pytest.approx(0.0)

    def test_zero_hour(self):
        assert _parse_timepoint_label("0hr") == pytest.approx(0.0)

    def test_float_minutes(self):
        assert _parse_timepoint_label("0.5min") == pytest.approx(0.5)

    def test_unparseable_returns_none(self):
        assert _parse_timepoint_label("early") is None

    def test_case_insensitive(self):
        assert _parse_timepoint_label("15MIN") == pytest.approx(15.0)
        assert _parse_timepoint_label("2HR") == pytest.approx(120.0)


# ── _timepoints_to_minutes ────────────────────────────────────────────────

class TestTimepointsToMinutes:
    def test_insulin_grid_unchanged(self):
        labels = ["1min", "5min", "15min", "30min", "60min", "180min"]
        result = _timepoints_to_minutes(labels)
        assert list(result) == pytest.approx([1, 5, 15, 30, 60, 180])

    def test_hypoxia_hours_converts_correctly(self):
        """'48hr' must NOT fall back to index 4 — actual 2880 min expected."""
        labels = ["0hr", "2hr", "8hr", "24hr", "48hr"]
        result = _timepoints_to_minutes(labels)
        assert list(result) == pytest.approx([0, 120, 480, 1440, 2880])

    def test_cell_cycle_h_suffix(self):
        labels = ["0h", "4h", "8h", "12h", "16h", "20h", "24h"]
        result = _timepoints_to_minutes(labels)
        assert list(result) == pytest.approx([0, 240, 480, 720, 960, 1200, 1440])

    def test_developmental_days(self):
        labels = ["0day", "1day", "2day", "3day"]
        result = _timepoints_to_minutes(labels)
        assert list(result) == pytest.approx([0, 1440, 2880, 4320])

    def test_bare_numbers_treated_as_minutes(self):
        labels = ["0", "5", "15", "30"]
        result = _timepoints_to_minutes(labels)
        assert list(result) == pytest.approx([0, 5, 15, 30])

    def test_unparseable_falls_back_to_index_with_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _timepoints_to_minutes(["early", "mid", "late"])
        assert len(w) == 1
        assert issubclass(w[0].category, UserWarning)
        assert list(result) == pytest.approx([0, 1, 2])

    def test_mixed_minutes_seconds(self):
        labels = ["30s", "1min", "5min"]
        result = _timepoints_to_minutes(labels)
        assert list(result) == pytest.approx([0.5, 1.0, 5.0])


# ── compute_gp_length_scale_from_grid ────────────────────────────────────

class TestComputeGPLengthScale:
    def test_insulin_gives_reasonable_value(self):
        labels = ["1min", "5min", "15min", "30min", "60min", "180min"]
        ls = compute_gp_length_scale_from_grid(labels)
        # min interval = 4 min, scale=3 → 12.0
        assert ls == pytest.approx(12.0)

    def test_hypoxia_gives_hours_scale(self):
        labels = ["0hr", "2hr", "8hr", "24hr", "48hr"]
        ls = compute_gp_length_scale_from_grid(labels)
        # min interval = 120 min, scale=3 → 360.0
        assert ls == pytest.approx(360.0)

    def test_cell_cycle_gives_12hr_scale(self):
        labels = ["0h", "4h", "8h", "12h", "16h", "20h", "24h"]
        ls = compute_gp_length_scale_from_grid(labels)
        # min interval = 240 min, scale=3 → 720.0
        assert ls == pytest.approx(720.0)

    def test_custom_scale_factor(self):
        labels = ["0min", "10min", "20min"]
        assert compute_gp_length_scale_from_grid(labels, scale_factor=2.0) == pytest.approx(20.0)

    def test_single_interval(self):
        labels = ["0min", "5min"]
        ls = compute_gp_length_scale_from_grid(labels)
        assert ls == pytest.approx(15.0)


# ── infer_context_from_grid ───────────────────────────────────────────────

class TestInferContextFromGrid:
    def test_insulin_infers_minutes_unit(self):
        ctx = infer_context_from_grid(
            ["1min", "5min", "15min", "30min", "60min", "180min"],
            study_id="test_insulin",
        )
        assert ctx.time_unit_label == "minutes"
        assert ctx.nominal_grid_interval_minutes == pytest.approx(4.0)
        assert ctx.pre_registered is False

    def test_hypoxia_infers_hours_unit(self):
        ctx = infer_context_from_grid(
            ["0hr", "2hr", "8hr", "24hr", "48hr"],
            study_id="test_hypoxia",
        )
        assert ctx.time_unit_label == "hours"
        assert ctx.nominal_grid_interval_minutes == pytest.approx(120.0)

    def test_developmental_infers_days_unit(self):
        ctx = infer_context_from_grid(
            ["0day", "1day", "2day", "3day"],
            study_id="test_dev",
        )
        assert ctx.time_unit_label == "days"

    def test_synchrony_tau_equals_min_interval(self):
        ctx = infer_context_from_grid(
            ["0h", "4h", "8h", "12h"],
            study_id="test_cc",
        )
        assert ctx.synchrony_tau_minutes == pytest.approx(ctx.nominal_grid_interval_minutes)

    def test_inferred_censoring_notes_reference_grid(self):
        labels = ["0hr", "2hr", "48hr"]
        ctx = infer_context_from_grid(labels, study_id="test")
        assert "0hr" in ctx.censoring_left_note
        assert "48hr" in ctx.censoring_right_note


# ── StudyTemporalContext.validate() ──────────────────────────────────────

class TestStudyTemporalContextValidate:
    def test_valid_insulin_context(self):
        INSULIN_TEMPORAL_CONTEXT.validate()

    def test_raises_when_length_scale_too_small(self):
        ctx = StudyTemporalContext(
            study_id="bad",
            time_unit_label="minutes",
            nominal_grid_interval_minutes=10.0,
            gp_length_scale_min_minutes=5.0,  # < grid interval
            synchrony_tau_minutes=10.0,
            gp_length_scale_source="test",
            chemical_holdout_description="test",
        )
        with pytest.raises(ValueError, match="length scale shorter than grid interval"):
            ctx.validate()

    def test_raises_when_tau_zero(self):
        ctx = StudyTemporalContext(
            study_id="bad",
            time_unit_label="minutes",
            nominal_grid_interval_minutes=5.0,
            gp_length_scale_min_minutes=15.0,
            synchrony_tau_minutes=0.0,
            gp_length_scale_source="test",
            chemical_holdout_description="test",
        )
        with pytest.raises(ValueError, match="synchrony_tau_minutes"):
            ctx.validate()


# ── Pre-registered contexts ───────────────────────────────────────────────

class TestPreRegisteredContexts:
    def test_insulin_is_pre_registered(self):
        assert INSULIN_TEMPORAL_CONTEXT.pre_registered is True

    def test_insulin_gp_length_scale(self):
        assert INSULIN_TEMPORAL_CONTEXT.gp_length_scale_min_minutes == pytest.approx(15.0)

    def test_insulin_synchrony_tau(self):
        assert INSULIN_TEMPORAL_CONTEXT.synchrony_tau_minutes == pytest.approx(5.0)

    def test_draft_contexts_not_pre_registered(self):
        for ctx in [EGF_TEMPORAL_CONTEXT_DRAFT, HYPOXIA_TEMPORAL_CONTEXT_DRAFT,
                    CELL_CYCLE_TEMPORAL_CONTEXT_DRAFT]:
            assert ctx.pre_registered is False

    def test_draft_contexts_validate_without_error(self):
        for ctx in [EGF_TEMPORAL_CONTEXT_DRAFT, HYPOXIA_TEMPORAL_CONTEXT_DRAFT,
                    CELL_CYCLE_TEMPORAL_CONTEXT_DRAFT]:
            ctx.validate()

    def test_hypoxia_length_scale_in_hour_range(self):
        # 360 min = 6 hr — appropriate for HIF1α timescale
        assert HYPOXIA_TEMPORAL_CONTEXT_DRAFT.gp_length_scale_min_minutes >= 60.0

    def test_cell_cycle_length_scale_in_multi_hour_range(self):
        # 720 min = 12 hr — appropriate for cell cycle
        assert CELL_CYCLE_TEMPORAL_CONTEXT_DRAFT.gp_length_scale_min_minutes >= 240.0

    def test_get_context_for_insulin(self):
        ctx = get_context_for_study("insulin_signaling_rat_phosphoproteomics")
        assert ctx is INSULIN_TEMPORAL_CONTEXT

    def test_get_context_missing_returns_none(self):
        assert get_context_for_study("unknown_study") is None
