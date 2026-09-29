# Astra 통합 검증 기록

기준 SHA: e5307169fa51fc0ea618ebb891a6c883792608b8. 최종 source SHA는 커밋/인계 manifest에 기록한다. Synthetic fixture 통과는 종별 생물학적 정확도 검증이 아니다. 운영 배포와 Astra 모델 보고서 비교는 별도다.

## 환경과 실행 근거

프로젝트 전용 Python 3.14.6 / numpy 2.5.3 / pandas 3.0.6 환경에서 테스트했다. 별도 Python 환경 비교 결과는 실제 replay 결과에 한해서만 기록한다. 원자료/중간/ZIP/로그는 git에 넣지 않고 `codex-inputs/astra-20260928/`에서 관리한다.

실행 진입점:

```sh
PYTHONPATH=.:api-server:workers python -m pytest ptm_shared/tests/test_astra_package.py ptm_shared/tests/test_generic_study.py ptm_shared/tests/test_enrichment_free_evidence.py ptm_shared/tests/test_motif_candidate_calibration.py api-server/tests/test_analysis_context_preservation.py api-server/tests/test_astra_input_capture.py -q
node --test frontend/tests/analysisContext.test.ts
cd frontend
npm run build
```

로컬 실제 서비스는 FastAPI/MySQL/Redis/Celery/Vite/Chrome이다. 합성 응답 fixture와 live provider smoke는 구분한다. 기본 fixture는 서로 같은 시간의 AB/CuAB, 공동 baseline, 반복 주입, parent 변화, 일부 결측, 등장 PTM, 두 kinase의 공유 기질, 긴 한글/영문 질문과 0/false/[]를 포함한다.

## T01–T48 대응 근거

아래 표의 passed는 적힌 범위의 프로그램 동작이다. 제공되지 않은 독립 생물학적 truth, 운영 배포, 실제 모델 비교까지 확장하지 않는다.

| ID | 상태 | 근거/범위 |
|---|---|---|
| T01 | passed | generic import21 test, 실제 HIRc-B manifest adapter; 21 injection/7 material 관계 |
| T02 | passed | Rep만으로 반복 관계를 확정하지 않는 resolver/Node test |
| T03 | passed | 기술반복 design, 실제 form joint identity, biological p/q 없음 |
| T04 | passed | AB/CuAB 공동 시점 fixture와 실제 API/UI 개별 contrast |
| T05 | passed | 단위 변환/비영점 reference/irregular grid generic tests |
| T06 | passed | 빈 reference root + 정상 frozen provider response에서 자동 수집·pin·후보 실행 |
| T07 | passed | provider timeout fixture와 live partial provider ledger; 정량/motif 유지 |
| T08 | passed | 정상 빈 source cache와 zero-edge table schema; inactive 주장 없음 |
| T09 | passed | 실제 API/UI Copy/Rerun 및 과거 provenance 불변 검사 |
| T10 | passed | 기대 질문만 변경 시 비교/멤버십/profile 동일, 새 context revision |
| T11 | passed | 합성 PTM 4배/parent 2배의 U=2/P=1/A=1 및 전체 identity |
| T12 | passed | all-row parent impact/strict/normalization sensitivity와 범주 |
| T13 | passed | 다른 masks, 복수 accession 단일 PG generic tests; parent/site 계약 분리 |
| T14 | passed | 연구 전체 scaling 1회와 form별 실제 mask/weight A offset 검증 |
| T15 | passed | baseline NA, 처리 후 반복 검출, post-reference; baseline FC 없음 |
| T16 | passed | arm/reference별 detection·post-reference ID, 다른 reference를 평균하지 않음 |
| T17 | passed | 외부 모델 없음 → unavailable; 문서화된 합성 상한 → conditional bound; 원 비교표 불변 |
| T18 | passed | localization 없는 curated 후보·점수 보존, localized subset no-call |
| T19 | passed | 주변 residue만 motif가 맞는 반례, center anchoring 및 배경 중복 불변 |
| T20 | passed / limited | exact target FASTA residue/taxon 검사, 종 mismatch 거절. 독립 ortholog alignment 자료가 없는 translated 관계는 제한을 명시 |
| T21 | passed | form/site dedup과 source/pub 별 필드. 같은 PMID를 독립 biological evidence 수로 채우지 않음 |
| T22 | passed | KEA/network context를 curated edge로 승격하지 않는 typed adapter |
| T23 | passed | KEA FDR only/P only/neither fixtures; nullable 통계 필드 |
| T24 | passed | charge/form/site/gene 집계, multi-site 제외와 measurement group provenance |
| T25 | passed | 동일 substrate membership에 같은 identifiability group; 강제 isoform 배정 없음 |
| T26 | passed | 검출되지 않은 kinase도 candidate/profile 유지, 별도 abundance unavailable |
| T27 | passed | common-set/available profiles, entered/departed membership와 turnover 표 |
| T28 | passed | NA gap을 연결하지 않는 AUC 예상값 187.5, 실제 onset/peak grid |
| T29 | passed | overlapping onset bracket은 unresolved, sparse data의 precise lag unavailable |
| T30 | passed | canonical technical-only series의 paired_biological_units=false; legacy sidecar 미호출 |
| T31 | passed | 기존 target-exclusion engine을 A와 measurement identity로 호출; 대상 그룹 제거 기록 |
| T32 | passed | 전체 PG/strict protein 표 + optional panel, independent validation=false |
| T33 | passed | U/A/strict/normalization impact 및 claim row ID·반대/민감도 근거 |
| T34 | passed | motif-only 및 no-usable-sequence/no-database/provider 부족 이유 분리 |
| T35 | passed | 비인산화·target form 0개 fixture, 전체 단백질 유지, kinase not_applicable |
| T36 | passed / limited | 취소 checkpoint/불완전 파일/atomic pointer. 로컬 HIRc-B 중단의 미발행 확인; 운영 동시 다중 worker stress는 미수행 |
| T37 | passed | input/source/norm/temporal fingerprint 의존성; 정량 cache reuse. downstream stage cache 최적화는 제한 |
| T38 | passed | urllib 차단된 synthetic bundle replay; 실제 HIRc-B replay는 최종 결과 항목 참조 |
| T39 | passed | 손상 bytes/hash, 필수표/schema, 잘못된 feature FK 거절 |
| T40 | passed | 실제 로컬 API 생성→Start→Results 다운로드→Copy→Rerun 및 UI roundtrip; 주문 전환 시 stale preview를 비우는 수정 포함 |
| T41 | passed | worker가 provider/motif/temporal/cross-layer를 호출하고 CSV가 실제 ZIP에 포함 |
| T42 | passed | source CSV all rows와 명시적 그림 preview selection; 낮은 coverage/opposing rows 보존 |
| T43 | passed | snapshot/field manifest/누락 검사 API→worker→archive 왕복 |
| T44 | passed | 긴 UTF-8 질문/줄바꿈/0/false/[]/null/custom extension roundtrip |
| T45 | passed | co_scientist mode에서도 custom questions 보존; 미저장 과거 질문 상태 표시 |
| T46 | passed | all_active/explicit/empty, 실제 collection 목록 pin, 권한별 content_status service tests, 첨부 scope/hash 및 변경 시 pin 무효화 |
| T47 | passed | 과거 결과 불변, 새 context revision 및 origin quant run; 미리보기와 archive 같은 brief |
| T48 | passed | resolver conflict test와 credential field exclusion; raw-only 값 보존 |

## 실제 결과 기록

핵심 Python 52 passed (alias gene balancing 포함), Node 2 passed, frontend build passed. 실제 로그는 final-tests.log 및 최종 인계 manifest에 포함한다. 프런트 빌드의 기존 큰 chunk 권고는 실패가 아니다.

광범위 legacy reorganization 테스트까지 추가로 실행했을 때 105 passed / 2 failed였다. 하나는 기존 biological p/q unavailable 결과의 NaN을 `==`로 비교하는 오래된 BH test이고, 다른 하나는 로컬 `python-docx` dependency 부재였다. 해당 legacy quantification 코드는 이번 작업에서 변경하지 않았다. 이 결과를 전체 suite 통과라고 쓰지 않는다.

합성 실제 API: 최초 및 수정 버전 Create/Copy/Rerun pass. UI: page error 0, 동일 run의 ZIP download checksum, 60분 AB/CuAB 구분, 확정된 반복관계 재질문 없음, 주입 부피/단위 유지, 수동 annotation/snapshot option 없음. 초기 UI test의 존재하지 않는 fixture 문구 기대값을 수정한 뒤 재실행했다.

Live source smoke: OmniPath hit, iPTMnet 일부 hit/종 확인 불가 parse failure, STRING 정상 no-hit, Reactome hit/404, PubMed hit. 초기 요청의 source/reference 필드 누락과 로컬 parser dependency 누락을 보완했다. KEA의 nonhuman uppercase mapping을 실행하지 않았으며 해당 smoke는 not_supported였다. live 응답은 frozen fixture 과학적 정답으로 사용하지 않는다.

## HIRc-B reference

PR/PG/FASTA에서 기존 estimator와 snapshot SHA `80c9ae707a853169b6890a1e393f72f9f0b57edbf94e0c1e6f61dec57594de07`로 다시 실행했다. 원 reference의 mapping/masks/수치/ID 비교가 통과했다.

- 2,824 forms, parent 적격 2,625, 비교 가능 2,101 forms, primary 비교 11,920.
- 기존 profile 3,948행; kinase 수가 아니다.
- baseline 미검출 287, 처리 후 반복 검출 261.
- strict v1/paired 11,451, complete-mask 11,406.
- paired 값이 달라진 2,363개, 최대 차이 1.208435191282705. PF01255 15분 1.6607036157855828, 180분 3.5688557146039495.
- joint parent kinase 민감도 132개, 최대 차이 0.029985738122164193. 부적격 eligible_A 유입 0.

실행: `validate_hircb_independent.py --inputs <inputs> --reference <original-reference> --output <new-dir>` 및 `validate_hircb_followup.py --reference <original-handoff> --actual <new-handoff> --output <validation.json>`. 이 이름의 independent는 원자료 재계산/원 reference 대조를 의미하며 전체 알고리즘을 제3의 독립 구현으로 재개발했다는 뜻이 아니다.

새 multi-source Astra profile은 별도 estimator/track/annotation 실행이며 위 profile 행 수에 맞추지 않는다. 최초 전체 실행에서 반복 site/omission 집계의 성능 병목을 찾아 미완성 결과를 게시하지 않고 중단했다. 최적화 전후 CSV의 값·ID·NA·문자 일치와 재실행 성능을 별도 기록한다.

## 별도 미실행/미확인

운영 서버 배포, 운영 URL의 API/worker mount·SHA, 운영 동시 실행 stress는 확인하지 않았다. Astra 실제 보고서 A/B 비교는 모델 실행 권한이 없어 `not_run_model_access_unavailable`이다. `prepare_astra_evaluation.py`가 동일 입력 manifest·고정 rubric·공통 질문 prompt·블라인드 평가 절차·실측 review 수집을 준비한다. 플랫폼 우월성이나 enrichment-free 우월성을 주장하지 않는다.

## 추가 portable 검증

최종 합성 다운로드 ZIP을 별도 Python 3.12.14 / numpy 2.3.5 / pandas 2.2.3에서 bundled code만 사용해 재실행했다. Outbound socket/urllib 차단 상태에서 48개 scientific CSV의 numeric/text/ID/NA 비교와 byte 일치가 모두 통과했고 network attempts는 0이었다. 원래 실행 환경 Python 3.14.6과 구분한다.

FASTA 별칭에 GN이 빠진 경우, 원 form mapping이 unambiguous일 때만 representative gene으로 연결한다. 다른 독립 gene으로 세지 않도록 typed regulator estimator를 v1.1로 기록했다. 기존 v2 reference 계산에는 적용하지 않는다.

## 최종 실제 주문과 신규 산출물

최종 HIRc-B 로컬 주문 33, run `g1-76a260def344440c854d6f108d3b90b5`. FastAPI → MySQL/Redis → Celery → 다운로드 경로에서 생성했다. ZIP 234,222,425 bytes, manifest 127 files, scientific CSV 48개다. 사용자 제공 `HIRcB_Insulin_Full_Article (2).docx`가 byte 그대로 포함됐으며 문헌 비교 상태는 provided_not_compared다. Canonical design은 21 injections / 7 materials / 7 conditions / 6 contrasts이고 insulin 100 nM, starvation 12 h, injection volume 10 µL를 보존했다. DIA-NN/upstream normalization/peptide mass는 unknown이다.

| 지표 | 최종 v4 실행 | 해석 |
|---|---:|---|
| forms / mapped / parent eligible | 2,824 / 2,628 / 2,625 | 기존 mapping·parent 규칙 유지 |
| A 비교 | 13,704 | Generic 최소 공동 관측 1회 |
| 반복 공동 관측 A 비교 | 11,920 | 양쪽 ≥2회 subset |
| Candidate entities | 343 | kinase/family 혼합; 활성 수가 아님 |
| Candidate relation rows | 50,568 | motif 49,262 / protein association 677 / orthology site 628 / native site 1 |
| Profile rows | 26,754 | 343 entities × 13 tracks × 6 contrasts |
| 전체 PG groups | 9,525 | 관심 패널로 제한하지 않음 |
| 전달 연구 field leaves | 664 | canonical 94 / raw-only 570 / 정당한 서버 경로 제외 1 / 누락 0 |

별칭 gene 수정 전 개발용 v1 결과와 비교해 quant summary 2,824, comparisons 16,944, runlevel 59,304, detection 16,944, primary input 13,704행의 값·ID·문자·결측이 동일했다. 새 typed estimator v1.1에서는 gene count와 activity가 108 profile rows에서 바뀌었다. 원본 FASTA GN 누락 별칭의 unambiguous representative gene 연결을 명시한 변경이다. Source pin도 별도 기록하며 이 비교를 legacy reference 3,948행 비교와 혼동하지 않는다. Form A identity 최대 오차 1.2865e-14.

최종 run의 실제 provider 상태는 OmniPath/registered snapshot/PubMed/STRING 일부/iPTMnet 일부 hit, iPTMnet 12 parse_failure, Reactome 3 access_unavailable, 일부 request-budget 미실행, KEA nonhuman mapping not_supported였다. 별도의 짧은 live smoke에서 Reactome hit였던 사실로 이 run의 실패를 덮어쓰지 않는다. 모든 제한은 pinned ledger에 포함됐고 정량·motif는 완료했다.

기록 stage 시간(초): 입력 0.32, 정량+정규화 대안 199.32, 자료 조회 38.41, 후보 8.49, footprint 117.54, 시간 통합 145.08, 패키지 조립 35.06, 검증/ZIP 게시 34.86. 이 합계에는 별도로 stage timer를 두지 않은 impact 계산 시간이 포함되지 않으므로 전체 wall time으로 쓰지 않는다. Process peak는 6,082,134,016 bytes이며 process cumulative high-water mark다. publication_metrics의 source_requests=24는 query ledger record 수이며 실제 새 HTTP request 수와 같다고 해석하지 않는다. Cache-hit records는 5개다.

집계 최적화 자체는 변경 전 기록된 50,568 edge / 26,754 profile / 65,862 contribution / 151,095 omission rows의 numeric/text/NA parity를 확인했고 score 단계 118.97초를 측정했다. 이후 gene alias 보정은 별도 v1.1 변경이다. 하나의 dataset/run timing을 일반 성능 보장으로 사용하지 않는다.

최종 합성 API 주문 31/32의 Create/Copy/Rerun은 모두 통과했다. UI 주문 31 → Copy 35 → Start → Rerun에서도 page errors 0, archive checksum, 같은 run의 Data Files, 질문·단위·설계 보존을 확인했다. HIRc-B 전체 Create/Copy/Rerun은 앞선 v1 실행 주문 29/30에서 수행했고, 최종 v1.1은 위 주문 33으로 생성·다운로드했다. 이를 같은 코드 버전의 HIRc-B Copy/Rerun을 다시 실행한 것으로 표현하지 않는다.

최종 archive SHA-256: `9a2811a208a12bd02327101eb97145ed643212294d186139e28855bc156816d5`.

그림 검토: 합성 패키지의 9개 SVG를 브라우저로 PNG 렌더링하고 직접 확인했다. 축/범례가 표시되고 heatmap NA는 회색이다. 긴 stable ID는 source table lookup 용도이며 이 도표를 최종 논문 조판 완료로 표현하지 않는다. UI 변경 전 v3 화면과 변경 후 v4 화면을 review 패키지에 함께 넣었다.

## 최종 HIRc-B portable replay

다운로드한 ZIP만 새 디렉터리에 풀고 저장된 source/input/code로 독립 실행했다. Python 3.12.14, numpy 2.3.5, pandas 2.2.3 환경에서 48개 scientific CSV 모두 값·문자·키·NA mask 비교를 통과했다(atol=rtol=1e-10). Byte 동일성은 48/48이며 numeric equivalence와 별도 판정이다. Socket/urllib 차단 상태의 network attempts=0, 재계산 및 비교 421.10초. 서버 registry와 repository engine을 import하지 않았다. 상세는 hircb-offline312/validation.json이다.

실제 명령 형태: `python scripts/validate_astra_offline.py --archive <downloaded-astra.zip> --output <new-offline-dir>`. replay의 범위는 모든 scientific CSV이며 SVG·Markdown의 cross-version byte 동일성까지 주장하지 않는다.
