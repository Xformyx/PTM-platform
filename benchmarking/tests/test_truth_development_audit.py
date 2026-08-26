from benchmarking.truth_development_audit import build_truth_development_audit


def _row(
    *,
    measurable: bool,
    regulated: bool = False,
    direction: bool | None = None,
    peak: bool | None = None,
    branch: str = "A",
) -> dict:
    return {
        "is_measurable": measurable,
        "regulated": regulated,
        "direction_correct": direction,
        "peak_window_correct": peak,
        "branch": branch,
        "exclusion_reason": None if measurable else "not_declared_measurable",
    }


def test_small_denominator_blocks_tuning_and_holdout() -> None:
    result = {"anchor_results": [_row(measurable=True, regulated=True, direction=True, peak=True), _row(measurable=False)]}
    audit = build_truth_development_audit(result)
    assert audit["development_eligibility"]["eligible_for_parameter_selection"] is False
    assert audit["holdout_eligibility"]["eligible"] is False
    assert "minimum_measurable_anchors" in audit["development_eligibility"]["failed_requirements"]
    assert audit["counts"]["exclusion_reasons"] == {"not_declared_measurable": 1}


def test_sufficient_synthetic_denominator_allows_protocol() -> None:
    rows = []
    for index in range(10):
        rows.append(
            _row(
                measurable=True,
                regulated=index < 6,
                direction=True if index < 6 else None,
                peak=True if index < 6 else None,
                branch=f"B{index % 3}",
            )
        )
    audit = build_truth_development_audit({"anchor_results": rows})
    assert audit["development_eligibility"]["eligible_for_parameter_selection"] is True
    assert audit["holdout_eligibility"]["eligible"] is True
