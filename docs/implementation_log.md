# 구현 원장 (Implementation Log)

**목적:** 논문 methods 절과 사전등록 방어를 위한 append-only 변경 기록.
**규칙:** `.cursor/rules/research-code-provenance.mdc`
**append-only.** 기존 항목을 고치지 않는다. 정정은 새 항목으로 추가하고 이전 항목을 참조한다.

이 원장이 답해야 하는 질문은 하나다 — **"이 값은 결과를 보기 전에 정해졌는가?"**
논문에서 falsifiability를 주장하려면 이 기록 없이는 증명할 방법이 없다.

---

## 항목 템플릿

```markdown
### [YYYY-MM-DD] 제목

- **분류:** 설계 | 사전등록 | 구현 | 측정 | 정정
- **대상:** 파일 경로 또는 문서 §
- **구현 대상 설계:** 문서명 §번호 (없으면 "신규 — 선언 먼저" 사유 기재)
- **사전등록 상태:** 결과 열람 전 확정 | 결과 열람 후 (탐색적, primary 금지) | 해당 없음
- **내용:** 무엇을 했는가
- **논문에서의 용도:** methods / results / limitation / 사용 안 함
- **해석 한계:** 이 변경으로 주장할 수 없는 것
- **결정성:** seed, solver 경로, dtype (측정 항목만)
```

---

## 기록

### [2026-08-20] 내부 데이터셋 교란 감사 재실행 및 수치 정정

- **분류:** 정정
- **대상:** `docs/integrated_research_design_v2.md` §11.1, `docs/core_ab_p2_frozen_contract_v1.md` §7
- **구현 대상 설계:** 외부 검토 지적(재현 가능한 audit table 요구)
- **사전등록 상태:** 해당 없음 (사실 확인)
- **내용:** 사전 지정된 kinase 교란 정의(선택적 억제제 / siRNA / shRNA / CRISPR-KO / 짝지어진
  vehicle·DMSO 대조)로 `data/inputs/*/`의 정량 matrix 헤더를 전수 검사. **정량 matrix 보유
  데이터셋은 19개가 아니라 20개**이며 적격 교란 데이터셋은 0건. 이전 판본의 "19개"는 오류.
- **논문에서의 용도:** limitation (§11 데이터 제약), supplement (데이터셋별 판정 표)
- **해석 한계:** 디렉터리 20개 중 실행 수·명명이 동일한 항목(Irisin 계열 4건 n=28, BIOEN 계열 3건
  n=5, HM 계열 3건 n=11)이 있어 **distinct 실험 단위 수는 20보다 적다. 이 수는 아직 미확정이며
  supplement에는 디렉터리 수가 아니라 실험 단위 수를 선언해야 한다.**
- **결정성:** 검사 대상 = `*pr_matrix*.tsv` | `*pg_matrix*.tsv` | `*report*.tsv` 중 첫 파일의 헤더.
  실행 컬럼 판정 = `\.(mzML|raw|d)$`

### [2026-08-20] C1 판정 규칙 사전등록 초안 작성

- **분류:** 사전등록
- **대상:** `docs/c1_prereg_v1.md` (신규)
- **구현 대상 설계:** `integrated_research_design_v2.md` §5.5.0.1, §5.5.1, §5.5.2
- **사전등록 상태:** **결과 열람 전 확정.** τ는 아직 계산되지 않았다
- **내용:** τ 수식(primary `τ_act`, secondary `τ_col`), 계층 정의(S-DEAD / S-NOFIT / S-RANK1 /
  S-EVAL), E1b 판별력 판정 기준(`R2_iso < 0.80` ∧ `disc ≥ 0.05`), E3 블록 분할(유전자 단위,
  SALT `"c1-prereg-v1"`, 50/50), E3b 개입 목록과 판정, seed 20260820을 확정.
- **논문에서의 용도:** methods (사전등록 프로토콜), supplement (전문)
- **해석 한계:** **아직 동결되지 않았다.** §2.1 인코더 출력 공간과 NNLS 조건 공간 정렬 확인이
  부정이면 τ 정의가 성립하지 않고 이 사전등록은 무효다. 동결 전 필수 3건은 문서 §11에 기재
- **결정성:** seed 20260820, 분할 SALT `"c1-prereg-v1"`, float64, 수치 rank 규칙은 기존
  `_numerical_rank` 재사용

### [2026-08-20] E1b 판별력 검정을 설계에 추가

- **분류:** 설계
- **대상:** `docs/integrated_research_design_v2.md` §5.5.0.1, §5.6, §9.1
- **구현 대상 설계:** 외부 검토 §12-(1) — C1의 신규성이 기존 deconvolution 진단과 구별되는가
- **사전등록 상태:** 결과 열람 전 확정
- **내용:** `condition number`와 `max_column_coherence`가 **이미** `ptm_shared/tmm_identifiability.py`에
  구현되어 동일 site들에 산출됨을 확인. 따라서 "τ는 방향 무관 지표와 다르다"는 §9.1의 논변을 주장으로
  둘 수 없고 실측 판정이 필요. E1b를 신규 실험으로 추가하고 §5.6 반증 조건에 등재.
- **논문에서의 용도:** methods (E1b), results (판별력), 실패 시 limitation
- **해석 한계:** **E1b는 전체 모집단에서 실행하면 거짓 통과한다.** rank-1 site(6오더 실측 54.4%)에서
  `cond`가 ∞로 포화되어 τ와 자동으로 무상관이 되기 때문. `S-EVAL` 계층에 한정해야 한다
- **결정성:** 해당 없음 (설계)

### [2026-08-20] Phase 1 / Phase 2 실행 순서 재배치

- **분류:** 설계
- **대상:** `docs/integrated_research_design_v2.md` §8.1
- **구현 대상 설계:** §0.1.1 강등 경로 (C1이 유일한 단일 실패점)
- **사전등록 상태:** 해당 없음
- **내용:** 기존 순서는 C2/C3 코드 작업을 1~3번, C1 검정을 4~5번에 뒀다. C1이 유일한 단일 실패점이고
  E1이 기존 모듈 확장이라 저렴하므로 순서를 뒤집었다. Phase 1 = gate 임계값 고정 → 판정 규칙 동결 →
  E1 → E1b → E3b. Phase 2 = C2/C3 구현.
- **논문에서의 용도:** 사용 안 함 (프로젝트 관리)
- **해석 한계:** Phase 1이 C1을 기각해도 Phase 2는 유효하나 논제 재구성이 필요하다(§0.1.1)
- **결정성:** 해당 없음

### [2026-08-21] τ의 선행 연구 확인 — resolution matrix와 수학적으로 동일

- **분류:** 정정
- **대상:** `docs/integrated_research_design_v2.md` §9.1.1 (신규), `docs/c1_prereg_v1.md` §4.1
- **구현 대상 설계:** §12-(1) C1 신규성 질문
- **사전등록 상태:** 해당 없음 (선행 조사)
- **내용:** `τ_col = ||P_col(A) d||²/||d||²`에서 `P_col(A) = U_r U_rᵀ = A A⁺ = R_data`이고 직교 정사영은
  `PᵀP = P`이므로 **`τ_col = dᵀ R_data d / dᵀ d`**. 즉 τ_col은 선형 역문제의 **data resolution
  matrix**(Backus–Gilbert 1968; Wiggins 1972; Jackson 1972)를 방향 `d`에서 평가한 Rayleigh 몫이며
  신규 양이 아니다. 별도로, cell-type deconvolution 분야에서 식별가능성 조건(full column rank,
  signature matrix condition number)으로 벤치마크 실패를 설명하는 최근 시도가 존재해 C1의 프레이밍
  공간이 이미 혼잡하다.
- **논문에서의 용도:** **methods 앞부분에서 선제 고지 필수.** 숨기면 심사에서 치명적
- **해석 한계:** C1의 **이론 신규성은 사실상 없다.** 남는 증분은 (a) `τ_act`의 활성집합 사용(NNLS
  특유, 작음), (b) 표현학습–고정 dictionary 합성 문제로의 전이, (c) dictionary가 prior 기반이어서
  rank가 붕괴하고 site 약 46%에서 추정기가 데이터의 함수조차 아니라는 도메인 실증. **C1을 "중심
  기여"로 유지할 수 있는지 재검토 필요**
- **결정성:** 해당 없음

### [2026-08-21] §2.1 정렬 확인 완료 — 조건부 통과, adapter 필수

- **분류:** 측정 (코드 정독. 실행 없음)
- **대상:** `docs/c1_alignment_check_2026-08-21.md` (신규), `docs/c1_prereg_v1.md` §2.1–2.1.3
- **구현 대상 설계:** `c1_prereg_v1.md` §2.1 (동결 전 필수 3건 중 1건)
- **사전등록 상태:** 결과 열람 전 (τ 미계산)
- **내용:** 인코더 `reconstruction = output[:, 0:n_time]`이 Track 2 궤적의 재구성이고 열 순서가
  `multiview.timepoints`와 같음을 확인. **두 경로가 같은 물리량(`PTM_Relative_Log2FC`)을 쓰므로 `d_i`는
  `R^{n_time}`에서 잘 정의된다.** 그러나 5지점이 정렬되지 않는다 — (1) site key 형식
  (인코더 `"GENE POS|form"` vs NNLS `"GENE_POS"`), (2) `key_level="form"` 기본값으로 인한 form↔site
  **다대일 관계**, (3) 인코더가 `control` 조건을 제외하므로 차원 불일치 가능, (4) 열 순서 보장 없음
  (인코더는 분 기준 정렬, NNLS는 저장 순서), (5) 모집단 불일치(인코더 `observed_counts>=3` vs NNLS
  shared site 전체). `TAU_ALIGNMENT_ADAPTER_V1`을 사전등록 §2.1.1에 확정했다.
- **논문에서의 용도:** methods (adapter 명세), limitation (결측 처리 비대칭)
- **해석 한계:** **τ는 부분적으로 "대입 채움 방향"의 전달성을 잰다.** NNLS는 미관측을 0 대입하고
  인코더 재구성은 조밀하므로 `d`가 그 자리에 비영 성분을 갖는다. 영값 대입은 평가 가능 site의 10.1%에서
  top-1을 뒤집으므로 무해한 세부가 아니다. 논문에서 τ를 "표현 변화의 전달성"이 아니라 **"대입 채움을
  포함한 표현 변화의 전달성"**으로 서술한다. 또한 `|S-EVAL|` 추정(0–597)은 교집합 감쇠 미반영이므로
  **실제 상한은 더 낮다**
- **부수 발견:** `scripts/run_representation_fair_probe.py`는 `key_level="site_form"`을 넘기지만
  `_merged_config`가 `"form"` 이외를 모두 `"site"`로 강제하므로 **site 수준**으로 실행된다. production
  표현 학습(`ptm_representation_learning.py`)은 **form 수준**이다. C0 실측 결과가 어느 수준인지 확인 필요
- **신규 미결:** **form → site 집계 규칙.** 다대일이므로 전단사가 아니고 집계가 필요하나 미정.
  후보 4개 열거, 현 권고는 site 수준 설정 확인 + 최다 관측 form 대표. **C1 primary(E3)가 여기 걸려 있어
  동결 전 확정 필수**
- **결정성:** 해당 없음 (코드 정독)

### [2026-08-21] 외부 검토 반영 — 사전등록 통계 설계 6건 수정, 논문 척추 확정

- **분류:** 사전등록 (수정)
- **대상:** `docs/c1_prereg_v1.md` §3.4, §6, §7, `docs/integrated_research_design_v2.md` §9.5, §9.1.3
- **구현 대상 설계:** `docs/external_review_request_2026-08-21.md` 질문 A·B
- **사전등록 상태:** **결과 열람 전 확정.** τ 미계산, held-out 미열람
- **내용:** (1) E1b를 C1 판정 관문에서 제거하고 `R2_iso < 0.80` / `disc ≥ 0.05` 기각 조건 삭제.
  (2) E1b primary 모형을 등위-NNLS 스택에서 ridge 선형(사전 grid, 내부 유전자 블록 CV)으로 교체하고
  등위 스택을 탐색적 sensitivity로 강등. (3) `disc`를 절단점 없는 `D_inv`(정규화 역위 비율)로 교체,
  Kendall tau-b 병기. (4) E3의 50/50 단일 분할을 결정적 5-fold 유전자 블록 교차적합으로 교체하고
  계층 불균형 재배정 규칙 삭제. (5) C1 성공 논리를 **E3 단독 primary**로 확정하고 OR 경로 금지.
  (6) S-DEAD를 baseline 고정 제외 + 유병률·전이표·전체 요약 4결과 동결, 용어를
  `constant-output-by-construction`으로 확정. 논문 척추는 저의 "C2+C3 중심" 초안이 기각되고
  **C0+감사+C1을 증거 있는 foundation으로 유지, C2를 조건부 중심 방법, C3를 독립성 확인 전 보조 모듈**로
  하는 5장 구조를 채택.
- **논문에서의 용도:** methods (사전등록 프로토콜), 논문 outline
- **해석 한계:** 교차적합 도입으로 유효 표본이 2배가 되지만 `S-EVAL` 하한이 여전히 미측정이다.
  `τ_act`의 활성집합 증분은 검토에서 인접 문헌(active set·nonsmoothness·sensitivity, parametric
  QP/NNLS)이 지목되어 **이론 신규성 주장이 불가**하다. 공학적 정식화로만 제시한다
- **결정성:** fold 배정 = `sha256(gene + "c1-prereg-v1") mod 5`, ridge grid `{0.01, 0.1, 1, 10, 100}`,
  순열 10,000회 seed 20260820, 저빈도 규칙 = held-out 군 5 블록 미만이면 해당 fold non-evaluable

### [2026-08-21] C1의 개념적 주장에도 선행 연구 확인 — 중심 기여 유지 불가

- **분류:** 정정
- **대상:** `docs/integrated_research_design_v2.md` §9.1.2, §9.1.3 (신규), §9.5
- **구현 대상 설계:** §12-(1)
- **사전등록 상태:** 해당 없음 (선행 조사)
- **내용:** τ라는 양의 선행 연구(직전 항목)에 이어, **"상류 표현 품질이 고정 하류 추정기로 전달되지
  않을 수 있다"는 개념적 주장 자체**의 선행 연구를 확인했다. objective function mismatch / metrics
  mismatch(Neural Comput. Appl. 2022)가 pretext 성공이 target을 해칠 수 있음을 정식 지표로 정의하고,
  SSL 평가 프로토콜 벤치마킹 문헌이 표현 품질 지표와 하류 성능의 괴리를 확립했다. 특히
  **"Frozen but Not Always Accessible"(arXiv 2608.05329, 2026-08)**은 frozen 표현에 신호가 존재하지만
  readout으로 접근되지 않음을 생물 도메인에서 보인다. 별도로 NNLS 활성집합에 국한한 resolution 해석은
  2회 조사에서 직접 선행 연구를 찾지 못했다(NNLS 문헌은 대부분 알고리즘 고속화).
- **논문에서의 용도:** related work (필수 인용), limitation
- **해석 한계:** **C1을 중심 기여로 유지하는 것은 방어 가능하지 않다.** 잔여 기여는 (a) `τ_act`의
  활성집합 제한(작음, 미발견은 부재의 증명이 아님), (b) prior 기반 dictionary의 rank 붕괴 실증,
  (c) site 약 46%에서 추정기가 데이터의 함수조차 아니라는 감사 결과. (b)(c)는 방법 기여가 아니라
  감사·특성화 기여다. **학위논문 척추 재배치가 필요하며 단일 실패점이 C1에서 C2/C3으로 이동한다**
- **결정성:** 해당 없음

### [2026-08-20] E1의 구현 규모 재평가 — 신규 모듈 아님

- **분류:** 정정
- **대상:** `docs/integrated_research_design_v2.md` §5.5.0
- **구현 대상 설계:** §5.5 E1
- **사전등록 상태:** 해당 없음 (사실 확인)
- **내용:** `ptm_shared/tmm_identifiability.py`에 `solve_nnls`, `_numerical_rank`, `_condition_number`,
  `max_column_coherence`, `group_parallel_columns`, `equal_weight_fallback`, `zero_imputation_bias`,
  `prior_column_fraction`이 이미 구현·테스트되어 있음을 확인
  (`workers/tests/test_tmm_identifiability.py`). E1이 추가로 필요한 것은 τ 하나이며 provenance는 이미
  산출된다. 이전에 "신규 모듈"로 표기한 것은 과대 추정.
- **논문에서의 용도:** methods (기존 진단 재사용 명시)
- **해석 한계:** 같은 사실이 C1의 신규성 위험을 키운다 — 인접 지표가 같은 데이터에 이미 계산되어 있다
- **결정성:** 해당 없음

### [2026-08-21] Chapter 2 감사 프로토콜 `reproduce` 완성 — 동결 fixture

- **분류:** 구현
- **대상:** `ptm_shared/tmm_audit.py` (신규), `scripts/freeze_tmm_audit_fixture.py` (신규),
  `workers/tests/fixtures/tmm_audit_v1/` (신규, git 추적), `docs/chapter2_audit_protocol_v1.md` (신규)
- **구현 대상 설계:** `integrated_research_design_v2.md` §9.5 (`detect → characterize → reproduce
  → guard → regression-test`)
- **사전등록 상태:** 해당 없음 (기존 판정 기준을 바꾸지 않고 입력을 아카이브). 판정 임계는
  `tmm_identifiability.default_thresholds`에서 2026-08-18 동결된 값을 그대로 사용
- **내용:** 공표된 감사 표가 살아 있는 MySQL `orders.kinase_activity_heatmap`과 **gitignore된**
  `data/outputs/**` TSV에서 산출되어 재생성 불가능했다. 감사가 소비한 입력 전체(설계행렬 열,
  후보 이름, prior 플래그, 0 대입 target, 관측 마스크, **원래 site 인덱스**)를 620KB fixture로
  동결. 살아 있는 감사와 재생이 모두 `audit_sites` 하나를 통과하도록 계산 지점을 단일화.
  1,160 site의 후보 열 7,216개가 **서로 다른 벡터 44개**로 수축.
- **논문에서의 용도:** methods (§3 재현 절차), supplement (fixture manifest)
- **해석 한계:** 재현 가능성은 **추적 가능성이며 타당성이 아니다.** 재생이 성공해도 감사의 결론이
  참임을 뜻하지 않는다. `production_ratio_max_deviation`은 재생이 다시 증명하지 않고 동결 시점
  기록을 옮기는 값이다(라이브 모듈 필요)
- **결정성:** seed 0, site별 `seed + site_index`, ε = 0.10·||y||, 부트스트랩 32,
  `nnls_path = scipy.optimize.nnls`, scipy 1.17.1, numpy 2.4.6, float64.
  **정본 환경은 worker 이미지이며 호스트는 scipy 부재로 solver 경로가 달라 재현되지 않는다**

### [2026-08-21] 감사 입력 표류 발견 — 2026-08-18 표 복구 불가

- **분류:** 정정
- **대상:** `docs/tmm_identifiability_diagnosis.md` (초과 표시), `docs/chapter2_audit_protocol_v1.md` §4,
  `docs/integrated_research_design_v2.md` §9.5
- **구현 대상 설계:** `chapter2_audit_protocol_v1.md` §4
- **사전등록 상태:** 해당 없음 (사실 확인)
- **내용:** 첫 동결에서 재생값이 2026-08-18 공표값과 18개 필드에서 어긋났고, 차이가 전부 오더 48
  한 곳이었다(1,310 → 1,160, 정확히 150 site). `orders.kinase_activity_heatmap`은 가변 production
  상태이며 2026-08-20 06:19 재실행이 후보 집합을 덮어썼다(kinase 87→29, module site 235→71,
  공유 site 199→49, 조건 목록 동일, site key 교집합 47). 사라진 후보는 `CSNK2_C1`…`CSNK2_C5`,
  `CAMK2_C0` 같은 **클러스터 접미사 변종**(구 후보 집합의 55.2%).
  **접미사 변종이 중복 열의 원인이라는 가설은 기각.** 정리된 후보 집합에서 중복률이 오히려
  91.0%→95.9%로 올랐고, 같은 base kinase가 한 site 후보 목록에 함께 든 경우는 199개 중 5개(2.5%).
  중복 열은 generic `peak_min = 30.0` fallback이 만든다는 원래 진단이 유지된다.
- **논문에서의 용도:** results (§4 표류 사건), limitation, methods (동결 필요성의 근거)
- **해석 한계:** 결론은 표류에 견딘다(identifiable 1.15%→0.69%, top-1 prior 유래 92.52%→94.14%,
  equal-weight fallback 46.18%→46.29%). **그러나 후보 집합이 왜 87→29로 줄었는지는 미규명이다.**
  LLM 예측·KEA3 응답·설정 변경 중 무엇인지 확인되지 않았고, 재실행마다 흔들리는 것이 확인되면
  §4.2는 관찰에서 **결함**으로 승격되며 BLOCKER-F와 병합해야 한다
- **결정성:** 대조 필드 = `combine()` 출력의 verdict 수·구조 비율·attribution 집계

### [2026-08-21] guard 정책 계층 구현 및 ablation — 기본값은 배포 동작

- **분류:** 구현 · 측정
- **대상:** `ptm_shared/tmm_attribution_guard.py` (신규),
  `api-server/app/services/temporal_kinase_scoring.py` (`compute_weighted_kinase_scores`),
  `scripts/run_tmm_guard_ablation.py` (신규), `scripts/verify_tmm_identifiability_additive.py`
- **구현 대상 설계:** `chapter2_audit_protocol_v1.md` §5
- **사전등록 상태:** 정책과 기본값은 **ablation 측정 전 선언.** 판정 기준은 2026-08-18 동결된
  `attribution_supported`를 그대로 사용하며 새 임계를 도입하지 않았다
- **내용:** 비음수 조합이 궤적을 설명하지 못하는 site의 기여를 가중합에서 빼고
  `contribution_ratio`를 None으로 발표하는 `strict` 정책을 추가. **기본값 `off`는 현재 배포
  동작이며** 오더 36·48·47·28에서 기존 필드 불일치 0건으로 additive 확인(`guard_policy`,
  `n_guard_withheld` 두 키만 추가). 검증 스크립트가 중첩 dict를 통째로 비교해 선언된 키 추가를
  거짓 실패로 잡던 문제도 함께 수정(키별 재귀 비교).
  `unresolved_shared`는 **막지 않는다** — 그룹 몫은 데이터가 결정하므로 증거가 있고, 없는 것은
  내부 분할뿐이다. `unannotated`도 막지 않는다(증거 진술이 아니라 인프라 오류).
  ablation: 보류 site 537/1,160(46.29%), 보류 기여 쌍 3,463/7,216(**47.99%**),
  kinase 163개 중 **74개**가 공유 증거 과반 상실, 4개가 전부 상실.
  보류 site 비율이 감사의 `equal_weight_fallback_rate`와 소수점까지 일치.
- **논문에서의 용도:** methods (§5.1 정책), results (§5.3 ablation 표)
- **해석 한계:** **보류량은 정확도 개선폭이 아니다.** 측정된 것은 발표 범위의 축소다.
  공유 site만 다루므로 exclusive substrate는 집계 밖이며 "공유 증거 중 비율"이다.
  q-value가 fixture에 없어 통과 판정은 `|fc| ≥ 0.3`만 쓴다
- **결정성:** `fc_threshold = 0.3`(production 기본값, 두 arm 동일), 나머지는 fixture manifest와 동일

### [2026-08-21] Chapter 2 회귀 테스트 14개 — 감사 수치와 guard 동작 고정

- **분류:** 구현
- **대상:** `workers/tests/test_tmm_audit_protocol.py` (신규)
- **구현 대상 설계:** `chapter2_audit_protocol_v1.md` §6
- **사전등록 상태:** 고정되는 수치는 **측정 후 확정**(2026-08-21 재생값). 판정 기준은 2026-08-18
  동결분이며 여기서 바뀌지 않았다. 이 테스트는 primary 판정 근거가 아니라 회귀 방어다
- **내용:** fixture 무결성(sha256·스키마·결정성 기록·배포 solver 편차 ≤ 5e-05), 재생이
  `pooled_summary.json`과 한 필드도 다르지 않음, headline 수치 리터럴 고정(1,160 site,
  identifiable 8, equal-weight 537, 발표 쌍 7,216, 추정 가능 그룹 몫 891), 두 번 재생 시 동일,
  DB·`app.services` 없이 동작, fixture 변조 시 거부, guard 정책 4종 동작, ablation 수치 고정,
  보류율 == 균등 fallback 비율. 기존 24개와 합쳐 **38개 통과 (2.39s)**.
- **논문에서의 용도:** methods (§6 회귀 방어), supplement
- **해석 한계:** 테스트 통과는 "감사 수치가 재현된다"만 보장하며 감사 결론의 타당성이 아니다.
  수치가 바뀌면 코드가 틀렸다는 뜻이 아니라 바뀐 사실을 사람이 검토해야 한다는 뜻이다.
  **`pytest`가 이미지에 없어 현재 회귀 방어는 자동이 아니다** — `workers/pyproject.toml`의
  `dev` extra에 선언되어 있으나 `Dockerfile`은 런타임 의존성만 설치한다
- **결정성:** 정본 환경 = worker 이미지 + scipy 1.17.1 + numpy 2.4.6. 호스트(scipy 부재)는
  projected-gradient fallback으로 떨어져 고정 수치가 재현되지 않는다

### [2026-08-21] C2 사전등록 v1 초안 — 조건부 중심 방법 장의 판정 규칙 확정

- **분류:** 사전등록
- **대상:** `docs/c2_prereg_v1.md` (신규), `docs/integrated_research_design_v2.md` §6.3·§6.4·§13
- **구현 대상 설계:** `integrated_research_design_v2.md` §6 (C2), §9.5 Chapter 3
- **사전등록 상태:** **결과 열람 전 확정.** adversary는 미구현이며 C2 실험(E4–E8)은 하나도
  실행되지 않았다. 인용된 실측치(§2)는 2026-08-20 이전에 산출된 **C2 도입 이전 출발점**이며
  판정 대상이 아니라 비교 기준이다. **단 §14의 5건이 미완이므로 아직 동결 아님**
- **내용:** (a)–(d) 정량 판정, 예측기族 P1–P5(scikit-learn 미의존, NumPy/SciPy 결정적),
  λ 격자 8점 `{0,0.05,0.1,0.25,0.5,1.0,2.0,5.0}`과 **λ\* = (a)·(c) 충족 중 최소 λ** 선택 규칙
  ((b)를 최대화하는 λ 선택 금지), frontier 판정, 다중성 논리(E4 단독 primary, OR 성공 금지),
  E8 veto 실험 신설(§6.5 세 번째 반증 조건에 실험이 없었음. 예산 동등성 요구).
  작성 중 발견해 반영한 문제 4건 — ① §6.3 (a)가 gate의 두 하위 조건 중 하나만 적어 부정확했음
  (D는 둘 다 실패, E는 R²만 실패로 실패 양상이 질적으로 다름), ② gate 판정이 induced mask
  단일 seed(0)에 의존 → 5 seed 규칙으로 교체, ③ induced 표적이 다수 site에서 정확히 0
  (`minimum_remaining=3` + 반올림)이라 R² 0.462의 해석이 불확실, ④ **두 coverage 지표의 arm
  순위가 반대** (induced: E 0.273 < D 0.462 < B 0.886 / natural: B 0.388 < E 0.409 < D 0.849).
- **논문에서의 용도:** methods (Chapter 3 판정 규칙), supplement (사전등록 원문)
- **해석 한계:** 이 문서는 판정 규칙만 정하며 C2가 성공한다는 근거가 아니다. (c) 통과 시에도
  허용 서술은 "사전등록된 예측기族 중 어느 것도 mask를 회수하지 못했다"이며 **"mask는 회수
  불가능하다" 또는 "표현이 coverage로부터 독립이다"는 금지**한다(§4.3). tree 계열 부재로 族이
  축 정렬 분할 앙상블을 덮지 않는다. gate는 `key_level="form"`에서 계산되므로 site 단위 결론으로
  확장하지 않는다. C2 성공 시에도 `generalization` gate는 외부 데이터셋 부재로 열려 있어 5/6이 상한.
  **§2.8의 "production handcrafted가 coverage 누출 최악"은 induced 기준에서만 성립한다**
- **결정성:** 인코더 seed 0, adversary 초기화 seed 1(분리), induced mask seed {0,1,2,3,4}(평가
  전용), 예측기 fold 분할 seed 0, 순열 귀무 seed 0. latent_dim = 16 고정. NumPy 전용 유지
  (PyTorch 미도입). **induced mask가 학습 경로에 도달하지 않음을 테스트로 강제**할 것을 요구

### [2026-08-21] §2.8 정정 — coverage 얽힘은 데이터 내재가 아니라 표현이 도입한다 (arm A)

- **분류:** 정정 (직전 항목 "C2 사전등록 v1 초안"의 후속. 그 항목의 문제 목록에 5번째 추가)
- **대상:** `docs/integrated_research_design_v2.md` §2.8·§6.1, `docs/c2_prereg_v1.md` §2.1·§2.2
- **구현 대상 설계:** `integrated_research_design_v2.md` §6.1 (교환의 정식화)
- **사전등록 상태:** **해당 없음 (기존 산출물의 재확인).** 새 측정을 하지 않았다. 인용 값은
  2026-08-20 이전에 이미 산출된 `ptm_representation_benchmark_phospho.json`에 있던 값이며,
  §2.8이 arm A·C를 표에서 누락했던 것을 채운 것이다
- **내용:** §2.8과 §6.1은 교환을 D 대 E의 2-arm 구조로 서술했다. arm 전체를 확인한 결과
  **gate의 두 하위 조건을 동시에 만족하는 arm은 없으나 각각은 개별적으로 만족된다** —
  retention ARI(≥0.20)는 B 0.234·E 0.974가, induced R²(≤0.25)는 **A 0.0073**이 만족한다.
  D만 둘 다 실패한다. arm C는 `skipped_motif_features_unavailable`로 미평가였음도 확인.
  **학습 없는 원 Track 2 궤적(A, 12차원)의 induced R²가 임계의 3%**이며 natural R²도 최저(0.235)다.
- **논문에서의 용도:** results (§2.8 실패 양상 표), methods (C2 표적 설정 근거)
- **해석 한계:** **A는 12차원, B는 30차원, D·E는 16차원이므로 R² 절대값의 arm 간 비교는 판정에
  쓸 수 없다**(§2.5, 예측변수 개수 미보정). 이 관찰은 판정이 아니라 목표 설정 근거다.
  "0.007 대 0.462가 차원 차이로 설명되지 않는다"는 논거이며 형식적 증명이 아니다.
  A가 조건을 하나 만족한다는 것이 **A가 좋은 표현이라는 뜻이 아니다** — 예측 이득이 없고
  (ΔR² −0.0008, p = 0.776) retention ARI 0.167로 다른 조건에서 실패한다.
  "coverage 얽힘을 표현이 도입한다"는 서술은 이 코호트·이 두 지표에 한정된 관찰이다
- **결정성:** 재측정 없음. 출처 = `data/outputs/Insulin_Signaling_Phosphoproteomics_HIRc-B/`
  `ptm_representation_benchmark_phospho.json` (`ablation.variants`, `ablation.adoption_gates`)

### [2026-08-21] C2 동결 전 측정 4건 — 사전등록 동결

- **분류:** 측정
- **대상:** `scripts/measure_c2_prefreeze.py` (신규),
  `ptm_shared/representation/coverage_probes.py` (신규), `docs/c2_prereg_v1.md` §1.3·§2.3·§4.1.1·§14
- **구현 대상 설계:** `c2_prereg_v1.md` §14 동결 전 필수 완료 항목
- **사전등록 상태:** **결과 열람 전 확정된 규칙에 따른 측정.** 판정 임계(0.25, 0.20, 0.5 계수)는
  §14.2에서 이 측정 **전에** 승인·동결되었다. 측정 대상은 **adversary 도입 전 기준선**이며
  C2 성공/실패 판정이 아니다. adversary 미구현, E4–E8 미실행
- **내용:** ① **공표값 정확 재현 확인** — seed 0에서 |Δ ARI| = 0, |Δ R²| = 0. 재현에는
  `epochs = 150`(`benchmark_epochs`, 주 인코더의 300이 아님)과 `eligible_subset()`
  (2,819 → 2,744)이 필수임을 확인. ② **다중 seed** — induced R² 중위수 0.564, 범위
  [0.462, 0.597]. **공표된 seed 0 값 0.462가 5개 중 최솟값**이었다. retention ARI는 0.033–0.048로
  안정적 실패. 0/5 통과. ③ **표적 구조** — 표적은 3값만 가짐(0: 30.36%, 1/6: 55.54%, 2/6: 14.10%).
  R²는 주로 "마스킹 여부"를 설명한다. 관측 시점 3개 site는 구조적으로 전부 표적 0이나 66개(2.4%)뿐이라
  **natural coverage 교란 우려는 기각**. ④ **차원 민감도** — 주성분 절단 R²: rank 4 → 0.033,
  8 → 0.074, 12 → 0.256, 16 → 0.462. arm A 차원(12)에서도 A의 35배이므로 §2.1 관찰 유지.
  ⑤ **예측기族 기준선** — P2 ridge 0.452, P3 kNN **0.625**, P4 RFF kernel ridge 0.620,
  P5 quadratic 0.607. 순열 귀무는 네 族 모두 0 근처. **gate 지표(P1 0.462)가 실제 회수 가능성을
  0.16 과소평가한다.** 이 4건 완료로 `c2_prereg_v1.md`를 동결
- **논문에서의 용도:** methods (재현 설정, 예측기族 구현), results (Chapter 3 기준선 표),
  limitation (gate 지표가 회수 가능성을 과소평가함)
- **해석 한계:** **이 측정은 adversary 효과가 아니다.** 전부 도입 전 상태다.
  차원 절단 결과는 **E8을 대체하지 않는다** — 학습된 16차원을 사후 절단하는 것과 `latent_dim=8`로
  처음부터 학습하는 것은 다르며, 절단이 retention ARI·프로브 ΔR²에 주는 영향은 측정하지 않았다.
  다만 rank 8에서 R² 0.074로 임계를 통과하므로 **E8 veto가 정량화된 실질 위험**임이 확인되었다.
  예측기族은 tree 계열을 덮지 않으므로(§14.3) 0.625가 회수 가능성의 상한이 아니다.
  P4는 RFF 512차 근사이며 정확한 kernel ridge보다 표현력이 낮을 수 있다.
  단일 코호트(HIRc-B), `key_level="form"`, T=6에 한정된다
- **결정성:** 정본 환경 = `ptm-worker-preprocessing`(scipy 필요), NumPy 2.4.6.
  ablation 재현 설정 = `encoder_config{latent_dim 16, hidden_dim 64, epochs 150, seed 0,
  n_perturbations 5}`, `config{neighbors 10, leave_one_out False, minimum_sites 8, seed 0}`,
  입력에 `eligible_subset()` 적용. induced mask seed {0,1,2,3,4}. 예측기 fold·RFF·순열 seed 0,
  RFF 차원 512, 순열 20회, 벌점 격자 {1e-4 … 10}

### [2026-08-21] E8 실행 — 하이퍼파라미터만으로는 gate 통과 불가. C2 veto 발동 안 함

- **분류:** 측정
- **대상:** `scripts/run_c2_e8_hyperparameter_control.py` (신규), `docs/c2_prereg_v1.md` §10.4
- **구현 대상 설계:** `c2_prereg_v1.md` §10 (E8, veto). 근거는
  `integrated_research_design_v2.md` §6.5 세 번째 반증 조건
- **사전등록 상태:** **결과 열람 전 확정.** 격자(§10.1)·예산 동등성(§10.2)·판정(§10.3)·임계(§14.2)가
  모두 실행 전에 동결되었다. 판정 규칙은 실행 후 바뀌지 않았다
- **내용:** 27 구성(latent_dim {8,16,32} × l2 {×0.1,×1,×10} × input_mask_fraction {×0,×1,×2})
  × 5 seed = 162 회 적합, 209초. **조건 (a) 통과 0/27 → veto 발동하지 않음.**
  구조: induced R²(P1)는 latent_dim에 단조 증가(0.13 → 0.57 → 0.64), retention ARI는
  `input_mask_fraction`에 반응(0.033 → 0.079 → 0.111, latent_dim 8 기준)하나 임계 0.20에 미달.
  **`l2`는 100배 범위에서 무정보.** 가장 가까운 구성은 latent_dim 8 / in_mask 0.30
  (ARI 0.111, R² 0.119). **E8 격자에서 구속 조건은 coverage 누출이 아니라 마스킹 하 군집 안정성이다**
- **논문에서의 용도:** methods (§10 veto 설계), results (E8 표), limitation (l2 축 무정보)
- **해석 한계:** **필요조건일 뿐이다.** (a) 통과 구성이 없다는 것은 "이 격자에서는 안 된다"는
  뜻이며 adversary가 성공한다는 뜻이 아니다. E8은 C2를 실패시킬 수만 있고 성공시킬 수 없다.
  latent_dim이 변하므로 R² 절대값을 E4와 직접 비교하지 않는다(§10.1). 단일 코호트
- **결정성:** encoder base `{hidden_dim 64, epochs 150, seed 0, n_perturbations 5}`,
  benchmark `{neighbors 10, leave_one_out False, minimum_sites 8, seed 0}`,
  `eligible_subset()` 적용, induced mask seed {0,1,2,3,4}. 환경 = worker + NumPy 2.4.6

### [2026-08-21] coverage adversary 구현 — 동시 하강 헤드는 gate 를 움직이지 못한다

- **분류:** 구현 + 측정
- **대상:** `ptm_shared/representation/coverage_adversary.py` (신규),
  `ptm_shared/representation/encoder.py` (adversary 배선),
  `workers/tests/test_coverage_adversary.py` (신규, 22건),
  `scripts/verify_coverage_adversary_gradients.py` (신규),
  `scripts/run_c2_e4_adversary_sweep.py` (신규), `docs/c2_prereg_v1.md` §3.1
- **구현 대상 설계:** `c2_prereg_v1.md` §3.1 (구조·표적), §3.2 (결정성), §3.3 (발산 판정),
  §7.1 (λ 격자·재현 대조), §12 (induced 미도달 테스트)
- **사전등록 상태:** **결과 열람 전 확정된 설계의 구현.** λ 격자 8 점·λ\* 규칙·임계 4 종·seed 가
  모두 구현 전에 동결되어 있었다. 기본값 `use_coverage_adversary=False` 로 두어 공표된
  A–E arm 수치는 바뀌지 않는다
- **내용:** NumPy 전용 수동 역전파에 gradient reversal 헤드 2 개(선형+tanh, RFF 512차)를 붙였다.
  표적은 §3.1 대로 **입력의 관측 행렬**에서만 계산한다. 행 표준화된 잠재값을 헤드 입력으로 써서
  예측기族(§4)과 같은 특징을 보게 했고, 인코더가 잠재 크기를 키워 우회하는 경로를 닫았다.
  **동시 하강 모드의 λ sweep 결과가 부정적이다** — adversary 손실은 1.359 → 2.064 로 올라
  두 헤드가 평균 예측 수준으로 무력화되었는데, **같은 임베딩에 최소제곱을 다시 적합하면
  같은 표적의 R² 이 0.798 → 0.721 로 거의 그대로였다.** 즉 정보는 남아 있고 헤드만 못 찾았다.
  gate 지표 induced R² 도 0.564 → 0.507 로 사실상 불변, 5 seed 개별 통과 0/5 (모든 λ).
  부수 관찰: λ 증가에 따라 유효 rank 가 6 → 4 로 줄고 retention ARI 는 0.036 → 0.066 으로
  소폭 상승한다. λ = 0 은 공표 D seed 0 값을 |Δ| = 0 으로 재현했다(§7.1 대조 통과)
- **논문에서의 용도:** methods (adversary 구조), results (동시 하강의 실패와 그 원인),
  discussion — **min-max adversary 와 최적반응 판정 지표 사이의 구조적 불일치**
- **해석 한계:** 이 실패는 "coverage 분리가 불가능하다"의 증거가 **아니다.** 최적화가 판정
  대상에 도달하지 못한 것이며 §13 의 "교환이 근본적" 분기로 보내지 않는다. 단일 코호트
- **결정성:** 유한차분으로 잠재·파라미터 기울기 전부 검증(상대오차 < 1e-8). RFF 가중치를
  비영으로 채운 뒤 재검증 — 초기값 0 이면 RFF 경로가 검증되지 않기 때문이다.
  encoder seed 0, adversary seed 1(§12 대로 분리), induced mask seed {0..4},
  NumPy 2.4.6, 정본 환경 = `ptm-worker-preprocessing`. Stage 1 소요 929s

### [2026-08-21] adversary 를 최적반응으로 개정 — 판정 지표와 학습 목표를 일치시킴

- **분류:** 방법 개정
- **대상:** `ptm_shared/representation/coverage_adversary.py`,
  `docs/c2_prereg_v1.md` §3.1 (개정 2), §15
- **구현 대상 설계:** `c2_prereg_v1.md` §3.1 최적반응 개정 (2026-08-21)
- **사전등록 상태:** **E4 판정 전의 방법 변경이다. 판정 규칙·임계·격자는 바뀌지 않았다.**
  개정 사유가 측정(위 항목의 동시 하강 결과)에 근거하므로 §15 개정 로그에 사유와 시점을
  남겼다. **판정 기준을 결과에 맞춰 바꾼 것이 아니다** — 바뀐 것은 방법이고, 그 방법이
  달성해야 하는 기준은 그대로다
- **내용:** 헤드를 매 epoch 닫힌 형태로 정확히 최소화한다. 헤드 1 은 절편 포함 무벌점
  최소제곱(gate 지표와 **같은 함수형**), 헤드 2 는 RFF 위 ridge(벌점 1e-3 고정).
  헤드가 최소해이므로 envelope theorem 에 의해 `dL*/dU = ∂L/∂U|_{w*}` 이고, 헤드
  파라미터를 학습시키지 않아도 올바른 상승 방향을 얻는다. 구현 중 두 가지 오류를 유한차분이
  잡아냈다 — (1) ridge 벌점항을 손실에서 빼고 보고하면 ∂L/∂w = 0 이 아닌 양을 미분하게 되어
  기울기가 틀린다(상대오차 0.11), (2) RFF 대역폭을 매 호출 median heuristic 으로 재추정하면
  사상이 U 의 함수가 되어 역시 틀린다(0.13). 벌점항을 포함해 보고하고 대역폭을 첫 호출에서
  동결해 둘 다 해소했다(상대오차 2.4e-9)
- **논문에서의 용도:** methods (adversary 명세), discussion — **판정 지표가 최적반응 적합일 때
  동시 하강 adversary 는 판정 대상을 겪지 않는다**는 방법론적 지적
- **해석 한계:** 두 헤드는 **표본 내** 적합이고 헤드 2 의 벌점은 고정값이다. 조건 (c) 의
  P2–P5 는 벌점을 내부 CV 로 고르는 **표본 외** 교차적합이므로 둘은 같은 양이 아니다.
  **최적반응 헤드를 이긴 것이 (c) 통과를 뜻하지 않는다.** 국소(kNN) 성분에 직접 대응하는
  미분 가능한 헤드는 여전히 없다 — §13 반증 분기 2 는 열린 채다
- **결정성:** solver 경로를 산출 레코드에 기록(`numpy.linalg.lstsq`, `numpy.linalg.solve`,
  `rff_ridge_penalty=1e-3`), 동결 대역폭 값도 기록. λ = 0 재현 대조를 스크립트가 강제하며
  불일치 시 결과를 출력하지 않고 종료한다

### [2026-08-22] C1 계층 실측 — **세 사전등록 수준 전부 검정력 미달. τ 는 아직 산정하지 않았다**

- **분류:** 측정 (사전등록된 선행 측정. τ 미열람)
- **대상:** `scripts/measure_c1_strata.py` (신규),
  `docs/c1_prereg_v1.md` §2.1.2·§2.2·§3.1.1·§3.5·§11,
  `docs/c1_alignment_check_2026-08-21.md` §5·§6,
  산출물 `data/outputs/_diagnostics/c1_strata_v1/measurement.json`
- **구현 대상 설계:** `c1_prereg_v1.md` §3.1 (계층 정의), §3.2 (계층 크기 선행 측정 요구),
  §3.3 (확장 경로 L1→L2→L3), §3.4 (검정력 구간), §2.1.1 A1·A3·A4·A5
- **사전등록 상태:** **결과 열람 전.** 계층 정의·확장 순서·검정력 구간이 2026-08-20~21 에
  동결되었고 **어느 것도 바꾸지 않았다.** τ 는 계산하지 않았다 — §3.2 가 요구한 순서
  (모집단 확정 → τ)를 지켰으므로 primary 자격은 유지된다
- **내용:** **`|S-EVAL ∩ adapter|` 가 L1 ≤ 58, L2 = 58, L3 = 66 으로 세 수준 전부 임계 73 에
  미달한다.** §3.4 의 마지막 조항(주장 철회 또는 새 데이터 요건 선언)이 발동했고 분기 선택은
  §3.5 에 미결로 기록했다. L2 ∪ L3 = 124 는 두 번째 구간에 들어가지만 **미달을 본 뒤 만든
  수준이므로 primary 승격 영구 불가**로 명시했다.
  **동시에 정렬 5지점 중 3지점이 해소되었다** — A3(오더 52 조건에 control 없음),
  A4(수열이 저장 순서 그대로 일치), A1·A5(form 수준과 site 수준의 고유 site 집합이 모두 2,377
  로 동일). 그 결과 §2.1.2 미결이 **`A2 = SITE_LEVEL_ENCODER_V1`** 으로 확정되었다 —
  집계 함수 자체가 불필요해진다.
  부수 관찰 2건: HIRc-B 가 pool 보다 건강하다(S-DEAD 10.0% 대 46.3%, S-EVAL 12.60% 대 7.93%)
  — `|S-EVAL|` 이 작은 것은 site 수가 적기 때문이다(500 대 1,160). 그리고 오더 간 S-EVAL 비율이
  0.0%(WithoutCu-AmyloidFibril, 86 site 전부 미달)~33.3%(Microgravity)로 흩어진다
- **논문에서의 용도:** Chapter 4 (C1) 의 모집단 절과 한계 절. **미달 자체가 §3.2 가 예고한
  위험의 실현이며 사후 발견이 아니다.** 사전등록이 이 순서를 강제한 것의 값어치가 여기서 나온다
- **해석 한계:** 계층 비율은 검사한 오더의 유병률이며 모집단 추정치가 아니다.
  **`|S-EVAL|` 이 작다는 것을 "표현 학습이 무용하다"로 읽지 않는다** — 퇴화는 하류 사전의
  성질이고 상류 표현의 성질이 아니다. 오더 52 의 살아 있는 입력은 버전 관리되지 않으므로
  L2 수치는 Chapter 2 의 표류 위험을 같은 방식으로 안고 있다(L3 는 동결 fixture 사용)
- **결정성:** ε = 0.10·||y||, bootstrap 32, site 별 seed = site_index, scipy 1.17.1 `nnls`,
  NumPy 2.4.6, float64. L3 는 `tmm_audit_v1` fixture(sha256 검증) 재생. 소요 96s

### [2026-08-22] 결정성 결함 수정 — 프로브 분할 salt. 그리고 C0 공표 프로브 표의 설정 확정

- **분류:** 수정 (결정성 복구) + 측정 (탐색적 교정)
- **대상:** `ptm_shared/representation/fair_probe.py` (`_arm_seed_component` 신규),
  `ptm_shared/representation/benchmark.py` (`_encode_reference_labels` 신규),
  `scripts/quantify_probe_split_sensitivity.py` (신규),
  `scripts/run_c2_e5_frontier.py` (`--key-level`·`--no-adversary`·`--no-eligible-filter`·per_arm 표),
  `docs/c2_prereg_v1.md` §7.2.2·§12.1,
  `docs/ptm_representation_learning_contract_v1.md` §R1.6 주석
- **구현 대상 설계:** `.cursor/rules/research-code-provenance.mdc` §5 (결정성 기록),
  `c2_prereg_v1.md` §12 (결정성과 seed)
- **사전등록 상태:** 결함 발견은 C2 판정(2026-08-21) **후**다. 따라서 교정 측정은 **탐색적**이며
  **§5.2 임계 0.01355 를 옮기지 않았다.** 코드 수정은 측정량의 정의를 바꾸지 않고 분할 배정만
  실행 간 고정하므로 결정성 복구에 해당한다
- **내용:** 프로브 분할 RNG 의 arm 성분이 `hash(arm)` 이었고 `PYTHONHASHSEED` 가 정본 컨테이너에
  설정되지 않으므로 **같은 seed·같은 입력이 실행마다 다른 분할을 뽑았다.** 흩어짐은 폭 0.00318,
  실행 간 sd 0.00158 (salt 4점). `crc32` 로 교체했다.
  **이 결함이 공표값 미재현의 원인은 아니었다** — 간격 0.0083 이 흩어짐 폭보다 크다. 설정을
  역추적해 4번째 시도에서 재현했다: `key_level="site"`, **`eligible_subset()` 미적용(2,447 site)**,
  epochs 300, arms (A,B,D,E) → ΔR² = 0.02681. 차원 4개 일치, B·D·E 평균 R² 소수 4째 자리 일치.
  **즉 §5.2 임계는 유효한 출처를 갖는다.** 단 C2 frontier(form 적격 2,744)와 모집단이 다르므로
  절대값 비교는 근사다. 8 점 전부 통과이므로 (b) 판정은 불변
- **논문에서의 용도:** Chapter 1(C0)의 프로브 표에 설정 출처 주석. Chapter 3 의 (b) 절대값
  해석 한계. **그리고 Chapter 2 의 논지 보강** — 재현 불가능성이 감사 대상 시스템만의 문제가
  아니라 연구 코드 자신에게도 있었다는 자기 적용 사례다
- **해석 한계:** 흩어짐은 한 λ 점·한 코호트·저비용 설정(epochs 150, arm B·D)에서 측정했다.
  공표값 설정의 흩어짐과 같다고 가정하지 않는다. **수정 이전 프로브 수치는 수정 이후 수치와
  절대값으로 비교할 수 없다.** 한 실행 내부의 짝지은 비교는 수정 전에도 유효했다
  (두 arm 이 같은 분할을 공유하므로 sign-flip 검정은 영향 없음). gate 지표(induced R², ARI)는
  `benchmark.py` 경로이며 이 seed 를 쓰지 않으므로 영향 없다
- **결정성:** `crc32("B") % 9973 = 6706`, `crc32("D") % 9973 = 9741`. ARI 라벨 인코딩은
  순서 기반 정수로 바꿨으나 **ARI 가 라벨 재명명에 불변이므로 값은 동일**하다.
  소요: 흩어짐 측정 1475s, 교정 4회 각 113~7527s

### [2026-08-21] E4/E5/E6 판정 — **λ\* 없음. C2 실패. 한계 기술 장으로 확정**

- **분류:** 측정 (primary 판정)
- **대상:** `scripts/run_c2_e4_adversary_sweep.py`, `scripts/run_c2_e5_frontier.py`,
  `scripts/measure_c2_arm_baselines.py` (모두 신규),
  `docs/c2_prereg_v1.md` §6.1·§6.2·§7.2.1·§8.1·§13.1,
  `docs/integrated_research_design_v2.md` §9.5·§13
- **구현 대상 설계:** `c2_prereg_v1.md` §6 (E4, primary), §7 (E5 frontier·λ\* 규칙),
  §8 (E6 예측기族), §5.4 (4-arm 필수 병기)
- **사전등록 상태:** **결과 열람 전 확정.** λ 격자·λ\* 규칙·임계 4 종·seed 가 실행 전에
  동결되어 있었고 **판정 후 어느 것도 바꾸지 않았다.** §13.1 은 사전등록 분기 문구를 실측에
  맞게 **좁혔을** 뿐이다
- **내용:** **λ\* 가 존재하지 않아 C2 인증서가 충족되지 않았다.** 독립적인 두 원인 —
  (1) 조건 (a) 의 ARI 하위 조건이 8 λ 전체에서 최대 0.066 (임계 0.20),
  (2) 조건 (c) 가 8 λ 전체에서 族 최대 ≥ 0.513 (임계 0.25).
  **한편 coverage 축은 해결되었다** — induced R² 0.564 → 0.042, 유효 rank 6 → 5~6 으로
  차원 붕괴 없이. λ = 0.05 만으로 이미 임계를 통과한다.
  **E6 이 사전등록된 §8 경고 신호를 발동시켰으나 예상보다 좁게** — 매끄러운 성분은 전부
  제거되고(선형 0.452 → 0.024, 2차 0.607 → 0.094, RFF 0.620 → 0.216) **국소 성분만 남는다**
  (kNN 0.625 → 0.513, −17.9%). 즉 **coverage 인코딩은 환원 불가능하게 국소적이다.**
  frontier 의 예측력 축은 ΔR² 이 λ 와 함께 **단조 증가**(0.0160 → 0.0222, 24/24 우세)하여
  "예측력을 팔았음" 분기는 발동하지 않았다.
  4-arm 대조가 §2.1 의 해석을 정정한다 — ARI 임계 0.20 은 도달 가능하며(B 0.248, E 0.974)
  **arm D 가 그 축에서 유별나게 나쁘다(0.036).** 비학습 arm A(0.162)보다도 낮다
- **논문에서의 용도:** Chapter 3 전체 (**방법 장이 아니라 한계 기술 장**). 방어 가능한 결과 4 건은
  `c2_prereg_v1.md` §13.2. 특히 **조건 (c) 를 예측기族으로 정의한 사전등록 결정의 정당화** —
  gate 지표(P1)만 보면 λ = 0.05 에서 통과이며 (c) 없이는 성공으로 오보고되었을 것이다
- **해석 한계:** 단일 코호트(HIRc-B, T = 6, form 단위). **"교환이 근본적"이라고 서술하지
  않는다** — coverage 축과 예측력 축은 동시에 개선되며 막힌 것은 ARI 축이고 그것은 arm 문제다.
  kNN 0.513 이 회수 가능성의 상한도 아니다(tree 계열 미포함, §14.3).
  **(b) 의 절대값 비교는 정확히 교정되지 않았다** — 임계 0.01355 는 공표값 0.0271(epochs 300,
  arms A·B·D·E)의 절반인데 측정은 ablation 설정(epochs 150, arms B·D)에서 했고 λ = 0 이
  0.01597 을 낸다. 방어 가능한 읽기는 한 설정을 공유하는 8 점의 **추세**다
- **결정성:** encoder seed 0, adversary seed 1, induced mask seed {0..4}, 예측기 fold seed 0,
  순열 20회, RFF 512차, 동결 대역폭 1.41406223. λ = 0 재현 대조 |Δ| = 0 (스크립트가 강제).
  NumPy 2.4.6, 정본 환경 `ptm-worker-preprocessing`. 소요 E4+E6 약 25분, frontier 2811s,
  4-arm 18s

### [2026-08-21] 탐색적 진단 — missingness_validity gate 는 비선형화만으로 통과될 수 있다

- **분류:** 측정 (탐색적)
- **대상:** `scripts/probe_c2_low_dimension_regime.py` (신규), `docs/c2_prereg_v1.md` §10.5·§3.1
- **구현 대상 설계:** **없음. 사전등록되지 않은 분석이다**
- **사전등록 상태:** **결과 열람 후 착수. exploratory. primary 판정 승격 영구 금지**
  (`c2_prereg_v1.md` §11). E8 결과를 본 뒤 그 해석을 위해 실행했다
- **내용:** E8에서 `latent_dim = 8`이 gate의 R² 조건을 통과했으므로 그 구성의 조건 (c)·(b)를
  측정. **kNN 회수율이 구성과 거의 무관하다** — latent 8/in_mask 0.30: 0.618,
  latent 8/in_mask 0.15: 0.598, latent 16/in_mask 0.30: 0.622, 원 D: 0.625.
  반면 gate 지표 P1은 0.462 → 0.086으로 5.4배 감소한다. **즉 coverage 인코딩이 제거된 것이
  아니라 비선형·국소 구조로 옮겨갔을 뿐이다.** `latent 8 / in_mask 0.15`는 예측력도 유지
  (ΔR² 0.0182 ≥ 0.01355, 24/24 우세, p = 0.0001). 즉 **(a)의 R² 조건과 (b)를 동시에 만족하면서
  (c)를 크게 위반하는 구성이 실재한다.** 이 발견을 반영해 §3.1의 adversary 헤드에 RFF 헤드를
  추가했다(방법 변경. 판정 규칙 변경 아님. E4 착수 전)
- **논문에서의 용도:** limitation / discussion — **배포된 gate의 방법론적 취약점**.
  조건 (c)를 예측기族으로 정의한 사전등록 결정의 정당화 사례. **primary 결과로 쓰지 않는다**
- **해석 한계:** **탐색적이다.** 단일 seed(0), 4개 구성만. E8의 정식 판정은 §10.4이며 이 표가
  아니다. "latent_dim을 낮추면 안 된다"는 결론이 아니다 — 낮춰도 실제 누출이 줄지 않는다는
  것이지 낮추는 것이 해롭다는 것이 아니다. kNN 회수율 0.60이 회수 가능성의 상한도 아니다
  (tree 계열 미포함, §14.3)
- **결정성:** E8과 동일한 encoder/benchmark 설정. induced mask seed 0.
  예측기族 seed 0, RFF 512차, 순열 20회. 공정 프로브는 `arms=("B","D")`, baseline B,
  기본 설정(`n_encoder_seeds` 5, `n_probe_splits` 4) → 24 짝

---

### [2026-08-22] C1 §3.5 분기 확정 — (i) 강등 + (iii) 탐색적 7 오더 pool

- **분류:** 사전등록
- **대상:** `docs/c1_prereg_v1.md` §3.5.1–3.5.3, §2.1.4, §2.1.4.1, §2.1.4.2, §7.3.1
- **구현 대상 설계:** `c1_prereg_v1.md` §3.4 마지막 조항, §0.1.1 강등 경로
- **사전등록 상태:** **결과 열람 전 확정.** τ 를 산정하기 전에 기록했다. 이 순서가 아래 측정
  항목의 지위를 결정하므로 원장에 별도 항목으로 남긴다.
- **내용:**
  - §3.1.1 에서 세 확장 수준 전부 `|S-EVAL| < 73` 이 확정된 뒤, §3.5 의 세 분기 중
    **(i) 강등 + (iii) 탐색적 7 오더 pool** 을 선택해 기록. E3 를 primary 에서 내렸다.
  - §3.5.3 — E2 를 **prior-free 축만으로 축소 수행**으로 확정. 국소 KSA 라이브러리가 없어
    KSA 버전 교체 축이 실행 불가이며, 이를 "E2 통과"로 서술하지 않기로 명문화.
  - §2.1.4 — `d` 의 baseline 을 `zero_imputed_l1_trajectory`(NNLS 가 실제 소비하는 영값 대입
    궤적), 처리 arm 을 **arm D**(`learned_temporal_representation`)로 명시. §2.1 의
    `ŷ(arm L1)` 이 코드에서 무엇인지 미규정이었고, §2.1.3 의 서술이 이미 이 baseline 을
    전제하고 있었으므로 새로 고른 것이 아니라 적어 둔 것이다.
  - §2.1.4 — `arm L1`(표현 층 이름)과 `population L1`(모집단 수준)의 용어 충돌 정리.
  - §2.1.4.1 — 관측 성분만의 τ(`d_obs`)를 secondary 로 추가. §2.1.3 의 결측 비대칭 한계를
    **선언에서 측정으로** 전환.
  - §2.1.4.2 — **A6 신규 발견.** NNLS `load_timeseries` 는 form 값을 last-wins 로 덮어쓰고
    인코더 `feature_contract` 는 mean 을 쓴다. 보정하지 않고 크기를 측정하기로 확정.
  - §7.3.1 — 블록 집계를 **median** 으로 고정(대안 탐색 금지), bootstrap seed·반복수 확정.
    §7.3 이 후보를 열거하지 않아 통제되지 않은 자유도로 남아 있던 지점이다.
- **논문에서의 용도:** methods (사전등록 절차와 강등 경로), limitation (E2 축소 범위)
- **해석 한계:** (iii) 의 7 오더 pool 은 **primary 승격 영구 불가**다. 미달을 본 뒤 만든
  수준이므로 §3.3 이 막으려던 사후 모집단 선택과 형식적으로 같다. (i) 없이 (iii) 단독은
  사전등록 위반이다.
- **결정성:** 해당 없음 (문서 변경)

### [2026-08-22] C1 τ 모듈 구현 + E1 측정 (7 오더 pool)

- **분류:** 구현 + 측정
- **대상:** `ptm_shared/c1_transmissibility.py` (신규),
  `scripts/run_c1_e1_transmissibility.py` (신규),
  `scripts/measure_c1_strata.py` (§5.1 provenance 필드 추가)
- **구현 대상 설계:** `c1_prereg_v1.md` §4 (τ 정의), §5 (E1 출력·요약), §7.4 (Δẑ), §8.1 (개입)
- **사전등록 상태:** **판정 규칙은 결과 열람 전 확정.** 모듈은 그 규칙을 적용할 뿐 임계를
  새로 도입하지 않으며, 모든 상수가 문서 절을 인용한다.
- **내용:**
  - `transmissibility`, `column_space_projector`, `active_columns`, `downstream_response`,
    `site_transmissibility`, `quantile_summary`, `summarize_by_stratum`, `primary_tau_field`
    구현. rank 규칙은 `tmm_identifiability._numerical_rank` 를 **재사용**(복제 금지).
  - E3b 개입 I1–I4 를 `merge_duplicate_columns`, `drop_prior_columns`, `augment_rank`,
    `truncate_rank` 로 구현.
  - `measure_c1_strata.classify_strata` 에 §5.1 이 요구하는 진단 필드를 **추가**(계층 배정
    논리 불변). `diagnose_site` 를 두 번 호출하지 않기 위해서다.
  - E1 실행: 7 오더(오더 52 live + 동결 6 오더 fixture), adapter 내 1,410 site,
    `S-EVAL ∩ adapter` = **124**(L2 58 + L3 66 — §3.1.1 실측과 정확히 일치).
- **측정 결과 (`c1_prereg_v1.md` §10.1.1 에 전문):**
  - `S-EVAL` `τ_act` p10/p50/p90 = 0.066 / 0.386 / 0.930. `τ_col` p50 = 0.989.
    S-DEAD 0.000, S-RANK1 p50 0.180.
  - **§4.2 승격 규칙 발동.** 활성집합 불안정 비율 0.460 > 0.30 → 사전등록된 primary 가
    `τ_act` → `τ_col`. 그러나 `τ_col` 은 `K_i >= T` 때문에 포화되어 site 를 구별하지 못한다.
    **규칙을 어기지 않고 두 값을 병기하며 이 딜레마를 기술한다.**
  - §4.3 일치 확인 3건 전부 통과: S-DEAD 플래그 불일치 0, 활성집합 불일치 0,
    τ 단위구간 이탈 0, 경계 규약 제외 0건.
  - **A6 해소.** `||agg_mismatch|| / ||d_obs||` p50 ≈ 1e-16 (부동소수점 수준). `c1_prereg_v1.md`
    §2.2 의 τ 성분 (3)(form 집계 차이)은 측정해서 배제했다.
- **논문에서의 용도:** results (τ 계층 분해), methods (adapter 와 baseline 정의),
  limitation (승격 규칙 딜레마, 결측 비대칭)
- **해석 한계:** τ 는 **반사실 섭동**의 전달성이며 production 변화가 아니다. **전달 가능성의
  필요조건**이고 하류 개선의 상한이 아니다. τ 에 (1) 궤적 변화와 (2) 대입 채움이 섞여 있고
  분리되지 않는다((3) 집계 차이는 배제됨). `τ_dd` 는 데이터 유래 열이 적어 primary 가 아니다.
  **금지:** 이 값으로 kinase 귀속 정확도를 논하는 것, "τ 가 낮으므로 표현 학습이 무용하다".
- **결정성:** 인코더 seed 0, `key_level="site"`, `minimum_observed_timepoints=3`,
  `eligible_subset()` 적용, arm D(`use_protein_context=False`, `use_track1=False`),
  adversary 미사용. NNLS = `scipy.optimize.nnls`(API 컨테이너), dtype float64,
  rank 규칙 `sigma > sigma_0 * max(shape) * eps`. `PYTHONHASHSEED=0`.
  산출물 `data/outputs/_diagnostics/c1_e1_v1/tau.json`.

### [2026-08-22] C1 추론 모듈 + E1b 기술 통계 + E3 미평가 확정

- **분류:** 구현 + 측정
- **대상:** `ptm_shared/c1_inference.py` (신규), `scripts/run_c1_e1b_e3.py` (신규)
- **구현 대상 설계:** `c1_prereg_v1.md` §6.2–6.5 (E1b), §7.2–7.4 (E3), §7.3.1 (집계·seed)
- **사전등록 상태:** 규칙은 결과 열람 전 확정. `descriptive_association` 만 **E3 미평가 확정
  후 추가**했으므로 영구 탐색적이며 그 사실을 함수 docstring 과 반환 status 에 기록했다.
- **내용:**
  - fold 배정을 `sha256(gene + "c1-prereg-v1") mod 5` 로 구현. **`hash()` 를 쓰지 않는다** —
    공정 프로브에서 발견된 `PYTHONHASHSEED` 결정성 결함(2026-08-22 항목)의 재발 방지.
  - E1b: 표준화 ridge(사전 격자 5점, 내부 유전자 블록 CV), OOF Spearman·R², 유전자 블록
    bootstrap 95% CI, `D_inv`(동점 half-credit) primary, Kendall tau-b redundant.
    **p-value 를 산출하지 않는다**(§6.5) — 회귀 테스트가 필드 부재를 검사한다.
  - E3: 유전자 블록 5-fold 교차적합, training fold q20/q80 임계, 블록 median 집계,
    블록 순열검정 10,000회, Cliff's delta. `scipy` 를 쓰지 않는다(결정성).
- **측정 결과 (`c1_prereg_v1.md` §10.1.2–10.1.3):**
  - E1b (pool `S-EVAL` 124 site, 101 블록): `τ_act` OOF Spearman 0.359 [0.205, 0.499],
    OOF R² 0.125 [−0.006, 0.224], `D_inv` 0.382. `τ_col` 0.798 [0.722, 0.843],
    R² 0.552 [0.398, 0.670], `D_inv` 0.206.
    → `τ_act` 는 사전 확정 기하 요약으로 잘 설명되지 않고, `τ_col` 은 상당히 중복된다.
    후자는 §9.1.1 의 선행 연구 고지(data resolution matrix)와 정합한다.
    **§4.2 승격의 두 번째 대가**: 승격은 primary 를 더 중복된 지표로 옮긴다.
  - **E3 = 미평가.** §7.2 의 저빈도 규칙(fold 당 high/low 군 각 최소 5 블록)이 **5 fold
    전부에서 발동**했다. 101 블록 → fold 당 held-out 13–32, q20/q80 후 각 군 2–7 블록.
    §7.2 가 대체 분할 탐색을 "핵심 금지 사항"으로 적었으므로 다른 분할을 시도하지 않았다.
  - 심사 대비로 동일 표본 Spearman(τ, Δẑ) 을 보고하고 §7.1 근거로 스스로 기각:
    `τ_act` site −0.089 / 블록 −0.198, `τ_col` site 0.072 / 블록 −0.012.
- **논문에서의 용도:** results (E1b 중복도), limitation (E3 미평가),
  **methods 관찰** (클러스터 단위 추론과 검정력 사전등록의 불일치)
- **해석 한계:** E1b 는 판정 관문이 아니며 어떤 임계로도 C1 을 기각하지 않는다. 단순 ridge
  비교자를 이긴 것이 τ 의 비환원성 증명이 아니다. E3 는 **미평가이며 실패가 아니다** —
  증거 부재와 부정 증거를 구별한다. 동일 표본 상관은 어느 방향으로도 증거가 아니다.
  **금지:** E3 결과로 C1 성공 선언(§6.6 OR 경로 금지), 통과/실패 라벨(§3.5.2).
- **결정성:** seed 20260820(순열·bootstrap 공통), 순열 10,000, bootstrap 10,000,
  `numpy.random.default_rng` (PCG64), dtype float64, scipy 미사용,
  fold = `sha256(gene + "c1-prereg-v1") mod 5`.
  산출물 `data/outputs/_diagnostics/c1_e1_v1/e1b_e3.json`.

### [2026-08-22] C1 E2 축소 수행 + E3b 합성 개입 — 진단 민감도 입증

- **분류:** 구현 + 측정
- **대상:** `scripts/run_c1_e2_e3b.py` (신규),
  `ptm_shared/c1_inference.py` (`exact_sign_test`, E3b 임계 추가)
- **구현 대상 설계:** `c1_prereg_v1.md` §8.1 (I1–I4), §8.2 (판정), §3.5.3 (E2 축소)
- **사전등록 상태:** 개입 목록과 판정(부호 일치 ≥ 0.80, 양측 p < 0.05)은 2026-08-20 동결.
  `RANK_STEPS = 3` 만 신규이며 **결과 열람 전** 확정하고 사유를 코드에 기록했다
  (§8.1 이 "단계적으로" 만 규정하고 단계 수를 정하지 않았다).
- **내용:** `S-EVAL` 124 site 에서 I1–I4 실행. 개입 후 활성집합을 **다시 구한다** — 원본
  활성집합을 재사용하면 개입이 활성집합을 바꾸는 효과가 사라져 민감도가 과소평정된다.
  부호검정은 정확 이항으로 구현(scipy 미사용).
- **측정 결과 (`c1_prereg_v1.md` §10.1.4):**
  - **I3 rank 증강: 부호 일치 53/53 = 1.000, p ≈ 2.2e-16 → 기준 충족.**
  - **I4 rank 감축: 부호 일치 113/124 = 0.911, p ≈ 1.3e-15 → 기준 충족.**
  - I1 중복 병합: Δτ_act p50 = 0.000 (61 site 에서 병합 발생). 중복 열은 열공간을 넓히지
    않으므로 정사영 불변 — **감사 통과 신호이며 발견이 아니다.**
  - I2 prior 제거(= E2 축소): Δτ_act p10/p50 = −0.324 / −0.038, 평가 57 site.
    **`S-EVAL` 124 site 중 49 site 는 prior 열 제거 시 열이 전부 사라진다**(18 site 는 애초에
    prior 열 없음). BLOCKER-E 를 평가 가능 계층에 한정해 재확인.
  - I3 에서 71 site 가 "단계 부족"으로 제외 — `rank = T` 라 증강 여지가 없다. §10.1.1 의
    `τ_col` 포화와 같은 사실의 다른 표현이다.
- **논문에서의 용도:** results (진단 민감도), limitation (E2 축소 범위, prior 지배)
- **해석 한계:** **허용 주장은 diagnostic sensitivity proof 뿐이다**(§8.2). 합성 rank 열은
  어떤 kinase 도 나타내지 않으므로 τ 가 rank 를 따라 움직인다는 것이 귀속이 옳아졌다는 뜻이
  아니다. E2 는 prior-free 한 축만 보므로 dictionary 조작 일반에 대한 민감도가 아니다.
  E3b 는 §6.6 에서 탐색적으로 지정되어 C1 채택 여부를 바꾸지 않는다.
  **금지:** individual kinase accuracy proof, "prior 열을 빼면 귀속이 좋아진다",
  "E2 통과".
- **결정성:** `RANK_STEPS = 3`, 합성 열 seed 20260820, 활성집합 하한 `> 0.0`(별도 tolerance
  도입 금지), dtype float64, NNLS = `scipy.optimize.nnls`.
  산출물 `data/outputs/_diagnostics/c1_e1_v1/e2_e3b.json`.

### [2026-08-22] C1 회귀 테스트 35건 — 사전등록 임계의 기계적 집행

- **분류:** 구현
- **대상:** `workers/tests/test_c1_transmissibility.py` (신규)
- **구현 대상 설계:** `.cursor/rules/research-code-provenance.mdc` §2 ("측정 후 변경 금지")
- **사전등록 상태:** 해당 없음 (검증 수단)
- **내용:** τ 수식(열공간 내 방향 → 1, 직교 → 0, `τ_col >= τ_act`), §4.3 경계 규약 3종의
  구별된 라벨, clip 금지, §4.2 승격 임계, 개입 I1–I4 의 성질, E1b 통계(상수 예측기 →
  `D_inv` = 0.5, p-value 필드 부재), E3 저빈도 규칙(대체 분할 없이 미평가로 종결),
  §5.1 필드 존재, §5.2 평균 비-primary 표기를 잠근다.
  **사전등록 상수 11개를 문서 값과 대조하는 테스트를 포함**해, 문서를 고치지 않고 코드만
  바꾸면 실패하게 만들었다. fold 배정은 프로세스 재시작 불변성을 상수로 고정했다.
- **논문에서의 용도:** methods (재현 가능성 근거), 사용 안 함 (결과 주장 없음)
- **해석 한계:** 수치 정확성만 검사한다. **테스트 통과가 τ 의 타당성을 뜻하지 않는다.**
- **결정성:** 35건 통과. 전 스위트 198 passed, 1 skipped (`ptm-worker-preprocessing`,
  `PYTHONPATH=/app:/opt`). 사전 존재하던 수집 오류 2건(`test_cross_species_iptmnet.py`
  입력 파일 부재, `test_dual_track_ptm_quantification.py` 의 `workers` 패키지 경로)은
  이 변경과 무관하며 그대로 남아 있다.

### [2026-08-22] §8.2 동결 대상 확정 — 판정 임계와 probe 설정의 분리

- **분류:** 사전등록
- **대상:** `docs/integrated_research_design_v2.md` §8.2.1, §8.2.2 (신규 절)
- **구현 대상 설계:** 같은 문서 §8.2 (2026-08-20 선언, 순위 0 작업)
- **사전등록 상태:** **결과 열람 전 확정.** 두 묶음 모두 **새 값을 도입하지 않는다** —
  판정 임계 4개는 §8.2 에서 2026-08-20, probe 설정 4개는 `c2_prereg_v1.md` §1.1 에서
  2026-08-21 이미 선언되어 있었다. §8.2.1 은 **선언 위치를 한 곳으로 모으는 것**이다.
- **내용:** 동결 대상을 두 묶음으로 나눠 확정.
  `GATE_JUDGEMENT_THRESHOLDS`(판정 부등식에 직접 들어가는 값: `time_validity_margin` 0.01,
  `missingness_r2_max` 0.25, `raw_concordance_min` 0.50, `missingness_pattern_ari_min` 0.20)와
  `GATE_PROBE_PARAMETERS`(판정 대상 수치를 만드는 값: `artificial_mask_fraction` 0.15,
  `cluster_distance_threshold` 0.30, `minimum_cluster_size` 2, `seed` 0).
  **두 번째 묶음을 함께 동결한 이유가 이 항목의 핵심이다** — `artificial_mask_fraction` 을
  0.15 → 0.05 로 낮추면 판정 부등식은 한 글자도 안 바뀌었는데 induced 표적의 분산이 줄어
  gate 통과가 쉬워진다. 판정 부등식만 잠그는 것은 반쪽 조치였다.
  §8.2.2 에서 이탈 시의 처리를 초안의 "표시"에서 **production 강제 차단**으로 강화했다
  (`GATE_THRESHOLD_CONFORMANCE_V1`). 표시를 읽지 않으면 그만이므로 §8.2 의 목적
  ("성공 기준을 조정해서 성공하는 것을 구조적으로 막는 것")이 달성되지 않는다.
  **강화 방향도 차단한다** — 강화된 임계로 통과한 결과를 선언 임계의 결과로 보고하는 것도
  사전등록 이탈이기 때문이다. 방향은 기록하되 판정은 이탈 여부만 본다.
- **논문에서의 용도:** methods (사전등록 집행 기제), supplement (임계 집합 digest)
- **해석 한계:** 이 절은 **임계를 지키게 만드는 장치**이며 임계값의 타당성과 무관하다.
  gate 통과가 표현의 타당성을 증명하지 않고, 실패가 무용을 증명하지 않는다.
  **금지:** "임계가 동결되었으므로 gate 판정이 옳다".
- **결정성:** 해당 없음 (설계 선언).

### [2026-08-22] gate 임계 단일 선언 + 이탈 시 production 강제 차단 (§8.2 순위 0 완료)

- **분류:** 구현
- **대상:** `ptm_shared/representation/layers.py`, `ptm_shared/representation/benchmark.py`,
  `ptm_shared/representation/__init__.py`, `workers/tests/test_ptm_representation_learning.py`
- **구현 대상 설계:** `docs/integrated_research_design_v2.md` §8.2 · §8.2.1 · §8.2.2
- **사전등록 상태:** **결과 열람 전 확정.** 동결 값은 이미 선언된 값의 이전(移轉)이며 새 판정
  기준이 아니다. `DEFAULT_BENCHMARK_CONFIG` 의 기존 리터럴과 **비트 단위로 동일**함을 테스트가
  대조하므로, 이 변경으로 기존에 보고된 gate 판정 수치는 하나도 바뀌지 않는다.
- **내용:**
  1. 임계·probe 설정 8개를 `benchmark.py` 리터럴에서 `layers.py` 로 이전하고 `MappingProxyType`
     으로 불변화. `DEFAULT_BENCHMARK_CONFIG` 는 이제 `**dict(FROZEN_GATE_SETTINGS)` 로 **참조**한다.
     리터럴 사본이 두 곳에 있으면 조용히 벌어지는 것이 정상 경로이기 때문이다.
  2. `gate_settings_digest()` — 선언 집합의 sha256
     `0e3eda884ef0a888d40e8429d6bb4375dce1250223e13bbb834153616bb4a0e0`.
     판정 출력과 `describe_contract()` 에 기록해 supplement 수치의 임계 출처를 사후 확인 가능하게 했다.
  3. `gate_settings_conformance(effective)` — 실사용값과 선언값을 대조. 이탈 시
     항목·선언값·사용값·방향(relaxed / tightened)·묶음을 기록한다.
  4. `evaluate_adoption_gates` 출력 분리: `all_gates_passed`(6개 부등식의 논리곱)와
     `production_influence_allowed`(= `all_gates_passed` ∧ `conformant`)를 **다른 필드로** 남겼다.
     이탈 실행은 `threshold_override_is_exploratory=True` 로 표시되고 6/6 이어도 production 이
     열리지 않는다. 수치는 그대로 산출되므로 민감도 분석은 계속 가능하다.
  5. **`seed` 만 등호가 아니라 집합 소속으로 검사한다.** `c2_prereg_v1.md` §1.3 이 gate 판정을
     5 seed 의 중앙값과 「5 중 4 통과」로 정의했으므로 seed 1 실행은 사전등록 프로토콜의 한
     반복이며 이탈이 아니다. 등호로 검사했다면 **이미 실행한 C2 다중 seed 측정 전부가 "이탈"로
     오표시**되었을 것이다. 집합 밖 seed 는 이탈로 본다 — seed 탐색 경로를 막는다.
  6. 테스트 11건 추가: 임계 4개·probe 4개·seed 집합의 값 고정, digest 고정,
     `DEFAULT_BENCHMARK_CONFIG` 재선언 금지, 기본 실행의 conformant 확인,
     완화·강화·probe 이탈·집합 밖 seed 4 경로의 production 차단, 사전등록 seed 5개의 비-이탈,
     `describe_contract()` 노출, 불변성.
- **논문에서의 용도:** methods (사전등록 집행), supplement (임계 digest)
- **해석 한계:** 이 장치는 **선언 임계를 썼는지**만 보증한다. 임계가 적절한지, gate 가 측정하려는
  성질을 실제로 측정하는지는 별개다. C2 의 E6 결과가 후자의 반례다 — gate 의 선형 프로브는
  통과하면서 kNN 회수는 남았다(`c2_prereg_v1.md` §8.1).
  **금지:** "임계가 테스트로 고정되었으므로 gate 는 신뢰할 수 있다".
- **결정성:** digest 는 `json.dumps(sort_keys=True, separators=(",",":"))` 의 sha256 으로
  플랫폼 무관. 부동소수 비교 tolerance `1e-12`.
  테스트 전 스위트 211 passed, 1 skipped (`ptm-worker-preprocessing`, `PYTHONPATH=/app:/opt`).
  기존 수집 오류 2건은 이 변경과 무관하게 그대로다.

### [2026-08-22] 정본 환경에 pytest 포함 — 고정 수치가 처음으로 자동 검증된다

- **분류:** 구현
- **대상:** `workers/Dockerfile`, `docs/chapter2_audit_protocol_v1.md` §6.1 · §8,
  `docs/tmm_identifiability_diagnosis.md`
- **구현 대상 설계:** `docs/chapter2_audit_protocol_v1.md` §8 미해결 항목 (2026-08-21 기록)
- **사전등록 상태:** 해당 없음 (검증 환경 정비, 측정되는 양을 바꾸지 않음)
- **내용:** `ARG INSTALL_DEV_DEPS=true`(기본값)를 추가해 `optional-dependencies.dev`
  (`pytest`, `pytest-asyncio`)를 런타임 의존성과 함께 설치한다.
  **왜 이것이 인프라가 아니라 연구 사안인가:** 감사·C1·C2 의 고정 수치는 scipy 경로
  (`scipy.optimize.nnls`)에서 산출되었다. 호스트에는 pytest 가 있으나 scipy 가 없어
  projected-gradient fallback 으로 떨어지고, 이미지에는 scipy 가 있으나 pytest 가 없었다.
  **두 조건을 동시에 만족하는 환경이 존재하지 않았다** — 즉 "고정했다"는 진술을 확인할 수 있는
  장소가 없었다. 검증 불가한 고정은 고정이 아니다.
  api-server·mcp-server 는 그대로 두었다. 연구 회귀 스위트가 worker 이미지에서만 돌고
  `ptm_shared` 가 두 이미지에 동일 마운트되므로 검증 환경을 늘릴 이유가 없다.
- **논문에서의 용도:** methods (재현 절차), supplement (환경 명세)
- **해석 한계:** **테스트가 도는 것과 수치가 옳은 것은 다르다.** 이 변경은 회귀 방어를
  자동화할 뿐 어떤 수치의 타당성도 뒷받침하지 않는다.
  **금지:** "테스트가 자동으로 도므로 결과가 검증되었다".
- **결정성:** 재빌드 후 새 컨테이너에서 `python -m pytest tests/ -q` →
  **211 passed, 1 skipped, 임시 설치 없음.** scipy 1.17.1, numpy 2.4.6, pytest 9.1.1,
  Python 3.11. 기존 수집 오류 2건(`test_cross_species_iptmnet.py` 입력 파일 부재,
  `test_dual_track_ptm_quantification.py` 의 `workers` 패키지 경로)은 이 변경과 무관하게 그대로다.

---

### [2026-08-22] C3 사전등록 초안 + E 번호 충돌 정정

- **분류:** 사전등록, 정정
- **대상:** `docs/c3_prereg_v1.md` (신규), `docs/integrated_research_design_v2.md` §7.4·§7.5
- **구현 대상 설계:** `docs/integrated_research_design_v2.md` §7 (C3),
  `docs/ptm_representation_learning_contract_v1.md` §12.3 (A3 의 재배치)
- **사전등록 상태:** 결과 열람 전 확정 (제약 미구현. 제약 적용 후의 값을 산출하지 않았다)
- **내용:** C3 의 주장 범위, `O` 정의, 모집단, false-merge 정의, 자명한 성공 차단 지표,
  제약 기제 후보(M1/M2/M3), 불확실성 설계를 문서화했다. **§12(동결 전 실측)를 §6(구현)보다
  앞에 배치한 것이 이 문서의 구조적 결정이다** — C1 에서 검정력 미달을 τ 계산 전에 발견해
  "평가 불가"로 남길 수 있었던 것이 그 근거다.
  같은 작업에서 C3 실험 번호를 E8–E11 → **E9–E12** 로 정정했다. `c2_prereg_v1.md` 가 E8 을
  하이퍼파라미터 통제 실험에 이미 쓰고 있어 충돌했다.
- **논문에서의 용도:** methods (C3 판정 규칙), limitation (§11 해석 한계)
- **해석 한계:** 이 문서는 **`O_ij = 0` 이 비유사성의 증거라고 말하지 않는다.** 증거 부재다.
  따라서 제약의 목표는 비교 불가 쌍을 멀리 두는 것이 아니라 그 쌍에 대해 유사성을 주장하지
  않는 것이며, 그 구별이 M1 을 primary 로, M2 를 대안으로 만든 이유다.
  **금지:** "제약이 kinase 예측을 개선한다", "제약이 표현 품질을 높인다".
- **결정성:** 해당 없음 (문서)

---

### [2026-08-22] C3 §12 동결 전 실측 4건 — 초안 G1 이 기각되었다

- **분류:** 측정
- **대상:** `scripts/measure_c3_prefreeze.py` (신규), `docs/c3_prereg_v1.md` §12.6
- **구현 대상 설계:** `docs/c3_prereg_v1.md` §12.1–§12.4
- **사전등록 상태:** 결과 열람 전 확정 — **무제약 기저만 측정한다.** 제약 적용 후의 값을 보지
  않았으므로 이 값에 근거해 §13 에서 임계를 정하는 것은 사후 선택이 아니다(§12.5 의 논거).
  결합률 하한 0.95 는 §12.1 실측 착수 전 §3.1 에 선언되었다.
- **내용:** 네 건을 측정했다.
  **§12.1** 원 `report.pr_matrix.tsv` 의 run 컬럼을 시점별로 묶어 `Modified.Sequence` 키로
  올린 뒤 표현 입력의 form 키와 결합. **결합률 1.0000 (2,744/2,744, 탈락 0)** → §3.1 경로 (a)
  확정. 판정 계층 `rep≥2` 를 구성했다(run 수준 replicate ≥ 2 **AND** 표현 입력 `observed`).
  전구체 여러 행은 최대값으로 올렸다 — 합을 쓰면 전하 상태 수가 replicate 수로 새어든다.
  **§12.3** 비교 불가 그래프의 Kish `n_eff` 를 계층 2 × `T_min` 3 에서 재측정.
  `rep≥2`·`T_min=4` 에서 **995.2** (§7.3 의 432 는 Core A/B 트랙 값이며 인용 금지).
  `integrated_research_design_v2.md` §7.2 의 집중 구조가 재현되었다 —
  상관 −0.758 (§7.2: −0.764), 상위 5% 평균 관측 3.52 대 5.88 (§7.2: 4.12 대 5.96).
  **§12.2** 무제약 arm A·B·D·E 의 기저 FM. arm D 에서 **FM_precision 0.1042,
  false merge 65,331 건** → §9 반증 조건 5 발동하지 않음. 개선 대상이 실재한다.
  **§12.4** 제약 없이 인코더 seed 만 바꾼 두 적합 사이의 안정성.
  비교 가능 쌍 ARI **0.0237–0.0373**, 쌍거리 순위 일치도 **0.0025–0.0056**,
  열공간 정렬 **0.178–0.195**.
- **논문에서의 용도:** methods (§13 임계의 근거), results (기저 표), limitation (기하 비식별성)
- **해석 한계:** **§12.4 가 초안의 G1 을 기각시켰다.** 군집 ARI 절대 임계도, 그 대안으로
  검토했던 거리순위 일치도도 쓸 수 없다 — 후자는 무제약 표현에서도 사실상 0 이다.
  행 표준화 인공물이 아님을 `standardize=False` 대조로 확인했다(0.0023–0.0054).
  열공간 정렬 0.18–0.20 은 **부분공간은 부분적으로 재현되고 미세 기하는 재현되지 않는다**는
  뜻이며, "arm D 가 무작위와 같다"가 아니다(무작위 기대값 ≈ 0.006).
  arm 간 FM 비교는 하지 않는다 — FM 은 군집 조밀도의 함수이므로 학습 arm(군집 15·9)이
  비학습 arm(군집 97·71)보다 높게 나오는 것은 §4.1 이 예고한 인공물이다.
  **금지:** "arm B 의 FM 이 낮으므로 B 가 우수하다", "표현 학습이 비교가능성을 악화시킨다".
- **결정성:** `ptm-worker-preprocessing`, scipy 1.17.1, numpy 2.4.6, Python 3.11.
  인코더 seed {0,1,2}, `latent_dim` 16, `hidden_dim` 64, `epochs` 150,
  `n_perturbations` 5(잡음 하한 측정 시), 군집 average linkage · cosine · threshold 0.30 ·
  `minimum_cluster_size` 2. `O` 구성은 정수 비교이며 tolerance 없음. 쌍 열거 상삼각(i<j).

---

### [2026-08-22] C3 지표를 공유 모듈로 이관 + 회귀 20건

- **분류:** 구현
- **대상:** `ptm_shared/representation/comparability.py` (신규),
  `workers/tests/test_comparability.py` (신규), `scripts/measure_c3_prefreeze.py`,
  `ptm_shared/representation/__init__.py`
- **구현 대상 설계:** `docs/c3_prereg_v1.md` §1.2 계산 경로, §4.1, §5.2
- **사전등록 상태:** 결과 열람 전 확정 (정의만 이관. 측정값은 §12.6 과 동일함을 확인)
- **내용:** 스크립트에만 있던 정의를 모듈로 옮겼다. **임계는 옮기지 않았다** — 임계를 모듈에
  두면 문서를 고치지 않고 코드만 바꿀 수 있다. 회귀 20건이 잠그는 것은 사전등록 규약이다:
  `label 0` 미배정 규약(§3.3), 미정의를 `None` 으로 남기는 규약(§4.2), `O` 의 비추이성(§2.1),
  `pair_restricted_ari` 가 mask 밖의 불일치를 세지 않는 것(§5.2), `subspace_alignment` 의
  회전 불변성. 이관 후 `measure_c3_prefreeze.py` 를 재실행해 §12.6 의 모든 값이 동일함을
  확인했다.
- **논문에서의 용도:** methods (지표 정의), supplement (회귀 스위트)
- **해석 한계:** 테스트 통과는 정의가 문서와 일치함을 뜻하며 **지표의 타당성을 뜻하지 않는다.**
  실제로 이 모듈의 `distance_rank_agreement` 는 §12.4 에서 guard 로 기각되었고 진단 용도로만
  남아 있다 — 즉 잠긴 정의 중에 판정에 쓰지 않는 것이 있다.
- **결정성:** 정본 환경 `python -m pytest tests/ -q` → **233 passed, 1 skipped**
  (이관 전 211 + comparability 20 + 공정 프로브 2). 기존 수집 오류 2건은 무관하게 그대로다.

---

### [2026-08-22] 공정 프로브 seed 집합 파생 규칙 명시화

- **분류:** 정정
- **대상:** `ptm_shared/representation/fair_probe.py`,
  `workers/tests/test_representation_fair_probe.py`
- **구현 대상 설계:** `docs/ptm_representation_learning_contract_v1.md` §R1.6
- **사전등록 상태:** 해당 없음 — **정본 경로의 수치가 바뀌지 않는다.**
  `encoder_config["seed"] = 0`, `config["seed"] = 0` 인 기존 실행에서 구·신 규칙이 같은
  집합 {0,1,2,3,4} 를 낸다. 두 값이 다를 때만 달라진다.
- **내용:** `encoder_seed > 0` 의 seed 를 `config["seed"] + k` 대신
  `encoder_config["seed"] + k` 에서 파생시킨다. 구 규칙에서는 `k = 0` 이 호출자의 인코더
  seed 를 쓰고 `k > 0` 이 프로브 seed 를 써서, 두 값이 다르면 **seed 집합이 두 계열의
  혼합**이 되어 methods 절에 진술할 수 없었다. 산출 레코드에 `encoder_seed_set` 을 추가했다.
- **논문에서의 용도:** methods (프로브 seed 집합 명세)
- **해석 한계:** **seed 를 평균하는 것은 기하 불안정을 해결하지 않고 우회한다.**
  `compare_to_baseline` 이 (시점, 분할)별로 학습 arm 의 seed 를 평균하므로 프로브의 짝지은
  관측 수가 부풀지 않고, 프로브가 열공간에만 의존하므로(회전 불변) `c3_prereg_v1.md` §12.6.1
  의 기하 비식별성과 양립한다. 그러나 인코더가 seed 에 대해 식별된다는 뜻은 아니다.
  **금지:** "seed 평균으로 표현이 안정화되었다".
- **결정성:** 회귀 2건 추가 — seed 집합이 인코더 seed 에서 연속임을 고정하고,
  학습 arm 의 fold 가 비학습 arm 의 seed 배수임에도 짝지은 관측이 1배임을 고정한다.

---

### [2026-08-22] C3 §13 미결 5건 확정 및 문서 동결

- **분류:** 사전등록
- **대상:** `docs/c3_prereg_v1.md` §5.2·§5.3·§6.2·§7.4·§9·§11.1·§13·§14,
  `docs/c2_prereg_v1.md` §13.2·§13.3
- **구현 대상 설계:** `docs/c3_prereg_v1.md` §12.6 실측
- **사전등록 상태:** 결과 열람 전 확정 — 임계는 전부 **무제약 기저 대비 상대값**이며 제약
  적용 후의 값은 산출되지 않았다. §12.5 가 이 순서의 정당성을 미리 선언했다.
- **내용:** 다섯 건을 확정했다.
  **적용점** M1-loss, **3-기준선 설계**(대조 손실 없음 / 무제약 대조 / 제약 대조).
  primary 대조를 무제약 대조 손실로 둔 것이 핵심이다 — 기준선 0 과 비교하면 "대조 항 추가
  효과"와 "비교 불가 쌍 제외 효과"가 섞이고 C3 이 주장하는 것은 후자뿐이다. 적합 비용 3배를
  받아들였다.
  **G1** 초안(군집 ARI 절대 임계) 기각 → **G1a ≥ 0.0237**(§12.4 잡음 하한 대비) +
  **G1b ≥ 0.0237**(제약 표현의 seed 간 ARI 비퇴행) 추가.
  **G2** 병합 쌍 비율 → **제거 표적성 ≥ 0.50**. 무작위 제거의 기대값이 기저 FM_precision
  (0.1042)이므로 0.50 은 그 4.8 배이며, 비율 하한과 달리 임의값이 아니다.
  **replicate 계층** 경로 (a). **C3 유지** 여부는 유지로 확정.
  §9 반증 조건 5·6 이 발동하지 않음을 기록하고, §11.1 에 새 해석 한계를 추가했다.
- **논문에서의 용도:** methods (판정 규칙), limitation (§11 · §11.1)
- **해석 한계:** **G1a 가 약한 기준임을 숨기지 않고 §5.2 에 적었다.** 같은 seed 의 제약 대
  무제약은 초기화를 공유하므로 제약이 아무 일도 하지 않아도 seed 간 값보다 높게 나온다.
  그럼에도 절대 임계를 쓸 수 없다 — 무제약 표현 자체가 ARI 0.02–0.04 에서만 재현되므로
  예컨대 0.50 은 무제약 기준선도 통과하지 못한다. G1b 가 이 약함을 **부분적으로만** 메운다.
  **§11.1 이 기록하는 새 사실:** 표현 입력의 `observed` 가 run 수준 `rep≥1` 과 0.012% 만
  다르므로 **기존 C0·C2 수치는 전부 `rep≥1` 계층에서 계산되어 있다.** §7.3 의 `rep≥1` 금지는
  pair 수준 false-merge 검정에 대한 것이어서 site 수준 예측 지표를 무효화하지 않지만,
  논문에서 그 계층을 명시해야 한다. 지금까지 어디에도 적혀 있지 않았다.
  **금지:** "G1a 통과가 구조 보존을 입증한다".
- **결정성:** 해당 없음 (문서). 인용한 실측값의 결정성은 §12.6 항목에 있다.

---

### [2026-08-22] C2 retention ARI 하위 조건의 타당성 기록

- **분류:** 측정, 설계
- **대상:** `docs/c2_prereg_v1.md` §13.2 (5) · §13.3
- **구현 대상 설계:** `docs/c3_prereg_v1.md` §12.6.1 의 파생 발견
- **사전등록 상태:** 결과 열람 후 (탐색적) — **C2 판정 후에 발견되었다.**
  primary 승격 영구 금지. 이 발견으로 C2 의 판정을 바꾸지 않는다.
- **내용:** 같은 축에서 두 값을 나란히 측정했다. arm D 에서 마스킹 전후 ARI = 0.0350
  (§1.1 공표값 재현)인데 **인코더 seed 만 바꾼 ARI 는 0.0427–0.0675 다.**
  즉 데이터의 15% 를 가리는 것이 인코더 seed 를 바꾸는 것보다 군집을 덜 흔든다. 따라서
  `missingness_pattern_ari_min = 0.20` 은 arm D 에서 **adversary 와 무관하게** 달성 불가능하며
  (무제약 arm 의 재현성 상한보다 3–5배 높다), 그 조건이 재는 것은 마스킹 강건성이 아니라
  군집의 seed 불안정이다.
  자기 대조 ARI = 1.0 으로 계산 경로의 건전성을 확인했다.
- **논문에서의 용도:** limitation (Chapter 3 지표 타당성 절)
- **해석 한계:** **임계를 바꾸지 않는다.** `missingness_pattern_ari_min` 은
  `integrated_research_design_v2.md` §8.2 에서 동결되었고 결과를 본 뒤 완화하면 사전등록이
  무의미해진다. 이 항목은 임계 변경 근거가 아니라 **그 조건이 arm D 에서 무엇을 재는지에 대한
  기술**이다. 임계 0.20 자체가 틀렸다고 말하지 않는다 — 문제는 그 요구가 겨냥한 성질
  (마스킹 강건성)을 이 arm 에서 **측정할 수 없다**는 것이다.
  **C2 의 판정은 바뀌지 않는다** — §13.2 의 2(국소 성분 잔존, kNN 회수 0.513)가 독립적으로
  인증서를 부정하므로, ARI 조건이 타당했더라도 C2 는 통과하지 못했다.
  **금지:** "지표가 잘못되었으므로 C2 는 실제로 성공했다".
- **결정성:** `scripts/measure_c3_prefreeze.py`. 인코더 seed {0,1,2},
  마스킹 `artificial_mask_fraction` 0.15 · induced mask `seed` 0
  (`layers.GATE_PROBE_PARAMETERS` 인용), 마스킹 arm 은 `n_perturbations = 0`.
  군집 정의(average linkage · cosine · threshold 0.30 · `minimum_cluster_size` 2)는
  세 비교에서 동일.

### [2026-08-22] C3 대조 손실 함수형 선언 — §6.2 의 공백을 구현 전에 메웠다

- **분류:** 사전등록
- **대상:** `docs/c3_prereg_v1.md` §6.3, §6.3.1, §6.3.2 (신규)
- **구현 대상 설계:** `c3_prereg_v1.md` §6.2 (M1-loss, 3-기준선). **§6.2 는 기제 족만 정하고
  함수형을 정하지 않았다** — 그 공백을 여기서 메운다. 문서를 먼저 고치고 코드를 썼다
  (`.cursor/rules/research-code-provenance.mdc` §2 의 순서).
- **사전등록 상태:** 결과 열람 전 확정. E9 미실행 시점.
- **내용:** InfoNCE + 코사인 유사도로 함수형 확정. 양성은 **관측 데이터의 거리**(공유 관측
  시점의 RMS)로 정하고 임베딩으로 정하지 않는다 — 임베딩으로 정하면 손실이 자기 자신을
  강화하는 되먹임이 된다. 제약은 항을 더하지 않고 양성·후보에서 `O_ij = 0` 을 **뺀다**.
  초모수 T = 0.5, k = 10 (`c2_prereg_v1.md` §1.1 의 `neighbors` 인용), λ = 1.0 primary,
  민감도 {0.3, 3.0}. 자명성 검사 S1(대조 항이 임베딩을 바꿨는가) · S2(제약이 손실을
  비웠는가, 임계 0.20) 를 판정 전 확인 항목으로 선언.
- **논문에서의 용도:** methods (C3 손실 정의), limitation (λ 가 판정 대상이 아님을 명시)
- **해석 한계:** `d_obs` 에 행 표준화를 적용하지 않는다 — 표준화 통계량이 관측 마스크에
  의존하므로 표준화하면 거리 자체가 coverage 의 함수가 되고 C2 가 겨냥한 문제를 대조 항에
  다시 들여온다. 이 선언은 함수형의 **타당성**을 보장하지 않는다.
- **결정성:** 해당 없음 (선언 항목)

### [2026-08-22] C3 제약 구현 + 기울기 유한차분 검증

- **분류:** 구현
- **대상:** `ptm_shared/representation/comparability_constraint.py` (신규),
  `ptm_shared/representation/replicate_stratum.py` (신규),
  `ptm_shared/representation/encoder.py`, `ptm_shared/representation/__init__.py`,
  `scripts/measure_c3_prefreeze.py`, `workers/tests/test_comparability_constraint.py` (신규)
- **구현 대상 설계:** `c3_prereg_v1.md` §6.1 (M1 마스킹형), §6.2, §6.3
- **사전등록 상태:** 결과 열람 전 확정. E9 미실행 시점.
- **내용:** `ComparabilityContrastive` 가 `O` 를 존중하는 InfoNCE 항의 손실과 `∂L/∂z` 를
  준다. 인코더 배선은 adversary 와 같은 지점(`grad_latent`)이며 **부호가 반대**다 — 제약은
  최소화하므로 더하고, adversary 는 기울기 반전이므로 뺀다. 기본값 꺼짐이라 기존 arm·gate
  수치는 전부 보존된다. `rep≥2` 계층 복원을 `measure_c3_prefreeze.py` 사본에서 모듈로
  이관했다(사본이 두 곳이면 한쪽만 고쳐도 아무 테스트가 실패하지 않는다). 이관 후 §12.1·§12.3
  실측값 전부 동일 재현 확인(결합률 1.0000, `rep≥2`·`T_min=4` n_eff 995.239681347666).
  회귀 26건 추가. 그중 결정적인 것 둘: **해석적 기울기 대 유한차분 오차 < 1e-7 (두 모드
  모두)**, **λ = 0 이 항 없는 적합과 비트 단위 동일**(§6.2 기준선 0 대조의 전제).
  전체 스위트 259 통과.
- **논문에서의 용도:** methods (C3 손실·기울기), supplement (기울기 검증)
- **해석 한계:** 기울기가 맞다는 것은 **선언한 목적함수를 최적화한다**는 뜻이며 그
  목적함수가 옳다는 뜻이 아니다. 테스트 통과는 방법의 성공을 뜻하지 않는다.
- **결정성:** float64. 쌍 열거는 전체 행렬, 대각 제외. `d_obs` 는 공유 관측 시점만 사용하고
  공유가 없으면 `+inf`(양성 불가). 양성 선택은 `argpartition` 후 안정 정렬로 동순위를 인덱스
  순으로 깬다. 마스크는 `config` 에 값으로 넣지 않고 SHA256 으로 기록한다 — `default=str` 로
  직렬화하면 잘려서 서로 다른 마스크가 같은 해시를 갖는다.

### [2026-08-22] E9 실행 — §5.3 다섯 조건 통과, 그러나 λ 민감도에서 결론이 뒤집힌다

- **분류:** 측정
- **대상:** `scripts/run_c3_e9.py` (신규), `docs/results/c3_e9/*.json`,
  `docs/c3_prereg_v1.md` §11 (해석 한계 2건 추가), §15 (결과)
- **구현 대상 설계:** `c3_prereg_v1.md` §8 (E9), §5.3 (판정 결합), §6.3.2 (자명성 검사),
  §7.1 (`C3_BOOTSTRAP_V1`)
- **사전등록 상태:** 결과 열람 전 확정된 규칙으로 판정. 임계 5개(G1a·G1b 0.0237, G2 0.50,
  G3 0.01355, S2 0.20)는 모두 이 실행 전에 선언되어 있었고 스크립트는 모듈에서 인용만 한다.
- **내용:** 3-기준선 × seed 2. 자명성 검사가 판정 전에 둘 다 통과(S1 ARI 0.3988 로 seed 잡음
  범위 밖, S2 빈 양성 행 0.0999 < 0.20). primary(λ = 1.0)에서 FM_precision
  0.14436 → 0.11548, feature 단위 짝지은 부트스트랩 2000 반복 95% CI [−0.0386, −0.0198].
  G1a 0.4713 / G1b 0.0702 / G2 `no_shrinkage` / G3 ΔR² 0.019014 (p = 0.0001, 24 fold).
  **§5.3 다섯 조건 논리곱 통과.** G2 가 `no_shrinkage` 인 것은 처리가 병합 쌍을 1,341,916 →
  1,485,234 로 **늘리면서** false merge 를 193,716 → 171,508 로 줄였기 때문이며, §5.2 가 이
  경우를 미리 통과로 규정했으므로 사후 선택이 아니다. 자명한 성공 경로(§5.1) 미발동.
  **그러나 §6.3.1 이 선언한 민감도에서 결론이 뒤집힌다** — λ = 0.3 은 악화(CI 전부 양수),
  λ = 3.0 은 CI 가 0 을 포함. 효과가 λ 에 단조가 아니며 개선은 한 점에서만 관측된다.
- **논문에서의 용도:** results (E9 primary), **limitation (λ 의존성, 기준선 0 대비 비개선)**
- **해석 한계:** 판정의 형식적 지위는 유지된다 — §6.3.1 이 "λ 는 판정 대상이 아니다"를 미리
  선언했고 primary 는 λ = 1.0 하나로 고정되어 있었으므로 임계를 사후에 고른 것이 아니다.
  **그러나 일반성 주장을 철회한다** (§9 반증 조건 4 가 T_min 에 대해 규정한 논거를 λ 에 적용).
  더 중요한 한계: 병기한 기준선 0(대조 항 없음 = 현행 arm D)의 FM_precision 이 **0.10421 로
  가장 낮다.** 대조 항 자체가 악화를 만들고 제약은 그 악화의 약 70% 만 회복한다. 따라서
  **"C3 가 현행 표현을 개선한다"는 주장은 성립하지 않는다.** 성립하는 주장은 "대조 손실을
  쓰는 표현 학습에서 비교가능성을 존중하면 근거 없는 병합이 줄어든다"이며 λ 조건이 붙는다.
  단일 코호트(HIRc-B, form 단위, T = 6). E10·E11·E12 미실행이므로 반증 조건 3·4 미평가.
- **결정성:** numpy 2.4.6, Python 3.11, float64. 계층 `rep≥2`(결합률 1.0000), `T_min = 4`,
  arm D, epochs 150, 인코더 seed {0, 1}. 부트스트랩 2000 반복, seed 20260822, feature 단위
  복원 추출, percentile 95%, 방향 단측 사전 고정. 공정 프로브는 `--skip-probe` 없이 1회
  (507s, 24 fold). 산출 레코드 `docs/results/c3_e9/`.

### [2026-08-22] E11 의 C2 arm λ 선언 — 착수 전, 측정 대상으로 정당화

- **분류:** 사전등록
- **대상:** `docs/c3_prereg_v1.md` §13.2 (신규), §13.1 미결 해소
- **구현 대상 설계:** `c3_prereg_v1.md` §13.1 이 "E11 착수 전에 `c2_prereg_v1.md` §7 frontier
  에서 선택한다"로 남겨 둔 미결.
- **사전등록 상태:** 결과 열람 전 확정. E11 미실행 시점. 선택 규칙은 C2 의 **공표된**
  E4/E5 수치(`c2_prereg_v1.md` §6.1·§7.2.1)만 참조하며 C3·E11 의 어떤 값도 보지 않았다.
- **내용:** primary λ = 0.50, 민감도 λ = 5.00. 근거를 결과가 아니라 **측정 대상**으로 적었다 —
  E11 의 판정량이 군집 기반 false-merge 지표이므로 C2 arm 은 군집이 퇴화하지 않는 λ 여야
  한다. 격자에서 retention ARI 가 최대(0.067)인 점이 0.50 이고, λ ≥ 1 에서는 0 또는 음수로
  퇴화한다. λ = 5.00 은 coverage 축 최강점(induced R² 0.0419)이지만 retention ARI 가 −0.0064
  라 판정에 쓸 수 없어 민감도로만 병기한다.
- **논문에서의 용도:** methods (E11 설계), supplement (λ 선택 근거)
- **해석 한계:** C2 는 자신의 인증서를 통과하지 못했으므로(`c2_prereg_v1.md` §13.1) 여기서
  "C2 arm" 은 **성공한 방법이 아니라 사전등록된 격자 점**이다. 두 λ 의 결론이 다르면 독립성
  주장을 조건부로 내린다고 미리 적었다.
- **결정성:** adversary 최적반응, seed 1 (`c2_prereg_v1.md` §12 인용). 인코더 seed 0.

### [2026-08-22] E12 — 반증 조건 4 발동. G2 가 T_min 3·5 에서 미달

- **분류:** 측정
- **대상:** `scripts/run_c3_e9.py` (`--t-min` 추가), `docs/results/c3_e9/e12_tmin{3,5}_*.json`,
  `docs/c3_prereg_v1.md` §16.1
- **구현 대상 설계:** `c3_prereg_v1.md` §8 (E12), §2.1 (T_min primary = 4), §9 반증 조건 4
- **사전등록 상태:** 결과 열람 전 확정된 규칙으로 판정. `--t-min` 은 판정 경로를 바꾸지 않고
  primary 여부 표시만 추가한다 — `judgement_is_primary` 는 λ 와 T_min 이 **둘 다** 사전등록
  값일 때만 참이다.
- **내용:** T_min ∈ {3, 5} 에서도 FM_precision 은 개선되고 CI 가 0 을 제외한다(각각
  [−0.0147, −0.0027], [−0.0221, −0.0008]). **뒤집히는 것은 자명성 guard G2 다** — 제거
  표적성 0.1251 / 0.2660 으로 임계 0.50 미달. T_min = 4 에서는 처리가 병합 쌍을 늘리며
  개선했으나(`no_shrinkage`), 3·5 에서는 병합 쌍을 줄이며 개선한다(각각 −228,122, −356,588).
  즉 **개선의 기제가 T_min 에 따라 바뀌고**, 3·5 에서는 §5.1 이 사전에 금지한 자명한 성공
  경로가 상당 부분 기여한다. §9 반증 조건 4 발동.
- **논문에서의 용도:** results (E12), **limitation (정식화가 임계 의존적)**
- **해석 한계:** primary 지표의 **방향**은 세 T_min 에서 견딘다. 그러나 §5.3 판정은 T_min = 4
  에서만 통과하므로 일반성 주장은 철회된다. 이 결과는 "제약이 효과 없다"가 아니라 "개선의
  기제가 임계에 따라 바뀌며 한 값에서만 자명하지 않다"이다.
- **결정성:** E9 와 동일 (float64, `rep≥2`, arm D, epochs 150, seed {0,1}, 부트스트랩 2000
  반복 seed 20260822). G3 는 이 실행에서 생략(`--skip-probe`).

### [2026-08-22] E10·E11 — C2 와 C3 는 대립한다. 동결 규칙 밖의 분기

- **분류:** 측정
- **대상:** `scripts/run_c3_e10_e11.py` (신규),
  `docs/results/c3_e9/e11_c2lambda{0.5,5.0}_*.json`, `docs/c3_prereg_v1.md` §16.2–§16.4
- **구현 대상 설계:** `c3_prereg_v1.md` §8 (E10, E11 및 그 판정 규칙), §13.2
- **사전등록 상태:** 결과 열람 전 확정된 규칙으로 판정. **단 관측된 분기가 규칙에 없다** —
  그 사실을 판정으로 감추지 않고 `preregistered: false` 로 기록한다.
- **내용:** C2+C3 의 FM_precision 이 C2 단독보다 **유의하게 높다** — C2 λ = 0.50 에서
  0.20361 대 0.10898, CI [+0.0777, +0.1105]; λ = 5.00 에서 0.20888 대 0.20729,
  CI [+0.0003, +0.0034]. 두 λ 에서 방향이 같으므로 적대성은 C2 강도에 의존하지 않는다.
  §8 규칙은 "0 아래 → 독립 기여", "0 포함 → 흡수" 두 분기만 열거했고 관측된 "전부 0 위"는
  없다. **흡수로 적으면 규칙보다 관대하게 읽는 것이므로** 세 번째 분기 `antagonistic` 을
  명시했다(흡수 = C3 가 아무것도 더하지 않음, 관측 = C3 가 해를 끼침 — 다른 결론이다).
  병기 대조에서 **C3 단독은 현행 arm D 와 통계적 차이가 없다**(0.11548 대 0.10421,
  CI [−0.0029, +0.0242]). E10 기술 통계에서 C3 는 induced R² 를 0.462 → 0.598 로 **올린다** —
  `O` 가 관측 구조를 손실에 들여오므로 표현이 결측 패턴을 더 인코딩한다. 이것이 적대성의
  기제 설명 후보다. 한편 C3 는 retention ARI 를 0.035 → 0.126 으로 올려 C2 가 8 λ 전체에서
  넘지 못한 하위 조건에서 가장 높은 값을 냈다.
- **논문에서의 용도:** results (E10·E11), **limitation (C2·C3 대립)**,
  exploratory (retention ARI)
- **해석 한계:** retention ARI 0.126 은 **탐색적이며 primary 승격 영구 금지**다 — E10 은
  판정 실험이 아니고(§8) retention ARI 는 §12.6.1 때문에 판정에서 배제되어 있다. 임계 0.20
  에도 미달이다. "C3 가 C2 보다 우수하다"는 주장은 하지 않는다 — 두 기여의 판정량이 다르다.
  false merge 는 induced masking 을 고려하지 않은 하한이다(§3.2). 단일 코호트.
- **결정성:** 부트스트랩 정의를 `run_c3_e9.py` 와 동일하게 맞췄다(2000 반복, feature 단위
  복원 추출, seed 20260822) — 다르면 E9 와 E11 의 구간을 나란히 읽을 수 없다.

### [2026-08-22] C3 지위 확정 — 방법 장이 아니라 한계·특성화 장

- **분류:** 설계
- **대상:** `docs/c3_prereg_v1.md` §17, `docs/integrated_research_design_v2.md` §7.6, §8.1
- **구현 대상 설계:** `c3_prereg_v1.md` §9 반증 조건, §17 (신규)
- **사전등록 상태:** 결과 열람 후 판단. **판정 규칙을 바꾸지 않았다** — §5.3 은 그대로이며
  primary 가 통과했다는 사실도 §15 에 그대로 남는다. 바뀐 것은 **장의 지위**이고 그 판단은
  §9 반증 조건 4 의 발동과 E11 결과에 근거한다.
- **내용:** C3 를 방법 장에서 한계·특성화 장으로 내린다. 근거는 누적이다 — primary 통과 1건
  대 선언된 민감도 2축 전부 뒤집힘 + 현행 arm D 대비 차이 없음 + C2 와 결합 시 악화.
  방법 장이라면 "언제 쓰면 되는가"에 답해야 하는데 답이 "λ ≈ 1, T_min = 4, C2 없이, 대조
  손실을 이미 쓰고 있을 때"이며 처방이 아니다. Chapter 4 에 남는 것 6건을 §17.1 에 적었고
  그중 **4번(C2 와 C3 의 대립)이 가장 값이 있다** — 어느 한쪽만 했으면 나오지 않는 결과이며
  두 병목이 독립이 아니라 대립한다는 정량적 증거다.
- **논문에서의 용도:** limitation, results (§17.1 의 6건)
- **해석 한계:** "C3 가 실패했다"와 "C3 의 primary 가 통과했다"가 **둘 다 참**이다. 전자는
  장의 지위에 대한 판단이고 후자는 사전등록된 판정의 결과다. 논문에서 후자를 지우고 전자만
  쓰면 사전등록의 의미가 없어지고, 전자를 지우고 후자만 쓰면 과대 주장이다. 둘을 함께 적는다.
- **결정성:** M2(벌점형)는 실행하지 않는다 — §6.1 이 "M1 이 §5.3 을 통과하지 못하고 원인이
  '제약이 너무 약하다' 일 때만" 허용했고 M1 은 통과했으므로 사전등록 조건이 성립하지 않는다.
  λ·T_min 재탐색도 하지 않는다 (사후 선택).
### [2026-08-22] E7 층화 지표 선언 + universe 분할 구현

- **분류:** 사전등록 / 구현
- **대상:** `docs/c2_prereg_v1.md` §9.1 (신규), `ptm_shared/representation/replicate_stratum.py`
  (`universe_assignment`, `CONTROL_RUN_LABEL`, `UNIVERSE_*`), `ptm_shared/representation/__init__.py`,
  `workers/tests/test_replicate_stratum.py` (신규 10건)
- **구현 대상 설계:** `c2_prereg_v1.md` §9 (E7), §11 (E7 = 기술적 보고),
  `core_ab_p2_frozen_contract_v1.md` §0.1 (universe 경계)
- **사전등록 상태:** **결과 열람 전 확정.** §9 는 층만 정하고 어떤 양을 층화할지 정하지
  않았으므로 그 공백을 측정 착수 전에 §9.1 로 메웠다. universe 경계(≥2 / 1 / 0)는 §0.1 에서
  이미 동결된 값을 **인용**하며 새로 정하지 않았다.
- **내용:** 층 3축(universe / 관측 시점 수 / 자연 결측률 사분위)과 지표 4개(M1 induced R²,
  M2 족 최대 회수 R², M3 FM_precision, M4 retention ARI)를 선언했다. 지표는 전부 기존 함수를
  부분 모집단에 그대로 호출한다 — 새 정의를 만들면 층별 값과 전체 값을 비교할 수 없다.
  §9 원문이 적은 관측 시점 층 4·5·6 에 **3 을 추가**했다: 모집단 필터가
  `minimum_observed_timepoints = 3` 이므로 빼면 층화가 모집단을 덮지 못한다. 이 추가를 측정
  전에 기록했다. `universe_assignment` 는 `report.pr_matrix.tsv` 의 `con` run 그룹 finite 값
  수로 paired control replicate 를 세며, 이 그룹은 `replicate_stratum_mask` 가 시점으로
  취급하지 않고 무시하는 그룹과 같다.
- **논문에서의 용도:** methods (§9.1 층·지표 정의), supplement (universe 분할 절차)
- **해석 한계:** **임계를 선언하지 않았고 이 실험은 판정하지 않는다.** 의도된 것이다 — 층을
  사후에 고를 수 있으므로 층별 판정을 허용하면 다중 비교가 된다. §11 이 "어느 층에서 인증서가
  충족되어도 C2 성공의 근거가 되지 않는다"를 이미 금지해 두었다. §0.1 의 공표 수치
  (2,420/302/313)와 여기 수가 다른 것은 모집단 차이이며 오류가 아니다.
  universe 분할은 **baseline 신뢰도** 층이고 값의 품질 순위가 아니다.
- **결정성:** 결합 실패를 control replicate 0 으로 강등하지 않고 `unjoined` 로 분리했다 —
  "모른다"와 "측정했으나 없었다"는 다른 상태이고, 섞으면 결합 실패 form 이 전부 U-denovo 로
  들어가 층이 오염된다. 회귀 테스트가 이 구별을 잠근다. 전구체 여러 행은 합이 아니라
  **최대값**으로 올린다(합을 쓰면 전하 상태 수가 replicate 수로 새어든다).

### [2026-08-22] E7 실행 — 전체 요약이 실패를 축소해 보고하고 있었다

- **분류:** 실험
- **대상:** `scripts/run_c2_e7_stratified.py` (신규),
  `docs/results/c2_e7/e7_stratified_arm_d.json`, `docs/c2_prereg_v1.md` §9.2,
  `docs/integrated_research_design_v2.md` §6.7, §7.6.2, §8.1(7번),
  `docs/c3_prereg_v1.md` §17.1(7번)
- **구현 대상 설계:** `c2_prereg_v1.md` §9.1 (`C2_E7_STRATIFICATION_V1`)
- **사전등록 상태:** 층·지표는 결과 열람 전 확정. **판정 없음(설계상).** 비교 불가 기저율은
  첫 실행 **뒤에** 추가했다 — 층별 FM_precision 만으로는 해석이 불가능했기 때문이며, 임계가
  없는 기술 통계이므로 어떤 primary 판정도 이 추가에 영향받지 않는다. §9.2.4 의 기전 설명은
  **탐색적**이고 C3 의 primary 판정을 갱신하지 않는다.
- **내용:** arm D, HIRc-B, n = 2,744. 세 가지가 나왔다.
  (1) **coverage 인코딩은 저관측 층의 인공물이 아니다** — 모집단 84.8% 인 완전 관측 층
  (2,328 form)에서 족 최대 mask 회수 R² 가 **0.9888** 이다(조건 (c) 상한 0.25). 전체 값
  0.6247 은 저관측 층과 섞여 내려간 값이므로 **문제를 축소해 보고한 것**이었다.
  (2) **선언한 층 축 하나가 퇴화했다** — 자연 결측률 사분위 경계 세 개가 모두 0.0 이어서
  Q2·Q3 가 비고 Q1 이 완전 관측 층과 동일 집합이 되었다.
  (3) **FM_precision 의 여지는 층 혼합의 산물이었다** — 층 내 비교 불가 기저율과 나란히
  재면 비가 어느 층에서도 1 을 넘지 않고(0.74–1.00), 전체의 0.52 는 기저율 0.042 인 큰 층과
  1.0 에 가까운 작은 층의 혼합에서 나온다(Simpson 형 역전). 비교 불가가 밀집한 층에서는
  줄일 여지가 구조적으로 없으므로, E9 의 λ 취약성과 E11 의 적대성이 같은 원인에서 나온다.
  전체 기저율 0.2020 은 `c3_prereg_v1.md` §12.3 의 전역 20.2% 와 독립 경로에서 일치했다.
- **논문에서의 용도:** results (§9.2 층별 표), **limitation (해상도 교란, 퇴화한 층 축)**,
  exploratory (§9.2.4 기전 설명 → Chapter 4)
- **해석 한계:** **저관측 층의 낮은 R² 를 독립성으로 읽지 않는다.** `minimum_remaining = 3`
  때문에 관측 4/6 site 는 최대 1개, 관측 3/6 site 는 0개만 마스킹 가능하므로 표적 분산이
  거의 또는 전혀 없다. **증거 부재와 독립성의 증거가 이 설계에서 분리되지 않으며**, 분리에는
  마스킹 예산을 관측 수에 비례시키지 않는 대체 프로토콜이 필요하다(§4 동결 프로토콜 변경이므로
  하지 않는다). M1 은 층 내부에서 회귀를 재적합하므로 층이 작을수록 분산이 크다 — 층별 n 을
  항상 병기한다. n < 20 층은 지표를 `None` 으로 두고 0 으로 채우지 않는다. 단일 코호트.
- **결정성:** 인코더 seed 0, 마스킹 seed 는 benchmark 기본값, 족 회수 순열 20회.
  M1·M2 는 `benchmark._missingness_r2` 와 `coverage_probes.residual_mask_recoverability` 를
  **그대로 호출**한다 — 정의가 바뀌면 E7 도 함께 바뀌게 두어 정의 표류를 막는다.
  M3·M4 의 쌍 제한은 비교가능성 행렬의 부분행렬이며 층 간 쌍은 어느 층 분모에도 들어가지 않는다.

### [2026-08-22] 오더 48 후보 축소(87→29) 원인 규명 — writer 이원화

- **분류:** 진단 / 구현
- **대상:** `ptm_shared/tmm_audit.py` (`classify_heatmap_writer`,
  `count_sub_pattern_candidates`, `HEATMAP_WRITER_*`),
  `scripts/diagnose_heatmap_writer_provenance.py` (신규),
  `docs/results/chapter2_audit/heatmap_writer_provenance.json`,
  `workers/tests/test_tmm_audit_protocol.py` (+6건, 총 20건),
  `docs/chapter2_audit_protocol_v1.md` §3.4 주의, §4.2 연결, §4.3, §4.3.1, §7, §8, §9
- **구현 대상 설계:** `chapter2_audit_protocol_v1.md` §8 미결 1번
- **사전등록 상태:** **탐색적.** 감사 결과를 본 뒤 착수했다. §3.4 의 동결 재생값은 갱신되지
  않았고(재생이 `pooled_summary.json` 을 필드 단위로 재현함을 스크립트가 확인한다),
  사전등록된 임계도 도입하지 않았다. 회귀 테스트가 고정하는 값은 측정 후 고정이며 **판정
  기준이 아니라 "바뀌면 사람이 검토한다"는 표지**다.
- **내용:** 원인은 §8 이 열거한 세 후보(LLM 예측 변화·KEA3 응답 변화·설정 변경) **전부
  아니었다.** `orders.kinase_activity_heatmap` 에 후보 어휘가 다른 writer 가 둘 있다 —
  `api-server/app/api/orders.py:7725` 는 비우세 클러스터를 `f"{kinase}_c{cluster_id}"` 라는
  **별도 후보로 발행**하고, `workers/rag_enrichment/tasks.py::_compute_kinase_activity_heatmap`
  는 `cluster_details` 안에만 보관한다. 두 writer 는 최상위 키로 구별된다(endpoint =
  `_cache_hash`·`computed_at`·`scoring_method`, pipeline = `_cached`·`all_kinase_scores`).
  **6 오더에서 writer 판별과 `_c{n}` 변종 유무가 완전히 일치하며 반례가 없다** —
  endpoint {28, 36, 47} 은 변종 {7, 87, 22}, pipeline {33, 45, 48} 은 전부 0.
  오더 47(WithoutCu)과 48(Cu)은 같은 실험의 두 arm 인데 2026-08-20 에 한 시간 차로
  각각 endpoint(05:13)·pipeline(06:19) writer 가 기록했다. 87→29 는 이 교체다.
  규명 과정에서 **더 큰 문제**가 드러났다(§4.3.1): 동결 fixture 재생을 오더별로 층화하니
  `top1_from_prior_rate` 만 폭이 좁고(0.9048–1.0000, 폭 0.095) 나머지 공표 비율은 폭이
  0.31–0.45 이며 오더 36(site 78.2%)이 통합값을 정한다. 구조적 미결정은 오더 28 에서 61.5%,
  균등 fallback 은 오더 48 에서 8.2% 다.
- **논문에서의 용도:** results (§4.3 원인, §4.3.1 층화 표), **limitation (pooling 지배)**,
  methods (writer 판별 절차)
- **해석 한계:** **어느 writer 가 옳은지 판정하지 않는다.** 후보가 많은 쪽이 더 정확한 것이
  아니다 — §4.1 에서 변종이 정리된 뒤 중복 열 비율이 91.0% → 95.9% 로 **올랐다.**
  2026-08-18 상태는 이 규명으로도 **복구되지 않는다**(입력 미아카이브).
  writer 층 대조(fallback 0.4947 대 0.1739)는 **교란되어 있다** — 오더 36 이 endpoint 층을
  지배하고 두 층의 실험·종·조건 수가 다르다. 짝지은 준대조(47 대 48)에서는 차이가 작으므로
  (미결정 1.000 대 0.959, fallback 0.116 대 0.082) 층 수준 격차를 writer 효과로 귀속하지
  않는다. n = 2 이므로 검정하지 않고, writer 효과와 Cu 효과도 분리되지 않는다.
- **결정성:** 판별은 최상위 키에만 근거하므로 두 writer 스키마가 수렴하면 `unknown` 이
  늘어난다 — 조용히 틀리는 대신 드러나게 설계했고 회귀 테스트가 그 경로를 잠근다.
  sub-pattern 계수는 `is_sub_pattern` 플래그와 이름 형태 두 경로로 세고 불일치를 함께
  보고한다(플래그 없는 writer 의 상태도 세야 하므로 이름 경로가 필요하다).
  진단 스크립트는 DB 를 **읽기만** 한다 — 가변 production 상태를 감사가 바꾸면 안 된다.

### [2026-08-22] distinct 실험 단위 동치 규칙 선언 및 측정 — 디렉터리 20개는 획득 11건

- **분류:** 사전등록 + 측정 + 정정
- **대상:** `docs/integrated_research_design_v2.md` §11.1(표 정정)·§11.1.1(신규 규칙)·§11.1.2(신규
  결과)·§11.2(범위 문구)·§13, `docs/chapter2_audit_protocol_v1.md` §3.4·§4.3.2(신규)·§7·§8,
  `ptm_shared/dataset_units.py`(신규), `scripts/audit_distinct_experimental_units.py`(신규),
  `workers/tests/test_dataset_units.py`(신규),
  `docs/results/dataset_audit/distinct_units_v1.json`(신규)
- **구현 대상 설계:** 2026-08-20 항목이 남긴 미결("distinct 실험 단위 수는 미확정이며 supplement
  에는 디렉터리 수가 아니라 실험 단위 수를 선언해야 한다")
- **사전등록 상태:** **동치 규칙은 결과 열람 전 확정.** §11.1.1 을 먼저 작성·저장하고 그 뒤에
  측정했다. 규칙에 넣지 않은 후보 4개(sha256 동일성·디렉터리명 유사도·실행 수 일치·경로 prefix)와
  각 배제 사유도 측정 전에 적었다. 규칙 작성 전에 확인한 것은 **컬럼명의 형식**뿐이다(run 컬럼이
  획득 파일 전체 경로임) — 식별자를 정의하려면 스키마를 알아야 했고, 이는 분할 결과를 보는 것이
  아니다. 이 사실을 여기에 남긴다.
  단위 수를 본 뒤에 착수한 §4.3.2(오더 33·45)는 **탐색적**이다.
- **내용:** 단위를 "원자료 획득"으로 정의하고, 디렉터리를 정점·원자료 공유를 간선으로 하는 그래프의
  **연결 성분 수**를 세도록 규칙을 고정했다(추이성이 구성상 보장되고 병합 순서에 무관).
  결과 **디렉터리 20개 = 획득 11건**, 고유 원자료 164, 디렉터리 합산 331(중복 계상 167).
  §11.1 의 추측 3곳이 틀렸다 — Irisin 계열은 4건이 아니라 **5건**(PTM-2026-0001 포함),
  Cu/WithoutCu 는 한 쌍이 아니라 **별개 단위 2개**(획득 폴더는 같고 원자료 집합이 서로 소),
  HM 계열은 한 묶음이 아니라 **별개 단위 3개**. 추측에 없던 것도 나왔다 —
  **`Korea_timecouse_drugrepositioning`(오더 33)과
  `Microgravity_Muscle_Atrophy_Phosphoproteomics`(오더 45)는 원자료 12개가 완전히 동일**하며
  `KRIBB_HSC_ubiquitylation`·`KRIBB_SCS_Phosphorylation` 도 15개가 완전히 동일하다(명칭의
  HSC/SCS 는 획득 차이가 아니다). 따라서 **Chapter 2 감사 오더 6건은 독립 획득 5건**이다.
  동시에 §11.1 표의 "실행 수" 열이 **전 행에서 정확히 1 과소**임을 발견하고 정정했다.
  원인까지 규명했다 — 2026-08-20 항목이 기록한 판정식 `\.(mzML|raw|d)$` 가 CRLF 때문에
  `...mzML\r` 로 끝나는 마지막 컬럼에서 `$` 앵커에 실패했다. 판정식을 그대로 재현하면
  BIOEN 5·Insulin 20·Universe_AF 8 로 v2 표와 정확히 일치하고, 개행만 제거하면 6·21·9 다.
- **논문에서의 용도:** supplement (**선언 값 11**), methods (§11.1.1 동치 규칙),
  limitation (§11.2 검증 범위, §4.3.2 오더 수를 표본 수로 쓰지 않음)
- **해석 한계:** **11 은 감사의 폭이며 생물학적 독립 반복 수가 아니다.** 같은 세포주·배치에서
  나온 별개 획득은 별개 단위로 세어지고 그 상관은 보정되지 않는다. 획득 경로로 묶는 민감도는
  8 이며 이것이 배치 수준 상한이지만 **8 은 선언 값이 아니다**(§11.1.1 이 prefix 를 판정에서
  배제). supplement 에는 11 을 선언하고 8 을 함께 적는다.
  이 수는 **적격 판정을 바꾸지 않는다** — 적격 0건은 단위를 어떻게 세든 0건이다.
  이 수로 표본 크기나 검정력을 논하지 않는다(모집단 정의는 `c1_prereg_v1.md` §6,
  `c3_prereg_v1.md` §9). §4.3.2 의 획득 내 차 대 오더 간 폭의 비(0.22–1.00)는 **n = 1 쌍**에서
  나온 것이므로 재처리 변동의 추정값이 아니며, 오더 33·45 는 조건 목록이 비시간순인 두 오더이기도
  해서 시간축 뒤틀림이 교란으로 남는다. 실행 수 정정은 교란 판정과 실험 결과에 영향이 없다 —
  파이프라인은 이 표를 읽지 않고 matrix 를 직접 읽는다.
- **결정성:** 순수 파일 읽기. 난수·솔버·부동소수 연산 없음. 경로 문자열을 **정규화하지 않고**
  비교한다(정규화 규칙 자체가 판정을 흔들기 때문). 정점 순서를 디렉터리명 정렬로 고정하고
  union-find 대표를 최소 이름으로 잡아 출력이 실행 간 동일하다. run 컬럼 판정은 확장자 앵커가
  아니라 **경로 구분자 포함 여부**이며(v2 의 CRLF 오류 재발 방지) 구분자 없는 컬럼이 run 영역에
  섞이면 버리지 않고 `integrity` 에 보고한다. precursor matrix 는 glob `report.pr_matrix*.tsv` —
  고정 파일명으로 잡으면 `report.pr_matrix_phospho.tsv` 인 오더 45 가 조용히 빠진다.
  판정 로직은 `ptm_shared/` 에 두고 `scripts/` 는 출력 형식만 담당한다(컨테이너 PYTHONPATH 에
  `scripts/` 가 없어 회귀 테스트가 import 할 수 없다). 회귀 23건. 전체 스위트 297 passed,
  1 skipped — 수집 오류 2건(`test_cross_species_iptmnet.py`,
  `test_dual_track_ptm_quantification.py`)은 이 변경과 무관한 기존 문제다.

### [2026-08-22] 단위 감사 결과의 파급 반영 — C1 L3 pool 과 §11 데이터 제약

- **분류:** 정정
- **대상:** `docs/c1_prereg_v1.md` §3.1.1(관찰 3 추가), `docs/integrated_research_design_v2.md`
  §11 표·§13(`S-EVAL` 편차 행)
- **구현 대상 설계:** 직전 항목([2026-08-22] distinct 실험 단위 …)의 파급 정리
- **사전등록 상태:** **탐색적.** 단위 수를 본 뒤 착수했다. `c1_prereg_v1.md` 의 **동결 선언은
  건드리지 않았다** — 추가한 것은 §3.1.1 실측 기록 절의 관찰 항목 하나이며 §3.4·§6 의 검정력
  임계와 모집단 정의는 그대로다(계층 크기는 site 수로 정의되고 오더 수로 정의되지 않는다).
- **내용:** C1 의 L3 = "동결 6 오더 pool" 이 **독립 획득 5건**이며, §3.1.1 이 기록한 오더 간
  `S-EVAL` 편차의 상단 33.3%(Microgravity = 오더 45)가 오더 33 과 **동일 획득**임을 명기했다.
  이에 따라 그 편차를 "데이터셋 간 편차"로 부르지 않고, 미규명 원인 후보에 **재처리 차이**를
  추가했다. §11 데이터 제약 표의 "20개 데이터셋"도 "디렉터리 20개 = 획득 11건"으로 고쳤다.
- **논문에서의 용도:** limitation (C1 특성화의 모집단 서술, §11 데이터 제약)
- **해석 한계:** 재처리 차이가 편차의 지배 요인이라고 **주장하지 않는다** — n = 1 쌍이며 두 오더의
  처리 차이가 무엇인지도 규명되지 않았다. 오더 33·45 는 조건 목록이 비시간순인 두 오더이기도
  해서(`chapter2_audit_protocol_v1.md` §8) 시간축 뒤틀림이 교란으로 남는다.
  §10.1.3 의 교훈이 "오더보다 거친 층이 하나 더 있다"로 확장되지만, **E3 미평가 판정은 바뀌지
  않는다**(유전자 블록 수에 걸린 것이며 오더 수와 무관).
- **결정성:** 문서 변경만. 측정 없음.

### [2026-08-22] `group_share` guard 정책 — 그룹 몫 전용 발표

- **분류:** 사전등록 + 구현 + 측정
- **대상:** `docs/chapter2_audit_protocol_v1.md` §5.1·§5.2(개정)·§5.5(신규 선언)·§5.5.1(신규
  결과)·§7·§8, `ptm_shared/tmm_attribution_guard.py`, `ptm_shared/tmm_audit.py::guard_ablation`,
  `api-server/app/services/temporal_kinase_scoring.py`, `scripts/run_tmm_guard_ablation.py`,
  `api-server/tests/test_temporal_kinase_scoring_guard.py`(신규),
  `workers/tests/test_tmm_audit_protocol.py`, `api-server/Dockerfile`, `docker-compose.yml`
- **구현 대상 설계:** §5.2 가 남긴 미결("그룹 몫만 발표하도록 바꾸는 것은 출력 스키마 변경이므로
  v1 범위 밖. guard 가 막지 않는 46%~ 구간이 남는다")
- **사전등록 상태:** **결과 열람 전 확정.** §5.5(정책 정의·비대칭의 근거·스키마 변경 목록·주장
  금지)를 먼저 작성·저장한 뒤 구현했다. **새 임계를 도입하지 않았다** — 판정은 동결된
  `attribution_supported` 와 `ambiguous` 플래그를 그대로 쓴다. 목표 수치 역시 2026-08-18
  동결분에 이미 있던 값(`estimable_group_shares = 891`, `quantity_reduction = 0.8765`)이므로
  이 작업은 **production 출력이 이미 측정된 해상도를 따라가게** 만든 것이고 새 측정이 아니다.
- **내용:** `GUARD_GROUP_SHARE` 를 추가했다. `strict` 에 더해 `unresolved_shared` 의
  `contribution_ratio`(= `group_ratio / |group|`, 즉 solver 가 고른 **균등 분할**)를 None 으로
  발표하고, **그룹 몫과 구성원 목록은 그대로 두며 가중합은 `strict` 와 정확히 동일하게 남긴다.**
  비대칭의 근거: 균등 분할을 발표하는 것은 없는 것을 있다고 말하는 것이지만, 그룹 몫을 점수에서
  빼는 것은 §5.2 가 경고한 대로 실재하는 신호를 버리는 것이다. `GuardDecision` 이
  `ratio_for_scoring` 과 `published_ratio` 를 분리해 둔 이유가 이 경우였고,
  `scoring_excluded` 필드를 더해 소비자가 두 행위를 **추론 없이** 구별하게 했다
  (`ratio_for_scoring == 0.0` 으로 판별하면 안 된다 — ratio 가 정당하게 0 일 수 있다).
  사유 문구도 분리했다(`GROUP_SPLIT_REASON` 대 `WITHHELD_REASON`) — 증거의 부재와 귀속 불가는
  다른 결핍이고 한 문구로 합치면 논문에서 그 구분이 사라진다.
  **결과: 발표되는 개별 kinase ratio 7,216 → 242, 보류 6,974(96.65%).** 발표량은
  그룹 몫 891 개(다중 구성원 649 + 단일 구성원 242)이며 **감소 87.65%**.
  `n_estimable_group_shares` 와 `published_quantity_reduction` 이 동결 감사값과 **소수점까지
  일치**한다(독립 경로 재현). 기존 arm 수치는 전부 불변(537·46.29%·3,463·47.99%·163·4·74).
  **가장 강한 결과: kinase 163개 중 129개(79.1%)는 개별 기여가 분리되는 공유 site 가 하나도
  없다.** `strict` 의 "전부 상실 4개"와 다른 종류의 진술이다.
- **논문에서의 용도:** results (§5.5.1 표), methods (정책 정의와 비대칭의 근거),
  limitation (기본값이 `off` 이므로 권고와 배포 동작이 갈린다)
- **해석 한계:** **기본값은 `off` 로 남는다.** 정책은 구현·측정됐으나 배포되지 않았고
  `production_influence_allowed = False` 가 유지된다. 논문에 "켜져 있다"고 쓰지 않는다.
  **그룹 몫이 신뢰할 수 있다는 뜻이 아니다** — 병합 후에도 30.50% 가 non-identifiable 이다(§3.4).
  통합 87.65% 는 오더 36(발표 쌍의 83.4%)이 정하며 오더별 감소는 59.2%–90.4% 다(§4.3.1 의
  pooling 경고가 그대로 적용된다). 동일 획득인 오더 33·45 가 74.9%·75.6% 로 근접하지만
  **n = 1 쌍이므로 검정하지 않는다.** 발표량 감소는 정확도 개선폭이 아니다.
- **결정성:** ablation 은 동결 fixture 만 읽으므로 DB 상태와 무관하다.
  solver 경로 `scipy.optimize.nnls`, numpy 2.4.6, scipy 1.17.1, float64.
  `group_share` arm 은 점수 질량을 바꾸지 않으므로 `evidence_count_mass_*` 계열을 새로 만들지
  않았고, 그 동일성을 테스트가 모든 resolution 에서 확인한다. 스키마 변경은 가산적이며
  `n_guard_withheld` 는 `off`(0)·`strict`(unsupported 수)에서 값이 불변이다.
  production 배선 검증을 위해 `api-server/Dockerfile` 에 `ARG INSTALL_DEV_DEPS=true` 를 두고
  `api-server/tests` 를 읽기 전용 마운트했다 — 정책 함수 단위 테스트로는 "가중합이 `strict` 와
  같다"는 **production 출력에 대한 주장**을 확인할 수 없다.
  회귀: workers 308 passed / 1 skipped, api-server 11 passed.

### [2026-08-22] 개발 종료 시점 전체 정리 및 외부 검토 요청 v2 — 설계 문서의 낡은 절 정정 포함

- **분류:** 설계 (정리) + 정정
- **대상:** `docs/external_review_request_2026-08-22.md` (신규),
  `docs/external_review_request_2026-08-21.md` (대체 표시),
  `docs/integrated_research_design_v2.md` §0.1·§0.1.1·§9.5·§10·§12
- **구현 대상 설계:** `integrated_research_design_v2.md` §8.1 (0–7번 전부 완료 확인),
  §12 (리뷰 요청 항목의 갱신)
- **사전등록 상태:** 해당 없음 (기존 판정의 정리·인용. **새 판정도 새 임계도 도입하지 않았다.**
  세 사전등록의 동결 규칙·임계·격자는 이 작업으로 변경되지 않는다)
- **내용:** 개발 종료 시점에서 C0·Chapter 2·C1·C2·C3 의 사전등록 판정과 실측을 한 문서로 모으고
  외부 검토 질문 7건을 정리했다. 수치는 전부 세 사전등록 문서와 감사 프로토콜 문서에서 인용하며
  절 번호를 병기했다 — 이 문서는 **1차 근거가 아니다.**

  **정리 과정에서 설계 문서의 낡은 절 5곳을 발견하고 정정했다.** 이 문서는 머리에
  "외부 전문가 리뷰용"이라 적혀 있어 리뷰어가 가장 먼저 읽는데, 실행 결과와 어긋나 있었다.

  ```text
  §0.1     C2 "방법 미구현" · C3 "제약 미구현"  → 둘 다 구현·실행 완료, 방법 주장 부정
           "구현된 기반 1 + 중심 특성화 1 + 사전등록 확장 2" → "구현된 기반 1 + 특성화 3"
  §0.1.1   C2·C3 강등 경로가 미발동으로 남아 있었다 → 발동 기록 추가.
           C2 는 "교환의 불가피성"으로 전환하지 않는다는 단서 병기 (§9.5 와 일치시킴).
           C3 는 흡수가 아니라 **적대** 분기였음을 명기.
           **네 경로 중 셋이 발동했고 설계 요건은 하나의 실패만 상정했다**는 사실을 추가
  §9.5     Chapter 4 (C3) "E11 이 비중복 이득을 보일 때만 독립 장" → 한계 기술 장 확정.
           C3 위상 확정 근거(λ 의존·T_min 의존·C2 적대·기준선 대비)를 블록으로 추가
  §10      "`O_ij` 학습 제약 | 미구현" → 구현·실행 완료, 회귀 46건
  §12      질문 (4)(5)(6) 이 측정으로 해소·역전되었음을 표시.
           (4) 는 "경험적 검증이 충분한가"에서 "**gate 가 느슨했다**"로 역전(§10.5).
           (5) 는 흡수가 아니라 적대로 해소. (6) 은 "과다한가"에서 "**부족한가**"로 역전.
           (7) 은 독립 획득 11 건·감사 5 건으로 범위 축소
  ```

  **회귀 테스트 수를 실측으로 확정했다.** workers 308 passed / 1 skipped,
  api-server 11 passed. 단 `celery-worker-report` 는 아직 `ptm-workers:2.2.2` 이미지라
  pytest 가 없어 `celery-worker-preprocessing`(`ptm-workers:001`)에서 실행했다 —
  **연구 모듈은 읽기 전용 바인드 마운트라 두 컨테이너가 같은 소스를 본다.**
  `test_cross_species_iptmnet` · `test_dual_track_ptm_quantification` 2 파일은 선행 수집 오류
  (모듈 경로·fixture 파일)로 제외했고 이번 작업과 무관하다.
- **논문에서의 용도:** 사용 안 함 (검토 요청 문서). 단 §6 의 사전등록 방법론 관찰 6건은
  discussion / limitation 후보이며, 채택 여부가 검토 질문 Q3 이다
- **해석 한계:** **이 문서는 새 결과를 만들지 않는다.** 인용 과정에서 붙인 해석 —
  특히 §2.2 의 "세 실패의 공통 기전은 층 구조"라는 설명 — 은 **탐색적**이다.
  E7 은 C2 인증서 판정 이후에 선언되었고 C3 와의 연결은 `c3_prereg_v1.md` §17.1 항 7 에서
  명시적으로 탐색적이다. **primary 승격 영구 금지.**
  §6 의 6건 중 6.3·6.4·6.5 는 **사후에 발견된 우리 설계의 결함**이며 "일반적 교훈"과
  구별할 독립 근거가 없다 — 그 구별을 §6.7 에 적어 두었고 논문에서 뭉치지 않는다.
  §2.3 의 세 척추안 중 어느 것도 확정이 아니다. 확정으로 인용하지 않는다.
- **결정성:** 문서 작업이므로 seed·solver 무관. 인용 수치는 전부 기존 동결 산출물에서 왔고
  이 작업으로 재계산하지 않았다. 회귀 실행 환경: `ptm-workers:001`,
  `ptm-api-server:001`, python 3.11.

---

### [2026-08-22] Substrate-level Temporal Dynamics Contract v1 (P1) 구현

- **분류:** 구현
- **대상:**
  - 신규 `ptm_shared/substrate_temporal_dynamics.py`
  - 수정 `ptm_shared/temporal_wave_engine.py` (`_member_detail`, `_build_wave`)
  - 신규 `workers/tests/test_substrate_temporal_dynamics.py`
- **구현 대상 설계:** Substrate-level Temporal Dynamics Deepening Plan v1 §4 (P1),
  `docs/external_review_request_2026-08-22.md` Appendix
- **사전등록 상태:** 플랫폼 엔지니어링 모듈 — 방법론적 기여 아님. 분류 taxonomy 및
  gate threshold 는 `CONTRACT_VERSION = "substrate_temporal_dynamics.v1"` 에 동결.
- **내용:**
  - `ptm_shared/substrate_temporal_dynamics.py` 신규 생성:
    - 입력: 시간점 레이블 시퀀스 + 값(Optional[float]) + q_value (optional)
    - 출력: `SiteKineticProfile` dataclass (signal/quality, onset/peak, duration,
      rise/recovery, shape, pattern, uncertainty, provenance 필드 포함)
    - **15개 taxonomy label** (flat → monotone → single_pulse → sustained →
      biphasic → multi_peak/oscillatory → unresolved); 레이블 precedence 동결
    - 분류 우선순위 (L0→L6): quality_gate, multi_peak/oscillatory, biphasic,
      monotone_rise (pk at last), monotone_decline (pk at first, no recovery),
      sustained, single_pulse/suppression
    - LOTO(Leave-One-Timepoint-Out) stability: 각 시간점 제거 후 패턴 일치 비율
    - threshold sensitivity: onset_threshold × {0.5, 2.0} 에서 레이블 변화 여부
    - `describe_member_dynamics()`: wave member 삽입용 compact 출력
    - `summarise_member_pattern_distribution()`: wave-level pattern composition
  - `temporal_wave_engine.py` 수정:
    - `_member_detail()`: `site_dynamics` 키 추가 (describe_member_dynamics 호출)
    - `_build_wave()`: `member_pattern_summary` 키 추가
  - `test_substrate_temporal_dynamics.py` 신규 56 tests (56 passed, 0 failed):
    - A. Feature computation (17 tests)
    - B. Taxonomy labels — 아키타입 1개 per label (11 tests)
    - C. Stability metrics (5 tests)
    - D. Edge cases (7 tests)
    - E. Wave integration helpers (6 tests)
    - F. Frozen thresholds regression (10 tests)
  - 주요 설계 결정 3건:
    1. endpoint를 local extremum에서 제외 (monotone의 후행 극값 오인식 방지)
    2. sign-switch 판별은 opposite-sign max 탐색으로 단순화
    3. monotone_rise/decline은 pk가 마지막/첫 번째 관측점일 때만 발동하며
       sustained가 먼저 발동하지 않도록 precedence 조정
- **논문에서의 용도:** 플랫폼 기능 기술 (methods 부록); 방법론적 주장 불가
- **해석 한계:** pattern label은 관측 궤적의 형태 기술. kinase 귀속, causal claim,
  protein-level aggregation 에 사용 금지.
- **결정성:** 분류 로직은 결정론적 (numpy argmax, sorted 우선순위). seed 불필요.
  threshold 상수는 모듈 레벨 상수로 동결됨.
  회귀 테스트 환경: python 3.12.4 (local), 56 passed / 0 failed.

---

### [2026-08-22] Condition-aware Substrate Divergence (P2) + Kinase Substrate Phenotype (P3) 구현

- **분류:** 구현
- **대상:**
  - 신규 `ptm_shared/substrate_divergence.py`
  - 수정 `ptm_shared/substrate_temporal_dynamics.py` (`compute_kinase_substrate_phenotypes` 추가)
  - 신규 `workers/tests/test_substrate_divergence.py`
  - 수정 `workers/tests/test_substrate_temporal_dynamics.py` (P3 테스트 추가)
- **구현 대상 설계:** Substrate-level Temporal Dynamics Deepening Plan v1 §5 (P2), §6 (P3)
- **사전등록 상태:** 플랫폼 엔지니어링 모듈 — 방법론적 기여 아님.
  `divergence_score` 가중치 및 `CONTRACT_VERSION = "substrate_divergence.v1"` 에 동결.
- **내용 — P2 (`substrate_divergence.py`):**
  - `SiteConditionDivergence` dataclass: 두 조건 간 feature-vector 차이
    (timing delta, amplitude ratio/log2, AUC delta, pattern conservation, sign reversal,
     composite divergence score, quality gate flags)
  - `compare_site_profiles(profile_a, profile_b)` → `SiteConditionDivergence`
  - `compare_site_trajectories(labels, values_a, values_b)` → (divergence, pa, pb)
  - `summarise_population_divergence(divergences)` → `PopulationDivergenceSummary`
    (n_conserved, conservation_rate, pattern_transition_counts, top_transitions, 집계 통계)
  - `divergence_score` 공식 (동결 가중치):
    - sign_reversal × 3.0 + pattern_change × 1.5 + |log2_ratio| (cap 2) × 1.0/FC + |peak_shift/span| × 2.0
- **내용 — P3 (`compute_kinase_substrate_phenotypes`):**
  - 입력: `site_profiles` {site_key: SiteKineticProfile} + `kinase_substrates` {kinase: [site_key]}
  - 출력: 키네이스별 substrate pattern distribution (n_substrates, n_quality_passed,
    pattern_counts, dominant_pattern, pattern_diversity, flat_fraction)
  - 목적: TMM attribution 결과와 site-level kinetic 분류를 교차하여 kinase마다
    어떤 dynamics phenotype의 substrate를 가지는지 기술
- **논문에서의 용도:** 플랫폼 기능 기술 (methods 부록); 방법론적 주장 불가
- **해석 한계:**
  - divergence_score는 feature distance이며 통계적 유의성이 아님.
  - sign_reversal이 높아도 kinase Y가 원인이라는 주장 불가.
  - kinase substrate phenotype은 귀속의 정확성을 검증하지 않음.
- **결정성:** 분류·점수 모두 결정론적. seed 불필요.
  회귀 테스트 환경: python 3.12.4 (local), 101 passed / 0 failed
  (P1 56 + P2 39 + P3 6 = 101).

### [2026-08-22] group_share 기본값 전환, P4 report/frontend 연동, benchmark seed 잡음 하한 병기

- **분류:** 구현
- **대상:**
  - 수정 `api-server/app/services/temporal_kinase_scoring.py`
  - 신규 함수 `build_substrate_dynamics_summary` in `workers/report_generation/core/dynamic_prompt_generator.py`
  - 수정 `workers/report_generation/core/nodes/writer_node.py`
  - 수정 `frontend/src/pages/OrderDetail.tsx`
  - 수정 `ptm_shared/representation/benchmark.py`
- **구현 대상 설계:**
  - group_share 기본값: `docs/chapter2_audit_protocol_v1.md` §5.5 (2026-08-22 선언)
  - P4 report 연동: Substrate-level Temporal Dynamics Deepening Plan v1 §7 (P4)
  - frontend adapter: 동 §7 (P4 UI alignment)
  - benchmark 잡음 하한: `docs/integrated_research_design_v2.md` §8.2.2 재현 가능 하한 기재 요건
- **사전등록 상태:**
  - group_share 기본값: 2026-08-22 선언 후 즉시 구현 (결과 열람 전).
  - seed_noise_lower_bound 계수 0.10: 2026-08-22 확정 (열람 전). 탐색 실행 없음.
  - P4 report/frontend: 플랫폼 엔지니어링 — 방법론적 선언 불필요.
- **내용 ①: GUARD_GROUP_SHARE 기본값 전환**
  - `compute_kinase_activity_scores()` 의 `guard_policy` 기본값을 `GUARD_OFF` → `GUARD_GROUP_SHARE` 로 변경.
  - 배경: 2026-08-22 chapter2 audit에서 87.65% ratio 축소 효과 확인;
    가중합은 GUARD_STRICT 와 동일하므로 점수 수치 불변.
  - 즉시 배포 적용 — 이전 `GUARD_OFF` 결과와 비교하면 per-kinase ratio 컬럼만 달라진다.
- **내용 ②: P4 Report 연동 (`build_substrate_dynamics_summary`)**
  - `dynamic_prompt_generator.py` 에 신규 함수 추가.
  - 입력: `parsed_ptms` (context_loader 출력), `max_sites=500`.
  - 처리: 각 PTM의 `trajectory.timepoints[].ptmLog2FC` 를 `compute_site_kinetic_profile`
    (P1 contract, `run_loto=False` 로 경량화)로 분류.
  - 출력: 패턴 분포 Markdown 블록 (top 5 패턴, mean amplitude, missingness 경고 수).
  - `writer_node.py` 의 supplement_blocks에 `("substrate_dynamics", …)` 로 주입.
  - ptm_shared.substrate_temporal_dynamics import 실패 시 빈 문자열 반환 (graceful degradation).
- **내용 ③: Frontend classifyTrend() P1 어댑터 정렬**
  - `P1_PATTERN_TO_TREND: Record<string, TrendCategory>` 15→8 매핑 상수 추가.
  - `p1PatternToTrend(pattern)` 어댑터 함수 추가.
  - `ptmTrends` 계산 루프: `top_n_ptms[].p1_pattern` 필드가 있으면 어댑터 우선 사용,
    없으면 기존 `classifyTrend()` 폴백.
  - 현재 백엔드가 `p1_pattern` 을 `top_n_ptms` 에 실어 내보내지 않으므로 폴백 경로가 사용됨.
    추후 API가 이 필드를 추가하면 자동 전환.
- **내용 ④: benchmark seed 잡음 하한 (`seed_noise_lower_bound`)**
  - `run_ablation()` 에서 `ε = 0.10 · mean_site_rms(target)` 계산.
  - 모든 evaluated arm metrics 에 `seed_noise_lower_bound` 주입.
  - `evaluate_adoption_gates()` `time_validity` 게이트 출력에 두 필드 추가:
    - `seed_noise_lower_bound`: 잡음 추정치 (observed_heldout_error 와 같은 단위, RMSE)
    - `margin_exceeds_noise_floor`: margin ≥ ε 여부 (진단 플래그; 게이트 통과 기준은 unchanged)
- **논문에서의 용도:**
  - group_share: Chapter 2 Methods §5 (공개 기준 엄격화 설명)
  - substrate_dynamics report block: 플랫폼 부록
  - seed_noise_lb: §8.2 재현 가능성 설명 (진단, methods)
- **해석 한계:**
  - group_share 전환은 ratio 공개 범위 변경이며 점수 개선 주장 불가.
  - substrate_dynamics 패턴 블록은 형태 기술이며 kinase 귀속 또는 인과관계 아님.
  - margin_exceeds_noise_floor=False 는 게이트 실패가 아닌 진단 플래그임.
- **결정성:** group_share·frontend 변경은 결정론적.
  benchmark seed 잡음 하한은 target matrix 수치에 의존 (dtype float32 또는 float64,
  `MultiViewTemporalInput.target.values` 그대로 사용).

### [2026-08-22] p1_pattern API 노출, frontend P1 서브라벨, heatmap writer 통합

- **분류:** 구현
- **대상:**
  - 수정 `api-server/app/api/orders.py` (`_compute_p1_pattern` 신규 + `top_n_ptms` 필드 추가)
  - 수정 `frontend/src/pages/OrderDetail.tsx` (P1 뱃지, 서브라벨, 툴팁, 필터 breakdown)
  - 수정 `workers/rag_enrichment/tasks.py` (sub-pattern 생성 로직 통합)
- **구현 대상 설계:** Substrate-level Temporal Dynamics Deepening Plan v1 §7 (P4 UI/API 연동)
- **사전등록 상태:** 플랫폼 엔지니어링 — 방법론적 선언 불필요.
- **내용 ①: `top_n_ptms` API에 `p1_pattern` 필드 추가**
  - `_compute_p1_pattern(ptm)` helper: enriched data의 `trajectory.timepoints[].ptmLog2FC` 로
    P1 contract 호출 (run_loto=False 경량), 실패 시 None 반환 (graceful).
  - `get_vector_plot_data` 응답 `top_n_ptms[].p1_pattern` 필드 추가.
  - 이 필드가 있으면 frontend P1 어댑터(`p1PatternToTrend`)가 heuristic 폴백 없이 canonical label 사용.
- **내용 ②: frontend P1 서브라벨 표시**
  - PTM 범례 아이템: `p1Pat` 있으면 인디고 색상 소형 뱃지 (`text-[8px]`) 표시.
  - 색상 dot title: `TREND_META label · P1: {p1Pat}` 형식.
  - span title: role, actCls, P1 pattern 포함.
  - Trend filter 버튼 tooltip: P1 서브패턴별 카운트 추가 (`p1SubCounts` 계산).
- **내용 ③: pipeline worker sub-pattern 생성 로직 통합**
  - 문제: `workers/rag_enrichment/tasks.py`의 `_compute_kinase_activity_heatmap()`은
    K-Means 클러스터링 결과를 갖고 있으나 `is_sub_pattern` 항목을 생성하지 않아
    `api_endpoint` writer와 출력 구조가 달랐음 (heatmap_writer_provenance audit 지적).
  - 수정: 각 kinase 메인 항목 append 직후, 비우세 클러스터 중 peak_condition 이 다른 것에
    대해 sub-pattern 항목 생성. API endpoint writer(orders.py §kinase_activity_heatmap)와
    동일한 필드 구조 (`is_sub_pattern`, `sub_pattern_label`, `sub_pattern_category`,
    `parent_kinase`, `confidence × 0.7`).
  - 임계: size < 2 또는 |peak_score| < 0.3 은 제외 (API endpoint 동일 로직).
- **논문에서의 용도:** 플랫폼 기능 기술 (부록); p1_pattern 노출은 방법 §P1 연결고리.
- **해석 한계:**
  - `_compute_p1_pattern` 은 trajectory 길이 < 3 이면 None 반환 — P1 뱃지는 충분한 시간점 데이터 보유 시에만 표시.
  - sub-pattern 항목은 클러스터 기반 구성이며 독립 kinase 귀속이 아님. `is_sub_pattern: True` 로 명시.
- **결정성:** P1 분류 — 결정론적 (seed 없음, run_loto=False).
  sub-pattern 생성 — `_numpy_kmeans(seed=42)` 상속, API 동일.

### [2026-08-22] P0 X축 감사 필드, GUARD_GROUP_SHARE 기본값 회귀 테스트, substrate temporal atlas API

- **분류:** 구현
- **대상:**
  - 수정 `ptm_shared/substrate_temporal_dynamics.py` (P0 필드 + 로직)
  - 수정 `workers/tests/test_substrate_temporal_dynamics.py` (P0 테스트 7건 추가)
  - 수정 `api-server/tests/test_temporal_kinase_scoring_guard.py` (기본값 회귀 테스트 추가)
  - 수정 `api-server/app/api/orders.py` (substrate_temporal_atlas 엔드포인트 추가)
- **구현 대상 설계:**
  - P0: Substrate-level Temporal Dynamics Deepening Plan v1 §3 (P0 입력 감사)
  - atlas API: 동 §7 (P4 atlas 데이터 소스)
  - guard 기본값 회귀 테스트: docs/chapter2_audit_protocol_v1.md §5.5 (기본값 전환 사후 고정)
- **사전등록 상태:**
  - P0 필드: 플랫폼 엔지니어링 — 방법론적 선언 불필요.
  - guard 회귀 테스트: 2026-08-22 기본값 전환 직후 추가. 전환 사유는 동일 날짜 원장 참조.
- **내용 ①: P0 X축 입력 감사 (`SiteKineticProfile` 신규 필드)**
  - `time_ordering_warning`: 파싱된 분 단위 시간이 비감소 순서가 아니면 True.
  - `duplicate_timepoint_warning`: 동일 분 값이 2번 이상 등장하면 True.
  - 두 필드 모두 패턴 분류에 영향 없음 — 진단 전용.
  - 구현: `_parse_trajectory`가 반환하는 `all_minutes_raw`에서 계산.
    unparseable label(무한대)은 제외하고 파싱 성공한 분 값만 검사.
  - 회귀 테스트 7건: 정상/역순/단일역전/중복/미파싱/패턴독립 시나리오.
  - P0 테스트 포함 전체 테스트: 69 passed / 0 failed.
- **내용 ②: GUARD_GROUP_SHARE 기본값 회귀 테스트**
  - `test_default_guard_policy_is_group_share`: `guard_policy` 를 명시하지 않은
    `compute_weighted_kinase_scores()` 호출에서 `tmm_identifiability.guard_policy == GUARD_GROUP_SHARE` 검증.
  - 실행: `PYTHONPATH=/path/ptm-platform python3 -m pytest ... -q` → 12 passed.
- **내용 ③: `/orders/{id}/substrate-temporal` API 엔드포인트**
  - GET 엔드포인트. auth: `_check_order_access` (소유자/admin 전용, read).
  - enriched_ptm_data*.json 에서 trajectory ≥ 3 시간점인 모든 사이트를 P1 contract로 분류.
  - 응답 필드: site_key, gene, position, primary_pattern, pattern_modifiers,
    quality_gate_passed, amplitude, peak_minutes, onset_minutes, auc_signed, auc_absolute,
    return_to_baseline, missingness_warning, time_ordering_warning,
    duplicate_timepoint_warning, observed_timepoints, timepoint_labels, values.
  - 최상위 필드: n_sites, pattern_distribution (카운트 집계), contract_version, status.
  - `ptm_shared` import 실패 시 `{"sites": [], "status": "module_unavailable"}` 반환.
- **논문에서의 용도:**
  - P0 필드: methods 부록 (데이터 품질 감사 절차 기술).
  - atlas API: 플랫폼 기능 기술 (부록).
- **해석 한계:**
  - P0 경고는 입력 데이터 형식 문제를 표시하며 생물학적 해석 불가.
  - atlas API는 계산된 패턴의 분포 통계이며 kinase 귀속 결론을 지지하지 않는다.
- **결정성:** P0 + atlas — 결정론적 (seed 없음, run_loto=False).

### [2026-08-22] Temporal Atlas 500 — `DATA_DIR` NameError 정정

- **분류:** 정정
- **대상:** `api-server/app/api/orders.py` (`substrate_temporal_atlas`)
- **구현 대상 설계:** Substrate-level Temporal Dynamics Deepening Plan v1 §7 (P4 atlas API)
- **사전등록 상태:** 해당 없음 (경로 해석 버그. 측정량·임계를 바꾸지 않음)
- **내용:** `/orders/{id}/substrate-temporal` 이 정의되지 않은 `DATA_DIR` 를 참조해
  `NameError` → HTTP 500 을 냈다. 다른 오더 엔드포인트와 동일하게
  `Path(os.getenv("OUTPUT_DIR", "/app/data/outputs")) / order.order_code` 로 맞췄다.
- **논문에서의 용도:** 사용 안 함 (플랫폼 경로 수정)
- **해석 한계:** 이 수정은 엔드포인트가 파일을 찾지 못해 죽던 것을 고친다.
  패턴 분류·atlas 적격 판정을 바꾸지 않는다.
- **결정성:** 해당 없음

### [2026-08-22] Temporal contract A/B (`legacy` / `current`)

- **분류:** 사전등록 + 구현
- **대상:** `docs/substrate_temporal_dynamics_deepening_plan_v1.md` §8,
  `ptm_shared/temporal_contract.py`, RAG heatmap, API heatmap/vector-plot/atlas,
  report graph/writer, Order Create / Rerun / Duplicate UI
- **구현 대상 설계:** §8 (2026-08-22, 구현 착수 전 선언)
- **사전등록 상태:** 결과 열람 전 확정. 새 임계 없음. 경로 선택 스위치.
- **내용:**
  - `report_options.temporal_contract`: `current`(기본, 키 누락 포함) |
    `legacy`.
  - `legacy`: `GUARD_OFF`, heatmap `_c1/_c2` 없음, P1/Atlas를 리포트·탭에
    넣지 않음.
  - `current`: 2026-08 기본 경로 (`group_share`, sub-pattern, P1, Atlas).
  - 비교는 Duplicate Order 후 한쪽만 `legacy` 로 두고 Compare 페이지를 쓴다.
- **논문에서의 용도:** methods (어느 오더가 어느 경로인지 기록)
- **해석 한계:** 스위치는 경로 선택이다. current 가 kinase 귀속을 개선했다는
  뜻이 아니다.
- **결정성:** 해당 없음

### [2026-08-22] Temporal contract 표시명 — Current → Dynamics v1

- **분류:** 정정
- **대상:** `ptm_shared/temporal_contract.py`, UI 라벨, `docs/substrate_temporal_dynamics_deepening_plan_v1.md` §8
- **구현 대상 설계:** 동 §8 (이름만 고정. 경로 효과는 그대로)
- **사전등록 상태:** 해당 없음 (표시/저장 이름. 측정량을 바꾸지 않음)
- **내용:** 상대 시각 이름 `current` 를 **Dynamics v1** (`dynamics_v1`) 으로 바꿨다.
  이미 저장된 `current` 는 alias 로 같은 경로다. `legacy` 는 그대로다.
- **논문에서의 용도:** methods 표기 (`Dynamics v1` vs `Legacy`)
- **해석 한계:** 이름 변경은 경로를 바꾸지 않는다.
- **결정성:** 해당 없음

### [2026-08-23] Temporal Atlas 빈 화면 — enriched 파일 suffix 정정

- **분류:** 정정
- **대상:** `api-server/app/api/orders.py` (`substrate_temporal_atlas`)
- **구현 대상 설계:** Substrate-level Temporal Dynamics Deepening Plan v1 §7 (P4 atlas API)
- **사전등록 상태:** 해당 없음 (경로 해석 버그. 측정량·임계를 바꾸지 않음)
- **내용:** phosphorylation 오더에서 Atlas 가 `enriched_ptm_data.json` 을 찾아
  `no_enriched_data` 를 반환했다. RAG 산출물은 `enriched_ptm_data_phospho.json`
  이다. 다른 오더 엔드포인트와 같이 `_phospho` / `_ubi` suffix 를 쓰고,
  그래도 없으면 `enriched_ptm_data*.json` glob fallback 을 쓴다.
- **논문에서의 용도:** 사용 안 함 (플랫폼 경로 수정)
- **해석 한계:** 이 수정은 존재하는 궤적 파일을 찾지 못하던 것을 고친다.
  패턴 분류·atlas 적격 판정을 바꾸지 않는다.
- **결정성:** 해당 없음

### [2026-08-23] De novo 표시를 LOD-relative + 검출 반복으로 교체

- **분류:** 설계 + 구현
- **대상:** `docs/de_novo_representation_contract_v1.md` (신규),
  `ptm_shared/de_novo_representation.py`,
  `workers/preprocessing/core/ptm_quantification.py`,
  `workers/rag_enrichment/tasks.py`,
  `workers/rag_enrichment/core/ptm_merger.py`,
  `workers/report_generation/core/nodes/writer_node.py`,
  `workers/report_generation/core/dynamic_prompt_generator.py`,
  `workers/report_generation/core/nodes/signal_flow_figure.py`,
  `workers/report_generation/core/nodes/context_loader.py`,
  `api-server/app/api/orders.py`,
  `frontend/src/pages/OrderDetail.tsx`,
  `frontend/src/pages/OrderCreate.tsx`
- **구현 대상 설계:** `docs/de_novo_representation_contract_v1.md` §3–§10
- **사전등록 상태:** 결과 열람 후 (탐색적, primary 금지). 기존 오더의
  pseudo-Log2FC 산출을 본 뒤에 표시·순위 규칙을 고정했다.
- **내용:** Control 결측을 0이 아니라 검출한계 미만으로 두고, de novo의
  Conventional Log2FC를 NA로 표시한다. LOD는 control run 검출 intensity의
  5th percentile median. 양적 표현은 검출 반복 수, 처리군 normalized
  abundance, LOD-relative lower-bound(`≥`)다. Dynamics v1 자체는 유지하고,
  PTM priority에서 |pseudo-Log2FC|를 제거했다. `top_n`은 contract
  `ranking_score`로 N개를 고르고, `de_novo_regulated`는 High/Moderate만
  기본 서술 우주에 넣는다. Kinase heatmap de novo 가중 1.5와 raw FC는
  폐기했다.
- **논문에서의 용도:** methods (de novo 결측·LOD·표시), limitation
  (정확한 FC를 주장하지 않음)
- **해석 한계:** LOD-relative는 정확한 fold change가 아니다. 재현성 등급과
  ranking_score는 서술 우주 선택용이며 kinase 귀속 또는 생물학적 중요도가
  아니다. 기존 오더는 전처리 재실행 전에는 site-level TSV fallback 또는
  고정 1.5×w(confidence)를 쓴다.
- **결정성:** dtype float64, NumPy percentile default, log2=np.log2, seed 없음.
  상수 `LOD_PERCENTILE=5.0`, `LOD_INDUCTION_RANK_CAP=4.0` 은 계약 §3·§8.

### [2026-08-23] Figure 1을 Direct NES + 독립 Protein/Network 열로 교체

- **분류:** 설계 + 구현
- **대상:** `docs/graph_aware_pathway_expansion_contract_v1.md` (신규),
  `ptm_shared/pathway_expansion.py`,
  `workers/report_generation/core/nodes/pathway_figure.py`,
  `workers/report_generation/core/nodes/network_node.py`,
  `workers/report_generation/core/nodes/signaling_cascade.py`,
  `workers/report_generation/core/nodes/writer_node.py`,
  `workers/report_generation/core/figure_context.py`
- **구현 대상 설계:** `docs/graph_aware_pathway_expansion_contract_v1.md` §2–§10
- **사전등록 상태:** 결과 열람 후 (탐색적, primary 금지). Insulin Dynamic V1
  Figure 1의 `Σ|Log2FC|` 편향을 본 뒤에 규칙을 고정했다.
- **내용:** Pathway 1차 순위를 직접 소속 정량 단백질의 시점별 weighted NES +
  BH-FDR로 바꾼다. Protein support와 STRING/BioGRID 1-hop은 같은 축에 합치지
  않는 보조 열이다. De novo(control 미검출)는 Direct universe에서 제외하고
  개수만 남긴다(방법 A). 단백질당 site는 `|E|` 최대 하나. 기능 부호 표는
  용어(activated/inhibited/modulated/network-associated)에만 쓴다.
  `PATHWAY_SIGNAL_ORDER` / template overlap은 cascade 화살표 배치에만 남기고
  점수에서 제거했다. Writer는 Σ|Log2FC| 순위와 “PI3K-Akt MUST be discussed”
  지시를 쓰지 않는다. 합성 `0.75 NES + 0.15 coherence + 0.10 network`는
  계산하지 않는다.
- **논문에서의 용도:** methods (Direct NES, 방법 A, protein cap), limitation
  (탐색적 가중, NES≠activation)
- **해석 한계:** Direct NES는 소속 정량 단백질의 enrichment다. pathway
  activation, kinase 활성, 인과가 아니다. STRING support로 pathway를
  발견했다고 쓰지 않는다. Insulin/MAPK canonical hit로 개선을 주장하지 않는다.
- **결정성:** dtype float64, `N_PERM=500`, seed `PERM_SEED + 1000*t + p`
  (`PERM_SEED=20260823`), BH 단조성 보정. 상수 `L_SHARED=0.50`,
  `L_UNVERIFIED=0.30`, `S_SIG=1.0`, `S_MISSING=0.70`, `S_NS=0.50`,
  `GSEA_WEIGHT_P=1`, `MIN_DIRECT_GENES=2`, `MIN_UNIVERSE=15`,
  `STRING_CONF_MIN=0.70`, `NETWORK_ALPHA=0.15`,
  `DIRECTION_CONSISTENCY_MIN=0.75` 는 계약 §3–§8.

### [2026-08-23] KSTAR·RoKAI related-work 비교 메모

- **분류:** 설계
- **대상:** `docs/2026-08-23_kstar_rokai_comparison.pdf`
- **구현 대상 설계:** 신규 — 외부 논문 위치 확인. 측정값·임계 변경 없음
- **사전등록 상태:** 해당 없음
- **내용:** Crowl et al. 2022 (KSTAR)과 Yılmaz et al. 2021 (RoKAI)을
  production heatmap·TMM·KEA3·Wave·C0–C3와 층별로 대조한 메모를 PDF로 고정.
  새 점수·임계를 도입하지 않는다.
- **논문에서의 용도:** related work / limitation (주장 범위 점검)
- **해석 한계:** 이 문서는 두 알고리즘보다 정확하다는 증거가 아니다.
  heatmap을 activity로 부르거나 TMM을 IKAP의 시계열 개선으로 쓰지 않는다.
- **결정성:** 해당 없음 (문헌 대조, 수치 재계산 없음)

### [2026-08-23] Quick Analysis mode (PR/PG 입력 서브셋)

- **분류:** 구현
- **대상:** `docs/quick_analysis_contract_v1.md`,
  `workers/preprocessing/core/quick_analysis.py`,
  `workers/preprocessing/tasks.py`,
  `frontend/src/pages/OrderCreate.tsx`
- **구현 대상 설계:** `docs/quick_analysis_contract_v1.md` §4–§7
- **사전등록 상태:** 결과 열람 후가 아님. 상수 선언 후 구현. 탐색적, primary 금지
- **내용:** 오더 생성 `analysis_options.quick_analysis=true` 이면 정량 전에
  대상 PTM precursor를 최대 400개로 줄인다. 시점 열·unmodified pair·대응 PG는
  유지. `PTMQuantificationAnalyzer` 산식은 그대로다.
- **논문에서의 용도:** 사용 안 함 (개발 반복용). limitation에 exploratory로만 언급 가능
- **해석 한계:** sample-median 정규화 인자가 Full과 다르다. Quick Log2FC·Wave·TMM을
  Full 또는 primary 수치로 쓰지 않는다.
- **결정성:** `QUICK_MAX_PTM_PRECURSORS=400`, `QUICK_PER_PROTEIN_CAP=4`,
  `QUICK_MIN_DETECTION_FRAC=0.50`. 정렬 `(-detection_frac, Protein.Group, Precursor.Id)`,
  mergesort. UniMod phospho=21, ubi=121.

### [2026-08-23] Custom Quick Analysis 입력 규칙 오버라이드

- **분류:** 구현
- **대상:** `docs/quick_analysis_contract_v1.md` §4.1,
  `workers/preprocessing/core/quick_analysis.py`,
  `frontend/src/components/QuickAnalysisOptions.tsx`
- **구현 대상 설계:** `docs/quick_analysis_contract_v1.md` §4.1 (선언 후 구현)
- **사전등록 상태:** 결과 열람 전 선언. 탐색적, primary 금지
- **내용:** Quick On일 때 사용자가 예산·단백질 cap·검출률·unmodified pair·
  non-PTM PG 추가를 바꿀 수 있다. 기본값은 §4와 같다. 범위 밖은 clamp.
  non-PTM은 PG 행만 추가하고 그 단백질의 unmodified precursor 전체를 넣지 않는다.
  시점 열은 오버라이드 금지. 정량 산식은 그대로다.
- **논문에서의 용도:** 사용 안 함 (개발 반복용)
- **해석 한계:** Custom 값이 더 좋은 kinase 추정이나 Full 대비 정확도를 만들지 않는다.
  설정마다 median 정규화 인자가 달라져 Quick끼리도 비교하지 않는다.
- **결정성:** clamp 범위 max PTM [10, 5000], cap [0, 50], detection [0, 1],
  non-PTM PG [0, 5000]. 기본 400 / 4 / 0.50 / pairs on / non-PTM off.

### [2026-08-24] Report run-stage가 queued에서 skip 되던 상태 게이트 수정

- **분류:** 정정
- **대상:** `api-server/app/api/orders.py` (`POST /orders/{id}/run-stage`),
  `workers/report_generation/tasks.py` (`run_report_generation`)
- **구현 대상 설계:** 해당 없음 (파이프라인 실행 게이트, 측정 상수 아님)
- **사전등록 상태:** 해당 없음
- **내용:** report 단독 재실행 시 API가 `status=queued`로 커밋한 뒤 워커가
  `queued`를 stale로 보고 skip 하던 불일치를 고쳤다. report stage는
  `report_generation`으로 두고, 워커 허용 집합에 그 값을 추가한다.
  `queued`는 계속 거부한다 (이전 run의 stale task 보호).
- **논문에서의 용도:** 사용 안 함
- **해석 한계:** 리포트 내용·정량 수치·kinase 판정을 바꾸지 않는다.
  실행 시작 조건만 맞춘다.
- **결정성:** 해당 없음

### [2026-08-24] Cancel 후 재시작 시 stale 워커 차단

- **분류:** 정정
- **대상:** `workers/common/run_control.py`, `workers/common/progress.py`,
  `workers/common/db_update.py`, `workers/preprocessing/tasks.py`,
  `workers/rag_enrichment/tasks.py`, `workers/report_generation/tasks.py`,
  `api-server/app/api/orders.py`, `api-server/app/api/user_orders.py`,
  `frontend/src/pages/OrderDetail.tsx`
- **구현 대상 설계:** 해당 없음 (파이프라인 실행 게이트, 측정 상수 아님)
- **사전등록 상태:** 해당 없음
- **내용:** cancel이 체인 전체 Celery task id를 revoke 하도록 바꿨다.
  start/run-stage마다 Redis `order_run_gen`을 올리고, 이전 워커는
  generation이 다르면 상태/로그를 쓰지 않고 중단한다.
  Re-run UI는 고정 1.5초 대기 대신 cancel 상태를 폴링한다.
- **논문에서의 용도:** 사용 안 함
- **해석 한계:** 워커 프로세스의 즉시 종료를 보장하지 않는다.
  산출 수치를 바꾸지 않는다.
- **결정성:** 해당 없음

### [2026-08-25] Blind benchmark 자식 Order를 목록·RAG에서 분리

- **분류:** 구현
- **대상:** `api-server/app/services/benchmark_run_lifecycle.py`,
  `api-server/app/api/benchmarks.py`, `api-server/app/api/orders.py`,
  `workers/common/db_update.py`, `workers/preprocessing/tasks.py`,
  `frontend/src/components/BenchmarkEvaluationPanel.tsx`,
  `frontend/src/pages/OrderDetail.tsx`
- **구현 대상 설계:** `docs/insulin_blind_benchmark_manuscript_output_spec_v1_ko.md`
  Figure 1 — analysis input와 RAG/LLM/report 분리
- **사전등록 상태:** 해당 없음 (실행 게이트, 측정 상수 아님)
- **내용:** Start Blind Benchmark가 실패 run을 재사용하도록 바꿨다.
  자식 snapshot Order는 Order list에서 숨기고, 일반 Re-analysis가 RAG/LLM으로
  체인되지 않게 막는다. 자식 Order 상태는 원본 Order Benchmark 탭에 overlay한다.
- **논문에서의 용도:** 사용 안 함 (blindness 유지용 실행 게이트)
- **해석 한계:** 이미 시작된 자식 RAG 작업을 소급 취소하지 않는다.
  Phase B 캐시 키는 바꾸지 않는다. 블라인드 자식은 원본 Insulin Order의
  문헌 해석 캐시를 쓰지 않는다.
- **결정성:** 해당 없음

### [2026-08-25] Benchmark 탭에서 leftover run과 TMM 대기 상태를 구분

- **분류:** 구현
- **대상:** `api-server/app/services/benchmark_run_lifecycle.py`,
  `frontend/src/components/BenchmarkEvaluationPanel.tsx`
- **구현 대상 설계:** 해당 없음 (실행 UI, 측정 상수 아님)
- **사전등록 상태:** 해당 없음
- **내용:** Order list에서 숨긴 자식 Order는 남아 있고, Benchmark 탭은
  BenchmarkRun 이력을 보여 준다. 완료된 스냅샷은 `ready for TMM`으로 표시하고,
  취소·실패 leftover는 Previous attempts로 접는다. TMM 버튼은 자식이
  completed일 때만 켠다.
- **논문에서의 용도:** 사용 안 함
- **해석 한계:** 이전 시도 행을 삭제하지 않는다. 점수나 전처리 수치를 바꾸지 않는다.
- **결정성:** 해당 없음

### [2026-08-25] Off-contract RAG leftover를 abandoned로 고정

- **분류:** 정정
- **대상:** `api-server/app/services/benchmark_run_lifecycle.py`,
  `api-server/app/api/benchmarks.py`, `workers/watchdog/tasks.py`
- **구현 대상 설계:** 해당 없음 (실행 게이트)
- **사전등록 상태:** 해당 없음
- **내용:** 블라인드 자식이 rag_enrichment/report_generation에 있으면
  진행 중이 아니라 leftover로 보고 취소한다. 워커 재시작으로 남은 stale
  RAG는 탭에서 돌고 있는 것처럼 보이지 않는다.
- **논문에서의 용도:** 사용 안 함
- **해석 한계:** 이미 끝난 0층 산출물은 지우지 않는다.
- **결정성:** 해당 없음

### [2026-08-26] Blind TMM을 HTTP 밖으로 옮겨 524 timeout 제거

- **분류:** 정정
- **대상:** `api-server/app/api/benchmarks.py`,
  `frontend/src/components/BenchmarkEvaluationPanel.tsx`
- **구현 대상 설계:** 해당 없음 (실행 게이트)
- **사전등록 상태:** 해당 없음
- **내용:** `Run TMM + locked score`가 요청 안에서 전체 TMM을 기다려 Cloudflare 524가
  나던 경로를, 즉시 accept 후 BackgroundTask로 바꿨다. 산출 식은 동일하다.
- **논문에서의 용도:** 사용 안 함
- **해석 한계:** TMM 수치·locked score 정의를 바꾸지 않는다.
- **결정성:** 해당 없음

### [2026-08-26] Blind TMM 재시도가 화면에 반영되게 수정

- **분류:** 정정
- **대상:** `api-server/app/api/benchmarks.py`,
  `api-server/app/services/benchmark_run_lifecycle.py`,
  `frontend/src/components/BenchmarkEvaluationPanel.tsx`
- **구현 대상 설계:** 해당 없음 (실행 게이트)
- **사전등록 상태:** 해당 없음
- **내용:** `temporal_analysis` leftover를 다시 눌러도 status가 같아서 SQLAlchemy가
  UPDATE를 생략하고 UI가 그대로였다. accept 시각을 provenance에 쓰고,
  TMM은 BackgroundTask 대신 event-loop task로 시작한다.
- **논문에서의 용도:** 사용 안 함
- **해석 한계:** TMM 산출 식과 locked score 정의를 바꾸지 않는다.
- **결정성:** 해당 없음

### [2026-08-26] Figure 2 source table과 Benchmark 탭 표시

- **분류:** 구현
- **대상:** `benchmarking/figure2_source.py`, `benchmarking/result_bundle.py`,
  `benchmarking/tasks.py`, `api-server/app/api/benchmarks.py`,
  `frontend/src/components/BenchmarkFigure2.tsx`,
  `frontend/src/components/BenchmarkEvaluationPanel.tsx`
- **구현 대상 설계:** `docs/insulin_blind_benchmark_manuscript_output_spec_v1_ko.md` §2 Figure 2, §4
- **사전등록 상태:** 해당 없음 (표시 재배열, primary 점수 변경 아님)
- **내용:** locked score의 metrics/anchor_results를 Figure 2 source TSV와
  화면 패널(2A–2D)로 재배열한다. branch 비율은 표시용 unweighted count다.
- **논문에서의 용도:** methods 표시 / source-data 초안. 결과는 score 완료 후에만 채움
- **해석 한계:** bootstrap CI, partial window, kinase rank, TMM contribution,
  inhibitor contrast를 만들지 않는다. 이 그림으로 attribution 정확도를 주장하지 않는다.
- **결정성:** 해당 없음

