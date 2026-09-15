"""Canonical Report audience and renderer-mode contract.

구현 대상: docs/report_audience_mode_contract_v1.md §1–§4
사전등록: 2026-09-15. 00:58 DOCX 회귀 이후 표시·dispatch 계약. 측정 공식 변경 아님.
해석 한계: audience/mode는 renderer와 export 라벨만 고정한다.
주장 금지: 이 계약 통과를 kinase 예측 향상으로 해석하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

REPORT_MODE_CONTRACT_VERSION = "report_audience_mode.v1"
"""Canonical audience/mode contract id.

docs/report_audience_mode_contract_v1.md §1 에서 2026-09-15 선언.
결과 열람 후 값을 바꾸면 00:58 dispatch 판정이 무효가 된다.
"""

REPORT_AUDIENCES = frozenset({"researcher_manuscript", "technical_audit"})
READER_AUTHORING_MODES = frozenset({"shadow", "opt_in_shadow", "legacy"})
READER_RENDERER_MODES = frozenset({"shadow", "opt_in_shadow"})
TECHNICAL_AUDIT_DELIVERIES = frozenset({"separate_sidecar", "embedded_technical_report"})


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _extract_report_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        return {}
    nested = config.get("report_config")
    if isinstance(nested, Mapping) and (
        "report_audience" in nested
        or "reader_authoring_mode" in nested
        or "technical_audit_delivery" in nested
        or "report_config" in nested
    ):
        return dict(nested)
    if any(key in config for key in ("report_audience", "reader_authoring_mode", "technical_audit_delivery")):
        return dict(config)
    return dict(nested) if isinstance(nested, Mapping) else {}


def _normalize_enum(value: Any) -> str:
    return str(value or "").strip().lower()


def _contract_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {
            "report_audience": payload.get("report_audience"),
            "requested_reader_mode": payload.get("requested_reader_mode"),
            "effective_reader_mode": payload.get("effective_reader_mode"),
            "technical_audit_delivery": payload.get("technical_audit_delivery"),
            "valid": payload.get("valid"),
            "reason_codes": payload.get("reason_codes"),
            "migration_rule": payload.get("migration_rule"),
            "contract_version": payload.get("contract_version"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_report_mode_contract(config: Any = None) -> Mapping[str, Any]:
    """Return the immutable audience/mode contract for one Report request.

    구현 대상: docs/report_audience_mode_contract_v1.md §2–§4
    사전등록: 2026-09-15. writer/graph/release가 각자 mode를 계산하면 안 된다.
    해석 한계: 이 매핑은 dispatch 계약이다. 데이터 품질이나 kinase 귀속을 증명하지 않는다.
    주장 금지: valid=True를 연구 결론의 과학적 승인으로 쓰지 않는다.
    """
    if isinstance(config, Mapping) and config.get("contract_version") == REPORT_MODE_CONTRACT_VERSION:
        return MappingProxyType(dict(config))
    raw = _extract_report_config(config)
    if isinstance(config, Mapping) and isinstance(config.get("report_mode_contract"), Mapping):
        existing = dict(config["report_mode_contract"])
        if existing.get("contract_version") == REPORT_MODE_CONTRACT_VERSION:
            return MappingProxyType(dict(existing))
    audience = _normalize_enum(raw.get("report_audience"))
    requested_mode = _normalize_enum(raw.get("reader_authoring_mode"))
    delivery = _normalize_enum(raw.get("technical_audit_delivery"))
    reasons: list[str] = []
    migration_rule = "explicit"

    if audience and audience not in REPORT_AUDIENCES:
        reasons.append("schema_validation_error")
    if requested_mode and requested_mode not in READER_AUTHORING_MODES:
        reasons.append("schema_validation_error")
    if delivery and delivery not in TECHNICAL_AUDIT_DELIVERIES:
        reasons.append("schema_validation_error")

    if not audience and requested_mode in READER_RENDERER_MODES:
        audience = "researcher_manuscript"
        migration_rule = "historical_shadow_migrated_to_researcher_manuscript"
        reasons.append(migration_rule)
    elif not audience:
        audience = "technical_audit"
        if not requested_mode:
            requested_mode = "legacy"
        migration_rule = "historical_legacy_default"
        reasons.append(migration_rule)

    if audience == "researcher_manuscript" and requested_mode not in READER_RENDERER_MODES:
        reasons.append("audience_mode_mismatch")
    if audience == "technical_audit" and requested_mode in READER_RENDERER_MODES:
        reasons.append("technical_audience_with_shadow_renderer")

    valid = "schema_validation_error" not in reasons and "audience_mode_mismatch" not in reasons
    if audience == "researcher_manuscript":
        effective_mode = requested_mode if requested_mode in READER_RENDERER_MODES else ""
        delivery = delivery or "separate_sidecar"
    else:
        effective_mode = requested_mode if requested_mode in READER_AUTHORING_MODES else "legacy"
        delivery = delivery or (
            "separate_sidecar" if effective_mode in READER_RENDERER_MODES else "embedded_technical_report"
        )

    payload = {
        "report_audience": audience or "",
        "requested_reader_mode": requested_mode,
        "effective_reader_mode": effective_mode,
        "technical_audit_delivery": delivery,
        "valid": valid,
        "reason_codes": sorted(set(reasons)),
        "migration_rule": migration_rule,
        "contract_version": REPORT_MODE_CONTRACT_VERSION,
    }
    payload["report_mode_contract_sha256"] = _contract_sha256(payload)
    return MappingProxyType(payload)


def apply_report_mode_contract(report_config: Any = None) -> tuple[dict[str, Any], Mapping[str, Any]]:
    """Write canonical fields back into report_config after resolving the contract."""
    contract = resolve_report_mode_contract(report_config)
    effective = dict(report_config) if isinstance(report_config, Mapping) else {}
    effective.pop("report_mode_contract", None)
    nested = effective.get("report_config")
    if isinstance(nested, Mapping) and not any(
        key in effective for key in ("report_audience", "reader_authoring_mode", "technical_audit_delivery")
    ):
        effective.pop("report_config", None)
        effective.update(nested)
    effective["report_audience"] = contract["report_audience"]
    if contract["effective_reader_mode"]:
        effective["reader_authoring_mode"] = contract["effective_reader_mode"]
    elif contract["requested_reader_mode"]:
        effective["reader_authoring_mode"] = contract["requested_reader_mode"]
    effective["technical_audit_delivery"] = contract["technical_audit_delivery"]
    return effective, contract


def contract_from_state(state: Any) -> Mapping[str, Any]:
    """Read the stored contract, or resolve once for tests that omit task handoff."""
    payload = _as_mapping(state)
    stored = payload.get("report_mode_contract")
    if isinstance(stored, Mapping) and stored.get("contract_version") == REPORT_MODE_CONTRACT_VERSION:
        return MappingProxyType(dict(stored))
    return resolve_report_mode_contract(state)


def uses_reader_renderer(contract: Any) -> bool:
    payload = _as_mapping(contract)
    return payload.get("effective_reader_mode") in READER_RENDERER_MODES


def is_researcher_manuscript(contract: Any) -> bool:
    payload = _as_mapping(contract)
    return payload.get("report_audience") == "researcher_manuscript"


def researcher_path_allowed(contract: Any) -> bool:
    payload = _as_mapping(contract)
    return bool(payload.get("valid")) and is_researcher_manuscript(payload) and uses_reader_renderer(payload)


def is_reader_mode(config: Any) -> bool:
    """Deprecated wrapper. Prefer contract_from_state() / uses_reader_renderer()."""
    contract = resolve_report_mode_contract(config)
    return bool(contract.get("valid")) and uses_reader_renderer(contract)
