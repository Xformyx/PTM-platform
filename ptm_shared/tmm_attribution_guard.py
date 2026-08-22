"""Withhold kinase contribution ratios that carry no evidence.

구현 대상: docs/chapter2_audit_protocol_v1.md §5 (guard)
사전등록: 2026-08-21. 정책과 기본값을 **감사 재측정 전에** 선언한다. 임계를 새로
          도입하지 않으며, 판정은 이미 동결된 `ambiguity_aware_attribution`의
          `attribution_supported`를 그대로 쓴다.
해석 한계: guard가 막는 것은 "증거 없는 숫자를 측정처럼 발표하는 것"이다. 남는 숫자가
          옳다는 뜻이 아니다. guard 통과가 정확도 보증이 아니다.
주장 금지: guard 적용으로 kinase 예측이 개선되었다고 서술하지 않는다. 개선이 아니라
          **발표 범위의 축소**다.

무엇을 막는가
-------------
비음수 basis가 부호 있는 log2FC 궤적을 설명하지 못하면 NNLS는 모든 계수를 0으로
돌려주고, production은 `total < 1e-9` 분기에서 **균등 ratio 1/K**를 발표한다. 이 숫자는
측정처럼 보이지만 증거가 전혀 없다. 감사에서 이 경로가 site의 46.3%였다.

`strict` 정책은 그 site의 기여를 가중합에서 제외하고 `contribution_ratio`를 None으로
발표한다. 숫자를 고치는 것이 아니라 **없는 것을 없다고 말하는 것**이다.

``group_share`` 정책은 여기에 하나를 더한다 — ``unresolved_shared``의 개별 kinase ratio는
``group_ratio / |group|`` 즉 **균등 분할**이며 solver가 고른 값이다. 그 값을 None으로
발표하고 그룹 몫은 그대로 둔다(§5.5).

무엇을 막지 않는가 — 그리고 왜인가
----------------------------------
어느 정책도 ``unresolved_shared``의 **그룹 몫**은 막지 않는다. 그룹 몫은 데이터가
결정하므로 **증거가 있다**. 없는 것은 그룹 내부 분할뿐이다. 제외하면 실재하는 신호를
버리게 된다. ``group_share``에서도 그 site의 기여는 **가중합에 그대로 들어간다** —
이것이 ``strict``와의 핵심 차이이며, 발표에서 지우는 것과 점수에서 빼는 것은 서로 다른
행위다(§5.5).

``unannotated``도 막지 않는다. 이것은 증거에 대한 진술이 아니라 주석 계산이 예외로
실패했다는 인프라 오류다. 코드 버그로 데이터가 조용히 사라지는 것이 더 나쁘다.
대신 호출자가 로그로 남긴다.

기본값
------
``GUARD_OFF``이 기본이다. `integrated_research_design_v2.md` §2.7의
``production_influence_allowed = False``를 유지하며, 실행 중인 분석의 수치를 바꾸지
않는다. 정책을 켜는 것은 명시적 결정이어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

GUARD_OFF = "off"
"""현재 배포 동작. 증거 없는 균등 ratio도 그대로 발표한다.

docs/chapter2_audit_protocol_v1.md §5 에서 2026-08-21 선언. **기본값이며 기본값을
바꾸는 것은 별도 결정이다.** 기본값을 조용히 뒤집으면 진행 중인 분석의 수치가 바뀐다.
"""

GUARD_STRICT = "strict"
"""증거 없는 site의 기여를 가중합에서 제외하고 ratio를 None으로 발표한다.

docs/chapter2_audit_protocol_v1.md §5 에서 2026-08-21 선언. 감사 측정 후 도입이지만
**판정 기준은 2026-08-18 동결된 `attribution_supported`를 그대로 쓴다.** 새 임계 없음.
"""

GUARD_GROUP_SHARE = "group_share"
"""`strict`에 더해 ambiguity 그룹 내부의 균등 분할도 None으로 발표한다.

docs/chapter2_audit_protocol_v1.md §5.5 에서 2026-08-22 선언. **구현 착수 전 선언.**
새 임계가 없다 — 판정은 동결된 ``attribution_supported``와 ``ambiguous`` 플래그를 그대로 쓴다.
**가중합은 `strict`와 동일하다.** 그룹 몫은 데이터가 정한 값이므로 점수에서 빼지 않는다.
발표되는 개별 ratio 수를 §3.4 의 이미 측정된 해상도(7,216 → 891)로 내리는 것이 목적이며
정확도 개선이 아니다.
"""

GUARD_POLICIES = (GUARD_OFF, GUARD_STRICT, GUARD_GROUP_SHARE)

RESOLUTION_UNSUPPORTED = "unsupported"
RESOLUTION_UNRESOLVED_SHARED = "unresolved_shared"
RESOLUTION_RESOLVED = "resolved"
RESOLUTION_EXCLUSIVE = "exclusive"
RESOLUTION_UNANNOTATED = "unannotated"

WITHHELD_REASON = "no non-negative combination explains the trajectory"

GROUP_SPLIT_REASON = "per-kinase split inside an ambiguity group is not estimable"
"""`group_share`가 `unresolved_shared`를 보류할 때의 사유.

§5.5 에서 2026-08-22 선언. 문구가 `WITHHELD_REASON`과 달라야 하는 이유: 두 보류는
**서로 다른 결핍**이다. 전자는 증거가 아예 없고, 후자는 그룹 몫이라는 증거가 있으나
내부 분할에만 증거가 없다. 하나의 사유 문구로 합치면 논문에서 그 구분이 사라진다.
"""


@dataclass(frozen=True)
class GuardDecision:
    """정책 적용 결과.

    ``ratio_for_scoring``은 가중합에 들어가는 값이고 ``published_ratio``는 보고되는
    값이다. 둘을 분리하는 이유는 "점수에서 빼는 것"과 "숫자를 지우는 것"이 서로 다른
    행위이며 논문에서 따로 서술되어야 하기 때문이다.

    ``scoring_excluded``는 그 구분을 소비자가 **추론하지 않고 읽을 수 있게** 한다.
    ``ratio_for_scoring == 0.0`` 으로 판별하면 안 된다 — ratio 가 정당하게 0 일 수 있다.
    """

    ratio_for_scoring: float
    published_ratio: Optional[float]
    withheld: bool
    reason: Optional[str] = None
    scoring_excluded: bool = False


def apply_guard(
    resolution: str,
    ratio: float,
    *,
    policy: str = GUARD_OFF,
    reason: Optional[str] = None,
) -> GuardDecision:
    """한 (kinase, site) 기여에 guard 정책을 적용한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §5, §5.5 (`group_share`)
    해석 한계: 판정은 site 수준이다. 같은 site를 공유하는 모든 kinase가 함께 보류된다.
    주장 금지: 보류되지 않은 기여가 정확하다는 뜻이 아니다.
    """
    if policy not in GUARD_POLICIES:
        raise ValueError(f"unknown guard policy {policy!r}; expected one of {GUARD_POLICIES}")

    withholds_unsupported = policy in (GUARD_STRICT, GUARD_GROUP_SHARE)
    if withholds_unsupported and resolution == RESOLUTION_UNSUPPORTED:
        return GuardDecision(
            ratio_for_scoring=0.0,
            published_ratio=None,
            withheld=True,
            reason=reason or WITHHELD_REASON,
            scoring_excluded=True,
        )

    if policy == GUARD_GROUP_SHARE and resolution == RESOLUTION_UNRESOLVED_SHARED:
        # 그룹 몫은 데이터가 정한 값이므로 점수에 남긴다. 지우는 것은 균등 분할뿐이다.
        return GuardDecision(
            ratio_for_scoring=float(ratio),
            published_ratio=None,
            withheld=True,
            reason=reason or GROUP_SPLIT_REASON,
            scoring_excluded=False,
        )

    return GuardDecision(
        ratio_for_scoring=float(ratio),
        published_ratio=float(ratio),
        withheld=False,
    )


__all__ = [
    "GROUP_SPLIT_REASON",
    "GUARD_GROUP_SHARE",
    "GUARD_OFF",
    "GUARD_POLICIES",
    "GUARD_STRICT",
    "GuardDecision",
    "RESOLUTION_EXCLUSIVE",
    "RESOLUTION_RESOLVED",
    "RESOLUTION_UNANNOTATED",
    "RESOLUTION_UNRESOLVED_SHARED",
    "RESOLUTION_UNSUPPORTED",
    "WITHHELD_REASON",
    "apply_guard",
]
