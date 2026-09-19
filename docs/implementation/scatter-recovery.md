# Scatter 복구 작업 기록

기준: `67867a751be01b4d36c3066eda8f6675ad3c472a`, `Xformyx/PTM-platform`.
작업 브랜치: `fix/restore-vector-scatter`. 2026-09-19 시작 시 main은 clean이었다.
적용되는 AGENTS.md와 전달된 patch 파일은 발견되지 않았다. 명세를 기준으로 구현했다.
네트워크 중단 후 동일 브랜치와 reader/API 두 파일의 변경을 재확인하고 보존했다.

## 진행 상태

1. 기준/회귀 재현 완료: TSV가 있는 임시 디렉터리에서 기존 `vector-view/manifest` 함수가 409 `columnar_snapshot_unavailable`을 반환했다.
2. read-only source-row reader 및 새 GET 구현. snapshot/RAG 의존 없음. 조건별 point→density 전환과 원본 행 계수 회귀 통과.
3. 공유 UI/admin/user 연결 완료. 최종 Python 19 passed/0 failed/0 skipped, Node 12 passed, production build 통과. 관련 TMM lifecycle과 vector selection 회귀를 포함한다.
4. 운영 배포·실주문 재분석은 수행하지 않았다. 기존 분석식/Top N 선택은 변경 대상이 아니다.
5. 2026-09-19 브라우저 재개 검증 완료: 13개 시나리오 통과, browser error 0, write 요청 0, 종료코드 0. 현재 구현과 fixture 해시를 고정하고 실행 전후 불변을 확인했다.

## 재개 지점

`git status --short`, 이 문서, `ptm_shared/scatter_overview.py`, `api-server/app/api/vector_view.py`를 먼저 확인한다.
검증 Python은 `/tmp/ptm-integration-20260917-venv/bin/python`, frontend는 기존 npm 환경을 사용한다.
현재 남은 작업은 운영 주문의 원본/count 대조와 배포 후 인증된 전체 화면 E2E다. 로컬 브라우저 검증은 완료됐으며 결과를 보존한다. 이번 재개 단계에서는 commit/push/merge/배포를 수행하지 않았다.

## 취소된 실행과 재개 환경 확인

직전 승인이 취소된 `/tmp/ptm-scatter-20260919-final-browser`는 존재하지 않았다. 진행 중인 검증/Chrome도 없었으므로 해당 시도를 성공으로 집계하지 않았다.
Vite만 남아 있었다. 프로세스의 cwd는 현재 저장소 `frontend`, 포트는 `127.0.0.1:5173`임을 확인했다.
Node 24.8.0, Playwright 1.63.0, Chrome 153.0.8010.50을 사용했다.
`/tmp/ptm-scatter-20260919-final-fixture`의 JSON 10개를 현재 reader로 다시 계산하여 전부 일치함을 확인했다.
Browser 스킬을 읽고 실행 도구를 확인했으나 내장 Node/browser 도구가 노출되지 않아 로컬 Playwright를 사용했다. Chrome 실행은 정상적인 sandbox 외부 실행 승인 절차로 재개했다.

## 실제 브라우저 명령과 결과

repository root에서 실행했다. `$PY`는 `/tmp/ptm-integration-20260917-venv/bin/python`, `$PW`는 해당 환경의 `lib/python3.14/site-packages/playwright/driver/package`였다.

```sh
$PY scripts/run_scatter_browser_validation.py \
  --fixture-dir /tmp/ptm-scatter-20260919-final-fixture \
  --output /tmp/ptm-scatter-browser-resume-20260919-01 \
  --browser '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  --playwright-module "$PW" --url http://127.0.0.1:5173
```

새 출력 디렉터리 생성, preflight, 코드/fixture SHA-256 기록, child 실행, live stdout/stderr 복사, 종료코드 및 실행 후 hash 검사를 wrapper가 수행한다. 기존 결과 디렉터리는 재사용하지 않는다.

- 실제 실행: 2026-09-19 03:40 UTC (12:40 KST), `status=passed`, `browser_exit_code=0`.
- `stdout.log`: 시나리오별 즉시 진행 로그와 최종 결과, 2,838 bytes. `stderr.log`: 0 bytes. `exit-code.txt`: `0`.
- `progress.json`: 마지막 완료 시나리오 13. `browser-result.json`: 전체 시나리오와 errors=[], request_count=16, write_requests=0.
- `run-manifest.json`: source/fixture 해시, 실행 명령, runtime, 종료 상태, 산출물 해시. 실행 전후 source/fixture 모두 불변이며 등록된 산출물 10개의 해시를 재검사했다.
- PNG: `scatter-desktop-hover.png`, `scatter-mobile.png`, `scatter-density.png`, `scatter-error.png`. desktop/mobile 화면을 직접 열어 레이아웃도 확인했다.
- 원본 다운로드: `downloaded-source.tsv`가 합성 입력 TSV 바이트와 일치한다.

모든 파일은 `/tmp/ptm-scatter-browser-resume-20260919-01`에 있다. macOS에서는 `/private/tmp`로 resolve될 수 있다. 저장소 요약은 `scatter-validation.json`이다.

통과 시나리오: 6조건 Canvas 실제 픽셀; precursor/raw label 및 실제 0 hover; 실제 viewport zoom; U/유효 occupancy 전환; 지연된 이전 axis 응답; 지연된 이전 order 응답; 390px mobile overflow 없음; 원본 다운로드; 오류/빈 Canvas 없음/재시도; 12만 행 전체 bins/구간 hover; 0만 있는 2,001행 density hover; 빈 원본과 축 부적격 구별; browser 오류·write 요청 없음.

이전 11개 시나리오 실행 중 최초 U hover timeout은 새 Canvas에 같은 좌표의 pointer 이벤트를 다시 전달하지 않은 harness 문제였다. pointer leave/re-entry를 명시한 뒤 통과했다. 최종 13개 시나리오 재개 실행에서는 실패가 없었다. 이전 실행의 통과를 이번 실행으로 대신하지 않았다.

## 기존 Python/Node/build 및 규모 시험

```sh
PYTHONPATH=.:api-server DATABASE_URL=sqlite+aiosqlite:///:memory: $PY -m pytest -q \
  ptm_shared/tests/test_scatter_overview.py api-server/tests/test_scatter_overview_api.py \
  api-server/tests/test_vector_view_api_v2.py api-server/tests/test_analysis_job_lifecycle.py \
  --junitxml=/tmp/ptm-scatter-20260919-tests.xml
# frontend 디렉터리
node --test tests/scatterOverview.test.ts tests/vectorView.test.ts tests/quantitation.test.ts
npm run build
# repository root
PYTHONPATH=. $PY scripts/build_scatter_fixture.py --output /tmp/ptm-scatter-20260919-final-fixture
```

XML은 19 passed/0 failed/0 skipped임을 재확인했다. Node는 12 passed, build는 성공했다. 기존 Starlette deprecation 및 Vite bundle/Browserslist 경고는 남는다. 재개 단계에서는 제품 코드를 바꾸지 않고 검증 스크립트/로그 수집과 기록을 보완했으므로 Python/build 전체를 다시 실행하지 않았다.

최종 합성 reader 시험은 120,000행/6조건/505 bins, represented_rows=120,000, sampled_out_rows=0이었다. 최초 조회 1.654422초, cache 0.000424초, JSON 19,415 bytes, peak process RSS 92,241,920 bytes (macOS)다. 이 값은 제공 문서의 다른 fixture 측정치와 동일하다고 주장하지 않는다. 현재 fixture 생성기의 별도 실행 결과다.

## 적용 범위와 남은 제약

API와 frontend를 함께 반영해야 한다. 기존 normalized TSV가 있으면 사용하고, 없으면 motifs TSV를 사용한다. snapshot 준비/전처리/TMM 재실행은 필요 없다. 두 TSV가 모두 없으면 명시적 오류이며 snapshot만으로 원본을 복원하지 않는다.
2,000행은 조건별 표시 방식 전환점이다. 중복/충돌 원본 행을 각각 계수하고, gene/site/identity/RAG/Top N으로 줄이지 않는다. source_rows=represented_rows+excluded_rows, 모든 density bin 합=조건별 유효 행 수를 검사한다. 미해결 identity 행도 표시하며 축별 null/nonfinite/부적격은 제외 이유로 남긴다.
원본 TSV·과거 revision·scientific thresholds·TMM 입력/수식·time-series 선정 정책을 변경하지 않았다. 최대 6개 응답의 process-local cache는 inode/크기/mtime/ctime 및 축으로 무효화하며 응답 revision은 source SHA-256이다.
실제 공통 컴포넌트와 CSS를 Vite에서 실행했지만 HTTP 응답은 현재 reader의 합성 fixture다. 실제 로그인·주문 페이지 전체·운영 데이터·운영 네트워크/동시 접속의 E2E 또는 성능 보장이 아니다. 밀도 모드의 개별 precursor 화면 drill-down은 미구현이며 원본 값은 TSV 다운로드로 확인할 수 있다. 이번 단계에서 운영 반영이나 실제 주문 재분석은 하지 않았다.
