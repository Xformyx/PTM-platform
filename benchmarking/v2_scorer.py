from __future__ import annotations

from statistics import mean
from typing import Any, Mapping

from .locked_scorer import _kinase_aliases, _secondary_expected_window, _safe_ratio


def _peak_minutes(value: Any) -> float | None:
    window = _secondary_expected_window(value)
    if window and window[0] == window[1]:
        return float(window[0])
    return None


def _distance_to_window(value: float, window: tuple[float, float]) -> float:
    if window[0] <= value <= window[1]:
        return 0.0
    return min(abs(value - window[0]), abs(value - window[1]))


def _direction_matches(expected: Any, observed: Any) -> bool:
    expected_text = str(expected or "").strip().lower()
    observed_text = str(observed or "").strip().lower()
    return not expected_text or expected_text == observed_text


def _lag_matches(reference: Mapping[str, Any], observed: Any) -> bool:
    try:
        lag = float(observed)
    except (TypeError, ValueError):
        return reference.get("minimum_peak_lag_minutes") is None and reference.get("maximum_peak_lag_minutes") is None
    minimum = reference.get("minimum_peak_lag_minutes")
    maximum = reference.get("maximum_peak_lag_minutes")
    return (minimum is None or lag >= float(minimum)) and (maximum is None or lag <= float(maximum))


def score_additive_v2(
    analysis_artifact: Mapping[str, Any],
    additive_truth: Mapping[str, Any],
) -> dict[str, Any]:
    sidecar = dict(analysis_artifact.get("v2_extensions") or {})
    predictions = [
        dict(row) for row in (sidecar.get("kinase_timing_predictions") or []) if isinstance(row, Mapping)
    ]
    prediction_aliases = [(_kinase_aliases(row.get("kinase")), row) for row in predictions]
    kinase_rows: list[dict[str, Any]] = []
    timing_matches = 0
    timing_denominator = 0
    timing_errors: list[float] = []
    matched = 0
    data_anchored = 0
    for reference in additive_truth.get("kinase_timing_reference") or []:
        aliases = _kinase_aliases(reference.get("Kinase_or_complex"))
        candidates = [row for row_aliases, row in prediction_aliases if aliases & row_aliases]
        prediction = candidates[0] if len(candidates) == 1 else None
        if candidates:
            matched += 1
        anchored = bool(prediction and prediction.get("data_anchored"))
        data_anchored += int(anchored)
        expected_window = _secondary_expected_window(reference.get("Expected_time"))
        observed_peak = _peak_minutes((prediction or {}).get("peak_timepoint"))
        timing_evaluable = anchored and expected_window is not None and observed_peak is not None
        timing_match = None
        timing_error = None
        if timing_evaluable:
            timing_denominator += 1
            timing_match = expected_window[0] <= observed_peak <= expected_window[1]
            timing_matches += int(timing_match)
            timing_error = _distance_to_window(observed_peak, expected_window)
            timing_errors.append(timing_error)
        kinase_rows.append(
            {
                "kinase_id": reference.get("Kinase_ID"),
                "reference_label": reference.get("Kinase_or_complex"),
                "matched_predictions": [row.get("kinase") for row in candidates],
                "match_resolution": "single_prediction" if prediction else "family_or_complex_unresolved" if candidates else "unmatched",
                "data_anchored": anchored,
                "expected_time": reference.get("Expected_time"),
                "observed_peak_timepoint": (prediction or {}).get("peak_timepoint"),
                "timing_evaluable": timing_evaluable,
                "timing_match": timing_match,
                "timing_error_minutes": timing_error,
            }
        )
    kinase_denominator = len(kinase_rows)
    timing_status = "evaluable" if timing_denominator else "not_evaluable"

    cross_reference = list(additive_truth.get("cross_layer_reference") or [])
    cross_edges = list(sidecar.get("cross_layer_edges") or [])
    protein_reference = list(additive_truth.get("protein_effector_reference") or [])
    proteins = list(sidecar.get("protein_time_series") or [])
    protein_matches = 0
    protein_rows: list[dict[str, Any]] = []
    proteins_by_gene = {str(row.get("gene") or "").upper(): row for row in proteins}
    for reference in protein_reference:
        observed = proteins_by_gene.get(str(reference.get("gene") or "").upper())
        direction_match = bool(observed and _direction_matches(reference.get("expected_direction"), observed.get("peak_direction")))
        expected_window = _secondary_expected_window(reference.get("expected_peak"))
        observed_peak = _peak_minutes((observed or {}).get("peak_timepoint"))
        timing_match = bool(
            observed
            and (expected_window is None or (observed_peak is not None and expected_window[0] <= observed_peak <= expected_window[1]))
        )
        matched_reference = bool(observed and direction_match and timing_match)
        protein_matches += int(matched_reference)
        protein_rows.append(
            {
                "effector_id": reference.get("effector_id"),
                "gene": reference.get("gene"),
                "matched": matched_reference,
                "observed_peak_timepoint": (observed or {}).get("peak_timepoint"),
                "observed_direction": (observed or {}).get("peak_direction"),
            }
        )
    cross_matches = 0
    cross_rows: list[dict[str, Any]] = []
    for reference in cross_reference:
        candidates = [
            row
            for row in cross_edges
            if str(row.get("target_gene") or "").upper() == str(reference.get("target_gene") or "").upper()
            and (
                not reference.get("source_wave_id")
                or str(row.get("source_wave_id") or "") == str(reference.get("source_wave_id"))
            )
            and _direction_matches(reference.get("expected_direction"), row.get("direction"))
            and _lag_matches(reference, row.get("peak_lag_minutes"))
        ]
        matched_reference = bool(candidates)
        cross_matches += int(matched_reference)
        cross_rows.append(
            {
                "relation_id": reference.get("relation_id"),
                "target_gene": reference.get("target_gene"),
                "candidate_edge_ids": [row.get("edge_id") for row in candidates],
                "matched": matched_reference,
            }
        )
    mechanism_reference = list(additive_truth.get("mechanism_reference") or [])
    mechanism_chains = list(sidecar.get("mechanism_chains") or [])
    mechanism_matches = 0
    mechanism_rows: list[dict[str, Any]] = []
    for reference in mechanism_reference:
        kinase_aliases = _kinase_aliases(reference.get("kinase_label") or reference.get("Kinase_or_complex"))
        outputs = {str(value).upper() for value in (reference.get("required_output_tokens") or [])}
        candidates = [
            row for row in mechanism_chains
            if kinase_aliases & _kinase_aliases(row.get("kinase"))
            and (not outputs or str(row.get("target_gene") or "").upper() in outputs)
        ]
        matched_chain = next(
            (row for row in candidates if row.get("mechanism_status") == "evidence_supported_mechanism_candidate"),
            None,
        )
        mechanism_matches += int(matched_chain is not None)
        mechanism_rows.append(
            {
                "kinase_id": reference.get("kinase_id") or reference.get("Kinase_ID"),
                "reference_label": reference.get("kinase_label") or reference.get("Kinase_or_complex"),
                "required_output_tokens": sorted(outputs),
                "candidate_chain_count": len(candidates),
                "evidence_supported_chain": (matched_chain or {}).get("chain_id"),
                "matched": matched_chain is not None,
            }
        )
    explicit_mechanism_reference = additive_truth.get("evaluability", {}).get("mechanism") == "explicit_reference_available"
    mechanism_status = "evaluable" if explicit_mechanism_reference else "descriptive_only_no_explicit_v2_chain_truth"
    refutation_status = (
        "evaluable"
        if additive_truth.get("evaluability", {}).get("refutation") == "explicit_reference_available"
        else "not_evaluable_ambiguous_site_policy_only"
    )
    counter_reference = list(additive_truth.get("counterexample_reference") or [])
    counterevidence = list(sidecar.get("mechanism_counterevidence") or [])
    refutation_matches = 0
    refutation_rows: list[dict[str, Any]] = []
    chains_by_id = {str(row.get("chain_id") or ""): row for row in mechanism_chains}
    for reference in counter_reference:
        candidates = []
        if reference.get("chain_id"):
            candidates = [row for row in counterevidence if str(row.get("chain_id") or "") == str(reference.get("chain_id"))]
        else:
            for row in counterevidence:
                chain = chains_by_id.get(str(row.get("chain_id") or ""), {})
                kinase_match = not reference.get("kinase_label") or bool(
                    _kinase_aliases(reference.get("kinase_label")) & _kinase_aliases(chain.get("kinase"))
                )
                target_match = not reference.get("target_gene") or str(chain.get("target_gene") or "").upper() == str(reference.get("target_gene") or "").upper()
                if kinase_match and target_match:
                    candidates.append(row)
        matched_reference = bool(candidates)
        refutation_matches += int(matched_reference)
        refutation_rows.append(
            {
                "counterexample_id": reference.get("counterexample_id"),
                "candidate_chain_ids": [row.get("chain_id") for row in candidates],
                "matched": matched_reference,
            }
        )
    return {
        "schema_version": "ptm_locked_additive_v2_score.v1",
        "kinase_evidence_v2": {
            "metrics": {
                "reference_coverage": _safe_ratio(matched, kinase_denominator),
                "data_anchored_coverage": _safe_ratio(data_anchored, kinase_denominator),
                "timing_accuracy_data_anchored": _safe_ratio(timing_matches, timing_denominator),
                "timing_error_minutes_mean": mean(timing_errors) if timing_errors else None,
            },
            "metric_denominators": {
                "reference_coverage": kinase_denominator,
                "data_anchored_coverage": kinase_denominator,
                "timing_accuracy_data_anchored": timing_denominator,
                "timing_error_minutes_mean": len(timing_errors),
            },
            "timing_status": timing_status,
            "not_evaluable_reason": None if timing_denominator else "no_data_anchored_timing_prediction",
            "results": kinase_rows,
        },
        "cross_layer_v2": {
            "status": "evaluable" if cross_reference else "not_evaluable_missing_locked_cross_layer_reference",
            "reference_count": len(cross_reference),
            "observed_edge_count": len(cross_edges),
            "mechanism_eligible_edge_count": sum(bool(row.get("eligible_for_mechanism_chain")) for row in cross_edges),
            "reference_recovery": _safe_ratio(cross_matches, len(cross_reference)) if cross_reference else None,
            "results": cross_rows,
        },
        "protein_effectors_v2": {
            "status": "evaluable" if protein_reference else "not_evaluable_missing_locked_protein_reference",
            "reference_count": len(protein_reference),
            "observed_protein_count": len(proteins),
            "reference_recovery": _safe_ratio(protein_matches, len(protein_reference)) if protein_reference else None,
            "results": protein_rows,
        },
        "mechanism_v2": {
            "status": mechanism_status,
            "reference_count": len(mechanism_reference),
            "observed_chain_count": len(mechanism_chains),
            "evidence_supported_chain_count": sum(
                row.get("mechanism_status") == "evidence_supported_mechanism_candidate" for row in mechanism_chains
            ),
            "reference_recovery": _safe_ratio(mechanism_matches, len(mechanism_reference)) if explicit_mechanism_reference else None,
            "results": mechanism_rows,
        },
        "refutation_v2": {
            "status": refutation_status,
            "reference_count": len(counter_reference),
            "insufficient_evidence_chain_count": len(counterevidence),
            "refutation_sensitivity": _safe_ratio(refutation_matches, len(counter_reference)) if refutation_status == "evaluable" else None,
            "results": refutation_rows,
        },
        "score_isolation": {
            "primary_v1_unchanged": True,
            "combined_weighted_score": None,
            "selection_boundary": "Additive v2 metrics are runner-only post-freeze evaluation and never alter primary-v1 metrics.",
        },
    }
