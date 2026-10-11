# 11-A — 요청한 엔진과 실제 reader 발행 경로

기준 main은 `0ca09c1`이다. `df0e98a` 이후 cache 누락 처리와 최초 partial-package 발행 수정 두 건을 fast-forward로 보존했다. 미커밋 `codex-inputs/`는 유지했고 원시 자료는 커밋하지 않는다.

## 확인한 원인과 범위

Downloads의 Order 89 원 ZIP을 읽었다. SHA-256은 `829f35e7658a8e91abcbc9dda3acd6605bf7269a74c54abfa16e64c443d72c72`, manifest 155개 파일의 bytes/hash가 모두 일치한다. context/plan/provenance/replay는 실제로 v5이고 reader가 없다. source pin은 `2566fabd9cab0bab1ebeedf55326652ae7808467c9715b00a3a29a1dd91f6160`, research_full 갱신은 partial이다. 정책 이름을 수집 완료로 바꾸지 않았다.

일반 UI의 v5 요청은 API `current_astra_context()`에서 `PTM_ASTRA_EVIDENCE_V6=1`일 때 v6가 된다. worker는 전달된 mode로 분기하며 flag를 재해석하지 않는다. v5 분기에서는 v6 card adapter/reader가 호출되지 않는다. 이것이 패키지의 reader 부재를 설명하는 직접 실행 원인이다. 다만 **Order 89의 당시 API flag, 실행 컨테이너 및 현재 DB를 확인한 것은 아니다.** flag 미설정/오래된 API/다른 dispatch 경로 중 하나로 최종 귀속할 운영 기록은 아직 없다. 공개 `/api/version`은 조사 시 `df0e98a`를 반환했다. 이 marker는 모든 프로세스의 release 증명이 아니다.

원 Order 89 문헌 7개는 기존 로컬 검증 문서와 SHA-256이 모두 같다. 운영 collection 39/document 96–102와 로컬 collection 1/document 1–7의 대응 근거는 파일 hash다. ID를 전역 상수로 사용하지 않는다. ZIP에 PDF가 없다는 사실과 내부 검색 가능 여부를 구분한다.

## 최소 변경과 기존 함수 재사용

- `analysis_context.current_astra_context`: 반복 호출에서도 최초 요청과 해석된 profile을 유지하는 진단 레코드를 추가했다. 기존 전환 조건은 그대로다.
- `astra_package.run_astra_analysis`: 요청에 기록된 기대 profile을 실제 engine.PROFILE과 비교한다. 불일치는 입력 복사/성공 pointer 게시 전에 `astra_profile_mismatch`로 실패한다. 실행 profile 레코드와 검사 코드를 provenance에 포함한다. 기존 v5 archive replay에서는 flag를 다시 해석하지 않는다.
- `astra_reader_temporal.source_row/project_temporal`: 새 실행에서 빈 문자열인 근거 ID 목록/사유가 CSV에서 NA로 바뀌어 seal 검증에 실패하는 결함을 수정했다. 저장 CSV와 동일하게 absent cell을 null로 투영한다. 측정값, 0, False, 실제 stable ID는 변경하지 않는다.
- `validate_astra_activation.package_contract`: 기존 검증 도구에 execution record와 reader 행 수를 추가했다.

호출 경로는 기존 일반 화면 → create/PATCH/start API → `_updated_analysis_context` → `_attach_enrichment_free_profile` → Celery preprocessing → `run_primary_analysis` → v6 `run/augment` → `project_card_inputs` → `build_reader_tables`/temporal attach → `write_reader` → `seal_archive` → Results 다운로드다. 카드/질문/선정/authoring 함수와 정량·그림 정책을 새로 만들지 않았다.

## 검증

새 생성→저장 CSV→seal→offline reader replay의 기존 합성 통합 검사가 처음에는 temporal source projection 차이로 실패했다. 차이는 specificity_ids/exclusion_reasons/remaining_site_keys의 빈 문자열 대 NA였으며, 수정 후 통과했다. 기록된 패키지만 읽던 회차 10 검증과 구별되는 실제 생성 경계 결함이다.

고유 Python 검사 29개: profile/잘못된 엔진/기존 API 입력 보존 21개, temporal projection 6개, v6 생성 및 offline reader replay 통합 1개. 실제 Order의 조건 JSON key 순서에 대한 회귀 1개를 추가했다. Frontend context 검사 5개. 재시도 횟수를 합산하지 않는다. PhosX/RAG/운영/Astra 소비 검증은 이 숫자에 포함하지 않는다.

실자료 로컬 경로는 새 Order 72에서 검증 중이다. 일반 v5 생성 요청이 API에서 v6로 저장되고, 화면의 실행/재시도 버튼을 통해 v6 dispatch된 것을 확인했다. API 8019/화면 5179, 별도 Redis DB14를 사용한다. 기존 source pin과 quant cache를 재사용하며 운영 주문을 변경하지 않는다. 최초 실행은 임시 reference 디렉터리의 pin 파일 소실로 정상 실패했다. 원 archive의 동일 bytes/hash를 복구했으며 새 reference 수집을 하지 않았다.

이 로컬 주문의 비교 기준은 이전 HIRc-B v5 archive다. Order 89와 PR/PG/FASTA bytes는 동일하지만 source pin, material/biological-unit ID 및 pairing 선언이 다르다(이전 unpaired, Order 89 unknown). **Order 89와 같은 설계·pin의 v5/v6 비교라고 주장하지 않는다.** Order 89 고정 입력·설계·pin을 사용하는 통합 검증은 다음 단위에서 별도로 기록한다. 다른 설계의 cache key를 임의로 바꾸어 재사용하지 않는다.

실자료 run/ZIP/reader/정량 불변성과 최종 상태는 실행 완료 후 결과 JSON 및 아래에 추가한다. 운영 배포·flag 변경은 수행하지 않았다. 실제 운영 원인 및 일반 UI 다운로드 완료는 아직 미확인이다.


## 실제 실행 완료 기록

로컬 Order 72의 정상 UI 재실행과 Results 다운로드: `g3-583a813dfdb6423eb848e44b0c56016c`, ZIP SHA `335425f42c6d11cc1aa4e92112a172931317e68c3896984c0b53427ae0534b61`. 요청 v5 → API 해석/dispatch/worker/context/plan/provenance/replay v6가 일치했다. Results 다운로드 bytes와 성공 pointer의 hash가 같고 화면도 직접 확인했다. Manifest 225개, 과학 표 79개; adapter 16,944행, 카드 14,658행, 선정 15개, coverage 16,944행이다. 실제 생성된 패키지 자체 코드의 offline reader replay 18개 파일이 byte-identical이다(네트워크·과학 재계산 없음).

동일 설계·pin 기준은 기존 Round10 `g0-02484ac7623548fe970d9f88f57ea2e1`이다. source pin 파일 bytes, canonical design, quant 22개 CSV가 모두 동일하다. 이전 v5 archive와도 quant 22개가 byte-identical이다. 기존 활성화 도구가 exported source JSON의 파일 hash를 registry ID로 취급하던 문제도 수정했다. 신규 요청은 기록된 pin ID를 사용한다. 원 g3의 registry bytes는 `2566...6160`과 정확히 일치하도록 복원했고 다음 통합 주문에 사용한다. 과거 archive를 수정하거나 ID를 덮어쓰지 않았다.

첫 실자료 ZIP `g2-d51...`은 다운로드/정량 검사는 통과했지만 reader replay에서 실패했다. `astra_literature.inputs()`의 `recorded_conditions_query` JSON 문자열에 정렬이 없어, 저장된 동일 pre_treatment의 key 순서 변화가 hash를 바꿨다. sort_keys로 수정하고 실제 조건 변경은 계속 거절하는 테스트를 추가했다. 새 g3는 quant·identity·discovery·score·temporal cache를 모두 재사용했으며 reference 수집을 실행하지 않았다. 실패한 검증을 통과 수에 포함하지 않는다.

11-A는 **로컬 실행 연결 완료, 운영 원인 귀속/운영 일반 UI 미확인**이다. 이 주문의 PhosX와 실제 문헌 검색은 미실행이다. 11-B에서 Order89의 실제 설계·원 source pin·7개 문헌으로 별도 통합한다. 운영 배포/운영 flag 변경/Astra 소비 검증은 수행하지 않았다.
