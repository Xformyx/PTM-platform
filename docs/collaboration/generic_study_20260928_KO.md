# PTM 범용 설계·Astra 개발 인계

작성: 2026-09-28. 기준: `4b7225bf5c9bff8b38f27c1ff5b3d17c7821cbe1`.
대상 저장소: `Xformyx/PTM-platform`. 이 문서의 로컬 검증은 운영 배포를 뜻하지 않는다.

## 변경 범위

`enrichment_free_timecourse.v3`를 추가했다. 입력 설계는 `study_design.v3`, 정량은 `material_then_unit_balanced_mean_log.v3`, kinase는 `contrast_gene_balanced_footprint.v3`, 전달 계약은 `astra_contrast_bundle.v3`다.

`enrichment_free_primary.v2`는 기존 추정량을 유지한다. 새 화면에서 `hircb_insulin_reference.v1`을 명시적으로 고르면 canonical 설계를 검증한 뒤 기존 HIRc-B 추정량으로 연결한다. 이 preset은 rat phosphorylation, 원래 7개 시간, 조건별 한 material의 세 주입, 검증 snapshot, 추가 scaling 없음이 필요하다. 다른 연구에 이 조건을 적용하지 않는다.

| 문제 | 반영 내용 |
|---|---|
| F01 | 기존 condition, time_points, v1 manifest를 서버 resolver가 가져온다. 목록 위치로 시간을 파일에 배정하지 않는다. |
| F02 | 원 condition·Rep 값을 전달하고 출처를 보존한다. 반복 종류는 Rep로 추론하지 않는다. |
| F03 | 범용 arm/treatment/dose/unit, acquisition, processing으로 분리했다. Legacy insulin dose는 확인된 insulin context에서만 이관한다. |
| F04 | Generic 종/PTM capability와 snapshot 호환성을 검사한다. Rat 제약은 reference adapter에 남는다. |
| F05 | Generic report는 관측 annotation 후보 전체를 coverage·gene/site 수·ID 순으로 표시한다. No-call과 전체 mode도 ZIP에 포함한다. |
| F06 | 6개 유전자와 30/60분 경계는 HIRc-B preset 상수다. Generic은 전체 protein layer와 선택적 사용자 panel/window를 사용한다. |
| F07 | 같은 시간의 다른 조건을 허용한다. Reference와 시간 원점은 별개다. |
| F08 | Generic 정량·strict parent·detection·kinase·omission·protein·replay는 condition/contrast ID를 전달한다. Shared control은 runlevel에 한 번만 존재한다. |
| F09 | 5개 원문 context, 처리/획득 정보, 설계·출처·문제 상태를 study_context/study_design과 provenance hash에 연결했다. |
| F10 | Loading, empty, unauthorized, server/network failure, incompatible, checksum/metadata invalid를 분리했다. |
| F11 | Registry에 database/source/version, 종/PTM, orthology, ID 체계, required audit와 digest를 제공한다. 불명확한 legacy 호환성은 확정하지 않는다. |
| F12 | Generic report/readiness는 실제 종·annotation·localization·반복·panel 설정을 따른다. HIRc-B 설명은 reference 경로에 한정된다. |

주요 신규 코드: `ptm_shared/study_design.py`, `study_execution.py`, `contrast_quantification.py`, `annotation_registry.py`, `generic_kinase.py`, `generic_workflow.py`, `study_presets.py`; 프런트 `CanonicalStudyFields.tsx`, `FrozenAnnotationFields.tsx`.
API에는 `POST /orders/resolve-design`과 실행 시 validation을 연결했다. Worker의 기존 primary-A 진입점이 profile에 따라 generic/reference 경로를 선택한다. 새 DB 테이블이나 기존 결과의 일괄 재계산은 없다.

## 계산과 해석 경계

- 같은 injection의 PTM/PG log₂ ratio를 먼저 만든다. Material 내 technical mean → biological unit 내 material mean → unit 간 동일 가중치 mean이다. Paired contrast는 명시된 pair ID의 공통 관측 차이를 요약한다. Material/unit 관계가 미확정이면 descriptive observation임을 표시한다.
- Generic 주 비교는 한 개 이상의 공동 관측이 있을 때 기술적 효과를 보존한다. 관측 수·집계 unit·mask·injection omission을 함께 제공하며 biological p/q나 CI는 생성하지 않는다. Reference preset은 기존 각 조건 최소 2회 규칙을 유지한다.
- A/U_joint/P_joint는 같은 mask와 같은 집계 정책을 사용한다. U_all/P_all은 각자의 관측 mask다. Gene/site median 후의 kinase 점수에 A=U−P를 강제하지 않는다.
- Strict 대체 parent는 PTM·PG·각 peptide의 공동 관측 ratio, 조건당 최소 2회·최소 2개 sequence를 사용한다. Complete-mask 결과는 별도다. HIRc-B v1/v2/complete 결과도 보존한다.
- Baseline 미검출에는 baseline FC를 만들지 않는다. Arm 및 reference별 최초 반복 검출과 post-reference를 내보낸다. Parent 부적격의 raw 계산 흔적은 eligible_A와 분리된다.
- 모든 PG와 strict-unmodified sequence/protein contrast를 내보낸다. Kinase 자체 단백질량, kinase의 개별 PTM, substrate footprint는 다른 근거다. 사용자 panel은 primary kinase 선택을 바꾸지 않으며, 선언한 경우에만 holdout sensitivity를 추가한다.
- Generic kinase는 phosphorylation만 지원한다. Human/mouse/rat family·noncatalytic 목록과 snapshot alias를 사용한다. HIRc-B source audit는 해당 digest·taxon·매핑된 site·source에만 적용한다. Rat_hir의 human INSR FASTA taxonomy와 rat annotation coverage를 구분한다.
- Localization은 `localization_evidence`의 실제 form/Protein.Group/Modified.Sequence/accession/residue/probability/source가 매칭될 때만 사용한다. 지원 threshold는 0.75, 단일 수정 form이다. Localization이 있어도 기질 coverage가 필요하고, 인과적 kinase 활성 검증을 뜻하지 않는다.
- 정규화는 전체 연구의 고정된 raw column 집합에서 한 번 수행한다. Arm별 재정규화하지 않는다. PR/PG factors, 전후 median, scope, 횟수를 기록한다. `already_normalized.v1`은 추가 scaling 없음이며 DIA-NN upstream normalization의 증거가 아니다.
- Temporal resolver의 실제 측정 grid와 분해능을 전체 protein summary에 연결한다. 미측정 시점 보간, 정밀 지연시간, 직접 조절·인과 추정은 하지 않는다.

## 사용 방법

1. 기존처럼 PR/PG와 시료 분류를 입력한다. Analysis Focus에서 **Generic enrichment-free study: condition contrasts + Astra**를 선택한다.
2. **Review imported study design**에서 가져온 조건·시간·reference를 확인한다. 명확한 단위 label은 자동 변환되며 원문을 보존한다. 충돌 필드만 수정·확인한다.
3. 반복 종류가 미확정일 때만 한 번 선언한다. 조건별 동일 material 반복 주입이면 material/injection ID가 생성된다. 혼합 설계는 펼친 표에서 material/unit/pair를 지정한다. Pairing은 별도 선택이다.
4. 추가 normalization을 확인한다. Annotation이 필수면 호환 snapshot을 선택한다. Annotation 없이 수행할 때는 **quantification_only**를 명시한다. 등록본 변경으로 기존 고정 digest가 바뀌지 않는다.
5. 필요한 경우 treatment dose, volume/mass, pre-treatment, 처리 software 정보를 보완한다. Unknown, none, not applicable을 구분한다. 미제공 값은 추정하지 않는다.
6. Draft를 저장할 수 있다. Start에서 실제 입력 column·설계·profile·snapshot을 검증한다. 결과의 **Primary A evidence**에서 report/primary CSV/Astra ZIP을 내려받는다. **Results → Data Files**에도 같은 run ZIP을 기록한다.

Copy/Rerun은 같은 resolver를 사용한다. 현재 주문 설정을 수정해도 이미 완료된 결과의 provenance/report/ZIP은 유지된다. 재실행은 새 run ID로 계산한다. Generic의 legacy LLM/RAG/Network 및 manuscript 옵션은 비활성 표시되며 실제로 실행하지 않는다. 문헌 collection 선택은 해석 context이고 collection 내용 자체는 bundle에 포함하지 않는다.

HIRc-B 새 검증 주문에는 사용자 선언인 insulin 100 nM, serum starvation 12 h, injection volume 10 µL만 반영했다. DIA-NN 버전·실제 upstream normalization·주입 peptide mass는 unknown이다. 이 값은 generic 기본값이 아니며 과거 ZIP을 수정하지 않았다.

## 검증 결과

환경: macOS arm64, Python 3.14.6 / NumPy 2.5.3 / pandas 3.0.6. 격리된 FastAPI·MySQL 8·Redis 7·Celery와 로컬 Chrome UI를 사용했다. 별도 Python 3.12.14 / NumPy 2.3.5 / pandas 2.2.3에서 generic portable replay도 실행했다. 후자의 환경에는 pytest가 없어 pytest suite는 전자의 프로젝트 검증 venv에서 수행했다.

관련 Python **91개**, Node analysis-context **2개**, `npm run build`가 통과했다. 빌드의 기존 large-chunk/Browserslist 경고는 남는다. 전체 저장소의 모든 테스트를 실행했다는 뜻은 아니다.

| 인수 항목 | 상태 | 근거/범위 |
|---|---|---|
| T01 | passed | 21개 조건/Rep + shared-unit 시간 목록, 7 materials/21 injections 자동 생성 |
| T02 | passed | Rep만으로 unit 미생성; unknown 유지; 명시 선언 후 생성 |
| T03 | passed | Structured/label 충돌의 field path와 실행 차단; 원문 보존 |
| T04 | passed | 0.5h/1d/불규칙 시간, 입력 순서 불변 |
| T05 | passed | AB/CuAB 60·180분 + 공통 baseline의 실제 API/worker 및 UI |
| T06 | passed | 비영점·동일 시간 reference, explicit contrast |
| T07 | passed | 조건당 biological n=1 / technical n=3; p/q 없음 |
| T08 | passed | Technical 2:1인 unit의 효과는 5, injection pooling의 10/3이 아님 |
| T09 | passed | PG 결측과 paired design에서 joint identity 및 실제 mask |
| T10 | passed | Arm별 first detection/post-reference, baseline FC 비생성 |
| T11 | passed | 하나의 Protein.Group에 multiple accession을 허용; 별도 mapping 적격성 |
| T12 | passed | Registry checksum/종 불일치·원자적 복구/immutable retry; UI unauthorized/server/network/metadata/empty/incompatible/checksum 7개 fault injection |
| T13 | passed (synthetic) | Human non-insulin footprint 및 mouse zero-edge fixture. 해당 종의 생물학적 성능 검증은 아님 |
| T14 | passed | Zero form/eligible A/annotation에서도 header·readiness 유지 |
| T15 | passed (synthetic) | Localization 없음 vs 정확한 form/site/source/probability 입력 |
| T16 | passed | 실제 생성·저장·Copy·Rerun·Astra에서 context·volume/unit·설정 보존 |
| T17 | passed | 주문 질문/정규화 수정 후 기존 provenance 불변, 새 run ID |
| T18 | passed | Full PG/strict-unmodified, 선택 panel/window와 실제 grid summary |
| T19 | passed | 전체 연구 PR factors 2/1/0.25, arm별 재적용 없음 |
| T20 | passed | 중단된 export는 pointer 미게시; 두 UI 경로의 같은 ZIP/hash; generic 22개 CSV offline/cross-environment, HIRc-B platform 29개 CSV offline replay |
| T21 | passed | HIRc-B raw 회귀 및 실제 reference preset 생성·Copy·Rerun |
| T22 | passed (targeted) | Standard acetylation context 보존; generic acetylation/ubiquitylation 정량, phosphorylation 전용 kinase 경계 |
| T23 | passed | 질문만 바꿔 실제 재실행: 수치/profile/membership 불변, context hash 변경 |

HIRc-B 기준: forms 2,824 / mapping eligible 2,628 / parent eligible 2,625 / A 평가 가능 2,101 / primary 비교 11,920 / profile 3,948 / baseline 미검출 287 / post ≥2회 261. v1 strict 11,451, paired v2 11,451, complete-mask 11,406. 기존 28개 CSV는 이 환경에서 수치·mask·text 및 bytes까지 일치했다. 원 외부 검토의 21개 수치 동등·14개 bytes 동일 결과와는 다른 실행 기록이다.

최종 플랫폼 HIRc-B ZIP은 portable entry point로 다시 실행하여 `primary_A_input.csv`를 포함한 29개 CSV의 schema·mask·text·수치와 bytes가 모두 일치했다. Generic은 동일 환경 및 위 Python 3.12 환경에서 각각 22개 CSV가 수치와 bytes까지 일치했다. 원본 `astra_handoff.zip`의 88,248,766 bytes 및 SHA-256 `81412530aa78ddebc807671c381370ade511fbacf57d3895aea4ccf04a1b9758`은 변경되지 않았다.

기존 v2 플랫폼 실행과 새 명시적 HIRc-B preset 실행의 29개 CSV도 대조했다. 새 실행에서 달라져야 하는 `primary_A_input.csv`의 `provenance_id`만 제외하고 모든 과학적 열·값·mask·text가 일치했다.

`validate_hircb_independent.py`는 현재 계산 모듈을 사용해 raw→reference를 재대조한 것이다. 이번 작업에서 kinase 전체를 별도의 독립 알고리즘으로 재개발한 검증이라고 주장하지 않는다. 재현성이 생물학적 정확도·인과성·Astra 대비 성능 우위를 입증하지 않는다.

## 검증 진입점과 인계 자료

프로젝트 의존성을 설치한 격리 환경에서 실행한다. 전역 Python 설치를 변경할 필요가 없다.

```bash
PYTHONPATH=.:api-server:workers python -m pytest ptm_shared/tests/test_generic_study.py ptm_shared/tests/test_enrichment_free_evidence.py ptm_shared/tests/test_report_compatible_quantification.py ptm_shared/tests/test_strict_parent_paired.py ptm_shared/tests/test_study_temporal_context.py ptm_shared/tests/test_study_temporal_context_resolution.py api-server/tests/test_analysis_context_preservation.py api-server/tests/test_normalization_provenance_stats.py -q
node --test frontend/tests/analysisContext.test.ts
npm --prefix frontend run build
python scripts/validate_generic_platform.py --help
python scripts/validate_generic_browser.py --help
python scripts/validate_hircb_platform.py --help
python scripts/register_frozen_annotation.py --help
```

Local integration runner는 `scripts/run_local_study_validation.py`다. 자격 정보는 개인 환경 파일/환경 변수로만 전달하고 인계물에 넣지 않는다. Localhost DB/broker만 허용한다. 운영 서버를 대상으로 이 주문 생성 스크립트를 실행하지 않는다.

검토용 전달 디렉터리: `codex-inputs/generic-20260928/delivery/`. 최종 source revision, 변경 diff, 신규 파일을 포함한 source snapshot, 테스트/실행 JSON, 합성 generic ZIP, HIRc-B reference ZIP과 비교 결과를 함께 제공한다. `review_manifest.json`이 파일 크기와 hash를 연결한다. Raw bundle은 Git에 추가하지 않는다.

운영 배포와 `ptm.xformyx.com`의 실제 API/worker/shared reference/UI 확인은 **pending / not run**이다. 로컬 human/mouse fixture 통과는 해당 종 실제 데이터·실제 annotation의 생물학적 검증이 아니다. 운영 등록·배포·되돌리기는 별도 [migration/운영 안내](generic_study_migration_operations_KO.md)를 따른다.
