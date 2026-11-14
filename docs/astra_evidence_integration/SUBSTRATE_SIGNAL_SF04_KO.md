# SF04 전체 궤적 / 시간 흐름 UI

SF03 `aba72b2` 다음 단계. OrderDetail의 시간 곡선에 `SubstrateSignalFlow`를 연결하고 기존 FullTrajectoryBrowser도 동일 화면에서 연다. Astra form_id와 Legacy precursor feature_id는 별도 경로다. 새 화면은 발행 provenance/run binding을 검증한 read-only API → 기존 EvidenceCatalog source registry → 저장 projection만 읽는다. projection이 없는 구 패키지는 unavailable + reader revision 안내이며 열람으로 계산하지 않는다.

form U_joint/P_joint/A numeric time curve → 실제 point Control → candidate bundle → 전체 membership / fixed·variable 결과 / typed relation / hypothesis를 탐색한다. null과 excluded는 선으로 잇지 않는다. pin은 현재 검토 표시이며 전체 분모와 bundle은 변하지 않는다. API cursor는 catalog·table·filter·정렬 계약에 결합한다.

Classic의 `9999 → 20`과 N/mode 미전달을 수정했다. 기존 load_vector_view/plot_selection을 사용하여 axis eligibility 후 canonical feature를 선정하고 annotation을 붙인다. 작은 annotation을 Top-N manifest로 간주하지 않는다. per-condition/global/all을 구분한다. conventional contrast, LOD-relative, normalized intensity를 별도 선택/축으로 표시한다. 기존 default 20은 유지하지만 All과 사용자 명시 N을 덮어쓰지 않는다.

Atlas의 gene/site grouping은 feature identity가 있으면 그 ID를 유지한다. 정보 부족 record는 별도 unresolved ID이며 gene/site로 합쳐 강제 연결하지 않는다. context join도 exact feature ID를 우선하고 현대 feature의 symbol-only context는 연결하지 않는다. non-PTM 문맥은 실제 gene 필드를 사용한다.

검증: frontend `tsc && vite build` 통과(기존 bundle size/Browserslist 경고). 관련 Python 경계 17개 고유 테스트(SF01–04 7, classic 6, atlas 2, HTTP/vector API 2). 기존 3 tests는 결함 동작을 기대하므로 새 명세에 맞춰 수정하고 All 26개 및 명시 global N=1 회귀를 추가했다.

실제 React component + 합성 API route를 Chrome에서 실행하여 form→candidate→membership, page size, pin을 확인했다. screenshot `codex-inputs/substrate-signal-20261114/SF04-browser.png`, 결과 `SF04_BROWSER_RESULTS.json`. 운영 UI/DB 확인은 아니다. 최초 Chrome sandbox 차단 후 허용 경로로 실행했고 검증 HTML import 오류를 수정했다. 과학/검색/모델 0회. 패키지 writer 연결은 SF05 범위이며 단계 SHA는 최종 보고/checkpoint 참조.
