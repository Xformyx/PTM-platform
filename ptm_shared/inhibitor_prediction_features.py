"""M1-M3 Feature extraction for inhibitor-sensitive transition prediction.

Builds frozen feature matrices from insulin-only temporal data for future
inhibitor prediction models.  No model training occurs here; features are
extracted and serialised before inhibitor outcomes are disclosed.

Model tiers mirror Dynamic Co-Wave AI Development Roadmap §4 M1–M3:
  M1 — phosphosite log2FC amplitude and timing only
  M2 — M1 + static Wave membership features
  M3 — M2 + Dynamic Co-Wave transition features (core model in Roadmap §4)

M4 (pLM integration) is defined by interface but not fitted here; see Roadmap §4
and docs/integrated_research_design_v2.md §3 pLM Attribution.

Implementation target: Dynamic Co-Wave AI Development Roadmap §4 M1–M4.
Pre-registration: 2026-08-28 동결.
  Feature definitions frozen before any inhibitor data is disclosed.
  Protein GroupKFold split boundary also declared here (GROUPKFOLD_COLUMN).
Interpretation limits:
  - Features derived from insulin-only condition-level trajectories.
  - M3 requires a Dynamic Co-Wave annotation result (dynamic_cowave_transition.v1).
  - AUPRC evaluation against inhibitor labels is a future step, not done here.
  - Feature importance should not be interpreted as kinase attribution confidence.
Claim boundary:
  - Do not claim "M3 improves kinase prediction" from feature extraction alone.
    That claim requires held-out inhibitor AUPRC > M2 baseline on the Group split.
  - Do not combine these features with inhibitor labels before the split is fixed.

Data leakage prevention (pre-registered 2026-08-28):
  - Evaluation split = GROUPKFOLD_COLUMN ("protein_id") via sklearn GroupKFold.
  - Rationale: sites from the same protein share kinase context; protein-grouped
    split prevents the model from memorising protein-level patterns as kinase
    signal.  This matches Roadmap §5 "held-out protein AUPRC".
  - GROUPKFOLD_COLUMN must not be changed after inhibitor labels are disclosed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np

CONTRACT_VERSION = "inhibitor_prediction_features.v1"

# ── Split boundary (pre-registered 2026-08-28) ─────────────────────────────
GROUPKFOLD_COLUMN: str = "protein_id"
"""Protein-grouped evaluation boundary.

docs/dynamic_cowave_ai_development_roadmap §5 선언. 2026-08-28 동결.
사용: GroupKFold(n_splits=5, groups=df[GROUPKFOLD_COLUMN]).
변경 금지: inhibitor 데이터 공개 후 변경하면 data-leakage 주장이 된다.
"""

# ── Activity threshold (must match production DYNAMIC_COWAVE_CONFIG) ────────
from ptm_shared.temporal_optimization_config import DYNAMIC_COWAVE_CONFIG  # noqa: E402

_THRESHOLD_FC: float = float(DYNAMIC_COWAVE_CONFIG["activity_threshold_fc"])
"""Shared with deterministic layer.  pre-registered 2026-08-28.

docs/ temporal_optimization_config.py DYNAMIC_COWAVE_CONFIG에서 인용.
측정 착수 전 확정.
"""


# ── Helper utilities ───────────────────────────────────────────────────────

def _timepoints_to_minutes(labels: Sequence[str]) -> np.ndarray:
    """Parse 'Xmin' labels → float minutes array.  Falls back to index spacing."""
    result = []
    for label in labels:
        s = str(label).strip().lower().replace(" ", "").replace("min", "").replace("m", "")
        try:
            result.append(float(s))
        except ValueError:
            return np.arange(len(labels), dtype=float)
    return np.array(result, dtype=float)


def _safe_auc(values: Sequence[float | None], times: np.ndarray | None = None) -> float | None:
    """Trapezoidal AUC of |FC| trajectory; None if <2 valid points."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    if times is None or len(times) != len(values):
        t = np.arange(len(vals), dtype=float)
    else:
        t = np.array([times[i] for i, v in enumerate(values) if v is not None], dtype=float)
    y = np.abs(vals)
    if len(t) < 2:
        return None
    _trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    return float(_trapz(y, t))


# ── M1: Amplitude and timing features ─────────────────────────────────────

def extract_m1_features(
    site_key: str,
    timepoint_labels: Sequence[str],
    fc_values: Sequence[float | None],
    *,
    activity_threshold_fc: float = _THRESHOLD_FC,
) -> dict[str, Any]:
    """M1 features: phosphosite FC amplitude and timing.

    Implementation target: Roadmap §4 M1 (FC-only model).
    Pre-registration: 2026-08-28.
    Interpretation limits: amplitude and timing of condition-level FC only.
    Claim boundary: M1 cannot distinguish kinase-specific from general activity.

    Features
    --------
    site_key                str    — site identifier (passed through)
    n_timepoints            int
    n_observed              int    — non-null timepoints
    peak_abs_fc             float  — max |FC| across trajectory
    peak_fc                 float  — FC at peak_abs_fc (signed)
    peak_timepoint_min      float  — time of peak (minutes)
    onset_timepoint_min     float  — first timepoint |FC| >= threshold
    exit_timepoint_min      float  — last timepoint |FC| >= threshold
    active_span_min         float  — exit - onset (0 if single point)
    trajectory_auc          float  — trapz(|FC|, t)
    recovery_fraction       float  — |fc_last| / peak_abs_fc  (0→1 or >1)
    direction               int    — +1 up-regulated, -1 down, 0 ambiguous
    fraction_active_tps     float  — fraction of timepoints above threshold
    """
    labels = list(timepoint_labels)
    n = len(labels)
    times = _timepoints_to_minutes(labels)
    vals = list(fc_values)

    valid_pairs = [(times[i], vals[i]) for i in range(n) if vals[i] is not None]
    if not valid_pairs:
        return {
            "site_key": site_key,
            "model_tier": "M1",
            **{k: None for k in [
                "n_timepoints", "n_observed", "peak_abs_fc", "peak_fc",
                "peak_timepoint_min", "onset_timepoint_min", "exit_timepoint_min",
                "active_span_min", "trajectory_auc", "recovery_fraction",
                "direction", "fraction_active_tps",
            ]},
        }

    valid_times = np.array([p[0] for p in valid_pairs])
    valid_fcs = np.array([p[1] for p in valid_pairs])
    abs_fcs = np.abs(valid_fcs)

    peak_idx = int(np.argmax(abs_fcs))
    peak_abs = float(abs_fcs[peak_idx])
    peak_signed = float(valid_fcs[peak_idx])
    peak_t = float(valid_times[peak_idx])

    active_mask = abs_fcs >= activity_threshold_fc
    active_times = valid_times[active_mask]
    onset_t = float(active_times[0]) if len(active_times) > 0 else None
    exit_t = float(active_times[-1]) if len(active_times) > 0 else None
    active_span = float(exit_t - onset_t) if (onset_t is not None and exit_t is not None) else 0.0

    last_fc_abs = float(abs_fcs[-1]) if len(abs_fcs) > 0 else None
    recovery = float(last_fc_abs / peak_abs) if (last_fc_abs is not None and peak_abs > 0) else None

    up_count = int(np.sum(valid_fcs > activity_threshold_fc))
    dn_count = int(np.sum(valid_fcs < -activity_threshold_fc))
    if up_count > dn_count:
        direction = 1
    elif dn_count > up_count:
        direction = -1
    else:
        direction = 0

    auc = _safe_auc(valid_fcs.tolist(), valid_times)
    frac_active = float(np.sum(active_mask) / len(valid_fcs))

    return {
        "site_key": site_key,
        "model_tier": "M1",
        "n_timepoints": n,
        "n_observed": len(valid_pairs),
        "peak_abs_fc": round(peak_abs, 6),
        "peak_fc": round(peak_signed, 6),
        "peak_timepoint_min": round(peak_t, 3),
        "onset_timepoint_min": round(onset_t, 3) if onset_t is not None else None,
        "exit_timepoint_min": round(exit_t, 3) if exit_t is not None else None,
        "active_span_min": round(active_span, 3),
        "trajectory_auc": round(auc, 6) if auc is not None else None,
        "recovery_fraction": round(recovery, 6) if recovery is not None else None,
        "direction": direction,
        "fraction_active_tps": round(frac_active, 6),
    }


# ── M2: M1 + static Wave membership features ──────────────────────────────

def extract_m2_features(
    m1_features: dict[str, Any],
    wave_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """M2 features: M1 + static Wave membership context.

    Implementation target: Roadmap §4 M2 (FC + static Wave).
    Pre-registration: 2026-08-28.
    Interpretation limits: static Wave membership is a correlation-based cluster
      assignment, not a mechanistic kinase assignment.
    Claim boundary: Wave co-membership alone does not imply shared kinase.

    Added features
    --------------
    static_wave_id              str | None
    wave_member_count           int | None
    within_wave_amplitude_rank  int | None   — 1 = highest peak_abs_fc in Wave
    wave_mean_peak_abs_fc       float | None
    wave_amplitude_zscore       float | None — (peak - wave_mean) / wave_std
    protein_id                  str | None   — extracted from site_key for GroupKFold
    """
    site_key = m1_features["site_key"]
    m2 = dict(m1_features)
    m2["model_tier"] = "M2"

    # Parse protein_id from site_key (format: "GENE_S123_UniMod:21" or "GENE")
    protein_id = site_key.split("_")[0] if "_" in site_key else site_key
    m2["protein_id"] = protein_id

    # Find Wave membership
    wave_id = None
    wave_members_peak: dict[str, float] = {}
    for wave in wave_contract.get("waves") or []:
        if not isinstance(wave, Mapping):
            continue
        wid = str(wave.get("wave_id") or "")
        for md in wave.get("member_details") or []:
            if not isinstance(md, Mapping):
                continue
            k = str(md.get("key") or "")
            if k == site_key:
                wave_id = wid
            # Collect peak for within-wave rank
            tv = md.get("temporal_values") or {}
            if tv:
                peak = max(abs(float(v)) for v in tv.values() if v is not None) if tv else 0.0
                wave_members_peak[k] = peak

    if wave_id is None:
        m2.update({
            "static_wave_id": None,
            "wave_member_count": None,
            "within_wave_amplitude_rank": None,
            "wave_mean_peak_abs_fc": None,
            "wave_amplitude_zscore": None,
        })
        return m2

    # Gather peaks from the same Wave
    same_wave_peaks: list[float] = []
    for wave in wave_contract.get("waves") or []:
        if not isinstance(wave, Mapping):
            continue
        if str(wave.get("wave_id") or "") != wave_id:
            continue
        for md in wave.get("member_details") or []:
            if not isinstance(md, Mapping):
                continue
            tv = md.get("temporal_values") or {}
            peak = max(abs(float(v)) for v in tv.values() if v is not None) if tv else 0.0
            same_wave_peaks.append(peak)

    n_wave = len(same_wave_peaks)
    wave_peaks_sorted = sorted(same_wave_peaks, reverse=True)
    site_peak = m1_features.get("peak_abs_fc") or 0.0
    rank = wave_peaks_sorted.index(site_peak) + 1 if site_peak in wave_peaks_sorted else None
    wave_mean = float(np.mean(same_wave_peaks)) if same_wave_peaks else None
    wave_std = float(np.std(same_wave_peaks)) if len(same_wave_peaks) > 1 else None
    zscore = None
    if wave_mean is not None and wave_std is not None and wave_std > 0:
        zscore = round((site_peak - wave_mean) / wave_std, 6)

    m2.update({
        "static_wave_id": wave_id,
        "wave_member_count": n_wave,
        "within_wave_amplitude_rank": rank,
        "wave_mean_peak_abs_fc": round(wave_mean, 6) if wave_mean is not None else None,
        "wave_amplitude_zscore": zscore,
    })
    return m2


# ── M3: M2 + Dynamic Co-Wave features ─────────────────────────────────────

def extract_m3_features(
    m2_features: dict[str, Any],
    dynamic_cowave_result: Mapping[str, Any],
) -> dict[str, Any]:
    """M3 features: M2 + Dynamic Co-Wave transition features.

    Implementation target: Roadmap §4 M3 (core model — FC + Wave + Co-Wave).
    Pre-registration: 2026-08-28.
    Interpretation limits: transition features quantify observed co-movement
      patterns; they are non-causal and not kinase-specific per se.
    Claim boundary: M3 > M2 AUPRC on protein-grouped inhibitor holdout is the
      paper's primary evidence; this feature extraction alone is not that claim.

    Added features
    --------------
    dynamic_partner_count_mean      float | None  — mean active partners across windows
    dynamic_partner_count_max       int | None    — peak number of active partners
    group_persistence_fraction      float | None  — frac windows in group_persistence
    split_fraction                  float | None  — frac windows in split_from_group
    joined_fraction                 float | None  — frac windows in joined_group
    exit_fraction                   float | None  — frac windows in exit
    independent_activation_fraction float | None
    dynamic_transition_entropy      float | None  — Shannon entropy of transition types
    loto_pair_stability             float | None  — LOTO pair Jaccard (from wave_id)
    co_wave_site_windows            int | None    — total annotated windows for site
    """
    site_key = m2_features["site_key"]
    m3 = dict(m2_features)
    m3["model_tier"] = "M3"

    # Extract per-site transition examples from dynamic_cowave_result
    examples = dynamic_cowave_result.get("transition_examples") or {}
    site_transitions = examples.get("site_transitions") or []

    site_rows = [r for r in site_transitions if r.get("site_key") == site_key]

    if not site_rows:
        m3.update({
            "dynamic_partner_count_mean": None,
            "dynamic_partner_count_max": None,
            "group_persistence_fraction": None,
            "split_fraction": None,
            "joined_fraction": None,
            "exit_fraction": None,
            "independent_activation_fraction": None,
            "dynamic_transition_entropy": None,
            "loto_pair_stability": None,
            "co_wave_site_windows": 0,
        })
        return m3

    n_rows = len(site_rows)
    type_counts: dict[str, int] = {}
    partner_counts: list[int] = []
    for row in site_rows:
        t = str(row.get("transition_type") or "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
        pc_after = row.get("partner_count_after") or 0
        partner_counts.append(int(pc_after))

    def _frac(key: str) -> float:
        return round(type_counts.get(key, 0) / n_rows, 6)

    total = sum(type_counts.values())
    entropy = 0.0
    for cnt in type_counts.values():
        p = cnt / total if total > 0 else 0.0
        if p > 0:
            entropy -= p * np.log2(p)

    # LOTO pair Jaccard for this site's Wave
    wave_id = m2_features.get("static_wave_id")
    loto_pair_jaccard = None
    loto = dynamic_cowave_result.get("lotto") or {}
    per_wave = dynamic_cowave_result.get("per_wave_summary") or {}
    if wave_id and wave_id in per_wave:
        # Use global mean LOTO as proxy (per-wave LOTO not exposed)
        loto_pair_jaccard = loto.get("mean_pair_transition_jaccard")

    m3.update({
        "dynamic_partner_count_mean": round(float(np.mean(partner_counts)), 4) if partner_counts else None,
        "dynamic_partner_count_max": int(max(partner_counts)) if partner_counts else None,
        "group_persistence_fraction": _frac("group_persistence"),
        "split_fraction": _frac("split_from_group"),
        "joined_fraction": _frac("joined_group"),
        "exit_fraction": _frac("exit"),
        "independent_activation_fraction": _frac("independent_activation"),
        "dynamic_transition_entropy": round(float(entropy), 6),
        "loto_pair_stability": round(float(loto_pair_jaccard), 6) if loto_pair_jaccard is not None else None,
        "co_wave_site_windows": n_rows,
    })
    return m3


# ── Batch feature matrix builder ──────────────────────────────────────────

def build_feature_matrix(
    wave_contract: Mapping[str, Any],
    dynamic_cowave_result: Mapping[str, Any] | None = None,
    *,
    model_tier: str = "M3",
    activity_threshold_fc: float = _THRESHOLD_FC,
) -> dict[str, Any]:
    """Build frozen M1/M2/M3 feature matrix for all Wave members.

    Implementation target: Roadmap §4 full M1–M3 matrix; §5 data-leakage prevention.
    Pre-registration: 2026-08-28.
    Interpretation limits: see module and per-function docstrings.
    Claim boundary: feature extraction does not constitute inhibitor prediction.

    Returns
    -------
    dict with keys:
      features        list[dict]    — one row per site
      model_tier      str           — M1 / M2 / M3
      n_sites         int
      feature_names   list[str]     — ordered column names (M1 first, then M2, M3)
      groupkfold_column  str        — column name for protein-grouped CV split
      provenance      dict
      contract_version str
    """
    if model_tier not in {"M1", "M2", "M3"}:
        raise ValueError(f"model_tier must be M1, M2, or M3; got {model_tier!r}")

    timepoints = [str(tp) for tp in (wave_contract.get("timepoints") or [])]
    if not timepoints:
        return {
            "features": [],
            "model_tier": model_tier,
            "n_sites": 0,
            "feature_names": [],
            "groupkfold_column": GROUPKFOLD_COLUMN,
            "provenance": {"status": "skipped_no_timepoints"},
            "contract_version": CONTRACT_VERSION,
        }

    rows: list[dict[str, Any]] = []
    for wave in wave_contract.get("waves") or []:
        if not isinstance(wave, Mapping):
            continue
        for md in wave.get("member_details") or []:
            if not isinstance(md, Mapping) or not md.get("key"):
                continue
            key = str(md["key"])
            tv = dict(md.get("temporal_values") or {})
            fcs = [
                (float(tv[tp]) if tp in tv and tv[tp] is not None else None)
                for tp in timepoints
            ]
            m1 = extract_m1_features(key, timepoints, fcs, activity_threshold_fc=activity_threshold_fc)
            if model_tier == "M1":
                rows.append(m1)
                continue
            m2 = extract_m2_features(m1, wave_contract)
            if model_tier == "M2":
                rows.append(m2)
                continue
            if dynamic_cowave_result is None:
                raise ValueError("model_tier='M3' requires dynamic_cowave_result")
            m3 = extract_m3_features(m2, dynamic_cowave_result)
            rows.append(m3)

    # Stable column order
    feature_names: list[str] = []
    if rows:
        meta_keys = {"site_key", "model_tier", "protein_id"}
        m1_keys = [k for k in rows[0] if k not in meta_keys]
        feature_names = [k for k in m1_keys if k != "model_tier"]

    # Provenance fingerprint
    hyper_key = {
        "model_tier": model_tier,
        "activity_threshold_fc": activity_threshold_fc,
        "groupkfold_column": GROUPKFOLD_COLUMN,
        "contract_version": CONTRACT_VERSION,
    }
    prov_sha = hashlib.sha256(
        json.dumps(hyper_key, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    return {
        "features": rows,
        "model_tier": model_tier,
        "n_sites": len(rows),
        "feature_names": feature_names,
        "groupkfold_column": GROUPKFOLD_COLUMN,
        "provenance": {
            "hyperparameters": hyper_key,
            "hyperparameter_sha256": prov_sha,
            "interpretation_boundary": (
                "Frozen insulin-only features. No model training here. "
                "Inhibitor labels must not be used to select or modify these features."
            ),
            "data_leakage_prevention": (
                f"Use GroupKFold(groups=df['{GROUPKFOLD_COLUMN}']) for all CV splits. "
                "Pre-registered 2026-08-28."
            ),
            "pre_registration_date": "2026-08-28",
        },
        "contract_version": CONTRACT_VERSION,
    }
