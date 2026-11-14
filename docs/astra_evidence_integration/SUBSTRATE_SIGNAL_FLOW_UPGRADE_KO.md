# 기질 시간 반응 기반 신호 흐름 연결 — SF01–SF06 최종 보고

2026-11-14. 작업 시작 main `92a3776fcc3747b981a77a4ff0838811b5a9b150`; branch `codex/substrate-signal-flow`. 원격은 `Xformyx/PTM-platform`임을 확인했다. 검토 기준 `fe11ff8` 이후 AI01–AI06-B와 Control 개발이 반영된 로컬 코드를 재사용했다. 기존 untracked codex-inputs와 입력·과학 결과를 보존했고 push/배포/flag 변경은 하지 않았다.

## 단계와 로컬 commit

| 단계 | 완료 내용 | 로컬 SHA |
|---|---|---|
| SF01 | 전체 form × canonical effect series × track, 원본 key/mask/time/ref | cbf3f44 |
| SF02 | 전체 kinase substrate association/membership, variable/fixed 및 제외 진단 | 300172d |
| SF03 | 관측 bracket·exact prior·계산 의존성·가설 분리 | aba72b2 |
| SF04 | Classic All/N/mode 수정, 전체 탐색 API/React/Atlas identity | 5eeb0aa |
| SF05 | 일반 발행·revision·replay·그림·writer 공통 소비 | 87fe6a1 |
| SF06 | 실제 저장 표/ZIP/replay 검증, 연결 오류 수정·최종 보고 | c01d602 |

구현·검증 최종 commit: `c01d6021a18780cc27c170279d17d4cb0ead19d7`. 이 보고서의 SHA 기록은 별도 docs commit으로 확정한다. 패키지의 변경된 reader 모듈9개 hash가 이 commit의 코드와 일치함을 확인했다.

단계 문서: [SF01](SUBSTRATE_SIGNAL_SF01_KO.md), [SF02](SUBSTRATE_SIGNAL_SF02_KO.md), [SF03](SUBSTRATE_SIGNAL_SF03_KO.md), [SF04](SUBSTRATE_SIGNAL_SF04_KO.md), [SF05](SUBSTRATE_SIGNAL_SF05_KO.md), [SF06](SUBSTRATE_SIGNAL_SF06_KO.md). 기계 판독 결과: [RESULTS](SUBSTRATE_SIGNAL_RESULTS.json).

## 실제 호출 경로와 계약

| 저장된 원본 | 공통 projection / 재사용 함수 | 소비 |
|---|---|---|
| quant/comparisons, form_identity, ptm_temporal_features | trajectory_projection; effect_series.resolve_series; TABLE_KEYS/source registry | 전체 form/track 궤적, 원 U/P/A·NA·mask와 실제 point Control |
| candidate_edges, contributions, profiles, fixed membership, anchors, sensitivity/inference, method scores/membership | kinase_projection; 원 edge/contribution/member key 검증 | candidate × series × track/method 묶음, 기존 점수와 count 단위 분리 |
| 저장 onset bracket, exact native site prior | observed_order / evidence_map | membership·방법 기여·same-parent·관측 선후·prior·review_required 가설 |
| 발행 pointer/provenance → EvidenceCatalog | substrate_signal_view.signal_page → FastAPI substrate-signal | OrderDetail → SubstrateSignalFlow → form → candidate → membership/관계/가설 |
| Legacy TSV/feature identity | 기존 load_vector_view/plot_selection, FullTrajectoryBrowser, Atlas exact context | per-condition/global/all, conventional/LOD/intensity 분리 |
| write_reader → write_signal_flow | 저장 CSV/dictionary/실행 study_design으로 projection; CODE_FILES/READER_CODE_FILES | signal_flow 7개 CSV, guide, packet, U/P/A SVG/PNG/point CSV |
| writer_node → load_report_signal | 발행 pointer·packet hash 검증 → temporal/biological formatter; saved_signal_figure | 동일 trajectory/bundle IDs와 quantitative binding, 전체 source locator |
| immutable revise_temporal / bundled reader_replay | 기존 atomic seal/pointer; manifest 검증/격리 interpreter | 새 revision과 archive 자체 코드 replay를 분리 |

새 score·정량·kinase·temporal 엔진은 없다. source/evidence ID를 바꾸지 않고 추가 bundle/link ID만 별도 namespace로 만든다. Top-N/pin/페이지는 projection 입력이 아니므로 전체 population을 줄이지 않는다. 카드 보류와 quant eligibility는 독립이다. 미기록 gene/localization/pair/prior를 보완 추정하지 않는다. 정확한 Legacy→Astra crosswalk가 없으면 unavailable이며 symbol-only로 합치지 않는다.

반복 metadata를 method마다 복사하던 초기 projection은 실제 표에서 약10GB까지 커져 발행 전에 중단했다. 최종 구현은 candidate association 공통 표와 compact exact key 집합을 사용한다. 숫자를 다시 합산하거나 membership을 제거한 최적화가 아니다. native selected=false는 조회되지만 기여 count와 contribution edge에서 제외된다.

## 검증 수준

| 수준 | 확인한 내용 | 결과/한계 |
|---|---|---|
| 합성 production 함수 | scope/identity/Top-N 독립, excluded trace, variable/fixed NA·turnover, 동일 support, exact prior 반대 순서, no-call, API auth/cursor/변조, U/P/A report binding | 고유 70 tests, 실패 0, skip 0 |
| 기존 C03 작은 과학 fixture | 6개 matched 시점, mixed pairing, arm/family, 중간 NA, 실제 mask·interval, 미계산 biological p | 기존7개 시나리오 재사용; 실제 주문 검증 아님 |
| 브라우저/build | 실제 React+Chrome, 합성 API; form→bundle→membership/관계, pin/page, U/P/A 범례 | build/브라우저 통과; 운영 UI는 미검증 |
| 실제 저장 결과 | G11 후속 자료에서 전체 source projection 및 source→bundle→map→hypothesis→figure→writer formatter | 84,720 point 값/NA/mask/시간/Control 일치, 13,704 적격 joint U−P=A 확인 |
| 실제 reader revision | 저장된 과학 표·pin으로 새 표시/metadata 생성 | 원본 273 files와 입력·ZIP·pointer hash 보존; 새 revision 내 116 보존 hash 검증 |
| archive 자체 코드 replay | 저장소 밖 cwd, PYTHONPATH 없음, -I -B, 공백 포함 새 출력, science/network guard | 56 reader 산출물 byte 동일, manifest 288 files 검증 |
| 실제 matched / 운영 / 신규 보고서 | 접근 가능한 실제 time-matched 주문 없음; 운영 DB/queue/download 및 신규 모델 보고서 미실행 | 미확인. 합성 통과를 운영·예측 정확도·인과 검증으로 보고하지 않음 |

실제 실행 설계는 동일 reference `condition_32d7e82082479b8c`를 공유하는 6개 target contrast다. 구형 실행 metadata의 policy 문자열을 그대로 보존했으며 이를 사용자가 새 radio를 선택한 증거로 바꾸지 않았다. 21 injection의 저장된 technical/material 구조와 unknown pairing을 유지했다. actual biological p/q는 계속 미계산이다.

추가 출력: trajectory/형태 membership 각각14,120행(2,824 forms ×5 tracks), candidate associations639, kinase bundles9,256, kinase membership663,597, typed links283,422, hypotheses9,256. 이 값은 독립 biological n이나 kinase 활성 수가 아니다. 7,261개 finite excluded track point는 calculation trace로만 남는다. 8,092개 관측 순서 링크 중 실제 분리 bracket의 observed_before는26, 겹침 unresolved4,864, 평가불가3,202다. exact prior33개와 missing prior 상태를 분리하며 모든 인과 상태는 not_established다.

대표 저장 관측: `form_8364bc9621787603`의 A는 5분0.6231, 60분−0.2061; `form_dad67340d209cde3`는 15분−0.7197, 180분1.3545다. 이는 sampled response 예시이며 kinase activation onset이 아니다. 합성 K1/K2 동일 support는 family가 아닌 구별 불가 후보 집합이고, 유일 기질 제외 후 anchor 없음·fixed-common NA가 유지된다. 실제 inference의 uncalibrated/not_evaluable도 보존한다.

실제 대표 query는 `form_id`와 `effect_series_id`, `evidence_type=ptm_contrast`로6개 원본 행을 batch로 회수한다. entity는 gene/accession 검색이므로 form ID를 entity 문자열로 보내지 않는다. source resolve와 claim checker에서 anchor/numeric/restriction은 통과하지만 semantic_review는 not_performed다. 원래 citation을 새 run으로 소급 변경하지 않았다.

## 보존과 의도한 변경

원본 PR/PG/FASTA, source/literature pin, native 점수/membership/calibration, U/P/A·NA·mask, source/evidence IDs, 기존 성공 ZIP/pointer는 hash 검증으로 보존했다. actual original273파일은 수정되지 않았다. 전체 catalog의175,537개 evidence_id/source_table/source_key도 원본과 동일하다. 새 ZIP hash와 새 output pointer 일치 및 원래 pointer hash 보존을 별도로 확인했다. quant/discovery/temporal fingerprint의 kernel 목록과 numeric_design은 변경하지 않았다.

새로운 것은 signal_flow 표, source registry/dictionary descriptors, reader/index/guide/packet, 표시용 U/P/A 그림·point binding과 selection ledger다. 그림은 유효 관측점 수 다음 stable ID 순의 최대12 preview이며 중요도·검토 범위가 아니다. excluded finite A를 일반 heatmap에서 NA로 표시하여 해당 display finite cell이275→263으로 달라졌고 원 quant 값은 그대로다. 기존 numeric 결과 byte 보존과 새 metadata byte 차이를 구분한다.

실제 revision 검증에서 발견한 두 오류도 수정했다. (1) refresh_figures의 전체 재렌더링을 기존 두 heatmap으로 제한하고 대응 PNG/display descriptor를 포함했다. 다른 curve caption/source/point bytes는 유지한다. (2) saved reader revision replay가 새 adapter로 다시 카드를 선정해 frozen pin input hash가 달라지는 경로를 저장 packet/cards 복원으로 고쳤다. pin hash/input/order 검증을 제거하지 않았다. 실제 저장 packet은 원 pin 입력과 일치했다. 실패 후보는 원본이나 최종 성공본으로 재표시하지 않고 별도 task 경로에 남겼다.

## 사용 가능한 산출물

최종 새 reader package: `/Users/josephk/Projects/PTM-platform/codex-inputs/substrate-signal-20261114/final-reader-revision-v3/astra_analysis_package_g0-adfcea86b3504959b75986baf994ade4.zip`

SHA256: `ea3a905d2c5d60ea9735a0f62714f8d6338f38fcc5d6f5ad98964b32a2924926`

실행 디렉터리: `/Users/josephk/Projects/PTM-platform/codex-inputs/substrate-signal-20261114/final-reader-revision-v3/enrichment_free_runs/g0-adfcea86b3504959b75986baf994ade4`. `START_HERE_ASTRA.md` → `reader/SUBSTRATE_SIGNAL_FLOW.md`; `reader/substrate_UPA_trajectories.png`, point CSV, 전체 signal_flow 표를 제공한다. ZIP/manifest와 이 task output의 새 pointer가 일치하며 원래 주문 성공 pointer는 변경하지 않았다.

```sh
python reader_replay.py --output <존재하지 않는 새 디렉터리>
```

검증 출력: `codex-inputs/substrate-signal-20261114/final archive replay v3/READER_REPLAY_VALIDATION.json`.
실제 검증 로그: `SF06_REVISION_RESULTS.json`, `SF06_ACTUAL_FLOW_RESULTS.json`, `SF06_TEST_SUMMARY.json`, `SF06_BROWSER_RESULTS.json`, `SF06-browser.png`, checkpoint.json. 이 경로들은 task 폴더 안에 있다. archive replay는 재생성 point binding을 비교한 뒤 manifest 검증된 frozen SVG/PNG를 재사용한다. 현재 코드 revision의 새 그림 생성과 구분한다.

## 실행·환경 경계

실제 새 정량/PhosX 계산0회, 새 검색/RAG/LLM0회. 합성 package smoke와 기존 C03 작은 함수는 실행했으며 반복 시도를 고유 테스트 수에 중복 합산하지 않았다. 전체 실제 과학 replay/새 native parity/문헌 의미 승인/새 모델 보고서 품질 평가를 수행하지 않았다. 문헌 논문을 이번 실험의 승인 결과로 주입하지 않았다.

기존 runtime/설치된 dependencies를 사용했고 다운로드·전역 환경 변경은 없다. pytest 경고는 기존 pandas/FastAPI deprecation, build는 기존 Browserslist/큰 chunk 경고다. 최종 디스크 여유 3.48GiB. 최종 추가 공간 예산은 실측 source3.37GB+projection1.70GB+ZIP0.65GB+replay2.50GB와3GiB reserve로 계산했다. 불필요한 원본 삭제로 공간을 만들지 않았으며 실패 후보도 task 경로에 보존했다. Vite와 Chrome은 종료했고 기존 사용자 caffeinate는 유지했다. 최종 process audit에서 작업용 Python/Vite/Chrome 잔여 프로세스0개를 확인했다. 기존 caffeinate PID2450/5292는 유지했다.

push/merge/운영 배포/flag 변경은 수행하지 않았다. local source·합성·실제 저장 표·immutable reader 전달 경계까지의 검증이며 운영 완료 또는 생물학적 인과 증명의 보고가 아니다.
