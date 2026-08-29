"""P2: Known temporal relation registry and order concordance scoring.

Provides two separate tests per PDF §2:
  A. Within-Wave event synchrony: are same-Wave sites' onset times similar?
     P(|t_onset_i - t_onset_j| ≤ τ) — null = Wave membership permutation.
     Supports claim: "static Wave enriches onset-synchronous events."

  B. Directed temporal precedence concordance: for pre-specified source→target
     relations, P(t_source + δ ∈ [allowed_lag_min, allowed_lag_max] before t_target).
     Null: hierarchical replicate bootstrap + relation-level temporal permutation.
     Supports claim: "observed temporal precedence with uncertainty."

RUNNER-ONLY RULE
----------------
Known relation registries contain ground-truth temporal order facts.
They MUST NOT flow into production temporal output or LLM context.
Instantiate KnownRelationRegistry only inside benchmark runner code.

CLAIM LIMITS
------------
Test A → structural claim only ("synchrony enriched in Waves"), NOT kinase attribution.
Test B → "observed temporal precedence with posterior uncertainty", NOT causal order.

Implementation target: PDF §2 P2.
Pre-registration: 2026-08-29.
"""

from __future__ import annotations

import enum
import json
import random
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.replicate_event_adapter import EventRecord, EventStatus
from ptm_shared.study_temporal_context import StudyTemporalContext, INSULIN_TEMPORAL_CONTEXT

CONTRACT_VERSION = "temporal_relation_registry.v1"


class EvidenceTier(str, enum.Enum):
    known_literature = "known_literature"
    kinase_substrate_db = "kinase_substrate_db"
    computational_prediction = "computational_prediction"
    experimental_prior = "experimental_prior"


@dataclass(frozen=True)
class RelationSpec:
    """A single pre-specified temporal relation between two biological events.

    Attributes
    ----------
    source_site : str  — upstream site key (e.g., "INSR_Y1158")
    target_site : str  — downstream site key
    allowed_lag_min : float  — minimum expected lag (minutes); 0 = simultaneous
    allowed_lag_max : float  — maximum expected lag (minutes)
    expected_direction : str — "source_before_target" | "synchronous" | "target_before_source"
    evidence_tier : EvidenceTier
    evidence_note : str  — literature/DB citation
    study_id : str  — which study this relation applies to
    """

    source_site: str
    target_site: str
    allowed_lag_min: float
    allowed_lag_max: float
    expected_direction: str
    evidence_tier: EvidenceTier
    evidence_note: str
    study_id: str

    def __post_init__(self) -> None:
        if self.allowed_lag_min > self.allowed_lag_max:
            raise ValueError(
                f"allowed_lag_min ({self.allowed_lag_min}) > allowed_lag_max ({self.allowed_lag_max})"
            )
        if self.expected_direction not in (
            "source_before_target", "synchronous", "target_before_source"
        ):
            raise ValueError(f"Invalid expected_direction: {self.expected_direction}")


class KnownRelationRegistry:
    """RUNNER-ONLY registry of pre-specified known temporal relations.

    Load from a JSON file or pass a list of RelationSpec objects directly.
    Never expose this registry or its contents to production temporal output.

    JSON format: list of dicts matching RelationSpec fields.
    """

    def __init__(self, relations: list[RelationSpec], *, study_id: str) -> None:
        self._relations = relations
        self.study_id = study_id

    @classmethod
    def from_json(cls, path: str | Path) -> "KnownRelationRegistry":
        """Load registry from JSON file."""
        data = json.loads(Path(path).read_text())
        study_id = data.get("study_id", "unknown")
        relations = [
            RelationSpec(
                source_site=r["source_site"],
                target_site=r["target_site"],
                allowed_lag_min=float(r["allowed_lag_min"]),
                allowed_lag_max=float(r["allowed_lag_max"]),
                expected_direction=r["expected_direction"],
                evidence_tier=EvidenceTier(r["evidence_tier"]),
                evidence_note=r.get("evidence_note", ""),
                study_id=study_id,
            )
            for r in data.get("relations", [])
        ]
        return cls(relations, study_id=study_id)

    @classmethod
    def stub_insulin_registry(cls) -> "KnownRelationRegistry":
        """Minimal insulin signaling stub registry for testing/development.

        Three regulated anchors from the locked benchmark (1 of 3 currently
        recovered with condition-mean data).

        Source: benchmarking/known_insulin_relations.json (runner-only).
        Evidence tier: known_literature.
        Note: 3 relations → denominator too small for reliable timing score.
        Expand registry before using timing accuracy as optimisation target.
        """
        relations = [
            RelationSpec(
                source_site="INSR_Y1158",
                target_site="IRS1_S302",
                allowed_lag_min=0.0,
                allowed_lag_max=5.0,
                expected_direction="source_before_target",
                evidence_tier=EvidenceTier.known_literature,
                evidence_note="Insulin receptor autophosphorylation precedes IRS1 S302. "
                              "White 1985 JBC; Shoelson 1992 Mol Cell.",
                study_id="insulin_signaling_rat_phosphoproteomics",
            ),
            RelationSpec(
                source_site="IRS1_S302",
                target_site="AKT1_T308",
                allowed_lag_min=1.0,
                allowed_lag_max=10.0,
                expected_direction="source_before_target",
                evidence_tier=EvidenceTier.known_literature,
                evidence_note="IRS1 engagement precedes AKT T308 phosphorylation. "
                              "Alessi 1996 EMBO J.",
                study_id="insulin_signaling_rat_phosphoproteomics",
            ),
            RelationSpec(
                source_site="AKT1_T308",
                target_site="GSK3B_S9",
                allowed_lag_min=0.0,
                allowed_lag_max=10.0,
                expected_direction="source_before_target",
                evidence_tier=EvidenceTier.known_literature,
                evidence_note="AKT phosphorylates GSK3β S9 to inactivate it. "
                              "Cross 1995 Nature.",
                study_id="insulin_signaling_rat_phosphoproteomics",
            ),
        ]
        return cls(relations, study_id="insulin_signaling_rat_phosphoproteomics")

    @property
    def relations(self) -> list[RelationSpec]:
        return list(self._relations)

    def coverage_report(self, event_records: Mapping[str, EventRecord]) -> dict[str, Any]:
        """How many relations have both sites with evaluable event records.

        EFFICACY WARNING: Do NOT use the 3-relation stub as an efficacy metric.
        The insulin stub registry has 3 pre-specified relations whose site keys
        (e.g. INSR_Y1158) may not match the actual site key format in the event
        records (e.g. INSR_Y1158_Y1162_Y1163 or similar multi-site keys).

        Before measuring timing accuracy:
          1. Verify site key format matches the event record keys.
          2. Expand the registry to >= 10 relations.
          3. Use discover_relation_candidates() to find data-driven candidates.
        """
        eligible = 0
        covered = 0
        for rel in self._relations:
            src = event_records.get(rel.source_site)
            tgt = event_records.get(rel.target_site)
            if src is None or tgt is None:
                continue
            eligible += 1
            src_ok = src.event_status not in (
                EventStatus.unresolved,
                EventStatus.not_evaluable_replicate_posterior,
                EventStatus.not_evaluable_context_not_registered,
            )
            tgt_ok = tgt.event_status not in (
                EventStatus.unresolved,
                EventStatus.not_evaluable_replicate_posterior,
                EventStatus.not_evaluable_context_not_registered,
            )
            if src_ok and tgt_ok and src.peak_t_min is not None and tgt.peak_t_min is not None:
                covered += 1
        efficacy_warning = ""
        if len(self._relations) <= 3:
            efficacy_warning = (
                "EFFICACY WARNING: <= 3 relations is insufficient for timing accuracy measurement. "
                "Expand registry and verify site key format before use as an efficacy metric."
            )
        return {
            "n_relations_total": len(self._relations),
            "n_eligible": eligible,
            "n_covered": covered,
            "evaluable_coverage": round(covered / eligible, 4) if eligible else 0.0,
            "efficacy_warning": efficacy_warning,
            "note": (
                "Zero coverage may indicate site key format mismatch. "
                "Run coverage_report() with the actual event_records before using this registry."
                if covered == 0 and eligible == 0 and len(self._relations) > 0 else ""
            ),
        }


# ── Data-driven relation candidate discovery (Fix-4, 2026-08-29 audit) ───

def discover_relation_candidates(
    wave_contract: Mapping[str, Any],
    event_records: Mapping[str, EventRecord],
    *,
    min_lag_min: float = 1.0,
    max_lag_min: float = 30.0,
    min_peak_fc_abs: float = 0.4,
    min_bootstrap_stability: float = 0.6,
    study_id: str = "unknown",
) -> list[dict[str, Any]]:
    """Discover data-driven temporal precedence candidate pairs within each Wave.

    RUNNER-ONLY: Candidates are exploratory. They require expert curation and
    independent validation before becoming pre-specified known relations.

    Algorithm:
      1. Collect same-Wave pairs where both sites have evaluable peak times.
      2. Require |peak_fc| >= min_peak_fc_abs for signal quality.
      3. Require bootstrap_stability >= min_bootstrap_stability (replicate) OR
         exploratory_model_uncertainty >= threshold (GP model — weaker signal).
      4. Compute observed lag = t_peak_target - t_peak_source.
      5. Return pairs where min_lag_min <= |lag| <= max_lag_min.

    Returns list of candidate dicts (source_site, target_site, observed_lag_min,
    wave_id, data_quality, candidate_tier).

    candidate_tier:
      "replicate_supported" — replicate_bootstrap_stability available
      "model_only" — only exploratory_model_uncertainty available (weaker)
    """
    site_to_wave: dict[str, str] = {}
    for wave in wave_contract.get("waves", []):
        wid = wave["wave_id"]
        for m in wave.get("members", []):
            site_to_wave[m] = wid

    wave_to_sites: dict[str, list[str]] = {}
    for site, wid in site_to_wave.items():
        wave_to_sites.setdefault(wid, []).append(site)

    _not_evaluable_statuses = {
        EventStatus.unresolved,
        EventStatus.not_evaluable_replicate_posterior,
        EventStatus.not_evaluable_context_not_registered,
    }

    def _quality(rec: EventRecord) -> tuple[bool, float, str]:
        """(is_evaluable, stability_score, tier)"""
        if rec.event_status in _not_evaluable_statuses:
            return False, 0.0, "none"
        if rec.peak_t_min is None:
            return False, 0.0, "none"
        if abs(rec.peak_fc or 0.0) < min_peak_fc_abs:
            return False, 0.0, "insufficient_signal"
        if rec.replicate_bootstrap_stability is not None:
            return True, rec.replicate_bootstrap_stability, "replicate_supported"
        if rec.exploratory_model_uncertainty is not None:
            return True, rec.exploratory_model_uncertainty, "model_only"
        return True, 0.0, "no_stability_estimate"

    candidates: list[dict[str, Any]] = []

    for wave_id, sites in wave_to_sites.items():
        evaluable = []
        for site in sites:
            rec = event_records.get(site)
            if rec is None:
                continue
            is_eval, score, tier = _quality(rec)
            if not is_eval:
                continue
            if score < min_bootstrap_stability and tier == "replicate_supported":
                continue
            evaluable.append((site, rec, score, tier))

        for i in range(len(evaluable)):
            for j in range(len(evaluable)):
                if i == j:
                    continue
                src_site, src_rec, src_score, src_tier = evaluable[i]
                tgt_site, tgt_rec, tgt_score, tgt_tier = evaluable[j]
                lag = (tgt_rec.peak_t_min or 0.0) - (src_rec.peak_t_min or 0.0)
                if not (min_lag_min <= lag <= max_lag_min):
                    continue
                candidates.append({
                    "source_site": src_site,
                    "target_site": tgt_site,
                    "wave_id": wave_id,
                    "observed_lag_min": round(lag, 3),
                    "source_peak_t_min": src_rec.peak_t_min,
                    "target_peak_t_min": tgt_rec.peak_t_min,
                    "source_bootstrap_score": src_score,
                    "target_bootstrap_score": tgt_score,
                    "candidate_tier": (
                        "replicate_supported"
                        if (src_tier == "replicate_supported"
                            and tgt_tier == "replicate_supported")
                        else "model_only"
                    ),
                    "study_id": study_id,
                    "status": "data_driven_candidate_requires_curation",
                    "warning": (
                        "Exploratory only. Requires expert biological curation and "
                        "independent held-out validation before becoming a "
                        "pre-specified known relation."
                    ),
                })

    return sorted(candidates, key=lambda x: x["candidate_tier"])


# ── Test A: Within-Wave event synchrony ───────────────────────────────────

def within_wave_synchrony_test(
    wave_contract: Mapping[str, Any],
    event_records: Mapping[str, EventRecord],
    study_context: StudyTemporalContext | None = None,
    *,
    permutation_n: int = 500,
    seed: int = 20260829,
) -> dict[str, Any]:
    """Test A: P(|t_onset_i - t_onset_j| ≤ τ) within static Wave pairs.

    Null distribution: Wave membership label permutation.
    Supports claim: "static Wave enriches onset-synchronized events."
    Does NOT support kinase attribution or causal ordering claims.

    Parameters
    ----------
    wave_contract : canonical wave contract (not mutated)
    event_records : {site_key: EventRecord} from P1 adapter
    study_context : provides synchrony_tau_minutes (default: insulin, τ=5 min)
    permutation_n : number of label permutations for null distribution
    """
    ctx = study_context or INSULIN_TEMPORAL_CONTEXT
    tau = ctx.synchrony_tau_minutes

    # Collect (site, wave_id) mapping
    site_to_wave: dict[str, str] = {}
    for wave in wave_contract.get("waves", []):
        wid = wave["wave_id"]
        for m in wave.get("members", []):
            site_to_wave[m] = wid

    all_sites = list(site_to_wave)

    def _synchrony_fraction(assignment: dict[str, str]) -> float:
        """Fraction of same-Wave pairs whose onset gap ≤ τ."""
        wave_groups: dict[str, list[float]] = {}
        for site, wid in assignment.items():
            rec = event_records.get(site)
            if rec is None or rec.onset_t50_min is None:
                continue
            wave_groups.setdefault(wid, []).append(rec.onset_t50_min)

        synced = 0
        total = 0
        for onsets in wave_groups.values():
            for a, b in combinations(onsets, 2):
                total += 1
                if abs(a - b) <= tau:
                    synced += 1
        return synced / total if total > 0 else float("nan")

    observed = _synchrony_fraction(site_to_wave)

    if not isinstance(observed, float) or np.isnan(observed):
        return {
            "status": "skipped_no_evaluable_onset_pairs",
            "tau_minutes": tau,
            "synchrony_fraction_observed": None,
        }

    # Null: permute wave labels
    rng = random.Random(seed)
    wave_ids = list(site_to_wave.values())
    null_values: list[float] = []
    for _ in range(permutation_n):
        shuffled = wave_ids.copy()
        rng.shuffle(shuffled)
        perm_assignment = dict(zip(all_sites, shuffled))
        v = _synchrony_fraction(perm_assignment)
        if not np.isnan(v):
            null_values.append(v)

    if not null_values:
        return {
            "status": "skipped_empty_null",
            "tau_minutes": tau,
            "synchrony_fraction_observed": round(observed, 4),
        }

    null_arr = np.array(null_values)
    n_exceed = int(np.sum(null_arr >= observed))
    p_empirical = (n_exceed + 1) / (len(null_arr) + 1)

    return {
        "status": "computed",
        "tau_minutes": tau,
        "synchrony_fraction_observed": round(observed, 4),
        "null_mean": round(float(np.mean(null_arr)), 4),
        "null_std": round(float(np.std(null_arr)), 4),
        "n_permutations": len(null_values),
        "n_exceedances": n_exceed,
        "p_empirical_one_sided": round(p_empirical, 6),
        "claim_limit": (
            "p < 0.05 supports 'static Wave enriches onset-synchronized events'. "
            "Does NOT support kinase attribution."
        ),
        "contract_version": CONTRACT_VERSION,
    }


# ── Test B: Directed temporal precedence concordance ─────────────────────

def _posterior_order_probability(
    t_source: float | None,
    t_source_ci: tuple[float, float] | None,
    t_target: float | None,
    t_target_ci: tuple[float, float] | None,
    allowed_lag_min: float,
    allowed_lag_max: float,
    *,
    n_samples: int = 2000,
    seed: int = 20260829,
) -> dict[str, Any]:
    """P(t_source + allowed_lag ∈ [min, max] < t_target) via CI Monte Carlo.

    Uses uniform distributions over CIs as a conservative approximation.
    Returns posterior_order_prob, ci_overlap, evaluable status.
    """
    if t_source is None or t_target is None:
        return {"evaluable": False, "reason": "missing_event_time"}

    # Point estimate check
    point_source_late = t_source + allowed_lag_max
    point_source_early = t_source + allowed_lag_min
    point_concordant = point_source_early < t_target and t_target <= point_source_late

    # CI Monte Carlo
    rng = np.random.default_rng(seed)

    def _sample_time(t: float, ci: tuple | None) -> np.ndarray:
        if ci is None:
            return np.full(n_samples, t)
        lo, hi = ci
        # Use normal centred on t with std derived from CI half-width
        half = (hi - lo) / 4.0  # 2σ = CI half → σ = CI_half/2
        half = max(half, 1e-6)
        return rng.normal(t, half, size=n_samples)

    src_samples = _sample_time(t_source, t_source_ci)
    tgt_samples = _sample_time(t_target, t_target_ci)

    lag = tgt_samples - src_samples
    concordant = (lag >= allowed_lag_min) & (lag <= allowed_lag_max)
    p_order = float(np.mean(concordant))

    # CI overlap: fraction of samples where CIs overlap
    ci_overlap = float(np.mean(np.abs(src_samples - tgt_samples) < 0.5 * allowed_lag_max))

    return {
        "evaluable": True,
        "point_concordant": bool(point_concordant),
        "posterior_order_probability": round(p_order, 4),
        "ci_overlap_fraction": round(ci_overlap, 4),
        "t_source_min": round(float(t_source), 3),
        "t_target_min": round(float(t_target), 3),
    }


def directed_precedence_concordance(
    registry: KnownRelationRegistry,
    event_records: Mapping[str, EventRecord],
    *,
    n_samples: int = 2000,
    seed: int = 20260829,
) -> dict[str, Any]:
    """Test B: P(t_source + δ < t_target) for pre-specified relations.

    Effect size: per-relation posterior order probability, CI overlap,
    and evaluable coverage — NOT a single aggregate p-value.

    RUNNER-ONLY: uses known ground-truth relations.
    Claim limit: "observed temporal precedence with uncertainty." NOT causal.
    """
    results = []
    n_evaluable = 0
    n_concordant = 0

    for rel in registry.relations:
        src_rec = event_records.get(rel.source_site)
        tgt_rec = event_records.get(rel.target_site)

        if src_rec is None or tgt_rec is None:
            results.append({
                "relation": f"{rel.source_site}→{rel.target_site}",
                "evaluable": False,
                "reason": "site_not_in_event_records",
                "evidence_tier": rel.evidence_tier.value,
            })
            continue

        order_result = _posterior_order_probability(
            src_rec.peak_t_min,
            src_rec.peak_ci95_min,
            tgt_rec.peak_t_min,
            tgt_rec.peak_ci95_min,
            rel.allowed_lag_min,
            rel.allowed_lag_max,
            n_samples=n_samples,
            seed=seed,
        )

        row: dict[str, Any] = {
            "relation": f"{rel.source_site}→{rel.target_site}",
            "expected_direction": rel.expected_direction,
            "allowed_lag_min_min": rel.allowed_lag_min,
            "allowed_lag_max_min": rel.allowed_lag_max,
            "evidence_tier": rel.evidence_tier.value,
            "source_event_status": src_rec.event_status.value,
            "target_event_status": tgt_rec.event_status.value,
        }
        row.update(order_result)

        if order_result["evaluable"]:
            n_evaluable += 1
            if order_result.get("point_concordant", False):
                n_concordant += 1

        results.append(row)

    coverage = registry.coverage_report(event_records)

    return {
        "status": "computed",
        "n_relations_total": len(registry.relations),
        "n_evaluable": n_evaluable,
        "n_point_concordant": n_concordant,
        "evaluable_coverage": coverage["evaluable_coverage"],
        "coverage_note": coverage.get("note", ""),
        "per_relation": results,
        "claim_limit": (
            "Results express 'observed temporal precedence with uncertainty'. "
            "Not causal evidence. Not flow to production output."
        ),
        "contract_version": CONTRACT_VERSION,
    }
