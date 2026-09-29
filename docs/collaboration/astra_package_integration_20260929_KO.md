# Astra 패키지 통합 변경 기록

기준: `e5307169fa51fc0ea618ebb891a6c883792608b8`. 이 문서는 2026-09-28 개정 명령서에 대한 구현 기록이다. 운영 배포 완료나 생물학적 성능 향상을 의미하지 않는다. 최종 검증 결과와 미확인 범위는 `astra_package_validation_20260929_KO.md`를 참조한다.

## 실행 계약

일반 사용자의 기본 진입점은 **Astra 분석 패키지 생성**이다. 내부 식별자 `astra_analysis.v4`는 추가로 조합할 UI 옵션이 아니다. 이미 저장된 v2/v3 결과와 실행 adapter는 유지한다. 사용자가 새로운 흐름으로 바꾸면 새 run으로 생성한다.

Create/Copy/Rerun은 같은 canonical study design resolver를 사용한다. v4 실행은 원자료 고정 → Generic 정량 → 자동 source 준비 → typed 후보 → 별도 footprint → 시간/단백질 통합 → 패키지 검증·발행 순으로 연결된다. Legacy LLM/RAG/report task 전체를 호출하지 않는다. 문헌 선택과 보고서 질문은 작성 맥락으로 전달한다.

공급 intensity 보존을 새 기본값으로 사용한다. 내부 호환 alias `already_normalized.v1`은 추가 scaling 없음이라는 뜻이며 DIA-NN upstream normalization을 확인했다는 뜻이 아니다. 별도 PR/PG median 대안을 함께 계산하고 같은 mask·weight에서 발생한 A offset을 검증한다. 기존 명시적 median 선택은 유지한다.

정량의 statistical unit과 반복/대조군은 canonical design에 의존한다. Generic estimator의 최소 공동 관측 1회와 strict parent의 최소 2회/2 sequence를 구분하며 repeated subset을 별도 제공한다. Biological p/q 방법은 추가하지 않았다.

## 변경 위치와 실제 호출

| 영역 | 구현 |
|---|---|
| UI | `OrderCreate`, `RerunOptionsModal`, `SampleDesignFields`, `CanonicalStudyFields`, `AstraWritingIntent`, `PrimaryAEvidence` |
| API/고정 | `orders.py`, `services/astra_input_capture.py`: 원 입력·문헌 목록을 dispatch 시점에 고정 |
| 공통 입력/계획 | `astra_inputs.py`, `astra_plan.py`: allowlist/필드 manifest/plan/fingerprint |
| 자료 준비 | `astra_sources.py`: registry·bounded provider·검사된 cache·불변 source pin |
| 후보/점수 | `astra_discovery.py`, `motif_candidate_calibration.py`, `motif_library.json`, `kea3_evidence.py` |
| 시간/통합 | `astra_temporal.py`, `astra_evidence.py`: A adapter, mask와 실제 grid, 전체 PG/strict protein |
| 패키지 | `astra_package.py`, `astra_figures.py`: all-row 표·그림·methods·code·replay·hash/FK 검증 |
| 실제 worker | `preprocessing/tasks.py` → `run_primary_analysis()` → `run_astra_analysis()` |

추가 파일은 `git diff`만으로 확인하지 않고 source inventory와 커밋에 포함한다. 과거 22개 Generic CSV 의미는 `quant/` 아래 유지하며 `v3_migration.json`으로 연결한다. 새 typed kinase 표는 기존 빈/curated 표의 의미를 바꾸지 않고 독립된 계약으로 제공한다.

## 진단 D01–D16 대응

| ID | 상태와 근거 |
|---|---|
| D01 | Astra worker의 return 앞에 새 orchestrator의 모든 stage가 실행된다. 완료 상태는 recorded readiness와 함께 제공한다. |
| D02 | Generic 수치 엔진 보존. legacy v3 호출과 새 v4 package 호출을 구분한다. |
| D03 | 실제 provider/motif/footprint/temporal/cross-layer 호출 및 archive 도달을 fixture와 로컬 worker에서 검사한다. |
| D04 | registry 재사용 또는 live OmniPath/iPTMnet 등 수집 후 response hash와 parsed evidence를 고정한다. |
| D05 | 수동 SHA 입력 없이 자동 준비. provider 실패 시 정량·motif를 유지하고 제한을 명시한다. |
| D06 | 관측 onset/peak/recovery, gap AUC, fixed-common membership, target-excluded anchor 및 cross-layer bracket을 제공한다. |
| D07 | 일반 화면에서 preset/annotation mode/snapshot 선택을 제거한다. 실험 사실 검토와 자동 plan 요약을 남긴다. |
| D08 | 새 Astra 기본은 공급 intensity 보존. 명시적 과거 정책은 유지하고 대안 offset을 내보낸다. |
| D09 | 기존 정량·추적 기반과 portable replay를 유지하고 v4 계약으로 확장한다. |
| D10 | Legacy confirmed 혼합 목록을 호출하지 않는다. 직접/orthology/motif/KEA/network/literature 역할을 분리한다. |
| D11 | 새 경로에서는 결측을 0으로 채우는 legacy refinement를 호출하지 않는다. |
| D12 | 새 motif는 exact-center anchoring과 `relative_candidate_weight`를 사용한다. legacy 필드는 호환을 위해 유지한다. |
| D13 | 새 ledger의 parent 정량 적격성과 site 귀속 적격성이 별도다. 단일 PG의 복수 accession만으로 parent를 제외하지 않는다. |
| D14 | canonical A와 측정 그룹을 target-exclusion engine에 전달한다. 반복번호를 biological pairing으로 만들지 않는다. legacy sidecar 전체는 호출하지 않는다. |
| D15 | KEA parser의 p/q/rank/score는 별도 nullable 값이다. 원 response/all rows 보존. 명시 taxon/검증 mapping 없이는 human으로 추정하지 않는다. |
| D16 | 기존 pattern engine을 보조 후보로 재사용하되 AUC/onset/간격/threshold는 새 실제-grid adapter에서 계산한다. NA 구간은 연결하지 않는다. |

## 과학적 해석 경계

후보와 활동 평가를 분리한다. 5 sites/3 genes는 운영 coverage gate이며 미달 후보와 값도 보존한다. Multi-site form은 후보 relation에 남지만 독립 site footprint로 복제하지 않는다. 같은 site의 여러 DB·publication, family/isoform의 공유 기질도 분리한다. Kinase 자체 abundance 및 self-site 관측은 별도 표이며 알려진 regulatory 기능이 없는 부위는 그렇게 표시한다.

Orthology-translated endpoint의 관계는 native 증거가 아니다. Target FASTA 좌표/잔기를 확인하되, 제공 source가 별도 human–rat alignment 증거를 주지 않으면 그 한계를 유지한다. Localization 입력은 정확한 form/accession/site/source에 연결된 실제 값만 사용한다. 부재가 모든 후보의 삭제나 비활성 판정으로 이어지지 않는다.

Source/gene/site/measurement-group/injection omission, shared-site 제외, localized/native/repeated/strict-parent track을 별도로 제공한다. Candidate priority와 activity magnitude를 확률로 합치지 않는다. 기술 측정의 dispersion과 LOTO는 biological confidence interval이 아니다.

LOD는 문서화된 외부 feature/run별 검출한계가 제공된 경우에만 조건부 bound를 계산한다. 이번 HIRc-B에 검증된 LOD는 제공되지 않았다. 검출 최소값을 LOD로 추정하지 않는다.

Provider query에는 시간/횟수 예산이 있다. 이 예산 밖 항목은 `not_run_budget`이며 no-hit이 아니다. 자동 수집은 모든 DB/모든 문헌의 완전 탐색을 보장하지 않는다. 외부 source의 원출처와 response hash, 미조회 ID를 함께 전달한다.
