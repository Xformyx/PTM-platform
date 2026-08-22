"""Regression tests for the order-level temporal contract switch.

구현 대상: docs/substrate_temporal_dynamics_deepening_plan_v1.md §8
사전등록: 2026-08-22. 구현 착수 전 선언.
해석 한계: 스위치가 어느 경로를 고르는지만 확인한다.
주장 금지: Dynamics v1 통과를 분석 품질 개선으로 서술하지 않는다.
"""

from __future__ import annotations

import pytest

from ptm_shared.temporal_contract import (
    DEFAULT_TEMPORAL_CONTRACT,
    TEMPORAL_CONTRACT_DYNAMICS_V1,
    TEMPORAL_CONTRACT_LEGACY,
    resolve_temporal_contract,
    same_temporal_arm,
)
from ptm_shared.tmm_attribution_guard import GUARD_GROUP_SHARE, GUARD_OFF


def test_missing_source_defaults_to_dynamics_v1():
    spec = resolve_temporal_contract(None)
    assert spec.name == DEFAULT_TEMPORAL_CONTRACT == TEMPORAL_CONTRACT_DYNAMICS_V1
    assert spec.guard_policy == GUARD_GROUP_SHARE
    assert spec.emit_heatmap_sub_patterns is True
    assert spec.inject_p1_report_context is True
    assert spec.run_atlas_report is True
    assert spec.show_p1_ui is True


def test_empty_report_options_default_to_dynamics_v1():
    spec = resolve_temporal_contract({})
    assert spec.name == TEMPORAL_CONTRACT_DYNAMICS_V1


def test_legacy_disables_new_layers():
    spec = resolve_temporal_contract({"temporal_contract": "legacy"})
    assert spec.name == TEMPORAL_CONTRACT_LEGACY
    assert spec.guard_policy == GUARD_OFF
    assert spec.emit_heatmap_sub_patterns is False
    assert spec.inject_p1_report_context is False
    assert spec.run_atlas_report is False
    assert spec.show_p1_ui is False


def test_nested_report_options_are_read():
    spec = resolve_temporal_contract({"report_options": {"temporal_contract": "legacy"}})
    assert spec.name == TEMPORAL_CONTRACT_LEGACY


def test_explicit_string_is_accepted():
    assert resolve_temporal_contract("legacy").name == TEMPORAL_CONTRACT_LEGACY
    assert resolve_temporal_contract("dynamics_v1").name == TEMPORAL_CONTRACT_DYNAMICS_V1


def test_stored_current_alias_resolves_to_dynamics_v1():
    spec = resolve_temporal_contract("current")
    assert spec.name == TEMPORAL_CONTRACT_DYNAMICS_V1
    assert same_temporal_arm("current", "dynamics_v1") is True
    assert same_temporal_arm("current", "legacy") is False


def test_unknown_contract_is_rejected():
    with pytest.raises(ValueError, match="unknown temporal_contract"):
        resolve_temporal_contract({"temporal_contract": "lagacy"})
