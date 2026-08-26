# Strict-blind optimization ledger contract v1

본 계약은 PR/PG matrix, replicate, numeric timepoint와 FASTA만 사용하는 truth-free 반복 최적화를 논리적으로 추적하기 위한 append-only 기록 형식이다. Stimulus, treatment, biological question, workbook, anchor와 locked truth는 key와 value 수준에서 재귀적으로 거부된다.

각 trial은 neutral input SHA-256, Git commit, registry version, variable configuration, configuration SHA-256, fold별 truth-free metric, 선택·기각 사유와 직전 record hash를 저장한다. Record hash는 canonical JSON의 SHA-256이며 다음 record가 이전 hash를 참조하므로 중간 수정 또는 삭제를 탐지할 수 있다.

| 구획 | 허용 내용 | 금지 내용 |
|---|---|---|
| Input | neutral matrix/sequence hash | sample identity와 자극원 이름 |
| Variables | registry에 사전 정의된 이름·범위 | trial 도중 추가한 미등록 변수 |
| Objective | replicate holdout, reconstruction, stability, identifiability, parsimony | locked score와 anchor recovery |
| Decision | continue, reject, select, freeze와 사유 | workbook 기준 선택 사유 |
| Final evaluation | freeze record 이후 별도 offline scorer | optimization ledger 내부 truth access |

Ledger schema는 `strict_blind_optimization_trial.v1`, variable registry는 `strict_blind_temporal_variables.v1`이다. 최종 configuration은 `decision=freeze` record로 동결하며 그 이후 동일 ledger에서 변수 선택을 계속하지 않는다.
