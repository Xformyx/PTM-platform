# Truth-Based Benchmark Development Audit: Leakage-Safe Feasibility Assessment

## 목적

본 audit의 목적은 locked truth를 사용하여 현재 temporal PTM–protein benchmark의 개선 방향을 찾되, 동일 truth에 대한 반복 tuning으로 성능을 과대평가하지 않는 것이다. 따라서 truth는 artifact freeze 후 runner-only scorer output에서만 사용했고, raw matrix·production analysis·parameter selector·RAG·LLM에는 전달하지 않았다.

## Protocol

분석 후 canonical locked scorer가 생성한 `anchor_results`만 runner-only audit의 입력으로 사용했다. Eligibility policy는 parameter selection 전에 최소 8개의 measurable anchor, 4개의 regulated anchor, 4개의 temporal-evaluable anchor, 3개의 measurable branch를 요구한다. 독립 holdout을 주장하려면 위 development 조건과 별도로 최소 2개의 measurable holdout anchor가 필요하다.

이 기준은 biological label에 특화되지 않은 denominator guard이다. 충분한 data가 있을 때에만 다음 순서가 허용된다.

| 단계 | 허용 작업 | 금지 작업 |
|---|---|---|
| Truth-free pre-registration | finite candidate grid와 objective를 고정 | locked truth를 보고 candidate 추가 |
| Development evaluation | runner-only development truth로 한 번의 선택 | production analysis에 truth 전달 |
| Holdout evaluation | 선택 후 한 번의 independent evaluation | holdout 결과에 맞춘 재-tuning |

## Current Runner-Only Result

| Quantity | Observed | Minimum for development | Interpretation |
|---|---:|---:|---|
| Tier 1/2 anchor rows | 46 | — | Reference record context |
| Measurable anchors | 2 | 8 | Insufficient |
| Regulated anchors | 1 | 4 | Insufficient |
| Temporal-evaluable anchors | 1 | 4 | Insufficient |
| Measurable branches | 2 | 3 | Insufficient |
| Independent holdout measurable anchors | 0 available | 2 | Insufficient |

결과적으로 current truth는 **coverage diagnosis에는 사용할 수 있지만 parameter selection 또는 holdout-generalized improvement에는 사용할 수 없다.** Candidate input list는 빈 목록으로 preregistered 되었고, parallel grid·threshold tuning·score selection은 실행하지 않았다.

> 이 audit에서 score가 개선되었다는 주장은 하지 않는다. current truth denominator에 맞춰 threshold를 낮추거나 mapping gate를 완화하는 것은 benchmark overfitting 위험이 있으므로 금지했다.

## Truth-Free Coverage Diagnosis

동일 artifact를 truth 없이 검사한 결과, 2,447개의 site observation이 모두 sequence–isoform–species mapping을 통과했고 unknown/empty gene row는 3개(0.12%)였다. 또한 690개 site가 regulated로 기록됐다. 반면 locked scorer에서는 44개 anchor가 `not_declared_measurable`로 제외됐다. 따라서 현재 병목은 generic sequence mapping 또는 regulation threshold라기보다, **curated reference panel과 observed PTM universe 사이의 coverage overlap 부족**으로 해석해야 한다.

이 결과는 rule relaxation을 정당화하지 않는다. 오히려 future truth panel이 observed, sequence-validated PTM universe와 충분히 overlap하도록 curated되어야 함을 보여 준다.

## Implemented Safeguard

`benchmarking/truth_development_audit.py`와 `scripts/audit_truth_development_eligibility.py`를 추가했다. 이 module은 post-freeze locked score result만 읽고 다음을 강제한다.

| Safeguard | Behavior |
|---|---|
| Small denominator | `coverage_diagnosis_only_no_parameter_tuning` 반환 |
| Insufficient holdout | `insufficient_evaluable_denominator_no_holdout_claim` 반환 |
| Production isolation | production API, shared PTM engine, worker는 audit module을 import하지 않음 |
| Regression | synthetic insufficient/sufficient denominator test 포함 |

## Next Data Specification

다음 truth-based optimization을 시작하려면 analyst-authored reference extension이 다음 조건을 충족해야 한다.

| Requirement | Minimum |
|---|---:|
| Observed sequence-validated PTM과 겹치는 measurable anchor | 8 |
| Regulated anchor | 4 |
| Direction 또는 peak-window truth가 있는 temporal-evaluable anchor | 4 |
| Distinct signaling branch | 3 |
| 단 한 번의 independent holdout을 위한 measurable anchor | 2 |

이 조건이 충족된 후에만, raw time-course evidence만으로 preregistered finite grid를 만들고, development truth로 한 번 선택한 뒤 untouched holdout truth에서 한 번 평가할 수 있다. 이후 independent truth-free dataset 또는 perturbation dataset에서 효과가 재현될 때에만 일반화 가능한 algorithm improvement로 보고한다.

## Reproducibility Records

Runner-only outputs are packaged outside the production repository under `benchmark_v1_v2_work/truth_dev_holdout_audit/`: `development_eligibility.json`, `failure_taxonomy_summary.json`, `preregistered_grid_decision.json`, `truth_free_coverage_diagnosis.md`, `holdout_insufficiency_record.md`, and `noninferiority_after_truth_audit_guard.json`.
