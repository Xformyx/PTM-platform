"""Attach leftover observational companions without changing TMM scores.

구현 대상: docs/collaboration/integrated_implementation_w0_2026-09-14.md
사전등록: 2026-09-14. P2는 기존 산출 연결이며 새 점수 학습이 아니다.
해석 한계: 카드 존재는 직접 효소관계·성능 향상이 아니다.
주장 금지: dual-track·Atlas·fraction을 독립 validation으로 부르지 않는다.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict
from typing import Any, Mapping

from common.temporal_utils import condition_sort_key
from ptm_shared.evidence_record_contract import typed_record
from ptm_shared.feature_identity import canonical_feature_identity
from ptm_shared.kinase_trajectory_evidence import compute_kinase_trajectory_evidence
from ptm_shared.quantitative_fields import axis_number


def _mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _as_card(base: dict) -> dict:
    base.setdefault("citation_ids", [])
    base.setdefault("allowed_verbs", ["provided context", "was consistent with"])
    base.setdefault("forbidden_interpretations", ["kinase activation", "direct kinase–site attribution"])
    return base


def _identity_aliases(identity: Mapping[str, Any], canonical: str) -> list[str]:
    aliases = [canonical]
    feature_id = str(identity.get("feature_id") or "").strip()
    reader_id = str(identity.get("reader_feature_id") or "").strip()
    gene = str(identity.get("gene") or "").strip().upper()
    position = str(identity.get("position") or identity.get("site") or "").strip().upper()
    if feature_id:
        aliases.append(feature_id)
    if reader_id:
        aliases.append(reader_id)
    if gene and position:
        aliases.extend([f"{gene}_{position}", f"{gene} {position}", f"{gene}-{position}"])
    return [alias for alias in dict.fromkeys(aliases) if alias]


def _register_alias(series: dict, identities: dict, alias: str, canonical: str) -> None:
    if not alias or alias == canonical or canonical not in series:
        return
    current = series.get(alias)
    if current is None or len(series[canonical]) > len(current):
        series[alias] = series[canonical]
        identities[alias] = dict(identities.get(canonical) or {})


def _resolve_series_key(key: str, series: Mapping[str, Any]) -> str | None:
    if key in series:
        return key
    compact = str(key or "").replace(" ", "_").strip()
    if compact in series:
        return compact
    upper = compact.upper()
    for existing in series:
        if str(existing).replace(" ", "_").upper() == upper:
            return str(existing)
    return None


def vector_unadjusted_timeseries(rows: list) -> tuple[dict, dict, dict, list[str]]:
    series: dict[str, dict[str, float]] = {}
    identities: dict[str, dict] = {}
    denovo: dict[str, bool] = {}
    conditions: set[str] = set()
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        identity = canonical_feature_identity(row)
        key = str(identity.get("feature_id") or "").strip()
        gene = str(identity.get("gene") or row.get("gene") or "").upper()
        position = str(identity.get("position") or row.get("position") or row.get("site") or "").upper()
        if not key and gene and position:
            key = f"{gene}_{position}"
        if not key:
            continue
        condition = str(row.get("condition") or "").strip()
        if not condition:
            continue
        value = axis_number(row, "unadjusted")
        if value is None:
            value = _finite(row.get("log2fc") or row.get("ptm_log2fc"))
        if value is None:
            continue
        conditions.add(condition)
        series.setdefault(key, {})[condition] = value
        identities[key] = {
            **identity,
            "gene": gene or identity.get("gene"),
            "position": position or identity.get("position"),
            "modified_sequence": identity.get("modified_sequence") or row.get("modified_sequence"),
            "protein_group": identity.get("protein_group") or row.get("protein_group"),
        }
        if row.get("is_de_novo_representation") or row.get("detection_context_only"):
            denovo[key] = True
        for alias in _identity_aliases(identities[key], key):
            _register_alias(series, identities, alias, key)
            if alias in denovo or key in denovo:
                denovo[alias] = True
    return series, identities, denovo, sorted(conditions, key=condition_sort_key)


def _raw_target_keys(row: Mapping[str, Any]) -> list[str]:
    keys = []
    for item in row.get("tmm_top_contributions") or row.get("contribution_details") or []:
        if isinstance(item, Mapping):
            keys.extend([
                str(item.get("ptm_key") or ""),
                str(item.get("key") or ""),
                str(item.get("feature_id") or ""),
                str(item.get("temporal_feature_key") or ""),
            ])
            gene = str(item.get("gene") or "").upper()
            position = str(item.get("position") or item.get("site") or "").upper()
            if gene and position:
                keys.append(f"{gene}_{position}")
    for item in row.get("substrates") or []:
        if isinstance(item, Mapping):
            keys.extend([
                str(item.get("key") or ""),
                str(item.get("temporal_feature_key") or ""),
                str(item.get("feature_id") or ""),
            ])
            gene = str(item.get("gene") or "").upper()
            position = str(item.get("position") or item.get("site") or "").upper()
            if gene and position:
                keys.append(f"{gene}_{position}")
        elif item:
            keys.append(str(item))
    members = _mapping(row.get("tmm_input_evidence")).get("members") or []
    for item in members:
        if isinstance(item, Mapping):
            keys.append(str(item.get("key") or item.get("feature_id") or ""))
    return [key for key in keys if key]


def _target_keys(row: Mapping[str, Any], series: Mapping[str, Any] | None = None) -> list[str]:
    resolved = []
    for key in _raw_target_keys(row):
        match = _resolve_series_key(key, series or {}) if series is not None else key
        if match:
            resolved.append(match)
        elif series is None:
            resolved.append(key)
    return list(dict.fromkeys(resolved))


def _trajectory_is_computed(row: Mapping[str, Any]) -> bool:
    evidence = _mapping(row.get("trajectory_evidence"))
    return (
        evidence.get("contract_version") == "kinase_trajectory_evidence.v1"
        and evidence.get("support_status") == "computed"
    )


def attach_missing_trajectory_evidence(heatmap: dict, vector_rows: list) -> dict:
    """Fill ``trajectory_evidence`` on stored scores. Weighted sums stay untouched.

    A stored not-evaluable payload is recomputed from the current vector aliases.
    A computed payload is left unchanged.
    """
    scores = list(heatmap.get("kinase_scores") or [])
    if not scores:
        return heatmap
    series, identities, denovo, inferred = vector_unadjusted_timeseries(vector_rows)
    conditions = list(heatmap.get("conditions") or inferred)
    if not series or len(conditions) < 2:
        for row in scores:
            if isinstance(row, dict) and not _trajectory_is_computed(row):
                row["trajectory_evidence"] = {
                    "contract_version": "kinase_trajectory_evidence.v1",
                    "support_status": "not_evaluable",
                    "unavailable_reason": "source_timeseries_unavailable_for_stale_heatmap",
                    "attached_after_storage": True,
                }
        return heatmap
    for row in scores:
        if not isinstance(row, dict) or row.get("is_sub_pattern"):
            continue
        if _trajectory_is_computed(row):
            continue
        candidate = str(row.get("canonical") or row.get("kinase") or "").upper()
        evidence = compute_kinase_trajectory_evidence(
            candidate=candidate,
            target_keys=_target_keys(row, series),
            timeseries=series,
            conditions=conditions,
            identities=identities,
            denovo_keys=denovo,
        )
        evidence["attached_after_storage"] = True
        row["trajectory_evidence"] = evidence
    heatmap["kinase_scores"] = scores
    heatmap["trajectory_evidence_attachment"] = "additive_on_stored_heatmap"
    return heatmap


def prepare_companion_state(state: Mapping[str, Any]) -> dict:
    prepared = dict(state)
    heatmap = copy.deepcopy(_mapping(state.get("kinase_activity_heatmap") or state.get("frontend_kinase_analysis")))
    attach_missing_trajectory_evidence(heatmap, list(state.get("vector_plot_raw_data") or []))
    prepared["kinase_activity_heatmap"] = heatmap
    return prepared


def dual_track_cards(state: Mapping[str, Any], *, maximum: int = 3) -> list[dict]:
    heatmap = _mapping(state.get("kinase_activity_heatmap"))
    cards = []
    for row in heatmap.get("kinase_scores") or []:
        if not isinstance(row, Mapping) or row.get("is_sub_pattern"):
            continue
        evidence = _mapping(row.get("dual_track_evidence"))
        classification = str(evidence.get("classification") or "")
        if classification in {"", "dual_track_unavailable"}:
            continue
        kinase = str(row.get("canonical") or row.get("kinase") or "candidate")
        correlation = evidence.get("correlation")
        cards.append(_as_card({
            "card_id": f"dual_track.{kinase}",
            "category": "kinase_context",
            "evidence_type": "kinase_candidate",
            "reader_summary": (
                f"{kinase} had a {classification.replace('_', ' ')} comparison between the conventional "
                "relative track and the apparent occupancy track. The two tracks share source data and "
                "are not an independent validation."
            ),
            "claim_tier": "C1",
            "evidence_ids": [f"kinase.dual_track.{kinase}"],
            "value_records": [
                typed_record(
                    record_type="dual_track",
                    entity_id=kinase,
                    metric_id="track_correlation",
                    value=None if correlation is None else round(float(correlation), 4),
                    unit="pearson_r",
                    estimator="tmm_dual_track_evidence.v2",
                    support_status="computed" if correlation is not None else "not_evaluable",
                    evidence_id=f"kinase.dual_track.{kinase}",
                    source={"classification": classification},
                )
            ] if correlation is not None else [],
            "allowed_verbs": ["was compared across tracks", "was consistent with"],
            "forbidden_interpretations": ["independent validation", "absolute occupancy", "kinase activation"],
            "counterevidence": "Both tracks can share the same samples; disagreement is not a causal defect.",
        }))
        if len(cards) >= maximum:
            break
    return cards


def paired_fraction_cards(state: Mapping[str, Any], *, maximum: int = 3) -> list[dict]:
    cards = []
    seen = set()
    for row in state.get("vector_plot_raw_data") or []:
        if not isinstance(row, Mapping):
            continue
        fraction = _finite(row.get("occupancy_logit_delta") or row.get("apparent_paired_fraction"))
        quality = str(row.get("pair_quality_tier") or row.get("pair_quality") or "").strip()
        calibration = str(row.get("occupancy_calibration_type") or "none").strip() or "none"
        if fraction is None or quality not in {"O1", "O2"}:
            continue
        gene = str(row.get("gene") or "feature")
        condition = str(row.get("condition") or "")
        key = (gene, condition)
        if key in seen:
            continue
        seen.add(key)
        cards.append(_as_card({
            "card_id": f"paired_fraction.{len(cards) + 1}",
            "category": "quantitation_comparison",
            "evidence_type": "paired_peptide_fraction",
            "reader_summary": (
                f"{gene} at {condition or 'a recorded condition'} had an apparent paired-peptide "
                f"logit change of {fraction:+.3f} (pair quality {quality}; "
                f"calibration={calibration}). This is an apparent peptide fraction, not a calibrated site amount."
            ),
            "claim_tier": "O2",
            "evidence_ids": [f"paired.fraction.{gene}.{condition or 'na'}"],
            "value_records": [
                typed_record(
                    record_type="paired_peptide_fraction",
                    entity_id=gene,
                    metric_id="occupancy_logit_delta",
                    value=round(fraction, 4),
                    unit="logit_delta",
                    condition=condition or None,
                    estimator="apparent_paired_peptide.v1",
                    support_status="computed",
                    evidence_id=f"paired.fraction.{gene}.{condition or 'na'}",
                    source={"pair_quality_tier": quality, "calibration": calibration},
                )
            ],
            "allowed_verbs": ["had an apparent paired-peptide change"],
            "forbidden_interpretations": ["absolute occupancy", "stoichiometry"],
            "counterevidence": "calibration=none keeps this an apparent peptide fraction.",
        }))
        if len(cards) >= maximum:
            break
    return cards


def multiform_cards(observations: list[dict], *, maximum: int = 3) -> list[dict]:
    by_gene: dict[str, list[dict]] = defaultdict(list)
    for card in observations or []:
        identity = _mapping(card.get("feature_identity"))
        gene = str(identity.get("gene") or "")
        fid = str(identity.get("reader_feature_id") or "")
        if gene and fid:
            by_gene[gene].append(card)
    cards = []
    for gene, group in by_gene.items():
        ids = {str((_mapping(card.get("feature_identity")).get("reader_feature_id"))) for card in group}
        if len(ids) < 2:
            continue
        n_forms = len(ids)
        cards.append(_as_card({
            "card_id": f"multiform.{gene}.{len(cards) + 1}",
            "category": "quantitation_comparison",
            "evidence_type": "multiform_comparison",
            "feature_identity": {
                "gene": gene,
                "reader_display_identity": gene,
            },
            "reader_summary": (
                f"{gene} had more than one measured precursor form. "
                "The forms are compared only on jointly observed conditions and are not a whole-protein activity."
            ),
            "claim_tier": "O2",
            "evidence_ids": [f"multiform.{gene}"],
            "value_records": [
                typed_record(
                    record_type="multiform_comparison",
                    entity_id=gene,
                    metric_id="n_compared_forms",
                    value=n_forms,
                    unit="form_count",
                    estimator="same_parent_precursor_forms.v1",
                    support_status="computed",
                    evidence_id=f"multiform.{gene}",
                    source={"form_ids": sorted(ids)},
                )
            ],
            "allowed_verbs": ["had more than one measured form"],
            "forbidden_interpretations": ["protein activity", "single-residue effect decomposition"],
            "counterevidence": "A multi-modified peptide is not reduced to one residue effect.",
        }))
        if len(cards) >= maximum:
            break
    return cards


def atlas_cards(state: Mapping[str, Any], *, maximum: int = 3) -> list[dict]:
    ledger = _mapping(state.get("atlas_claim_ledger"))
    claims = [row for row in list(ledger.get("site_claims") or []) + list(ledger.get("claims") or []) if isinstance(row, Mapping)]
    cards = []
    for claim in claims:
        site = _mapping(claim.get("site"))
        gene = str(site.get("gene") or site.get("site_key") or "site")
        pattern = str(site.get("primary_pattern") or claim.get("claim_type") or "observed_pattern")
        claim_id = str(claim.get("claim_id") or f"atlas.{gene}.{len(cards) + 1}")
        cards.append(_as_card({
            "card_id": f"atlas.{len(cards) + 1}",
            "category": "temporal_profile",
            "evidence_type": "atlas_observation",
            "reader_summary": (
                f"{gene} had an observational sampled-shape pattern of {pattern.replace('_', ' ')}. "
                "This is a sampled-shape description, not interpolated onset or causal order."
            ),
            "claim_tier": "O2",
            "evidence_ids": [claim_id],
            "value_records": [
                typed_record(
                    record_type="atlas_observation",
                    entity_id=gene,
                    metric_id="observed_pattern",
                    value=None,
                    unit="pattern_label",
                    estimator="atlas_claim_ledger.v1",
                    support_status="computed",
                    evidence_id=claim_id,
                    source={"primary_pattern": pattern, "claim_type": claim.get("claim_type")},
                )
            ],
            "allowed_verbs": ["had an observed sampled pattern"],
            "forbidden_interpretations": ["causal order", "kinase switching", "interpolated peak"],
            "counterevidence": str(claim.get("interpretation_boundary") or "Observed trajectory shape only."),
        }))
        if len(cards) >= maximum:
            break
    return cards


def cluster_profile_cards(state: Mapping[str, Any], *, maximum: int = 3) -> list[dict]:
    analysis = _mapping(state.get("comovement_analysis"))
    cards = []
    for row in analysis.get("clusters") or []:
        if not isinstance(row, Mapping):
            continue
        pattern = str(row.get("pattern") or row.get("pattern_type") or "unclassified")
        members = [
            member for member in row.get("member_details") or []
            if isinstance(member, Mapping)
            and str(member.get("activity_class") or "").lower() != "de_novo"
            and not member.get("control_pseudocount_used")
        ]
        if not members:
            continue
        pattern_label = pattern.replace("_", " ")
        entity = pattern_label
        cards.append(_as_card({
            "card_id": f"cluster.profile.{len(cards) + 1}",
            "category": "temporal_profile",
            "evidence_type": "cluster_profile",
            "reader_summary": (
                f"Among conventionally quantified members, a temporal profile cluster "
                f"with pattern {pattern_label} included {len(members)}. Cluster membership is a "
                "sampled-shape grouping, not common regulation."
            ),
            "claim_tier": "O2",
            "evidence_ids": [f"cluster.profile.{entity}"],
            "figure_keys": ["reader_temporal_profiles"],
            "value_records": [
                typed_record(
                    record_type="cluster_profile",
                    entity_id=entity,
                    metric_id="members",
                    value=len(members),
                    unit="feature_count",
                    estimator="temporal_profile_cluster.v1",
                    support_status="computed",
                    evidence_id=f"cluster.profile.{entity}",
                    source={"pattern": pattern},
                )
            ],
            "allowed_verbs": ["grouped observed profiles"],
            "forbidden_interpretations": ["common regulation", "kinase activity", "causal order"],
            "counterevidence": "Pattern class is a display grouping, not a mechanistic module.",
        }))
        if len(cards) >= maximum:
            break
    return cards


def typed_concordance_records(bindings: list) -> list[dict]:
    """Bind stored pair-window integer counts. Do not reconstruct rates as if they were 100%."""
    records = []
    for row in bindings or []:
        if not isinstance(row, Mapping):
            continue
        cluster = str(row.get("cluster_id") or "").strip() or "cluster"
        if cluster.lower().startswith("wave_"):
            cluster = "temporal-profile-cluster"
        interval = f"{row.get('from_window') or ''}->{row.get('to_window') or ''}".strip("->")
        denominator = row.get("denominator")
        if not isinstance(denominator, int) or denominator <= 0:
            continue
        for metric in ("gain", "loss", "retained"):
            numerator = row.get(metric)
            if not isinstance(numerator, int):
                continue
            records.append(typed_record(
                record_type="module_interval",
                entity_id=cluster,
                metric_id=f"{metric}_count",
                value=numerator,
                unit="pair_count",
                interval=interval,
                numerator=numerator,
                denominator=denominator,
                estimator="interval_concordance.v1",
                support_status="computed",
                evidence_id=f"module.interval.{cluster}",
                source={"source": row.get("source")},
            ))
    return records


def module_interval_records(record: Mapping[str, Any], evidence_id: str) -> list[dict]:
    rates = _mapping(record.get("concordance") or record.get("interval_rates") or record)
    records = []
    for metric in ("gain_rate", "loss_rate", "retained_rate"):
        value = _finite(rates.get(metric))
        if value is None:
            continue
        records.append(typed_record(
            record_type="module_interval",
            entity_id=evidence_id,
            metric_id=metric,
            value=round(value, 4),
            unit="pair_window_rate",
            interval=str(rates.get("interval") or record.get("interval") or ""),
            numerator=rates.get("numerator"),
            denominator=rates.get("denominator"),
            estimator="interval_concordance.v1",
            support_status="computed",
            evidence_id=evidence_id,
        ))
    return records
