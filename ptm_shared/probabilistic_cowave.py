"""Probabilistic Co-Wave: GP-based trajectory uncertainty for Dynamic Co-Wave.

Replaces hard-threshold binary activity judgements with posterior probability
estimates derived from a Gaussian Process (squared-exponential kernel) fitted
to condition-level log2FC trajectories.  The deterministic Dynamic Co-Wave
(dynamic_cowave_transition.py) remains the primary analysis; this module adds
a parallel probabilistic layer without altering Wave membership or TMM scores.

Implementation target: docs/integrated_research_design_v2.md §3 Probabilistic
  Dynamic Co-Wave, Roadmap §3 Probabilistic Dynamic Co-Wave.
Pre-registration: 2026-08-28 동결.  Inhibitor 데이터 공개 전 확정.
Interpretation limits:
  - Condition-level trajectories only (no replicate-level input available).
    GP noise term absorbs biological replicate variance implicitly.
  - P(active|data) is a soft analogue of the hard threshold, not a causal claim.
  - P(same_direction) reflects trajectory curvature similarity, not kinase sharing.
  - Hyperparameters are fixed by domain knowledge (signaling timescale ~15 min),
    not fitted per site — fitting 3 params on 6 points overfits.
Claim boundary: do not use P(active|data) to claim kinase-attribution accuracy
  improvement without a held-out inhibitor prediction evaluation.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np

CONTRACT_VERSION = "probabilistic_cowave.v1"

# ── Hyperparameter defaults ────────────────────────────────────────────────
# length_scale: characteristic signaling timescale (minutes).
#   PI3K-AKT response peaks ~5-15 min; ERK ~5-30 min.  15 min is a conservative
#   mid-range choice that smooths replicate noise without washing out fast events.
#   Source: Humphrey 2013 Cell Metab; Parker 2015 Sci Signal (docs/ refs §10).
#   Pre-registered 2026-08-28; must not be tuned after inhibitor data is seen.
GP_LENGTH_SCALE_MIN: float = 15.0
"""Minimum GP length scale in raw minutes.

Pre-registered 2026-08-28.  Used with time_transform="minutes" (production default).
Corresponds to ~15-minute smoothing window; prevents single-timepoint overfitting.
"""

GP_LOG1P_LENGTH_SCALE_MIN: float = 2.0
"""Minimum GP length scale in log1p(minutes) coordinate space.

EXPERIMENTAL — not production-validated as of 2026-08-29.
Revalidation on raw insulin (2026-08-29): T_adjacency p=0.284327, not significant.
log1p default reverted to "minutes"; this constant is available for
future experiments but must NOT be used without passing it explicitly.

Derivation: log1p(15) ≈ 2.71; log1p(5) ≈ 1.79.  A value of 2.0 ≈ "15 min
smoothing near the early trajectory" in log1p space.

IMPORTANT — unit mismatch trap: if time_transform="log1p_minutes" is used with
the default GP_LENGTH_SCALE_MIN=15, the kernel is nearly degenerate because all
log1p(minute) values lie in [0.69, 5.20] and l=15 dwarfs the entire axis.
Always pass length_scale_min=GP_LOG1P_LENGTH_SCALE_MIN when using log1p transform:
    estimate_trajectory_posterior(
        labels, fcs,
        time_transform="log1p_minutes",
        length_scale_min=GP_LOG1P_LENGTH_SCALE_MIN,
    )
Pre-registration: 2026-08-29 as EXPERIMENTAL.
"""

# signal_var: prior variance of the latent trajectory.
#   Estimated from data variance at runtime when None.
GP_SIGNAL_VAR: float | None = None

# noise_var_fraction: observation noise as fraction of signal variance.
#   Condition-level medians from 3 replicates suppress ~1/sqrt(3) of replicate
#   noise; 0.10 is a conservative prior.
#   Pre-registered 2026-08-28.
GP_NOISE_VAR_FRACTION: float = 0.10

# activity_threshold_fc: mirrors DYNAMIC_COWAVE_CONFIG for P(active) integration.
#   Pre-registered 2026-08-28 (same as deterministic layer).
ACTIVITY_THRESHOLD_FC: float = 0.40


def _se_kernel(
    t1: np.ndarray,
    t2: np.ndarray,
    length_scale: float,
    signal_var: float,
) -> np.ndarray:
    """Squared-exponential (RBF) kernel K(t1, t2)."""
    diff = (t1[:, None] - t2[None, :]) / length_scale
    return signal_var * np.exp(-0.5 * diff ** 2)


def _gp_posterior(
    t_obs: np.ndarray,
    y_obs: np.ndarray,
    t_query: np.ndarray,
    length_scale: float,
    signal_var: float,
    noise_var: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (posterior_mean, posterior_variance) at t_query.

    Uses Cholesky solve for numerical stability.  Missing observations (NaN)
    are dropped before conditioning so incomplete trajectories are handled.
    """
    mask = ~np.isnan(y_obs)
    t_obs_valid = t_obs[mask]
    y_obs_valid = y_obs[mask]

    n = len(t_obs_valid)
    if n == 0:
        # No observations: return prior
        return np.zeros(len(t_query)), np.full(len(t_query), signal_var)

    K_nn = _se_kernel(t_obs_valid, t_obs_valid, length_scale, signal_var)
    K_nn += (noise_var + 1e-8) * np.eye(n)  # jitter for numerical stability
    K_sn = _se_kernel(t_query, t_obs_valid, length_scale, signal_var)
    K_ss_diag = np.full(len(t_query), signal_var)  # prior variance on diagonal

    try:
        L = np.linalg.cholesky(K_nn)
    except np.linalg.LinAlgError:
        # Fallback to pseudo-inverse if Cholesky fails (near-singular)
        alpha = np.linalg.lstsq(K_nn, y_obs_valid, rcond=None)[0]
        mu = K_sn @ alpha
        v = np.linalg.lstsq(K_nn, K_sn.T, rcond=None)[0]
        var = K_ss_diag - np.sum(K_sn * v.T, axis=1)
    else:
        alpha = np.linalg.solve(L.T, np.linalg.solve(L, y_obs_valid))
        mu = K_sn @ alpha
        v = np.linalg.solve(L, K_sn.T)
        var = K_ss_diag - np.sum(v ** 2, axis=0)

    var = np.maximum(var, 1e-10)
    return mu, var


def _normal_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc for zero external deps."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _p_above_threshold(
    mean: float,
    std: float,
    threshold: float,
) -> float:
    """P(FC > threshold | GP posterior N(mean, std²))."""
    if std <= 0:
        return 1.0 if mean > threshold else 0.0
    return 1.0 - _normal_cdf((threshold - mean) / std)


def _p_below_neg_threshold(
    mean: float,
    std: float,
    threshold: float,
) -> float:
    """P(FC < -threshold | GP posterior N(mean, std²))."""
    if std <= 0:
        return 1.0 if mean < -threshold else 0.0
    return _normal_cdf((-threshold - mean) / std)


def _parse_timepoint_label(label: str) -> float | None:
    """Parse a single timepoint label to minutes.

    Supported formats (case-insensitive, spaces ignored):
      - minutes:  "15min", "15m", "15 min", "15minutes", "15 minutes" → 15.0
      - hours:    "2hr", "2h", "2 hr", "2hours", "2 hour"            → 120.0
      - days:     "1day", "1d", "1 day", "1days"                     → 1440.0
      - seconds:  "30s", "30sec", "30 sec", "30second"               → 0.5
      - bare num: "15", "0.5"                                        → 15.0, 0.5

    Returns None if the label cannot be parsed.

    Design notes (generalizability):
      Different time-course studies use different time units.  This parser enables
      the platform to handle EGF (minutes), hypoxia (hours), cell cycle (hours),
      developmental (days) without changing any downstream GP/statistic code.
      All internal representations use **minutes** as the canonical unit.
    """
    s = str(label).strip().lower().replace(" ", "")
    # Try each unit suffix in decreasing specificity
    for suffix, factor in [
        ("minutes", 1.0), ("minute", 1.0), ("min", 1.0),
        ("hours", 60.0), ("hour", 60.0), ("hr", 60.0), ("h", 60.0),
        ("days", 1440.0), ("day", 1440.0), ("d", 1440.0),
        ("seconds", 1 / 60.0), ("second", 1 / 60.0), ("sec", 1 / 60.0),
        ("s", 1 / 60.0),
        ("m", 1.0),  # "m" last to avoid matching "min" residual
    ]:
        if s.endswith(suffix):
            num_str = s[: len(s) - len(suffix)]
            try:
                return float(num_str) * factor
            except ValueError:
                return None
    # Bare number — assume minutes (backward-compatible with original behaviour)
    try:
        return float(s)
    except ValueError:
        return None


def _timepoints_to_minutes(labels: Sequence[str]) -> np.ndarray:
    """Parse timepoint labels → float array of minutes.

    Handles min/h/hr/day/d/s suffixes and bare numbers.
    Falls back to 0, 1, 2, ... index spacing when any label fails to parse,
    and emits a warning so the caller is aware of the degradation.

    See _parse_timepoint_label() for supported formats.
    """
    result: list[float] = []
    for label in labels:
        val = _parse_timepoint_label(label)
        if val is None:
            import warnings
            warnings.warn(
                f"Could not parse timepoint label '{label}' to minutes; "
                "falling back to integer index spacing for all timepoints. "
                "Supported suffixes: min/m, hr/h, day/d, s/sec. "
                "GP kernel distances will be in index units, not physical time.",
                UserWarning,
                stacklevel=3,
            )
            return np.arange(len(labels), dtype=float)
        result.append(val)
    return np.array(result, dtype=float)


def _timepoints_to_log1p_minutes(labels: Sequence[str]) -> np.ndarray:
    """Parse timepoint labels → log1p(minutes) coordinates.

    EXPERIMENTAL coordinate (reverted to "minutes" default on 2026-08-29).
    Requires passing length_scale_min=GP_LOG1P_LENGTH_SCALE_MIN when used.

    Notes on generalisation across study types:
      log1p compression is more beneficial when the time grid spans multiple
      orders of magnitude (e.g., insulin 1→180 min = 2.3 decades).
      For uniformly-spaced grids (cell cycle, circadian) it provides little benefit.
      For studies where ALL intervals are already uniform (e.g., every 4 h), use
      time_transform="minutes" with an appropriate length_scale.

    Pre-registered as EXPERIMENTAL for insulin signaling: 2026-08-28.
    Revalidation on raw insulin (2026-08-29): T_adjacency p=0.284327, not significant.
    Source: Image §4 Dynamic Co-Wave v3 recommendation.
    """
    minutes = _timepoints_to_minutes(labels)
    return np.log1p(minutes)


# ── Public API ─────────────────────────────────────────────────────────────

def estimate_trajectory_posterior(
    timepoint_labels: Sequence[str],
    fc_values: Sequence[float | None],
    *,
    length_scale_min: float = GP_LENGTH_SCALE_MIN,
    signal_var: float | None = GP_SIGNAL_VAR,
    noise_var_fraction: float = GP_NOISE_VAR_FRACTION,
    activity_threshold_fc: float = ACTIVITY_THRESHOLD_FC,
    time_transform: str = "minutes",
) -> dict[str, Any]:
    """Compute GP posterior for a single site trajectory.

    Implementation target: Roadmap §3 Probabilistic Dynamic Co-Wave (v2+v3).
    Pre-registration: 2026-08-28.
    Interpretation limits:
      - Condition-level FC only; no replicate decomposition (current v2 limitation).
      - v3 model will model per-replicate intensity y_irt = f_i(t) + b_ir + ε_irt
        (requires replicate-level input not yet available in production pipeline).
    Claim boundary: do not claim kinase-activity inference from P(active) alone.

    Parameters
    ----------
    time_transform : "minutes" | "log1p_minutes"
        Coordinate system for GP kernel distances.
        "minutes" (default, production-safe): raw minutes.  length_scale_min=15 is
          defined in minute units; coordinate and length-scale are consistent.
        "log1p_minutes" (experimental only): log1p(minutes).  NOTE: length_scale_min
          must be re-specified in log1p units when using this transform — see
          GP_LOG1P_LENGTH_SCALE_MIN.  Do NOT use as production default until the
          coordinate–length-scale mismatch is resolved and biological validation is
          complete.  Revalidation on raw insulin (2026-08-29): T_adjacency p=0.284327
          (not significant); log1p effect not demonstrated.  Promoted back to
          experimental ("minutes" default restored 2026-08-29).

    Returns
    -------
    dict with keys:
      posterior_mean        list[float]   — posterior mean at each timepoint
      posterior_std         list[float]   — posterior std at each timepoint
      p_positive_active     list[float]   — P(FC > threshold | data)
      p_negative_active     list[float]   — P(FC < -threshold | data)
      p_inactive            list[float]   — 1 - p_pos - p_neg
      p_active              list[float]   — P(|FC| > threshold | data)
      hyperparameters       dict          — fixed hyperparameters used
      contract_version      str
    """
    labels = list(timepoint_labels)
    n = len(labels)
    if time_transform == "log1p_minutes":
        t = _timepoints_to_log1p_minutes(labels)
    else:
        t = _timepoints_to_minutes(labels)
    y = np.array([v if v is not None else np.nan for v in fc_values], dtype=float)

    obs_var = float(np.nanvar(y)) if np.sum(~np.isnan(y)) > 1 else 1.0
    sv = signal_var if signal_var is not None else max(obs_var, 0.01)
    nv = sv * noise_var_fraction

    mu, var = _gp_posterior(t, y, t, length_scale_min, sv, nv)
    std = np.sqrt(var)

    p_pos = [_p_above_threshold(float(mu[i]), float(std[i]), activity_threshold_fc) for i in range(n)]
    p_neg = [_p_below_neg_threshold(float(mu[i]), float(std[i]), activity_threshold_fc) for i in range(n)]
    p_act = [p_pos[i] + p_neg[i] for i in range(n)]
    p_ina = [max(0.0, 1.0 - p_act[i]) for i in range(n)]

    return {
        "posterior_mean": [round(float(v), 6) for v in mu],
        "posterior_std": [round(float(v), 6) for v in std],
        "p_positive_active": [round(v, 6) for v in p_pos],
        "p_negative_active": [round(v, 6) for v in p_neg],
        "p_active": [round(v, 6) for v in p_act],
        "p_inactive": [round(v, 6) for v in p_ina],
        "hyperparameters": {
            "length_scale_min": length_scale_min,
            "time_transform": time_transform,
            "signal_var": round(sv, 6),
            "noise_var": round(nv, 6),
            "noise_var_fraction": noise_var_fraction,
            "activity_threshold_fc": activity_threshold_fc,
        },
        "contract_version": CONTRACT_VERSION,
    }


def p_same_derivative_direction(
    posterior_a: dict[str, Any],
    posterior_b: dict[str, Any],
    window_index: int,
) -> float:
    """P(dFC_a/dt and dFC_b/dt have the same sign) for a given window.

    Implementation target: Roadmap §3 P(same derivative direction).
    Pre-registration: 2026-08-28.
    Interpretation limits: derivative estimated from mean posterior difference
      between consecutive timepoints; not a causal claim.
    Claim boundary: do not equate same-direction derivative with kinase sharing.

    Uses a Monte Carlo integral over posterior samples for robustness.
    """
    i = window_index
    if i >= len(posterior_a["posterior_mean"]) - 1:
        return float("nan")

    # Posterior of delta_FC for each site: N(mu_b - mu_a, var_a + var_b)
    # (approximation: treat consecutive timepoints as independent normals)
    dmu_a = posterior_a["posterior_mean"][i + 1] - posterior_a["posterior_mean"][i]
    dmu_b = posterior_b["posterior_mean"][i + 1] - posterior_b["posterior_mean"][i]
    dstd_a = math.sqrt(posterior_a["posterior_std"][i] ** 2 + posterior_a["posterior_std"][i + 1] ** 2)
    dstd_b = math.sqrt(posterior_b["posterior_std"][i] ** 2 + posterior_b["posterior_std"][i + 1] ** 2)

    # P(same sign) = P(both > 0) + P(both < 0)
    p_a_pos = _p_above_threshold(dmu_a, dstd_a, 0.0)
    p_b_pos = _p_above_threshold(dmu_b, dstd_b, 0.0)
    p_a_neg = 1.0 - p_a_pos
    p_b_neg = 1.0 - p_b_pos

    # Assume independence (conservative: correlated sites → actual p is higher)
    return round(p_a_pos * p_b_pos + p_a_neg * p_b_neg, 6)


def probabilistic_transition_annotation(
    wave_contract: Mapping[str, Any],
    *,
    length_scale_min: float = GP_LENGTH_SCALE_MIN,
    noise_var_fraction: float = GP_NOISE_VAR_FRACTION,
    activity_threshold_fc: float = ACTIVITY_THRESHOLD_FC,
    time_transform: str = "minutes",
) -> dict[str, Any]:
    """Annotate all Wave members with GP posteriors and soft co-activity scores.

    Implementation target: Roadmap §3 full probabilistic layer (v2).
    v3 roadmap (replicate-aware): requires per-replicate intensity input
      y_irt = f_i(t) + b_ir + ε_irt — not yet supported; noted for future extension.
    Pre-registration: 2026-08-28.
    Default time_transform reverted to "minutes" on 2026-08-29: log1p coordinate
      has a length-scale unit mismatch (length_scale_min=15 is in minute scale,
      log1p values are 0.69–5.20) and was not validated on raw insulin data
      (T_adjacency p=0.284327, not significant).
    Interpretation limits: see module docstring.
    Claim boundary: do not promote soft co-activity to kinase attribution.

    Returns
    -------
    dict with keys:
      site_posteriors       dict[site_key, posterior_dict]
      pair_soft_coactivity  list[dict]  — per-window P(both active) for each pair
      summary               dict        — coverage and soft transition stats
      provenance            dict
      contract_version      str
    """
    timepoints = [str(tp) for tp in (wave_contract.get("timepoints") or [])]
    if not timepoints:
        return {
            "status": "skipped_no_timepoints",
            "contract_version": CONTRACT_VERSION,
        }

    # Build membership and trajectory maps
    site_wave: dict[str, str] = {}
    trajectories: dict[str, list[float | None]] = {}
    for wave in wave_contract.get("waves") or []:
        if not isinstance(wave, Mapping):
            continue
        wave_id = str(wave.get("wave_id") or "")
        for member in wave.get("member_details") or []:
            if not isinstance(member, Mapping) or not member.get("key"):
                continue
            key = str(member["key"])
            site_wave[key] = wave_id
            tvals = dict(member.get("temporal_values") or {})
            trajectories[key] = [
                (float(tvals[tp]) if tp in tvals and tvals[tp] is not None else None)
                for tp in timepoints
            ]

    if not site_wave:
        return {"status": "skipped_no_members", "contract_version": CONTRACT_VERSION}

    # Per-site GP posteriors
    site_posteriors: dict[str, dict[str, Any]] = {}
    for key, fcs in trajectories.items():
        site_posteriors[key] = estimate_trajectory_posterior(
            timepoints,
            fcs,
            length_scale_min=length_scale_min,
            noise_var_fraction=noise_var_fraction,
            activity_threshold_fc=activity_threshold_fc,
            time_transform=time_transform,
        )

    # Per-window, per-pair soft co-activity P(both active | data)
    # Only computed for same-Wave pairs (mirrors deterministic layer scope)
    pair_soft: list[dict[str, Any]] = []
    wave_members: dict[str, list[str]] = {}
    for key, wid in site_wave.items():
        wave_members.setdefault(wid, []).append(key)

    n_windows = max(0, len(timepoints) - 1)
    window_labels = [f"{timepoints[i]}→{timepoints[i+1]}" for i in range(n_windows)]

    for wid, members in sorted(wave_members.items()):
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                post_a, post_b = site_posteriors[a], site_posteriors[b]
                for w in range(n_windows):
                    p_a = post_a["p_active"][w + 1] if (w + 1) < len(post_a["p_active"]) else 0.0
                    p_b = post_b["p_active"][w + 1] if (w + 1) < len(post_b["p_active"]) else 0.0
                    p_a_pos = post_a["p_positive_active"][w + 1] if (w + 1) < len(post_a["p_positive_active"]) else 0.0
                    p_b_pos = post_b["p_positive_active"][w + 1] if (w + 1) < len(post_b["p_positive_active"]) else 0.0
                    p_same_sign = p_a_pos * p_b_pos + (1.0 - p_a_pos) * (1.0 - p_b_pos) * p_a * p_b
                    p_coactive = p_a * p_b * (p_same_sign / max(p_a * p_b, 1e-9))
                    p_dir = p_same_derivative_direction(post_a, post_b, w)
                    pair_soft.append({
                        "wave_id": wid,
                        "site_a": a,
                        "site_b": b,
                        "window_index": w,
                        "window_label": window_labels[w] if w < len(window_labels) else "",
                        "p_both_active": round(p_a * p_b, 6),
                        "p_same_direction": p_dir,
                    })

    # Summary statistics
    n_sites = len(site_posteriors)
    mean_p_active = (
        float(np.mean([np.mean(v["p_active"]) for v in site_posteriors.values()]))
        if site_posteriors else None
    )
    uncertain_sites = sum(
        1 for v in site_posteriors.values()
        if any(0.2 < p < 0.8 for p in v["p_active"])
    )

    # Provenance fingerprint
    hyper_key = {
        "length_scale_min": length_scale_min,
        "noise_var_fraction": noise_var_fraction,
        "activity_threshold_fc": activity_threshold_fc,
        "time_transform": time_transform,
    }
    prov_sha = hashlib.sha256(
        json.dumps(hyper_key, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    return {
        "status": "computed",
        "site_posteriors": site_posteriors,
        "pair_soft_coactivity": pair_soft,
        "summary": {
            "n_sites": n_sites,
            "n_windows": n_windows,
            "mean_p_active_across_sites_and_windows": mean_p_active,
            "sites_with_uncertain_activity": uncertain_sites,
            "sites_with_uncertain_activity_fraction": (
                uncertain_sites / n_sites if n_sites else None
            ),
        },
        "provenance": {
            "hyperparameters": hyper_key,
            "hyperparameter_sha256": prov_sha,
            "membership_mutation": "forbidden",
            "tmm_mutation": "forbidden",
            "interpretation_boundary": (
                "GP posterior uncertainty on condition-level log2FC; "
                "not replicate-decomposed; not causal evidence. "
                "v3 roadmap: model from per-replicate intensity y_irt = f_i(t) + b_ir + e_irt "
                "for true replicate posterior decomposition."
            ),
            "time_transform_rationale": (
                "log1p(minutes) used: insulin intervals 1→5→15→30→60→180 min are non-uniform; "
                "log1p compression gives SE kernel balanced sensitivity. Pre-registered 2026-08-28."
            ),
            "pre_registration_date": "2026-08-28",
        },
        "contract_version": CONTRACT_VERSION,
    }
