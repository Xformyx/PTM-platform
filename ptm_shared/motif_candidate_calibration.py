"""Truth-free sequence calibration for motif-only kinase candidates.

The calibration uses only the observed sequence windows in the current order and
generic motif regexes.  It never consumes treatment identity, benchmark anchors,
literature truth, RAG context, report text, or LLM output.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
import re
from typing import Any, Callable, Mapping, Sequence


CALIBRATION_CONTRACT = "motif_candidate_likelihood.v1"

_SOURCE_RELIABILITY = {
    "motif_analysis": 1.0,
    "inline_motif_match": 0.9,
    "residue_prediction": 0.1,
}

_KNOWN_FAMILY_LEVEL = {
    "AKT", "AMPK", "ATM/ATR", "AURORA", "CAMK", "CDK", "CDK/MAPK",
    "CHK1/CHK2", "CK1", "CK2", "CLK", "ERK1/ERK2", "GSK3", "JNK",
    "MAPK", "MTOR/S6K", "PAK1/PAK2", "P38", "PKA", "PKC", "PLK",
    "RSK", "S6K", "SGK", "SRC-FAMILY", "SRPK", "SYK/ZAP70",
}


def _clean_sequence(value: Any) -> str:
    return re.sub(r"[^A-Z]", "", str(value or "").upper())


def hierarchy_family(canonical: str) -> str:
    """Return a conservative family parent without pretending isoform resolution."""

    name = str(canonical or "").upper().strip()
    if not name:
        return ""
    parts = [part for part in re.split(r"[/|]", name) if part]
    roots = [re.sub(r"\d+[A-Z]*$", "", part).rstrip("-_ ") or part for part in parts]
    if roots and len(set(roots)) == 1:
        return roots[0]
    if len(parts) == 1:
        root = roots[0]
        return root if len(root) >= 3 else name
    return name


def candidate_resolution_level(canonical: str) -> str:
    name = str(canonical or "").upper().strip()
    family = hierarchy_family(name)
    if "/" in name or name in _KNOWN_FAMILY_LEVEL or name.endswith("-FAMILY"):
        return "family"
    if family and family != name and re.search(r"\d", name):
        return "gene_or_isoform"
    return "single_or_unresolved"


def build_empirical_pattern_background(
    annotations: Sequence[Mapping[str, Any]],
    patterns_by_canonical: Mapping[str, Sequence[str]],
) -> dict[str, dict[str, float]]:
    """Estimate each motif's match rate in the observed sequence-window background."""

    sequences = [_clean_sequence(row.get("sequence_window")) for row in annotations]
    sequences = [sequence for sequence in sequences if sequence]
    n_sequences = len(sequences)
    result: dict[str, dict[str, float]] = {}
    for canonical, patterns in patterns_by_canonical.items():
        compiled = []
        for pattern in patterns:
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                continue
        matches = 0
        if compiled:
            matches = sum(
                1 for sequence in sequences
                if any(pattern.search(sequence) for pattern in compiled)
            )
        rate = matches / n_sequences if n_sequences else 1.0
        smoothed_rate = (matches + 1.0) / (n_sequences + 2.0) if n_sequences else 1.0
        result[str(canonical).upper()] = {
            "background_sequence_count": n_sequences,
            "background_match_count": matches,
            "background_match_rate": rate,
            "smoothed_background_match_rate": smoothed_rate,
            "information_bits": max(0.0, -math.log2(max(smoothed_rate, 1e-12))),
        }
    return result


def calibrate_motif_annotations(
    annotations: Sequence[Mapping[str, Any]],
    patterns_by_canonical: Mapping[str, Sequence[str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach normalized sequence-support probabilities to every motif candidate."""

    normalized_patterns = {
        str(canonical).upper(): list(patterns)
        for canonical, patterns in patterns_by_canonical.items()
    }
    background = build_empirical_pattern_background(annotations, normalized_patterns)
    calibrated = deepcopy(list(annotations))
    candidate_count = 0
    calibrated_count = 0
    source_counts: dict[str, int] = defaultdict(int)
    family_counts: dict[str, int] = defaultdict(int)

    for annotation in calibrated:
        sequence = _clean_sequence(annotation.get("sequence_window"))
        candidates = list(annotation.get("motif_predicted_kinases") or [])
        logits: list[float] = []
        for candidate in candidates:
            canonical = str(
                candidate.get("canonical_family")
                or candidate.get("kinase_family")
                or ""
            ).upper()
            source = str(candidate.get("source") or "unknown")
            source_counts[source] += 1
            candidate_count += 1
            bg = background.get(canonical, {})
            patterns = normalized_patterns.get(canonical, [])
            sequence_match = False
            for pattern in patterns:
                try:
                    if sequence and re.search(pattern, sequence, re.IGNORECASE):
                        sequence_match = True
                        break
                except re.error:
                    continue
            information_bits = float(bg.get("information_bits") or 0.0)
            reliability = float(_SOURCE_RELIABILITY.get(source, 0.25))
            if source == "residue_prediction":
                raw_support = 0.05 * reliability
                support_class = "residue_only_low_information"
            elif sequence_match or source == "motif_analysis":
                raw_support = reliability * max(information_bits, 0.05)
                support_class = "sequence_background_calibrated"
                calibrated_count += 1
            else:
                raw_support = 0.1 * reliability
                support_class = "sequence_pattern_unconfirmed"
            # Temper likelihood ratios so a rare regex does not become a direct
            # kinase assertion.  The output is a relative candidate prior only.
            logit = min(4.0, max(-4.0, raw_support / 2.0))
            logits.append(logit)
            family = hierarchy_family(canonical)
            family_counts[family] += 1
            candidate.update({
                "candidate_likelihood_contract": CALIBRATION_CONTRACT,
                "candidate_support_class": support_class,
                "candidate_source_reliability": round(reliability, 6),
                "empirical_background_match_rate": round(float(bg.get("background_match_rate") or 0.0), 8),
                "empirical_information_bits": round(information_bits, 6),
                "sequence_pattern_confirmed": bool(sequence_match),
                "candidate_raw_support": round(raw_support, 6),
                "hierarchy_family": family,
                "candidate_resolution_level": candidate_resolution_level(canonical),
            })

        if candidates:
            max_logit = max(logits)
            exp_values = [math.exp(value - max_logit) for value in logits]
            denominator = sum(exp_values) or 1.0
            for candidate, value in zip(candidates, exp_values):
                candidate["candidate_probability"] = round(value / denominator, 8)
        annotation["motif_predicted_kinases"] = candidates

    summary = {
        "contract": CALIBRATION_CONTRACT,
        "selection_boundary": "observed sequence windows and generic motif regexes only",
        "candidate_count": candidate_count,
        "sequence_calibrated_candidate_count": calibrated_count,
        "source_counts": dict(sorted(source_counts.items())),
        "hierarchy_family_counts": dict(sorted(family_counts.items())),
        "background_sequence_count": max(
            (int(row.get("background_sequence_count") or 0) for row in background.values()),
            default=0,
        ),
        "probability_semantics": "relative motif-candidate prior; not direct kinase-substrate evidence",
    }
    return calibrated, summary
