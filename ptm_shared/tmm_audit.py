"""Reproducible audit protocol for the deployed TMM kinase attribution.

구현 대상: docs/chapter2_audit_protocol_v1.md — `reproduce` 단계
          (프로토콜 정의는 docs/integrated_research_design_v2.md §9.5)
사전등록: 2026-08-21. 감사 수치는 2026-08-18에 이미 산출되어 공표된 값이며,
          이 모듈은 그 값을 **재계산**할 뿐 새 판정 기준을 도입하지 않는다.
해석 한계: 이 모듈이 재현하는 것은 "배포된 추정기가 무엇을 결정하지 못하는지"이다.
          더 나은 추정기를 제안하지 않으며, 개선 주장의 근거로 쓸 수 없다.
주장 금지: 이 감사로 kinase 귀속의 생물학적 정확도를 논하지 않는다. 측정되는 것은
          식별가능성(해집합의 크기)이며 정답과의 거리가 아니다.

왜 이 모듈이 필요한가
---------------------
감사 수치(1,310 site, identifiable 1.1%)는 살아 있는 MySQL `orders` 행과
gitignore된 `data/outputs/` TSV에서 산출되었다. 두 입력 모두 버전 관리되지 않으므로
그 표는 **원리적으로 재생성 불가능**했다. 학위논문 표가 재생성 불가능하면 심사에서
방어할 수 없다.

이 모듈은 감사가 소비한 입력을 DB 없이 재생 가능한 fixture로 동결하고, 살아 있는
경로와 재생 경로가 **같은 계산 코드**를 쓰도록 강제한다. 둘이 갈라져서 재생이 다른
문제를 푸는 사고를 구조적으로 막는다(`audit_sites`가 유일한 계산 지점).

결정성
------
`solve_nnls`는 scipy가 있으면 `scipy.optimize.nnls`, 없으면 projected-gradient
fallback을 쓴다. **solver 경로가 바뀌면 수치가 바뀔 수 있으므로** fixture manifest에
scipy·numpy 버전과 solver 경로를 기록한다. seed는 site별로 `seed + site_index`이며,
`site_index`는 정렬된 shared-site 목록에서의 원래 위치다. 진단이 건너뛴 site도
인덱스를 소비했으므로 fixture는 그 인덱스를 보존해야 seed가 재현된다.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np

from ptm_shared.tmm_identifiability import (
    VERDICT_IDENTIFIABLE,
    ambiguity_aware_attribution,
    diagnose_site,
    summarize_bias,
    summarize_diagnostics,
    zero_imputation_bias,
)

FIXTURE_SCHEMA = "TMM_AUDIT_FIXTURE_V1"
"""동결 fixture 형식 식별자.

docs/chapter2_audit_protocol_v1.md §3 에서 2026-08-21 선언.
형식을 바꾸면 새 버전 문자열을 쓰고 기존 fixture는 그대로 둔다. 기존 fixture를
새 스키마로 덮어쓰면 공표된 감사 표의 출처가 사라진다.
"""

DEFAULT_RELATIVE_NOISE = 0.10
"""감사 산출에 쓰인 잡음 가정 ε = 0.10·||y||.

docs/tmm_identifiability_diagnosis.md 「방법」에서 선언. 숨은 상수가 아니라 기록되는
가정이며, 구조적 결론(rank, 중복 열)은 이 값과 무관하다.
"""

DEFAULT_BOOTSTRAP = 32
"""top-1 안정성 부트스트랩 반복 수. 공표된 감사와 동일해야 재현이 성립한다."""


# ---------------------------------------------------------------------------
# 입력 조립 — 살아 있는 경로에서만 쓰인다 (DB·TSV 필요)
# ---------------------------------------------------------------------------


HEATMAP_WRITER_ENDPOINT = "api_endpoint"
"""`api-server/app/api/orders.py` 의 global-kinase-modules 경로가 쓴 상태.

이 writer 는 비우세 클러스터를 **별도 후보**로 발행한다 — 이름이 `f"{kinase}_c{cluster_id}"`
이며(orders.py:7725) 자기 `substrates` 목록을 갖는다. 따라서 이 writer 의 상태에서는
후보 수와 module 내 site 수가 모두 더 크다.
"""

HEATMAP_WRITER_PIPELINE = "pipeline_worker"
"""`workers/rag_enrichment/tasks.py::_compute_kinase_activity_heatmap` 이 쓴 상태.

이 writer 는 클러스터를 `cluster_details` 안에만 보관하고 **별도 후보로 발행하지 않는다.**
같은 데이터에서도 후보 집합이 endpoint writer 보다 작다.
"""

HEATMAP_WRITER_UNKNOWN = "unknown"

_ENDPOINT_MARKERS = ("_cache_hash", "computed_at", "scoring_method")
_PIPELINE_MARKERS = ("_cached", "all_kinase_scores")


def classify_heatmap_writer(heatmap: Mapping[str, Any]) -> str:
    """`orders.kinase_activity_heatmap` 을 쓴 코드 경로를 최상위 키로 판별한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §4.3 (오더 48 후보 축소 원인 규명)
    사전등록: **탐색적.** 이 판별기는 2026-08-22 에 §8 미결 항목을 규명하다가 만들어졌고,
              감사 결과를 본 뒤에 도입되었다. 어떤 사전등록 임계도 이것으로 갱신되지 않는다.
    해석 한계: 두 writer 를 **구별**하지만 어느 쪽이 옳은지 말하지 않는다. 후보를 더 많이
              발행하는 것이 더 정확한 것이 아니다 — §4.1 에서 접미사 변종이 정리된 뒤
              중복 열 비율이 오히려 올랐다(91.0% → 95.9%).
              판별은 최상위 키에만 근거하므로, 두 writer 의 스키마가 나중에 수렴하면
              `unknown` 이 늘어난다. 그때는 이 함수가 조용히 틀리지 않고 드러난다.
    주장 금지: "endpoint writer 의 후보 집합이 진짜다".
              "이 판별로 2026-08-18 상태를 복원할 수 있다" — 복원 불가다(§4.1).
    """
    keys = set(heatmap or {})
    endpoint = sum(1 for marker in _ENDPOINT_MARKERS if marker in keys)
    pipeline = sum(1 for marker in _PIPELINE_MARKERS if marker in keys)
    if endpoint and not pipeline:
        return HEATMAP_WRITER_ENDPOINT
    if pipeline and not endpoint:
        return HEATMAP_WRITER_PIPELINE
    return HEATMAP_WRITER_UNKNOWN


def count_sub_pattern_candidates(kinase_scores: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """후보 중 비우세 클러스터 변종(`..._c{n}`)의 수를 센다.

    `is_sub_pattern` 플래그를 먼저 보고, 없으면 이름 형태로 판정한다 — 이름만으로 세면
    실제로 `_c3` 로 끝나는 kinase 가 있을 때 잘못 센다. 두 경로의 값을 함께 돌려주므로
    불일치가 드러난다.
    """
    by_flag = 0
    by_name = 0
    for entry in kinase_scores:
        if entry.get("is_sub_pattern"):
            by_flag += 1
        name = str(entry.get("kinase") or "")
        if re.search(r"_c\d+$", name):
            by_name += 1
    return {
        "n_candidates": len(kinase_scores),
        "n_sub_pattern_by_flag": by_flag,
        "n_sub_pattern_by_name": by_name,
        "flag_and_name_agree": by_flag == by_name,
    }


def build_kinase_modules(
    kinase_scores: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], int]:
    """저장된 kinase 점수에서 module 구조와 site→kinase 대응을 복원한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §2 (detect 입력 복원)
    해석 한계: 저장된 substrate 목록이 잘려 있으면 후보 집합이 실제보다 작아진다.
              잘린 kinase 수를 함께 돌려주므로 호출자가 그 사실을 기록해야 한다.
    """
    modules: List[Dict[str, Any]] = []
    ptm_to_kinases: Dict[str, List[str]] = {}
    n_truncated = 0
    for entry in kinase_scores:
        canonical = str(entry.get("kinase") or entry.get("canonical") or "").upper()
        if not canonical:
            continue
        substrates = entry.get("substrates") or entry.get("members") or []
        keys = [str(item.get("ptm_key") or item.get("key") or "") for item in substrates]
        keys = [key for key in keys if key]
        declared = entry.get("substrate_count") or entry.get("total_substrates")
        if declared and int(declared) > len(keys):
            n_truncated += 1
        modules.append({"canonical": canonical, "members": [{"key": key} for key in keys]})
        for key in keys:
            ptm_to_kinases.setdefault(key, [])
            if canonical not in ptm_to_kinases[key]:
                ptm_to_kinases[key].append(canonical)
    return modules, ptm_to_kinases, n_truncated


def load_timeseries(
    output_dir: Path, file_suffix: str
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Set[str]]]:
    """kinase endpoint와 동일하게 ptm_timeseries를 복원하고 관측 집합을 함께 반환한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §2 (detect 입력 복원)
    해석 한계: 관측 집합은 TSV에 행이 존재하는지로 정의된다. 값이 0.0인 관측과
              미관측을 구별하는 유일한 근거이며, 이 구별이 0 대입 편향 측정의 전제다.
    """
    timeseries: Dict[str, Dict[str, float]] = {}
    observed: Dict[str, Set[str]] = {}
    for name in (
        f"ptm_vector_data_normalized{file_suffix}.tsv",
        f"ptm_vector_data_with_motifs{file_suffix}.tsv",
    ):
        path = output_dir / name
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                gene = row.get("Gene.Name", row.get("gene", "")) or ""
                position = str(row.get("PTM_Position", row.get("position", "")) or "")
                condition = row.get("Condition", "") or ""
                if not gene or not position or not condition:
                    continue
                raw = row.get("PTM_Relative_Log2FC", "")
                try:
                    value = float(raw) if raw else 0.0
                except ValueError:
                    value = 0.0
                key = f"{gene.upper()}_{position.upper()}"
                timeseries.setdefault(key, {})[condition] = value
                observed.setdefault(key, set()).add(condition)
        break
    return timeseries, observed


def build_design(
    candidates: Sequence[str],
    kinase_profiles: Mapping[str, Mapping[str, Any]],
    conditions: Sequence[str],
) -> Tuple[np.ndarray, List[str], List[bool]]:
    """``deconvolve_shared_ptm`` 내부에서 조립되는 설계행렬을 그대로 재구성한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §2 (detect 입력 복원)
    해석 한계: exclusive substrate가 부족한 kinase는 문헌 peak time이 관측인 것처럼
              basis에 들어간다. 그 열은 prior 유래로 표시되며, top-1이 그 열에서
              나왔다는 사실이 「prior와 증거의 분리」 주장의 근거다.
    주장 금지: prior 유래 열이라는 사실만으로 그 kinase 귀속이 틀렸다고 말하지 않는다.
              측정된 것은 "데이터가 그 값을 결정하지 않았다"이다.
    """
    from app.services.temporal_kinase_scoring import (
        BASOPHILIC_KINASES,
        PRO_DIRECTED_KINASES,
        _gaussian_kinase_profile,
    )

    columns: List[np.ndarray] = []
    names: List[str] = []
    prior_flags: List[bool] = []
    for canonical in candidates:
        info = kinase_profiles.get(canonical)
        if info is None:
            reference = BASOPHILIC_KINASES.get(canonical) or PRO_DIRECTED_KINASES.get(canonical)
            if reference:
                low, high = reference["typical_peak_min"]
                peak = (low + high) / 2.0
            else:
                peak = 30.0
            columns.append(np.asarray(_gaussian_kinase_profile(conditions, peak), dtype=float))
            prior_flags.append(True)
        else:
            columns.append(np.asarray(info["profile"], dtype=float))
            prior_flags.append(info.get("profile_type") != "data_driven")
        names.append(canonical)
    if not columns:
        return np.zeros((len(conditions), 0)), names, prior_flags
    return np.column_stack(columns), names, prior_flags


# ---------------------------------------------------------------------------
# 감사 계산 — 살아 있는 경로와 재생 경로가 공유하는 유일한 지점
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteInputs:
    """한 site에 대해 배포된 solver가 받는 입력 전체.

    ``site_index``는 정렬된 shared-site 목록에서의 원래 위치이며 site별 seed를
    결정한다. 진단이 건너뛴 site(후보 열 0개)도 인덱스를 소비했으므로, 이 값을
    보존하지 않으면 부트스트랩 seed가 어긋나 재현이 깨진다.
    """

    site_index: int
    site_key: str
    candidates: Tuple[str, ...]
    design: np.ndarray
    prior_flags: Tuple[bool, ...]
    target: np.ndarray
    observed_mask: Tuple[bool, ...]


def audit_sites(
    site_inputs: Iterable[SiteInputs],
    *,
    relative_noise: float = DEFAULT_RELATIVE_NOISE,
    n_bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = 0,
) -> Dict[str, Any]:
    """site 입력들에 대해 식별가능성·0 대입 편향·ambiguity 귀속을 계산한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §2·§3
    사전등록: 판정 임계는 ``tmm_identifiability.default_thresholds``에서 2026-08-18
              선언되었고 이 함수는 그 값을 바꾸지 않는다.
    해석 한계: 반환되는 비율은 검사한 6개 오더의 유병률이며 모집단 추정치가 아니다.
    주장 금지: 이 값으로 플랫폼 전체나 다른 파이프라인의 신뢰성을 일반화하지 않는다.

    살아 있는 감사와 fixture 재생이 **모두 이 함수를 통과**해야 한다. 계산이 두 곳에
    복제되면 재생이 다른 문제를 설명하게 된다.
    """
    diagnostics = []
    bias_records: List[Dict[str, Any]] = []
    attribution_records: List[Dict[str, Any]] = []

    for item in site_inputs:
        if item.design.size == 0 or item.design.shape[1] == 0:
            continue
        names = list(item.candidates)
        diagnostics.append(
            diagnose_site(
                item.site_key,
                item.target,
                item.design,
                names,
                relative_noise=relative_noise,
                n_bootstrap=n_bootstrap,
                seed=seed + item.site_index,
                prior_columns=list(item.prior_flags),
            )
        )

        attribution = ambiguity_aware_attribution(
            item.site_key,
            item.target,
            item.design,
            names,
            relative_noise=relative_noise,
        )
        attribution_records.append(
            {
                "site_key": item.site_key,
                "n_candidates": attribution.n_candidates,
                "n_groups": attribution.n_groups,
                "attribution_supported": attribution.attribution_supported,
                "unsupported_reason": attribution.unsupported_reason,
                "n_ambiguous_groups": sum(1 for group in attribution.groups if group.ambiguous),
                "largest_group_size": max(
                    (len(group.members) for group in attribution.groups), default=0
                ),
                "reduced_verdict": (
                    attribution.reduced_diagnosis.verdict
                    if attribution.reduced_diagnosis
                    else None
                ),
            }
        )

        bias_records.append(
            zero_imputation_bias(
                item.site_key,
                item.target,
                item.design,
                names,
                np.asarray(item.observed_mask, dtype=bool),
            )
        )

    return {
        "n_diagnosed": len(diagnostics),
        "identifiability": summarize_diagnostics(diagnostics),
        "zero_imputation_bias": summarize_bias(bias_records),
        "attribution": summarize_attribution(attribution_records),
        "sites": [item.to_dict() for item in diagnostics],
    }


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------


def quantiles(values: Sequence[float], points: Sequence[int] = (10, 50, 90)) -> Dict[str, Any]:
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if finite.size == 0:
        return {"n": 0, **{f"p{point}": None for point in points}, "max": None}
    summary: Dict[str, Any] = {"n": int(finite.size)}
    for point in points:
        summary[f"p{point}"] = float(np.percentile(finite, point))
    summary["max"] = float(finite.max())
    return summary


def summarize_attribution(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """발표되는 양과 실제 추정 가능한 양을 비교한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §2
    해석 한계: ``quantity_reduction``은 "보고량이 얼마나 과했는지"이며 정확도 개선이
              아니다. 해상도를 낮춰 방어 가능한 진술로 바꾼 비율이다.
    """
    summary: Dict[str, Any] = {"n_sites": len(records)}
    if not records:
        return summary

    published = sum(int(record["n_candidates"]) for record in records)
    supported = [record for record in records if record["attribution_supported"]]
    estimable = sum(int(record["n_groups"]) for record in supported)
    verdicts: Dict[str, int] = {}
    for record in supported:
        label = str(record.get("reduced_verdict"))
        verdicts[label] = verdicts.get(label, 0) + 1

    summary.update(
        {
            "per_kinase_ratios_published": published,
            "estimable_group_shares": estimable,
            "quantity_reduction": 1.0 - (estimable / published) if published else None,
            "n_supported": len(supported),
            "unsupported_rate": 1.0 - len(supported) / len(records),
            "sites_needing_merge_rate": float(
                np.mean([record["n_groups"] < record["n_candidates"] for record in records])
            ),
            "largest_group_size": quantiles(
                [int(record["largest_group_size"]) for record in records]
            ),
            "reduced_verdicts": verdicts,
            "reduced_verdict_fractions": {
                key: value / len(supported) for key, value in verdicts.items()
            }
            if supported
            else {},
        }
    )
    return summary


def combine_attribution(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    published = estimable = supported = sites = 0
    verdicts: Dict[str, int] = {}
    for report in reports:
        block = report.get("attribution") or {}
        if not block.get("n_sites"):
            continue
        sites += int(block["n_sites"])
        published += int(block["per_kinase_ratios_published"])
        estimable += int(block["estimable_group_shares"])
        supported += int(block["n_supported"])
        for key, value in (block.get("reduced_verdicts") or {}).items():
            verdicts[key] = verdicts.get(key, 0) + int(value)
    if not sites:
        return {}
    return {
        "n_sites": sites,
        "per_kinase_ratios_published": published,
        "estimable_group_shares": estimable,
        "quantity_reduction": 1.0 - estimable / published if published else None,
        "n_supported": supported,
        "unsupported_rate": 1.0 - supported / sites,
        "reduced_verdicts": verdicts,
        "reduced_verdict_fractions": (
            {key: value / supported for key, value in verdicts.items()} if supported else {}
        ),
    }


def combine(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """오더별 보고를 논문에 실리는 통합 표로 합친다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §2 (공표 수치의 출처)
    해석 한계: site를 오더 구분 없이 pooling하므로 오더가 큰 쪽(오더 36, 907 site)이
              통합 비율을 지배한다. 오더별 표를 반드시 함께 보고해야 한다.
    """
    pooled: List[Dict[str, Any]] = []
    for report in reports:
        pooled.extend(report["sites"])

    def rate(key: str) -> Optional[float]:
        flags = [site.get(key) for site in pooled if site.get(key) is not None]
        return float(np.mean([bool(flag) for flag in flags])) if flags else None

    verdicts: Dict[str, int] = {}
    for site in pooled:
        label = str(site.get("verdict"))
        verdicts[label] = verdicts.get(label, 0) + 1
    total = max(len(pooled), 1)
    return {
        "n_orders": len(reports),
        "n_sites": len(pooled),
        "verdicts": verdicts,
        "verdict_fractions": {key: value / total for key, value in verdicts.items()},
        "structurally_underdetermined_rate": rate("structurally_underdetermined"),
        "rank_one_design_rate": float(
            np.mean([int(site.get("design_rank") or 0) <= 1 for site in pooled])
        )
        if pooled
        else None,
        "explains_nothing_rate": float(
            np.mean([float(site.get("relative_residual") or 0.0) >= 0.999 for site in pooled])
        )
        if pooled
        else None,
        "top1_in_ambiguity_set_rate": float(
            np.mean(
                [
                    bool(
                        site.get("top1_kinase")
                        and site.get("top1_kinase") in (site.get("ambiguity_set") or [])
                    )
                    for site in pooled
                ]
            )
        )
        if pooled
        else None,
        "top1_from_prior_rate": rate("top1_from_prior"),
        "equal_weight_fallback_rate": rate("equal_weight_fallback"),
        "attribution": combine_attribution(reports),
    }


# ---------------------------------------------------------------------------
# 동결 fixture — DB 없이 감사를 재생하기 위한 입력 아카이브
# ---------------------------------------------------------------------------


def freeze_site_inputs(site_inputs: Sequence[SiteInputs]) -> Dict[str, Any]:
    """설계 열을 중복 제거해 site 입력을 직렬화 가능한 형태로 만든다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §3 (reproduce)
    해석 한계: 열 중복 제거가 가능한 것 자체가 감사 결과다. 오더 36은 111개 후보가
              서로 다른 열 9개만 가지므로 fixture가 작아진다. 크기가 작다는 사실을
              "데이터가 적다"로 읽지 않는다 — 후보가 많고 열이 적은 것이다.
    """
    columns: List[Tuple[float, ...]] = []
    column_ids: Dict[Tuple[float, ...], int] = {}
    sites: List[Dict[str, Any]] = []

    for item in site_inputs:
        ids: List[int] = []
        matrix = np.asarray(item.design, dtype=float)
        for position in range(matrix.shape[1]):
            key = tuple(matrix[:, position].tolist())
            if key not in column_ids:
                column_ids[key] = len(columns)
                columns.append(key)
            ids.append(column_ids[key])
        target = np.asarray(item.target, dtype=float)
        if not np.all(np.isfinite(target)):
            raise ValueError(f"non-finite target for {item.site_key}; fixture would not round-trip")
        sites.append(
            {
                "site_index": int(item.site_index),
                "site_key": item.site_key,
                "candidates": list(item.candidates),
                "column_ids": ids,
                "prior_flags": [bool(flag) for flag in item.prior_flags],
                "target": target.tolist(),
                "observed_mask": [bool(flag) for flag in item.observed_mask],
            }
        )

    return {"columns": [list(column) for column in columns], "sites": sites}


def thaw_site_inputs(fixture: Mapping[str, Any]) -> List[SiteInputs]:
    """동결된 fixture에서 ``SiteInputs``를 복원한다. DB·TSV를 읽지 않는다."""
    columns = [np.asarray(column, dtype=float) for column in fixture["columns"]]
    restored: List[SiteInputs] = []
    for site in fixture["sites"]:
        ids = site["column_ids"]
        design = (
            np.column_stack([columns[index] for index in ids])
            if ids
            else np.zeros((len(site["target"]), 0))
        )
        restored.append(
            SiteInputs(
                site_index=int(site["site_index"]),
                site_key=str(site["site_key"]),
                candidates=tuple(str(name) for name in site["candidates"]),
                design=design,
                prior_flags=tuple(bool(flag) for flag in site["prior_flags"]),
                target=np.asarray(site["target"], dtype=float),
                observed_mask=tuple(bool(flag) for flag in site["observed_mask"]),
            )
        )
    return restored


def replay_order(fixture: Mapping[str, Any]) -> Dict[str, Any]:
    """fixture 하나로 오더 보고를 재계산한다. DB 접근 없음.

    구현 대상: docs/chapter2_audit_protocol_v1.md §3 (reproduce)
    해석 한계: ``production_ratio_max_deviation``은 재계산되지 않는다. 그것은 살아 있는
              ``deconvolve_shared_ptm``과의 대조이므로 fixture에 **기록된 값**을
              그대로 옮긴다. 즉 "배포 추정기와 동일하다"는 근거는 동결 시점의 증거이며
              재생이 다시 증명하는 것이 아니다.
    """
    assumptions = fixture["assumptions"]
    report = audit_sites(
        thaw_site_inputs(fixture),
        relative_noise=float(assumptions["relative_noise"]),
        n_bootstrap=int(assumptions["n_bootstrap"]),
        seed=int(assumptions["seed"]),
    )
    for key in (
        "order_id",
        "order_code",
        "status",
        "ptm_type",
        "conditions",
        "n_timepoints",
        "n_kinases",
        "n_kinase_profiles",
        "profile_types",
        "n_sites_in_modules",
        "n_shared_sites",
        "site_list_truncated",
        "n_kinases_with_truncated_substrate_list",
        "production_ratio_max_deviation",
    ):
        if key in fixture:
            report[key] = fixture[key]
    report["assumptions"] = dict(assumptions)
    return report


def replay_fixture_dir(fixture_dir: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """fixture 디렉터리 전체를 재생해 오더별 보고와 통합 표를 돌려준다."""
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    reports: List[Dict[str, Any]] = []
    for entry in manifest["orders"]:
        path = fixture_dir / entry["file"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != FIXTURE_SCHEMA:
            raise ValueError(f"{path.name}: unexpected schema {payload.get('schema')!r}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(
                f"{path.name}: sha256 mismatch — fixture was modified after freezing"
            )
        reports.append(replay_order(payload))
    return reports, combine(reports)


def fixture_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# guard ablation — 정책을 켰을 때 무엇이 보류되는가
# ---------------------------------------------------------------------------


def guard_ablation(
    site_inputs: Sequence[SiteInputs],
    *,
    relative_noise: float = DEFAULT_RELATIVE_NOISE,
    fc_threshold: float = 0.3,
) -> Dict[str, Any]:
    """`GUARD_STRICT`와 `GUARD_GROUP_SHARE`가 보류하는 양을 kinase 수준까지 정량화한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §5 (guard ablation), §5.5 (`group_share`)
    사전등록: 2026-08-21 (strict arm), 2026-08-22 (`group_share` arm, 구현 착수 전 §5.5 선언).
              판정은 동결된 ``attribution_supported``와 그룹 구성을 쓰고 새 임계가 없다.
              ``fc_threshold``는 production 기본값 0.3이며 모든 arm에 동일하게 적용된다.
    해석 한계: **공유 site만** 다룬다. exclusive substrate는 guard 대상이 아니므로 여기
              집계되지 않는다. 따라서 ``withheld_fraction``은 "그 kinase의 공유 증거 중
              증거 없는 비율"이며 전체 증거 대비 비율이 아니다.
              q-value는 fixture에 없으므로 통과 판정은 ``|fc| >= fc_threshold``만 쓴다.
              production이 q-value를 함께 보는 site에서는 양이 다를 수 있다.
    주장 금지: 보류량을 정확도 개선폭으로 읽지 않는다. 측정된 것은 발표 범위의 축소다.

    ``evidence_count_mass``는 production이 ``weighted_up_counts``/``weighted_down_counts``에
    누적하는 분수 카운트와 같은 양이다(통과 조건마다 ratio 를 더한 값). guard 를 켜면
    unsupported site 의 기여가 0이 되므로 그 차이가 보류량이다.

    ``group_share`` arm 은 **점수 질량을 바꾸지 않는다** (§5.5) — 따라서
    ``evidence_count_mass_*`` 계열은 strict arm 것만 있고 group_share 용이 따로 없다.
    그 arm 에서 세는 것은 **발표되는 개별 ratio 수**이며, 감사 §3.4 의
    ``attribution.estimable_group_shares`` 와 같은 양을 독립 경로로 재현한다.
    """
    from ptm_shared.tmm_identifiability import normalized_ratios, solve_nnls

    per_kinase: Dict[str, Dict[str, float]] = {}
    n_withheld_sites = 0
    n_published_pairs = 0
    n_withheld_pairs = 0
    n_sites = 0
    n_group_share_withheld_pairs = 0
    n_estimable_group_shares = 0
    n_ambiguous_groups = 0

    for item in site_inputs:
        if item.design.size == 0 or item.design.shape[1] == 0:
            continue
        n_sites += 1
        names = list(item.candidates)
        n_published_pairs += len(names)

        attribution = ambiguity_aware_attribution(
            item.site_key,
            item.target,
            item.design,
            names,
            relative_noise=relative_noise,
        )
        withheld = not attribution.attribution_supported
        if withheld:
            n_withheld_sites += 1
            n_withheld_pairs += len(names)
            # unsupported site 에서는 그룹 몫도 추정되지 않으므로 세지 않는다.
            n_group_share_withheld_pairs += len(names)
        else:
            n_estimable_group_shares += len(attribution.groups)
            n_ambiguous_groups += sum(1 for group in attribution.groups if group.ambiguous)
            n_group_share_withheld_pairs += sum(
                len(group.members) for group in attribution.groups if group.ambiguous
            )

        # production 이 실제로 쓰는 ratio: 붕괴하면 균등, 아니면 NNLS 비율.
        ratios = normalized_ratios(solve_nnls(item.design, item.target)[0])
        passing = [
            value for value in np.asarray(item.target, dtype=float) if abs(value) >= fc_threshold
        ]

        for position, name in enumerate(names):
            record = per_kinase.setdefault(
                name,
                {
                    "n_shared_sites": 0.0,
                    "n_withheld_sites": 0.0,
                    "n_separable_sites": 0.0,
                    "evidence_count_mass_off": 0.0,
                    "evidence_count_mass_strict": 0.0,
                },
            )
            ratio = float(ratios[position]) if position < len(ratios) else 0.0
            mass = ratio * len(passing)
            record["n_shared_sites"] += 1.0
            record["evidence_count_mass_off"] += mass
            if withheld:
                record["n_withheld_sites"] += 1.0
            else:
                record["evidence_count_mass_strict"] += mass
                # production 의 `resolution == "resolved"` 와 같은 판정이다.
                entry = attribution.per_kinase.get(name)
                if (
                    entry is not None
                    and entry.get("attribution_supported")
                    and not entry.get("ambiguous")
                ):
                    record["n_separable_sites"] += 1.0

    kinases: Dict[str, Dict[str, Any]] = {}
    for name, record in per_kinase.items():
        off = record["evidence_count_mass_off"]
        strict = record["evidence_count_mass_strict"]
        kinases[name] = {
            "n_shared_sites": int(record["n_shared_sites"]),
            "n_withheld_sites": int(record["n_withheld_sites"]),
            "n_separable_sites": int(record["n_separable_sites"]),
            "evidence_count_mass_off": off,
            "evidence_count_mass_strict": strict,
            "withheld_fraction": (off - strict) / off if off > 0 else None,
        }

    fully_withheld = [
        name
        for name, record in kinases.items()
        if record["n_shared_sites"] > 0 and record["n_withheld_sites"] == record["n_shared_sites"]
    ]
    majority_withheld = [
        name
        for name, record in kinases.items()
        if record["withheld_fraction"] is not None and record["withheld_fraction"] >= 0.5
    ]

    no_separable_site = [
        name
        for name, record in kinases.items()
        if record["n_shared_sites"] > 0 and record["n_separable_sites"] == 0
    ]

    return {
        "policy_compared": ["off", "strict", "group_share"],
        "fc_threshold": fc_threshold,
        "n_shared_sites": n_sites,
        "n_withheld_sites": n_withheld_sites,
        "withheld_site_rate": n_withheld_sites / n_sites if n_sites else None,
        "n_published_pairs": n_published_pairs,
        "n_withheld_pairs": n_withheld_pairs,
        "withheld_pair_rate": n_withheld_pairs / n_published_pairs if n_published_pairs else None,
        "n_kinases": len(kinases),
        "n_kinases_losing_all_shared_evidence": len(fully_withheld),
        "n_kinases_losing_majority_shared_evidence": len(majority_withheld),
        "kinases_losing_all_shared_evidence": sorted(fully_withheld),
        # §5.5 group_share arm. **점수 질량은 strict 와 같다** — 여기 세는 것은 발표량이다.
        "group_share": {
            "n_withheld_pairs": n_group_share_withheld_pairs,
            "withheld_pair_rate": (
                n_group_share_withheld_pairs / n_published_pairs
                if n_published_pairs
                else None
            ),
            "n_published_per_kinase_ratios": n_published_pairs - n_group_share_withheld_pairs,
            "n_estimable_group_shares": n_estimable_group_shares,
            "n_ambiguous_groups": n_ambiguous_groups,
            "published_quantity_reduction": (
                1.0 - n_estimable_group_shares / n_published_pairs
                if n_published_pairs
                else None
            ),
            "n_kinases_without_any_separable_site": len(no_separable_site),
            "kinases_without_any_separable_site": sorted(no_separable_site),
        },
        "kinases": kinases,
    }


def solver_provenance() -> Dict[str, Any]:
    """수치를 재현하려면 알아야 하는 solver·라이브러리 상태.

    구현 대상: .cursor/rules/research-code-provenance.mdc §5 (결정성 기록)
    """
    from ptm_shared import tmm_identifiability

    provenance: Dict[str, Any] = {
        "numpy": np.__version__,
        "nnls_path": "scipy.optimize.nnls"
        if getattr(tmm_identifiability, "_HAS_SCIPY", False)
        else "projected_gradient_fallback",
        "dtype": "float64",
    }
    try:
        import scipy

        provenance["scipy"] = scipy.__version__
    except Exception:
        provenance["scipy"] = None
    return provenance


__all__ = [
    "DEFAULT_BOOTSTRAP",
    "DEFAULT_RELATIVE_NOISE",
    "FIXTURE_SCHEMA",
    "SiteInputs",
    "VERDICT_IDENTIFIABLE",
    "audit_sites",
    "build_design",
    "build_kinase_modules",
    "combine",
    "combine_attribution",
    "fixture_digest",
    "freeze_site_inputs",
    "guard_ablation",
    "load_timeseries",
    "quantiles",
    "replay_fixture_dir",
    "replay_order",
    "solver_provenance",
    "summarize_attribution",
    "thaw_site_inputs",
]
