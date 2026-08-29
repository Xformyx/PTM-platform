"""Study-specific temporal context for time-course PTM analyses.

PURPOSE
-------
The PTM platform was initially calibrated on insulin signaling (1–180 min).
When applied to other time-course studies — EGF signaling, hypoxia response,
cell cycle, developmental biology, drug pharmacodynamics — every temporal
parameter must be re-derived from the study's measurement grid, not copied
from insulin defaults.

This module provides:
  StudyTemporalContext   — study-specific temporal configuration contract
  infer_context_from_grid() — auto-derive safe defaults from timepoint labels
  compute_gp_length_scale_from_grid() — GP length scale from grid intervals
  INSULIN_TEMPORAL_CONTEXT — reference insulin configuration
  Example contexts for EGF, hypoxia, cell cycle, developmental

HOW TO USE
----------
1. For insulin (existing): use INSULIN_TEMPORAL_CONTEXT directly.
2. For a new study: call infer_context_from_grid(timepoint_labels, study_id).
   Then review and pre-register the derived values before analysis begins.
3. Pass context.gp_length_scale_min_minutes to estimate_trajectory_posterior().
4. Pass context.synchrony_tau_minutes to the Within-Wave synchrony test (P1).

CLAIM BOUNDARIES
----------------
No temporal context object implies or enables claims beyond:
  "Observed temporal precedence with uncertainty within the measured time window."
Use chemical/genetic holdout validation (study-specific, see chemical_holdout_description)
before making mechanistic claims.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from ptm_shared.probabilistic_cowave import _timepoints_to_minutes


@dataclass(frozen=True)
class StudyTemporalContext:
    """Frozen study-specific temporal configuration.

    All time values are stored in **minutes** for consistency with the
    canonical internal representation.  Display formatting (e.g., "2 hr")
    is handled separately.

    Attributes
    ----------
    study_id : str
        Human-readable study identifier (e.g., "insulin_signaling_rat").
    time_unit_label : str
        Display unit for the study ("minutes", "hours", "days") — for reporting only.
    nominal_grid_interval_minutes : float
        Minimum time interval in the measurement grid (minutes).
        Drives default synchrony_tau and gp_length_scale derivation.
    gp_length_scale_min_minutes : float
        Minimum GP length scale (minutes).  Must be pre-registered before analysis.
        Rule of thumb: 2–4× the nominal_grid_interval.  Biological rationale required.
    synchrony_tau_minutes : float
        τ for Within-Wave onset-synchrony test: P(|t_i - t_j| ≤ τ).
        Should equal the nominal_grid_interval (one grid step as the resolution limit).
        Source: PDF §2A "early interval resolution에 맞춘 5 min" (insulin-specific example).
    gp_length_scale_source : str
        Citation/rationale for the chosen length scale (required for pre-registration).
    chemical_holdout_description : str
        Description of the validation holdout for this study (study-specific equivalent
        of Trametinib/mirdametinib for insulin).
    known_relation_registry_path : str | None
        Path to a study-specific known-relation registry (runner-only).
        Format per relation: (source_event, target_event, allowed_lag_min,
        expected_direction, evidence_tier).
    censoring_left_note : str
        Human note about left-censoring (onset before first timepoint).
    censoring_right_note : str
        Human note about right-censoring (response not resolved by last timepoint).
    pre_registration_date : str
        ISO date when this context was frozen (YYYY-MM-DD).
    pre_registered : bool
        Must be True before context is used in primary analysis.
        Set to False for exploratory/draft contexts.
    """

    study_id: str
    time_unit_label: str
    nominal_grid_interval_minutes: float
    gp_length_scale_min_minutes: float
    synchrony_tau_minutes: float
    gp_length_scale_source: str
    chemical_holdout_description: str
    known_relation_registry_path: str | None = None
    censoring_left_note: str = "onset before first measured timepoint → left_censored"
    censoring_right_note: str = "response not resolved by last timepoint → right_censored"
    pre_registration_date: str = "unregistered"
    pre_registered: bool = False

    def validate(self) -> None:
        """Raise if context violates basic consistency constraints."""
        if self.gp_length_scale_min_minutes < self.nominal_grid_interval_minutes:
            raise ValueError(
                f"gp_length_scale_min_minutes ({self.gp_length_scale_min_minutes}) "
                f"< nominal_grid_interval_minutes ({self.nominal_grid_interval_minutes}): "
                "length scale shorter than grid interval will overfit to grid noise."
            )
        if self.synchrony_tau_minutes <= 0:
            raise ValueError("synchrony_tau_minutes must be > 0.")
        if not self.gp_length_scale_source:
            raise ValueError("gp_length_scale_source must be documented.")


def compute_gp_length_scale_from_grid(
    timepoint_labels: Sequence[str],
    *,
    scale_factor: float = 3.0,
) -> float:
    """Suggest GP length scale from the minimum grid interval.

    Derivation:
      length_scale = scale_factor × min(Δt_i)
      scale_factor=3 means "smooth over 3 grid steps"; prevents single-timepoint
      overfitting without washing out events at the Nyquist rate.

    This is a STARTING POINT for biological review, not a pre-registered value.
    The returned value must be reviewed against known signaling timescales for
    the study system before pre-registration.

    Parameters
    ----------
    timepoint_labels : sequence of str
        Labels parseable by _parse_timepoint_label() (any unit).
    scale_factor : float
        Multiplier applied to minimum interval.  3.0 is conservative default.

    Returns
    -------
    float
        Suggested length scale in minutes.

    Examples
    --------
    Insulin (min intervals [4, 10, 15, 30, 120]):
        compute_gp_length_scale_from_grid(["1min","5min","15min","30min","60min","180min"])
        → 3.0 × 4.0 = 12.0 min  (close to pre-registered 15.0, reasonable)

    Hypoxia (hr intervals [2, 6, 16, 24] hr = [120, 360, 960, 1440] min):
        compute_gp_length_scale_from_grid(["0hr","2hr","8hr","24hr","48hr"])
        → 3.0 × 120.0 = 360.0 min (6 hr smoothing)

    Cell cycle (4 hr intervals = 240 min):
        compute_gp_length_scale_from_grid(["0h","4h","8h","12h","16h","20h","24h"])
        → 3.0 × 240.0 = 720.0 min (12 hr smoothing)
    """
    minutes = _timepoints_to_minutes(list(timepoint_labels))
    diffs = [abs(float(minutes[i + 1] - minutes[i])) for i in range(len(minutes) - 1)]
    if not diffs:
        return scale_factor * 1.0
    min_interval = min(d for d in diffs if d > 0) if any(d > 0 for d in diffs) else 1.0
    return round(scale_factor * min_interval, 2)


def infer_context_from_grid(
    timepoint_labels: Sequence[str],
    study_id: str,
    *,
    chemical_holdout_description: str = "NOT_SPECIFIED — must be defined before primary analysis",
    known_relation_registry_path: str | None = None,
    scale_factor: float = 3.0,
) -> StudyTemporalContext:
    """Infer a draft StudyTemporalContext from timepoint labels.

    The returned context has pre_registered=False; review derived values and
    call .validate() before freezing for primary analysis.

    Parameters
    ----------
    timepoint_labels : sequence of str
        All timepoint labels in chronological order.
    study_id : str
        Human-readable study identifier.
    chemical_holdout_description : str
        Required: describe the chemical/genetic holdout for this study.
    scale_factor : float
        Passed to compute_gp_length_scale_from_grid().
    """
    minutes = _timepoints_to_minutes(list(timepoint_labels))
    diffs = [abs(float(minutes[i + 1] - minutes[i])) for i in range(len(minutes) - 1)]
    min_interval = min((d for d in diffs if d > 0), default=1.0)

    # Infer display unit from label suffixes, not from raw minute magnitudes.
    # This keeps "180min" → "minutes" rather than accidentally → "hours".
    labels_lower = [str(lb).strip().lower().replace(" ", "") for lb in timepoint_labels]
    if any(lb.endswith(("day", "days", "d")) and not lb.endswith(("day",) + ()) for lb in labels_lower):
        unit_label = "days"
    elif any(lb.endswith(("days", "day")) for lb in labels_lower):
        unit_label = "days"
    elif any(lb.endswith(("hours", "hour", "hr", "h"))
             and not lb.endswith(("min",))
             for lb in labels_lower):
        unit_label = "hours"
    elif any(lb.endswith(("minutes", "minute", "min", "m")) for lb in labels_lower):
        unit_label = "minutes"
    else:
        # Bare numbers: use magnitude heuristic
        max_minutes = float(max(minutes)) if len(minutes) else 0.0
        if max_minutes >= 2880:
            unit_label = "days"
        elif max_minutes >= 180:
            unit_label = "hours"
        else:
            unit_label = "minutes"

    gp_ls = compute_gp_length_scale_from_grid(timepoint_labels, scale_factor=scale_factor)

    return StudyTemporalContext(
        study_id=study_id,
        time_unit_label=unit_label,
        nominal_grid_interval_minutes=round(min_interval, 4),
        gp_length_scale_min_minutes=gp_ls,
        synchrony_tau_minutes=round(min_interval, 4),
        gp_length_scale_source=(
            f"auto-derived: {scale_factor}× min_interval ({min_interval:.2f} min). "
            "REVIEW REQUIRED before pre-registration."
        ),
        chemical_holdout_description=chemical_holdout_description,
        known_relation_registry_path=known_relation_registry_path,
        censoring_left_note=f"onset before {timepoint_labels[0]} → left_censored",
        censoring_right_note=f"response not resolved by {timepoint_labels[-1]} → right_censored",
        pre_registration_date="unregistered",
        pre_registered=False,
    )


# ── Pre-registered study contexts ─────────────────────────────────────────

INSULIN_TEMPORAL_CONTEXT = StudyTemporalContext(
    study_id="insulin_signaling_rat_phosphoproteomics",
    time_unit_label="minutes",
    nominal_grid_interval_minutes=4.0,   # 1→5 min, smallest interval
    gp_length_scale_min_minutes=15.0,    # PI3K-AKT ~5-15 min, ERK ~5-30 min
    synchrony_tau_minutes=5.0,           # one early grid step = 5 min (1→5)
    gp_length_scale_source=(
        "Humphrey 2013 Cell Metab; Parker 2015 Sci Signal. "
        "PI3K-AKT peak ~5-15 min, ERK peak ~5-30 min. "
        "15 min is conservative mid-range. Pre-registered 2026-08-28."
    ),
    chemical_holdout_description=(
        "Trametinib (MEK inhibitor) as primary interaction-response validation; "
        "mirdametinib as fixed-pipeline chemical holdout (Q2 reproducibility). "
        "ΔMEK = [IM − M] − [I − V]. Frozen pipeline required before use."
    ),
    known_relation_registry_path="benchmarking/known_insulin_relations.json",
    censoring_left_note="onset before 1 min → left_censored (0 min baseline not sampled)",
    censoring_right_note="response not resolved by 180 min → right_censored",
    pre_registration_date="2026-08-29",
    pre_registered=True,
)
"""Insulin signaling reference context (pre-registered 2026-08-29).

Timepoints: 1, 5, 15, 30, 60, 180 min.
Do NOT copy gp_length_scale_min_minutes=15 to other studies without biological justification.
"""

EGF_TEMPORAL_CONTEXT_DRAFT = StudyTemporalContext(
    study_id="egf_signaling_human_phosphoproteomics_DRAFT",
    time_unit_label="minutes",
    nominal_grid_interval_minutes=2.0,   # 0→2 min, typical early EGF grid
    gp_length_scale_min_minutes=6.0,     # 3× min_interval; EGFR peak ~2-5 min
    synchrony_tau_minutes=2.0,
    gp_length_scale_source=(
        "auto-derived 3×2=6 min. DRAFT — review against EGFR/ERK timescale "
        "(Cohen 2000, Citri & Yarden 2006). Pre-register before primary analysis."
    ),
    chemical_holdout_description=(
        "DRAFT: Gefitinib or Erlotinib (EGFR inhibitor) as primary holdout; "
        "define before data analysis."
    ),
    censoring_left_note="onset before 0 min — verify 0 is a true unstimulated baseline",
    censoring_right_note="response not resolved by last timepoint → right_censored",
    pre_registration_date="unregistered",
    pre_registered=False,
)
"""Draft EGF signaling context. NOT pre-registered. Review before use."""

HYPOXIA_TEMPORAL_CONTEXT_DRAFT = StudyTemporalContext(
    study_id="hypoxia_response_DRAFT",
    time_unit_label="hours",
    nominal_grid_interval_minutes=120.0,  # 2 hr in minutes
    gp_length_scale_min_minutes=360.0,   # 3×2 hr = 6 hr smoothing
    synchrony_tau_minutes=120.0,          # τ = 2 hr (one grid step)
    gp_length_scale_source=(
        "auto-derived 3×120=360 min. DRAFT — review against HIF1α stabilisation "
        "timescale (~1-4 hr). Pre-register before primary analysis."
    ),
    chemical_holdout_description=(
        "DRAFT: HIF PHD inhibitor (e.g., Roxadustat/FG-4592) as primary holdout; "
        "define before data analysis."
    ),
    censoring_left_note="onset before 0 hr — verify normoxic baseline",
    censoring_right_note="response not resolved by last timepoint → right_censored",
    pre_registration_date="unregistered",
    pre_registered=False,
)
"""Draft hypoxia response context (hours). NOT pre-registered."""

CELL_CYCLE_TEMPORAL_CONTEXT_DRAFT = StudyTemporalContext(
    study_id="cell_cycle_synchronised_DRAFT",
    time_unit_label="hours",
    nominal_grid_interval_minutes=240.0,  # 4 hr in minutes
    gp_length_scale_min_minutes=720.0,   # 3×4 hr = 12 hr smoothing
    synchrony_tau_minutes=240.0,          # τ = 4 hr
    gp_length_scale_source=(
        "auto-derived 3×240=720 min. DRAFT — review against CDK1/2 activation timescale. "
        "Pre-register before primary analysis."
    ),
    chemical_holdout_description=(
        "DRAFT: CDK inhibitor (e.g., Palbociclib/CDK4/6, RO-3306/CDK1) as primary holdout; "
        "define before data analysis."
    ),
    censoring_left_note="onset before release from synchronisation → left_censored",
    censoring_right_note="response extends past last timepoint → right_censored",
    pre_registration_date="unregistered",
    pre_registered=False,
)
"""Draft cell cycle context (4-hr intervals). NOT pre-registered."""


def get_context_for_study(study_id: str) -> StudyTemporalContext | None:
    """Look up a pre-registered or draft context by study_id.

    Returns None if no matching context is found; caller should then use
    infer_context_from_grid() to create a draft context.
    """
    registry = {
        ctx.study_id: ctx
        for ctx in [
            INSULIN_TEMPORAL_CONTEXT,
            EGF_TEMPORAL_CONTEXT_DRAFT,
            HYPOXIA_TEMPORAL_CONTEXT_DRAFT,
            CELL_CYCLE_TEMPORAL_CONTEXT_DRAFT,
        ]
    }
    return registry.get(study_id)
