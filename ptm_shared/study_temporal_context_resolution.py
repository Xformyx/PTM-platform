"""Resolve a study-local temporal context from explicit Order metadata.

The resolver never selects a pathway, kinase, or relation registry.  When an
Order has not supplied a frozen study context, it derives a *draft* context
from the declared measured time grid only.  Draft contexts allow descriptive
event-time output but keep pre_registered=False, so downstream consumers must
retain the observational/exploratory claim ceiling.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from ptm_shared.study_temporal_context import StudyTemporalContext, infer_context_from_grid


def _context_from_mapping(value: Mapping[str, Any]) -> StudyTemporalContext:
    fields = {
        "study_id": value.get("study_id"),
        "time_unit_label": value.get("time_unit_label"),
        "nominal_grid_interval_minutes": value.get("nominal_grid_interval_minutes"),
        "gp_length_scale_min_minutes": value.get("gp_length_scale_min_minutes"),
        "synchrony_tau_minutes": value.get("synchrony_tau_minutes"),
        "gp_length_scale_source": value.get("gp_length_scale_source"),
        "chemical_holdout_description": value.get("chemical_holdout_description"),
        "known_relation_registry_path": value.get("known_relation_registry_path"),
        "censoring_left_note": value.get("censoring_left_note") or "onset before first measured timepoint → left_censored",
        "censoring_right_note": value.get("censoring_right_note") or "response not resolved by last timepoint → right_censored",
        "pre_registration_date": value.get("pre_registration_date") or "unregistered",
        "pre_registered": bool(value.get("pre_registered", False)),
    }
    if not all(fields[key] not in (None, "") for key in (
        "study_id", "time_unit_label", "nominal_grid_interval_minutes",
        "gp_length_scale_min_minutes", "synchrony_tau_minutes",
        "gp_length_scale_source", "chemical_holdout_description",
    )):
        raise ValueError("declared temporal_context is missing required fields")
    context = StudyTemporalContext(**fields)
    context.validate()
    return context


def resolve_study_temporal_context(
    *,
    experimental_context: Mapping[str, Any] | None,
    declared_conditions: Sequence[str],
    study_id: str,
) -> tuple[StudyTemporalContext | None, dict[str, Any]]:
    """Resolve context without applying any treatment- or pathway-specific prior.

    An explicit ``experimental_context.temporal_context`` is honored after
    validation.  Otherwise, two or more parseable declared conditions create a
    draft context based only on measurement spacing.  One-timepoint designs are
    returned as not evaluable rather than guessed.
    """

    labels = [str(label).strip() for label in declared_conditions if str(label).strip()]
    metadata = dict(experimental_context or {})
    explicit = metadata.get("temporal_context")
    if isinstance(explicit, StudyTemporalContext):
        explicit.validate()
        return explicit, {
            "status": "explicit_context",
            "pre_registered": explicit.pre_registered,
            "context": asdict(explicit),
            "known_relation_registry_enabled": False,
        }
    if isinstance(explicit, Mapping):
        context = _context_from_mapping(explicit)
        # Registry references belong to runner-only validation, never ordinary
        # production inference, even if accidentally supplied in user config.
        if context.known_relation_registry_path:
            context = StudyTemporalContext(**{
                **asdict(context),
                "known_relation_registry_path": None,
            })
        return context, {
            "status": "explicit_context",
            "pre_registered": context.pre_registered,
            "context": asdict(context),
            "known_relation_registry_enabled": False,
        }
    if len(labels) < 2:
        return None, {
            "status": "not_evaluable_insufficient_declared_timepoints",
            "pre_registered": False,
            "known_relation_registry_enabled": False,
        }
    try:
        context = infer_context_from_grid(labels, study_id=study_id)
        context.validate()
    except (TypeError, ValueError) as error:
        return None, {
            "status": "not_evaluable_unparseable_declared_time_grid",
            "reason": str(error),
            "pre_registered": False,
            "known_relation_registry_enabled": False,
        }
    return context, {
        "status": "draft_context_inferred_from_declared_grid",
        "pre_registered": False,
        "context": asdict(context),
        "known_relation_registry_enabled": False,
        "claim_boundary": (
            "Draft context is grid-derived only. Event timing remains observational and exploratory; "
            "it does not enable direct regulation, pathway identity, or causal claims."
        ),
    }
