"""Run 수준 replicate 구조를 표현 입력의 form 키로 복원한다.

구현 대상: docs/c3_prereg_v1.md §3.1 (A7 정렬), §12.1 (결합 가능성 실측)
사전등록: 결합률 하한 0.95 는 2026-08-22 §3.1 에서 §12.1 실측 착수 전 선언되었다.
          이 모듈은 그 하한을 판정하지 않고 결합률만 산출한다 — 판정은 호출자가 한다.
해석 한계: 표현 학습 입력(`ptm_vector_data_normalized_phospho.tsv`)의 시점 컬럼은 **이미
          replicate 평균**이며 시점별 replicate 수를 복원할 컬럼이 없다. 따라서
          `integrated_research_design_v2.md` §7.3 이 "유일하게 판정 가능"하다고 선언한
          `replicate ≥ 2` 계층은 원 `report.pr_matrix.tsv` 없이는 구성되지 않는다.
          실측(§12.1): HIRc-B 에서 결합률 1.0000, 관측 항목 중 rep≥2 비율 0.9341.
주장 금지: "rep≥2 계층이 더 정확한 데이터다" — 이 계층은 **pair 수준 false-merge 검정의
          검정력 요건**을 충족하는 계층이며 값의 품질 순위가 아니다.
          "rep≥1 에서 계산된 기존 지표가 무효다" — §7.3 의 금지는 pair 검정에 대한 것이고
          site 수준 예측 지표를 무효화하지 않는다 (§11.1).

결정성: run 컬럼 판정은 정규식 `_(label)_(replicate).(mzML|raw|d)$` 이며 대소문자를 구별한다.
        전구체 여러 행이 같은 form 으로 올라올 때 **최대값**으로 합친다 — 합을 쓰면 전하
        상태 수가 replicate 수로 새어든다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

CONTRACT_VERSION = "ptm_replicate_stratum.v1"

JOIN_RATE_FLOOR = 0.95
"""docs/c3_prereg_v1.md §3.1 의 경로 (a) 판단 기준.

2026-08-22 선언. §12.1 실측 착수 전. 이 값 미만이면 replicate 계층 결합을 폐기하고 검정력을
재산정한다(경로 (c)). 결합에서 탈락한 form 이 저관측 쪽에 쏠려 있으면 탈락이 곧 신호의
제거이기 때문이다. 측정 후 변경 금지 — 변경하면 (a)/(c) 분기가 무효가 된다.
"""

_RUN_PATTERN = re.compile(r"_(?P<label>[A-Za-z0-9.]+)_(?P<replicate>\d+)\.(?:mzML|raw|d)$")


def parse_run_columns(columns: Sequence[str]) -> Dict[str, List[str]]:
    """run 컬럼명을 시점 라벨로 묶는다. `..._1min_01.mzML` → `1min`."""
    grouped: Dict[str, List[str]] = defaultdict(list)
    for column in columns:
        match = _RUN_PATTERN.search(str(column).replace("\\", "/"))
        if match:
            grouped[match.group("label")].append(column)
    return dict(grouped)


def replicate_counts_by_form(
    matrix_path: Path, timepoints: Sequence[str]
) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    """`Modified.Sequence` 별 시점당 replicate 수.

    전구체 여러 행은 **최대값**으로 올린다. 한 form 이 어느 전하 상태에서든 2 replicate 로
    관측되면 그 시점은 replicate ≥ 2 로 관측된 것이다.
    """
    import pandas as pd

    header = pd.read_csv(matrix_path, sep="\t", nrows=0)
    run_groups = parse_run_columns(header.columns)
    missing = [label for label in timepoints if label not in run_groups]
    used = [label for label in timepoints if label in run_groups]
    if not used:
        raise ValueError(f"no run columns matched the timepoints {list(timepoints)}")
    columns = ["Modified.Sequence"] + [c for label in used for c in run_groups[label]]
    frame = pd.read_csv(matrix_path, sep="\t", usecols=columns, low_memory=False)

    per_timepoint = [
        np.isfinite(frame[run_groups[label]].to_numpy(dtype=float)).sum(axis=1) for label in used
    ]
    stacked = np.vstack(per_timepoint).T.astype(np.int16)
    counts: Dict[str, np.ndarray] = {}
    for row_index, sequence in enumerate(frame["Modified.Sequence"].astype(str).to_numpy()):
        current = counts.get(sequence)
        if current is None:
            counts[sequence] = stacked[row_index].copy()
        else:
            np.maximum(current, stacked[row_index], out=current)

    meta = {
        "contract_version": CONTRACT_VERSION,
        "matrix": str(matrix_path),
        "timepoints_used": used,
        "timepoints_without_runs": missing,
        "runs_per_timepoint": {label: len(run_groups[label]) for label in used},
        "n_precursor_rows": int(frame.shape[0]),
        "n_distinct_modified_sequences": len(counts),
        "unmatched_columns_ignored": sorted(set(run_groups) - set(used)),
    }
    return counts, meta


CONTROL_RUN_LABEL = "con"
"""paired control run 그룹의 라벨. `report.pr_matrix.tsv` 의 컬럼명에서 나온다.

`replicate_stratum_mask` 는 이 그룹을 시점으로 취급하지 않고 무시한다 — control 은 시계열의
한 점이 아니다. `universe_assignment` 가 같은 그룹을 **universe 분할 근거**로 쓴다.
"""

UNIVERSE_CONFIRMATORY = "U-confirmatory"
UNIVERSE_LOW_BASELINE = "U-low-baseline"
UNIVERSE_DENOVO = "U-denovo"
UNIVERSE_ORDER = (UNIVERSE_CONFIRMATORY, UNIVERSE_LOW_BASELINE, UNIVERSE_DENOVO)
"""docs/core_ab_p2_frozen_contract_v1.md §0.1 의 분할을 **인용**한다.

경계는 paired control replicate 수다 — ≥ 2 / 정확히 1 / 0. 이 값을 C2·C3 이 새로 정하지
않는다. `U-unpaired`(protein 결측)는 여기서 만들지 않는다: 표현 입력의 Track 1 가용성은
별도 필드(`track1_available`)이며 control replicate 수와 다른 축이다.
"""


def universe_assignment(
    multiview, matrix_path: Path
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """form 별 feature universe 라벨과 paired control replicate 수.

    구현 대상: docs/c2_prereg_v1.md §9.1 층 (1), docs/core_ab_p2_frozen_contract_v1.md §0.1
    사전등록: 경계값(≥2 / 1 / 0)은 §0.1 에서 이미 동결되어 있다. 이 함수는 인용만 한다.
    해석 한계: §0.1 의 공표 수치(2,420 / 302 / 313)는 **다른 모집단**에서 나온 값이다.
              여기서 나오는 수는 표현 입력의 적격 form 집합에 대한 것이므로 일치하지 않는다.
              불일치가 오류를 뜻하지 않는다.
    주장 금지: "U-confirmatory 가 더 정확한 데이터다" — 이 분할은 **baseline 신뢰도** 층이며
              값의 품질 순위가 아니다. U-denovo 는 자극 유발 층일 수 있다 (§0.1).
    """
    import pandas as pd

    header = pd.read_csv(matrix_path, sep="\t", nrows=0)
    groups = parse_run_columns(header.columns)
    control_columns = groups.get(CONTROL_RUN_LABEL, [])
    if not control_columns:
        raise ValueError(
            f"no control run columns matched label {CONTROL_RUN_LABEL!r} in {matrix_path}"
        )
    frame = pd.read_csv(
        matrix_path,
        sep="\t",
        usecols=["Modified.Sequence"] + control_columns,
        low_memory=False,
    )
    per_row = np.isfinite(frame[control_columns].to_numpy(dtype=float)).sum(axis=1)
    counts: Dict[str, int] = {}
    for sequence, value in zip(frame["Modified.Sequence"].astype(str).to_numpy(), per_row):
        # 전구체 여러 행은 최대값으로 올린다 — `replicate_counts_by_form` 과 같은 규칙이다.
        current = counts.get(sequence)
        if current is None or int(value) > current:
            counts[sequence] = int(value)

    labels: List[str] = []
    control_replicates = np.full(len(multiview.site_keys), -1, dtype=int)
    for row_index, key in enumerate(multiview.site_keys):
        count = counts.get(_form_sequence(key))
        if count is None:
            # 결합 실패는 0 으로 강등하지 않는다. 0 은 "control 을 측정했으나 없었다"이고
            # 결합 실패는 "모른다"이므로 다른 상태다.
            labels.append("unjoined")
            continue
        control_replicates[row_index] = count
        if count >= 2:
            labels.append(UNIVERSE_CONFIRMATORY)
        elif count == 1:
            labels.append(UNIVERSE_LOW_BASELINE)
        else:
            labels.append(UNIVERSE_DENOVO)

    array = np.asarray(labels, dtype=object)
    diagnostics = {
        "contract_version": CONTRACT_VERSION,
        "declaration": "docs/core_ab_p2_frozen_contract_v1.md §0.1",
        "control_run_label": CONTROL_RUN_LABEL,
        "n_control_runs": len(control_columns),
        "counts": {name: int((array == name).sum()) for name in UNIVERSE_ORDER},
        "n_unjoined": int((array == "unjoined").sum()),
        "mean_control_replicates": (
            round(float(control_replicates[control_replicates >= 0].mean()), 4)
            if (control_replicates >= 0).any()
            else None
        ),
    }
    return array, diagnostics


def _form_sequence(site_key: str) -> str:
    """표현 입력의 form 키에서 `Modified.Sequence` 부분을 꺼낸다."""
    return site_key.split("|", 1)[1] if "|" in site_key else ""


def replicate_stratum_mask(
    multiview, matrix_path: Path, *, minimum_replicates: int = 2
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """`replicate ≥ minimum_replicates` 관측 마스크와 결합 진단.

    반환 마스크는 run 수준 조건과 표현 입력 `observed` 의 **논리곱**이다. run 수준에 값이
    있어도 vector 단계에서 탈락한 항목을 관측으로 되살리지 않는다 — 표현이 보지 못한 값으로
    비교가능성을 주장할 수 없다 (docs/c3_prereg_v1.md §3.1).
    """
    timepoints = list(multiview.timepoints)
    counts, meta = replicate_counts_by_form(matrix_path, timepoints)
    used = meta["timepoints_used"]
    column_index = [timepoints.index(label) for label in used]

    observed = np.asarray(multiview.target.observed, dtype=bool)
    n_sites = observed.shape[0]
    joined = np.zeros(n_sites, dtype=bool)
    per_site = np.zeros((n_sites, len(used)), dtype=np.int16)
    for row_index, key in enumerate(multiview.site_keys):
        vector = counts.get(_form_sequence(key))
        if vector is None:
            continue
        joined[row_index] = True
        per_site[row_index] = vector

    # 판정 계층 마스크는 run 수준 조건과 표현 입력 `observed` 의 논리곱이다.
    stratum = np.zeros_like(observed)
    stratum[:, column_index] = per_site >= int(minimum_replicates)
    stratum &= observed

    # 진단은 **논리곱 이전의 raw run 수준 값**을 본다. 두 정의가 무엇을 세고 있는지 비교하는
    # 것이 목적이므로 한쪽을 다른 쪽으로 가두면 비교가 성립하지 않는다.  실측(§12.1)에서
    # rep≥1 평균 관측(5.7613)이 `observed` 평균(5.7606)보다 **크다** — 논리곱을 취하면 이
    # 초과분이 보이지 않는다.
    observed_used = observed[:, column_index]
    raw_at_least_one = per_site >= 1
    raw_at_least_minimum = per_site >= int(minimum_replicates)
    join_rate = float(joined.mean()) if n_sites else 0.0
    dropped = observed[~joined].sum(axis=1)
    kept = observed[joined].sum(axis=1)
    has_join = bool(joined.any())
    observed_positions = observed_used[joined] if has_join else np.zeros((0, 0), dtype=bool)

    diagnostics = {
        "source": meta,
        "minimum_replicates": int(minimum_replicates),
        "join_rate": round(join_rate, 6),
        "join_rate_floor": JOIN_RATE_FLOOR,
        "path_a_viable": bool(join_rate >= JOIN_RATE_FLOOR),
        "n_sites": int(n_sites),
        "n_joined": int(joined.sum()),
        "n_dropped": int((~joined).sum()),
        "dropped_mean_observed_timepoints": (
            round(float(dropped.mean()), 4) if dropped.size else None
        ),
        "joined_mean_observed_timepoints": (round(float(kept.mean()), 4) if kept.size else None),
        # 0 에 가까우면 표현 입력의 결측 정의가 사실상 "replicate 1 개 이상"이라는 뜻이다.
        # 그것이 §11.1 이 기록하는 사실이다 — 기존 지표가 계산된 계층.
        "observed_vs_rep1_disagreement": (
            round(float((observed_positions != raw_at_least_one[joined]).mean()), 6)
            if has_join
            else None
        ),
        "rep2_share_of_observed": (
            round(float(raw_at_least_minimum[joined][observed_positions].mean()), 6)
            if has_join and observed_positions.any()
            else None
        ),
        "mean_observed_timepoints_rep1": (
            round(float(raw_at_least_one[joined].sum(axis=1).mean()), 4) if has_join else None
        ),
        "mean_observed_timepoints_rep2": (
            round(float(raw_at_least_minimum[joined].sum(axis=1).mean()), 4) if has_join else None
        ),
    }
    return stratum, diagnostics
