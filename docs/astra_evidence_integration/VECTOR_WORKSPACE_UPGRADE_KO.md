# Vector Plot의 시간·기질·근거 연결

작업 시작 시 로컬 main은 `b1f69bf`였다. Xformyx/PTM-platform의 main을 fetch해 `3311050c7af020057bd622b8ab8225671e0be821`로 fast-forward한 뒤 `codex/vector-workspace`에서 작업했다. 기존 미추적 `codex-inputs/`는 작업 커밋에서 제외했다.

| 단계 | 구현 커밋 | 확인한 결과 |
|---|---|---|
| V01 | `6c0d3e4` | 선정 전 전체 grid, 기록 시간 우선, 결측에서 끊긴 선, 빈 축 전환, 다중 부위 표시 경계를 적용했다. |
| V02 | `237d45c` | 실행·catalog 및 다운로드 SHA를 검증했다. 손상된 bundle과 optional pathway의 오류에서도 다른 결과에 접근했다. |
| V03 | `b8b68c1` | 원본 행에서 exact precursor의 U/P/A와 동일 측정 revision의 근거로 이동했다. 검토 pin에 실행·catalog·원본 참조를 포함했다. |
| V04 | `6196734` | 실제 Chrome·저장 ZIP·합성 API로 연결을 확인했다. 검증 중 드러난 모바일 버튼 잘림, 서로 다른 scope를 가진 동명 조건, 대량 표시와 페이지 선택 상태를 수정했다. |

## 원본에서 연구자가 보는 화면까지

| 원본 | 호출 경로 | 화면과 산출물 |
|---|---|---|
| Legacy 전처리 TSV | `read_scatter_overview` → 원본 행 또는 density bin → `scatter_members` → `vector-view/feature-detail` | 전체 반응 분포에서 행을 고른 뒤 원본 SHA와 precursor ID에 묶인 상세로 이동한다. 전체 TSV 다운로드는 표시한 파일의 SHA와 실제 전송 chunk를 확인한다. |
| TSV 또는 기존 Parquet | `load_vector_view` / `VectorColumnar` → `condition_grid` → Top-N / FullTrajectoryBrowser | 먼저 축의 적격성을 적용한다. 기록 시간이 충돌하거나 없으면 출처와 상태를 표시한다. 동일 form의 U/P/A 상세는 선정 축과 별도로 조회한다. 저장된 다중 부위 pair의 revision·부모 identity·서로 다른 부위를 확인한다. |
| 완료 AnalysisJob 및 report bundle | `bound` → 검증된 candidates manifest 측정 revision → `explorer_page` → contributions, evidence, report-claims | 동일 precursor일 때 kinase 기여, 저장 문헌과 보고서 주장을 조회한다. 이전 실행의 손상·권한 오류와 필터 밖 기질을 구분한다. |
| Astra 발행 snapshot | Primary A → SubstrateSignalFlow → `published_root` / EvidenceCatalog / `signal_page` | form × effect series × track으로 저장한 값, 시간, 실제 Control, 시작·회복 구간, 후보 묶음과 관계를 읽는다. 검토 pin JSON은 원래 points의 source_ref까지 포함한다. |
| 기존 reader·보고서 입력 | 저장 projection → `load_report_signal` → 시간 근거·생물학적 합성 formatter, 기존 figure binding | 기존 합성 reader 테스트에서 그림과 보고서 입력의 원본 수치 연결을 대조했다. 브라우저에서 내보낸 pin은 검토용 파일이다. 운영 보고서로 자동 가져오기나 모델 작성은 검증 범위 밖이다. |

Legacy의 A는 기존 sample-wise 비율 기반 contrast이며 U와 P는 독립 축이다. Canonical의 U_joint/P_joint/A는 해당 실행의 estimator와 joint mask를 따른다. 두 자료의 gene/site 표기가 같아도 precursor와 form 사이의 대조를 만들지 않는다. 저장된 정확한 crosswalk가 없는 자료는 각각의 원본 화면에서 열 수 있다.

## 검증 결과와 경계

- Python 고유 테스트 60개와 Node 고유 테스트 12개가 통과했다. Python의 처음 6개 스위트에서 통과한 45개는 최종 60개에 포함한다. 단계별 재실행·진단 재시도 수는 통과 건수에 더하지 않았다. TypeScript 검사와 Vite production build가 통과했다. 기존 Browserslist 데이터와 번들 크기 경고가 남는다.
- Chrome에서 Scatter 13개와 Explorer 16개 시나리오를 통과했다. 별도의 화면 간 통합 검증은 실제 React 컴포넌트에 합성 API 응답을 연결했다. 1440·1280·990·390px, 모두 해제, 빈 A에서 U 선택, dark/light heatmap 대비, stale 409, optional 503, 늦은 응답, 원본 pin을 확인했다. 선정된 기질의 관측 행이 없는 중간 조건은 표에 남고, 불균일한 기록 시간과 중간 A 결측은 SVG path 좌표와 분리된 두 구간으로 확인했다.
- API 경계에서 A를 조회한 뒤 B를 발행해 A에 고정한 요청이 409가 됨을 확인했다. 파일 경로 교체 뒤에도 이미 연 descriptor의 원본을 전송했고, 같은 파일 내용이 전송 중 바뀌면 변경 chunk를 보내기 전에 스트림이 실패했다.
- 연구자 주문에 로그인한 브라우저 검증은 수행하지 않았다. 실제 공통 Control 결과는 아래 archive 한 건을 읽었고, 시간대별 Control의 form·kinase·source pin 탐색은 합성 fixture에서 확인했다. 운영 MySQL/queue, 실제 matched 주문 다운로드, 새 모델의 해석 품질은 미확인이다.

## 실제 저장 결과

실행 `g0-adfcea86b3504959b75986baf994ade4`의 archive는 `codex-inputs/substrate-signal-20261114/final-reader-revision-v3/astra_analysis_package_g0-adfcea86b3504959b75986baf994ade4.zip`이다. SHA-256은 `ea3a905d2c5d60ea9735a0f62714f8d6338f38fcc5d6f5ad98964b32a2924926`였다. ZIP 내부와 기존 추출본에서 전체 기질 궤적, kinase 묶음, method scores, contrast 정량표, data dictionary의 바이트 해시 5개가 일치했다.

`form_ba2993ff20c8f5f3`의 `series_8bcf2a244a036b564b4c`에 대해 6개 source contrast를 찾아 적격 A값을 대조했다. 개별 해시·시간·pointer SHA와 변경 파일 전체 목록은 `VECTOR_WORKSPACE_RESULTS.json`에 있다. 실제 주문 전체의 모든 셀에 대한 수치 동등성은 측정하지 않았다.

새 과학표, native method 실행, 실제 정량 재계산, 외부 RAG·LLM 요청, reader revision이나 발행 ZIP 생성은 0건이다. 테스트의 작은 합성 executor 및 reader 함수는 로컬에서 실행했다. 기존 ZIP·pointer·source/literature pin을 수정하는 경로는 호출하지 않았다. 원격 push·merge, 배포와 flag 변경도 수행하지 않았다.

## 재현 자료

`scripts/build_explorer_fixture.py --output <새 경로>`로 작은 합성 API 응답을 만든다. 프런트엔드 Vite 서버를 열고, 저장소 테스트 환경에서 `scripts/validate_vector_workspace.py --fixture <응답 경로> --url <Vite 주소> --browser <Chrome 실행 파일>`을 실행하면 실제 탭 이동과 canonical pin 검증을 반복할 수 있다. Scatter와 Explorer의 상세 시나리오는 기존 `validate_scatter_browser.mjs` 및 `validate_explorer_browser.mjs`를 사용한다.

최종 확인 시 디스크 여유는 약 3.9 GiB였다. 검증용 Vite 포트 5191은 종료했다. 기존 caffeinate 두 프로세스가 유휴 절전을 계속 방지한다.
