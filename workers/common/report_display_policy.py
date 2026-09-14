"""Declared reader-display policy for shadow Report generation.

구현 대상: docs/개발_업무지시서_연구자용_PTM_Report의_Identity_Projection·서사·생성.md §4.E-2
사전등록: 2026-09-14 표시 계약. 데이터셋 결과를 본 뒤 임계를 바꾸지 않는다.
해석 한계: 정책 해시는 표시·생성 계약의 재현용이며 분석 성능의 증거가 아니다.
주장 금지: 이 수치를 kinase 예측 정확도 개선으로 해석하지 않는다.
"""
from __future__ import annotations

import hashlib
import json

from common.section_budgets import SECTION_BUDGETS

REPORT_DISPLAY_POLICY_VERSION = "reader_display_policy.v1"
SHADOW_AUTHORING_MODE = "shadow"
STANDARD_AUTHORING_MODE = "standard"

PER_PARAGRAPH_NAMED_FEATURE_LIMIT = 3
"""Maximum named features in one narrative paragraph.

docs/개발_업무지시서_연구자용_PTM_Report의_Identity_Projection·서사·생성.md §4.D-1
에서 2026-09-14 선언. 측정 후 변경 금지.
"""

MAIN_FIGURE_COUNT_LIMIT = 3
HEATMAP_ROW_MINIMUM = 12
HEATMAP_ROW_MAXIMUM = 16
PROMPT_CHAR_BUDGET = 200_000
COMPACTION_STAGE_COUNT = 6
TECHNICAL_IDENTIFIER_EXPOSURE = "hidden_binding_only"
PARSER_RECOVERY_POLICY = "retain_valid_sibling_sentences"
FIGURE_AXIS_WORDING = {
    "unadjusted": "independent unadjusted PTM relative log2 contrast",
    "adjusted": "protein-abundance-adjusted relative PTM log2 contrast",
    "protein": "linked protein relative log2 contrast",
    "render_axis": "protein_adjusted_relative_ptm_contrast",
}


def _shadow_policy() -> dict:
    return {
        "policy_version": REPORT_DISPLAY_POLICY_VERSION,
        "authoring_mode": SHADOW_AUTHORING_MODE,
        "main_figure_count_limit": MAIN_FIGURE_COUNT_LIMIT,
        "heatmap_row_minimum": HEATMAP_ROW_MINIMUM,
        "heatmap_row_maximum": HEATMAP_ROW_MAXIMUM,
        "per_paragraph_named_feature_limit": PER_PARAGRAPH_NAMED_FEATURE_LIMIT,
        "section_word_budgets": {key: dict(value) for key, value in SECTION_BUDGETS.items()},
        "prompt_char_budget": PROMPT_CHAR_BUDGET,
        "compaction_stage_count": COMPACTION_STAGE_COUNT,
        "figure_axis_wording": dict(FIGURE_AXIS_WORDING),
        "technical_identifier_exposure": TECHNICAL_IDENTIFIER_EXPOSURE,
        "parser_recovery_policy": PARSER_RECOVERY_POLICY,
    }


def _standard_policy() -> dict:
    return {
        "policy_version": REPORT_DISPLAY_POLICY_VERSION,
        "authoring_mode": STANDARD_AUTHORING_MODE,
        "shadow_compaction_enabled": False,
        "shadow_role_batch_enabled": False,
        "technical_identifier_exposure": "legacy_unspecified",
        "parser_recovery_policy": "legacy_section_or_retry",
    }


def effective_display_policy(authoring_mode: str | None = SHADOW_AUTHORING_MODE) -> dict:
    """Return the frozen display policy for the requested authoring mode."""
    mode = str(authoring_mode or STANDARD_AUTHORING_MODE).strip().lower()
    policy = _shadow_policy() if mode == SHADOW_AUTHORING_MODE else _standard_policy()
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return {
        **policy,
        "policy_sha256": hashlib.sha256(encoded).hexdigest(),
    }
