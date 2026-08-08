"""
Data Verification Node — verifies co-scientist hypotheses against experimental data.

v1.0: 4 verification types:
  Type A: Temporal peak distribution — "21/28 ERK1/2 exclusive substrates peak at 1h"
  Type B: Co-wave functional coherence — substrates in same wave share GO/domain
  Type C: Autophosphorylation timing — self-PTM peak matches kinase module peak
  Type D: TMM contribution specificity — high-contribution shared substrates have kinase-specific motifs

Each verified finding includes:
  - hypothesis_id: linked hypothesis
  - verification_type: A/B/C/D
  - result: "supported" | "partially_supported" | "refuted" | "insufficient_data"
  - evidence: dict with raw numbers
  - statement: human-readable summary (e.g., "21/28 (75%) ERK1/2 exclusive substrates peak at 1h")
  - confidence: float 0-1
"""

import collections
import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_data_verification(state: dict) -> dict:
    """Verify co-scientist hypotheses against experimental data."""
    if state.get("report_type") != "co_scientist":
        logger.info("[DataVerification] Skipped (not co_scientist mode)")
        return {"verified_findings": []}

    cb = state.get("progress_callback")
    if cb:
        cb(45, "[Co-Scientist] Verifying hypotheses against experimental data")

    hypotheses: List[dict] = state.get("hypotheses", [])
    vector_plot_raw_data: List[dict] = state.get("vector_plot_raw_data", [])
    kinase_activity_heatmap: dict = state.get("kinase_activity_heatmap") or {}
    co_scientist_context: dict = state.get("co_scientist_context") or {}

    kinase_scores: List[dict] = kinase_activity_heatmap.get("kinase_scores", [])
    conditions: List[str] = kinase_activity_heatmap.get("conditions", [])

    # Build lookup: gene_position → peak_condition, fc values
    ptm_lookup = _build_ptm_lookup(vector_plot_raw_data)

    verified_findings: List[dict] = []

    for hyp in hypotheses:
        hyp_id = hyp.get("id", "")
        hyp_type = hyp.get("type", "")
        findings_for_hyp = []

        # ── Type A: Temporal peak distribution ──────────────────────────────
        if hyp_type in ("temporal", "tmm_contribution", "integrated"):
            findings_for_hyp.extend(
                _verify_type_a_temporal_peak(hyp, kinase_scores, ptm_lookup, conditions)
            )

        # ── Type B: Co-wave functional coherence ─────────────────────────────
        if hyp_type in ("cowave", "integrated"):
            findings_for_hyp.extend(
                _verify_type_b_cowave_coherence(hyp, kinase_scores, ptm_lookup, co_scientist_context)
            )

        # ── Type C: Autophosphorylation timing ───────────────────────────────
        if hyp_type in ("autophospho", "integrated"):
            findings_for_hyp.extend(
                _verify_type_c_autophospho_timing(hyp, kinase_scores, ptm_lookup)
            )

        # ── Type D: TMM contribution specificity ─────────────────────────────
        if hyp_type in ("tmm_contribution", "integrated"):
            findings_for_hyp.extend(
                _verify_type_d_tmm_specificity(hyp, kinase_scores, ptm_lookup)
            )

        verified_findings.extend(findings_for_hyp)

    # Also run global verifications (not tied to specific hypotheses)
    verified_findings.extend(
        _run_global_verifications(kinase_scores, ptm_lookup, conditions, co_scientist_context)
    )

    # Deduplicate and sort by confidence
    verified_findings = _deduplicate_findings(verified_findings)
    verified_findings.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    logger.info(f"[DataVerification] Produced {len(verified_findings)} verified findings")
    if cb:
        cb(50, f"[Co-Scientist] Data verification complete: {len(verified_findings)} findings")

    return {"verified_findings": verified_findings}


# ---------------------------------------------------------------------------
# Helper: PTM lookup table
# ---------------------------------------------------------------------------

def _build_ptm_lookup(vector_plot_raw_data: List[dict]) -> Dict[str, dict]:
    """Build gene_position → {peak_condition, fc_by_condition, all_conditions} lookup."""
    lookup: Dict[str, list] = collections.defaultdict(list)
    for row in vector_plot_raw_data:
        gene = row.get("gene", "")
        pos = row.get("position", "")
        if not gene:
            continue
        key = f"{gene}_{pos}" if pos else gene
        lookup[key].append(row)

    result: Dict[str, dict] = {}
    for key, rows in lookup.items():
        fc_by_cond: Dict[str, float] = {}
        for r in rows:
            cond = r.get("condition", "")
            fc = float(r.get("ptm_relative_log2fc", 0) or 0)
            if cond:
                fc_by_cond[cond] = fc

        if fc_by_cond:
            peak_cond = max(fc_by_cond, key=lambda c: abs(fc_by_cond[c]))
            result[key] = {
                "peak_condition": peak_cond,
                "peak_fc": fc_by_cond[peak_cond],
                "fc_by_condition": fc_by_cond,
                "all_conditions": list(fc_by_cond.keys()),
            }
    return result


# ---------------------------------------------------------------------------
# Type A: Temporal peak distribution
# ---------------------------------------------------------------------------

def _verify_type_a_temporal_peak(
    hyp: dict,
    kinase_scores: List[dict],
    ptm_lookup: Dict[str, dict],
    conditions: List[str],
) -> List[dict]:
    """Verify that a kinase's exclusive substrates peak at the expected timepoint."""
    findings = []

    for ks in kinase_scores:
        if ks.get("is_sub_pattern"):
            continue
        kinase = ks.get("kinase", "")
        expected_peak = ks.get("peak_condition", "")
        substrates = ks.get("substrates", [])
        n_exclusive = ks.get("tmm_n_exclusive", 0)

        if not kinase or not expected_peak or not substrates:
            continue

        # Collect exclusive substrates
        exclusive_subs = [s for s in substrates if s.get("is_exclusive", True)]
        if not exclusive_subs:
            exclusive_subs = substrates  # fallback: use all

        # Count how many peak at expected condition
        n_total = 0
        n_matching = 0
        peak_distribution: Dict[str, int] = collections.defaultdict(int)

        for sub in exclusive_subs:
            gene = sub.get("gene", "")
            pos = sub.get("position", "")
            key = f"{gene}_{pos}" if pos else gene
            info = ptm_lookup.get(key)
            if not info:
                continue
            n_total += 1
            actual_peak = info["peak_condition"]
            peak_distribution[actual_peak] += 1
            if actual_peak == expected_peak:
                n_matching += 1

        if n_total < 3:
            continue

        ratio = n_matching / n_total
        # Binomial test approximation: p-value under H0 (random peak = 1/n_conditions)
        n_conds = max(len(conditions), 2)
        p_random = 1.0 / n_conds
        p_value = _binomial_p_value(n_matching, n_total, p_random)

        result_label = (
            "supported" if ratio >= 0.6 and p_value < 0.05
            else "partially_supported" if ratio >= 0.4
            else "refuted"
        )

        dist_str = ", ".join(f"{c}:{cnt}" for c, cnt in sorted(peak_distribution.items()))
        statement = (
            f"{kinase} exclusive substrates: {n_matching}/{n_total} ({ratio:.0%}) "
            f"peak at {expected_peak} (p={p_value:.3f}) — {result_label.upper()}\n"
            f"  Peak distribution: [{dist_str}]"
        )

        findings.append({
            "hypothesis_id": hyp.get("id", ""),
            "verification_type": "A",
            "kinase": kinase,
            "result": result_label,
            "evidence": {
                "n_matching": n_matching,
                "n_total": n_total,
                "ratio": round(ratio, 3),
                "expected_peak": expected_peak,
                "p_value": round(p_value, 4),
                "peak_distribution": dict(peak_distribution),
            },
            "statement": statement,
            "confidence": round(ratio * (1 - p_value), 3),
        })

    return findings


# ---------------------------------------------------------------------------
# Type B: Co-wave functional coherence
# ---------------------------------------------------------------------------

def _verify_type_b_cowave_coherence(
    hyp: dict,
    kinase_scores: List[dict],
    ptm_lookup: Dict[str, dict],
    co_scientist_context: dict,
) -> List[dict]:
    """Verify that co-wave substrates share functional coherence (peak condition consistency)."""
    findings = []
    cowave_kinases = co_scientist_context.get("cowave_kinases", {})
    cowave_substrates = co_scientist_context.get("cowave_substrates", {})

    for cw_id, kinases in cowave_kinases.items():
        if cw_id == "-1" or not kinases:
            continue
        expected_peak = kinases[0].get("peak_condition", "") if kinases else ""
        subs = cowave_substrates.get(cw_id, [])
        if len(subs) < 3:
            continue

        n_total = 0
        n_coherent = 0
        peak_dist: Dict[str, int] = collections.defaultdict(int)

        for sub in subs:
            gene = sub.get("gene", "")
            pos = sub.get("position", "")
            key = f"{gene}_{pos}" if pos else gene
            info = ptm_lookup.get(key)
            if not info:
                continue
            n_total += 1
            actual_peak = info["peak_condition"]
            peak_dist[actual_peak] += 1
            if actual_peak == expected_peak:
                n_coherent += 1

        if n_total < 3:
            continue

        coherence_ratio = n_coherent / n_total
        k_names = ", ".join(k["kinase"] for k in kinases[:3])
        dist_str = ", ".join(f"{c}:{cnt}" for c, cnt in sorted(peak_dist.items()))

        result_label = (
            "supported" if coherence_ratio >= 0.65
            else "partially_supported" if coherence_ratio >= 0.4
            else "refuted"
        )

        statement = (
            f"Co-wave G{cw_id} ({k_names}): {n_coherent}/{n_total} ({coherence_ratio:.0%}) "
            f"substrates peak at {expected_peak} — {result_label.upper()}\n"
            f"  Peak distribution: [{dist_str}]"
        )

        findings.append({
            "hypothesis_id": hyp.get("id", ""),
            "verification_type": "B",
            "cowave_group": f"G{cw_id}",
            "kinases": k_names,
            "result": result_label,
            "evidence": {
                "n_coherent": n_coherent,
                "n_total": n_total,
                "coherence_ratio": round(coherence_ratio, 3),
                "expected_peak": expected_peak,
                "peak_distribution": dict(peak_dist),
            },
            "statement": statement,
            "confidence": round(coherence_ratio * 0.9, 3),
        })

    return findings


# ---------------------------------------------------------------------------
# Type C: Autophosphorylation timing
# ---------------------------------------------------------------------------

def _verify_type_c_autophospho_timing(
    hyp: dict,
    kinase_scores: List[dict],
    ptm_lookup: Dict[str, dict],
) -> List[dict]:
    """Verify that kinase self-phosphorylation peaks at the same time as the kinase module."""
    findings = []

    for ks in kinase_scores:
        if ks.get("is_sub_pattern"):
            continue
        kinase = ks.get("kinase", "")
        module_peak = ks.get("peak_condition", "")
        self_ptm = ks.get("self_ptm")
        if not self_ptm or not module_peak:
            continue

        site = self_ptm.get("site", "")
        corr = self_ptm.get("correlation", 0)
        key = f"{kinase}_{site}"
        info = ptm_lookup.get(key)

        if not info:
            # Try without position
            info = ptm_lookup.get(kinase)

        if not info:
            continue

        actual_peak = info["peak_condition"]
        timing_match = actual_peak == module_peak
        corr_type = "activation" if corr > 0 else "inhibition"

        result_label = (
            "supported" if timing_match and abs(corr) >= 0.7
            else "partially_supported" if timing_match or abs(corr) >= 0.5
            else "refuted"
        )

        statement = (
            f"{kinase} autophosphorylation at {site} (r={corr:+.2f}, {corr_type}): "
            f"self-PTM peaks at {actual_peak}, module peaks at {module_peak} → "
            f"{'TIMING MATCH' if timing_match else 'TIMING MISMATCH'} — {result_label.upper()}"
        )

        findings.append({
            "hypothesis_id": hyp.get("id", ""),
            "verification_type": "C",
            "kinase": kinase,
            "site": site,
            "result": result_label,
            "evidence": {
                "self_ptm_peak": actual_peak,
                "module_peak": module_peak,
                "timing_match": timing_match,
                "correlation": round(corr, 3),
                "correlation_type": corr_type,
                "peak_fc": round(info["peak_fc"], 3),
            },
            "statement": statement,
            "confidence": round(abs(corr) * (0.9 if timing_match else 0.4), 3),
        })

    return findings


# ---------------------------------------------------------------------------
# Type D: TMM contribution specificity
# ---------------------------------------------------------------------------

def _verify_type_d_tmm_specificity(
    hyp: dict,
    kinase_scores: List[dict],
    ptm_lookup: Dict[str, dict],
) -> List[dict]:
    """Verify TMM contribution: high-exclusivity kinases should have substrate-specific timing."""
    findings = []

    for ks in kinase_scores:
        if ks.get("is_sub_pattern"):
            continue
        kinase = ks.get("kinase", "")
        n_excl = ks.get("tmm_n_exclusive", 0)
        n_shared = ks.get("tmm_n_shared", 0)
        total = n_excl + n_shared
        if total < 5:
            continue

        exclusivity = n_excl / total
        top_contribs = ks.get("tmm_top_contributions", [])
        module_peak = ks.get("peak_condition", "")

        # Check if top-contribution shared substrates peak at kinase's peak
        n_contrib_checked = 0
        n_contrib_matching = 0
        for contrib in top_contribs[:5]:
            gene = contrib.get("gene", "")
            pos = contrib.get("position", "")
            key = f"{gene}_{pos}" if pos else gene
            info = ptm_lookup.get(key)
            if not info:
                continue
            n_contrib_checked += 1
            if info["peak_condition"] == module_peak:
                n_contrib_matching += 1

        result_label = "insufficient_data"
        contrib_ratio = 0.0
        if n_contrib_checked >= 2:
            contrib_ratio = n_contrib_matching / n_contrib_checked
            result_label = (
                "supported" if exclusivity >= 0.6 and contrib_ratio >= 0.6
                else "partially_supported" if exclusivity >= 0.4 or contrib_ratio >= 0.4
                else "refuted"
            )

        statement = (
            f"{kinase} TMM: {n_excl}/{total} ({exclusivity:.0%}) exclusive substrates, "
            f"top-contribution shared substrates: {n_contrib_matching}/{n_contrib_checked} "
            f"peak at {module_peak} — {result_label.upper()}"
        )

        findings.append({
            "hypothesis_id": hyp.get("id", ""),
            "verification_type": "D",
            "kinase": kinase,
            "result": result_label,
            "evidence": {
                "n_exclusive": n_excl,
                "n_shared": n_shared,
                "exclusivity_ratio": round(exclusivity, 3),
                "top_contrib_matching": n_contrib_matching,
                "top_contrib_checked": n_contrib_checked,
                "contrib_peak_ratio": round(contrib_ratio, 3),
                "module_peak": module_peak,
            },
            "statement": statement,
            "confidence": round((exclusivity + contrib_ratio) / 2 * 0.85, 3),
        })

    return findings


# ---------------------------------------------------------------------------
# Global verifications (not tied to specific hypotheses)
# ---------------------------------------------------------------------------

def _run_global_verifications(
    kinase_scores: List[dict],
    ptm_lookup: Dict[str, dict],
    conditions: List[str],
    co_scientist_context: dict,
) -> List[dict]:
    """Run global verification analyses across all kinases."""
    findings = []

    # Global Type A: all kinases' temporal peak fidelity
    for ks in kinase_scores:
        if ks.get("is_sub_pattern"):
            continue
        kinase = ks.get("kinase", "")
        expected_peak = ks.get("peak_condition", "")
        substrates = ks.get("substrates", [])
        if not kinase or not expected_peak or len(substrates) < 3:
            continue

        n_total = 0
        n_match = 0
        peak_dist: Dict[str, int] = collections.defaultdict(int)

        for sub in substrates:
            gene = sub.get("gene", "")
            pos = sub.get("position", "")
            key = f"{gene}_{pos}" if pos else gene
            info = ptm_lookup.get(key)
            if not info:
                continue
            n_total += 1
            actual = info["peak_condition"]
            peak_dist[actual] += 1
            if actual == expected_peak:
                n_match += 1

        if n_total < 3:
            continue

        ratio = n_match / n_total
        n_conds = max(len(conditions), 2)
        p_val = _binomial_p_value(n_match, n_total, 1.0 / n_conds)

        if ratio >= 0.5 and p_val < 0.1:
            dist_str = ", ".join(f"{c}:{cnt}" for c, cnt in sorted(peak_dist.items()))
            findings.append({
                "hypothesis_id": "global",
                "verification_type": "A_global",
                "kinase": kinase,
                "result": "supported" if ratio >= 0.65 else "partially_supported",
                "evidence": {
                    "n_matching": n_match,
                    "n_total": n_total,
                    "ratio": round(ratio, 3),
                    "expected_peak": expected_peak,
                    "p_value": round(p_val, 4),
                    "peak_distribution": dict(peak_dist),
                },
                "statement": (
                    f"[Global] {kinase}: {n_match}/{n_total} ({ratio:.0%}) substrates "
                    f"peak at {expected_peak} (p={p_val:.3f})\n  Distribution: [{dist_str}]"
                ),
                "confidence": round(ratio * (1 - p_val), 3),
            })

    return findings


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate_findings(findings: List[dict]) -> List[dict]:
    """Remove duplicate findings (same kinase + verification_type)."""
    seen = set()
    unique = []
    for f in findings:
        key = (f.get("kinase", ""), f.get("verification_type", ""), f.get("cowave_group", ""))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# ---------------------------------------------------------------------------
# Statistical helper: binomial p-value (one-tailed, k >= observed)
# ---------------------------------------------------------------------------

def _binomial_p_value(k: int, n: int, p: float) -> float:
    """Approximate one-tailed binomial p-value P(X >= k | n, p)."""
    if n <= 0 or k <= 0:
        return 1.0
    if k > n:
        return 0.0
    # Use normal approximation for n >= 10
    if n >= 10:
        mu = n * p
        sigma = math.sqrt(n * p * (1 - p))
        if sigma == 0:
            return 0.0 if k > mu else 1.0
        z = (k - 0.5 - mu) / sigma  # continuity correction
        return _normal_sf(z)
    # Exact for small n
    total = 0.0
    for i in range(k, n + 1):
        total += _binom_pmf(i, n, p)
    return min(total, 1.0)


def _binom_pmf(k: int, n: int, p: float) -> float:
    """Binomial PMF P(X=k)."""
    log_coeff = _log_comb(n, k)
    if p <= 0:
        return 1.0 if k == 0 else 0.0
    if p >= 1:
        return 1.0 if k == n else 0.0
    return math.exp(log_coeff + k * math.log(p) + (n - k) * math.log(1 - p))


def _log_comb(n: int, k: int) -> float:
    """Log of C(n, k) using log-gamma."""
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _normal_sf(z: float) -> float:
    """Survival function of standard normal: P(Z >= z)."""
    # Abramowitz & Stegun approximation
    if z > 8:
        return 0.0
    if z < -8:
        return 1.0
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    p = pdf * poly
    return p if z >= 0 else 1.0 - p
