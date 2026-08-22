"""E1 — τ 기본 측정. C1 의 주 산출물.

구현 대상: docs/c1_prereg_v1.md §5 (E1 출력·요약), §4 (τ 정의), §2.1.1 (adapter A1–A6),
          §2.1.4 (baseline·처리 arm), §3.5.1 (강등 후 E1 의 지위)
사전등록: 판정 규칙은 2026-08-20 동결, 선행 확인 2026-08-22 완료, §3.5 분기 (i)+(iii) 2026-08-22
          확정. **이 스크립트가 τ 를 처음 산정한다.** 어떤 임계도 새로 도입하지 않으며 모든
          규칙은 `ptm_shared/c1_transmissibility.py` 의 인용된 상수를 쓴다.
해석 한계: E1 의 성공은 "τ 가 낮다"가 아니라 **"τ 가 provenance 와 함께 계산되고 계층별로
          분해된다"**다(§5.3). 여기서 C1 의 참/거짓이 결정되지 않는다.
          τ 는 **반사실 섭동**의 전달성이며 production 변화가 아니다(§2.2).
          τ 에는 (1) 궤적 변화, (2) 대입 채움(§2.1.3), (3) form 집계 차이(§2.1.4.2)가 섞여 있고
          분리되지 않는다.
주장 금지: 이 값으로 kinase 귀속 정확도를 논하지 않는다. "τ 가 낮으므로 표현 학습이 무용하다"고
          쓰지 않는다 — 퇴화는 하류 사전의 성질이다. E3 미평가를 "예측 실패"로 쓰지 않는다(§3.5.1).

정본 환경(설계행렬 조립에 필요한 참조 kinase 표와 scipy 가 있는 API 컨테이너):

    docker exec -i ptm-api-server env PYTHONPATH=/app:/opt PYTHONHASHSEED=0 python - \
        --order-ids 52 --l3-fixture-dir /app/tests/fixtures/tmm_audit_v1 \
        --output /app/data/outputs/_diagnostics/c1_e1_v1/tau.json < scripts/run_c1_e1_transmissibility.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

sys.path[:0] = ["/app", "/opt", "/app/scripts"]

from ptm_shared.c1_transmissibility import (  # noqa: E402
    STATUS_EVALUATED,
    SiteTransmissibility,
    primary_tau_field,
    provenance as tau_provenance,
    quantile_summary,
    site_transmissibility,
    summarize_by_stratum,
)
from ptm_shared.tmm_audit import SiteInputs, solver_provenance  # noqa: E402

ENCODER_SEED = 0
"""τ 산정용 인코더 seed. docs/c1_prereg_v1.md §2.1.4 `TAU_TREATMENT_ARM_V1` 에서 2026-08-22 선언.

단일 seed 인 이유: τ 는 **판정에 쓰이지 않는 기술 통계**로 강등되었다(§3.5.1). C2 의 gate 처럼
단일 seed 로 통과/실패를 가르지 않으므로 다중 seed 요건이 적용되지 않는다. 대신 seed 의존성을
§9 의 미결 항목으로 남긴다.
"""

ARM_TREATMENT = "D"
"""처리 arm. docs/c1_prereg_v1.md §2.1.4 `TAU_TREATMENT_ARM_V1`.

`ptm_shared/representation/layers.py` 의 variant D = `learned_temporal_representation`
(Track 2 only). 설계 v2 §11 이 C0/C2/C3 의 primary arm 을 D 로 정했으므로 장 간 비교를 위해
C1 도 D 를 쓴다.
"""


def normalize_site_key(gene: str, position: str) -> str:
    """`TAU_ALIGNMENT_ADAPTER_V1` A1 의 정규형. `measure_c1_strata.py` 와 동일 규칙."""
    return f"{str(gene).strip().upper()}_{str(position).strip().upper()}"


def gene_of(site_key: str) -> str:
    """유전자 블록 라벨. docs/c1_prereg_v1.md §7.2 (블록 단위 = 유전자).

    해석 한계: `GENE_POSITION` 정규형의 마지막 밑줄 앞부분을 유전자로 본다. gene 별칭은
              해결하지 않는다(A1 과 같은 한계).
    """
    head = str(site_key).rsplit("_", 1)
    return head[0] if len(head) == 2 else str(site_key)


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


def fit_site_level_encoder(vector_path: Path) -> Dict[str, Any]:
    """arm D 를 site 수준으로 적합하고 site 별 재구성을 돌려준다.

    구현 대상: docs/c1_prereg_v1.md §2.1.2 (A2 = SITE_LEVEL_ENCODER_V1), §2.1.4 (처리 arm 설정)
    해석 한계: 재구성은 **미관측 시점에도 값을 낸다.** 그것이 §2.1.3 의 비대칭이며 여기서
              보정하지 않는다.
    주장 금지: 재구성을 "복원된 참값"으로 서술하지 않는다. 자기지도 학습의 출력이다.
    """
    import pandas as pd

    from ptm_shared.representation import build_multiview_input
    from ptm_shared.representation.encoder import fit_masked_temporal_encoder
    from ptm_shared.representation.layers import resolve_variant

    frame = pd.read_csv(vector_path, sep="\t", low_memory=False)
    multiview = build_multiview_input(
        frame.to_dict("records"),
        config={"key_level": "site", "minimum_observed_timepoints": 3},
    )
    eligible = multiview.eligible_subset()

    arm = resolve_variant(ARM_TREATMENT)
    result = fit_masked_temporal_encoder(
        eligible,
        config={**dict(arm.encoder_options or {}), "seed": ENCODER_SEED},
    )

    observed = eligible.target.observed
    inputs = eligible.target.filled(0.0)
    by_site: Dict[str, Dict[str, Any]] = {}
    for row, key in enumerate(result.site_keys):
        meta = eligible.site_metadata.get(key, {})
        gene = meta.get("gene") or meta.get("Gene.Name") or ""
        position = meta.get("position") or meta.get("PTM_Position") or ""
        if not gene or not position:
            parts = str(key).split("|", 1)[0].rsplit(" ", 1)
            if len(parts) != 2:
                continue
            gene, position = parts
        by_site[normalize_site_key(gene, position)] = {
            "reconstruction": result.reconstruction[row],
            "encoder_input": inputs[row],
            "observed": observed[row],
        }

    return {
        "timepoints": list(eligible.timepoints),
        "by_site": by_site,
        "n_rows": int(eligible.n_sites),
        "n_distinct_sites": len(by_site),
        "encoder_provenance": {
            key: result.provenance.get(key)
            for key in ("encoder_version", "config_sha256", "views", "time_order")
        },
        "heldout_reconstruction_error": result.heldout_reconstruction_error,
        "train_reconstruction_error": result.train_reconstruction_error,
    }


def build_direction(
    site: SiteInputs,
    conditions: Sequence[str],
    encoder_timepoints: Sequence[str],
    block: Mapping[str, Any],
) -> Tuple[np.ndarray, np.ndarray, float, int]:
    """`d_full`, NNLS 조건 기준 관측 마스크, A6 집계 불일치, 인코더에 없는 조건 수.

    구현 대상: docs/c1_prereg_v1.md §2.1.4 (`d` 정의), §2.1.1 A3·A4 (조건 정합), §2.1.4.2 (A6)
    해석 한계: 인코더에 없는 조건(control 등)에서 `d = 0` 이다. 표현이 그 조건을 바꾸지 않는다는
              뜻이며 "변화가 없음을 관측했다"가 아니다.
    """
    index_of = {str(label): position for position, label in enumerate(encoder_timepoints)}
    reconstruction = np.asarray(block["reconstruction"], dtype=float)
    encoder_input = np.asarray(block["encoder_input"], dtype=float)
    encoder_observed = np.asarray(block["observed"], dtype=bool)

    n_time = len(conditions)
    direction = np.zeros(n_time, dtype=float)
    observed = np.zeros(n_time, dtype=bool)
    mismatch = np.zeros(n_time, dtype=float)
    n_absent = 0
    for position, condition in enumerate(conditions):
        column = index_of.get(str(condition))
        if column is None:
            n_absent += 1
            continue
        direction[position] = reconstruction[column] - site.target[position]
        observed[position] = bool(encoder_observed[column]) and bool(
            site.observed_mask[position]
        )
        if observed[position]:
            mismatch[position] = encoder_input[column] - site.target[position]

    return direction, observed, float(np.linalg.norm(mismatch)), n_absent


PROVENANCE_FIELDS = (
    "design_rank",
    "design_condition_number",
    "max_column_coherence",
    "n_redundant",
    "relative_residual",
    "verdict",
    "active_condition_number",
    "active_sigma_min",
    "structurally_underdetermined",
    "equal_weight_fallback",
    "prior_column_fraction",
    "top1_from_prior",
)
"""docs/c1_prereg_v1.md §5.1 이 E1 레코드에 요구하는 진단 provenance.

**재구현 금지, 재사용** (§1). `classify_strata` 가 이미 `diagnose_site` 를 호출하므로 그 출력을
그대로 합친다. τ 모듈이 자체 계산하는 `n_active`·`active_rank` 는 여기서 덮어쓰지 않는다 —
두 경로가 일치하는지 확인하는 것이 §4.3 의 감사 항목이다.
"""


def measure_order(
    site_inputs: Sequence[SiteInputs],
    strata: Mapping[str, Mapping[str, Any]],
    conditions: Sequence[str],
    encoder: Mapping[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """한 오더의 τ 레코드. adapter 교집합 밖의 site 는 조용히 버리지 않고 계수한다."""
    by_site = encoder["by_site"]
    timepoints = encoder["timepoints"]
    records: List[Dict[str, Any]] = []
    n_outside_adapter = 0
    n_absent_conditions = 0

    for site in site_inputs:
        block = by_site.get(site.site_key)
        if block is None:
            n_outside_adapter += 1
            continue
        direction, observed, mismatch, n_absent = build_direction(
            site, conditions, timepoints, block
        )
        n_absent_conditions = max(n_absent_conditions, n_absent)
        record: SiteTransmissibility = site_transmissibility(
            site.site_key,
            site.design,
            site.target,
            direction,
            observed_mask=observed,
            prior_flags=site.prior_flags,
            gene=gene_of(site.site_key),
        )
        payload = record.to_dict()
        diagnosis = strata.get(site.site_key) or {}
        payload["stratum"] = str(diagnosis.get("stratum") or "UNCLASSIFIED")
        for field in PROVENANCE_FIELDS:
            payload[field] = diagnosis.get(field)
        payload["n_active_from_diagnosis"] = diagnosis.get("n_active")
        payload["active_rank_from_diagnosis"] = diagnosis.get("active_rank")
        payload["agg_mismatch_norm"] = mismatch
        payload["n_conditions_absent_from_encoder"] = n_absent
        records.append(payload)

    meta = {
        "n_sites_in_adapter": len(records),
        "n_sites_outside_adapter": n_outside_adapter,
        "n_conditions_absent_from_encoder": n_absent_conditions,
        "encoder_rows": encoder["n_rows"],
        "encoder_distinct_sites": encoder["n_distinct_sites"],
        "encoder_provenance": encoder["encoder_provenance"],
        "heldout_reconstruction_error": encoder["heldout_reconstruction_error"],
        "train_reconstruction_error": encoder["train_reconstruction_error"],
    }
    return records, meta


def a6_summary(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """A6 집계 불일치의 크기. docs/c1_prereg_v1.md §2.1.4.2.

    해석 한계: 판정에 쓰지 않는 기술 통계다. 임계가 없다.
    """
    evaluated = [r for r in records if r.get("status") == STATUS_EVALUATED]
    ratios = [
        float(r["agg_mismatch_norm"]) / float(r["d_norm_observed_only"])
        for r in evaluated
        if float(r.get("d_norm_observed_only") or 0.0) > 1e-12
    ]
    return {
        "agg_mismatch_norm": quantile_summary(
            [r.get("agg_mismatch_norm") for r in evaluated]
        ),
        "ratio_to_d_observed": quantile_summary(ratios),
        "n_sites_with_any_mismatch": sum(
            1 for r in evaluated if float(r.get("agg_mismatch_norm") or 0.0) > 1e-12
        ),
        "n_evaluated": len(evaluated),
    }


def consistency_audit(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """§4.3 이 명령한 두 일치 확인. 불일치는 숨기지 않고 개수를 보고한다.

    구현 대상: docs/c1_prereg_v1.md §4.3
              ("n_active = 0 → S-DEAD 로 분류. equal_weight_fallback 과 일치해야 함. 불일치 시 보고")
    해석 한계: 불일치가 0 이 아니면 τ 모듈과 배포 진단이 활성집합을 다르게 본다는 뜻이며,
              그 경우 τ_act 의 해석이 배포 추정기와 어긋난다.
    """
    dead_mismatch = [
        r["site_key"]
        for r in records
        if bool(r.get("equal_weight_fallback")) != (int(r.get("n_active") or 0) == 0)
    ]
    active_mismatch = [
        r["site_key"]
        for r in records
        if r.get("n_active_from_diagnosis") is not None
        and int(r["n_active_from_diagnosis"]) != int(r.get("n_active") or 0)
    ]
    out_of_range = [
        r["site_key"]
        for r in records
        for value in (r.get("tau_act"), r.get("tau_col"))
        if value is not None and not (-1e-9 <= float(value) <= 1.0 + 1e-9)
    ]
    return {
        "n_dead_flag_mismatch": len(dead_mismatch),
        "dead_flag_mismatch_examples": dead_mismatch[:5],
        "n_active_set_mismatch": len(active_mismatch),
        "active_set_mismatch_examples": active_mismatch[:5],
        "n_tau_out_of_unit_range": len(set(out_of_range)),
        "tau_out_of_range_examples": sorted(set(out_of_range))[:5],
    }


def print_stratum_table(summary: Mapping[str, Any]) -> None:
    order = ("S-DEAD", "S-NOFIT", "S-RANK1", "S-EVAL", "UNCLASSIFIED")
    print(
        f"    {'계층':<13} {'site':>6} {'평가':>6} "
        f"{'τ_act p10':>10} {'p50':>8} {'p90':>8} "
        f"{'τ_col p50':>10} {'τ_obs p50':>10} {'Δẑ p50':>9} {'불안정':>7}"
    )
    for stratum in order:
        block = summary.get(stratum)
        if not block:
            continue
        act = block["tau_act"]
        col = block["tau_col"]
        obs = block["tau_act_observed_only"]
        response = block["downstream_response"]
        unstable = block["active_unstable_fraction"]

        def show(value: Optional[float], width: int = 8) -> str:
            return f"{value:>{width}.4f}" if value is not None else f"{'—':>{width}}"

        print(
            f"    {stratum:<13} {block['n_sites']:>6} {block['n_evaluated']:>6} "
            f"{show(act['p10'], 10)} {show(act['p50'])} {show(act['p90'])} "
            f"{show(col['p50'], 10)} {show(obs['p50'], 10)} "
            f"{show(response['p50'], 9)} {show(unstable, 7)}"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-ids", default="52")
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument("--max-sites", type=int, default=4000)
    parser.add_argument("--l3-fixture-dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    output_root = Path(args.data_root) / "outputs"
    order_ids = [int(part) for part in str(args.order_ids).split(",") if part.strip()]

    print("=" * 108)
    print("E1 — τ 기본 측정 (docs/c1_prereg_v1.md §5)")
    print("기술 단계. 여기서 C1 의 참/거짓이 결정되지 않는다 (§5.3)")
    print("τ 는 반사실 섭동의 전달성이며 production 변화가 아니다 (§2.2)")
    print("=" * 108)
    print(f"solver     = {json.dumps(solver_provenance(), ensure_ascii=False)}")
    print(f"tau module = {json.dumps(tau_provenance(), ensure_ascii=False)}")
    print()

    from measure_c1_strata import (  # type: ignore
        assemble_site_inputs,
        classify_strata,
        strata_from_fixture,
    )

    payload: Dict[str, Any] = {
        "contract": "C1_E1_TRANSMISSIBILITY_V1",
        "measured_at": "2026-08-22",
        "prereg_branch": "(i) 강등 + (iii) 탐색적 7 오더 pool  (c1_prereg_v1.md §3.5.1)",
        "treatment_arm": ARM_TREATMENT,
        "encoder_seed": ENCODER_SEED,
        "solver": solver_provenance(),
        "tau_module": tau_provenance(),
        "orders": [],
    }
    pooled: List[Dict[str, Any]] = []

    def run_order(
        label: str,
        code: str,
        ptm_type: str,
        conditions: Sequence[str],
        site_inputs: Sequence[SiteInputs],
        strata: Mapping[str, Mapping[str, Any]],
    ) -> None:
        suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
        vector = output_root / code / f"ptm_vector_data_normalized{suffix}.tsv"
        if not vector.exists():
            print(f"[skip] {label}: vector TSV 없음 {vector}")
            return
        encoder = fit_site_level_encoder(vector)
        records, meta = measure_order(site_inputs, strata, conditions, encoder)
        for record in records:
            record["order_code"] = code
        pooled.extend(records)

        summary = summarize_by_stratum(records)
        print("-" * 108)
        print(f"{label} | {code} | {ptm_type}")
        print(
            f"  NNLS site {len(site_inputs)} | adapter 내 {meta['n_sites_in_adapter']}"
            f" | adapter 밖 {meta['n_sites_outside_adapter']}"
            f" | 인코더 고유 site {meta['encoder_distinct_sites']}"
            f" | 인코더에 없는 조건 {meta['n_conditions_absent_from_encoder']}"
        )
        print()
        print_stratum_table(summary)
        s_eval = summary.get("S-EVAL") or {}
        if s_eval:
            unstable = s_eval.get("active_unstable_fraction")
            print()
            print(
                f"  S-EVAL primary τ 필드 = {primary_tau_field(unstable)}"
                f"  (활성집합 불안정 비율 {unstable if unstable is None else round(unstable, 4)},"
                f" 승격 임계 0.30 — §4.2)"
            )
        mismatch = a6_summary(records)
        print(
            f"  A6 집계 불일치: 비영 site {mismatch['n_sites_with_any_mismatch']}"
            f" / {mismatch['n_evaluated']}"
            f" | ||mismatch|| p50 = {mismatch['agg_mismatch_norm']['p50']}"
            f" | ||d_obs|| 대비 p50 = {mismatch['ratio_to_d_observed']['p50']}"
        )
        payload["orders"].append(
            {
                "label": label,
                "order_code": code,
                "ptm_type": ptm_type,
                "conditions": list(conditions),
                **meta,
                "summary": summary,
                "a6": mismatch,
                "sites": records,
            }
        )

    for order_id in order_ids:
        order = asyncio.run(load_order(order_id))
        if order is None:
            print(f"[skip] order {order_id}: heatmap 없음")
            continue
        site_inputs, meta = assemble_site_inputs(
            order, output_root, max_sites=args.max_sites
        )
        strata = {record["site_key"]: record for record in classify_strata(site_inputs)}
        run_order(
            f"order {order_id} (live)",
            meta["order_code"],
            meta["ptm_type"],
            meta["conditions"],
            site_inputs,
            strata,
        )

    if args.l3_fixture_dir:
        from ptm_shared.tmm_audit import FIXTURE_SCHEMA, fixture_digest, thaw_site_inputs

        fixture_dir = Path(args.l3_fixture_dir)
        manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
        fixture_strata = {
            (record["order_code"], record["site_key"]): record
            for record in strata_from_fixture(fixture_dir)
        }
        for entry in manifest["orders"]:
            path = fixture_dir / entry["file"]
            block = json.loads(path.read_text(encoding="utf-8"))
            if block.get("schema") != FIXTURE_SCHEMA:
                raise ValueError(f"{path.name}: unexpected schema")
            if fixture_digest(path) != entry["sha256"]:
                raise ValueError(f"{path.name}: sha256 mismatch — fixture was modified")
            code = str(block["order_code"])
            run_order(
                f"L3 fixture order {block['order_id']}",
                code,
                str(block.get("ptm_type") or ""),
                [str(c) for c in block["conditions"]],
                thaw_site_inputs(block),
                {
                    site_key: record
                    for (order_code, site_key), record in fixture_strata.items()
                    if order_code == code
                },
            )

    if pooled:
        print("=" * 108)
        print("7 오더 pool 합산 (§3.5.2 탐색적 모집단). **탐색적. primary 승격 영구 금지**")
        pooled_summary = summarize_by_stratum(pooled)
        print()
        print_stratum_table(pooled_summary)
        s_eval = [r for r in pooled if r.get("stratum") == "S-EVAL"]
        evaluable = [r for r in s_eval if r.get("status") == STATUS_EVALUATED]
        print()
        print(
            f"  |S-EVAL ∩ adapter| = {len(s_eval)}  (τ 평가 가능 {len(evaluable)})"
            f"  | 사전 지정 하한 73 → {'미달' if len(evaluable) < 73 else '충족'}"
        )
        excluded: Dict[str, int] = {}
        for record in pooled:
            status = str(record.get("status"))
            if status != STATUS_EVALUATED:
                excluded[status] = excluded.get(status, 0) + 1
        print(f"  제외 사유별 개수 (§4.3): {excluded or '없음'}")
        audit = consistency_audit(pooled)
        print(
            f"  §4.3 일치 확인: S-DEAD 플래그 불일치 {audit['n_dead_flag_mismatch']}"
            f" | 활성집합 불일치 {audit['n_active_set_mismatch']}"
            f" | τ 단위구간 이탈 {audit['n_tau_out_of_unit_range']}"
        )
        s_eval_summary = pooled_summary.get("S-EVAL") or {}
        unstable = s_eval_summary.get("active_unstable_fraction")
        promoted = primary_tau_field(unstable)
        print(
            f"  pool S-EVAL primary τ 필드 = {promoted}"
            f"  (활성집합 불안정 비율 {None if unstable is None else round(unstable, 4)},"
            f" 승격 임계 0.30 — §4.2)"
        )
        payload["pool"] = {
            "n_sites": len(pooled),
            "summary": pooled_summary,
            "n_s_eval": len(s_eval),
            "n_s_eval_evaluable": len(evaluable),
            "excluded_counts": excluded,
            "a6": a6_summary(pooled),
            "consistency_audit": audit,
            "primary_tau_field": promoted,
            "status": "exploratory_only_never_primary",
        }

    print()
    print("=" * 108)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"기록 → {path}")
    else:
        trimmed = {
            key: value for key, value in payload.items() if key not in {"orders", "pool"}
        }
        print(json.dumps(trimmed, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
