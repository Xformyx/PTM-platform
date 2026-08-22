"""Order-level A/B contract for substrate temporal dynamics.

구현 대상: docs/substrate_temporal_dynamics_deepening_plan_v1.md §8
사전등록: 2026-08-22. 비교 스위치를 구현하기 전에 선언.
해석 한계: 이 값은 분석 경로를 고르는 스위치다. 어느 쪽이 생물학적으로
          맞다는 판정이 아니다.
주장 금지: Dynamics v1 을 켠 결과를 kinase 귀속 정확도 개선으로 서술하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from ptm_shared.tmm_attribution_guard import GUARD_GROUP_SHARE, GUARD_OFF


TEMPORAL_CONTRACT_LEGACY = "legacy"
TEMPORAL_CONTRACT_DYNAMICS_V1 = "dynamics_v1"
TEMPORAL_CONTRACT_CURRENT_ALIAS = "current"
"""Deprecated stored alias for Dynamics v1. Resolve to ``dynamics_v1``.

2026-08-22 첫 구현에서 `current` 로 저장했다. 상대 시각 이름이라
Dynamics v1 으로 바꿨고, 이미 저장된 `current` 는 같은 경로로 읽는다.
"""

TEMPORAL_CONTRACTS = (
    TEMPORAL_CONTRACT_LEGACY,
    TEMPORAL_CONTRACT_DYNAMICS_V1,
    TEMPORAL_CONTRACT_CURRENT_ALIAS,
)
DEFAULT_TEMPORAL_CONTRACT = TEMPORAL_CONTRACT_DYNAMICS_V1
"""오더에 키가 없으면 Dynamics v1.

docs/substrate_temporal_dynamics_deepening_plan_v1.md §8.1
누락을 legacy 로 읽으면 이미 새 경로로 끝난 오더가 조용히 구경로로 바뀐다.
명시적 `legacy` 만 구경로다.
"""


@dataclass(frozen=True)
class TemporalContractSpec:
    """Resolved effects of one temporal_contract value."""

    name: str
    guard_policy: str
    emit_heatmap_sub_patterns: bool
    inject_p1_report_context: bool
    run_atlas_report: bool
    show_p1_ui: bool


def _canonical_name(raw: str) -> str:
    if raw == TEMPORAL_CONTRACT_CURRENT_ALIAS:
        return TEMPORAL_CONTRACT_DYNAMICS_V1
    return raw


def _spec_for(name: str) -> TemporalContractSpec:
    canonical = _canonical_name(name)
    if canonical == TEMPORAL_CONTRACT_LEGACY:
        return TemporalContractSpec(
            name=TEMPORAL_CONTRACT_LEGACY,
            guard_policy=GUARD_OFF,
            emit_heatmap_sub_patterns=False,
            inject_p1_report_context=False,
            run_atlas_report=False,
            show_p1_ui=False,
        )
    return TemporalContractSpec(
        name=TEMPORAL_CONTRACT_DYNAMICS_V1,
        guard_policy=GUARD_GROUP_SHARE,
        emit_heatmap_sub_patterns=True,
        inject_p1_report_context=True,
        run_atlas_report=True,
        show_p1_ui=True,
    )


def _extract_raw(source: Any) -> Optional[str]:
    if source is None:
        return None
    if isinstance(source, str):
        return source
    if not isinstance(source, Mapping):
        return None
    for key in ("temporal_contract",):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for nested_key in ("report_options", "report_config"):
        nested = source.get(nested_key)
        if isinstance(nested, Mapping):
            value = nested.get("temporal_contract")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def same_temporal_arm(left: Any, right: Any) -> bool:
    """True when two stored labels resolve to the same arm."""
    return resolve_temporal_contract(left).name == resolve_temporal_contract(right).name


def resolve_temporal_contract(source: Any = None) -> TemporalContractSpec:
    """Resolve ``legacy`` / ``dynamics_v1`` from report_options, worker config, or state.

    Missing or empty → Dynamics v1. Stored alias ``current`` maps to Dynamics v1.
    An explicit unknown string is an error so a typo cannot silently select an arm.
    """
    raw = _extract_raw(source)
    if raw is None:
        return _spec_for(DEFAULT_TEMPORAL_CONTRACT)
    if raw not in TEMPORAL_CONTRACTS:
        raise ValueError(
            f"unknown temporal_contract {raw!r}; "
            f"expected one of {TEMPORAL_CONTRACTS}"
        )
    return _spec_for(raw)
