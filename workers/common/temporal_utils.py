"""
Temporal Utilities — common time-related helper functions for PTM analysis.

Ported from ptm-chromadb-web/python_backend/ptm_nonptm_network_command.py (v80/v86/v87).
Provides timepoint parsing, condition name formatting, and gating mechanism inference.
"""

import re
from typing import Optional


def tp_to_minutes(tp_str: str) -> float:
    """Convert timepoint string to minutes for comparison.

    v87: Returns -1.0 for condition-based data (non-time patterns).

    Examples:
        '15min' -> 15.0
        '2hr'   -> 120.0
        '30sec' -> 0.5
        'AF_microgravity' -> -1.0  (condition-based)
    """
    tp_str_clean = tp_str.lower().strip()
    if "min" in tp_str_clean:
        num = re.search(r"([\d.]+)", tp_str_clean)
        return float(num.group(1)) if num else 999
    elif "hr" in tp_str_clean or "hour" in tp_str_clean:
        num = re.search(r"([\d.]+)", tp_str_clean)
        return float(num.group(1)) * 60 if num else 999
    elif "h" in tp_str_clean and re.match(r"^[\d.]+h$", tp_str_clean):
        num = re.search(r"([\d.]+)", tp_str_clean)
        return float(num.group(1)) * 60 if num else 999
    elif "sec" in tp_str_clean:
        num = re.search(r"([\d.]+)", tp_str_clean)
        return float(num.group(1)) / 60 if num else 999

    # v87: Check if this is a condition name (not a time pattern)
    if re.search(r"[a-zA-Z_]{2,}", tp_str) and not re.match(
        r"^\d+(?:\.\d+)?$", tp_str.strip()
    ):
        return -1.0

    try:
        return float(tp_str_clean)
    except ValueError:
        return -1.0


def format_condition_display_name(tp: str) -> str:
    """Convert technical condition/timepoint names to human-readable display names.

    v86: Handles both time-based and condition-based names.

    Examples:
        'AF_microgravity'   -> 'Atrial Fibrillation under Microgravity Conditions'
        'AF_ground_control' -> 'Atrial Fibrillation Ground Control'
        'hypoxia_24h'       -> 'Hypoxia 24h'
        '15min'             -> '15 min'
        'control_vs_treated' -> 'Control vs. Treated'
    """
    # If it's a simple timepoint (e.g., '15min', '30min'), format nicely
    time_match = re.match(r"^(\d+)\s*min$", tp, re.IGNORECASE)
    if time_match:
        return f"{time_match.group(1)} min"

    # Common abbreviation expansions
    abbreviations = {
        "AF": "Atrial Fibrillation",
        "AD": "Alzheimer's Disease",
        "PD": "Parkinson's Disease",
        "ALS": "Amyotrophic Lateral Sclerosis",
        "TBI": "Traumatic Brain Injury",
        "SCI": "Spinal Cord Injury",
        "HD": "Huntington's Disease",
        "MS": "Multiple Sclerosis",
        "ER": "Endoplasmic Reticulum",
        "ROS": "Reactive Oxygen Species",
        "UV": "Ultraviolet",
        "IR": "Ionizing Radiation",
    }

    # Split by underscores
    parts = tp.split("_")
    display_parts = []

    for part in parts:
        upper_part = part.upper()
        if upper_part in abbreviations:
            display_parts.append(abbreviations[upper_part])
        elif part.lower() in ("vs", "versus"):
            display_parts.append("vs.")
        elif part.lower() == "microgravity":
            display_parts.append("under Microgravity Conditions")
        elif part.lower() == "ground":
            display_parts.append("Ground")
        elif part.lower() == "control":
            display_parts.append("Control")
        elif part.lower() == "flight":
            display_parts.append("Spaceflight")
        else:
            # Capitalize first letter
            display_parts.append(part.capitalize())

    result = " ".join(display_parts)
    # Clean up double spaces
    result = re.sub(r"\s+", " ", result).strip()
    return result


def infer_gating_mechanism(
    leading_ptm: str, lagging_ptm: str, time_lag_minutes: float
) -> str:
    """Infer the biological mechanism of sequential PTM gating based on time lag."""
    if time_lag_minutes <= 5:
        return "Direct enzymatic cascade (rapid sequential modification)"
    elif time_lag_minutes <= 15:
        return "Signal-dependent priming (leading PTM creates recognition motif for lagging PTM enzyme)"
    elif time_lag_minutes <= 30:
        return "Conformational change-mediated (leading PTM alters protein structure, exposing lagging PTM site)"
    else:
        return "Transcription/translation-dependent (leading PTM triggers gene expression changes affecting lagging PTM)"
