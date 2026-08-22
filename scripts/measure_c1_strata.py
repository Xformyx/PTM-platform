"""C1 동결 전 실측 — 계층 크기, adapter 교집합, 그리고 정렬 확인 4항목.

구현 대상: docs/c1_prereg_v1.md §3.1 (계층 정의) · §3.2 (계층 크기 미지) · §3.3 (확장 경로 L1/L2/L3)
          · §2.1.1 `TAU_ALIGNMENT_ADAPTER_V1` A3·A4·A5
          · docs/c1_alignment_check_2026-08-21.md §5 (데이터 접근 필요 4항목)
사전등록: **결과 열람 전.** 계층 정의(§3.1)·확장 경로 순서(§3.3)·검정력 기준(§3.4)이
          2026-08-20~21 에 동결되었고 이 스크립트는 그 정의를 적용할 뿐 임계를 도입하지 않는다.
          τ 는 계산하지 않는다 — τ 를 보기 전에 모집단을 확정하는 것이 이 측정의 목적이다.
해석 한계: 계층 비율은 **검사한 오더의 유병률**이며 모집단 추정치가 아니다.
          `S-EVAL` 크기는 τ 의 정밀도 상한을 정할 뿐 τ 의 값이나 부호를 말하지 않는다.
          adapter 교집합은 form→site 집계 규칙(§2.1.2)에 의존하므로 규칙별로 따로 보고한다.
주장 금지: 계층 크기로 배포 추정기의 생물학적 타당도를 논하지 않는다. 측정되는 것은
          「어느 site 에서 τ 가 정의되는가」이며 귀속이 옳은지가 아니다.
          `S-EVAL` 이 작다는 것을 "표현 학습이 쓸모없다"로 읽지 않는다 — 하류 사전(dictionary)의
          퇴화이며 상류 표현의 성질이 아니다.

정본 환경(설계행렬 조립에 필요한 참조 kinase 표가 있는 API 컨테이너):

    docker exec -i ptm-api-server env PYTHONPATH=/app:/opt python - \
        --order-ids 52 < scripts/measure_c1_strata.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

sys.path[:0] = ["/app", "/opt"]

from ptm_shared.tmm_audit import (  # noqa: E402
    DEFAULT_BOOTSTRAP,
    DEFAULT_RELATIVE_NOISE,
    SiteInputs,
    build_design,
    build_kinase_modules,
    load_timeseries,
    solver_provenance,
)
from ptm_shared.tmm_identifiability import diagnose_site  # noqa: E402

S_EVAL_POWER_TIERS = ((195, "E1b 중복도 추정 정밀. E3 확증 판정"),
                      (73, "E1b 는 CI 폭 명시. E3 는 검정력 부족 선언 + 효과크기·CI 보고"),
                      (0, "E3 primary 평가 불가. C1 은 미평가로 선언"))
"""검정력 구간. docs/c1_prereg_v1.md §3.4 에서 2026-08-21 선언. τ 산정 전.

근거는 Spearman ρ 의 Fisher-z CI 반폭 (SE ≈ 1.06/√(n−3)).
**측정 후 변경 금지** — 변경하면 C1 평가 가능성 판정이 무효가 된다.
여기서 도입하는 값이 아니라 인용이며, 이 스크립트는 구간을 재계산하지 않는다.
"""

MINIMUM_OBSERVED_TIMEPOINTS = 3
"""인코더 적격 기준. `ptm_representation_learning_contract_v1.md` §8 의 production 기본값.

C1 이 새로 정하는 값이 아니라 배포된 표현 학습 설정을 그대로 인용한다. 이 값을 바꾸면
adapter 교집합(§2.1.1 A5)이 달라지므로 C1 모집단이 달라진다.
"""


def normalize_site_key(gene: str, position: str) -> str:
    """`TAU_ALIGNMENT_ADAPTER_V1` A1 의 정규형.

    구현 대상: docs/c1_prereg_v1.md §2.1.1 A1
    해석 한계: gene 별칭은 해결하지 않는다. 두 경로가 같은 원본 TSV 에서 나오므로
              별칭 문제는 발생하지 않지만, 다른 출처를 섞으면 이 함수로는 부족하다.
    """
    return f"{str(gene).strip().upper()}_{str(position).strip().upper()}"


async def load_order(order_id: int) -> Optional[Dict[str, Any]]:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT id, order_code, ptm_type, status, kinase_activity_heatmap"
                    " FROM orders WHERE id = :id"
                ),
                {"id": order_id},
            )
        ).first()
    if row is None or not row.kinase_activity_heatmap:
        return None
    raw = row.kinase_activity_heatmap
    return {
        "id": int(row.id),
        "order_code": str(row.order_code),
        "ptm_type": str(row.ptm_type or ""),
        "status": str(row.status or ""),
        "heatmap": json.loads(raw) if isinstance(raw, (str, bytes)) else raw,
    }


def assemble_site_inputs(
    order: Mapping[str, Any], output_root: Path, *, max_sites: int
) -> Tuple[List[SiteInputs], Dict[str, Any]]:
    """감사와 동일한 경로로 site 입력을 조립한다. 계산 코드를 복제하지 않는다."""
    from app.services.temporal_kinase_scoring import build_kinase_profiles_from_data

    heatmap = order["heatmap"]
    conditions = [str(condition) for condition in (heatmap.get("conditions") or [])]
    kinase_scores = heatmap.get("kinase_scores") or []
    if len(conditions) < 2 or not kinase_scores:
        raise RuntimeError(
            f"order {order['id']}: conditions={len(conditions)} kinases={len(kinase_scores)}"
        )

    suffix = "_phospho" if order["ptm_type"] == "phosphorylation" else "_ubi"
    order_dir = output_root / order["order_code"]
    timeseries, observed = load_timeseries(order_dir, suffix)
    if not timeseries:
        raise RuntimeError(f"order {order['id']}: no vector TSV under {order_dir}")

    modules, ptm_to_kinases, n_truncated = build_kinase_modules(kinase_scores)
    profiles = build_kinase_profiles_from_data(modules, timeseries, ptm_to_kinases, conditions)

    all_shared = sorted(key for key, names in ptm_to_kinases.items() if len(names) >= 2)
    shared = all_shared[:max_sites] if max_sites and len(all_shared) > max_sites else all_shared

    site_inputs: List[SiteInputs] = []
    for index, site_key in enumerate(shared):
        candidates = ptm_to_kinases[site_key]
        design, names, prior_flags = build_design(candidates, profiles, conditions)
        series = timeseries.get(site_key, {})
        target = np.asarray([series.get(cond, 0.0) for cond in conditions], dtype=float)
        seen = observed.get(site_key, set())
        site_inputs.append(
            SiteInputs(
                site_index=index,
                site_key=site_key,
                candidates=tuple(names),
                design=design,
                prior_flags=tuple(prior_flags),
                target=target,
                observed_mask=tuple(cond in seen for cond in conditions),
            )
        )

    meta = {
        "order_id": order["id"],
        "order_code": order["order_code"],
        "ptm_type": order["ptm_type"],
        "status": order["status"],
        "conditions": conditions,
        "n_timepoints": len(conditions),
        "n_kinases": len(kinase_scores),
        "n_kinase_profiles": len(profiles),
        "n_sites_in_modules": len(ptm_to_kinases),
        "n_shared_sites": len(all_shared),
        "site_list_truncated": len(shared) != len(all_shared),
        "n_kinases_with_truncated_substrate_list": n_truncated,
    }
    return site_inputs, meta


def classify_strata(site_inputs: Sequence[SiteInputs]) -> List[Dict[str, Any]]:
    """§3.1 의 계층 정의를 그대로 적용한다. 임계를 새로 정하지 않는다.

    구현 대상: docs/c1_prereg_v1.md §3.1
    해석 한계: 계층은 **배타적이며 순서가 있다** — S-DEAD 를 먼저 걸러내고, 남은 것에서
              S-NOFIT, 그 다음 S-RANK1, 나머지가 S-EVAL 이다. 순서를 바꾸면 비율이 바뀐다.
    """
    records: List[Dict[str, Any]] = []
    for item in site_inputs:
        if item.design.size == 0 or item.design.shape[1] == 0:
            continue
        diagnosis = diagnose_site(
            item.site_key,
            item.target,
            item.design,
            list(item.candidates),
            relative_noise=DEFAULT_RELATIVE_NOISE,
            n_bootstrap=DEFAULT_BOOTSTRAP,
            seed=item.site_index,
            prior_columns=list(item.prior_flags),
        ).to_dict()

        if diagnosis.get("equal_weight_fallback"):
            stratum = "S-DEAD"
        elif float(diagnosis.get("relative_residual") or 0.0) >= 0.999:
            stratum = "S-NOFIT"
        elif int(diagnosis.get("design_rank") or 0) <= 1:
            stratum = "S-RANK1"
        elif np.isfinite(float(diagnosis.get("design_condition_number") or np.inf)):
            stratum = "S-EVAL"
        else:
            stratum = "S-RANK1"

        records.append(
            {
                "site_key": item.site_key,
                "stratum": stratum,
                "n_candidates": len(item.candidates),
                "design_rank": diagnosis.get("design_rank"),
                "design_condition_number": diagnosis.get("design_condition_number"),
                "active_sigma_min": diagnosis.get("active_sigma_min"),
                "max_column_coherence": diagnosis.get("max_column_coherence"),
                "n_redundant": diagnosis.get("n_redundant"),
                "relative_residual": diagnosis.get("relative_residual"),
                "verdict": diagnosis.get("verdict"),
                "n_observed": int(sum(item.observed_mask)),
                # 아래는 docs/c1_prereg_v1.md §5.1 이 E1 site 레코드에 요구하는 나머지
                # provenance 이며 §6.2 의 방향 무관 예측자 집합 X 에도 쓰인다.
                # 계층 배정 논리는 바뀌지 않는다 — 순수 추가다.
                "active_condition_number": diagnosis.get("active_condition_number"),
                "n_active": diagnosis.get("n_active"),
                "active_rank": diagnosis.get("active_rank"),
                "structurally_underdetermined": diagnosis.get("structurally_underdetermined"),
                "equal_weight_fallback": diagnosis.get("equal_weight_fallback"),
                "prior_column_fraction": diagnosis.get("prior_column_fraction"),
                "top1_from_prior": diagnosis.get("top1_from_prior"),
            }
        )
    return records


def strata_from_fixture(fixture_dir: Path) -> List[Dict[str, Any]]:
    """L3 pool 의 계층을 **동결 fixture** 에서 계산한다. DB 를 읽지 않는다.

    구현 대상: docs/c1_prereg_v1.md §3.3 L3 (6 오더 전체 pool)
    사전등록: L3 의 정의는 공표된 6 오더 pool 이며 여기서 오더를 추가하지 않는다.
              살아 있는 DB 에는 heatmap 이 있는 오더가 더 많지만(35·38 ubiquitylation),
              **사후에 모집단을 늘리면 선택 편향**이므로 fixture 에 있는 6 오더만 쓴다.
    해석 한계: 오더 48 의 살아 있는 입력은 2026-08-20 에 덮어써졌으므로(§4 표류) fixture 와
              다르다. fixture 를 쓰는 것은 재현 가능성 때문이며, τ 를 실제로 계산할 때는
              **같은 fixture 를 써야 모집단이 일치한다.**
    주장 금지: fixture 수치를 현재 production 의 상태로 서술하지 않는다.
    """
    from ptm_shared.tmm_audit import FIXTURE_SCHEMA, fixture_digest, thaw_site_inputs

    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    pooled: List[Dict[str, Any]] = []
    for entry in manifest["orders"]:
        path = fixture_dir / entry["file"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != FIXTURE_SCHEMA:
            raise ValueError(f"{path.name}: unexpected schema {payload.get('schema')!r}")
        if fixture_digest(path) != entry["sha256"]:
            raise ValueError(f"{path.name}: sha256 mismatch — fixture was modified")
        records = classify_strata(thaw_site_inputs(payload))
        for record in records:
            record["order_id"] = int(payload["order_id"])
            record["order_code"] = str(payload["order_code"])
            record["ptm_type"] = str(payload.get("ptm_type") or "")
            record["n_timepoints"] = int(payload.get("n_timepoints") or 0)
        pooled.extend(records)
    return pooled


def load_encoder_populations(vector_path: Path) -> Dict[str, Any]:
    """인코더 적격 집합을 form 수준과 site 수준 양쪽에서 만든다.

    구현 대상: docs/c1_prereg_v1.md §2.1.1 A5 (모집단 교집합), §2.1.2 (form→site 집계)
    해석 한계: 두 수준을 모두 산출하는 이유는 §2.1.2 의 후보 (a)(site 수준 설정)와
              (c)(최다 관측 form 대표)가 서로 다른 모집단을 뜻하기 때문이다.
              어느 쪽을 쓸지는 이 스크립트가 결정하지 않는다.
    """
    import pandas as pd

    from ptm_shared.representation import build_multiview_input, validate_multiview_input

    frame = pd.read_csv(vector_path, sep="\t", low_memory=False)
    records = frame.to_dict("records")

    populations: Dict[str, Any] = {}
    for level in ("form", "site"):
        multiview = build_multiview_input(
            records,
            config={
                "key_level": level,
                "minimum_observed_timepoints": MINIMUM_OBSERVED_TIMEPOINTS,
            },
        )
        errors = validate_multiview_input(multiview)
        eligible = multiview.eligible_subset()
        normalized: Dict[str, int] = {}
        for key in eligible.site_keys:
            meta = eligible.site_metadata.get(key, {})
            gene = meta.get("gene") or meta.get("Gene.Name") or ""
            position = meta.get("position") or meta.get("PTM_Position") or ""
            if not gene or not position:
                # form 수준 키는 "GENE POS|form" 형식이다. 앞부분에서 복원한다.
                head = str(key).split("|", 1)[0]
                parts = head.rsplit(" ", 1)
                if len(parts) == 2:
                    gene, position = parts
            if not gene or not position:
                continue
            canonical = normalize_site_key(gene, position)
            normalized[canonical] = normalized.get(canonical, 0) + 1
        populations[level] = {
            "n_rows_total": multiview.n_sites,
            "n_rows_eligible": eligible.n_sites,
            "n_timepoints": eligible.n_timepoints,
            "timepoints": list(eligible.timepoints),
            "contract_errors": errors,
            "normalized_site_keys": normalized,
        }
    return populations


def check_condition_alignment(conditions: Sequence[str], timepoints: Sequence[str]) -> Dict[str, Any]:
    """A3(control 성분) 과 A4(수열 동일성) 를 확인한다.

    구현 대상: docs/c1_prereg_v1.md §2.1.1 A3·A4
    해석 한계: 순서가 다르면 재배열로 해결되지만, **집합이 다르면 재배열로 해결되지 않는다.**
              그 경우 τ 는 공통 성분에서만 정의되며 그 사실을 기록해야 한다.
    """
    from ptm_shared.representation.feature_contract import timepoint_to_minutes

    control = [cond for cond in conditions if str(cond).strip().lower() == "control"]
    without_control = [cond for cond in conditions if str(cond).strip().lower() != "control"]
    encoder_order = list(timepoints)
    nnls_sorted = sorted(
        without_control, key=lambda label: (timepoint_to_minutes(label), str(label))
    )
    return {
        "nnls_conditions": list(conditions),
        "nnls_n_conditions": len(conditions),
        "control_components": control,
        "nnls_conditions_without_control": without_control,
        "encoder_timepoints": encoder_order,
        "set_identical": set(without_control) == set(encoder_order),
        "sequence_identical_as_stored": without_control == encoder_order,
        "sequence_identical_after_sort": nnls_sorted == encoder_order,
        "reordering_required": (
            set(without_control) == set(encoder_order) and without_control != encoder_order
        ),
        "minutes_by_condition": {
            str(label): timepoint_to_minutes(label) for label in conditions
        },
    }


def power_tier(n: int) -> str:
    for threshold, label in S_EVAL_POWER_TIERS:
        if n >= threshold:
            return label
    return S_EVAL_POWER_TIERS[-1][1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-ids", default="52")
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument("--max-sites", type=int, default=4000)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--l3-fixture-dir",
        default=None,
        help="동결 fixture 로 L3 pool 을 함께 측정한다 (§3.3). 예: /app/tests/fixtures/tmm_audit_v1",
    )
    args = parser.parse_args(argv)

    output_root = Path(args.data_root) / "outputs"
    order_ids = [int(part) for part in str(args.order_ids).split(",") if part.strip()]

    print("=" * 88)
    print("C1 동결 전 실측 — 계층 크기 · adapter 교집합 · 정렬 확인")
    print("판정 아님. τ 는 계산하지 않는다 (c1_prereg_v1.md §3)")
    print("=" * 88)
    print(f"solver = {json.dumps(solver_provenance(), ensure_ascii=False)}")
    print()

    payload: Dict[str, Any] = {
        "contract": "C1_STRATA_MEASUREMENT_V1",
        "measured_at": "2026-08-22",
        "solver": solver_provenance(),
        "power_tiers": [[n, label] for n, label in S_EVAL_POWER_TIERS],
        "orders": [],
    }

    for order_id in order_ids:
        order = asyncio.run(load_order(order_id))
        if order is None:
            print(f"[skip] order {order_id}: heatmap 없음")
            continue

        site_inputs, meta = assemble_site_inputs(
            order, output_root, max_sites=args.max_sites
        )
        records = classify_strata(site_inputs)
        counts: Dict[str, int] = {}
        for record in records:
            counts[record["stratum"]] = counts.get(record["stratum"], 0) + 1

        print("-" * 88)
        print(f"order {order_id} | {meta['order_code']} | {meta['ptm_type']} | {meta['status']}")
        print(
            f"  후보 kinase {meta['n_kinases']} | profile {meta['n_kinase_profiles']}"
            f" | module site {meta['n_sites_in_modules']} | shared site {meta['n_shared_sites']}"
            f" | 진단 {len(records)}"
        )
        print(f"  조건 {meta['n_timepoints']}개: {meta['conditions']}")
        print()
        total = max(len(records), 1)
        print("  계층 (배타적. §3.1 순서대로 적용)")
        for stratum in ("S-DEAD", "S-NOFIT", "S-RANK1", "S-EVAL"):
            n = counts.get(stratum, 0)
            print(f"    {stratum:<9} {n:>6}  {n / total * 100:>6.2f}%")
        n_eval = counts.get("S-EVAL", 0)
        print()
        print(f"  |S-EVAL| = {n_eval}  →  {power_tier(n_eval)}")

        vector = output_root / meta["order_code"] / (
            "ptm_vector_data_normalized_phospho.tsv"
            if meta["ptm_type"] == "phosphorylation"
            else "ptm_vector_data_normalized_ubi.tsv"
        )
        encoder: Dict[str, Any] = {}
        alignment: Dict[str, Any] = {}
        intersections: Dict[str, Any] = {}
        if vector.exists():
            encoder = load_encoder_populations(vector)
            alignment = check_condition_alignment(
                meta["conditions"], encoder["form"]["timepoints"]
            )
            print()
            print("  A3·A4 조건 정합")
            print(f"    control 성분          {alignment['control_components'] or '없음'}")
            print(f"    집합 동일             {alignment['set_identical']}")
            print(f"    수열 동일 (저장 순서) {alignment['sequence_identical_as_stored']}")
            print(f"    수열 동일 (정렬 후)   {alignment['sequence_identical_after_sort']}")
            print(f"    재배열 필요           {alignment['reordering_required']}")
            print(f"    인코더 시점           {alignment['encoder_timepoints']}")

            eval_keys = {r["site_key"] for r in records if r["stratum"] == "S-EVAL"}
            all_keys = {r["site_key"] for r in records}
            print()
            print("  A5 모집단 교집합 (§2.1.2 집계 규칙별)")
            for level in ("form", "site"):
                normalized = encoder[level]["normalized_site_keys"]
                encoder_keys = set(normalized)
                both_all = encoder_keys & all_keys
                both_eval = encoder_keys & eval_keys
                multi = sum(1 for count in normalized.values() if count > 1)
                intersections[level] = {
                    "n_encoder_rows_eligible": encoder[level]["n_rows_eligible"],
                    "n_encoder_distinct_sites": len(encoder_keys),
                    "n_sites_with_multiple_forms": multi,
                    "n_nnls_diagnosed": len(all_keys),
                    "n_intersection_all_strata": len(both_all),
                    "n_intersection_s_eval": len(both_eval),
                    "s_eval_power_tier": power_tier(len(both_eval)),
                }
                print(
                    f"    {level:<5} 적격 행 {encoder[level]['n_rows_eligible']:>6}"
                    f" | 고유 site {len(encoder_keys):>6}"
                    f" | 다중 form site {multi:>5}"
                    f" | ∩전계층 {len(both_all):>5}"
                    f" | ∩S-EVAL {len(both_eval):>5}"
                )
            print()
            for level in ("form", "site"):
                block = intersections[level]
                print(
                    f"    {level:<5} 최종 |S-EVAL ∩ 인코더| = {block['n_intersection_s_eval']}"
                    f"  →  {block['s_eval_power_tier']}"
                )
        else:
            print(f"  [경고] vector TSV 없음: {vector}")

        payload["orders"].append(
            {
                **meta,
                "strata_counts": counts,
                "n_diagnosed": len(records),
                "s_eval_power_tier": power_tier(n_eval),
                "encoder": {
                    level: {
                        key: value
                        for key, value in block.items()
                        if key != "normalized_site_keys"
                    }
                    for level, block in encoder.items()
                },
                "condition_alignment": alignment,
                "intersections": intersections,
                "sites": records,
            }
        )

    if args.l3_fixture_dir:
        fixture_dir = Path(args.l3_fixture_dir)
        pooled = strata_from_fixture(fixture_dir)
        counts: Dict[str, int] = {}
        for record in pooled:
            counts[record["stratum"]] = counts.get(record["stratum"], 0) + 1
        total = max(len(pooled), 1)

        print("-" * 88)
        print(f"L3 pool — 동결 fixture {fixture_dir}")
        by_order: Dict[str, Dict[str, int]] = {}
        for record in pooled:
            block = by_order.setdefault(record["order_code"], {})
            block[record["stratum"]] = block.get(record["stratum"], 0) + 1
        print(f"  오더 {len(by_order)} | site {len(pooled)}")
        print()
        print("  계층 (배타적. §3.1 순서대로 적용)")
        for stratum in ("S-DEAD", "S-NOFIT", "S-RANK1", "S-EVAL"):
            n = counts.get(stratum, 0)
            print(f"    {stratum:<9} {n:>6}  {n / total * 100:>6.2f}%")
        n_eval_pool = counts.get("S-EVAL", 0)
        print()
        print(f"  |S-EVAL| (adapter 전) = {n_eval_pool}  →  {power_tier(n_eval_pool)}")
        print()
        print("  오더별 S-EVAL")
        for code in sorted(by_order):
            block = by_order[code]
            n_sites = sum(block.values())
            print(
                f"    {code[:52]:<52} {block.get('S-EVAL', 0):>5} / {n_sites:>5}"
                f"  ({block.get('S-EVAL', 0) / max(n_sites, 1) * 100:>5.1f}%)"
            )

        # adapter 교집합: 오더별 인코더 적격 site 와 교차한다.
        eval_by_order: Dict[str, set] = {}
        all_by_order: Dict[str, set] = {}
        ptm_by_order: Dict[str, str] = {}
        for record in pooled:
            code = record["order_code"]
            ptm_by_order[code] = record["ptm_type"]
            all_by_order.setdefault(code, set()).add(record["site_key"])
            if record["stratum"] == "S-EVAL":
                eval_by_order.setdefault(code, set()).add(record["site_key"])

        pooled_intersection: Dict[str, Dict[str, int]] = {"form": {}, "site": {}}
        missing_vectors: List[str] = []
        print()
        print("  A5 오더별 adapter 교집합")
        for code in sorted(all_by_order):
            suffix = (
                "_phospho" if ptm_by_order.get(code) == "phosphorylation" else "_ubi"
            )
            vector = output_root / code / f"ptm_vector_data_normalized{suffix}.tsv"
            if not vector.exists():
                missing_vectors.append(code)
                print(f"    {code[:52]:<52} [vector TSV 없음]")
                continue
            populations = load_encoder_populations(vector)
            line = f"    {code[:52]:<52}"
            for level in ("form", "site"):
                encoder_keys = set(populations[level]["normalized_site_keys"])
                n_all = len(encoder_keys & all_by_order[code])
                n_eval = len(encoder_keys & eval_by_order.get(code, set()))
                block = pooled_intersection[level]
                block["n_all"] = block.get("n_all", 0) + n_all
                block["n_eval"] = block.get("n_eval", 0) + n_eval
                line += f"  {level} ∩전계층 {n_all:>5} ∩S-EVAL {n_eval:>4}"
            print(line)

        print()
        for level in ("form", "site"):
            block = pooled_intersection[level]
            n_eval = block.get("n_eval", 0)
            print(
                f"    {level:<5} L3 |S-EVAL ∩ 인코더| = {n_eval}"
                f"  (전계층 {block.get('n_all', 0)})  →  {power_tier(n_eval)}"
            )
        if missing_vectors:
            print()
            print(f"    [경고] vector TSV 없어 교집합에서 빠진 오더: {missing_vectors}")

        payload["l3_pool"] = {
            "fixture_dir": str(fixture_dir),
            "n_orders": len(by_order),
            "n_sites": len(pooled),
            "strata_counts": counts,
            "s_eval_before_adapter": n_eval_pool,
            "by_order": by_order,
            "intersections": {
                level: {
                    **block,
                    "s_eval_power_tier": power_tier(block.get("n_eval", 0)),
                }
                for level, block in pooled_intersection.items()
            },
            "orders_missing_vector": missing_vectors,
            "sites": pooled,
        }

    print()
    print("=" * 88)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"기록 → {path}")
    else:
        skip = {"orders", "l3_pool"}
        print(json.dumps({k: v for k, v in payload.items() if k not in skip}, ensure_ascii=False))
        for entry in payload["orders"]:
            print(
                json.dumps(
                    {k: v for k, v in entry.items() if k != "sites"}, ensure_ascii=False
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
