"""`replicate_stratum` 의 회귀 테스트 — run 그룹 해석과 universe 분할.

정본 환경에서 실행:

    docker exec ptm-worker-preprocessing python -m pytest tests/test_replicate_stratum.py -q

이 파일이 잠그는 것은 세 가지다.

1. **universe 경계가 인용된 값인가** — ≥2 / 정확히 1 / 0 은
   `docs/core_ab_p2_frozen_contract_v1.md` §0.1 에서 왔다. 코드에서 조용히 옮겨지면 E7 의
   층이 문서와 달라지고, 층별 수치는 문서를 인용할 수 없게 된다.
2. **"모른다"와 "0" 이 구별되는가** — 결합 실패를 control replicate 0 으로 강등하면 결합
   실패 form 이 전부 U-denovo 로 들어가 층이 오염된다. 이것이 이 모듈에서 가장 조용히
   틀릴 수 있는 지점이다.
3. **control 이 시점으로 취급되지 않는가** — `con` 그룹이 시계열의 한 점으로 새어들면
   `rep≥2` 계층과 universe 층이 같은 컬럼을 두 뜻으로 쓴다.

테스트 통과는 **층의 타당성이나 방법의 성공을 뜻하지 않는다.**
"""

from types import SimpleNamespace

import numpy as np
import pytest

from ptm_shared.representation.replicate_stratum import (
    CONTROL_RUN_LABEL,
    UNIVERSE_CONFIRMATORY,
    UNIVERSE_DENOVO,
    UNIVERSE_LOW_BASELINE,
    UNIVERSE_ORDER,
    parse_run_columns,
    universe_assignment,
)

TIMEPOINT_COLUMNS = ["/data/run_1min_01.mzML", "/data/run_1min_02.mzML"]
CONTROL_COLUMNS = [
    "/data/run_con_01.mzML",
    "/data/run_con_02.mzML",
    "/data/run_con_03.mzML",
]


def _matrix(tmp_path, rows):
    """`report.pr_matrix.tsv` 의 최소 형태. `rows` 는 (sequence, control 관측 3칸) 이다."""
    path = tmp_path / "report.pr_matrix.tsv"
    header = ["Modified.Sequence"] + TIMEPOINT_COLUMNS + CONTROL_COLUMNS
    lines = ["\t".join(header)]
    for sequence, controls in rows:
        cells = [sequence, "1.0", "1.0"] + ["" if value is None else str(value) for value in controls]
        lines.append("\t".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _multiview(sequences):
    """`universe_assignment` 가 쓰는 최소 표면은 `site_keys` 뿐이다."""
    return SimpleNamespace(site_keys=[f"P00001|{sequence}" for sequence in sequences])


# ---------------------------------------------------------------------------
# run 그룹 해석
# ---------------------------------------------------------------------------


def test_control_runs_are_grouped_under_their_own_label():
    groups = parse_run_columns(TIMEPOINT_COLUMNS + CONTROL_COLUMNS)
    assert set(groups) == {"1min", CONTROL_RUN_LABEL}
    assert len(groups[CONTROL_RUN_LABEL]) == 3


def test_control_label_is_not_a_timepoint_label():
    """`con` 이 시점 라벨과 섞이면 `rep≥2` 계층이 control 을 시점으로 센다."""
    groups = parse_run_columns(TIMEPOINT_COLUMNS + CONTROL_COLUMNS)
    assert CONTROL_RUN_LABEL not in {"1min"}
    assert CONTROL_COLUMNS[0] not in groups["1min"]


# ---------------------------------------------------------------------------
# universe 경계 — docs/core_ab_p2_frozen_contract_v1.md §0.1
# ---------------------------------------------------------------------------


def test_universe_boundaries_follow_the_cited_contract(tmp_path):
    path = _matrix(
        tmp_path,
        [
            ("AAAK", [1.0, 2.0, 3.0]),
            ("BBBK", [1.0, 2.0, None]),
            ("CCCK", [1.0, None, None]),
            ("DDDK", [None, None, None]),
        ],
    )
    labels, meta = universe_assignment(_multiview(["AAAK", "BBBK", "CCCK", "DDDK"]), path)

    assert labels.tolist() == [
        UNIVERSE_CONFIRMATORY,
        UNIVERSE_CONFIRMATORY,
        UNIVERSE_LOW_BASELINE,
        UNIVERSE_DENOVO,
    ]
    assert meta["counts"] == {
        UNIVERSE_CONFIRMATORY: 2,
        UNIVERSE_LOW_BASELINE: 1,
        UNIVERSE_DENOVO: 1,
    }
    assert meta["declaration"] == "docs/core_ab_p2_frozen_contract_v1.md §0.1"


def test_unjoined_forms_are_not_demoted_to_zero_controls(tmp_path):
    """결합 실패는 "모른다"이고 control 0 은 "측정했으나 없었다"다. 섞으면 층이 오염된다."""
    path = _matrix(tmp_path, [("AAAK", [1.0, 2.0, 3.0])])
    labels, meta = universe_assignment(_multiview(["AAAK", "ZZZK"]), path)

    assert labels.tolist() == [UNIVERSE_CONFIRMATORY, "unjoined"]
    assert meta["n_unjoined"] == 1
    assert meta["counts"][UNIVERSE_DENOVO] == 0


def test_multiple_precursor_rows_take_the_maximum_not_the_sum(tmp_path):
    """합을 쓰면 전하 상태 수가 control replicate 수로 새어든다."""
    path = _matrix(
        tmp_path,
        [("AAAK", [1.0, None, None]), ("AAAK", [None, 2.0, None])],
    )
    labels, _ = universe_assignment(_multiview(["AAAK"]), path)

    # 두 전구체 각각 1 replicate. 합이면 2 가 되어 U-confirmatory 로 잘못 승격된다.
    assert labels.tolist() == [UNIVERSE_LOW_BASELINE]


def test_non_finite_control_values_are_not_counted_as_observed(tmp_path):
    path = _matrix(tmp_path, [("AAAK", [1.0, "nan", "inf"])])
    labels, _ = universe_assignment(_multiview(["AAAK"]), path)

    assert labels.tolist() == [UNIVERSE_LOW_BASELINE]


def test_missing_control_group_fails_loudly(tmp_path):
    """control 컬럼이 없는 데이터셋에서 조용히 전부 U-denovo 가 되면 안 된다."""
    path = tmp_path / "report.pr_matrix.tsv"
    path.write_text(
        "Modified.Sequence\t" + "\t".join(TIMEPOINT_COLUMNS) + "\nAAAK\t1.0\t1.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="control run columns"):
        universe_assignment(_multiview(["AAAK"]), path)


def test_universe_order_is_the_reporting_order_of_the_contract():
    assert UNIVERSE_ORDER == (
        UNIVERSE_CONFIRMATORY,
        UNIVERSE_LOW_BASELINE,
        UNIVERSE_DENOVO,
    )


def test_mean_control_replicates_excludes_unjoined_forms(tmp_path):
    path = _matrix(tmp_path, [("AAAK", [1.0, 2.0, 3.0])])
    _, meta = universe_assignment(_multiview(["AAAK", "ZZZK"]), path)

    # 미결합 form 을 0 으로 세면 평균이 1.5 로 내려간다.
    assert meta["mean_control_replicates"] == pytest.approx(3.0)


def test_labels_align_positionally_with_site_keys(tmp_path):
    path = _matrix(
        tmp_path, [("BBBK", [None, None, None]), ("AAAK", [1.0, 2.0, 3.0])]
    )
    labels, _ = universe_assignment(_multiview(["AAAK", "BBBK"]), path)

    # 행렬의 행 순서가 아니라 `site_keys` 순서를 따라야 한다.
    assert labels.tolist() == [UNIVERSE_CONFIRMATORY, UNIVERSE_DENOVO]
    assert isinstance(labels, np.ndarray)
