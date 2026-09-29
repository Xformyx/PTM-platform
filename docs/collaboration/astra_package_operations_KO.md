# Astra 패키지 운영·사용 안내

## 사용자 실행

주문 생성의 기본 **Astra 분석 패키지 생성**을 사용한다. 가져온 조건/시간/대조군을 확인하고 실제 반복 관계가 미정일 때만 선언한다. Acquisition의 unknown 값은 추가 필수 질문이 아니다. 기존 연구 질문·문헌 선택을 그대로 사용한다. Project & Files의 선택 입력 “참고 논문·연구 자료”로 제공한 파일은 원문 그대로 포함하고, 플랫폼에서 비교 완료했다는 뜻으로 표시하지 않는다. 보고서 언어/형식과 custom questions는 계산 점수에 영향을 주지 않는 Astra 작성 맥락이다.

Results의 **Astra 분석 패키지** 카드에서 **패키지 다운로드**, **Astra 전달 지침**, primary A 및 근거 보고서를 받는다. “전달되는 실험 정보”는 다운로드 archive와 같은 serializer 결과다. 수정은 기존 주문 입력에서 하며 새 run/package에만 반영된다. Data Files에도 동일한 run ZIP이 표시된다.

## 로컬 검증과 운영 구분

검증은 격리된 localhost FastAPI/UI/Celery와 별도 MySQL·Redis를 사용한다. API 8000, UI 5173, MySQL 13366, Redis 16386의 loopback 서비스다. 운영 URL이나 운영 주문으로 destructive fixture를 실행하지 않는다. private environment file과 계정/토큰은 package와 source handoff에 넣지 않는다.

```sh
python scripts/run_local_study_validation.py api --environment-file <private-env>
python scripts/run_local_study_validation.py worker --environment-file <private-env>
python scripts/run_local_study_validation.py astra --environment-file <private-env> --email <local-test-user> --fixture <fixture-dir> --output <new-validation-dir>
python scripts/run_local_study_validation.py astra-browser --environment-file <private-env> --email <local-test-user> --order-id <local-order> --output <new-ui-dir>
```

Frozen response fixture는 검증용 환경의 `PTM_ASTRA_PROVIDER_FIXTURES`로만 주입한다. 운영 release에는 이 변수를 설정하지 않는다. `--live-sources`는 로컬 runner에서 이 변수를 제거한다. `probe_astra_sources.py --help`는 실제 mapped accession과 FASTA로 bounded live smoke를 수행하는 진입점이다.

## Reference와 cache

API와 preprocessing worker의 `REFERENCE_DIR`는 같은 shared reference volume을 가리켜야 한다. API가 고정한 literature object와 worker가 생성한 source pin 모두 양쪽에서 읽혀야 한다. 기존 compose의 `./data:/app/data` 공유를 유지한다. 배포 시 양쪽의 resolved path·등록 목록·checksum을 직접 확인한다. 등록 API의 empty/unauthorized/server/checksum 오류를 운영 로그에서 구분한다.

`register_frozen_annotation.py --help`에 따라 snapshot·metadata·audit를 검증하고 원자적으로 등록한다. 이미 유효한 content-addressed directory를 수정하지 않는다. 일반 Astra 사용자는 등록을 기다리거나 SHA를 선택하지 않는다. 호환되고 관측 accession을 포함하는 등록본을 재사용하며 없으면 허용 provider 자료를 수집한다. Reference 재현 preset만 정확한 과거 snapshot을 요구한다.

`source_cache/`는 query/provider/parser/license/taxon/PTM 기반 key와 response hash를 검증한다. 정상 조회 hit/no-hit만 7일 cache를 사용한다. timeout/rate limit/parse error를 음성 결과로 저장하지 않는다. 고급 참조 갱신은 query cache도 우회하고 새 pin을 만든다. `source_pins/<sha>.json`은 immutable이며 같은 run replay/기본 Copy·Rerun은 원 pin을 사용한다.

현재 provider budget은 전체 45초/24 요청, iPTMnet은 고유 accession 순서와 예약된 context 요청 예산, Reactome은 첫 3개 고유 accession, PubMed는 정렬한 관측 edge PMID의 첫 200개다. 예산·미조회 목록은 ledger에 남는다. STRING/Reactome/KEA 결과는 site-resolved curated kinase edge로 승격하지 않는다. Cache와 snapshot은 별도 reference 데이터 배포 단계다.

## Release/rollback 절차

1. 원격 main과 release SHA를 확인한다. API/worker/frontend 및 shared modules를 같은 release로 준비한다.
2. worker 의존성에 aiohttp/BeautifulSoup가 포함되므로 이미지도 재빌드한다. `workers/Dockerfile`은 기존 iPTMnet parser를 `/opt/mcp-server/app/tools/iptmnet.py`로 포함한다. shared source bind mount만 갱신하고 구 dependency image를 쓰지 않는다.
3. 읽기/쓰기 가능한 동일 reference volume과 입력/출력 volume을 확인한다. 기존 immutable snapshot/cache/run은 보존한다.
4. 격리된 fixture의 Create→Start→download→Copy→Rerun, manifest/FK/NA replay, 프런트 빌드를 실행한다.
5. 배포 권한이 있는 환경에서 서비스 이미지를 교체하고 실제 목록 API·worker 접근·Results 다운로드 SHA를 확인한다. 이 단계의 실제 수행 여부는 검증 보고서에 별도 기록한다.
6. 장애 시 신규 dispatch를 멈추고 직전 code/image로 복귀한다. 완료 ZIP과 `enrichment_free_current.json`의 이전 검증된 pointer를 보존한다. 불완전 디렉터리나 `.zip` 임시 파일을 정상 결과로 게시하지 않는다. DB/다른 프로젝트 volume을 삭제하지 않는다.

Git push는 운영 배포가 아니다. 이번 로컬 검증만으로 `ptm.xformyx.com`의 배포 SHA나 데이터 mount를 확인했다고 말하지 않는다.

## 독립 재실행

패키지를 새 디렉터리에 풀고 별도 Python 환경에 `reproducibility/requirements.txt`를 설치한다. 기록된 Python/library 버전도 확인한다.

```sh
python replay.py --validate-only
python replay.py --output <new-replay-directory>
# Downloaded archive only, with outbound sockets disabled:
python scripts/validate_astra_offline.py --archive <download.zip> --output <new-offline-validation-dir>
```

입력 bytes·pinned source·code로 모든 scientific CSV를 네트워크 없이 재계산한다. ID/text/NA mask는 정확 비교하고 numeric은 atol=rtol=1e-10이다. byte 동일성은 별도 항목이다. Providers를 다시 조회하지 않으며 parsed source pin과 원 response/hash를 사용한다. 허용되지 않아 포함하지 않은 문헌 원문은 metadata_only로 표시한다. 해당 원문의 내용 비교는 재실행 완료로 간주하지 않는다.

현재 결과가 `completed_with_limitations`여도 정량·후보·시간 근거는 사용할 수 있다. 정확한 제한은 `evidence/readiness.json`, source ledger, field manifest에서 확인한다. 낮은 신뢰도는 비활성을 의미하지 않는다.
