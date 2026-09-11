"""Immutable quantitative estimator facts shared by preprocessing and Report.

This module describes existing arithmetic; it does not change the numerical
estimators.  LLM-authored Methods may explain rationale and limitations but must
not paraphrase these formulas into a different calculation.
"""

from __future__ import annotations

import re
from typing import Any


CONTRACT_VERSION = "ptm_quantitation_estimators.v1"
INDEPENDENT_UNADJUSTED_ESTIMATOR_ID = "independent_unadjusted_ratio_of_condition_arithmetic_means.v1"
PROTEIN_ADJUSTED_ESTIMATOR_ID = "protein_adjusted_mean_of_sample_ptm_to_protein_ratios.v1"
LINKED_PROTEIN_ESTIMATOR_ID = "linked_protein_ratio_of_condition_arithmetic_means.v1"
LEGACY_RECONSTRUCTED_ESTIMATOR_ID = "legacy_reconstructed_adjusted_plus_protein.v1"

DETERMINISTIC_METHODS_PARAGRAPH = (
    "For each modified-precursor feature and treatment condition, the independent unadjusted PTM contrast was "
    "log2(mean normalized PR intensity in treatment / mean normalized PR intensity in control). The protein-adjusted "
    "contrast was calculated by first forming each sample's normalized PTM-to-linked-protein ratio, then taking the "
    "arithmetic mean of those ratios within each condition, and finally calculating log2(mean treatment ratio / mean "
    "control ratio). The linked protein contrast remained a separate quantitative axis. The legacy reconstructed value "
    "equaled the protein-adjusted contrast plus the linked protein contrast and was retained only for compatibility; it "
    "was not an independent measurement and was not used as a substitute for the independent unadjusted contrast."
)

_ESTIMATOR_CLAIM_RE = re.compile(
    r"(?:protein[- ]adjusted (?:PTM )?contrast|adjusted (?:PTM )?(?:log2fc|contrast)|"
    r"subtract(?:ed|ing)?\s+(?:the\s+)?(?:linked\s+)?protein|unadjusted[^.]{0,100}minus[^.]{0,60}protein)",
    flags=re.IGNORECASE,
)


def build_quantitation_estimator_contract() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "estimators": {
            "independent_unadjusted": {
                "estimator_id": INDEPENDENT_UNADJUSTED_ESTIMATOR_ID,
                "input_scale": "sample_wise_median_scaled_pr_intensity",
                "aggregation_order": "condition arithmetic means, then treatment/control ratio, then log2",
                "formula": "log2(mean(PR_treatment) / mean(PR_control))",
                "pseudocount_policy": "none; control-undetected conventional contrast is NA",
            },
            "protein_adjusted": {
                "estimator_id": PROTEIN_ADJUSTED_ESTIMATOR_ID,
                "input_scale": "sample_wise_normalized_ptm_intensity_over_linked_normalized_protein_intensity",
                "aggregation_order": "sample PTM/protein ratios, then condition arithmetic means, then treatment/control ratio, then log2",
                "formula": "log2(mean((PTM/Protein)_treatment) / mean((PTM/Protein)_control))",
                "interpretation": "protein-abundance-adjusted relative PTM ratio; not absolute occupancy",
            },
            "linked_protein": {
                "estimator_id": LINKED_PROTEIN_ESTIMATOR_ID,
                "formula": "log2(mean(Protein_treatment) / mean(Protein_control))",
            },
            "legacy_reconstructed": {
                "estimator_id": LEGACY_RECONSTRUCTED_ESTIMATOR_ID,
                "formula": "protein_adjusted_log2fc + linked_protein_log2fc",
                "role": "legacy compatibility only; not an independent measurement",
            },
        },
        "non_equivalence": (
            "The protein-adjusted mean-of-sample-ratios estimator is not generally identical to subtracting the linked "
            "protein contrast from the independent unadjusted PTM contrast."
        ),
        "deterministic_methods_paragraph": DETERMINISTIC_METHODS_PARAGRAPH,
    }


def repair_quantitation_estimator_sentence(sentence: str) -> tuple[str, bool]:
    text = str(sentence or "").strip()
    if not text or not _ESTIMATOR_CLAIM_RE.search(text):
        return text, False
    if text in DETERMINISTIC_METHODS_PARAGRAPH:
        return text, False
    return DETERMINISTIC_METHODS_PARAGRAPH, True


def ensure_quantitation_methods_contract(text: str) -> str:
    """Remove conflicting estimator prose and append one immutable paragraph."""
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", text or "") if paragraph.strip()]
    retained = [paragraph for paragraph in paragraphs if not _ESTIMATOR_CLAIM_RE.search(paragraph)]
    retained.append(DETERMINISTIC_METHODS_PARAGRAPH)
    return "\n\n".join(retained)
