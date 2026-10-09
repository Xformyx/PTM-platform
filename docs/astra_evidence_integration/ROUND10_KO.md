# 회차 10 — 저장된 시간 근거의 reader 연결

2026-10-09–10 로컬 구현·검증. 기준 main `11db1e5e34178c96aa1814a8eb6feb8d741463a5`. 직접 main에서 작업했고 기존 미커밋 `codex-inputs/`는 보존했다. 운영 배포·flag 변경은 하지 않았다.

부모 패키지: `g0-1f09d0d2622540cb894a61e0bf1b1aa0`.
새 reader revision: **`g0-02484ac7623548fe970d9f88f57ea2e1`**.
새 과학 계산·방법 개발·문헌 조회 없이, 저장된 행의 출처와 해석 범위를 연결했다. 과학적 성능 개선이나 생물학적 검증 결과가 아니다.

## 변경과 실제 호출 경로

| 파일 | 변경·재사용 |
| --- | --- |
| `ptm_shared/astra_reader_temporal.py` | 순수 reader projection/검증/직렬화. 원본 값·JSON 벡터·NA를 복사하고, source table + 실제 PK/복합키를 연결한다. 추정기·시간 분석·선정 함수 없음. |
| `ptm_shared/astra_reader.py` | 기존 `build_reader_tables`가 카드 생성 후 projection을 붙인다. `validate_reader`와 `write_reader`에 시간 근거 검증·출력을 연결한다. 기존 카드/선정 엔진 유지. |
| `ptm_shared/astra_evidence_v6.py` | 새 reader 모듈을 기존 `CODE_FILES`에 추가. 과학 계산 함수 변경 없음. |
| `ptm_shared/astra_reader_revision.py` | 기존 manifest 기반 복사를 `_copy_package`로 공용화. `revise_temporal`은 기존 `read_tables`, `write_tables`, `write_reader`, `seal_archive`를 사용하고 `revise_literature`/collect는 호출하지 않는다. |
| `scripts/replay_astra_reader.py` | 패키지 코드가 요구하는 저장 temporal 표를 읽고 기존 reader replay 수행. nullable object dtype도 archive dictionary에 따라 읽는다. |
| `scripts/revise_astra_temporal_reader.py` | 실제 개정 CLI. 계산·검색·원본 findings 재선정을 호출하면 실패하는 guard를 둔다. |
| `scripts/validate_astra_temporal_reader.py` | 원본/개정 bytes, 모든 projection 행, feature 값과 원 contrast, 상대 링크를 독립 대조한다. |
| 관련 테스트 3개 파일 | 새 연결 경계 회귀 추가, 기존 전체 replay 테스트의 예상 reader 산출물 수만 +3 갱신. 이번에 전체 과학 replay는 실행하지 않았다. |

일반 v6 연결은 `astra_evidence_v6.augment → 기존 build_reader_tables → attach_temporal`, `write_artifacts → write_reader → write_temporal`이다. 저장 표를 공급한 fixture에서 실제 기존 builder 호출과 산출물을 검증했다.

실제 HIRc-B 실행은 `revise_temporal → read_tables → attach_temporal → validate_reader → write_tables(reader/packet만) → write_reader → seal_archive`였다. 기존 15개 findings를 다시 선정하지 않았다. Writer에서 기존 `write_phosx_time_views`와 문헌 `write`는 **저장 결과 직렬화만** 재사용했다.

## 감사: 이미 있던 결과와 추가 소비

기존 reader에는 카드별 실제 시간·U/P/A·joint mask와 기본 pattern label이 있었다. 회차 09-B의 PhosX 시간 표도 이미 연결되어 있어 유지했다. 아래 저장 temporal 특징과 sensitivity는 주로 원본 CSV에만 있었고, 정확한 feature/interval/cowave 키로 authoring packet·question map까지 연결되지 않았다.

| 기존 산출물 / 생성 함수 | 전체 행 | 새 reader에 연결한 고유 행 |
| --- | ---: | ---: |
| `temporal_series` / `astra_temporal.integrate_temporal` | 1 | 1 |
| `ptm_temporal_features` / 위 함수의 `feature`, `measured_features` | 11,296 | 60 |
| `protein_temporal_features` / 같은 경로 | 18,601 | 30 |
| `kinase_temporal_features` / 같은 경로 | 8,974 | 23 |
| `interval_contrasts` / `evidence_temporal.adjacent_contrasts` | 16,944 | 90 |
| `kinase_fixed_membership` / `astra_temporal.integrate_temporal` | 53,844 | 138 |
| `target_excluded_anchors` / 기존 `compute_target_trajectory_evidence` 경로 | 3,252 | 25 |
| `group_excluded_cowave` / `evidence_temporal.excluded_cowave` | 6,504 | 50 |
| `kinase_temporal_profiles` / 기존 candidate scoring | 53,844 | 138 |
| `substrate_contributions` / 기존 candidate scoring | 21,219 | 156 |

위 생성 함수들은 이번 실행에서 **호출하지 않았다**. 기존 결과만 읽었다. 중복 count를 독립 근거 수로 쓰지 않으며, 여러 finding이 공유한 행은 inventory에서 고유 원본 키로 센다. 요약 밖의 모든 행은 원래 CSV와 링크로 보존한다.

기존 `cross_layer_links`와 PhosX native 결과도 그대로 보존했다. 새 lag/causal 판단을 만들지 않았고, parent는 `quant/summary.parent_pg`의 정확한 protein group과 같은 series로 연결했다. PG/strict unmodified protein trajectory는 `P_joint`와 다른 track임을 명시한다.

## 15개 finding의 연결 상태

모두 원래 ID·순서·원문 질문·관측을 유지했다. **시간 특징 연결 15, 미연결 0, 모호 0**. 각 finding에 PTM 4 tracks와 parent 2 tracks, 인접 비교 6행을 연결했다. 후보 기여도가 있는 finding은 4개, 없는 finding은 11개다. 기여도 부재를 시간 근거 전체 부재나 biological negative로 바꾸지 않았다.

| 원래 순서 / 표시명 | finding ID | 후보×track 연결 | 제외 결과 행 |
| --- | --- | ---: | ---: |
| 1 DOCK7 | `finding_cf8f4249c4fa5bd2be47` | 0 | 0 |
| 2 SIK3 | `finding_8d461aa65e3c36763221` | 0 | 0 |
| 3 RBM26 | `finding_ac77a2145e4e726099e4` | 0 | 0 |
| 4 ITPR1 | `finding_6ff9b5317c9757cd32df` | 1 | 0 |
| 5 OSBPL3 | `finding_46014d4da0dbfc4c3eb5` | 0 | 0 |
| 6 GTPBP1 | `finding_73ec03a8ce3caf8e4155` | 0 | 0 |
| 7 ULK1 | `finding_2114f9540b7df28b918f` | 9 | 27 |
| 8 SMARCC1 | `finding_8db4d4e823a204a0e06c` | 0 | 0 |
| 9 PALLD | `finding_07f274450364a1c20919` | 0 | 0 |
| 10 PCBP2 | `finding_fec46f1f1b3e76d0404f` | 0 | 0 |
| 11 SPECC1L | `finding_2facbbc04ff9a833d825` | 0 | 0 |
| 12 RPLP0 | `finding_5655109b0640a68315be` | 7 | 21 |
| 13 TELO2 | `finding_4b06279febeea1746cdd` | 9 | 27 |
| 14 SEC16A | `finding_7b649b1f8325352ca0e9` | 0 | 0 |
| 15 PNN | `finding_21636fa7f4f9f9b08727` | 0 | 0 |

Matching은 form → 카드의 arm/reference/pairing → 저장 series의 contrast IDs로 한다. Candidate는 해당 form을 실제로 포함한 contribution의 candidate/track/site/group 키를 사용한다. 같은 gene/표시명은 join에 사용하지 않는다. 중복 PK는 실패하고, 여러 series/feature scope가 맞으면 ambiguous로 남긴다.

## 실제 사례: 원본 행이 추가로 설명하는 범위

사례는 원래 순서의 첫 두 finding과, 이후 처음으로 `computed` 제외 결과가 있는 finding을 사용했다. 예상 경로나 효과 크기로 findings를 바꾸지 않았다. 아래 소수 표시는 설명용 반올림이며 JSON/대응표에는 원값을 보존한다.

1. **DOCK7 후보 S1423** (`form_5f6b1591279b085d`). `ptm_temporal_features`의 `feature_6587835ed9bd2bce90c6`, A track: 절댓값 최대 관측은 15분, signed peak `+0.5447439697010603`. 저장 onset bracket `[5,15]`, recovery bracket `[15,30]`; threshold 0.5, threshold-sensitive, LOTO 5/6, 관측 6점. `interval_25faa4aeec64a4684f33`의 5→15분 A는 `+0.23788518312395368`; `interval_30b338ced4cf61288751`의 15→30분 A는 `−0.10508963163659502`. 정밀한 발생·회복 시각은 알 수 없다. 연결된 candidate contribution은 없으며 kinase support를 추정하지 않았다.
2. **SIK3 후보 S779** (`form_0307f4dc0d707fd5`). `feature_a14498e23d1c7c558d60`, A: 15분 signed peak `+0.9787728140422836`. onset lower는 NA, upper 1분으로 left-censored이고 recovery bracket은 NA, right-censored다. 첫 관측부터 operational threshold를 넘은 상태이며 정확한 시작 시각은 확정할 수 없다. `interval_d3380e71e889d50b4c6f`에서 1→5분 A `+0.3656143501674016`, `interval_a034286233d258f3b0ae`에서 15→30분 `−0.24344759200567623`. 관측 6점, LOTO 1.0이나 threshold-sensitive이며 biological significance가 아니다.
3. **ULK1 후보 S450** (`form_aee8bfc47ce1a311`). `feature_233e4073dac417df10c1`, A: 30분 signed peak `+0.5379625936409225`, onset `[15,30]`, recovery `[30,60]`. 저장 인접 행 `interval_178cd9b7d7239353fff4`의 15→30분 A `+0.2664942007158402`, `interval_f539cbfebc6ffe222e32`의 30→60분 `−0.39866124650380463`. 180분에는 다시 operational threshold 이상이므로 앞 recovery bracket을 영구 회복으로 설명하지 않는다.

ULK1에 연결된 `candidate_104bbab4968a374908a4`는 **CDK/MAPK (Pro-directed), motif_A**이다. `series_5fbe10ec151c613c0e74`에서 공통 기질 138, 시점별 available 149/150/151/148/145/147이므로 available/fixed 값을 함께 제시한다. 첫 1분의 entered=149는 비교 집합 초기화이며 emergence 149건이 아니다.

같은 `site_15426259a5511f9b5113`에 대해 target 제외 r=`0.32296118688372744`, gene 제외 r=`0.314966695836053` (`cowave_21b99316466cd356589d`), measurement-group 제외 r=`0.32296118688372744` (`cowave_35a8efa54eb20dd3b324`), 각각 interval concordance=0.6이다. Gene 제외 대상은 `10116:Ulk1`, 남은 site keys 150; group 제외 대상은 `measurement_36311518fa7180d12b24`, 남은 site keys 151이다. Target 제외는 원 저장 결과에 남은 site ID 전체 목록이 없어서, 원문 details의 **구간별 anchor 수**만 제공한다(첫 구간 n=144, fixed common groups=136). 남은 site 목록을 추정하여 생성하지 않았다. 약한 양의 정합성과 일부 불일치가 남는다는 기술적 설명까지만 가능하며, 독립 검증·개별 kinase 판별·인과 근거가 아니다.

## Reader와 작성 지침

`START_HERE_ASTRA.md → reader/READ_ME.md → reader/TEMPORAL_EVIDENCE.md`로 이동한다. 같은 위치의 `temporal_evidence.json`에 원본 행·값·NA·관측 수·run IDs·민감도 details를, `temporal_links.csv`에 finding→실제 source key와 역할을 저장한다. 총 1,049개 고유 finding/source 연결이다.

`authoring_packet.temporal_evidence`와 `authoring_rules.temporal_evidence`는 추가 시간 주장에 feature_id/interval_id/cowave_id 또는 정확한 table+복합키와 finding_id를 요구한다. 원래 카드 ID 규칙도 유지한다. 저장 질문 `BQ-001`에 15개 findings와 1,049개 temporal source links를 추가했다. 답변 범위는 표본 시점의 관측 구간·절댓값 최대 변화·인접 비교·같은 자료의 민감도이며, 정밀 event time/인과/독립 검증은 제외된다.

문헌 상태 `retrieved_comparison_pending` 및 기존 문헌 evidence/질문 원문은 그대로다. Localization 미측정, no-call/calibration 제한도 유지한다. PhosX native score/p/q와 log2 descriptive footprint는 별도 자료이며 native score에 새 onset/peak 규칙을 적용하지 않았다.

## 검증과 산출물

| 검사 | 실제 결과 |
| --- | --- |
| 원본 정량 CSV | 22/22 byte-identical |
| 원본 dictionary 표 전체 | reader/packet을 제외한 78/78 byte-identical; PhosX·temporal 포함 |
| 그림·source/literature pin | 그림 25/25, 모든 references 파일 보존 |
| 원 packet | temporal 추가 필드만 제거하면 원 packet과 동일; 15개 ID·순서·관측·문헌 상태 보존 |
| projection | 1,049개 원본 행 exact 비교; 시간 feature 관측점 696개를 원본 contrast 값·NA·시간과 대조 (atol/rtol 1e-10) |
| reader replay | 최종 archive 내부 코드로 21/21 산출물 byte-identical; 네트워크 0; 16,944 source rows, 14,658 cards, 15 findings 검증 |
| 표·링크 | Markdown 98개 표/613개 header 포함 행의 열 구조 검증; 상대 링크 103개 유효. DOCK7·제외 민감도·PNN 표를 실제 렌더링하여 직접 확인 |
| 관련 회귀 | 12 passed, 1 deselected, 1.48초. 다른 reference/arm/track, 동일 표시명, 중간 NA, fixed score NA, duplicate/ambiguous, nullable bool, 질문/작성 지침, 실패 시 pointer 보존 포함 |
| PhosX method replay | 미반복. 방법 코드·자원·입력·결과가 불변이며 이번 변경은 reader 경계뿐 |

최초 봉인 시 nullable boolean의 문자열/자동 추론 타입 차이를 검출하여 수정했고, 그 실패 run은 게시하지 않았다. 이후 reader replay 중 `/tmp`의 이전 venv 파일 소실로 import가 실패하여, 동일 pandas/numpy/scipy 등 reader 의존성을 새 `/tmp/ptm-round10-reader-venv`에 복원했다. 최종 replay와 테스트는 이 환경에서 통과했다. 기록은 [ROUND10_READER_ENVIRONMENT.lock](ROUND10_READER_ENVIRONMENT.lock)에 있다. 원 계산 환경과 PhosX 설치를 갱신하거나 재실행하지 않았다.

```sh
env PYTHONPATH=.:workers /tmp/ptm-round10-reader-venv/bin/python -m pytest ptm_shared/tests/test_astra_reader_temporal.py ptm_shared/tests/test_astra_reader.py ptm_shared/tests/test_phosx_reader_time.py -k 'not real_v6_package_invocation' -q
env PYTHONPATH=.:workers /tmp/ptm-round10-reader-venv/bin/python scripts/revise_astra_temporal_reader.py --package <부모 package 디렉터리> --output <새 출력 폴더>
env PYTHONPATH=.:workers /tmp/ptm-round10-reader-venv/bin/python scripts/validate_astra_temporal_reader.py --before <부모> --package <개정 package> --output <검증 JSON>
env PYTHONPATH=.:workers /tmp/ptm-round10-reader-venv/bin/python scripts/replay_astra_reader.py --package <개정 package> --output <비어 있는 replay 출력 폴더>
```

기존 전체 v6 portable test는 과학 계산을 실행하므로 이번 범위에서 제외했다. 수정된 전체 replay 산출물 개수 assertion을 실행 통과했다고 집계하지 않는다. 변경된 builder 경계는 저장 표 fixture로, 패키지 경계는 실제 reader 개정/오프라인 replay로 검증했다.

새 ZIP: `codex-inputs/round10-20261009/output/astra_analysis_package_g0-02484ac7623548fe970d9f88f57ea2e1.zip` (316,909,006 bytes).
SHA-256: `c710ad40ebc75f5bb41a4eb5e505c690003c62d92a4e0d6c9a7747f2ce8bd9a3`.
Reader: `codex-inputs/round10-20261009/output/enrichment_free_runs/g0-02484ac7623548fe970d9f88f57ea2e1/reader/TEMPORAL_EVIDENCE.md`.
개정·봉인·검증 실행 128.70초(과학 계산 없음). 부모 패키지와 부모 성공 pointer는 보존했고 별도 출력 폴더의 pointer만 봉인 성공 후 갱신했다.

상세 결과·hash·대표 source key는 [ROUND10_RESULTS.json](ROUND10_RESULTS.json). 원시 입력·ZIP·임시 결과·비밀 설정은 커밋하지 않는다. main 반영은 코드·테스트·이 보고서만 대상으로 하며, 과학적 우월성이나 독립 검증 완료를 주장하지 않는다.
