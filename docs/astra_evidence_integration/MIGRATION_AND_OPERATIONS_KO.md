# 버전·실행·배포 안내

사용자는 기존 Order의 실험 설계와 원자료를 확인한 뒤 **Astra 분석 패키지 생성**을 실행한다. 일반 화면에 v5/v6, kinase-required, snapshot 조합을 추가하지 않았다. 이미 선택한 Order species를 canonical resolver에 전달한다. report/site report는 제공할 때만 기존 과학 입력 영역에 첨부한다. Results의 **Astra 분석 패키지 → 패키지 다운로드 / Astra 전달 지침 / 근거 보기**와 Data Files는 같은 recorded run을 가리킨다.

## Migration

- 신규 v6 profile: `astra_analysis.v6`, schema `astra_analysis_package.v6.experimental`. v4/v5 파일·기존 archive는 그대로 읽고 포함된 코드로 replay한다.
- 서버 `PTM_ASTRA_EVIDENCE_V6=1`일 때 신규 Astra 요청을 v6로 해석한다. 기본 운영 활성화는 하지 않았다. 기존 완료 pointer/provenance를 현재 form 값으로 재작성하지 않는다.
- API/Order에 nullable `calibration_policy_path`가 추가된다. 시작 시 기존 방식의 additive migration을 수행한다. calibration 자료 없는 주문은 null이다.
- `quant/kinase_profiles.csv`는 legacy projection이다. 새 canonical profile은 `kinase/kinase_temporal_profiles.csv`; migration JSON에 연결한다.
- 새 localization parser는 main precursor minimum/library/q/site posterior를 분리한다. v6 audit-only가 기본이며 정량값을 필터링하지 않는다. 관측 필터 재정량은 명시적 기존 정책/threshold/normalization scope가 필요한 별도 계산이다.
- 종별/혼합종 reference 검사와 single protein-group parent 적격성은 기존 v5 구현을 유지한다. lineage에서 실제 소비되지 않는 transgene manifest는 accepted_but_unused로 표시한다.

## 자원과 실행 환경

API와 worker가 동일한 reference/object store 및 같은 release를 사용해야 한다. `REFERENCE_DIR`의 source_pins/source_cache와 등록 FASTA를 동일 mount로 제공한다. reference 데이터 배포와 코드 배포는 별개다. content-addressed 기존 pin은 수정하지 않는다. Copy/Rerun은 원 pin을 유지하고 reference refresh는 새 run으로 수행한다.

PhosX는 선택 의존성 `workers[astra-official]`에 upstream commit을 고정했다. 이 extra 설치가 atlas의 사용 권한을 부여하지 않는다. 승인된 manifest와 행렬/background를 worker가 읽을 수 있는 같은 resource directory에 배치해야 한다. 현재 일반 UI에서 자원 라이선스나 내부 snapshot을 사용자가 조합하도록 요구하지 않는다. 개별 JSON manifest만 업로드하면 옆의 행렬 파일이 자동 확보되는 기능은 없다.

Replay 환경은 package의 `software_versions.json`, `reproducibility/requirements.txt`를 따른다. 이번 engine 검사는 Python 3.14 환경, 공식 PhosX는 pandas<3을 요구하므로 별도 Python 3.11 환경에서 실행했다. 환경 설정/의존성 설치와 계산의 offline 실행을 구분한다.

```sh
python replay.py --validate-only
python replay.py --output <새로운-출력-디렉터리>
# restricted resource package인 경우만:
python replay.py --output <새로운-출력-디렉터리> --specificity-manifest <동일-hash-manifest>
```

## research_full과 복구

v6 신규 source acquisition은 전체 적격 accession을 기록하고 provider별 4시간/100,000 request 상한과 rate limit을 적용한다. 기존 3개 Reactome·200 PMID 상한은 full mode의 모집단 제한으로 쓰지 않는다. 시간 예산을 소진하면 나머지 질의를 not_run_budget으로 기록한다. 완전한 annotation 성공으로 표시하지 않는다.

STRING은 species별 고유 ID를 batch로 해소한 뒤 모든 해소 ID의 induced network를 한 번에 요청한다. 서버가 전체 요청을 거절하면 unavailable/partial로 남기며 배치내 결과만으로 완전 network라고 하지 않는다. 404는 no_hit가 아니며 반복 시간 연장으로 고치지 않는다.

query cache는 검증된 성공/no_hit만 재사용한다. 실패·partial은 음성 캐시가 아니다. 정량 외에도 canonical evidence 준비, discovery, footprint, temporal의 순수 계산 출력은 Parquet/typed JSON과 checksum manifest로 저장한다. 완전히 쓰인 manifest만 atomic publish하며 깨진 cache는 재계산한다. 새 context 원문을 과거 cache의 설명으로 덮어쓰지 않는다. bootstrap/policy 적용 및 optional native method 실행은 현재 다시 수행하며 모든 함수 내부를 checkpoint하는 방식은 아니다. 새 실행 완료 전 기존 current pointer는 유지한다.

## 실제 검증 및 운영 구분

격리 로컬 환경에서 API 8016, UI 5176, 기존 검증용 MySQL 13366의 새 주문, Redis 16386 DB9 및 별도 output/reference directory를 사용했다. 운영 주문이나 무관한 volume을 삭제하지 않았다. 별도 DB 생성 권한이 없어 이미 격리된 검증 DB에서 새 주문만 만들었다. 이는 운영 URL/production mount 확인이 아니다.

배포 시 동일 commit으로 API/worker/frontend를 빌드하고 additive column migration, shared reference digest, 기능 flag, 신규 테스트 주문을 확인한다. rollback은 v6 flag를 해제하고 이전 image를 복원한다. nullable column과 이미 완료된 run/archive는 보존한다. Git push는 배포가 아니다. 이번 작업에서 운영 배포·운영 URL 확인은 수행하지 않았다.

## 문헌 검토 단계

2026-10-13 선언. 승인 조건은 `finding_retrieval.v6`와 같다. 인용문이 검색 구간에 있고, 범위와 조건 문자열이 그 인용문에 있으며, DOI 또는 PMID가 있을 때만 비교 후보로 남긴다. 이 조건을 낮춰 승인 건수를 늘리지 않는다. `semantically_verified_comparable_findings`는 0이다. 통과한 행도 `claim_support_status=not_verified`, `relationship=literature_background`로 유지한다.

거절된 제안만 기존 조건의 첫 실패 지점으로 나눈다.

- `citation_mismatch`: 인용문이 검색 구간에 없거나 DOI·PMID가 없다.
- `scope`: 범위가 선언되지 않았거나, gene·site·허용 관계가 인용문과 맞지 않거나, 주장 문장이 비어 있다.
- `condition_comparison`: species, cell type, dose, time, readout, perturbation 중 모델이 적은 값이 인용문에 없다.

검색 완료, 모델 비교 완료, 인용 근거 검증, 생물학적 의미 검토, 외부 전달은 `review_stages`에 따로 적는다. packet `mode=citation_complete`는 reference card가 있다는 뜻이며 인용 검증이나 외부 전달 승인이 아니다. 원문 구간을 패키지에 넣지 않으면 DOI, PMID, 원문 위치, 접근 제한을 `LITERATURE.md`에 남긴다.

선정 finding은 전체 신호망이 아니다. insulin 경로 기대에 맞춰 고르지 않는다. `cards.csv`와 `authoring_packet.json` 전체를 읽지 않고 `findings.csv`와 `question_map.json`의 card_id만 고른다. 전체 emergence, protein, kinase 표로 범위를 넓힌다. `repository_measured_gene_zscore` 행은 PhosX 실행 결과가 아니다. PhosX는 `method_id=PhosX_native_functions`이고 `method_executions`가 있을 때만 그렇게 읽는다.

## 저장된 결과의 reader 연결

2026-10-13 선언. Order 89 g7 패키지를 본 뒤의 탐색적 표시 규칙이다. primary 승격 금지. 새 측정 임계는 없다. 정량과 PhosX를 다시 계산하지 않는다.

- `source_bindings.membership_ids`는 precursor 카드 멤버다. kinase 후보 기여도가 아니다. precursor 연결 수는 `reader_adapter/precursor_membership.csv`의 `membership_id`와 맞는 선정 관측이다. 표가 없으면 0개로 적지 않는다.
- 후보 기여도는 `project_temporal()`이 카드의 contrast, arm, reference, pairing 범위에서 연결한 `candidates`의 고유 `candidate_id`다. `candidates` 배열 길이를 후보 수로 쓰지 않는다. 이 투영이 없으면 `substrate_contributions.csv`의 `form_ids`를 `;`로 나눈 토큰이 `form_id`와 같고 `contrast_id`가 카드 범위 안인 행만 센다. `form_1`과 `form_10`은 다른 ID다. PhosX native membership은 이 수와 합치지 않는다.
- `condition_grid.conditions`와 카드의 trajectory, source_bindings는 기록된 `time_minutes` 또는 `time_min`이 조건마다 하나일 때 그 숫자 순이다. 조건 문자열로 시간을 추정하지 않는다. 시간이 없거나 충돌하면 기존 목록을 두고 `time_order_status=unresolved_recorded_time`으로 남긴다. 이 투영은 카드 생성과 저장 reader revision이 함께 호출한다. revision은 `build_feature_observation_cards()`를 다시 실행하지 않는다. 이미 숫자 시간순인 그림, PhosX 표, temporal 배열은 다시 쓰지 않는다.
- `LITERATURE.md`의 구간 안내는 `literature_sources.csv`의 `source_key`, title, DOI, PMID, `evidence_location`이다. `source_key` 순으로 구간을 각각 남기고, 고유 논문 수와 구간 수를 따로 적는다. pin documents의 빈 DOI는 그 목록에 넣지 않는다. 승인 조건은 «문헌 검토 단계»와 같다.
- `method_executions`의 executed와 `method_scores` 행 수는 유의한 kinase 활성 검출이 아니다. `insufficient_coverage`는 비활성이 아니다. method q로 특정 kinase의 활성 또는 비활성을 결론내지 않는다. no-call은 v6 미적용의 증거가 아니다. 이 문장은 저장된 상태 개수를 옮길 뿐 새 q 임계를 적용하지 않는다.

## PhosX 등록 자원

2026-10-13 선언. 회차 09에서 실행 전에 고정한 행렬 해시를 그대로 쓴다. PSSM `7d18a78d6efc45925aacae9c62ea26c5d7c22519eb856b2891debeed0ea42c6d`, background `487beac611126c973c36b3b01161991a7c01d08e8d00f764136eb2c45aac1c11`, metadata `ab48c161eb8f35225cc410331c71cd0d35c1fd198a828a6eb78069d3fc341952`. 코드 commit `b556f59c39f099b5f3fcb574a8a70856c3fdc82c`.

`ptm-workers` 이미지 빌드는 PhosX 0.23.1 commit `b556f59c`를 포함한다. RAG, report, beat도 같은 이미지 태그를 쓰므로 이 패키지를 뺀 빌드가 그 태그를 덮어쓰면 안 된다. 행렬 HDF5는 이미지에 넣지 않고 reference 마운트에 둔다. API 이미지의 duckdb는 `api-server/pyproject.toml` 의존성이다.

`REFERENCE_DIR/phosx-0.23.1-b556f59/manifest.json`이 있고 위 행렬 해시가 맞을 때만 기존 v6 specificity 연결이 그 파일을 읽는다. 서버 환경변수로 다른 manifest를 지정하면 그 값이 우선이다. 파일이 없거나 해시가 다르면 기존처럼 PhosX를 실행하지 않고 `resource_unavailable`로 남긴다. 원본 manifest 파일 `12eff82db554b22355169115f39fc4ba0ce65584f26aac4dcccf9b4b999dfa0a`는 이 작업 공간에 없다. 로컬 wrapper의 sha256은 `1f0f262e684276d95672f33ba79f7e2ff7e1d6b8f7a8d5d6cddce2874380a605`이며 그 파일과 같지 않다. 같은 것은 행렬과 background 바이트다.

이 연결은 여섯 시간점 실행 기록이 아니다. 실행은 주문의 선언된 contrast 전부이며, 시간 목록을 코드에 새로 넣지 않는다. `method_executions.csv`에 `executed` 행이 생기기 전에는 PhosX 결과라고 적지 않는다. 원본 HDF5는 패키지에 넣지 않는다.


