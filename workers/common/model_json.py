"""Load a JSON value from model text without treating a fence as failure.

구현 대상: docs/official_temporal_terminology_contract.md § Structured model JSON
사전등록: 2026-09-14 표시 계약. 결과 기반 primary 승격 아님.
해석 한계: 복원된 객체가 과학적 참임을 증명하지 않는다.
주장 금지: 파싱 성공을 kinase 귀속이나 하류 개선으로 해석하지 않는다.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def parse_model_json(text: str) -> Any:
    """Return a dict or list from fenced or wrapped model JSON."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty_model_json")
    candidates: list[str] = []
    stripped = _FENCE_RE.sub("", raw).strip()
    for candidate in (raw, stripped):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            block = candidate[start : end + 1]
            if block not in candidates:
                candidates.append(block)
        start, end = candidate.find("["), candidate.rfind("]")
        if start != -1 and end > start:
            block = candidate[start : end + 1]
            if block not in candidates:
                candidates.append(block)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError) as exc:
            last_error = exc
            continue
        if isinstance(parsed, (dict, list)):
            return parsed
        last_error = ValueError("model_json_must_be_object_or_array")
    raise last_error or ValueError("invalid_model_json")
