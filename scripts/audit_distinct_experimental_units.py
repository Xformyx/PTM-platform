"""distinct 실험 단위 감사의 실행 드라이버.

구현 대상: docs/integrated_research_design_v2.md §11.1.1 (규칙) → §11.1.2 (결과)
사전등록: 규칙 2026-08-22 선언, 측정 착수 전. 판정 로직은 `ptm_shared/dataset_units.py`
          에 있고 이 파일은 출력 형식만 담당한다 — 로직을 여기에 두면 회귀 테스트가
          scripts/ 를 import 해야 하고 컨테이너 PYTHONPATH 에 그 경로가 없다.
해석 한계·주장 금지: `ptm_shared/dataset_units.py` 의 docstring 과 동일하다.

실행:

    python3 scripts/audit_distinct_experimental_units.py \
        --inputs-dir data/inputs \
        --out docs/results/dataset_audit/distinct_units_v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path[:0] = ["/app", "/opt", str(Path(__file__).resolve().parent.parent)]

from ptm_shared.dataset_units import build_report  # noqa: E402

DEFAULT_INPUTS_DIR = Path("data/inputs")
DEFAULT_AUDIT_FIXTURE_DIR = Path("workers/tests/fixtures/tmm_audit_v1")


def format_text(report: Dict) -> str:
    lines: List[str] = []
    lines.append("distinct 실험 단위 감사 — §11.1.1 규칙")
    lines.append(f"  규칙 선언        {report['rule_declared']}")
    lines.append(f"  디렉터리 훑음     {report['n_directories_scanned']}")
    lines.append(f"  범위 내          {report['n_directories_in_scope']}")
    lines.append(f"  고유 원자료 수    {report['n_distinct_raw_runs']}")
    lines.append(
        f"  디렉터리 합산 run {report['n_raw_runs_summed_over_directories']}"
    )
    lines.append(f"  distinct 실험 단위 {report['n_distinct_experimental_units']}")
    lines.append("")

    for index, component in enumerate(report["components"], start=1):
        lines.append(
            f"[단위 {index:02d}] {component['relation']}  "
            f"디렉터리 {component['n_directories']}  "
            f"원자료 {component['n_raw_runs_union']}"
        )
        for member in component["members"]:
            lines.append(
                f"    {member}  (runs={component['run_set_sizes'][member]})"
            )
        for prefix in component["acquisition_prefixes"]:
            lines.append(f"    획득경로: {prefix}")
        lines.append("")

    sensitivity = report["sensitivity_acquisition_prefix"]
    lines.append(
        f"민감도(획득 경로로 묶을 때, 판정 아님): "
        f"{sensitivity['n_units_by_acquisition_prefix']} 단위"
    )
    for members in sensitivity["components"]:
        if len(members) > 1:
            lines.append(f"    병합됨: {', '.join(members)}")
    lines.append("")

    crossref = report["audited_order_crossref"]
    if crossref["orders"]:
        lines.append(
            f"Chapter 2 감사 오더 {crossref['n_orders']}건 → "
            f"획득 {crossref['n_distinct_units_spanned']}개"
        )
        for order in crossref["orders"]:
            flag = "" if order["directory_in_scope"] else "  [범위 외]"
            lines.append(
                f"    order {order['order_id']:03d}  단위 {order['unit']}  "
                f"{order['directory']}{flag}"
            )
        lines.append("")

    if report["out_of_scope"]:
        lines.append("범위 외:")
        for item in report["out_of_scope"]:
            lines.append(f"    {item['directory']}  {item['reason']}")
        lines.append("")

    integrity = report["integrity"]
    lines.append("정합성:")
    lines.append(
        f"    pg/pr run 집합 불일치      {integrity['pg_run_set_mismatch'] or '없음'}"
    )
    lines.append(
        f"    run 컬럼 중복 보유 디렉터리 "
        f"{integrity['directories_with_duplicate_run_columns'] or '없음'}"
    )
    lines.append(
        f"    경로 아닌 run 영역 컬럼      {integrity['run_column_anomalies'] or '없음'}"
    )
    lines.append(
        f"    precursor matrix 복수 보유   "
        f"{integrity['directories_with_multiple_precursor_matrices'] or '없음'}"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS_DIR)
    parser.add_argument(
        "--audit-fixture-dir", type=Path, default=DEFAULT_AUDIT_FIXTURE_DIR
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    report = build_report(args.inputs_dir, args.audit_fixture_dir)
    print(format_text(report))

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\n기록: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
