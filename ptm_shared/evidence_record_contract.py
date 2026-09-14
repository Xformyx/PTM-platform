"""Shared evidence-type and numeric-record roles for reader cards.

구현 대상: docs/collaboration/integrated_implementation_w0_2026-09-14.md
사전등록: 2026-09-14 표시/전달 계약. 결과 열람 전.
해석 한계: 타입 이름이 생물학적 직접성이나 검정 결과를 뜻하지 않는다.
주장 금지: 이 계약으로 kinase 정확도나 하류 개선을 주장하지 않는다.
"""
from __future__ import annotations

VERSION = "reader_evidence_record.v1"

EVIDENCE_TYPES = (
    "feature_observation",
    "kinase_candidate",
    "temporal_module",
    "protein_trajectory",
    "pathway_context",
    "multiform_comparison",
    "paired_peptide_fraction",
    "atlas_observation",
    "cluster_profile",
)

RECORD_TYPES = (
    "feature_axis",
    "kinase_footprint",
    "kinase_trajectory",
    "module_interval",
    "protein_group",
    "pathway_enrichment",
    "dual_track",
    "paired_peptide_fraction",
    "multiform_comparison",
    "atlas_observation",
    "cluster_profile",
)

EXCLUSION_REASONS = (
    "source_unavailable",
    "not_computable",
    "ineligible",
    "not_relevant",
    "missing_adapter",
    "capacity_excluded",
    "relevant_but_unused",
    "generation_rejected",
    "postprocess_removed",
    "technical_only",
    "legacy_unavailable",
)


def typed_record(
    *,
    record_type: str,
    entity_id: str,
    metric_id: str,
    value,
    unit: str,
    condition: str | None = None,
    interval: str | None = None,
    numerator=None,
    denominator=None,
    estimator: str,
    support_status: str,
    test_status: str = "not_a_significance_test",
    evidence_id: str,
    source: dict | None = None,
) -> dict:
    if record_type not in RECORD_TYPES:
        raise ValueError("unknown_record_type")
    return {
        "record_type": record_type,
        "entity_id": entity_id,
        "metric_id": metric_id,
        "value": value,
        "unit": unit,
        "condition": condition,
        "interval": interval,
        "numerator": numerator,
        "denominator": denominator,
        "estimator": estimator,
        "support_status": support_status,
        "test_status": test_status,
        "evidence_id": evidence_id,
        "source": source or {},
        "schema_version": VERSION,
    }
