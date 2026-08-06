"""
Temporal-aware Kinase Scoring & Signal Decomposition
=====================================================

This module implements Smart Signal Decomposition for PTM kinase assignment:

1. Kinase Subfamily Disambiguation:
   - Basophilic kinases (AKT, S6K, RSK, SGK, PKC) share overlapping motifs
   - Temporal context (which wave a PTM peaks in) disambiguates subfamily
   - Treatment context (EGF → EGFR → ERK/AKT axis) provides additional signal

2. Wave-based Kinase Assignment:
   - PTMs peaking at early timepoints → direct kinase targets (MAPK, Src)
   - PTMs peaking at intermediate timepoints → AKT/PI3K axis
   - PTMs peaking at late timepoints → mTOR/S6K/CDK
   - Anchor kinases (confirmed via iPTMnet/UniProt) define wave identity

3. Cascade-level Scoring:
   - Known signaling cascades define expected temporal order
   - Kinase assignment probability is weighted by cascade position fit
"""

import re
import logging
from typing import Optional
import numpy as np
try:
    from scipy.optimize import nnls as _scipy_nnls
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

_log = logging.getLogger("temporal_kinase_scoring")

# ═══════════════════════════════════════════════════════════════════════════════
# SIGNALING CASCADE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Canonical signaling cascades with expected temporal ordering (minutes)
# Format: cascade_name → [(kinase, expected_peak_minutes_range)]
SIGNALING_CASCADES = {
    "RAS-MAPK": [
        ("SRC", (0, 5)),
        ("RAS", (0, 5)),
        ("RAF", (1, 10)),
        ("MEK", (2, 10)),
        ("ERK1", (3, 15)),
        ("ERK2", (3, 15)),
        ("MAPK1", (3, 15)),
        ("MAPK3", (3, 15)),
        ("RSK", (5, 30)),
        ("MSK", (5, 30)),
        ("MNK", (5, 30)),
    ],
    "PI3K-AKT": [
        ("PI3K", (1, 10)),
        ("PDK1", (2, 15)),
        ("AKT1", (5, 30)),
        ("AKT2", (5, 30)),
        ("GSK3", (10, 45)),
        ("FOXO", (10, 60)),
        ("TSC2", (10, 45)),
    ],
    "mTOR-S6K": [
        ("MTOR", (10, 60)),
        ("S6K", (15, 60)),
        ("S6K1", (15, 60)),
        ("RPS6KA", (15, 60)),
        ("4EBP1", (15, 60)),
        ("EIF4E", (20, 90)),
    ],
    "AMPK-metabolic": [
        ("AMPK", (5, 30)),
        ("PRKAA1", (5, 30)),
        ("PRKAA2", (5, 30)),
        ("ACC", (10, 60)),
        ("ULK1", (15, 60)),
    ],
    "CDK-cell-cycle": [
        ("CDK1", (30, 1440)),
        ("CDK2", (30, 1440)),
        ("CDK4", (60, 1440)),
        ("CDK6", (60, 1440)),
    ],
    "CK2-constitutive": [
        ("CK2", (0, 1440)),
        ("CSNK2", (0, 1440)),
        ("CSNK2A1", (0, 1440)),
    ],
    "DNA-damage": [
        ("ATM", (5, 60)),
        ("ATR", (5, 60)),
        ("CHK1", (10, 60)),
        ("CHK2", (10, 60)),
    ],
    "JAK-STAT": [
        ("JAK1", (2, 15)),
        ("JAK2", (2, 15)),
        ("STAT3", (5, 30)),
        ("STAT5", (5, 30)),
    ],
    "p38-stress": [
        ("MKK3", (2, 15)),
        ("MKK6", (2, 15)),
        ("MAPK14", (5, 30)),
        ("p38", (5, 30)),
        ("MAPKAPK2", (10, 45)),
        ("MK2", (10, 45)),
    ],
    "JNK-stress": [
        ("MKK4", (2, 15)),
        ("MKK7", (2, 15)),
        ("JNK", (5, 30)),
        ("MAPK8", (5, 30)),
        ("MAPK9", (5, 30)),
    ],
}

# ═══════════════════════════════════════════════════════════════════════════════
# BASOPHILIC KINASE DISAMBIGUATION
# ═══════════════════════════════════════════════════════════════════════════════

# These kinases share overlapping basophilic motifs (RxRxxS/T or similar)
# Disambiguation requires temporal + cascade context
BASOPHILIC_KINASES = {
    "AKT1": {"cascade": "PI3K-AKT", "typical_peak_min": (5, 30)},
    "AKT2": {"cascade": "PI3K-AKT", "typical_peak_min": (5, 30)},
    "AKT": {"cascade": "PI3K-AKT", "typical_peak_min": (5, 30)},
    "S6K": {"cascade": "mTOR-S6K", "typical_peak_min": (15, 60)},
    "S6K1": {"cascade": "mTOR-S6K", "typical_peak_min": (15, 60)},
    "RPS6KA": {"cascade": "mTOR-S6K", "typical_peak_min": (15, 60)},
    "RSK": {"cascade": "RAS-MAPK", "typical_peak_min": (5, 30)},
    "RSK1": {"cascade": "RAS-MAPK", "typical_peak_min": (5, 30)},
    "RSK2": {"cascade": "RAS-MAPK", "typical_peak_min": (5, 30)},
    "SGK": {"cascade": "PI3K-AKT", "typical_peak_min": (15, 60)},
    "SGK1": {"cascade": "PI3K-AKT", "typical_peak_min": (15, 60)},
    "PKA": {"cascade": "cAMP-PKA", "typical_peak_min": (2, 15)},
    "PRKACA": {"cascade": "cAMP-PKA", "typical_peak_min": (2, 15)},
    "PKC": {"cascade": "DAG-PKC", "typical_peak_min": (1, 15)},
    "PRKCA": {"cascade": "DAG-PKC", "typical_peak_min": (1, 15)},
    "AMPK": {"cascade": "AMPK-metabolic", "typical_peak_min": (5, 30)},
    "PRKAA1": {"cascade": "AMPK-metabolic", "typical_peak_min": (5, 30)},
    "MTOR": {"cascade": "mTOR-S6K", "typical_peak_min": (10, 60)},
    "RPS6KB1": {"cascade": "mTOR-S6K", "typical_peak_min": (15, 60)},
    "RPS6KA1": {"cascade": "RAS-MAPK", "typical_peak_min": (5, 30)},
}

# Pro-directed kinases that also overlap
PRO_DIRECTED_KINASES = {
    "CDK1": {"cascade": "CDK-cell-cycle", "typical_peak_min": (30, 1440)},
    "CDK2": {"cascade": "CDK-cell-cycle", "typical_peak_min": (30, 1440)},
    "CDK": {"cascade": "CDK-cell-cycle", "typical_peak_min": (30, 1440)},
    "ERK1": {"cascade": "RAS-MAPK", "typical_peak_min": (3, 15)},
    "ERK2": {"cascade": "RAS-MAPK", "typical_peak_min": (3, 15)},
    "MAPK1": {"cascade": "RAS-MAPK", "typical_peak_min": (3, 15)},
    "MAPK3": {"cascade": "RAS-MAPK", "typical_peak_min": (3, 15)},
    "JNK": {"cascade": "JNK-stress", "typical_peak_min": (5, 30)},
    "MAPK8": {"cascade": "JNK-stress", "typical_peak_min": (5, 30)},
    "p38": {"cascade": "p38-stress", "typical_peak_min": (5, 30)},
    "MAPK14": {"cascade": "p38-stress", "typical_peak_min": (5, 30)},
    "DYRK1A": {"cascade": "CDK-cell-cycle", "typical_peak_min": (15, 120)},
}

# Motif family → possible specific kinases (for disambiguation)
MOTIF_FAMILY_MEMBERS = {
    "AKT/PKB": ["AKT1", "AKT2", "SGK1", "SGK"],
    "RSK": ["RSK", "RSK1", "RSK2", "S6K", "S6K1"],
    "S6K": ["S6K", "S6K1", "RSK", "RSK1"],
    "PKA": ["PKA", "PRKACA", "PRKACB"],
    "PKC": ["PKC", "PRKCA", "PRKCB", "PRKCD", "PRKCE"],
    "AMPK": ["AMPK", "PRKAA1", "PRKAA2"],
    "CDK/MAPK": ["CDK1", "CDK2", "ERK1", "ERK2", "MAPK1", "MAPK3", "JNK", "p38"],
    "CDK1/CDK2": ["CDK1", "CDK2"],
    "ERK1/ERK2": ["ERK1", "ERK2", "MAPK1", "MAPK3"],
    "CAMK2": ["CAMK2", "CAMK2A", "CAMK2B", "CAMK2D"],
    "CAMK": ["CAMK2", "CAMK1", "CAMK4", "DAPK"],
    "PIM1/PIM2": ["PIM1", "PIM2", "PIM3"],
    "mTOR": ["MTOR", "S6K", "S6K1", "RPS6KA1", "RPS6KB1"],
    "mTOR/S6K": ["MTOR", "S6K", "S6K1", "RPS6KA1", "RPS6KB1"],
    "CK2": ["CK2", "CSNK2A1", "CSNK2A2"],
    "GSK3": ["GSK3", "GSK3A", "GSK3B"],
    "ATM/ATR": ["ATM", "ATR"],
    "CHK1/CHK2": ["CHK1", "CHK2", "CHEK1", "CHEK2"],
    "Aurora_A/B": ["AURKA", "AURKB"],
    "PLK1": ["PLK1", "PLK2", "PLK3"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPORAL SCORING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def parse_time_minutes(cond: str) -> float:
    """Parse condition string like '5min', '1h', '24h' to minutes.

    Bare numbers (no unit) are treated as minutes, consistent with tp_to_minutes
    in common/temporal_utils.py (e.g., 'peak: 5' in co-wave labels → 5 min).
    """
    m = re.match(r'([\d.]+)\s*(h|hr|hour|min|m|s|sec)?', cond, re.IGNORECASE)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = (m.group(2) or 'min').lower()
    if unit.startswith('s'):
        return val / 60
    if unit.startswith('m'):
        return val
    return val * 60


def compute_temporal_fit_score(
    peak_minutes: float,
    kinase_canonical: str,
) -> float:
    """
    Compute how well a PTM's peak time fits a kinase's expected temporal window.
    
    Returns a score 0.0-1.0:
    - 1.0 = perfect fit (peak is within the kinase's typical window)
    - 0.5 = marginal fit (peak is near the edges)
    - 0.1 = poor fit (peak is far outside the window)
    """
    kinase_upper = kinase_canonical.upper()
    
    # Check basophilic kinases
    info = BASOPHILIC_KINASES.get(kinase_upper)
    if not info:
        # Check pro-directed
        info = PRO_DIRECTED_KINASES.get(kinase_upper)
    if not info:
        # Check all cascades
        for cascade_name, members in SIGNALING_CASCADES.items():
            for member_name, time_range in members:
                if member_name.upper() == kinase_upper:
                    info = {"cascade": cascade_name, "typical_peak_min": time_range}
                    break
            if info:
                break
    
    if not info:
        return 0.5  # Unknown kinase, neutral score
    
    min_t, max_t = info["typical_peak_min"]
    
    if min_t <= peak_minutes <= max_t:
        # Perfect fit
        return 1.0
    elif peak_minutes < min_t:
        # Too early
        ratio = peak_minutes / max(min_t, 0.1)
        return max(0.1, min(0.8, ratio))
    else:
        # Too late
        ratio = max_t / max(peak_minutes, 0.1)
        return max(0.1, min(0.8, ratio))


def disambiguate_basophilic_kinase(
    motif_family: str,
    peak_minutes: float,
    anchor_kinases_in_wave: list[str],
    treatment_context: str = "",
) -> list[dict]:
    """
    Given a broad motif family (e.g., "AKT/PKB"), disambiguate into specific
    kinase candidates with probability scores based on temporal context.
    
    Returns list of {kinase, score, reasoning} sorted by score descending.
    """
    candidates = MOTIF_FAMILY_MEMBERS.get(motif_family, [])
    if not candidates:
        # Try partial match
        for family_key, members in MOTIF_FAMILY_MEMBERS.items():
            if motif_family.upper() in family_key.upper() or family_key.upper() in motif_family.upper():
                candidates = members
                break
    
    if not candidates:
        return [{"kinase": motif_family, "score": 0.5, "reasoning": "no disambiguation available"}]
    
    scored = []
    for kinase in candidates:
        score = compute_temporal_fit_score(peak_minutes, kinase)
        
        # Bonus: if this kinase is already confirmed in the same wave (anchor)
        kinase_upper = kinase.upper()
        if any(kinase_upper == a.upper() or kinase_upper.startswith(a.upper()) 
               for a in anchor_kinases_in_wave):
            score = min(1.0, score + 0.3)
        
        # Treatment context bonus
        if treatment_context:
            tc_lower = treatment_context.lower()
            if kinase_upper in ("AKT1", "AKT2", "AKT"):
                if any(kw in tc_lower for kw in ("egf", "insulin", "igf", "pdgf", "ngf", "fgf")):
                    score = min(1.0, score + 0.15)
            elif kinase_upper in ("ERK1", "ERK2", "MAPK1", "MAPK3"):
                if any(kw in tc_lower for kw in ("egf", "fgf", "pdgf", "ngf", "pma")):
                    score = min(1.0, score + 0.15)
            elif kinase_upper in ("AMPK", "PRKAA1", "PRKAA2"):
                if any(kw in tc_lower for kw in ("metformin", "aicar", "glucose", "starvation", "nutrient")):
                    score = min(1.0, score + 0.2)
            elif kinase_upper in ("S6K", "S6K1", "RPS6KA"):
                if any(kw in tc_lower for kw in ("insulin", "igf", "amino acid", "leucine", "nutrient")):
                    score = min(1.0, score + 0.15)
            elif kinase_upper in ("RSK", "RSK1", "RSK2"):
                if any(kw in tc_lower for kw in ("egf", "pma", "ngf", "fgf")):
                    score = min(1.0, score + 0.15)
        
        # Build reasoning
        info = BASOPHILIC_KINASES.get(kinase_upper) or PRO_DIRECTED_KINASES.get(kinase_upper)
        if info:
            reasoning = f"cascade={info['cascade']}, typical_peak={info['typical_peak_min'][0]}-{info['typical_peak_min'][1]}min, ptm_peak={peak_minutes:.0f}min"
        else:
            reasoning = f"ptm_peak={peak_minutes:.0f}min"
        
        scored.append({
            "kinase": kinase,
            "score": round(score, 3),
            "reasoning": reasoning,
        })
    
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ═══════════════════════════════════════════════════════════════════════════════
# WAVE-BASED KINASE ASSIGNMENT
# ═══════════════════════════════════════════════════════════════════════════════

def classify_wave_tier(peak_minutes: float) -> str:
    """Classify a timepoint into a signaling tier."""
    if peak_minutes <= 5:
        return "immediate"      # Direct kinase targets (RTK, Src, MAPKKK)
    elif peak_minutes <= 15:
        return "early"          # MAPK cascade, PI3K activation
    elif peak_minutes <= 30:
        return "intermediate"   # AKT, mTOR activation
    elif peak_minutes <= 60:
        return "late"           # S6K, CDK, transcriptional
    else:
        return "very_late"      # Cell cycle, epigenetic


# Expected dominant kinases per wave tier
WAVE_TIER_KINASES = {
    "immediate": {
        "primary": ["SRC", "FAK", "RAF", "MEK", "JAK1", "JAK2"],
        "secondary": ["ERK1", "ERK2", "MAPK1", "MAPK3", "PI3K"],
    },
    "early": {
        "primary": ["ERK1", "ERK2", "MAPK1", "MAPK3", "AKT1", "AKT2", "p38", "MAPK14", "JNK"],
        "secondary": ["RSK", "MSK", "MNK", "PDK1", "PKC"],
    },
    "intermediate": {
        "primary": ["AKT1", "AKT2", "MTOR", "GSK3", "AMPK"],
        "secondary": ["S6K", "S6K1", "SGK", "SGK1", "FOXO"],
    },
    "late": {
        "primary": ["S6K", "S6K1", "MTOR", "CDK1", "CDK2", "CK2"],
        "secondary": ["DYRK1A", "HIPK2", "CLK1", "NEK2"],
    },
    "very_late": {
        "primary": ["CDK1", "CDK2", "CDK4", "CDK6", "CK2", "CSNK2A1"],
        "secondary": ["AURKA", "AURKB", "PLK1", "BUB1"],
    },
}


def get_wave_dominant_kinases(
    wave_peak_minutes: float,
    anchor_kinases: list[str],
) -> dict:
    """
    Determine the dominant kinase(s) for a wave based on:
    1. Confirmed anchor kinases in that wave
    2. Expected kinases for the wave's temporal tier
    
    Returns: {
        "tier": str,
        "dominant_kinases": [str],
        "cascade_context": str,
        "confidence": float
    }
    """
    tier = classify_wave_tier(wave_peak_minutes)
    tier_kinases = WAVE_TIER_KINASES.get(tier, {"primary": [], "secondary": []})
    
    # If we have anchor kinases, use them as dominant
    if anchor_kinases:
        # Check which cascade the anchors belong to
        cascade_hits = {}
        for ak in anchor_kinases:
            ak_upper = ak.upper()
            for cascade_name, members in SIGNALING_CASCADES.items():
                for member_name, _ in members:
                    if member_name.upper() == ak_upper or ak_upper.startswith(member_name.upper()):
                        cascade_hits[cascade_name] = cascade_hits.get(cascade_name, 0) + 1
                        break
        
        dominant_cascade = max(cascade_hits, key=cascade_hits.get) if cascade_hits else "unknown"
        
        return {
            "tier": tier,
            "dominant_kinases": anchor_kinases[:5],
            "cascade_context": dominant_cascade,
            "confidence": 0.9 if len(anchor_kinases) >= 2 else 0.7,
        }
    
    # No anchors: use tier-expected kinases
    return {
        "tier": tier,
        "dominant_kinases": tier_kinases["primary"][:3],
        "cascade_context": f"expected_for_{tier}",
        "confidence": 0.4,
    }


def score_kinase_for_ptm(
    kinase_canonical: str,
    ptm_peak_minutes: float,
    wave_info: dict,
    is_confirmed: bool = False,
) -> float:
    """
    Score a kinase assignment for a specific PTM considering:
    1. Temporal fit (does the PTM peak match the kinase's expected window?)
    2. Wave context (is this kinase dominant in the PTM's wave?)
    3. Confirmation status
    
    Returns score 0.0-1.0
    """
    if is_confirmed:
        return 1.0  # Database-confirmed, no scoring needed
    
    # Base temporal fit
    temporal_score = compute_temporal_fit_score(ptm_peak_minutes, kinase_canonical)
    
    # Wave context bonus
    wave_bonus = 0.0
    kinase_upper = kinase_canonical.upper()
    dominant = [k.upper() for k in wave_info.get("dominant_kinases", [])]
    if kinase_upper in dominant:
        wave_bonus = 0.2
    elif any(kinase_upper.startswith(d) or d.startswith(kinase_upper) for d in dominant):
        wave_bonus = 0.1
    
    # Cascade coherence bonus
    cascade_bonus = 0.0
    wave_cascade = wave_info.get("cascade_context", "")
    if wave_cascade and wave_cascade != "unknown":
        info = BASOPHILIC_KINASES.get(kinase_upper) or PRO_DIRECTED_KINASES.get(kinase_upper)
        if info and info.get("cascade") == wave_cascade:
            cascade_bonus = 0.15
    
    final_score = min(1.0, temporal_score + wave_bonus + cascade_bonus)
    return round(final_score, 3)


# ═══════════════════════════════════════════════════════════════════════════════
# SMART KINASE REDISTRIBUTION
# ═══════════════════════════════════════════════════════════════════════════════

def redistribute_kinase_assignments(
    kinase_modules: list[dict],
    cowave_modules: list[dict],
    treatment_context: str = "",
) -> list[dict]:
    """
    Redistribute PTMs from over-concentrated kinase modules using temporal context.
    
    This is the main entry point for Smart Signal Decomposition.
    
    Algorithm:
    1. Identify over-concentrated modules (>30% of total PTMs in one kinase)
    2. For each PTM in over-concentrated modules:
       a. Find its co-wave peak time
       b. Score the current kinase assignment vs alternatives
       c. If a better kinase exists with higher temporal fit, reassign
    3. Create new kinase sub-modules where appropriate
    
    Args:
        kinase_modules: Current kinase module list from global-kinase-modules
        cowave_modules: Co-wave modules with peak timepoint info
        treatment_context: Treatment/stimulus description
    
    Returns:
        Updated kinase_modules list with redistributed assignments
    """
    if not kinase_modules or not cowave_modules:
        return kinase_modules
    
    total_ptms = sum(km["total_count"] for km in kinase_modules)
    if total_ptms == 0:
        return kinase_modules
    
    # Build PTM → wave peak time map
    ptm_peak_map = {}  # ptm_key → peak_minutes
    ptm_wave_map = {}  # ptm_key → wave_info
    wave_anchor_kinases = {}  # cowave_id → [confirmed kinases]
    
    for cw in cowave_modules:
        cw_id = cw.get("id", 0)
        cw_label = cw.get("label", "")
        peak_match = re.search(r'peak:\s*([\w.]+)', cw_label)
        peak_cond = peak_match.group(1) if peak_match else ""
        if not peak_cond:
            continue
        peak_min = parse_time_minutes(peak_cond)
        
        ptm_keys = cw.get("ptm_keys", []) or cw.get("ptms", [])
        for pk in ptm_keys:
            ptm_peak_map[pk] = peak_min
        
        wave_anchor_kinases[cw_id] = []
    
    # Find anchor kinases per wave (confirmed kinases in each wave)
    for km in kinase_modules:
        # Members with membership == "confirmed" are the anchor kinases
        confirmed_members = [
            m for m in km.get("members", [])
            if m.get("membership") == "confirmed"
        ]
        for member in confirmed_members:
            pk = member.get("key", "")
            if pk in ptm_peak_map:
                # Find which wave this PTM belongs to
                for cw in cowave_modules:
                    cw_ptms = set(cw.get("ptm_keys", []) or cw.get("ptms", []))
                    if pk in cw_ptms:
                        cw_id = cw.get("id", 0)
                        if cw_id in wave_anchor_kinases:
                            wave_anchor_kinases[cw_id].append(km["canonical"])
                        break
    
    # Build wave_info for each wave
    wave_infos = {}
    for cw in cowave_modules:
        cw_id = cw.get("id", 0)
        cw_label = cw.get("label", "")
        peak_match = re.search(r'peak:\s*([\w.]+)', cw_label)
        peak_cond = peak_match.group(1) if peak_match else ""
        if not peak_cond:
            continue
        peak_min = parse_time_minutes(peak_cond)
        anchors = list(set(wave_anchor_kinases.get(cw_id, [])))
        wave_infos[cw_id] = get_wave_dominant_kinases(peak_min, anchors)
        
        # Assign wave_info to PTMs
        ptm_keys = cw.get("ptm_keys", []) or cw.get("ptms", [])
        for pk in ptm_keys:
            ptm_wave_map[pk] = wave_infos[cw_id]
    
    # Identify over-concentrated modules
    concentration_threshold = 0.25  # 25% of total PTMs
    over_concentrated = []
    for km in kinase_modules:
        if km["total_count"] / total_ptms > concentration_threshold:
            over_concentrated.append(km["canonical"])
    
    if not over_concentrated:
        _log.info("[TEMPORAL-SCORING] No over-concentrated modules found, skipping redistribution")
        return kinase_modules
    
    _log.info(
        f"[TEMPORAL-SCORING] Over-concentrated modules: {over_concentrated} "
        f"(threshold={concentration_threshold*100:.0f}% of {total_ptms} PTMs)"
    )
    
    # Initialize redistribution containers
    new_modules = {}  # canonical → module dict
    reassigned_keys = set()
    
    # ── Strategy: Tier-based forced redistribution ──
    # For severely over-concentrated modules (>40%), force split by temporal tier
    # This ensures PTMs in different time windows get assigned to different kinases
    for km in kinase_modules:
        if km["canonical"] not in over_concentrated:
            continue
        if km["total_count"] / total_ptms < 0.35:
            continue  # Only force-split severely concentrated ones
        
        # Group inferred members by temporal tier
        tier_groups: dict = {}  # tier → [members]
        for member in km.get("members", []):
            if member.get("membership") != "inferred":
                continue
            pk = member.get("key", "")
            peak_min = ptm_peak_map.get(pk)
            if peak_min is not None:
                tier = classify_wave_tier(peak_min)
            else:
                tier = "unknown"
            if tier not in tier_groups:
                tier_groups[tier] = []
            tier_groups[tier].append(member)
        
        if len(tier_groups) <= 1:
            continue  # All in same tier, can't split
        
        _log.info(
            f"[TEMPORAL-SCORING] Force-splitting {km['canonical']} by tier: "
            + ", ".join(f"{t}={len(ms)}" for t, ms in tier_groups.items())
        )
        
        # Determine which tier the original kinase belongs to
        original_canonical = km["canonical"]
        original_info = BASOPHILIC_KINASES.get(original_canonical.upper()) or PRO_DIRECTED_KINASES.get(original_canonical.upper())
        if original_info:
            orig_min_t, orig_max_t = original_info["typical_peak_min"]
            orig_tier = classify_wave_tier((orig_min_t + orig_max_t) / 2)
        else:
            orig_tier = "early"  # Default assumption for unknown kinases
        
        # For each tier that doesn't match the original kinase's tier,
        # pick the best alternative kinase and force-assign those PTMs
        for tier, tier_members in tier_groups.items():
            if tier == orig_tier or tier == "unknown":
                continue  # Keep these with original kinase
            
            # Pick the best kinase for this tier
            tier_kinase_candidates = WAVE_TIER_KINASES.get(tier, {}).get("primary", [])
            best_tier_kinase = None
            for tk in tier_kinase_candidates:
                if tk.upper() != original_canonical.upper():
                    best_tier_kinase = tk
                    break
            
            if not best_tier_kinase:
                continue
            
            # Force-assign all PTMs in this tier to the tier's kinase
            new_canon = best_tier_kinase.upper()
            if new_canon not in new_modules:
                new_modules[new_canon] = {
                    "kinase": best_tier_kinase,
                    "canonical": new_canon,
                    "sources": set(["temporal_decomposition"]),
                    "confirmed": [],
                    "inferred": [],
                    "temporal_reasoning": f"tier-forced from {original_canonical} (tier={tier})",
                    "is_temporal_decomposition": True,
                }
            for m in tier_members:
                new_modules[new_canon]["sources"].add("temporal_decomposition")
                new_modules[new_canon]["inferred"].append({
                    **m,
                    "evidence": f"tier-forced reassignment from {original_canonical} "
                               f"(tier={tier}, target_kinase={best_tier_kinase})",
                    "temporal_score": 0.8,
                    "original_kinase": original_canonical,
                })
                reassigned_keys.add(m.get("key", ""))
            
            _log.info(
                f"[TEMPORAL-SCORING] Tier-forced {len(tier_members)} PTMs "
                f"from {original_canonical} to {best_tier_kinase} (tier={tier})"
            )
    
    # Redistribute inferred PTMs from over-concentrated modules (score-based)
    # Note: new_modules and reassigned_keys may already have tier-forced entries from above
    
    for km in kinase_modules:
        if km["canonical"] not in over_concentrated:
            continue
        
        original_canonical = km["canonical"]
        inferred_members = [m for m in km["members"] if m.get("membership") == "inferred"]
        
        # Calculate over-concentration penalty:
        # The more PTMs concentrated, the more aggressively we redistribute
        concentration_ratio = km["total_count"] / total_ptms
        # penalty: 0.0 at threshold, up to 0.4 at 70%+ concentration
        overconcentration_penalty = min(0.4, (concentration_ratio - concentration_threshold) * 1.5)
        
        for member in inferred_members:
            pk = member.get("key", "")
            
            # Skip if already reassigned by tier-forced redistribution
            if pk in reassigned_keys:
                continue
            
            peak_min = ptm_peak_map.get(pk)
            wave_info = ptm_wave_map.get(pk, {})
            
            if peak_min is None:
                continue  # No temporal info, keep current assignment
            
            # Score current kinase WITH penalty for over-concentration
            raw_score = score_kinase_for_ptm(
                original_canonical, peak_min, wave_info, is_confirmed=False
            )
            current_score = max(0.1, raw_score - overconcentration_penalty)
            
            # Get motif family for this PTM
            evidence = member.get("evidence", "")
            motif_families = []
            if "motif match" in evidence.lower() or "motif" in evidence.lower():
                # Extract families from evidence string like "motif match (AKT/PKB, RSK)"
                fam_match = re.search(r'\(([^)]+)\)', evidence)
                if fam_match:
                    motif_families = [f.strip() for f in fam_match.group(1).split(",")]
            
            # If no motif families found, use the original kinase canonical to find its family
            if not motif_families:
                for family_key, members in MOTIF_FAMILY_MEMBERS.items():
                    if original_canonical.upper() in [m.upper() for m in members]:
                        motif_families.append(family_key)
                        break
                # Also try matching by canonical name prefix
                if not motif_families:
                    for family_key in MOTIF_FAMILY_MEMBERS:
                        if (original_canonical.upper() in family_key.upper() or
                            family_key.upper().split('/')[0] in original_canonical.upper()):
                            motif_families.append(family_key)
                            break
            
            # Try disambiguation
            best_alternative = None
            best_alt_score = current_score
            
            for mf in motif_families:
                candidates = disambiguate_basophilic_kinase(
                    mf, peak_min,
                    anchor_kinases_in_wave=wave_info.get("dominant_kinases", []),
                    treatment_context=treatment_context,
                )
                for cand in candidates:
                    if cand["kinase"].upper() == original_canonical.upper():
                        continue  # Skip current kinase
                    if cand["score"] > best_alt_score + 0.1:  # Lowered threshold for better redistribution
                        best_alternative = cand
                        best_alt_score = cand["score"]
                        break
            
            # Also check wave-tier expected kinases (more aggressive)
            if not best_alternative and wave_info:
                tier = wave_info.get("tier", "")
                tier_kinases = WAVE_TIER_KINASES.get(tier, {})
                for primary_k in tier_kinases.get("primary", []):
                    if primary_k.upper() == original_canonical.upper():
                        continue
                    alt_score = score_kinase_for_ptm(primary_k, peak_min, wave_info)
                    if alt_score > best_alt_score + 0.15:
                        best_alternative = {
                            "kinase": primary_k,
                            "score": alt_score,
                            "reasoning": f"wave_tier={tier}, expected_kinase",
                        }
                        best_alt_score = alt_score
                        break
            
            if best_alternative:
                new_canon = best_alternative["kinase"].upper()
                if new_canon not in new_modules:
                    new_modules[new_canon] = {
                        "kinase": best_alternative["kinase"],
                        "canonical": new_canon,
                        "sources": set(),
                        "confirmed": [],
                        "inferred": [],
                        "temporal_reasoning": best_alternative.get("reasoning", ""),
                        "is_temporal_decomposition": True,
                    }
                new_modules[new_canon]["sources"].add("temporal_decomposition")
                new_modules[new_canon]["inferred"].append({
                    **member,
                    "evidence": f"temporal reassignment from {original_canonical} "
                               f"(score: {current_score:.2f}→{best_alt_score:.2f}, "
                               f"{best_alternative.get('reasoning', '')})",
                    "temporal_score": best_alt_score,
                    "original_kinase": original_canonical,
                })
                reassigned_keys.add(pk)
    
    if not reassigned_keys:
        _log.info("[TEMPORAL-SCORING] No PTMs reassigned after temporal scoring")
        return kinase_modules
    
    _log.info(f"[TEMPORAL-SCORING] Reassigned {len(reassigned_keys)} PTMs to {len(new_modules)} new/existing modules")
    
    # Remove reassigned PTMs from original modules
    updated_modules = []
    for km in kinase_modules:
        if km["canonical"] in over_concentrated:
            remaining_members = [m for m in km["members"] if m.get("key") not in reassigned_keys]
            if remaining_members:
                km_copy = dict(km)
                km_copy["members"] = remaining_members
                km_copy["confirmed_count"] = sum(1 for m in remaining_members if m.get("membership") == "confirmed")
                km_copy["inferred_count"] = sum(1 for m in remaining_members if m.get("membership") == "inferred")
                km_copy["total_count"] = len(remaining_members)
                updated_modules.append(km_copy)
        else:
            updated_modules.append(km)
    
    # Add new modules (merge with existing if same canonical)
    for new_canon, new_mod in new_modules.items():
        # Check if this kinase already exists in updated_modules
        existing = next((km for km in updated_modules if km["canonical"] == new_canon), None)
        if existing:
            # Merge into existing
            existing_keys = set(m["key"] for m in existing["members"])
            for m in new_mod["inferred"]:
                if m["key"] not in existing_keys:
                    existing["members"].append(m)
                    existing["inferred_count"] = existing.get("inferred_count", 0) + 1
                    existing["total_count"] = existing.get("total_count", 0) + 1
            if "temporal_decomposition" not in existing.get("sources", []):
                if isinstance(existing.get("sources"), list):
                    existing["sources"].append("temporal_decomposition")
                elif isinstance(existing.get("sources"), set):
                    existing["sources"].add("temporal_decomposition")
        else:
            # Create new module entry
            all_members = new_mod["confirmed"] + new_mod["inferred"]
            updated_modules.append({
                "kinase": new_mod["kinase"],
                "canonical": new_canon,
                "sources": sorted(new_mod["sources"]),
                "source_count": len(new_mod["sources"]),
                "members": all_members,
                "confirmed_count": len(new_mod["confirmed"]),
                "inferred_count": len(new_mod["inferred"]),
                "total_count": len(all_members),
                "cowave_overlap": [],
                "is_temporal_decomposition": True,
                "temporal_reasoning": new_mod.get("temporal_reasoning", ""),
            })
    
    # Re-sort by total_count
    updated_modules.sort(key=lambda x: x["total_count"], reverse=True)
    
    return updated_modules


# ═══════════════════════════════════════════════════════════════════════════════
# WAVE-AWARE RECEPTOR INFERENCE SUPPORT
# ═══════════════════════════════════════════════════════════════════════════════

def build_wave_kinase_profile(
    kinase_modules: list[dict],
    cowave_modules: list[dict],
) -> list[dict]:
    """
    Build a wave-by-wave kinase activity profile for receptor inference.
    
    Instead of sending all kinases as a flat list to Reactome,
    this structures kinases by temporal wave, allowing the receptor
    inference to map different receptors to different cascade stages.
    
    Returns list of wave profiles:
    [{
        "wave_id": int,
        "wave_label": str,
        "peak_minutes": float,
        "tier": str,
        "kinases": [{"canonical": str, "ptm_count": int, "is_anchor": bool}],
        "cascade_context": str,
        "suggested_receptors": [str],  # from _RECEPTOR_DOWNSTREAM_KINASES reverse lookup
    }]
    """
    from app.services.ligand_receptor_db import _RECEPTOR_DOWNSTREAM_KINASES
    
    # Build reverse map: kinase → possible receptors
    kinase_to_receptors = {}
    for receptor, kinases in _RECEPTOR_DOWNSTREAM_KINASES.items():
        for k in kinases:
            k_upper = k.upper()
            if k_upper not in kinase_to_receptors:
                kinase_to_receptors[k_upper] = set()
            kinase_to_receptors[k_upper].add(receptor)
    
    wave_profiles = []
    
    for cw in cowave_modules:
        cw_id = cw.get("id", 0)
        cw_label = cw.get("label", "")
        peak_match = re.search(r'peak:\s*([\w.]+)', cw_label)
        peak_cond = peak_match.group(1) if peak_match else ""
        if not peak_cond:
            continue
        peak_min = parse_time_minutes(peak_cond)
        tier = classify_wave_tier(peak_min)
        
        cw_ptm_keys = set(cw.get("ptm_keys", []) or cw.get("ptms", []))
        
        # Find kinases active in this wave
        wave_kinases = []
        for km in kinase_modules:
            km_ptm_keys = set(m["key"] for m in km.get("members", []))
            shared = cw_ptm_keys & km_ptm_keys
            if shared:
                is_anchor = any(
                    m["key"] in shared and m.get("membership") == "confirmed"
                    for m in km.get("members", [])
                )
                wave_kinases.append({
                    "canonical": km["canonical"],
                    "kinase": km.get("kinase", km["canonical"]),
                    "ptm_count": len(shared),
                    "is_anchor": is_anchor,
                })
        
        wave_kinases.sort(key=lambda x: (-int(x["is_anchor"]), -x["ptm_count"]))
        
        # Suggest receptors based on wave kinases
        suggested_receptors = set()
        for wk in wave_kinases[:5]:  # Top 5 kinases per wave
            canon = wk["canonical"].upper()
            recs = kinase_to_receptors.get(canon, set())
            suggested_receptors.update(recs)
            # Also try without trailing digits
            base = re.sub(r'\d+$', '', canon)
            if base != canon:
                recs2 = kinase_to_receptors.get(base, set())
                suggested_receptors.update(recs2)
        
        # Determine cascade context from anchor kinases
        cascade_context = "unknown"
        anchor_kinases = [wk["canonical"] for wk in wave_kinases if wk["is_anchor"]]
        if anchor_kinases:
            cascade_hits = {}
            for ak in anchor_kinases:
                ak_upper = ak.upper()
                for cascade_name, members in SIGNALING_CASCADES.items():
                    for member_name, _ in members:
                        if member_name.upper() == ak_upper or ak_upper.startswith(member_name.upper()):
                            cascade_hits[cascade_name] = cascade_hits.get(cascade_name, 0) + 1
                            break
            if cascade_hits:
                cascade_context = max(cascade_hits, key=cascade_hits.get)
        
        wave_profiles.append({
            "wave_id": cw_id,
            "wave_label": cw_label,
            "peak_minutes": peak_min,
            "tier": tier,
            "kinases": wave_kinases[:10],
            "cascade_context": cascade_context,
            "suggested_receptors": sorted(suggested_receptors)[:15],
        })
    
    return wave_profiles


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPORAL MIXTURE MODELING — Option B (Data-driven Kinase Deconvolution)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Algorithm:
#   1. For each kinase, collect its "exclusive" substrates (PTMs assigned to
#      that kinase only) and compute their mean time-series → kinase profile k(t)
#   2. For each "shared" PTM (assigned to 2+ kinases), solve:
#         y(t) = Σ aᵢ · kᵢ(t) + ε    subject to aᵢ ≥ 0
#      using Non-Negative Least Squares (NNLS).
#   3. Normalize contributions: rᵢ = aᵢ / Σaᵢ  (contribution ratio 0–1)
#   4. Weight kinase activity scores by contribution ratios instead of
#      counting shared substrates equally.
#
# Fallback: if a kinase has fewer than MIN_EXCLUSIVE_FOR_PROFILE exclusive
# substrates, fall back to a Gaussian profile centred at typical_peak_min.
# ═══════════════════════════════════════════════════════════════════════════════

MIN_EXCLUSIVE_FOR_PROFILE = 3   # minimum exclusive substrates to build a data-driven profile
_GAUSSIAN_SIGMA_LOG = 0.6       # log-space sigma for Gaussian fallback profile


def _gaussian_kinase_profile(
    conditions_sorted: list[str],
    peak_min: float,
    sigma: float = _GAUSSIAN_SIGMA_LOG,
) -> np.ndarray:
    """Gaussian (log-normal) fallback profile for a kinase.

    Returns a 1-D numpy array of length len(conditions_sorted) with values in [0, 1].
    """
    times = np.array([parse_time_minutes(c) for c in conditions_sorted], dtype=float)
    times = np.maximum(times, 0.1)  # avoid log(0)
    log_t = np.log(times)
    log_peak = np.log(max(peak_min, 0.1))
    profile = np.exp(-0.5 * ((log_t - log_peak) / sigma) ** 2)
    norm = profile.max()
    return profile / norm if norm > 0 else profile


def build_kinase_profiles_from_data(
    kinase_modules: list[dict],
    ptm_timeseries: dict[str, dict[str, float]],
    ptm_to_kinases: dict[str, list[str]],
    conditions_sorted: list[str],
) -> dict[str, dict]:
    """Build per-kinase temporal activity profiles from exclusive substrates.

    For each kinase module, identify substrates that are assigned to that kinase
    ONLY (exclusive substrates) and compute their mean time-series as the kinase's
    empirical activity profile.

    Falls back to a Gaussian profile centred at typical_peak_min when there are
    fewer than MIN_EXCLUSIVE_FOR_PROFILE exclusive substrates.

    Returns:
        dict[canonical_name → {
            "profile": np.ndarray,          # shape (n_conditions,), normalised to [0,1]
            "profile_type": "data_driven" | "gaussian_fallback",
            "n_exclusive": int,             # number of exclusive substrates used
            "exclusive_keys": list[str],    # PTM keys used to build profile
            "peak_condition": str,          # condition with highest profile value
        }]
    """
    n_cond = len(conditions_sorted)
    profiles: dict[str, dict] = {}

    for km in kinase_modules:
        canonical = km.get("canonical", "").upper()
        if not canonical:
            continue

        # Collect all PTM keys in this kinase module
        all_keys = [m.get("key", "") for m in km.get("members", []) if m.get("key")]

        # Exclusive: assigned to this kinase only
        exclusive_keys = [
            pk for pk in all_keys
            if len(ptm_to_kinases.get(pk, [])) <= 1
        ]

        if len(exclusive_keys) >= MIN_EXCLUSIVE_FOR_PROFILE:
            # ── Data-driven profile ──────────────────────────────────────────
            vectors = []
            for pk in exclusive_keys:
                ts = ptm_timeseries.get(pk, {})
                if not ts:
                    continue
                row = np.array([ts.get(c, 0.0) for c in conditions_sorted], dtype=float)
                # Use absolute value — we care about the temporal shape, not direction
                vectors.append(np.abs(row))

            if vectors:
                mat = np.stack(vectors, axis=0)  # shape (n_exclusive, n_cond)
                # Robust profile: median across exclusive substrates
                profile = np.median(mat, axis=0)
                norm = profile.max()
                profile = profile / norm if norm > 0 else profile
                peak_idx = int(np.argmax(profile))
                profiles[canonical] = {
                    "profile": profile,
                    "profile_type": "data_driven",
                    "n_exclusive": len(vectors),
                    "exclusive_keys": exclusive_keys[:20],  # cap for storage
                    "peak_condition": conditions_sorted[peak_idx],
                }
                _log.debug(
                    f"[TMM] {canonical}: data-driven profile from {len(vectors)} "
                    f"exclusive substrates, peak={conditions_sorted[peak_idx]}"
                )
                continue

        # ── Gaussian fallback ────────────────────────────────────────────────
        all_kinase_info = (
            BASOPHILIC_KINASES.get(canonical)
            or PRO_DIRECTED_KINASES.get(canonical)
        )
        if all_kinase_info:
            min_t, max_t = all_kinase_info["typical_peak_min"]
            peak_min = (min_t + max_t) / 2.0
        else:
            peak_min = 30.0  # generic default

        profile = _gaussian_kinase_profile(conditions_sorted, peak_min)
        peak_idx = int(np.argmax(profile))
        profiles[canonical] = {
            "profile": profile,
            "profile_type": "gaussian_fallback",
            "n_exclusive": len(exclusive_keys),
            "exclusive_keys": exclusive_keys,
            "peak_condition": conditions_sorted[peak_idx],
        }
        _log.debug(
            f"[TMM] {canonical}: Gaussian fallback profile "
            f"(peak_min={peak_min:.0f}, only {len(exclusive_keys)} exclusive substrates)"
        )

    return profiles


def deconvolve_shared_ptm(
    ptm_key: str,
    candidate_kinases: list[str],
    kinase_profiles: dict[str, dict],
    ptm_timeseries: dict[str, dict[str, float]],
    conditions_sorted: list[str],
) -> dict[str, float]:
    """Decompose a shared PTM's time-series into per-kinase contribution ratios.

    Solves:  y(t) = Σ aᵢ · kᵢ(t)   s.t. aᵢ ≥ 0   (NNLS)

    Returns:
        dict[canonical_name → contribution_ratio]   values sum to 1.0.
        Falls back to equal weights if NNLS fails or scipy is unavailable.
    """
    n_cond = len(conditions_sorted)
    ts = ptm_timeseries.get(ptm_key, {})
    if not ts:
        equal = 1.0 / max(len(candidate_kinases), 1)
        return {k: equal for k in candidate_kinases}

    y = np.array([ts.get(c, 0.0) for c in conditions_sorted], dtype=float)

    # Build design matrix A  (n_cond × n_kinases)
    valid_kinases = []
    cols = []
    for canon in candidate_kinases:
        prof_info = kinase_profiles.get(canon)
        if prof_info is None:
            # Build Gaussian fallback on the fly
            all_kinase_info = (
                BASOPHILIC_KINASES.get(canon)
                or PRO_DIRECTED_KINASES.get(canon)
            )
            if all_kinase_info:
                min_t, max_t = all_kinase_info["typical_peak_min"]
                peak_min = (min_t + max_t) / 2.0
            else:
                peak_min = 30.0
            col = _gaussian_kinase_profile(conditions_sorted, peak_min)
        else:
            col = prof_info["profile"]
        valid_kinases.append(canon)
        cols.append(col)

    if not valid_kinases:
        equal = 1.0 / max(len(candidate_kinases), 1)
        return {k: equal for k in candidate_kinases}

    A = np.column_stack(cols)  # shape (n_cond, n_kinases)

    # Solve NNLS: min ||Ax - y||  s.t. x ≥ 0
    if _HAS_SCIPY and n_cond >= 2:
        try:
            coeffs, residual = _scipy_nnls(A, y)
        except Exception as e:
            _log.warning(f"[TMM] NNLS failed for {ptm_key}: {e}. Using equal weights.")
            coeffs = np.ones(len(valid_kinases))
    else:
        # Pure-numpy fallback: non-negative least squares via projected gradient
        # Simple approach: use absolute dot product as proxy
        coeffs = np.array([max(0.0, float(np.dot(A[:, i], y))) for i in range(len(valid_kinases))])

    total = float(coeffs.sum())
    if total < 1e-9:
        # All coefficients near zero → equal distribution
        equal = 1.0 / len(valid_kinases)
        ratios = {k: equal for k in valid_kinases}
    else:
        ratios = {k: round(float(coeffs[i]) / total, 4) for i, k in enumerate(valid_kinases)}

    # Add zero for any candidate kinase that was skipped
    for k in candidate_kinases:
        if k not in ratios:
            ratios[k] = 0.0

    _log.debug(
        f"[TMM] {ptm_key} deconvolved: "
        + ", ".join(f"{k}={v:.2f}" for k, v in sorted(ratios.items(), key=lambda x: -x[1]))
    )
    return ratios


def compute_weighted_kinase_scores(
    kinase_modules: list[dict],
    ptm_timeseries: dict[str, dict[str, float]],
    ptm_to_kinases: dict[str, list[str]],
    conditions_sorted: list[str],
    fc_threshold: float = 0.3,
    q_threshold: float = 0.05,
    ptm_qvalues: dict | None = None,
) -> dict[str, dict]:
    """Compute per-kinase per-condition activity scores with TMM-weighted contributions.

    For exclusive substrates: contribution = 1.0 (unchanged from current logic).
    For shared substrates: contribution = deconvolved ratio from NNLS.

    Returns:
        dict[canonical → {
            "weighted_up_sums":   dict[condition → float],
            "weighted_down_sums": dict[condition → float],
            "weighted_up_counts": dict[condition → float],   # fractional counts
            "weighted_down_counts": dict[condition → float],
            "contribution_details": list[{ptm_key, contribution_ratio, profile_type}],
            "n_exclusive": int,
            "n_shared": int,
        }]
    """
    if ptm_qvalues is None:
        ptm_qvalues = {}

    # Step 1: Build kinase profiles from exclusive substrates
    kinase_profiles = build_kinase_profiles_from_data(
        kinase_modules, ptm_timeseries, ptm_to_kinases, conditions_sorted
    )

    results: dict[str, dict] = {}

    for km in kinase_modules:
        canonical = km.get("canonical", "").upper()
        if not canonical:
            continue

        all_keys = [m.get("key", "") for m in km.get("members", []) if m.get("key")]

        w_up_sums = {c: 0.0 for c in conditions_sorted}
        w_dn_sums = {c: 0.0 for c in conditions_sorted}
        w_up_cnts = {c: 0.0 for c in conditions_sorted}
        w_dn_cnts = {c: 0.0 for c in conditions_sorted}
        contribution_details = []
        n_exclusive = 0
        n_shared = 0

        for pk in all_keys:
            ts = ptm_timeseries.get(pk, {})
            if not ts:
                continue

            # Determine contribution ratio for this PTM
            other_kinases = [k for k in ptm_to_kinases.get(pk, []) if k != canonical]
            if not other_kinases:
                # Exclusive substrate → full contribution
                ratio = 1.0
                profile_type = "exclusive"
                n_exclusive += 1
            else:
                # Shared substrate → NNLS deconvolution
                all_candidates = [canonical] + other_kinases
                deconv = deconvolve_shared_ptm(
                    pk, all_candidates, kinase_profiles, ptm_timeseries, conditions_sorted
                )
                ratio = deconv.get(canonical, 1.0 / len(all_candidates))
                prof_info = kinase_profiles.get(canonical)
                profile_type = prof_info["profile_type"] if prof_info else "gaussian_fallback"
                n_shared += 1

            contribution_details.append({
                "ptm_key": pk,
                "contribution_ratio": round(ratio, 4),
                "profile_type": profile_type,
                "n_competing_kinases": len(other_kinases),
            })

            # Accumulate weighted sums
            for c in conditions_sorted:
                fc = ts.get(c, 0.0)
                q_val = ptm_qvalues.get(pk, {}).get(c)
                passes = (q_val is not None and q_val < q_threshold) or (abs(fc) >= fc_threshold)
                if not passes:
                    continue
                weighted_fc = fc * ratio
                if weighted_fc > 0:
                    w_up_sums[c] += weighted_fc
                    w_up_cnts[c] += ratio
                elif weighted_fc < 0:
                    w_dn_sums[c] += weighted_fc
                    w_dn_cnts[c] += ratio

        results[canonical] = {
            "weighted_up_sums": {c: round(v, 4) for c, v in w_up_sums.items()},
            "weighted_down_sums": {c: round(v, 4) for c, v in w_dn_sums.items()},
            "weighted_up_counts": {c: round(v, 3) for c, v in w_up_cnts.items()},
            "weighted_down_counts": {c: round(v, 3) for c, v in w_dn_cnts.items()},
            "contribution_details": contribution_details,
            "n_exclusive": n_exclusive,
            "n_shared": n_shared,
            "profile_type": (kinase_profiles.get(canonical) or {}).get("profile_type", "gaussian_fallback"),
            "n_profile_substrates": (kinase_profiles.get(canonical) or {}).get("n_exclusive", 0),
        }

    _log.info(
        f"[TMM] Weighted scores computed for {len(results)} kinases "
        f"({'scipy NNLS' if _HAS_SCIPY else 'numpy fallback'})"
    )
    return results
