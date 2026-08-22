"""Regression tests locking the distinct experimental unit rule and its 2026-08-22 result.

구현 대상: docs/integrated_research_design_v2.md §11.1.1 (규칙) · §11.1.2 (결과),
          docs/chapter2_audit_protocol_v1.md §4.3.2 (오더 33·45 동일 획득)
사전등록: 규칙은 2026-08-22 측정 전 선언. 아래 고정 수치는 그 규칙을 집행한 결과이며
          **측정 후 고정**이다. 수치가 바뀌면 코드가 틀렸다는 뜻이 아니라
          `data/inputs` 가 바뀐 사실을 사람이 검토해야 한다는 뜻이다.
해석 한계: 이 테스트는 "단위 수가 재현된다"만 보장한다. 11 이 생물학적 독립 반복 11 이라는
          뜻이 아니다(배치 수준 상한은 8, §11.1.2).
주장 금지: 통과를 표본 크기나 검정력의 근거로 서술하지 않는다.

왜 필요한가
-----------
supplement 에 선언하는 수라서 조용히 흔들리면 안 된다. 특히 §11.1 의 초판이 "19개",
2판이 "20개 디렉터리"였고 실행 수는 전 행 +1 과소였다 — 이 계열의 수치는 반복해서 틀렸다.
또한 오더 33·45 가 동일 획득이라는 사실은 §3.4·§4.3.1 의 pooling 서술을 제약하므로
그 사실이 유지되는지 자동으로 확인해야 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ptm_shared.dataset_units import (
    acquisition_prefix,
    build_report,
    connected_components,
    read_run_columns,
    split_header,
)

INPUTS_DIR = Path("/app/data/inputs")
AUDIT_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tmm_audit_v1"

N_DISTINCT_EXPERIMENTAL_UNITS = 11
"""§11.1.2 에서 2026-08-22 측정. supplement 에 선언되는 수.

규칙은 §11.1.1 에서 측정 전 선언(원자료 공유 그래프의 연결 성분).
바뀌면 `docs/integrated_research_design_v2.md` §11.1.2 와 supplement 를 함께 갱신해야 한다.
"""

N_DIRECTORIES_IN_SCOPE = 20
"""§11.1 의 `n_with_quantitative_matrix`. 2026-08-20 v2 감사에서 선언되고 2026-08-22 재확인."""

N_DISTINCT_RAW_RUNS = 164
N_UNITS_BY_ACQUISITION_PREFIX = 8
"""배치 수준 상한. **판정 값이 아니다** (§11.1.1 이 경로 prefix 를 판정에서 배제)."""

SAME_ACQUISITION_ORDERS = (33, 45)
"""§4.3.2. 원자료 12개가 완전히 동일하므로 감사 오더 6건은 독립 획득 5건이다."""

N_AUDITED_ORDERS = 6
N_AUDITED_ACQUISITIONS = 5


def _requires_inputs() -> None:
    if not INPUTS_DIR.is_dir():
        pytest.skip(f"{INPUTS_DIR} 미마운트 — 컨테이너 밖 실행")


# --- 규칙 자체 (데이터 불필요) ---------------------------------------------


def test_split_header_cuts_at_first_path_column() -> None:
    metadata, runs = split_header(
        (
            "Protein.Group",
            "N.Sequences",
            r"C:\acq\a.mzML",
            r"C:\acq\b.mzML",
        )
    )
    assert metadata == ("Protein.Group", "N.Sequences")
    assert runs == (r"C:\acq\a.mzML", r"C:\acq\b.mzML")


def test_split_header_accepts_posix_separator() -> None:
    _, runs = split_header(("Genes", "/mnt/acq/a.mzML"))
    assert runs == ("/mnt/acq/a.mzML",)


def test_split_header_without_any_path_column_yields_no_runs() -> None:
    metadata, runs = split_header(("Protein.Group", "Genes"))
    assert metadata == ("Protein.Group", "Genes")
    assert runs == ()


def test_crlf_does_not_drop_the_last_run(tmp_path: Path) -> None:
    """v2 감사(2026-08-20)의 off-by-one 재발 방지.

    당시 판정식 `\\.(mzML|raw|d)$` 는 CRLF 때문에 `...mzML\\r` 로 끝나는 **마지막** 컬럼을
    놓쳐 모든 데이터셋의 실행 수를 1 만큼 과소 계상했다(§11.1 실행 수 정정).
    §11.1.1 은 확장자 앵커 대신 경로 구분자 포함 여부를 쓰므로 이 오류가 재발할 수 없다.
    """
    matrix = tmp_path / "report.pr_matrix.tsv"
    header = "\t".join(
        ["Protein.Group", "Genes", r"C:\acq\a.mzML", r"C:\acq\b.mzML"]
    )
    matrix.write_bytes((header + "\r\n").encode("utf-8"))

    runs, anomalies = read_run_columns(matrix)
    assert runs == (r"C:\acq\a.mzML", r"C:\acq\b.mzML")
    assert anomalies == ()


def test_components_merge_on_any_shared_run() -> None:
    """교집합이 1개라도 있으면 같은 단위다 (§11.1.1)."""
    components = connected_components(
        {
            "a": frozenset({"r1", "r2"}),
            "b": frozenset({"r2", "r3"}),
            "c": frozenset({"r9"}),
        }
    )
    assert components == [["a", "b"], ["c"]]


def test_components_are_transitive() -> None:
    """a–b, b–c 만 겹쳐도 a·c 는 한 단위여야 한다. 연결 성분이므로 구성상 보장된다."""
    components = connected_components(
        {
            "a": frozenset({"r1"}),
            "b": frozenset({"r1", "r2"}),
            "c": frozenset({"r2"}),
        }
    )
    assert components == [["a", "b", "c"]]


def test_components_ignore_insertion_order() -> None:
    """같은 그래프를 삽입 순서만 바꿔 넣어도 분할과 그 나열이 동일해야 한다.

    출력이 실행 간 결정적이어야 §11.1.2 의 단위 번호를 문서에 적을 수 있다.
    """
    graph = {
        "a": frozenset({"x"}),
        "b": frozenset({"x", "y"}),
        "c": frozenset({"y"}),
        "d": frozenset({"z"}),
    }
    forward = connected_components(graph)
    backward = connected_components(dict(reversed(list(graph.items()))))
    assert forward == backward == [["a", "b", "c"], ["d"]]


def test_disjoint_sets_in_same_folder_stay_separate() -> None:
    """Cu/WithoutCu 형태 — 획득 폴더가 같아도 원자료가 서로 소면 별개 단위다."""
    components = connected_components(
        {
            "cu": frozenset({r"D:\batch\Fibril-Cu_1.mzML"}),
            "without_cu": frozenset({r"D:\batch\Fibril_1.mzML"}),
        }
    )
    assert components == [["cu"], ["without_cu"]]


def test_empty_run_set_is_its_own_unit() -> None:
    components = connected_components(
        {"empty": frozenset(), "other": frozenset({"r1"})}
    )
    assert components == [["empty"], ["other"]]


def test_acquisition_prefix_is_descriptive_only() -> None:
    assert acquisition_prefix(r"D:\batch\run_1.mzML") == r"D:\batch"
    assert acquisition_prefix("/mnt/batch/run_1.mzML") == "/mnt/batch"
    assert acquisition_prefix("bare_name.mzML") == ""


# --- 실측 결과 고정 (data/inputs 필요) --------------------------------------


@pytest.fixture(scope="module")
def report() -> dict:
    _requires_inputs()
    return build_report(INPUTS_DIR, AUDIT_FIXTURE_DIR)


def test_declared_unit_count_holds(report: dict) -> None:
    assert report["n_distinct_experimental_units"] == N_DISTINCT_EXPERIMENTAL_UNITS


def test_scope_matches_perturbation_audit(report: dict) -> None:
    """§11.1 의 `n_with_quantitative_matrix = 20` 과 어긋나면 두 표가 다른 모집단을 센다."""
    assert report["n_directories_in_scope"] == N_DIRECTORIES_IN_SCOPE


def test_raw_run_total_holds(report: dict) -> None:
    assert report["n_distinct_raw_runs"] == N_DISTINCT_RAW_RUNS


def test_component_run_counts_sum_to_total(report: dict) -> None:
    """성분 간 교집합이 없다는 것의 확인. 규칙이 깨지면 합이 초과한다."""
    assert (
        sum(component["n_raw_runs_union"] for component in report["components"])
        == report["n_distinct_raw_runs"]
    )


def test_directory_count_overstates_breadth(report: dict) -> None:
    """디렉터리 수를 단위 수로 쓰면 안 되는 이유가 유지되는지."""
    assert report["n_directories_in_scope"] > report["n_distinct_experimental_units"]


def test_batch_level_sensitivity_holds(report: dict) -> None:
    sensitivity = report["sensitivity_acquisition_prefix"]
    assert sensitivity["n_units_by_acquisition_prefix"] == N_UNITS_BY_ACQUISITION_PREFIX
    assert sensitivity["is_declared_rule"] is False


def test_integrity_checks_are_clean(report: dict) -> None:
    integrity = report["integrity"]
    assert integrity["pg_run_set_mismatch"] == []
    assert integrity["directories_with_duplicate_run_columns"] == []
    assert integrity["run_column_anomalies"] == {}
    assert integrity["directories_with_multiple_precursor_matrices"] == {}


def test_insulin_primary_dataset_run_count(report: dict) -> None:
    """6 시점 × 3 replicate + control 3 = 21. §11.1 표의 20 은 off-by-one 이었다."""
    per_directory = {
        record["directory"]: record for record in report["per_directory"]
    }
    assert per_directory["Insulin_Signaling_Phosphoproteomics_HIRc-B"]["n_runs"] == 21


def test_microgravity_is_in_scope_despite_phospho_suffixed_filename(
    report: dict,
) -> None:
    """`report.pr_matrix_phospho.tsv` — 고정 파일명으로 잡으면 오더 45 가 조용히 빠진다."""
    per_directory = {
        record["directory"]: record for record in report["per_directory"]
    }
    record = per_directory["Microgravity_Muscle_Atrophy_Phosphoproteomics"]
    assert record["primary_matrix"] == "report.pr_matrix_phospho.tsv"


# --- Chapter 2 감사에 대한 제약 (§4.3.2) ------------------------------------


def test_audited_orders_span_fewer_acquisitions_than_orders(report: dict) -> None:
    crossref = report["audited_order_crossref"]
    assert crossref["n_orders"] == N_AUDITED_ORDERS
    assert crossref["n_distinct_units_spanned"] == N_AUDITED_ACQUISITIONS


def test_orders_33_and_45_are_one_acquisition(report: dict) -> None:
    """이 사실이 §3.4 의 "오더 수를 표본 수로 쓰지 않는다" 서술을 지탱한다."""
    unit_of = {
        order["order_id"]: order["unit"]
        for order in report["audited_order_crossref"]["orders"]
    }
    left, right = SAME_ACQUISITION_ORDERS
    assert unit_of[left] == unit_of[right]


def test_orders_33_and_45_share_every_raw_run() -> None:
    """부분 겹침이 아니라 완전 일치임을 직접 확인한다 (§4.3.2 의 교집합 12/12)."""
    _requires_inputs()
    runs = {}
    for directory in (
        "Korea_timecouse_drugrepositioning",
        "Microgravity_Muscle_Atrophy_Phosphoproteomics",
    ):
        matrices = sorted((INPUTS_DIR / directory).glob("report.pr_matrix*.tsv"))
        assert matrices, f"{directory} 에 precursor matrix 가 없다"
        runs[directory], _ = read_run_columns(matrices[0])

    left, right = (set(value) for value in runs.values())
    assert left == right
    assert len(left) == 12


def test_orders_47_and_48_are_separate_acquisitions(report: dict) -> None:
    """짝지은 준대조는 같은 배치이지만 별개 획득이다 — §4.3.1 의 대조가 성립하는 근거."""
    unit_of = {
        order["order_id"]: order["unit"]
        for order in report["audited_order_crossref"]["orders"]
    }
    assert unit_of[47] != unit_of[48]
