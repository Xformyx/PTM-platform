# 검증 기록 — 2026-10-02

기준 commit: `6386c553e26530d887649e8a008f19c0938b8bb7`.
평가 계약을 먼저 고정한 commit: `703aace7e5a23db0bfadf1d1b7dab472f11924c2`.
개발 브랜치: `feature/astra-science-v5`. 운영 배포는 수행하지 않았다.

## 실제 수행한 검사

- Python 3.14.6, numpy 2.5.3, pandas 3.0.6, pytest 9.1.1, pyarrow 25.0.1의 프로젝트 전용 venv.
- `python -m pytest -q ptm_shared/tests/test_astra_science.py ptm_shared/tests/test_astra_package.py ptm_shared/tests/test_generic_study.py ptm_shared/tests/test_enrichment_free_evidence.py ptm_shared/tests/test_species_site_mapping.py api-server/tests/test_analysis_context_preservation.py api-server/tests/test_astra_input_capture.py`: 84 passed (53.56 s). API 테스트에는 프로젝트와 api-server PYTHONPATH 및 격리 SQLite URL을 사용했다. 최종 로그: `regression-final.log`.
- `node --experimental-strip-types --test frontend/tests/analysisContext.test.ts`: 3 passed.
- 프런트엔드 `npm run build`: 통과. 기존 번들 크기 경고가 남는다.
- `scripts/validate_astra_platform.py --science`: 실제 FastAPI → MySQL → Redis → Celery → archive. 생성/복사/질문 수정/재실행, SHA 검증, 서로 다른 arm, 원문 전달 누락 0 확인. 새 v5는 정량 cache 재사용을 아직 구현하지 않아 `computed`로 기록한다.
- 같은 API 검사에서 mouse 선언 + human FASTA는 실행 전 422 `species_reference_conflict`; 주문은 registered 상태 유지. PG만 있는 mouse protein-only cross-sectional 실행은 완료, kinase/temporal은 not_applicable.
- `/orders/create-from-user`의 업로드·자동 시작도 같은 resolver/dispatch로 실행하여 DIA-NN 관측 audit까지 확인했다.
- `scripts/validate_astra_browser.py`: 실제 로컬 Chrome에서 결과 다운로드, 입력 미리보기, 복사/시작/재실행. 콘솔 page error 0. 재입력할 species/replication/snapshot 창을 추가하지 않았다.
- 합성 human/mouse 각각 57개 scientific CSV를 offline replay. ID/text/NA와 값(atol=rtol=1e-10)을 비교. 이는 종별 생물학적 성능 검증이 아니다.

위 로그/산출물은 저장소 내 `codex-inputs/astra-science-20261001/`에 보관한다. 원자료와 대형 산출물은 Git에 커밋하지 않는다. 테스트 계정, 환경 파일과 비밀번호는 전달 자료에 포함하지 않는다.

## MS 인수 사례

| 사례 | 상태 | 실제 근거/범위 |
|---|---|---|
| MS01 | passed, synthetic | human/mouse 같은 입력 U/P/A 동일한 예상값; site taxon 분리. enzyme taxon 근거가 없으면 unknown 유지 |
| MS02–03 | passed | 양방향 species conflict unit test; mouse/human 불일치 실제 API 422 |
| MS04 | passed | manifest ID로 human reference 선택; 앞선 mouse 파일 무시; checksum 변조 거절 |
| MS05 | passed | 누락 worker taxonomy와 잘못된 species 오류; 새 분석 종 기본값 없음 |
| MS06 | passed, synthetic | OX/GN 없는 등록 mapping 및 checksum provenance; 미등록은 제한 상태 |
| MS07 | passed, synthetic | 공유 peptide 두 taxon mapping은 한 measurement group, site 귀속 부적격 |
| MS08 | partial | explicit mixed inventory/허용 taxa 테스트. 실제 xenograft/co-culture 입력은 미확보 |
| MS09 | passed, synthetic | explicit decoy 제외 및 biological taxon inventory 구분 |
| MS10–11 | passed | cross-sectional PTM/protein replay; 실제 mouse PG-only API/worker 완료 |
| MS12 | passed | PG 없는 PTM은 `parent_input_required`, U-only 실행 미지원 명시; 가짜 A 없음 |
| MS13 | passed, inherited fixture | KEA native human 제한 유지, mouse는 not_supported. projected KEA adapter 미구현 |
| MS14 | passed | FASTA/report/version/QC/resource/code dependency fingerprints. 구 run 불변 |
| MS15 | passed, synthetic | human/mouse offline scientific table replay. 실제 human/mouse 원자료 미확보 |
| MS16 | passed, local | 관리자·사용자 API, copy/rerun, worker, Results; Order species와 reference 재사용 |

## 측정·계산 실패 사례

다른 run/charge, basename 불일치, 중복 관측, library-only confidence, 0–1 범위 밖 값과 잘못된 숫자, TSV/Parquet 연결을 확인했다. 보고서 confidence를 individual-site posterior로 복제하지 않는다. 검증된 관측 필터는 PTM/PG 공동 mask와 한 번의 정규화로 다시 계산한다. 특정 gene/window가 같아도 위치별 site ID는 유지되고, 공유 mapping은 독립 측정으로 늘지 않는다. 실제 DIA-NN long/site report와 공식 버전별 parity는 미검증이다.

기존 parent identity, 기술 반복 biological p/q 결측, emergence, fixed membership, target 제외와 gene/group 제외 anchor, 패키지 header/FK/hash/중단 보호 검사를 유지했다. Synthetic specificity 행렬의 합·곱/percentile, residue/말단 제한은 확인했지만 실제 atlas scorer와 비교하지 않았다.

## 불확실성 진단

`scripts/simulate_astra_unit_intervals.py`: paired Gaussian 효과, technical measurement 중복, n=3/8/20, 효과 0/1 각각 300회, seed 20261001. 95% percentile 구간 포함률은 n=3에서 양쪽 0.7533, n=8에서 0.8833/0.8667, n=20에서 0.9033/0.9467이었다. 작은 n의 undercoverage가 확인됐다. 이 모듈은 기본 비활성, experimental이며 검증된 biological CI 정책으로 출시하지 않는다. 기술 반복에는 biological interval/p/q가 생성되지 않는다. 이 simulation은 biological benchmark 또는 calibration이 아니다.

## 미수행/미확보

실제 human/mouse proteome 각 1세트, 실제 DIA-NN long/site report+crosswalk+search FASTA, 허용된 실제 Ser/Thr·Tyr atlas와 공식 scorer, 독립 calibration/locked test, 독립 perturbation/WB/PRM이 필요하다. 각 단계는 unavailable/pending/uncalibrated이며 성공을 생성하지 않는다. Source live smoke와 운영 shared registry/API/UI는 이번 v5 검증에서 수행하지 않았다. Astra-only 보고서 품질 비교, KSEA/PTM-SEA/PhosX/KSTAR 공식 결과 비교도 수행하지 않았다.

## 실제 HIRc-B 회귀와 v4 비교

`validate_hircb_independent.py --inputs codex-inputs --reference codex-inputs/hircb_reference --output ...`로 기존 reference estimator를 재실행했다. 177,116 PR/9,525 PG, 2,824 forms, 2,625 parent eligible, 2,101 평가 가능 forms, 11,920 primary 비교, 3,948 reference profile 조합, baseline 미검출 287/처리 후 반복 검출 261을 유지했다. 기록된 59,304 runlevel 및 전체 16,944 비교의 키·mask·값 회귀가 통과했다. 기존 shared 계산 모듈을 사용한 회귀이며, 정량 알고리즘을 독립적으로 다시 개발한 검증으로 표현하지 않는다.

`validate_astra_science_archive.py`는 기존 self-contained v4 패키지의 PR/PG/FASTA/source pin으로 **새 v5 실행**을 만들었다. 비교 결과:

| 항목 | 결과 |
|---|---|
| v4→v5 quantitative CSV | 22개 모두 값/ID/NA/mask 동등, 22개 byte-identical |
| v5 package-only replay | 57개 scientific table, 57개 byte-identical |
| v5 forms / parent eligible / proteins | 2,824 / 2,625 / 9,525 |
| v5 primary / repeated comparisons | 13,704 / 11,920 |
| v4→v5 candidate entities | 343 → 338 |
| v4→v5 edge rows | 50,568 → 50,568 |
| v4→v5 profile rows | 26,754 → 28,392 |

Generic estimator는 side당 ≥1 joint 관측을 허용하므로 13,704와 reference 11,920를 구분한다. Profile 행 수 증가는 새 specificity track의 빈/no-call 조합도 포함하며 새로운 kinase 발견 수가 아니다. Entity/ID 차이는 enzyme taxon 및 식별 계약 변경에 따른 것으로 정확도 개선의 증거가 아니다. Actual specificity resource는 없었고 확정 call은 0이다.

이 실행의 source pin은 `c1826b838baa2082d30a90f316164237fc94dffa445f9a5cd6f319fbe74291db`이다. Reference 회귀 snapshot `80c9ae707a853169b6890a1e393f72f9f0b57edbf94e0c1e6f61dec57594de07`과 다른 종류의 식별자다. 각각의 package에는 실제 실행한 소스 hash와 dependency pin이 들어 있다. 개발 중 실패한 부분 출력은 인계용 정상 패키지로 사용하지 않는다.

Standalone replay에서 발견한 누락 `species_registry.py`를 추가했으며 human/mouse subprocess 검사로 회귀를 고정했다. 저장소 내부 import 성공만으로 portable replay를 통과 처리하지 않는다. 최종 합성 API 다운로드도 57/57 byte-identical replay를 통과했다.

정상 자료 위치: `hircb-final/validation.json`, `hircb-final/all_quant_parity.json`, `hircb-final/offline_replay/replay_result.json`, `platform-delivery/validation.json`, `delivery-replay/replay_result.json`, `browser-delivery/validation.json`. 위 경로는 모두 `codex-inputs/astra-science-20261001/` 아래이다. 과학 코드와 CSV는 각각의 archive에 포함되며 대형 원자료는 Git push 대상이 아니다.

등록 reference의 inline taxonomy mapping도 파일 입력으로 고정하여 API/worker/archive에서 보존한다. 최종 회귀는 원 registry FASTA/manifest를 제거한 뒤 패키지 내부 자료만으로 이 custom-reference 계산을 재현한다. HIRc-B/로컬 UI 통합 산출물을 만든 이후 specificity 파일의 이름 공간 분리와 등록 reference metadata 전달을 보완했으며, 각 기존 산출물은 그 실행 시점 코드를 보존한다. 이 두 보완은 최종 84개 회귀에 포함했고 실제 HIRc-B의 업로드 FASTA/미제공 specificity 계산값을 변경하지 않는다.

최종 HIRc-B v5 측정: 정량 177.42초, 후보 탐색 8.83초, footprint 109.35초, temporal 56.56초, 조립 27.45초, ZIP 게시 27.09초; 기록된 peak RSS 4,537,499,648 bytes, ZIP 173,864,911 bytes. Source query ledger 24행은 실제 HTTP 요청 24회를 뜻하지 않는다. 이 실행은 frozen pin을 사용했다. 동일 하드웨어/동일 정책 성능 baseline을 별도로 측정하지 않아 성능 개선 주장은 하지 않는다.
