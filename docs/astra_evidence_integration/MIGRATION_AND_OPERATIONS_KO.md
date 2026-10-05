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
