from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from ptm_shared.directed_temporal_relationship import analyze_directed_temporal_relationship
from ptm_shared.temporal_optimization_config import (
    CONTRACT_VERSION,
    CROSS_LAYER_CONFIG,
    DYNAMIC_COWAVE_CONFIG,
    DYNAMIC_COWAVE_CONTRACT_VERSION,
    WAVE_CONFIG,
)


SIDECAR_SCHEMA_VERSION = "enrichment_free_temporal_mechanism.v2.sidecar"
# One numeric configuration is used by ordinary orders and strict-blind
# benchmark replays.  The runner-only truth/scoring boundary is separate from
# this shared analysis contract.
DEFAULT_CROSS_LAYER_CONFIG = dict(CROSS_LAYER_CONFIG)


def _minutes(label: str) -> float:
    text = str(label or "").strip().lower()
    digits = "".join(character for character in text if character.isdigit() or character == ".")
    if not digits:
        return math.inf
    value = float(digits)
    if "hour" in text or text.endswith("hr") or text.endswith("h"):
        return value * 60.0
    return value


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _boolean(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def load_protein_time_series(output_dir: Path, ptm_type: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
    path = output_dir / f"all_protein_level_changes_normalized{suffix}.tsv"
    if not path.is_file():
        return [], {
            "contract": "protein_time_series.v2",
            "status": "unavailable",
            "reason": "all_protein_level_changes_not_found",
        }

    grouped: dict[str, dict[str, Any]] = {}
    value_buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    control_buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    treatment_buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            gene = str(row.get("Gene.Name") or "").strip().upper()
            condition = str(row.get("Condition") or "").strip()
            log2fc = _optional_float(row.get("Log2FC"))
            if not gene or not condition or log2fc is None:
                continue
            entry = grouped.setdefault(
                gene,
                {
                    "gene": gene,
                    "protein_group": str(row.get("Protein.Group") or "").strip(),
                    "protein_name": str(row.get("Protein.Name") or "").strip(),
                    "accessions": sorted(
                        {
                            token.strip()
                            for token in str(row.get("Protein.Group") or "").split(";")
                            if token.strip()
                        }
                    ),
                    "has_measured_ptm": _boolean(row.get("Has_PTM")),
                },
            )
            entry["has_measured_ptm"] = bool(entry["has_measured_ptm"] or _boolean(row.get("Has_PTM")))
            value_buckets[(gene, condition)].append(log2fc)
            control = _optional_float(row.get("Control_Mean"))
            treatment = _optional_float(row.get("Treatment_Mean"))
            if control is not None:
                control_buckets[(gene, condition)].append(control)
            if treatment is not None:
                treatment_buckets[(gene, condition)].append(treatment)

    conditions = sorted(
        {condition for _, condition in value_buckets},
        key=lambda item: (_minutes(item), item),
    )
    trajectories: list[dict[str, Any]] = []
    for gene in sorted(grouped):
        entry = grouped[gene]
        values = {
            condition: float(statistics.median(value_buckets[(gene, condition)]))
            for condition in conditions
            if value_buckets.get((gene, condition))
        }
        if not values:
            continue
        peak_condition = max(values, key=lambda name: abs(values[name]))
        peak_value = values[peak_condition]
        trajectories.append(
            {
                **entry,
                "values": values,
                "control_means": {
                    condition: float(statistics.median(control_buckets[(gene, condition)]))
                    for condition in conditions
                    if control_buckets.get((gene, condition))
                },
                "treatment_means": {
                    condition: float(statistics.median(treatment_buckets[(gene, condition)]))
                    for condition in conditions
                    if treatment_buckets.get((gene, condition))
                },
                "observed_timepoint_count": len(values),
                "missing_timepoints": [condition for condition in conditions if condition not in values],
                "peak_timepoint": peak_condition,
                "peak_minutes": _minutes(peak_condition),
                "peak_log2fc": peak_value,
                "peak_direction": "up" if peak_value > 0 else "down" if peak_value < 0 else "neutral",
                "replicate_provenance": {
                    "status": "condition_level_only",
                    "source": path.name,
                    "note": "production preprocessing output stores condition-level protein means; replicate PG values are not persisted here",
                },
            }
        )
    return trajectories, {
        "contract": "protein_time_series.v2",
        "status": "available" if trajectories else "unavailable",
        "source": path.name,
        "gene_count": len(trajectories),
        "condition_count": len(conditions),
        "conditions": conditions,
        "aggregation": "median_within_gene_condition",
        "replicate_values_persisted": False,
    }


def build_ptm_protein_pairs(
    site_observations: Iterable[Mapping[str, Any]],
    protein_time_series: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    protein_by_gene = {
        str(row.get("gene") or "").strip().upper(): row
        for row in protein_time_series
        if str(row.get("gene") or "").strip()
    }
    pairs: list[dict[str, Any]] = []
    for site in site_observations:
        gene = str(site.get("gene") or "").strip().upper()
        protein = protein_by_gene.get(gene)
        if not protein:
            continue
        ptm_peak = _optional_float(site.get("peak_minutes"))
        protein_peak = _optional_float(protein.get("peak_minutes"))
        lag = protein_peak - ptm_peak if ptm_peak is not None and protein_peak is not None else None
        ptm_direction = str(site.get("phosphorylation_direction") or "unknown")
        protein_direction = str(protein.get("peak_direction") or "unknown")
        pairs.append(
            {
                "pair_id": f"{gene}_{site.get('site')}__PROTEIN",
                "gene": gene,
                "site": site.get("site"),
                "protein_group": protein.get("protein_group"),
                "protein_accessions": list(protein.get("accessions") or []),
                "ptm_peak_timepoint": site.get("peak_timepoint"),
                "ptm_peak_minutes": ptm_peak,
                "ptm_peak_log2fc": site.get("peak_log2fc"),
                "ptm_direction": ptm_direction,
                "protein_peak_timepoint": protein.get("peak_timepoint"),
                "protein_peak_minutes": protein_peak,
                "protein_peak_log2fc": protein.get("peak_log2fc"),
                "protein_direction": protein_direction,
                "peak_lag_minutes": lag,
                "ptm_precedes_protein": bool(lag is not None and lag > 0),
                "direction_concordant": bool(
                    ptm_direction in {"up", "down"}
                    and protein_direction in {"up", "down"}
                    and ptm_direction == protein_direction
                ),
                "relation_scope": "same_gene",
                "evidence_class": "observed_ptm_and_condition_level_protein_trajectory",
                "temporal_interpretation": "observational_peak_order_only",
                "causality_status": "not_tested",
            }
        )
    return pairs


def build_cross_layer_edges(
    wave_contract: Mapping[str, Any],
    protein_time_series: Iterable[Mapping[str, Any]],
    *,
    config: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    effective = {**DEFAULT_CROSS_LAYER_CONFIG, **dict(config or {})}
    minimum_change = max(0.0, float(effective["minimum_absolute_change"]))
    minimum_similarity = max(0.0, min(1.0, float(effective["minimum_lag_aware_similarity"])))
    minimum_stability = max(0.0, min(1.0, float(effective["minimum_loto_stability"])))
    maximum_per_wave = max(1, int(effective["maximum_candidates_per_wave"]))
    timepoints = [str(value) for value in (wave_contract.get("timepoints") or [])]
    proteins = [
        row
        for row in protein_time_series
        if row.get("has_measured_ptm") is False
        and max((abs(float(value)) for value in (row.get("values") or {}).values()), default=0.0) >= minimum_change
    ]
    retained: list[dict[str, Any]] = []
    evaluated = 0
    for wave in wave_contract.get("waves") or []:
        source_values = dict(wave.get("mean_profile") or {})
        if not source_values or not timepoints:
            continue
        wave_edges: list[dict[str, Any]] = []
        for protein in proteins:
            values = dict(protein.get("values") or {})
            if any(timepoint not in values for timepoint in timepoints):
                continue
            evaluated += 1
            relation = analyze_directed_temporal_relationship(
                {"key": str(wave.get("wave_id") or "unknown_wave"), "temporal_values": source_values},
                {"key": str(protein.get("gene") or "unknown_protein"), "temporal_values": values},
                timepoints,
                config={
                    "onset_threshold": minimum_change,
                    "minimum_lag_aware_similarity": minimum_similarity,
                    "bootstrap_iterations": int(effective["bootstrap_iterations"]),
                    "permutation_iterations": int(effective["permutation_iterations"]),
                    "random_seed": int(effective["random_seed"]),
                },
                biological_support={
                    "kinase_substrate_consistent": False,
                    "motif_consistent": False,
                    "ppi_consistent": False,
                    "chromadb_consistent": False,
                },
            )
            similarity = relation.get("lag_aware_similarity", {}).get("best_similarity")
            if similarity is None or abs(float(similarity)) < minimum_similarity:
                continue
            loto_stability = relation.get("evidence_profile", {}).get("leave_one_timepoint_stability")
            eligible = bool(
                relation.get("direction") == "source_precedes_target"
                and loto_stability is not None
                and float(loto_stability) >= minimum_stability
            )
            wave_edges.append(
                {
                    "edge_id": f"{wave.get('wave_id')}__{protein.get('gene')}",
                    "source_wave_id": wave.get("wave_id"),
                    "target_gene": protein.get("gene"),
                    "target_protein_group": protein.get("protein_group"),
                    "target_accessions": list(protein.get("accessions") or []),
                    "relation_scope": "co_temporal_non_ptm_candidate",
                    "source_member_count": int(wave.get("member_count") or 0),
                    "target_peak_timepoint": protein.get("peak_timepoint"),
                    "target_peak_log2fc": protein.get("peak_log2fc"),
                    "direction": relation.get("direction"),
                    "directionality_tier": relation.get("directionality_tier"),
                    "onset_lag_minutes": relation.get("onset_lag_minutes"),
                    "peak_lag_minutes": relation.get("peak_lag_minutes"),
                    "lag_aware_similarity": relation.get("lag_aware_similarity"),
                    "evidence_profile": relation.get("evidence_profile"),
                    "quality_flags": list(relation.get("quality_flags") or []),
                    "eligible_for_mechanism_chain": eligible,
                    "network_support_status": "not_evaluated",
                    "causality_status": "not_tested",
                    "interpretation_boundary": "Temporal co-movement candidate only; network relation and causality were not established.",
                }
            )
        wave_edges.sort(
            key=lambda row: (
                not bool(row["eligible_for_mechanism_chain"]),
                -abs(float((row.get("lag_aware_similarity") or {}).get("best_similarity") or 0.0)),
                str(row.get("target_gene") or ""),
            )
        )
        retained.extend(wave_edges[:maximum_per_wave])
    return retained, {
        "contract": "cross_layer_temporal_relationship.v2",
        "scope": "wave_to_non_ptm_protein",
        "evaluated_pair_count": evaluated,
        "retained_edge_count": len(retained),
        "mechanism_eligible_count": sum(bool(row["eligible_for_mechanism_chain"]) for row in retained),
        "protein_candidate_count": len(proteins),
        "config": {
            "minimum_absolute_change": minimum_change,
            "minimum_lag_aware_similarity": minimum_similarity,
            "minimum_loto_stability": minimum_stability,
            "maximum_candidates_per_wave": maximum_per_wave,
            "bootstrap_iterations": int(effective["bootstrap_iterations"]),
            "permutation_iterations": int(effective["permutation_iterations"]),
            "random_seed": int(effective["random_seed"]),
        },
        "replicate_stability_status": "unavailable_for_protein_layer",
        "causality_boundary": "observational_temporal_precedence_only",
    }


def build_kinase_timing_predictions(tmm_result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timepoints = [str(value) for value in (tmm_result.get("conditions") or [])]
    predictions: list[dict[str, Any]] = []
    direct_sources = {"iPTMnet_direct", "UniProt", "observed_kinase_regulatory_ptm", "curated_exact_site"}
    for score in tmm_result.get("kinase_scores") or []:
        profile = dict(score.get("tmm_profile_values") or {})
        if not profile:
            continue
        profile_type = str(score.get("tmm_profile_type") or "unavailable")
        input_evidence = dict(score.get("tmm_input_evidence") or {})
        sources = {str(value) for value in (input_evidence.get("sources") or [])}
        input_tier = str(input_evidence.get("evidence_tier") or "")
        is_direct = bool(sources & direct_sources) or input_tier in {
            "direct_site_annotation",
            "observed_kinase_regulatory_ptm",
        }
        is_empirical = profile_type in {"data_driven", "iterative_data_driven"}
        if is_direct and is_empirical:
            evidence_class = "direct_plus_empirical_data_anchor"
        elif is_direct:
            evidence_class = "direct_site_data_anchor"
        elif is_empirical:
            evidence_class = "empirical_profile_motif_candidate"
        elif profile_type == "gaussian_fallback":
            evidence_class = "prior_assisted"
        else:
            evidence_class = "unclassified"
        ordered = timepoints or list(profile)
        peak_timepoint = max(ordered, key=lambda label: abs(float(profile.get(label, 0.0)))) if ordered else None
        max_value = max((abs(float(profile.get(label, 0.0))) for label in ordered), default=0.0)
        onset_threshold = 0.2 * max_value
        onset_timepoint = next(
            (label for label in ordered if abs(float(profile.get(label, 0.0))) >= onset_threshold),
            None,
        )
        predictions.append(
            {
                "kinase": score.get("kinase"),
                "profile_type": profile_type,
                "profile_values": {label: float(profile.get(label, 0.0)) for label in ordered},
                "onset_timepoint": onset_timepoint,
                "peak_timepoint": peak_timepoint,
                "evidence_class": evidence_class,
                "data_anchored": bool(is_direct),
                "input_evidence": input_evidence,
                "profile_evidence": dict(score.get("tmm_evidence") or {}),
                "timing_interval_status": "pending_profile_bootstrap" if is_direct else "not_available",
                "interpretation_boundary": (
                    "Eligible for direct-evidence timing evaluation."
                    if is_direct
                    else "Not eligible for direct-evidence timing accuracy."
                ),
            }
        )
    anchored = [row for row in predictions if row["data_anchored"]]
    return predictions, {
        "contract": "data_anchored_kinase_timing.v2",
        "prediction_count": len(predictions),
        "data_anchored_prediction_count": len(anchored),
        "data_anchored_timing_status": "evaluable" if anchored else "not_evaluable",
        "not_evaluable_reason": None if anchored else "no_direct_site_or_observed_kinase_ptm_profile",
        "prior_assisted_prediction_count": sum(row["evidence_class"] == "prior_assisted" for row in predictions),
        "empirical_motif_candidate_count": sum(
            row["evidence_class"] == "empirical_profile_motif_candidate" for row in predictions
        ),
        "accuracy_semantics": "Accuracy is undefined when the data-anchored denominator is zero.",
    }


def build_mechanism_evidence(
    wave_contract: Mapping[str, Any],
    tmm_result: Mapping[str, Any],
    cross_layer_edges: Iterable[Mapping[str, Any]],
    kinase_timing_predictions: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    contribution_matrix = dict(
        tmm_result.get("relative_site_contribution_matrix")
        or tmm_result.get("tmm_site_contribution_matrix")
        or {}
    )
    timing_by_kinase = {
        str(row.get("kinase") or ""): dict(row)
        for row in kinase_timing_predictions
        if row.get("kinase")
    }
    wave_kinases: dict[str, list[dict[str, Any]]] = {}
    for wave in wave_contract.get("waves") or []:
        totals: dict[str, float] = {}
        for member in wave.get("members") or []:
            for kinase, contribution in dict(contribution_matrix.get(member) or {}).items():
                totals[str(kinase)] = totals.get(str(kinase), 0.0) + float(contribution or 0.0)
        ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        denominator = sum(value for _, value in ordered) or 1.0
        wave_kinases[str(wave.get("wave_id") or "")] = [
            {"kinase": kinase, "contribution_mass": value, "contribution_fraction": value / denominator}
            for kinase, value in ordered[:5]
        ]
    chains: list[dict[str, Any]] = []
    counterevidence: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    for edge in cross_layer_edges:
        wave_id = str(edge.get("source_wave_id") or "")
        kinase_rows = wave_kinases.get(wave_id) or [
            {"kinase": None, "contribution_mass": 0.0, "contribution_fraction": 0.0}
        ]
        for kinase_row in kinase_rows:
            kinase = kinase_row.get("kinase")
            timing = timing_by_kinase.get(str(kinase or ""), {})
            data_anchor = bool(timing.get("data_anchored"))
            network_supported = edge.get("network_support_status") == "supported"
            temporal_supported = bool(edge.get("eligible_for_mechanism_chain"))
            status = (
                "evidence_supported_mechanism_candidate"
                if data_anchor and network_supported and temporal_supported
                else "temporal_candidate"
            )
            chain_id = f"{kinase or 'unresolved_kinase'}__{wave_id}__{edge.get('target_gene')}"
            reasons = []
            if not data_anchor:
                reasons.append("kinase_timing_not_data_anchored")
            if not network_supported:
                reasons.append("network_relation_not_evaluated")
            if not temporal_supported:
                reasons.append("cross_layer_temporal_gate_failed")
            chain = {
                "chain_id": chain_id,
                "kinase": kinase,
                "wave_id": wave_id,
                "target_gene": edge.get("target_gene"),
                "kinase_to_wave": {
                    **kinase_row,
                    "timing_evidence_class": timing.get("evidence_class") or "unavailable",
                    "data_anchored": data_anchor,
                },
                "wave_to_protein": {
                    "direction": edge.get("direction"),
                    "directionality_tier": edge.get("directionality_tier"),
                    "onset_lag_minutes": edge.get("onset_lag_minutes"),
                    "peak_lag_minutes": edge.get("peak_lag_minutes"),
                    "network_support_status": edge.get("network_support_status"),
                    "temporal_eligible": temporal_supported,
                },
                "mechanism_status": status,
                "causality_status": "not_tested",
                "falsification_targets": [
                    "kinase_perturbation_should_reduce_wave_activity",
                    "wave_attenuation_should_precede_target_protein_change",
                    "orthogonal_assay_should_confirm_target_protein_change",
                ],
                "interpretation_boundary": "Ordered observational evidence; not a causal mechanism claim.",
            }
            chains.append(chain)
            if reasons:
                counterevidence.append({"chain_id": chain_id, "reasons": reasons, "status": "insufficient_evidence"})
            packets.append(
                {
                    "packet_id": chain_id,
                    "observation": {
                        "kinase": kinase,
                        "wave_id": wave_id,
                        "target_gene": edge.get("target_gene"),
                        "peak_lag_minutes": edge.get("peak_lag_minutes"),
                    },
                    "attribution": chain["kinase_to_wave"],
                    "cross_layer_evidence": chain["wave_to_protein"],
                    "counterevidence": reasons,
                    "literature_evidence": [],
                    "literature_status": "not_requested_in_numeric_benchmark",
                    "falsification_targets": chain["falsification_targets"],
                    "allowed_claim": status,
                }
            )
    return chains, counterevidence, packets


def build_v2_sidecar(
    *,
    output_dir: Path,
    ptm_type: str,
    site_observations: Iterable[Mapping[str, Any]],
    wave_contract: Mapping[str, Any] | None = None,
    tmm_result: Mapping[str, Any] | None = None,
    cross_layer_config: Mapping[str, Any] | None = None,
    dynamic_transition_config: Mapping[str, Any] | None = None,
    enable_dynamic_transition: bool = True,
    enable_probabilistic_cowave: bool = False,
    replicate_time_series: Mapping[str, Mapping[str, Iterable[Any]]] | None = None,
    study_context: Any | None = None,
    raw_replicate_fc_series: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build v2 enrichment-free temporal sidecar.

    enable_probabilistic_cowave=True adds a GP-posterior soft co-activity
    annotation as an optional parallel layer.  Disabled by default: it does not
    affect Wave membership, TMM scores, kinase rankings, or canonical evidence
    and must not replace hard-threshold output until inhibitor holdout validation
    confirms calibration benefit (P2 — Roadmap §3 production integration gate).

    study_context : StudyTemporalContext | None
        Required for temporal_precedence event extraction.  When None, the
        temporal_precedence field is populated with status="not_evaluable_context_not_registered".
        Never silently defaults to INSULIN_TEMPORAL_CONTEXT.

    raw_replicate_fc_series : Mapping[site_key, {"timepoints": [...], "matrix": np.ndarray}] | None
        Per-site per-replicate FC matrices aligned to the same timepoint labels as
        wave_contract["timepoints"].  When provided together with study_context,
        replicate-level event records are computed.  When absent, condition-mean GP
        records are computed (exploratory_model_uncertainty only, replicate_bootstrap_stability=None).
        Partial coverage is allowed: sites without replicate data receive condition-mean records.
    """
    protein_time_series, protein_provenance = load_protein_time_series(output_dir, ptm_type)
    ptm_protein_pairs = build_ptm_protein_pairs(site_observations, protein_time_series)
    cross_layer_edges, cross_layer_provenance = build_cross_layer_edges(
        dict(wave_contract or {}),
        protein_time_series,
        config=cross_layer_config,
    )
    kinase_timing_predictions, kinase_timing_provenance = build_kinase_timing_predictions(
        dict(tmm_result or {})
    )
    mechanism_chains, mechanism_counterevidence, hypothesis_evidence_packets = build_mechanism_evidence(
        dict(wave_contract or {}),
        dict(tmm_result or {}),
        cross_layer_edges,
        kinase_timing_predictions,
    )
    if not enable_dynamic_transition:
        dynamic_transition: dict[str, Any] = {
            "contract_version": DYNAMIC_COWAVE_CONTRACT_VERSION,
            "status": "disabled_by_caller",
            "interpretation_boundary": "Optional additive local co-movement annotation; static Wave membership and TMM are unchanged.",
        }
    else:
        from ptm_shared.dynamic_cowave_transition import analyze_dynamic_co_wave_transitions

        dynamic_transition = analyze_dynamic_co_wave_transitions(
            dict(wave_contract or {}),
            config=dict(DYNAMIC_COWAVE_CONFIG if dynamic_transition_config is None else dynamic_transition_config),
        )
        dynamic_transition["status"] = "computed"

    # A distinct event-time layer prevents Dynamic Co-Wave's descriptive
    # reorganization ratio from being misreported as temporal-order evidence.
    # It reads immutable Wave members and does not alter the canonical Wave,
    # TMM, kinase ranking, or Dynamic Co-Wave v2 result.
    from ptm_shared.temporal_event_order import build_temporal_event_order_evidence

    temporal_event_order = build_temporal_event_order_evidence(
        dict(wave_contract or {}),
        replicate_time_series=replicate_time_series,
    )

    # Probabilistic co-wave companion (P2 — optional, disabled by default)
    # Must not alter Wave membership, TMM, or canonical scores.
    # Production integration gate: enable only after inhibitor holdout confirms
    # calibration benefit (Roadmap §3; pre-registered 2026-08-28).
    if enable_probabilistic_cowave and wave_contract:
        from ptm_shared.probabilistic_cowave import probabilistic_transition_annotation
        probabilistic_cowave: dict[str, Any] = probabilistic_transition_annotation(
            dict(wave_contract)
        )
    else:
        probabilistic_cowave = {
            "status": "disabled_by_caller",
            "interpretation_boundary": (
                "GP posterior companion; not integrated into canonical scoring. "
                "Enable after inhibitor holdout calibration is confirmed."
            ),
        }

    # Temporal precedence output (P3 — additive, non-mutating).
    # Requires explicit study_context (no insulin default).
    # Attaches event-time records for each Wave member without modifying
    # Wave membership, TMM scores, kinase rankings, or canonical evidence.
    # ISOLATION: no known relation registry / benchmark truth flows in here.
    temporal_precedence: dict[str, Any]
    if study_context is None:
        temporal_precedence = {
            "status": "not_evaluable_context_not_registered",
            "note": (
                "study_context not provided. Pass an explicit StudyTemporalContext "
                "to enable temporal event record extraction."
            ),
            "mutation_guarantee": (
                "This field is additive. Wave membership, TMM scores, kinase rankings, "
                "and locked scores are not modified."
            ),
        }
    elif wave_contract:
        from ptm_shared.replicate_event_adapter import (
            EventStatus,
            build_event_records_for_wave_contract,
            extract_event_record_from_replicates,
        )
        from ptm_shared.temporal_precedence_output import build_temporal_precedence_output

        # Build condition-mean records for all Wave members as the base layer
        event_records = build_event_records_for_wave_contract(
            dict(wave_contract),
            study_context=study_context,
        )

        # Upgrade to replicate-level where raw_replicate_fc_series is available.
        # SCOPE RULE (audit 2026-08-29): upgrade is restricted to Wave members only.
        # Admitting non-Wave-member sites here would produce 2,117 > 834 records,
        # creating a scope inconsistency vs the contract text "each Wave member".
        # Raw replicate values are used ephemerally; no matrix/intensity fields
        # are persisted in the output.
        if raw_replicate_fc_series:
            import numpy as np
            wave_members: set[str] = {
                site
                for wave in (wave_contract or {}).get("waves", [])
                for site in wave.get("members", [])
            }
            for site_key, rep_data in raw_replicate_fc_series.items():
                if site_key not in wave_members:
                    continue  # restrict to Wave members — scope contract
                matrix = rep_data.get("matrix")
                tps = rep_data.get("timepoints", [])
                if matrix is None or not tps:
                    continue
                arr = np.asarray(matrix, dtype=float)
                if arr.ndim != 2 or arr.shape[0] < 2:
                    continue
                try:
                    event_records[site_key] = extract_event_record_from_replicates(
                        site_key, tps, arr,
                        study_context=study_context,
                    )
                except Exception:
                    pass  # retain condition-mean record on failure

        temporal_precedence = build_temporal_precedence_output(
            event_records,
            dict(wave_contract),
            study_context=study_context,
        )
        temporal_precedence["replicate_input_summary"] = {
            "n_sites_with_replicate_data": len(raw_replicate_fc_series) if raw_replicate_fc_series else 0,
            "n_sites_with_event_records": len(event_records),
            "replicate_mode": "replicate_level" if raw_replicate_fc_series else "condition_mean_gp_only",
        }
    else:
        temporal_precedence = {
            "status": "skipped_no_wave_contract",
            "mutation_guarantee": (
                "This field is additive. Wave membership, TMM scores, kinase rankings, "
                "and locked scores are not modified."
            ),
        }

    return {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "temporal_wave_contract": dict(wave_contract or {}),
        "protein_time_series": protein_time_series,
        "ptm_protein_pairs": ptm_protein_pairs,
        "kinase_direct_evidence": [
            row for row in kinase_timing_predictions if row.get("data_anchored")
        ],
        "kinase_timing_predictions": kinase_timing_predictions,
        "cross_layer_edges": cross_layer_edges,
        "mechanism_chains": mechanism_chains,
        "mechanism_counterevidence": mechanism_counterevidence,
        "hypothesis_evidence_packets": hypothesis_evidence_packets,
        "dynamic_co_wave_transition": dynamic_transition,
        "temporal_event_order": temporal_event_order,
        "probabilistic_co_wave": probabilistic_cowave,
        "temporal_precedence": temporal_precedence,
        "provenance": {
            "source": "production_preprocessing_outputs",
            "rag_used": False,
            "llm_used": False,
            "benchmark_truth_used": False,
            "protein_time_series": protein_provenance,
            "ptm_protein_pair_count": len(ptm_protein_pairs),
            "cross_layer": cross_layer_provenance,
            "kinase_timing": kinase_timing_provenance,
            "mechanism_chain_count": len(mechanism_chains),
            "mechanism_supported_count": sum(
                row.get("mechanism_status") == "evidence_supported_mechanism_candidate"
                for row in mechanism_chains
            ),
            "dynamic_co_wave_transition": {
                "status": dynamic_transition.get("status"),
                "config_sha256": (dynamic_transition.get("provenance") or {}).get("config_sha256"),
                "membership_mutation": (dynamic_transition.get("provenance") or {}).get("membership_mutation"),
                "tmm_mutation": (dynamic_transition.get("provenance") or {}).get("tmm_mutation"),
            },
            "temporal_event_order": {
                "status": temporal_event_order.get("status"),
                "contract_version": temporal_event_order.get("contract_version"),
                "config_sha256": (temporal_event_order.get("provenance") or {}).get("config_sha256"),
                "temporal_order_validation_status": (temporal_event_order.get("summary") or {}).get("temporal_order_validation_status"),
                "membership_mutation": (temporal_event_order.get("provenance") or {}).get("membership_mutation"),
                "tmm_mutation": (temporal_event_order.get("provenance") or {}).get("tmm_mutation"),
            },
            "causality_boundary": "temporal_order_is_observational_and_not_causal",
            "probabilistic_co_wave": {
                "status": probabilistic_cowave.get("status"),
                "enabled": enable_probabilistic_cowave,
                "interpretation_boundary": (
                    "GP posterior uncertainty annotation; parallel layer only. "
                    "Does not replace hard-threshold canonical output. "
                    "Inhibitor holdout validation required before production use."
                ),
            },
        },
    }


def build_production_site_observations(
    ptm_timeseries: Mapping[str, Mapping[str, Any]],
    conditions: Iterable[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Normalize ordinary-order PTM vectors into the shared sidecar input.

    Missing values are retained as missing in site observations and excluded
    only from canonical Wave fitting, never converted to zero.
    """

    ordered_conditions = [str(value) for value in conditions]
    observations: list[dict[str, Any]] = []
    complete_vectors: dict[str, dict[str, Any]] = {}
    for raw_key, raw_values in sorted(ptm_timeseries.items()):
        key = str(raw_key or "").strip().upper()
        if "_" not in key:
            continue
        gene, site = key.rsplit("_", 1)
        values = {
            condition: parsed
            for condition in ordered_conditions
            if (parsed := _optional_float(dict(raw_values or {}).get(condition))) is not None
        }
        if not values:
            continue
        peak_timepoint = max(values, key=lambda label: abs(values[label]))
        peak_value = values[peak_timepoint]
        observations.append(
            {
                "site_key": key,
                "gene": gene,
                "site": site,
                "temporal_values": values,
                "peak_timepoint": peak_timepoint,
                "peak_minutes": _minutes(peak_timepoint),
                "peak_log2fc": peak_value,
                "phosphorylation_direction": "up" if peak_value > 0 else "down" if peak_value < 0 else "neutral",
                "observed_timepoint_count": len(values),
                "missing_timepoints": [condition for condition in ordered_conditions if condition not in values],
                "quantification_track": "protein_normalized_relative_log2fc",
            }
        )
        if len(values) == len(ordered_conditions):
            complete_vectors[key] = values
    return observations, complete_vectors


def build_production_temporal_ptm_protein_analysis(
    *,
    output_dir: Path,
    ptm_type: str,
    ptm_timeseries: Mapping[str, Mapping[str, Any]],
    conditions: Iterable[str],
    tmm_result: Mapping[str, Any],
    cross_layer_config: Mapping[str, Any] | None = None,
    dynamic_transition_config: Mapping[str, Any] | None = None,
    enable_dynamic_transition: bool = True,
    study_context: Any | None = None,
    raw_replicate_fc_series: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the exact v2 sidecar contract for a normal production order.

    Benchmark replay passes its archived Wave contract into :func:`build_v2_sidecar`.
    Production derives that contract from the same canonical Wave engine and
    frozen numeric configuration; only runner-only truth/scoring remains
    benchmark-specific.

    study_context : StudyTemporalContext | None
        When provided, enables temporal_precedence event record extraction.
        When None, temporal_precedence field is not_evaluable_context_not_registered.
        Never inferred or defaulted; must be supplied explicitly by the caller.

    raw_replicate_fc_series : Mapping[site_key, {"timepoints": [...], "matrix": np.ndarray}] | None
        Per-site per-replicate FC matrices.  When provided with study_context,
        replicate-level event records are extracted for Wave members.
    """

    from ptm_shared.temporal_wave_engine import analyze_temporal_waves

    ordered_conditions = [str(value) for value in conditions]
    observations, complete_vectors = build_production_site_observations(
        ptm_timeseries,
        ordered_conditions,
    )
    metadata = {
        row["site_key"]: {
            "gene": row["gene"],
            "site": row["site"],
            "quantification_track": row["quantification_track"],
        }
        for row in observations
        if row["site_key"] in complete_vectors
    }
    wave_contract = analyze_temporal_waves(
        complete_vectors,
        ordered_conditions,
        metadata=metadata,
        config={**dict(WAVE_CONFIG), "threshold_source": CONTRACT_VERSION},
    )
    wave_contract["analysis_scope"] = "production_observed_only_complete_ptm_vectors"
    sidecar = build_v2_sidecar(
        output_dir=output_dir,
        ptm_type=ptm_type,
        site_observations=observations,
        wave_contract=wave_contract,
        tmm_result=tmm_result,
        cross_layer_config=cross_layer_config,
        dynamic_transition_config=dynamic_transition_config,
        enable_dynamic_transition=enable_dynamic_transition,
        study_context=study_context,
        raw_replicate_fc_series=raw_replicate_fc_series,
    )
    sidecar["provenance"]["analysis_mode"] = "production"
    sidecar["provenance"]["shared_engine_contract"] = "unified_temporal_ptm_protein.v1"
    sidecar["provenance"]["complete_wave_site_count"] = len(complete_vectors)
    # STRICT/PRODUCTION PARITY NOTE (audit 2026-08-29):
    # Production admits complete-vector sites only (no missingness).
    # Strict benchmark runner fills missing timepoints with zero at request boundary.
    # This produces different Wave member universes (629 production vs 834 strict).
    # Do NOT compare T_adjacency, transition_resolution, or Wave-level aggregates
    # across strict and production runs without resolving this discrepancy.
    # Resolution requires aligning missing-value treatment; changing either path
    # risks altering locked-score baselines or production output quality.
    sidecar["provenance"]["missing_value_treatment"] = "complete_vectors_only_no_imputation"
    sidecar["provenance"]["strict_production_parity"] = "NOT_RESOLVED_strict_fills_zero_production_omits"
    return sidecar


def _compact_temporal_precedence(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    """Extract a provenance-preserving summary of temporal_precedence for compact sidecar.

    This is the Report/UI-facing aggregate — it does not expose individual
    event records, raw timing values, or relation registry contents.

    Fields emitted:
      status         : "computed" | "not_evaluable_context_not_registered" | "skipped_*"
      n_sites        : total sites with event records
      n_evaluable    : sites with tier != not_evaluable
      tier_breakdown : {tier: count}
      replicate_mode : "replicate_level" | "condition_mean_gp_only" | None
      p4_gate_passed : bool | None
      claim_boundary : fixed phrase
    """
    tp = dict(sidecar.get("temporal_precedence") or {})
    status = tp.get("status")
    summary = dict(tp.get("summary") or {})
    rep_summary = dict(tp.get("replicate_input_summary") or {})
    p4 = dict(tp.get("p4_gate") or {})

    return {
        "status": status or "unavailable",
        "n_sites": summary.get("n_sites"),
        "n_evaluable": summary.get("n_evaluable"),
        "tier_breakdown": dict(summary.get("tier_breakdown") or {}),
        "replicate_mode": rep_summary.get("replicate_mode"),
        "n_sites_with_replicate_data": rep_summary.get("n_sites_with_replicate_data"),
        "p4_gate_passed": p4.get("passed"),
        "claim_boundary": (
            "Temporal event records are observational response timing only. "
            "Causal interpretation requires P4 Trametinib validation. "
            "This field does not expose individual event records or relation registry."
        ),
        "contract_version": tp.get("contract_version"),
    }


def summarize_temporal_ptm_protein_analysis(
    sidecar: Mapping[str, Any],
    *,
    artifact_path: str | None = None,
    max_examples: int = 20,
) -> dict[str, Any]:
    """Return a DB/API-context-safe projection of the shared full sidecar."""

    edges = list(sidecar.get("cross_layer_edges") or [])
    chains = list(sidecar.get("mechanism_chains") or [])
    packets = list(sidecar.get("hypothesis_evidence_packets") or [])
    counterevidence = list(sidecar.get("mechanism_counterevidence") or [])
    dynamic_transition = dict(sidecar.get("dynamic_co_wave_transition") or {})
    dynamic_summary = dict(dynamic_transition.get("summary") or {})
    temporal_event_order = dict(sidecar.get("temporal_event_order") or {})
    temporal_event_summary = dict(temporal_event_order.get("summary") or {})
    eligible_edges = [row for row in edges if row.get("eligible_for_mechanism_chain")]
    ordered_edges = sorted(
        eligible_edges or edges,
        key=lambda row: abs(float((row.get("lag_aware_similarity") or {}).get("best_similarity") or 0.0)),
        reverse=True,
    )
    return {
        "schema_version": sidecar.get("schema_version"),
        "shared_engine_contract": (sidecar.get("provenance") or {}).get("shared_engine_contract"),
        "artifact_path": artifact_path,
        "full_artifact_available": bool(artifact_path),
        "protein_trajectory_count": len(sidecar.get("protein_time_series") or []),
        "ptm_protein_pair_count": len(sidecar.get("ptm_protein_pairs") or []),
        "cross_layer_edge_count": len(edges),
        "temporally_eligible_edge_count": len(eligible_edges),
        "mechanism_chain_count": len(chains),
        "evidence_supported_mechanism_count": sum(
            row.get("mechanism_status") == "evidence_supported_mechanism_candidate" for row in chains
        ),
        "mechanism_counterevidence_count": len(counterevidence),
        "kinase_timing_status": ((sidecar.get("provenance") or {}).get("kinase_timing") or {}).get("data_anchored_timing_status"),
        "dynamic_co_wave_transition_status": dynamic_transition.get("status", "not_requested"),
        "dynamic_co_wave_transition_contract_version": dynamic_transition.get("contract_version"),
        "dynamic_co_wave_transition_config_sha256": (dynamic_transition.get("provenance") or {}).get("config_sha256"),
        "dynamic_transition_supported_wave_count": dynamic_summary.get("transition_supported_wave_count"),
        "dynamic_transition_pair_count": dynamic_summary.get("pair_transition_count"),
        "dynamic_transition_site_count": dynamic_summary.get("site_transition_count"),
        "dynamic_transition_resolution": dynamic_summary.get("transition_resolution"),
        "dynamic_transition_loto": dict(dynamic_transition.get("lotto") or {}),
        "dynamic_transition_per_wave": list(dynamic_transition.get("per_wave_summary") or []),
        "dynamic_transition_pair_scope": dict(dynamic_transition.get("pair_scope") or {}),
        "dynamic_transition_event_exposure": dict(dynamic_transition.get("event_exposure") or {}),
        "temporal_event_order_status": temporal_event_order.get("status", "not_available"),
        "temporal_event_order_contract_version": temporal_event_order.get("contract_version"),
        "temporal_event_order_validation_status": temporal_event_summary.get("temporal_order_validation_status"),
        "temporal_event_order_event_estimability_fraction": temporal_event_summary.get("event_estimability_fraction"),
        "temporal_event_order_replicate_uncertainty_status": temporal_event_summary.get("replicate_uncertainty_status"),
        "temporal_event_order_current_transition_resolution_status": temporal_event_summary.get("current_transition_resolution_status"),
        "causality_status": "not_tested",
        "interpretation_boundary": "Temporal precedence and mechanism packets are observational, falsifiable candidates; they are not causal claims.",
        "top_cross_layer_edges": [
            {
                key: row.get(key)
                for key in (
                    "edge_id", "source_wave_id", "target_gene", "direction", "onset_lag_minutes",
                    "peak_lag_minutes", "lag_aware_similarity", "temporal_interpretation",
                    "eligible_for_mechanism_chain", "causality_status",
                )
            }
            for row in ordered_edges[:max_examples]
        ],
        "top_mechanism_counterevidence": [
            {
                "chain_id": row.get("chain_id"),
                "status": row.get("status"),
                "reasons": list(row.get("reasons") or [])[:6],
            }
            for row in counterevidence[:max_examples]
            if isinstance(row, Mapping)
        ],
        "hypothesis_evidence_packets": packets[:max_examples],
        "temporal_precedence_status": _compact_temporal_precedence(sidecar),
        "provenance": dict(sidecar.get("provenance") or {}),
    }
