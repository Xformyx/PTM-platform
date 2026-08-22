"""Regression tests locking the guard wiring inside the production scoring path.

구현 대상: docs/chapter2_audit_protocol_v1.md §5 (guard), §5.5 (`group_share`)
사전등록: 정책은 §5.5 에서 2026-08-22 **구현 착수 전** 선언. 이 테스트가 고정하는 것은
          그 선언의 세 가지 검증 가능한 주장이며 새 임계를 도입하지 않는다.
해석 한계: guard 가 발표를 줄인다는 것만 확인한다. 남는 숫자가 옳다는 뜻이 아니고
          정확도가 개선된다는 뜻도 아니다.
주장 금지: 통과를 kinase 귀속 타당성의 근거로 서술하지 않는다.

왜 여기인가
-----------
`ptm_shared/tmm_attribution_guard.py` 단위 테스트는 정책 함수만 검사한다. 그러나 §5.5 가
논문에 적을 주장은 **production 출력에 대한 것**이다 — "가중합은 `strict` 와 동일하고
발표만 바뀐다". 그 주장은 `compute_weighted_kinase_scores` 를 실제로 돌려야 확인된다.
동결 fixture 는 heatmap 스냅샷이라 이 함수의 입력 형태가 아니므로 합성 입력을 쓴다.
합성 입력은 **정책 간 비교**에만 쓰이며 어떤 유병률 수치도 여기서 나오지 않는다.
"""

from __future__ import annotations

import pytest

from app.services.temporal_kinase_scoring import (
    MIN_EXCLUSIVE_FOR_PROFILE,
    compute_weighted_kinase_scores,
)
from ptm_shared.tmm_attribution_guard import (
    GROUP_SPLIT_REASON,
    GUARD_GROUP_SHARE,
    GUARD_OFF,
    GUARD_STRICT,
    WITHHELD_REASON,
)

CONDITIONS = ["t1", "t2", "t3", "t4"]

SHARED_PARALLEL = "SHARED_AB"
"""A·B 의 프로파일이 평행하므로 그룹 몫만 추정되는 site → `unresolved_shared`."""

SHARED_SEPARABLE = "SHARED_AC"
"""프로파일 방향이 달라 개별 기여가 분리되는 site → `resolved`."""

SHARED_NEGATIVE = "SHARED_NEG"
"""전 시점 음수라 비음수 조합이 설명하지 못하는 site → `unsupported`."""


@pytest.fixture(scope="module")
def synthetic_inputs():
    """세 resolution 이 모두 나타나는 최소 입력.

    A 와 B 의 exclusive substrate 를 같은 모양·다른 크기로 주어 프로파일이 평행해지게
    만든다(그룹화 조건). C 는 다른 모양을 준다.
    """
    shape = [1.0, 2.0, 1.0, 0.5]
    timeseries: dict[str, dict[str, float]] = {}
    ptm_to_kinases: dict[str, list[str]] = {}

    def add(key: str, values: list[float], kinases: list[str]) -> None:
        timeseries[key] = dict(zip(CONDITIONS, values))
        ptm_to_kinases[key] = kinases

    for index in range(MIN_EXCLUSIVE_FOR_PROFILE):
        add(f"A_exclusive_{index}", [value * 1.0 for value in shape], ["A"])
        add(f"B_exclusive_{index}", [value * 3.0 for value in shape], ["B"])
        add(f"C_exclusive_{index}", [0.4, 0.4, 2.0, 1.2], ["C"])

    add(SHARED_PARALLEL, [1.5, 3.0, 1.5, 0.75], ["A", "B"])
    add(SHARED_SEPARABLE, [1.0, 1.6, 1.4, 0.6], ["A", "C"])
    add(SHARED_NEGATIVE, [-1.2, -2.0, -0.9, -0.5], ["A", "B", "C"])

    modules = [
        {
            "canonical": kinase,
            "members": [
                {"key": key}
                for key, assigned in ptm_to_kinases.items()
                if kinase in assigned
            ],
        }
        for kinase in ("A", "B", "C")
    ]
    return modules, timeseries, ptm_to_kinases


def _score(synthetic_inputs, policy: str) -> dict:
    modules, timeseries, ptm_to_kinases = synthetic_inputs
    return compute_weighted_kinase_scores(
        modules, timeseries, ptm_to_kinases, CONDITIONS, guard_policy=policy
    )


def _score_mass(entry: dict) -> float:
    return sum(entry["weighted_up_sums"].values()) + sum(
        entry["weighted_down_sums"].values()
    )


def _detail(entry: dict, ptm_key: str) -> dict:
    for detail in entry["contribution_details"]:
        if detail["ptm_key"] == ptm_key:
            return detail
    raise AssertionError(f"{ptm_key} not present in contribution_details")


def test_the_fixture_exercises_all_three_resolutions(synthetic_inputs):
    """이 테스트가 무엇을 덮는지 먼저 못박는다. 라벨이 바뀌면 아래 검증이 무의미해진다."""
    scores = _score(synthetic_inputs, GUARD_OFF)
    assert _detail(scores["A"], SHARED_PARALLEL)["resolution"] == "unresolved_shared"
    assert _detail(scores["A"], SHARED_SEPARABLE)["resolution"] == "resolved"
    assert _detail(scores["A"], SHARED_NEGATIVE)["resolution"] == "unsupported"


def test_guard_off_publishes_every_ratio(synthetic_inputs):
    """기본값은 배포 동작이다. 진행 중인 분석의 수치를 바꾸지 않는다."""
    scores = _score(synthetic_inputs, GUARD_OFF)
    for kinase, entry in scores.items():
        identifiability = entry["tmm_identifiability"]
        assert identifiability["guard_policy"] == GUARD_OFF, kinase
        assert identifiability["n_guard_withheld"] == 0, kinase
        assert identifiability["n_guard_scoring_excluded"] == 0, kinase
        for detail in entry["contribution_details"]:
            assert detail["contribution_ratio"] is not None, (kinase, detail["ptm_key"])


def test_group_share_scores_are_identical_to_strict(synthetic_inputs):
    """§5.5 의 핵심 주장. 발표만 바뀌고 가중합은 그대로여야 한다."""
    strict = _score(synthetic_inputs, GUARD_STRICT)
    group_share = _score(synthetic_inputs, GUARD_GROUP_SHARE)

    assert set(strict) == set(group_share)
    for kinase in strict:
        assert _score_mass(group_share[kinase]) == pytest.approx(
            _score_mass(strict[kinase]), abs=1e-12
        ), kinase
        for field in ("weighted_up_sums", "weighted_down_sums", "weighted_up_counts",
                      "weighted_down_counts"):
            assert group_share[kinase][field] == pytest.approx(
                strict[kinase][field]
            ), (kinase, field)


def test_group_share_withholds_the_even_split_and_keeps_the_group_share(
    synthetic_inputs,
):
    """지우는 것은 균등 분할이고 남기는 것은 그룹 몫이다."""
    detail = _detail(_score(synthetic_inputs, GUARD_GROUP_SHARE)["A"], SHARED_PARALLEL)
    assert detail["contribution_ratio"] is None
    assert detail["guard_withheld"] is True
    assert detail["guard_scoring_excluded"] is False
    assert detail["guard_reason"] == GROUP_SPLIT_REASON
    assert detail["group_ratio"] is not None
    assert set(detail["ambiguity_group_members"]) == {"A", "B"}


def test_strict_leaves_the_even_split_published(synthetic_inputs):
    """`strict` 와 `group_share` 의 차이가 정확히 이 한 지점이어야 한다."""
    detail = _detail(_score(synthetic_inputs, GUARD_STRICT)["A"], SHARED_PARALLEL)
    assert detail["contribution_ratio"] is not None
    assert "guard_withheld" not in detail


def test_unsupported_is_excluded_from_scoring_under_both_policies(synthetic_inputs):
    """`unsupported` 는 두 정책에서 동일하게 처리된다 — `group_share` 는 상위집합이다."""
    for policy in (GUARD_STRICT, GUARD_GROUP_SHARE):
        detail = _detail(_score(synthetic_inputs, policy)["A"], SHARED_NEGATIVE)
        assert detail["contribution_ratio"] is None, policy
        assert detail["guard_withheld"] is True, policy
        assert detail["guard_scoring_excluded"] is True, policy
        # production 은 attribution 의 기계 판독 사유를 넘기고 guard 가 그것을 우선한다.
        # `WITHHELD_REASON` 은 사유가 없을 때의 대체값이다(단위 테스트가 그 경로를 덮는다).
        assert detail["guard_reason"] == detail["unsupported_reason"], policy
        assert detail["guard_reason"], policy


def test_the_two_withholding_reasons_stay_distinguishable_in_output(synthetic_inputs):
    """증거가 없는 것과 내부 분할만 없는 것을 출력에서 구별할 수 있어야 한다 (§5.5)."""
    entry = _score(synthetic_inputs, GUARD_GROUP_SHARE)["A"]
    unsupported = _detail(entry, SHARED_NEGATIVE)["guard_reason"]
    group_split = _detail(entry, SHARED_PARALLEL)["guard_reason"]
    assert unsupported != group_split
    assert group_split == GROUP_SPLIT_REASON
    assert WITHHELD_REASON not in (unsupported, group_split)


def test_separable_contributions_survive_group_share(synthetic_inputs):
    """분리 가능한 기여를 막으면 실재 신호를 버린다."""
    detail = _detail(
        _score(synthetic_inputs, GUARD_GROUP_SHARE)["A"], SHARED_SEPARABLE
    )
    assert detail["contribution_ratio"] is not None
    assert "guard_withheld" not in detail


def test_withheld_count_separates_publication_from_scoring(synthetic_inputs):
    """`n_guard_withheld` 와 `n_guard_scoring_excluded` 는 같은 수가 아니다 (§5.5)."""
    entry = _score(synthetic_inputs, GUARD_GROUP_SHARE)["A"]
    identifiability = entry["tmm_identifiability"]
    assert identifiability["n_guard_withheld"] == 2
    assert identifiability["n_guard_scoring_excluded"] == 1

    strict = _score(synthetic_inputs, GUARD_STRICT)["A"]["tmm_identifiability"]
    assert strict["n_guard_withheld"] == 1
    assert strict["n_guard_scoring_excluded"] == 1


def test_group_share_never_withholds_less_than_strict(synthetic_inputs):
    strict = _score(synthetic_inputs, GUARD_STRICT)
    group_share = _score(synthetic_inputs, GUARD_GROUP_SHARE)
    for kinase in strict:
        assert (
            group_share[kinase]["tmm_identifiability"]["n_guard_withheld"]
            >= strict[kinase]["tmm_identifiability"]["n_guard_withheld"]
        ), kinase


def test_an_unknown_policy_does_not_silently_pass_through(synthetic_inputs):
    with pytest.raises(ValueError, match="unknown guard policy"):
        _score(synthetic_inputs, "lenient")


def test_default_guard_policy_is_group_share(synthetic_inputs):
    """기본값이 GUARD_GROUP_SHARE 임을 못박는다.

    2026-08-22 GUARD_OFF → GUARD_GROUP_SHARE 전환 회귀 방지.
    `guard_policy` 를 명시하지 않으면 GUARD_GROUP_SHARE 가 적용돼야 한다.
    """
    modules, timeseries, ptm_to_kinases = synthetic_inputs
    scores_default = compute_weighted_kinase_scores(
        modules, timeseries, ptm_to_kinases, CONDITIONS
        # guard_policy deliberately omitted — tests the default
    )
    for kinase, entry in scores_default.items():
        policy_used = entry["tmm_identifiability"]["guard_policy"]
        assert policy_used == GUARD_GROUP_SHARE, (
            f"기본값이 GUARD_GROUP_SHARE 여야 하는데 {policy_used!r} 로 실행됨 — "
            "temporal_kinase_scoring.py 의 기본값이 변경된 것 같다."
        )
