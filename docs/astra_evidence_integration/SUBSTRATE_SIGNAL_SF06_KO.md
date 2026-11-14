# SF06 통합 검증과 보존

시작점 main `92a3776fcc3747b981a77a4ff0838811b5a9b150`, 작업 branch `codex/substrate-signal-flow`. 이전 AI01–06-B 구현을 보존하고 SF01–05의 projection·UI·reader/report 경계를 검증했다. 최신 로컬 source가 검토 기준 `fe11ff8`보다 앞서므로 과거 SHA로 되돌리지 않았다. 실행 결과와 단계 SHA는 [최종 보고](SUBSTRATE_SIGNAL_FLOW_UPGRADE_KO.md), 작은 `SUBSTRATE_SIGNAL_RESULTS.json`에 기록한다.

## 최종 경계 수정

- native `selected=false` 입력은 조회 가능하지만 contribution count/signature와 `method_contribution`에서 제외하고 `method_input_excluded`로 표시한다. native membership에 없는 gene identity는 0이 아니라 미기록이다.
- API는 발행 root별 기존 EvidenceCatalog 세션을 최대2개 재사용한다. 호출마다 catalog/source 변경 검사를 유지하고 lock으로 세션 접근을 직렬화한다. key/filter 열로 page를 정한 뒤 해당 원본 행만 resolve한다. 전체 canonical key 중복 검사는 생략하지 않는다.
- 실제 reader display revision에서 기존 `refresh_figures`가 모든 그림을 재렌더링하여 관계없는 caption/PNG까지 바꿨다. 보존 검사가 발행을 막은 뒤 `figure_names`로 기존 refresh 범위 두 heatmap만 그리도록 수정했다. 대응 SVG/PNG/display descriptor와 legend만 허용하며 다른 그림·source·point bytes는 유지한다.
- archive replay가 구형 frozen pin의 입력을 새 adapter로 다시 선정하던 문제를 수정했다. saved temporal/display revision은 저장 packet/cards/findings/coverage를 복원한 뒤 기존 pin hash·입력·순서 검증을 그대로 수행한다. 새 selection을 실행하지 않으며 재생성할 signal_flow 출력은 입력에서 제외한다.
- START_HERE와 READ_ME에 기질→kinase 묶음→관계·가설 guide를 연결했다. UI에 U/P/A 범례와 화살표 의미, missing prior/인과 미확정을 표시했다.

## 검증

최종 경계 테스트의 고유 test name 70개 통과, 실패/skip 0. 혼합 pytest collection에서 JUnit classname 일부가 비어 있으므로 같은 test name을 중복 합산하지 않았다. 주요 범위는 production projection, exact key/FK/중복 거부, native 제외, membership turnover/fixed NA, partial/mixed scope, 실제 FastAPI 접근 제어·cursor·source 변조, Classic N/mode 전달, Atlas identity, figure/report binding, immutable package/replay다. 기존 C03의7개 작은 science 함수 회귀를 재사용해 불균일 시간·중간 NA·arm/family 분리·shared/matched scope와 미계산 biological p를 확인했다.

별도 `npm run build` 통과. 설치된 실제 Chrome에서 production React component와 합성 API를 연결하여 form→candidate→membership/관계, page size, pin, 범례를 검증했다. 운영 DB/queue/browser 검증은 아니다. 기존 Browserslist·bundle size 및 pandas/FastAPI deprecation 경고가 남아 있고 변경 범위와 무관하다.

검증 중 실패는 미확인 자원으로 바꾸지 않았다. 초기 reader byte mismatch(empty/null), font subprocess, 실제 projection의 반복 metadata 과다, native 제외 count, display revision allowlist를 수정하고 재검증했다. 한 추가 테스트 명령에서 workers PYTHONPATH가 빠져 import가 실패한 것은 환경 인자를 보완해 같은 범위를 통과했다. 중단한 projection/실패 revision은 성공 pointer로 발행하지 않았다.

실제 저장 자료의 전체 point 값/NA/mask/실제 Control, source hash, native 원본, frozen literature, 기존 ZIP/pointer 보존과 최종 reader replay 결과는 최종 보고의 실제 검증 표를 따른다. 원본과 새 reader revision을 구분하며 scientific table byte 동일성과 의도적으로 달라진 projection/reader 파일을 혼동하지 않는다.

## 제한

실제 time-matched 주문, 운영 UI/worker/다운로드, 신규 모델 보고서 품질 비교는 미검증이다. exact Legacy feature→Astra form crosswalk가 없는 입력은 unavailable이며 gene/site로 강제 연결하지 않는다. relation bundle이 없으면 missing prior를 표시하고 관측 궤적·기질 association은 제공한다. 모든 temporal hypothesis는 review_required / causality not_established이며 no-call이나 미계산 biological p/q를 승격하지 않는다.

최종 실제 확인: 전체84,720 track points 및13,704 joint 분해, 기존175,537 evidence/source keys 보존. v3 immutable ZIP의 archive 자체 코드 replay에서56 reader 파일 byte 동일, manifest288개 검증, science/network/model0회. 원본273개 files와 기존 입력·ZIP·pointer 유지. 작업 프로세스 잔여0개, 디스크 여유 약3.48GiB. 최종 artifact 경로/hash는 통합 보고를 따른다.
