"""내부 데이터셋의 distinct 실험 단위를 원자료 공유 그래프의 연결 성분으로 센다.

구현 대상: docs/integrated_research_design_v2.md §11.1.1 (동치 규칙)
사전등록: 규칙 2026-08-22 선언, 측정 착수 전. §11.1.1 의 "측정 전 선언" 표시가 그것이다.
          본 모듈은 그 규칙을 그대로 집행하며 판정 기준을 하나도 추가하지 않는다.
해석 한계: 이 수는 **감사의 폭**이다. 획득이 하나라는 것이 생물학적 독립성이 하나라는 뜻이
          아니다. 같은 세포주·배치에서 나온 별개 획득은 별개 단위로 세어지며 그 상관은
          보정하지 않는다. sha256 과 획득 경로 prefix 는 기술 통계이며 판정에 쓰이지 않는다.
주장 금지: 이 수로 표본 크기나 검정력을 논하지 않는다(모집단 정의는 `c1_prereg_v1.md` §6,
          `c3_prereg_v1.md` §9). 적격 판정(§11.1 교란 정의)은 이 수와 무관하다 —
          적격 0건은 단위를 어떻게 세든 0건이다.

결정성: 순수 파일 읽기. 난수·솔버·부동소수 연산 없음. 경로 문자열 비교만 사용하며 정규화를
        하지 않는다(§11.1.1: 정규화 규칙 자체가 판정을 흔들기 때문). 정점 순서를 디렉터리명
        정렬로 고정하고 union-find 의 대표를 최소 이름으로 잡아 출력이 실행 간 동일하다.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, FrozenSet, List, Sequence, Tuple

MATRIX_SCAN_PATTERN = re.compile(r"(pr_matrix|pg_matrix|report)", re.IGNORECASE)
"""§11.1 audit_scope 의 matrix 판정 정규식.

docs/integrated_research_design_v2.md §11.1 에서 2026-08-20 선언(v2 감사).
이 모듈은 그 범위를 재정의하지 않고 그대로 적용한다. 변경하면 §11.1 의
`n_with_quantitative_matrix = 20` 과 어긋난다.
"""

PRIMARY_MATRIX_GLOB = "report.pr_matrix*.tsv"
"""단위 식별자를 읽는 파일의 glob.

§11.1.1 에서 2026-08-22 선언. run 컬럼명이 획득 파일 전체 경로인 precursor 수준 matrix 다.
`*` 가 필요한 이유: `Microgravity_Muscle_Atrophy_Phosphoproteomics` 는
`report.pr_matrix_phospho.tsv` 로 저장돼 있다. 고정 파일명으로 잡으면 감사 대상 오더 45 가
조용히 빠진다. `pg_matrix` 는 동일 run 집합을 가져야 하며 그 일치는 검증만 하고 판정에 쓰지 않는다.
"""

SECONDARY_MATRIX_GLOB = "report.pg_matrix*.tsv"

PATH_SEPARATORS = ("\\", "/")
"""run 컬럼 판별의 구조적 근거.

§11.1.1 의 식별자는 **획득 파일 전체 경로**다. 따라서 run 컬럼은 경로 구분자를 포함하고
DIA-NN 메타데이터 컬럼명(`Protein.Group`, `N.Sequences` 등)은 포함하지 않는다.
확장자 화이트리스트(`.mzML`/`.raw`/`.d`)를 쓰지 않는 이유는 그 목록이 자체로 판정 규칙이 되어
§11.1.1 에 선언되지 않은 기준을 들여오기 때문이다. 구분자 미포함 컬럼이 run 영역에 섞여 있으면
버리지 않고 `integrity` 에 보고한다.
"""

AUDIT_FIXTURE_ORDER_PATTERN = re.compile(r"^order_(\d+)_(?P<directory>.+)\.json$")


def split_header(columns: Sequence[str]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """헤더를 (선행 메타데이터, run 영역)로 자른다.

    경로 구분자를 포함한 첫 컬럼부터 run 영역이다. run 영역 안에서 구분자가 없는 컬럼은
    **버리지 않고 그대로 돌려준다** — 호출자가 정합성 위반으로 보고한다.
    """
    for index, column in enumerate(columns):
        if any(separator in column for separator in PATH_SEPARATORS):
            return tuple(columns[:index]), tuple(columns[index:])
    return tuple(columns), ()


def read_header(matrix_path: Path) -> Tuple[str, ...]:
    with matrix_path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
        header = handle.readline()
    return tuple(header.rstrip("\r\n").split("\t"))


def read_run_columns(matrix_path: Path) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """matrix 헤더의 run 컬럼과 그중 경로 구분자가 없는 이상 컬럼을 돌려준다."""
    _, run_region = split_header(read_header(matrix_path))
    anomalies = tuple(
        column
        for column in run_region
        if not any(separator in column for separator in PATH_SEPARATORS)
    )
    return run_region, anomalies


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquisition_prefix(run_path: str) -> str:
    """획득 파일 경로에서 디렉터리 부분. **기술 통계 전용이며 판정에 쓰지 않는다.**"""
    for separator in PATH_SEPARATORS:
        if separator in run_path:
            return run_path.rsplit(separator, 1)[0]
    return ""


def connected_components(run_sets: Dict[str, FrozenSet[str]]) -> List[List[str]]:
    """원자료 공유(교집합 비공백)를 간선으로 한 연결 성분.

    §11.1.1 의 동치 규칙 그대로다. 연결 성분이므로 추이성은 구성상 보장되고
    병합 순서에 의존하지 않는다. 공집합은 어떤 것과도 교집합이 없으므로 단독 성분이 된다.
    """
    names = sorted(run_sets)
    parent = {name: name for name in names}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if run_sets[left] & run_sets[right]:
                union(left, right)

    grouped: Dict[str, List[str]] = {}
    for name in names:
        grouped.setdefault(find(name), []).append(name)
    return [grouped[key] for key in sorted(grouped)]


def scan_directories(inputs_dir: Path) -> Tuple[List[Dict], List[Dict]]:
    """정량 matrix 보유 디렉터리를 훑어 run 집합을 수집한다.

    돌려주는 두 목록은 (범위 내, 범위 외) 다. 범위 외 사유를 버리지 않는다 —
    §11.1 의 `rag/` 제외처럼 사유가 감사 기록의 일부다.
    """
    in_scope: List[Dict] = []
    out_of_scope: List[Dict] = []

    for directory in sorted(p for p in inputs_dir.iterdir() if p.is_dir()):
        matrix_files = sorted(
            child.name
            for child in directory.iterdir()
            if child.is_file() and MATRIX_SCAN_PATTERN.search(child.name)
        )
        if not matrix_files:
            out_of_scope.append(
                {"directory": directory.name, "reason": "no_quantitative_matrix"}
            )
            continue

        primary_candidates = sorted(directory.glob(PRIMARY_MATRIX_GLOB))
        if not primary_candidates:
            out_of_scope.append(
                {
                    "directory": directory.name,
                    "reason": "precursor_matrix_absent",
                    "matrix_files": matrix_files,
                }
            )
            continue
        primary = primary_candidates[0]

        runs, run_anomalies = read_run_columns(primary)
        record = {
            "directory": directory.name,
            "primary_matrix": primary.name,
            "matrix_files": matrix_files,
            "n_runs": len(runs),
            "runs": list(runs),
            "n_runs_distinct": len(set(runs)),
            "run_column_anomalies": list(run_anomalies),
            "n_primary_matrix_candidates": len(primary_candidates),
            "acquisition_prefixes": sorted({acquisition_prefix(r) for r in runs}),
            "sha256": {name: sha256_of(directory / name) for name in matrix_files},
        }

        secondary_candidates = sorted(directory.glob(SECONDARY_MATRIX_GLOB))
        if secondary_candidates:
            pg_runs, _ = read_run_columns(secondary_candidates[0])
            record["pg_run_set_matches_pr"] = set(pg_runs) == set(runs)
        else:
            record["pg_run_set_matches_pr"] = None

        in_scope.append(record)

    return in_scope, out_of_scope


def describe_component(members: Sequence[str], records: Dict[str, Dict]) -> Dict:
    """한 실험 단위의 구성을 기술한다. 판정은 이미 끝났고 여기서는 설명만 한다."""
    run_sets = {name: frozenset(records[name]["runs"]) for name in members}
    union_runs: FrozenSet[str] = frozenset().union(*run_sets.values())

    identical_run_sets = len({run_sets[name] for name in members}) == 1

    primary_hashes = {
        records[name]["sha256"].get(records[name]["primary_matrix"]) for name in members
    }
    byte_identical = len(primary_hashes) == 1 and None not in primary_hashes

    if len(members) == 1:
        relation = "single_directory"
    elif identical_run_sets and byte_identical:
        relation = "byte_identical_rerun"
    elif identical_run_sets:
        relation = "same_acquisition_reprocessed"
    else:
        relation = "condition_split_or_subset"

    return {
        "members": list(members),
        "n_directories": len(members),
        "n_raw_runs_union": len(union_runs),
        "run_set_sizes": {name: len(run_sets[name]) for name in members},
        "identical_run_sets": identical_run_sets,
        "primary_matrix_byte_identical": byte_identical,
        "relation": relation,
        "acquisition_prefixes": sorted(
            {acquisition_prefix(run) for run in union_runs}
        ),
    }


def prefix_sensitivity(records: Dict[str, Dict]) -> Dict:
    """획득 디렉터리 경로로 묶으면 몇 개가 되는지. **기술 통계이며 판정이 아니다.**

    §11.1.1 은 경로 prefix 를 판정에서 명시적으로 배제했다(한 폴더에 여러 실험을 담을 수 있고
    한 실험을 여러 폴더로 나눌 수 있다). 그래도 병기하는 이유는 선언된 규칙이 배치 상관을
    보정하지 않음을 독자가 볼 수 있어야 하기 때문이다. 이 수를 supplement 의 단위 수로 쓰지 않는다.
    """
    prefix_sets = {
        name: frozenset(rec["acquisition_prefixes"]) for name, rec in records.items()
    }
    components = connected_components(prefix_sets)
    return {
        "n_units_by_acquisition_prefix": len(components),
        "components": [sorted(members) for members in components],
        "is_declared_rule": False,
    }


def audited_order_crossref(
    records: Dict[str, Dict], components: Sequence[Sequence[str]], fixture_dir: Path
) -> Dict:
    """Chapter 2 감사 오더가 몇 개의 획득에 걸쳐 있는지.

    오더 → 디렉터리 대응은 동결 fixture 파일명(`order_NNN_<directory>.json`)에서 읽는다.
    감사 표(`chapter2_audit_protocol_v1.md` §3)가 "6 오더"로 통합하므로 그 6이 몇 개의
    독립 획득인지가 pooling 서술에 필요하다.
    """
    unit_of = {
        member: index
        for index, members in enumerate(components, start=1)
        for member in members
    }
    orders: List[Dict] = []
    if fixture_dir.is_dir():
        for path in sorted(fixture_dir.glob("order_*.json")):
            match = AUDIT_FIXTURE_ORDER_PATTERN.match(path.name)
            if match is None:
                continue
            directory = match.group("directory")
            orders.append(
                {
                    "order_id": int(match.group(1)),
                    "directory": directory,
                    "unit": unit_of.get(directory),
                    "directory_in_scope": directory in records,
                }
            )
    units = sorted({o["unit"] for o in orders if o["unit"] is not None})
    return {
        "fixture_dir": str(fixture_dir),
        "orders": orders,
        "n_orders": len(orders),
        "n_distinct_units_spanned": len(units),
        "units_spanned": units,
    }


def build_report(inputs_dir: Path, audit_fixture_dir: Path) -> Dict:
    """§11.1.1 규칙을 집행하고 §11.1.2 가 인용하는 레코드를 만든다."""
    in_scope, out_of_scope = scan_directories(inputs_dir)
    records = {record["directory"]: record for record in in_scope}
    run_sets = {name: frozenset(rec["runs"]) for name, rec in records.items()}

    components = connected_components(run_sets)
    described = [describe_component(members, records) for members in components]

    all_runs: FrozenSet[str] = (
        frozenset().union(*run_sets.values()) if run_sets else frozenset()
    )

    return {
        "rule_source": "docs/integrated_research_design_v2.md §11.1.1",
        "rule_declared": "2026-08-22 (측정 착수 전)",
        "unit_definition": (
            "raw MS acquisition; directories sharing >=1 raw run path are one unit"
        ),
        "inputs_dir": str(inputs_dir),
        "n_directories_scanned": len(in_scope) + len(out_of_scope),
        "n_directories_in_scope": len(in_scope),
        "n_distinct_experimental_units": len(components),
        "n_distinct_raw_runs": len(all_runs),
        "n_raw_runs_summed_over_directories": sum(
            rec["n_runs"] for rec in records.values()
        ),
        "components": described,
        "sensitivity_acquisition_prefix": prefix_sensitivity(records),
        "audited_order_crossref": audited_order_crossref(
            records, components, audit_fixture_dir
        ),
        "out_of_scope": out_of_scope,
        "integrity": {
            "pg_run_set_mismatch": sorted(
                name
                for name, rec in records.items()
                if rec["pg_run_set_matches_pr"] is False
            ),
            "directories_with_duplicate_run_columns": sorted(
                name
                for name, rec in records.items()
                if rec["n_runs"] != rec["n_runs_distinct"]
            ),
            "run_column_anomalies": {
                name: rec["run_column_anomalies"]
                for name, rec in records.items()
                if rec["run_column_anomalies"]
            },
            "directories_with_multiple_precursor_matrices": {
                name: rec["n_primary_matrix_candidates"]
                for name, rec in records.items()
                if rec["n_primary_matrix_candidates"] > 1
            },
        },
        "per_directory": [
            {
                "directory": rec["directory"],
                "primary_matrix": rec["primary_matrix"],
                "n_runs": rec["n_runs"],
                "matrix_files": rec["matrix_files"],
                "sha256": rec["sha256"],
                "acquisition_prefixes": rec["acquisition_prefixes"],
            }
            for rec in in_scope
        ],
    }
