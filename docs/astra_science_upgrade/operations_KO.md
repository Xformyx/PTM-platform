# 사용 및 운영 인계

기본 제품 경로는 Astra v5이다. 별도의 `Experimental science validation` 항목과 체크박스 없이 실행한다. 기존 v4 주문의 Copy/Rerun도 새 v5 실행으로 처리하며, 완료된 패키지는 변경하지 않는다. 주문에 이미 있는 species, sample/condition/material, reference, 정규화와 질문을 재사용한다.

새 주문에서는 PR/PG와 분석 FASTA 업로드 또는 등록 Reference ID를 사용한다. 측정 근거 파일은 필요할 때 추가한다. 기존 주문의 Copy/Rerun은 저장된 경로와 canonical design을 승계한다. DIA-NN 원본이 있을 때만 정확한 version을 입력한다. 보고서 Run과 matrix column이 정확히 다르면 `Run,input_column,injection_id` crosswalk를 제공한다. 비시계열은 Design axis를 cross-sectional로 지정하며 time=null이 허용된다. Protein-only는 proteomics와 PG를 사용한다. 현재 U-only PTM 분석은 입력 오류로 명시적으로 거절한다.

Results의 Astra 분석 패키지 카드에서 패키지, 전달 지침, 판단·보류 근거, 측정 audit, 단백질 비교를 받는다. 카드의 recorded run과 provenance는 완료 시점 값이며 현재 form 변경으로 덮어쓰지 않는다. 패키지의 experimental/uncalibrated 표기는 과학적 검증 상태이며 기능 활성화 스위치가 아니다. 아직 calibration된 kinase call을 생성하지 않는다.

## 배포 전 순서

1. API/worker/frontend를 같은 Git release로 빌드한다. API/worker pyproject에 pyarrow가 포함된다. 실제 환경 dependency resolver/lock과 이미지 digest를 배포 기록에 고정한다.
2. 운영 DB 백업 후 orders의 8개 nullable scientific input 경로, nullable PR, proteomics enum migration을 적용한다. Startup migration은 격리 MySQL에서 사용했으며 운영에서는 미실행이다. 구 app으로 rollback하더라도 컬럼과 완료 패키지를 삭제하지 않는다.
3. API와 worker에 동일 input/output/reference volume을 마운트한다. 원자료 파일과 FASTA hash를 두 서비스에서 대조한다. 단순 코드 push는 이 작업을 수행하지 않는다.
4. 새 sequence reference는 `sequence_references/<reference_id>/manifest.json`에 ID, version, file, sha256를 고정한다. 종별 폴더의 첫 파일 선택은 v5에서 사용하지 않는다. 실제 biological FASTA inventory와 Order 종을 preflight한다. taxonomy mapping 파일은 source/release/accessions 및 SHA를 보존한다. reviewed/isoform/strain/custom construct 설명은 등록 manifest에 기록한다.
5. Frozen annotation/source pin은 기존 content-addressed registry를 유지한다. 신규 run의 provider 요청은 taxon round-robin 예산 정책을 기록한다. 기존 source pin을 복사·재실행할 때는 그대로 재사용한다. Production registry/live provider readiness는 별도 운영 확인 대상이다.
6. 제공 가능한 specificity resource의 manifest와 matrix/background checksum 및 라이선스를 검증한다. `redistribution_status=permitted`만 portable package에 원 행렬을 포함한다. 그 외는 메타데이터·해시와 미실행 사유를 보존하고 정량은 계속한다. 로컬 scorer interface 사용과 portable export 권한은 별개다.
7. 아래 격리 검증을 배포 대상 이미지에서 반복하고, 새 주문의 archive와 다운로드 SHA를 확인한다. 운영 주문을 test fixture로 사용하지 않는다.

## 재현 명령

```sh
python scripts/run_local_study_validation.py science --environment-file PRIVATE_ENV --fixture FIXTURE_DIRECTORY --output REVIEW_DIRECTORY --port ISOLATED_API_PORT
python scripts/run_local_study_validation.py astra-browser --environment-file PRIVATE_ENV --order-id TEST_ORDER --ui-url LOCAL_UI_URL --output UI_REVIEW_DIRECTORY
python scripts/validate_astra_science_archive.py --archive FROZEN_V4_PACKAGE --output NEW_REVIEW_DIRECTORY --replay
python replay.py --validate-only
python replay.py --output NEW_EMPTY_REPLAY_DIRECTORY
```

위의 대문자 인자는 실제 격리 환경 값으로 바꾼다. 환경 파일은 전달 패키지와 Git에서 제외한다. v4→v5 비교 도구는 기존 archive를 수정하지 않으며 원래 pinned source만 사용한다. replay는 package의 code/resource pin으로 실행한다. 재배포할 수 없어 미실행한 자원을 계산 완료로 표시하지 않는다.

## 지원 제한

- DIA-NN TSV/Parquet는 명시된 version과 공통 정확한 컬럼 계약을 검사한다. 실제 버전별 원자료 parity는 아직 없다. Site report와 transgene manifest는 원문 provenance를 보존하지만 site posterior/construct 검증 parser는 미완성이다.
- OX/GN 없는 custom FASTA는 명시 mapping을 사용한다. 승인된 search/analysis FASTA 차이는 현재 accession/sequence/taxon이 같은 header-only conversion에 한정한다. 좌표 변경 conversion은 거절한다.
- Exact-site source/sequence/motif 및 gene/group 제외를 제공하지만 독립적으로 sequence alignment를 수행하는 orthology adapter, 공식 atlas scorer, calibration된 family fallback은 아직 미완성이다. Provider translation을 정렬 검증으로 표시하지 않는다.
- Mixed-species의 symbol-only STRING cross-layer 연결은 억제하며 source context 원자료는 남긴다. 해당 관계를 직접 효소-기질 근거로 사용하지 않는다.
- v5 quant 단계는 재계산한다. 단계별 source/hash 무효화는 기록하지만 성공한 quant cache 재사용까지 구현됐다고 표시하지 않는다.
- 외부 공식 comparator 실행 adapter는 고정된 argv/resource/code 계약과 실행 로그를 제공하는 process interface이다. 방법별 입력 변환/출력 동등성은 공식 도구 및 데이터 확보 후 별도 검증해야 한다.

Rollback은 이전 application release와 요청 경로를 복원하고 v5 입력/DB/완료 archive를 보존하는 방식이다. v5 archive를 v4로 읽거나 이름만 바꾸지 않는다. 기본 실행 경로 변경은 정확도 향상이나 독립 실험 검증 완료를 의미하지 않는다.
