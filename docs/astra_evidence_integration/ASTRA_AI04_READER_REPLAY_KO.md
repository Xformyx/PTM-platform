# AI04 — ZIP reader-only 재현

기준 AI03-B `6d70b27`, branch `codex/astra-ai-usability`; 회차 SHA는 최종 통합 표에 기록한다.

## 진입점과 공통 logic

기존 `scripts/replay_astra_reader.py`의 saved-table 검증/복원/write/byte 비교 logic를
`ptm_shared/astra_reader_replay.py`로 옮겼다. repository CLI와 ZIP `reader_replay.py`가 공유한다.
기존 PROGRAM import 계약도 유지했다. 새 ZIP은 자체 bundled runner를 우선 사용하고,
구 ZIP은 repository harness가 그 archive의 reader 모듈을 실행한다. 구 ZIP에 코드를 쓰지 않는다.

```
python reader_replay.py --output /new/output
python /path/to/repository/scripts/replay_astra_reader.py --package /old/archive --output /new/output
```

`seal_archive`의 기존 원자적 발행 전에 새 진입점/capabilities/START_HERE 안내를 생성한다.
일반 발행과 immutable revision 모두 같은 경로다. `READER_CODE_FILES`에 bundled runner를 포함한다.
새 의존성은 없다. pandas 등 기존 requirements를 사용하며 자동 다운로드를 추가하지 않았다.

| 경로 | 의미/필요 자료 |
|---|---|
| catalog query/resolve | 저장 근거 조회, reader 재생성 없음 |
| archive reader replay | archive 자체 코드 + 저장 표 → 원 reader 산출물 bytes 검증 |
| current-code revision | 현재 개선 코드 → 새 immutable reader/index/descriptor, 과거와 byte equality 주장 안 함 |
| full replay.py | 과학 재계산, 경우에 따라 동일 restricted 자원 필요; 이번 검증 대상 아님 |

current-code temporal revision은 기존 과학 CSV를 재직렬화하지 않고 column descriptor만 보완한다.
과거 detection을 새 계산 결과로 바꾸지 않는다.

## 격리·검증

새 interpreter `-I -B`, PYTHONPATH 제거, source 외부 cwd를 사용한다.
출력은 새 경로만 허용하며 source 내부/기존 경로/`..`/symlink parent를 거부한다.
전체 manifest의 hash/size를 전후 검증하고 source 파일 목록도 비교한다.
실제 reader `__file__` 및 로드된 ptm_shared 모듈이 archive code root 안인지 검증한다.
pycache를 만들지 않는다. network socket/URL, 과학 calculate/quantify, native method,
문헌 collect/runtime/execute, subprocess에 실행 금지 guard를 설치한다.
frozen literature projection만 허용한다. 제한 자원 preflight를 거치지 않는다.

수정 전 production tiny package에는 reader_replay.py가 없어 회귀가 실패했다.
수정 후 공백 경로·외부 cwd·source 전체 bytes 보존·fresh interpreter·null/기존 reader 기능·
unsafe output 거부·source hash 변조 거부가 통과했다. 합성 archive에 의도적으로 과학 함수를
호출하는 reader를 주입해 guard가 실제로 실패시키는 것도 확인했다.
동일 합성 package에서 새 whole-reader revision 및 그 자체 entry replay까지 byte 비교가 통과했다.

AI04.xml: 2 passed. AI04_guard.xml: 2 passed. AI04_revision.xml: 1 passed.
중복 제외 **3개의 고유 테스트**이며 마지막 파일은 첫 테스트의 강화 버전이다.
기존 literature revision의 frozen replay와 정상 package 생성 경계도 포함한다.
과학 함수는 합성 tiny package 준비 시 기존 함수만 실행했다. 실제 과학/native/RAG/LLM 신규 호출 0회.

실제 G11 구 archive는 read-only replay를 별도 시작했다. source logical size 3,203,517,883 bytes,
reader 상한 750,243,224 bytes, 측정 당시 여유 29,682,987,008 bytes, reserve 20GiB다.
추가 peak 예산은 reader 상한의 2배로 계산했다. 기존 추출본을 재사용해 ZIP 복사/압축하지 않았다.
결과 경로 `codex-inputs/astra-ai-20261113/old_archive_replay/READER_REPLAY_VALIDATION.json`.
실제 구 archive 검증이 완료됐다: manifest **257개** 전후 hash/size 불변, 비교 기록42개에 해당하는
**고유 reader 파일40개** 모두 byte-identical. source reader 모듈은 해당 archive code root였다.
과학·network·model 호출0, M4 frozen 실행 복원 true. 기존 runner의 중복 artifact 반환은 고유 파일로 중복 집계하지 않았다.
AI04 commit은 `91618dc`; 최종 현재-code revision은 통합 보고에 기록한다.
실제 matched/운영 환경과 actual native scientific replay는 검증하지 않았다.
