"""
PTM Vector Analysis — 2D vector-based PTM classification and analysis.

Ported from ptm-rag-backend/src/ptmVectorAnalysis.ts (v2.0).

Features:
  - PTM vs Protein log2FC 2D vector classification (8 quadrants)
  - Time-course trajectory analysis across multiple time points
  - Multi-PTM type support (Phosphorylation, Ubiquitylation, Acetylation, etc.)
  - Statistical summary and distribution analysis
  - Automatic time-unit detection (hour, min)
"""

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification thresholds
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLD = 0.5  # log2FC threshold for significance


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PTMClassification:
    gene: str = ""
    position: str = ""
    ptm_type: str = ""
    ptm_log2fc: float = 0.0
    protein_log2fc: float = 0.0
    quadrant: str = ""
    classification: str = ""
    interpretation: str = ""
    vector_magnitude: float = 0.0
    vector_angle: float = 0.0  # degrees


@dataclass
class TimePointData:
    time_label: str = ""
    time_value: float = 0.0
    time_unit: str = "hour"
    ptm_log2fc: float = 0.0
    protein_log2fc: float = 0.0
    classification: str = ""


@dataclass
class TrajectoryAnalysis:
    gene: str = ""
    position: str = ""
    ptm_type: str = ""
    time_points: List[TimePointData] = field(default_factory=list)
    trajectory_pattern: str = ""  # "sustained", "transient", "delayed", "oscillating"
    peak_time: str = ""
    peak_magnitude: float = 0.0
    overall_trend: str = ""


@dataclass
class VectorAnalysisSummary:
    total_ptms: int = 0
    classifications: Dict[str, int] = field(default_factory=dict)
    top_activated: List[PTMClassification] = field(default_factory=list)
    top_inactivated: List[PTMClassification] = field(default_factory=list)
    compensatory: List[PTMClassification] = field(default_factory=list)
    desensitized: List[PTMClassification] = field(default_factory=list)
    trajectories: List[TrajectoryAnalysis] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Time unit detection
# ---------------------------------------------------------------------------

def detect_time_unit(time_labels: List[str]) -> str:
    """Auto-detect time unit from column labels (hour, min, sec)."""
    combined = " ".join(time_labels).lower()
    if "min" in combined:
        return "min"
    if "sec" in combined or "s" in combined:
        return "sec"
    return "hour"


def parse_time_value(label: str) -> float:
    """Extract numeric time value from label like '0.5h', '30min', 'T1'."""
    # Try direct numeric
    m = re.search(r"([\d.]+)", label)
    if m:
        return float(m.group(1))
    return 0.0


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------

def classify_ptm_vector(
    ptm_log2fc: float,
    protein_log2fc: float,
    threshold: float = DEFAULT_THRESHOLD,
    modification_type: str = "Phosphorylation",
) -> PTMClassification:
    """
    Classify a PTM based on 2D vector (PTM log2FC vs Protein log2FC).

    Returns PTMClassification with quadrant, classification name, and interpretation.
    """
    result = PTMClassification(
        ptm_log2fc=ptm_log2fc,
        protein_log2fc=protein_log2fc,
        ptm_type=modification_type,
    )

    # Vector magnitude and angle
    result.vector_magnitude = math.sqrt(ptm_log2fc ** 2 + protein_log2fc ** 2)
    result.vector_angle = math.degrees(math.atan2(ptm_log2fc, protein_log2fc)) if result.vector_magnitude > 0 else 0

    ptm_sig = abs(ptm_log2fc) >= threshold
    prot_sig = abs(protein_log2fc) >= threshold

    is_ubi = "ubiquityl" in modification_type.lower() or "ubiquitin" in modification_type.lower()

    if ptm_log2fc > 0 and protein_log2fc >= 0 and ptm_sig:
        if prot_sig:
            result.quadrant = "Q1"
            result.classification = "Coupled activation"
            if is_ubi:
                result.interpretation = "Coordinated increase in both protein and ubiquitylation — may indicate quality control or active signaling"
            else:
                result.interpretation = "Coordinated increase in both protein and PTM — pathway activation"
        else:
            result.quadrant = "Q1-edge"
            result.classification = "PTM-driven hyperactivation"
            if is_ubi:
                result.interpretation = "Strong ubiquitylation increase suggests enhanced protein degradation (K48) or activated signaling (K63)"
            else:
                result.interpretation = "Strong PTM increase indicates active signaling regulation through kinase activation"

    elif ptm_log2fc > 0 and protein_log2fc < 0 and ptm_sig:
        result.quadrant = "Q2"
        result.classification = "Compensatory PTM hyperactivation"
        if is_ubi:
            result.interpretation = "Increased ubiquitylation despite decreased protein — accelerated clearance of remaining protein pool"
        else:
            result.interpretation = "Increased PTM despite decreased protein — compensatory signaling mechanism"

    elif ptm_log2fc < 0 and protein_log2fc <= 0 and ptm_sig:
        if prot_sig:
            result.quadrant = "Q3"
            result.classification = "Coupled shutdown"
            if is_ubi:
                result.interpretation = "Coordinated decrease in both protein and ubiquitylation — reduced protein turnover"
            else:
                result.interpretation = "Coordinated decrease in both protein and PTM — pathway downregulation"
        else:
            result.quadrant = "Q3-edge"
            result.classification = "PTM-driven inactivation"
            if is_ubi:
                result.interpretation = "Strong ubiquitylation decrease suggests protein stabilization through DUB activity"
            else:
                result.interpretation = "Strong PTM decrease indicates signaling shutdown through phosphatase activity"

    elif ptm_log2fc < 0 and protein_log2fc > 0 and ptm_sig:
        result.quadrant = "Q4"
        result.classification = "Desensitization-like pattern"
        if is_ubi:
            result.interpretation = "Decreased ubiquitylation despite increased protein — protein stabilization and accumulation"
        else:
            result.interpretation = "Decreased PTM despite increased protein — feedback inhibition or desensitization"

    elif not ptm_sig and prot_sig:
        result.quadrant = "expression-driven"
        result.classification = "Expression-driven change"
        result.interpretation = "PTM changes primarily reflect protein abundance changes rather than active signaling"

    else:
        result.quadrant = "center"
        result.classification = "Baseline / low-change state"
        result.interpretation = "No significant changes in PTM or protein levels"

    return result


# ---------------------------------------------------------------------------
# Trajectory analysis
# ---------------------------------------------------------------------------

def analyze_trajectory(
    time_series: List[dict],
    gene: str,
    position: str,
    ptm_type: str = "Phosphorylation",
    threshold: float = DEFAULT_THRESHOLD,
) -> TrajectoryAnalysis:
    """
    Analyze PTM trajectory across time points.

    Args:
        time_series: List of dicts with keys: time_label, ptm_log2fc, protein_log2fc
        gene: Gene name
        position: PTM position
        ptm_type: PTM type
        threshold: Significance threshold

    Returns:
        TrajectoryAnalysis with pattern classification.
    """
    result = TrajectoryAnalysis(gene=gene, position=position, ptm_type=ptm_type)

    if not time_series:
        return result

    # Detect time unit
    labels = [tp.get("time_label", "") for tp in time_series]
    time_unit = detect_time_unit(labels)

    # Build time point data
    for tp in time_series:
        ptm_fc = float(tp.get("ptm_log2fc", 0))
        prot_fc = float(tp.get("protein_log2fc", 0))
        classification = classify_ptm_vector(ptm_fc, prot_fc, threshold, ptm_type)

        td = TimePointData(
            time_label=tp.get("time_label", ""),
            time_value=parse_time_value(tp.get("time_label", "")),
            time_unit=time_unit,
            ptm_log2fc=ptm_fc,
            protein_log2fc=prot_fc,
            classification=classification.classification,
        )
        result.time_points.append(td)

    # Determine trajectory pattern
    magnitudes = [abs(tp.ptm_log2fc) for tp in result.time_points]
    if not magnitudes:
        return result

    peak_idx = magnitudes.index(max(magnitudes))
    result.peak_time = result.time_points[peak_idx].time_label
    result.peak_magnitude = magnitudes[peak_idx]

    # Pattern classification
    sig_count = sum(1 for m in magnitudes if m >= threshold)
    total = len(magnitudes)

    if sig_count == 0:
        result.trajectory_pattern = "no_change"
        result.overall_trend = "No significant PTM changes across time points"
    elif sig_count == total:
        result.trajectory_pattern = "sustained"
        result.overall_trend = f"Sustained PTM change across all {total} time points"
    elif peak_idx == 0:
        result.trajectory_pattern = "early_response"
        result.overall_trend = "Early PTM response that diminishes over time"
    elif peak_idx == total - 1:
        result.trajectory_pattern = "delayed"
        result.overall_trend = "Delayed PTM response that builds over time"
    elif peak_idx > 0 and peak_idx < total - 1:
        result.trajectory_pattern = "transient"
        result.overall_trend = f"Transient PTM response peaking at {result.peak_time}"
    else:
        result.trajectory_pattern = "complex"
        result.overall_trend = "Complex PTM response pattern"

    return result


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------

def analyze_ptm_vectors(
    ptm_data: List[dict],
    threshold: float = DEFAULT_THRESHOLD,
    top_n: int = 20,
) -> VectorAnalysisSummary:
    """
    Batch classify PTM vectors and produce summary statistics.

    Args:
        ptm_data: List of PTM dicts with gene, position, ptm_type,
                  ptm_relative_log2fc, protein_log2fc
        threshold: Significance threshold
        top_n: Number of top PTMs to include per category

    Returns:
        VectorAnalysisSummary with classification counts and top PTMs.
    """
    summary = VectorAnalysisSummary(total_ptms=len(ptm_data))
    all_classified: List[PTMClassification] = []

    for ptm in ptm_data:
        gene = ptm.get("gene") or ptm.get("Gene.Name", "")
        position = ptm.get("position") or ptm.get("PTM_Position", "")
        ptm_type = ptm.get("ptm_type") or ptm.get("PTM_Type", "Phosphorylation")
        ptm_fc = float(ptm.get("ptm_relative_log2fc") or ptm.get("PTM_Relative_Log2FC", 0))
        prot_fc = float(ptm.get("protein_log2fc") or ptm.get("Protein_Log2FC", 0))

        c = classify_ptm_vector(ptm_fc, prot_fc, threshold, ptm_type)
        c.gene = gene
        c.position = position
        all_classified.append(c)

        summary.classifications[c.classification] = summary.classifications.get(c.classification, 0) + 1

    # Sort by vector magnitude
    all_classified.sort(key=lambda x: x.vector_magnitude, reverse=True)

    # Top activated (Q1, Q1-edge)
    summary.top_activated = [
        c for c in all_classified
        if c.classification in ("Coupled activation", "PTM-driven hyperactivation")
    ][:top_n]

    # Top inactivated (Q3, Q3-edge)
    summary.top_inactivated = [
        c for c in all_classified
        if c.classification in ("Coupled shutdown", "PTM-driven inactivation")
    ][:top_n]

    # Compensatory (Q2)
    summary.compensatory = [
        c for c in all_classified
        if c.classification == "Compensatory PTM hyperactivation"
    ][:top_n]

    # Desensitized (Q4)
    summary.desensitized = [
        c for c in all_classified
        if c.classification == "Desensitization-like pattern"
    ][:top_n]

    return summary
