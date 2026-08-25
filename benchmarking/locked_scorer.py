"""Locked Tier 1/2 scorer for blind PTM-platform analysis artifacts.

The scorer accepts only post-analysis observations that carry explicit
sequence+isoform+species mapping evidence.  It intentionally cannot be used
by report/LLM runtime and does not infer biological truth from gene symbols.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import BenchmarkManifest, BenchmarkManifestError, load_locked_truth_bundle


class LockedScoreError(ValueError):
    """Raised for malformed post-analysis benchmark artifacts."""


@dataclass(frozen=True)
class _Anchor:
    anchor_id: str
    tier: str
    branch: str
    gene: str
    rat_site: str
    human_site: str
    expected_direction: str
    peak_window: str
    truth_use: str


def _as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def _normalise_direction(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _normalise_site(value: Any) -> str:
    return str(value or "").upper().replace(" ", "").replace(";", "/").strip()


def _parse_window_minutes(value: str) -> tuple[float, float] | None:
    """Parse workbook-style compatible time windows, not exact-minute truth."""

    import re

    raw = str(value or "").lower().replace("–", "-").replace("—", "-")
    numbers = [float(part) for part in re.findall(r"\d+(?:\.\d+)?", raw)]
    if not numbers:
        return None
    if "≤" in raw or "<=" in raw:
        return (0.0, max(numbers))
    if len(numbers) == 1:
        return (numbers[0], numbers[0])
    return (min(numbers[0], numbers[1]), max(numbers[0], numbers[1]))


def _mapping_is_sequence_isoform_species(mapping: Any) -> bool:
    """Reject gene/site-only matches from the canonical denominator."""

    if not isinstance(mapping, Mapping):
        return False
    method = str(mapping.get("method") or "").strip().lower()
    return (
        method == "sequence_isoform_species"
        and _as_bool(mapping.get("sequence_match"))
        and _as_bool(mapping.get("isoform_match"))
        and _as_bool(mapping.get("species_match"))
    )


class LockedBenchmarkScorer:
    """Score a locked Tier 1/2 reference without exposing it to analysis code."""

    def __init__(self, manifest: BenchmarkManifest):
        self.manifest = manifest
        self.truth = load_locked_truth_bundle(manifest)
        self.anchors = self._load_anchors(self.truth.get("anchors", []))
        self.weights = {
            str(key): float(value)
            for key, value in self.manifest.score_config.get("component_weights", {}).items()
        }
        self.tier_weights = {
            str(key): float(value)
            for key, value in self.manifest.score_config.get(
                "evidence_tier_weights", {"Tier 1": 2, "Tier 2": 1}
            ).items()
        }

    @staticmethod
    def _load_anchors(rows: Sequence[Mapping[str, Any]]) -> dict[str, _Anchor]:
        anchors: dict[str, _Anchor] = {}
        for row in rows:
            anchor_id = str(row.get("Anchor_ID") or "").strip()
            tier = str(row.get("Evidence_tier") or "").strip()
            truth_use = str(row.get("Benchmark_truth_use") or "").strip()
            if not anchor_id or tier not in {"Tier 1", "Tier 2"}:
                continue
            if "truth" not in truth_use.lower():
                continue
            anchors[anchor_id] = _Anchor(
                anchor_id=anchor_id,
                tier=tier,
                branch=str(row.get("Branch") or "Unspecified").strip() or "Unspecified",
                gene=str(row.get("Gene") or "").strip().upper(),
                rat_site=str(row.get("Rat_site") or "").strip(),
                human_site=str(row.get("Human_site") or "").strip(),
                expected_direction=str(row.get("Expected_p_direction") or "").strip(),
                peak_window=str(row.get("Expected_peak_window") or "").strip(),
                truth_use=truth_use,
            )
        if not anchors:
            raise LockedScoreError("locked truth has no Tier 1/2 positive anchors")
        return anchors

    def score(self, analysis_artifact: Mapping[str, Any]) -> dict[str, Any]:
        """Score an archived blind-analysis summary.

        Required artifact sections are truth-free ``site_availability`` and
        ``site_observations``.  The scorer maps their generic gene/site/mapping
        signatures to locked anchor IDs internally. Missing availability
        deliberately excludes an anchor from the detectable denominator instead
        of treating absence as a false negative.
        """

        if not isinstance(analysis_artifact, Mapping):
            raise LockedScoreError("analysis artifact must be an object")
        availability = self._index_availability(analysis_artifact.get("site_availability", []))
        observations, mapping_rejections = self._index_observations(
            analysis_artifact.get("site_observations", [])
        )

        anchor_rows: list[dict[str, Any]] = []
        numerators = defaultdict(float)
        denominators = defaultdict(float)
        branch_detected: dict[str, list[_Anchor]] = defaultdict(list)

        for anchor in self.anchors.values():
            availability_row = availability.get(anchor.anchor_id)
            availability_mapping_ok = bool(
                availability_row
                and _mapping_is_sequence_isoform_species(availability_row.get("mapping_evidence"))
            )
            measurable = bool(
                availability_row
                and _as_bool(availability_row.get("is_measurable"))
                and availability_mapping_ok
            )
            weight = float(self.tier_weights.get(anchor.tier, 0.0))
            observation = observations.get(anchor.anchor_id)
            detected = bool(observation and _as_bool(observation.get("detected"))) if measurable else False
            regulated = bool(observation and _as_bool(observation.get("regulated"))) if detected else False
            direction_correct = self._direction_correct(anchor, observation) if regulated else False
            peak_correct = self._peak_correct(anchor, observation) if regulated else False

            if measurable:
                denominators["detectable_anchor_recall"] += weight
                denominators["regulated_anchor_recall"] += weight
                numerators["detectable_anchor_recall"] += weight if detected else 0.0
                numerators["regulated_anchor_recall"] += weight if regulated else 0.0
            if regulated:
                denominators["direction_accuracy"] += weight
                denominators["peak_window_accuracy"] += weight
                numerators["direction_accuracy"] += weight if direction_correct else 0.0
                numerators["peak_window_accuracy"] += weight if peak_correct else 0.0
            if detected:
                branch_detected[anchor.branch].append(anchor)

            anchor_rows.append(
                {
                    "anchor_id": anchor.anchor_id,
                    "tier": anchor.tier,
                    "branch": anchor.branch,
                    "is_measurable": measurable,
                    "detected": detected,
                    "regulated": regulated,
                    "direction_correct": direction_correct if regulated else None,
                    "peak_window_correct": peak_correct if regulated else None,
                    "mapping_rejected": anchor.anchor_id in mapping_rejections or bool(availability_row and not availability_mapping_ok),
                    "exclusion_reason": None if measurable else (
                        "sequence_isoform_species_mapping_required"
                        if availability_row and not availability_mapping_ok
                        else (availability_row or {}).get("reason", "not_declared_measurable")
                    ),
                }
            )

        metrics = {
            key: _safe_ratio(numerators[key], denominators[key])
            for key in (
                "detectable_anchor_recall",
                "regulated_anchor_recall",
                "direction_accuracy",
                "peak_window_accuracy",
            )
        }
        metrics["chain_completeness"] = self._chain_completeness(
            analysis_artifact.get("branch_evidence", []), branch_detected
        )
        metrics["canonical_weighted_score"] = self._weighted_score(metrics)

        return {
            "schema_version": "ptm_locked_score_result.v1",
            "dataset_id": self.manifest.dataset_id,
            "metrics": metrics,
            "metric_denominators": dict(denominators),
            "metric_numerators": dict(numerators),
            "anchor_results": anchor_rows,
            "provenance": {
                "manifest_path": str(self.manifest.path),
                "locked_truth_sha256": self.manifest.raw["locked_truth_sha256"],
                "production_contract": self.manifest.production_contract,
                "blind_policy": self.manifest.blind_policy,
                "mapping_requirement": "sequence_isoform_species",
                "mapping_rejections": sorted(mapping_rejections),
                "analysis_artifact_provenance": analysis_artifact.get("provenance", {}),
            },
        }

    def _index_availability(self, rows: Any) -> dict[str, Mapping[str, Any]]:
        if not isinstance(rows, list):
            raise LockedScoreError("site_availability must be a list")
        indexed: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            anchor_id = self._match_anchor_id(row)
            if anchor_id and anchor_id not in indexed:
                indexed[anchor_id] = row
        return indexed

    def _index_observations(self, rows: Any) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
        if not isinstance(rows, list):
            raise LockedScoreError("site_observations must be a list")
        observations: dict[str, Mapping[str, Any]] = {}
        rejected: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            anchor_id = self._match_anchor_id(row)
            if not anchor_id:
                continue
            if not _mapping_is_sequence_isoform_species(row.get("mapping_evidence")):
                rejected.add(anchor_id)
                continue
            observations[anchor_id] = row
        return observations, rejected

    def _match_anchor_id(self, row: Mapping[str, Any]) -> str | None:
        """Resolve a generic observed site to one unambiguous locked anchor.

        The generic artifact never contains `Anchor_ID`.  This routine runs
        after blind analysis has completed and treats gene/site as a candidate
        lookup only; the row is scoreable only if mapping evidence separately
        proves sequence, isoform, and species agreement.
        """

        gene = str(row.get("gene") or row.get("Gene.Name") or "").strip().upper()
        site = _normalise_site(row.get("site") or row.get("position") or row.get("PTM_Position"))
        if not gene or not site:
            return None
        candidates = [
            anchor.anchor_id
            for anchor in self.anchors.values()
            if anchor.gene == gene
            and site in {_normalise_site(anchor.rat_site), _normalise_site(anchor.human_site)}
        ]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _direction_correct(anchor: _Anchor, observation: Mapping[str, Any] | None) -> bool:
        if not observation:
            return False
        expected = _normalise_direction(anchor.expected_direction)
        observed = _normalise_direction(observation.get("phosphorylation_direction"))
        if not expected or not observed:
            return False
        if "biphasic" in expected:
            return observed in {"up", "biphasic", "up_or_biphasic"}
        return ("up" in expected and observed == "up") or ("down" in expected and observed == "down")

    @staticmethod
    def _peak_correct(anchor: _Anchor, observation: Mapping[str, Any] | None) -> bool:
        if not observation:
            return False
        expected = _parse_window_minutes(anchor.peak_window)
        try:
            observed = float(observation.get("peak_minutes"))
        except (TypeError, ValueError):
            return False
        return bool(expected and expected[0] <= observed <= expected[1])

    @staticmethod
    def _chain_completeness(
        rows: Any, branch_detected: Mapping[str, list[_Anchor]]
    ) -> float | None:
        if isinstance(rows, list) and rows:
            evaluable = [row for row in rows if isinstance(row, Mapping) and _as_bool(row.get("evaluable"))]
            if not evaluable:
                return None
            complete = [
                row
                for row in evaluable
                if int(row.get("ordered_layers", 0) or 0) >= int(row.get("minimum_layers", 2) or 2)
            ]
            return len(complete) / len(evaluable)
        evaluable_branches = [branch for branch, anchors in branch_detected.items() if anchors]
        if not evaluable_branches:
            return None
        return sum(len(branch_detected[branch]) >= 2 for branch in evaluable_branches) / len(evaluable_branches)

    def _weighted_score(self, metrics: Mapping[str, float | None]) -> float | None:
        included = {
            key: value
            for key, value in metrics.items()
            if key != "canonical_weighted_score" and value is not None and key in self.weights
        }
        total_weight = sum(self.weights[key] for key in included)
        if total_weight <= 0:
            return None
        return sum(float(included[key]) * self.weights[key] for key in included) / total_weight


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None
