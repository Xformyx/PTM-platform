# AI05 — native subprocess code root

기준 AI04 `91618dc`, branch `codex/astra-ai-usability`; 회차 SHA는 최종 통합 표 참조.

실제 `official_method_tracks.execute_tracks`를 작은 합성 입력으로 호출하고 subprocess만
저장소 밖 cwd/PYTHONPATH 없는 환경에서 실행했다. 수정 전 자식은
`ModuleNotFoundError: No module named 'ptm_shared'`로 실패했다.

`adapter_command`가 현재 로드된 official_method_tracks.__file__의 절대 code root를 전달한다.
자식은 `-I -B -c` bootstrap 안에서 그 root를 sys.path에 넣고,
phosx_activity_adapter의 실제 import origin이 정확히 포함된 파일인지 확인한 뒤 run_module한다.
cwd/사용자 path/PYTHONPATH에서 root를 추정하지 않는다. 기존 subprocess argument list,
shell=False, fresh process/PRNG 경계를 유지했다. service 환경을 삭제하거나 log에 노출하지 않는다.
module 누락은 nonzero→failed이며, process 시작 자체의 OSError도 별도 failed 이유로 기록한다.
실패를 executed로 표시하지 않으며 기존 성공 발행/pointer 경로를 변경하지 않는다.

검증 **5 passed**, skip 없음 (`codex-inputs/astra-ai-20261113/AI05.xml`):

- 공백 포함 bundle의 가짜 adapter import/정확한 __file__/argument 전달.
- seed71, permutations19, ST, input/matrix/background의 공백 인자 보존.
- module 누락은 installed copy로 대체하지 않고 실패.
- root가 cwd에서 파생되지 않으며 기본 seed1729/permutations10000 인자 보존.
- native code hash는 discovery fingerprint를 바꾸고 quant fingerprint는 유지.
- 기존 unscored Tyr가 ST ranking에 영향을 주지 않는 실제 execute_tracks 회귀 재사용.

마지막 항목과 parameter 확인은 위 5개 테스트 안의 assertion이다. 별도 테스트 수로 더하지 않는다.
가짜 adapter는 import/argument 기록 후 의도적으로 exit3하므로 실행표는 failed다.
이는 bootstrap 성공 검증이며 실제 PhosX 점수 parity가 아니다. PhosX adapter의 method/version,
점수/seed/permutation/rank/membership 정의는 수정하지 않았다. 관련 코드 hash는 기존
astra_evidence_v6.resolve_plan의 official_method_tracks 의존성으로 새 stage에 반영된다.

실제 native scientific replay/parity는 수행하지 않았다. 새 matrix 다운로드, 장시간 계산,
외부 검색/모델 호출0이다. 실제 구 reader archive replay(AI04)는 별개로 완료했으며
restricted specificity 원본 없이 고유 reader 파일40개의 bytes가 같았다.
실제 과학 표·pin·원 ZIP·pointer·입력은 쓰지 않았다. bootstrap 하위 프로세스는 모두 종료됐다.
