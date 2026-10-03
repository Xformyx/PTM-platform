# Astra 과학 분석 v5 변경 보고

`6386c553e26530d887649e8a008f19c0938b8bb7`을 기준으로 기존 기능을 확인하고 `feature/astra-science-v5`에서 개발했다. 기존 Order 종이 기준이며 사용자에게 종을 다시 입력시키지 않는다. 기본 profile은 v4로 유지한다. 새 계산/근거는 명시적 opt-in `astra_analysis.v5`, `astra_analysis_package.v5.experimental`, `study_design.v4`로 구분한다.

## 구현 연결

| 경로 | 변경과 과학적 이유 |
|---|---|
| Order → API → worker | nullable scientific file 8개, PR optional protein-only, 관리자·사용자 공통 resolver/dispatch, upload/copy/rerun/input snapshot 전달 |
| reference preflight | 명시 ID/content hash, accession sequence inventory, OX/GN 또는 등록 mapping, mixed/contaminant 분리. FASTA/Order 충돌을 dispatch 전에 차단 |
| measurement observations | 정확한 Run→injection 및 precursor/sequence/charge/PG join, 충돌·원본 필드·contributor 보존. TSV/Parquet, audit_only 및 명시 QC filter |
| scientific identity | 종·accession·서열hash·위치별 site. measurement group과 parent/site 적격성 분리. enzyme taxon은 substrate에서 채우지 않음 |
| quantification | 기존 unit-balanced joint U/P/A, strict paired/complete parent, emergence, 전체 PG 재사용. cross-sectional 및 PG-only를 명시적으로 처리 |
| discovery | 기존 curated/motif 탐색 보존, 실험 specificity local matrix adapter와 별도 typed edge/footprint. heuristic/curated로 승격하지 않음 |
| temporal/selective evidence | fixed membership 재사용, gene/measurement-group 제외, 공유 근거와 제안 해상도. calibration 전 모든 확정 call은 no_call |
| uncertainty/validation | 선택적 unit/pair joint-ratio resampling. 기본 비활성. cohort/run별 4-arm perturbation 기록; global validation flag 없음 |
| package/UI | 과학 표 9개, provenance/keys/FK/replay 확장, 기록된 결과의 입력·판단·측정·단백질 다운로드. UI 복사/재실행 v5 분기 연결 |
| benchmark | 알고리즘 전 계약 commit, study/cohort/ancestry 누출 검사와 unknown truth 제외 metric, immutable 평가 CLI/외부 process adapter |

기존 generic quantification/strict parent/temporal engine을 별도 복사하지 않고 v5 adapter로 호출한다. 새 파일은 `astra_science.py`, `science_reference.py`, `diann_evidence.py`, `kinase_specificity.py`, `science_inference.py`, `perturbation_validation.py`와 versioned family/schema이다. `astra_package.py`는 공통 orchestration/export로 유지하고 scientific 계산은 분리한다.

v4와 달라지는 후보 수/ID/구성은 enzyme taxon 분리, 정확한 site key, 모호한 mapping의 footprint 제한, 추가 specificity track 때문이다. 같은 gene/window의 다른 site를 합치지 않으며 accession mapping 복제로 support를 늘리지 않는다. 새 수를 예전 reference profile 3,948개에 맞추지 않는다. 초기 운영 coverage gate는 calibration된 정확도 기준이 아니다.

## 상태를 구분한다

- **구현 및 synthetic/local integration 확인:** Order 종 재사용, reference 충돌, 원본 관측 연결, 조건 대비 정량, protein-only, 식별/판단/재현 계약.
- **실제 자원 검증 대기:** DIA-NN 버전별 원본 및 site parser, transgene construct 확인, 실제 specificity atlas와 공식 scorer parity, 정렬 검증 가능한 orthology 자원.
- **과학적 개선 미입증:** 독립 human/mouse/rat benchmark, calibrated kinase/family resolution, 공식 comparator 성능, Astra-only 품질 비교.
- **독립 실험 없음:** 실제 perturbation/WB/PRM 자료가 없으므로 pending_data.

일부 구현의 의도적인 제한은 operations_KO.md에 명시했다. 연구별 복잡한 covariate/batch 모델, PG 없는 U-only 실행, 좌표 변경 reference conversion, calibrated family fallback, v5 정량 cache 재사용은 제공하지 않는다. 표의 원문/제외 사유를 남기는 것과 해당 분석을 완성한 것은 구분한다.

## 공개 자료 해석

[DIA-NN 공식 문서](https://github.com/vdemichev/DiaNN)의 run PTM.Site.Confidence, library confidence 및 위치별 localization 자료를 구별한다. 이 프로젝트가 현재 설치한 DIA-NN 또는 실제 사용자 버전을 재실행했다고 주장하지 않는다.

[Kinase Library](https://github.com/TheKinaseLibrary/kinase-library), [PhosX](https://github.com/alussana/phosx) 및 관련 specificity 자원은 검토 대상이며 이 작업에 실제 atlas 파일/공식 scorer를 설치·재배포하지 않았다. 논문과 코드 license가 자료 재배포 허가를 대신하지 않는다. 제공된 local matrix의 hash/semantics/license와 실제 실행을 별도로 기록한다. 내부 scorer를 PhosX 전체 알고리즘, percentile을 kinase 정답 확률로 부르지 않는다.
