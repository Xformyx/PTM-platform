# 11-B — 일반 생성 경로의 공식 방법·문헌·시간 근거

이 회차의 기준은 실제 Order 89 archive `g3-bb4f83b9a528415e82b1fcdacc8b392a`다. 운영 DB를 복제하거나 운영 Order를 변경하지 않았다. 원 ZIP, 이전 성공 패키지, 미커밋 입력은 보존했다. 실제 실행 수와 최종 판정은 아래 검증 결과에 기록한다.

## 원인과 연결

| 기존 함수와 경로 | 소비되지 않던 이유 | 최소 변경 |
| --- | --- | --- |
| Order `specificity_manifest_path` → `prepare_astra_inputs`/`capture_order` → 기존 dispatch/worker → `prepare_evidence` | 공식 자원이 로컬 검증 폴더에만 있었고 일반 Order에는 등록 자원이 연결되지 않음 | API 설정의 manifest 경로와 SHA를 검증하고 기존 Order 필드에 연결. API/worker 공유 reference 디렉터리에 동일 bytes 보관 |
| `score_sites → score_phosx → discover/score_candidates → execute_tracks → phosx_activity_adapter.execute` | 기존 방법은 존재. 일반 요청의 실제 자원·명시적 contrast 범위가 필요 | 기존 설정 객체에 canonical design의 contrast IDs와 기존 10,000 permutations/seed 1729 기본값 연결. 명시된 기존 scope는 덮어쓰지 않음 |
| worker Dockerfile → `astra-official` optional dependencies | 기존 image build가 dev extra만 설치하여 공식 방법 extra는 설치되지 않음 | 기존 고정 extra를 설치하는 opt-in build arg 연결. 기본 서비스 설정·flag는 변경하지 않음 |
| `retrieve_finding_literature → RAGRetriever/LLMClient → apply` | 원본 7편 선택과 검증 환경의 collection ID가 다름 | 원본 파일 SHA로 로컬 collection/document 대응 확인 후 기존 선택 pin 사용. 과거 별도 업로드 record/hash는 현재 입력 범위에서 제외. DB ID를 코드에 하드코딩하지 않음 |
| `collect` → 기존 단계 cache | source anchor가 있는 비교도 의미 검토 보류이면 같은 성공 패키지의 검색을 반복할 수 있음 | 동일 finding/관측/문헌 선택/설정/코드의 이전 발행 pin을 검증해 재사용. 검색 실패·budget/부분 실패·미실행 비교는 재사용하지 않음. 의미 검토 상태는 승격하지 않음 |
| `quantitative_evidence`, `augment` → 기존 `cached_stage` | audit와 native method가 재실행마다 무조건 계산됨 | 기존 cache로 성공한 과학 산출물만 재사용. 입력/설계/자원/정책/공식 코드/환경 의존성 확인; reader는 현재 질문으로 다시 구성. 실패 method는 cache하지 않음 |
| `finding_literature` 비교 prompt | 같은 trajectory 객체 반복으로 100,000 byte 예산을 초과 | 반복 객체의 lossless 참조와 같은 요청 내 원본 정의. 질문/시간/값/mask/source 문장 무삭제, 복원 동등성 검사 |
| `build_reader_tables → attach_temporal → write_reader` | v5 run에서는 호출되지 않음 | 기존 v6 실행에서 그대로 호출. 별도 선정·시간 계산·LLM 보고서 엔진 없음 |

## 고정 자원과 실험 범위

- PhosX 0.23.1, commit `b556f59c39f099b5f3fcb574a8a70856c3fdc82c`.
- Manifest SHA `12eff82db554b22355169115f39fc4ba0ce65584f26aac4dcccf9b4b999dfa0a`.
- S/T matrix SHA `7d18a78d6efc45925aacae9c62ea26c5d7c22519eb856b2891debeed0ea42c6d`.
- Background SHA `487beac611126c973c36b3b01161991a7c01d08e8d00f764136eb2c45aac1c11`.
- 설치된 공식 배포물의 HDF5와 등록 자원의 bytes가 같다. 기존 local-use/derived-export 허용 근거를 유지한다. 원 HDF5의 ZIP 재배포는 여전히 보류하며 동일 hash 외부 자원이 있어야 수치 method replay가 가능하다.
- A ranking, 10,000 permutations, seed 1729, min hits 4, top 5, min quantile 0.95, single worker, upstream activation evidence 미실행.
- 시간은 실제 design에서 1·5·15·30·60·180분 vs Control을 확인했다. 범용 실행 코드는 이 시간을 하드코딩하지 않는다.
- g3와 PR/PG/FASTA·study design·source pin을 고정했다. source pin은 `2566fabd9cab0bab1ebeedf55326652ae7808467c9715b00a3a29a1dd91f6160`, 실제 수집 상태는 기존 research_full/partial이며 이번에는 refresh하지 않았다.
- g3 design의 pairing/material IDs는 과거 회차의 로컬 design과 다르다. 기존 cache 키를 위조해 재사용하지 않고 이 설계의 정량 cache를 한 번 생성한다. 이후 동일 설계 재실행은 이 cache를 사용한다.

## 실제 문헌 접근과 제한

원본 collection 39/document 96–102와 로컬 collection 1/document 1–7은 각각 동일 파일 SHA로 대응했다. 7개 카탈로그·본문 파일·기존 Chroma index가 존재하며 각 문서에 대한 기존 RAG 검색 호출을 직접 확인했다. 이 접근 probe 자체를 finding 비교로 세지 않는다. 동일 실험의 첨부 methods/review 문서는 외부 독립 검증으로 세지 않는다.

원 Order의 `gemma3:27b`는 검증 환경에 설치되지 않았다. 이번 로컬 실행은 사용 가능한 기존 `ptm-round08b-qwen3-14b-40k:latest`를 명시적으로 선택했다. 운영 모델과 동일하다고 주장하지 않는다. 검색·비교의 실행 여부, 반환 구간, 제안과 의미 검토 상태는 실제 pin/reader 결과로 보고한다.

Localization report 미제공, 기술 반복, calibration 부재, human assay/rat substrate 및 미확정 enzyme mapping을 유지한다. Method p/q는 biological p/q가 아니며 문헌 anchor가 있다는 이유로 의미 검토나 직접 kinase 활성 검증을 완료 처리하지 않는다.

## 배포 준비와 확인 범위

기존 `.env`/Compose 경로를 사용한다. 운영에서 사용하려면 검토된 manifest와 HDF5를 API가 읽는 공유 mount에 두고 `ASTRA_SPECIFICITY_MANIFEST_PATH`, `ASTRA_SPECIFICITY_MANIFEST_SHA256`를 지정한다. preprocessing image는 `INSTALL_ASTRA_OFFICIAL=true`로 다시 빌드하여 기존 고정 extra를 포함해야 한다. API/worker의 reference mount와 resource SHA, Chroma collection 접근, 실제 사용 모델을 확인해야 한다.

이번 작업에서 운영 배포나 운영 flag 변경은 하지 않았다. Compose 정적 검증은 비밀 설정 대신 `.env.example`을 사용하는 임시 설정으로 수행했다. 로컬 Python 실행과 Docker image 빌드·운영 실행은 별개다.

## 재시작 경계에서 발견한 추가 원인

API `_clear_order_locks`는 REDIS_URL의 report lock만 제거했다. 실제 preprocessing lock은 CELERY_BROKER_URL의 별도 DB에 있어 강제 종료 뒤 정상 재실행이 duplicate로 건너뛰어졌다. 이번 로컬 실행에서 재현했고 해당 Order의 broker lock을 기존 취소/시작 경로에서 함께 제거하도록 수정했다. 새 scheduler를 만들지 않았다. 서로 다른 Redis DB와 타 Order 격리 fixture를 검사한다.

## 검증 결과

첫 run `g1-d15a6db9544d4b0780bd958f0ef574ed`에서 6개 PhosX 실행과 6개 문서/25개 본문 구간 검색을 확인했으나 비교는 prompt 예산 초과로 0건이었다. 이를 완료로 세지 않았다. 원본 g3에는 없는 이전 별도 첨부 한 건을 발견해 다음 로컬 검증 run을 취소하고 원래 7편만 유지했다. 첫 성공 ZIP/pointer는 보존됐다.

180분에 대한 이번 독립 공식 함수 비교: raw score 116,049행, native 결과 303행, membership 106,353행; 허용오차 atol/rtol=1e-12, 최대 실제 차이 0, skip 0. 첫 실제 문헌 비교 probe는 28,895 input tokens / 약 299초이며 비교 호출 완료·제안 0건이다.

최종 로컬 Order 73 / run `g5-b2d6432b11e741ea9f998126903de0c1`, ZIP SHA `0880e58baf75372c0f57a96e85770402accae5addb323689fa8a8e1cadec6536`. 일반 UI v5 요청을 API가 v6로 해석했고 dispatch/worker/네 가지 package profile이 v6다. Results UI 다운로드와 성공 pointer SHA가 같다. 로컬 release는 d535e34에 이 회차 변경을 적용한 상태다.

6 contrast 각각 303 assay 결과를 저장했다. 입력 joint A form / native group / selected membership은 순서대로 2276/353/1595, 2310/357/1612, 2306/357/1611, 2299/354/1601, 2215/348/1570, 2298/351/1582다. 미평가 Tyr를 S/T ranking에 섞지 않았고 method 표의 평가 불가 상태를 유지했다.

문헌: 46 queries, 15 model calls, 비교 실행 15/15, 실패 0, 외부 문서 6편, 고유 본문 구간 25개. 모든 비교가 `not_explained_by_retrieved_evidence`이며 제안 0, 의미 검토로 승인한 관계 0이다. 동일 실험 첨부를 외부 독립 검증으로 세지 않았다. 검색 성공은 생물학적 일치 증명이 아니다. 본문 export 제한은 그대로 유지했다.

정량 22표의 key/NA/수치 동등성 확인. 12표 byte 동일, 나머지 수치 차이 최대 7.105427357601002e-15(허용 1e-10); g3 캐시가 없어 동일 estimator의 첫 계산에서 생긴 부동소수점/직렬화 차이다. 이후 g1→g5의 정량 22표와 findings 15개는 byte 동일. science/kinase/temporal 등 67표 중 66개 byte 동일, candidate edge 170563×53은 값·NA 동일하고 직렬화만 다르다. 시간 근거는 15/15 linked다.

최종 archive 228 manifest 항목 및 과학 표 79개 검증, 상대 링크 101개 누락 0. 패키지 자체 코드의 reader replay 21파일 byte 동일, 네트워크/과학 재계산 0. 정량 audit 101.5초, native augment 588.5초, 문헌 3386.2초, assemble 70.1초. 나머지 정량/discovery/temporal은 유효 cache 재사용이다.

변경 경계 테스트 고유 22개 통과. 처음 추가한 두 fixture의 import/모델 JSON 형식을 수정하고 해당 두 개만 재검증했으며 중복 횟수를 합산하지 않았다. 실제 자료 검증과 합성 fixture 결과는 별개다.

완료된 빈 비교를 reader 전체 상태에서 대기로 표시하던 오류도 수정했다. 문헌 실행·export 코드가 동일함을 hash가 결속된 이전 코드의 AST로 확인하는 경우에만 표시 변경 후 pin 재사용을 허용한다. 입력/설정/다른 실행 코드 변경, 실패 pin은 재사용하지 않는다. g5 원 ZIP은 수정하지 않았으며 이 표시 수정은 11-C/11-D 새 reader에서 확인한다.

실제 ZIP: `codex-inputs/round11-20261010/B/astra_analysis_package_g5-b2d6432b11e741ea9f998126903de0c1.zip`. 입력·PDF·검증 출력은 Git에 넣지 않는다. 운영 release/flag/Order 89 DB/다운로드는 미확인이다. 11-C는 이 성공 run의 저장 표만 사용한다.
