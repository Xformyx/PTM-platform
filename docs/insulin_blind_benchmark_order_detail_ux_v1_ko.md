# Order Detail 기반 Stimulus-Blind Benchmark UX 및 서버 강제 설계 v1

## 권장 결론

**완료된 time-course Order의 상세 화면에 `Benchmark Evaluation` 버튼을 추가하고, 클릭 시 기존 Order의 원본 분석을 재사용하지 않는 별도 `BenchmarkRun` snapshot을 만드는 방식**을 권장한다. 사용자가 treatment나 biological question을 다시 입력하지 못하게 하는 것은 필요하지만, 그것만으로 충분하지 않다. 서버가 source Order의 민감 context를 읽어도 worker에는 전달하지 않고, neutral alias와 고정 generic context를 가진 새 benchmark task를 만들어야 한다.

이 방식은 기존 Order 생성·일반 분석·Report·RAG·Data-Grounded Analysis·rerun의 동작을 전혀 바꾸지 않는다. Benchmark는 Order Detail의 사후 평가 기능으로만 추가된다.

## 1. 가능한 진입 방식 비교

| 방식 | 사용자 경험 | Blind 보장 | 단점 | 권고 |
|---|---|---|---|---|
| A. Create New Order에 `Benchmark` 체크박스 추가 | 새 Order 입력 화면에서 직접 실행 | 낮음 | treatment/question을 입력하는 순간 누출 위험; 원자료 재업로드·config 재작성 필요 | 비권장 |
| B. 독립 `Create Benchmark` 메뉴 | Order와 별도 upload wizard | 중간 | 파일·sample config를 다시 입력해 실수와 중복이 늘어남; source provenance 추적이 약함 | 보류 |
| C. **Order Detail의 `Benchmark Evaluation` 버튼** | 완료된 Order에서 한 번의 snapshot 생성 | **높음** | 별도 `BenchmarkRun` 모델·worker가 필요 | **권장** |

Option C는 연구자가 원래 Order에서 정상적인 biological analysis를 수행한 뒤, 동일한 raw matrix와 time design을 보존하면서 algorithm benchmark만 독립적으로 수행할 수 있게 한다.

## 2. Order Detail UI

### 2.1 버튼 노출 규칙

`Benchmark Evaluation`은 Order Detail의 별도 **Evaluation** 영역에만 표시한다. 다음 preflight를 통과한 경우에만 활성화한다.

| Preflight | 활성화 조건 | UI 표시 |
|---|---|---|
| Order 상태 | `completed` | 완료된 Order만 평가 가능 |
| 시간 구조 | `single_time_point=false`, numeric timepoint 3개 이상 | 시간축 부족 시 비활성 이유 표시 |
| Source files | PR/PG matrix와 sample configuration 존재 | 누락 파일·sample config를 안내 |
| Reference | selected species FASTA가 resolution 가능 | Rat_hir는 custom FASTA provenance 확인 |
| 권한 | owner/admin 또는 명시적 benchmark 실행 권한 | read-only 공유자는 결과만 열람 |
| Protocol | 서버에 활성화된 benchmark manifest 존재 | 사용자 임의 truth 업로드 금지 |

Preflight는 source Order의 treatment, biological question, RAG collection을 benchmark panel의 request payload 또는 progress detail에 보여주지 않는다.

### 2.2 `Create blinded benchmark snapshot` modal

사용자가 버튼을 누르면 일반 Order form이 아니라 **정보 입력을 최소화한 잠금 modal**을 연다.

| 표시/입력 요소 | 정책 | 이유 |
|---|---|---|
| Source data summary | PTM type, species, timepoint 수, replicate 구조, file checksum만 표시 | 분석 적격성을 확인하되 biological identity를 재전달하지 않음 |
| Benchmark protocol | 서버 등록 `Insulin signaling benchmark v1` 같은 protocol만 선택 | truth·metric·time window를 사용자 입력에서 분리 |
| Primary mode | 기본값 `Strict blind primary`; 수정 불가 | 논문용 주 score를 사전등록 정책으로 고정 |
| Generic question preview | 고정 문장만 읽기 전용 표시 | 사용자의 question 유입 방지 |
| RAG policy | `No RAG` 또는 manifest-defined strict allowlist; 읽기 전용 | insulin-specific literature 누출 방지 |
| Run label | 선택적으로 `Benchmark run 01` 같은 비생물학적 label만 허용 | 식별 편의; worker에는 전달하지 않음 |
| 잠금 확인 | “입력·context·threshold가 snapshot 이후 변경되지 않음” 확인 checkbox | post-hoc tuning 방지 |
| 시작 버튼 | `Lock snapshot and start blind analysis` | immutable run 생성 |

다음 입력은 modal에서 **표시하지도, 수정하지도, worker에 전달하지도 않는다**: treatment, cell type, biological question, special conditions, user research questions, original project/order name, original filename, active RAG collection, external Co-Scientist goal, LLM 자유 선택, threshold 자유 조정.

### 2.3 사용자에게 보이는 실행 단계

```text
1. Eligibility check
2. Snapshot & context masking
3. Blind analysis (Wave / TMM / directionality / divergence)
4. Blind artifact archive
5. Locked scoring
6. Paper figures and source-data bundle ready
```

진행 화면은 `Treatment A`, `Benchmark run <ID>`와 같은 neutral label만 사용한다. “correct INSR anchor”, “expected AKT window” 같은 truth-derived 단어는 단계 5가 완료되기 전에는 UI/API에 나타나지 않는다.

## 3. Benchmark result 화면

result는 원래 Order Report tab을 대체하지 않고 `Evaluation → Benchmark runs` 안에 별도 tab으로 보인다.

| Tab | 내용 | 수정 가능 여부 |
|---|---|---|
| Run summary | protocol, snapshot hash, code/model version, blind policy, timestamps | 읽기 전용 |
| Locked score | Tier 1/2 component/branch metric, CI, error taxonomy | 읽기 전용 |
| Figures | main/supplementary graph, SVG/PDF/PNG download | 읽기 전용 |
| Source data | TSV/JSON table, figure manifest, mapping audit | 읽기 전용 |
| Blind artifact | generic-context report, wave/TMM/directionality outputs | 읽기 전용 |
| Post-score interpretation | truth reveal 후의 비교 해석 | 별도 note만 가능; score 수정 불가 |

동일 source Order를 다시 benchmark하려면 existing run을 수정하지 않는다. 새 `BenchmarkRun`을 만들고 protocol version, code/model version 또는 사전등록된 algorithm variant를 명시한다. 이는 figure와 논문 결과의 재현성을 보장한다.

## 4. Secondary mode는 primary 이후에만 노출

primary run은 평가의 기준점이다. 아래 run type은 primary run이 archive된 후에만 선택할 수 있으며, primary score와 합산하지 않는다.

| Run type | 목적 | Context 정책 | 결과 위치 |
|---|---|---|---|
| `strict_primary` | 알고리즘 blind recovery의 주 평가 | generic context, no user RQ, no RAG 또는 strict manifest policy | 논문 주 score |
| `literature_assisted` | 문헌 보강이 data-grounded narrative에 주는 추가 가치 | fixed collection allowlist, generic question 유지 | 별도 narrative comparison |
| `perturbation_validation` | inhibitor 조건의 branch-selective attenuation 확인 | inhibitor condition metadata 허용 | 별도 validation appendix |

`literature_assisted`와 `perturbation_validation`의 score나 figure가 `strict_primary`의 canonical performance를 덮어쓰지 않도록 UI에서 색상·badge·export folder를 구분한다.

## 5. Cell context: 보존하되 cell-line identity는 마스킹

Cell context를 완전히 제거하는 것은 권장하지 않는다. Cell lineage는 cancer-specific false positive를 줄이고, lineage에 맞지 않는 receptor·pathway·문헌 근거를 제한하는 데 필요한 분석 정보다. 반면 `HIRc-B`, `INSR-overexpressing`, disease-model 이름처럼 cell-line 명칭에 transgene 또는 stimulus를 암시하는 단서가 있으면 primary blind run의 stimulus/question blindness를 약화한다.

따라서 `strict_primary`에서는 source Order의 자유 텍스트 cell type을 직접 전달하지 않고, server-side sanitizer가 lineage-level alias만 전달한다.

| Context 수준 | 예시 | Strict primary | Literature-assisted / 일반 Order |
|---|---|---|---|
| Lineage class | `cultured fibroblast-like cell`, `epithelial-like cell`, `myeloid-like cell` | 보존 | 보존 |
| Sample setting | `in vitro cultured cells`, `primary tissue`, `organoid` | 보존 | 보존 |
| Exact cell-line name | `HIRc-B`, `MCF-7`, `A549` | 차단 또는 neutral alias | 원문 허용 |
| Transgene/engineering | `human INSR overexpression`, knock-in, reporter | 차단 | 원문 허용 |
| Disease/oncology label | `breast cancer`, `glioblastoma`, insulin-resistant model | 차단 | 원문 허용 |
| Species analysis context | `rat` | 보존 | 보존 |
| Custom FASTA provenance | Rat_hir 및 human INSR entry | 분석 engine 내부에는 유지, LLM/RAG context에는 차단 | 원문 허용 |

예를 들어 source Order의 cell type이 `HIRc-B (human INSR-overexpressing rat fibroblast)`라면 strict primary worker에는 `cultured fibroblast-like cells`만 제공한다. `rat_hir` label도 LLM/RAG에는 전달하지 않고 analysis species `rat`만 전달한다. Human INSR가 실제로 관측된 PTM/protein data에 존재하는 사실은 데이터 관찰로서 유지된다. 따라서 이 benchmark는 데이터 자체에서 보이는 단서를 지우는 것이 아니라, **사용자 입력·cell-line 명칭·transgene annotation이 제공하는 추가 prior를 차단하는 평가**로 기술한다.

Cell context의 영향을 투명하게 보이기 위해 다음 세 run을 구분한다.

| Run | Cell context 정책 | 목적 |
|---|---|---|
| `strict_primary_lineage` | lineage class만 허용 | 논문용 primary blind score |
| `no_cell_context_sensitivity` | cell context 전부 제거 | lineage context가 specificity에 주는 영향을 측정 |
| `literature_assisted_full_context` | exact cell line·model·allowlisted literature 허용 | 실제 연구 해석에서의 지원 효과를 별도로 평가 |

Primary score는 `strict_primary_lineage`만 사용한다. No-cell sensitivity와 full-context run은 성능을 부풀리기 위한 것이 아니라, lineage 정보의 이득과 identity prior의 영향을 분해하는 supplementary analysis로 보고한다.

## 6. 서버 강제 정책

### 6.1 별도 데이터 모델

일반 `Order`는 변경하지 않는다. 새 `BenchmarkRun`은 최소한 아래를 보존한다.

```text
BenchmarkRun
  id, source_order_id, protocol_id, protocol_version, run_type, status
  source_input_hash, source_order_snapshot_hash, sanitized_context_hash
  analysis_commit, scorer_commit, model_policy, rag_policy
  blinded_artifact_uri, score_bundle_uri, truth_reveal_at
  created_by, created_at, locked_at, completed_at
```

`source_order_snapshot_hash`는 source PR/PG matrix, sample configuration, FASTA, PTM type, species, numeric timepoints, replicate relation을 가리킨다. 반면 `sanitized_context_hash`는 actual treatment·question이 제거된 worker input을 가리킨다.

### 6.2 Server-side BlindContextBuilder

Frontend가 입력을 숨겨도 API를 직접 호출하면 우회할 수 있다. 따라서 API는 source Order context를 그대로 전달하지 않고, 서버에서 아래의 benchmark config를 새로 만들어야 한다.

```json
{
  "blind_mode": true,
  "experimental_context": {
    "ptm_type": "phosphorylation",
    "species": "rat_hir",
    "time_points": [0, 1, 5, 15, 30, 60, 180],
    "condition_aliases": {"Control": "Control", "original_treated_1": "Treatment A 1 min"},
    "generic_question": "Identify reproducible temporal PTM programs and candidate kinase activities from this treatment-versus-control time course."
  },
  "research_questions": [],
  "rag_policy": "disabled",
  "treatment_context_enabled": false,
  "external_coscientist_enabled": false,
  "truth_access": "scorer_only"
}
```

실제 field 명칭은 구현 시 정하되, 핵심은 **frontend가 보내는 treatment/question/collection을 무시하고 API가 whitelist 기반 context를 생성한다**는 점이다. 허용되지 않은 context key가 들어오면 request를 거절하고 audit log에 key name만 기록한다.

### 6.3 재분석 원칙

기존 source Order의 preprocessing/RAG/report artifact는 이미 context 영향을 받았을 수 있으므로 benchmark에서 재사용하지 않는다. Source input snapshot에서 별도의 benchmark workspace로 preprocessing부터 다시 실행한다. Raw matrix header 또는 config filename에 insulin/HIRc-B가 들어 있으면 temp workspace에서 neutral alias로 변환한다. Numeric timepoint·control/treatment 관계·replicate relation은 보존한다.

Receptor inference의 treatment-context source, context-based collection selection, LLM context tagger, external Co-Scientist, user research questions는 `strict_primary`에서 비활성화한다. TMM, wave, minute lag, bootstrap, threshold stability, multisite divergence처럼 data matrix와 time design에만 의존하는 분석은 활성화한다.

### 6.4 Locked scoring과 truth reveal

`benchmark_locked/` truth는 scorer process만 읽을 수 있어야 한다. Analysis/RAG/LLM worker에는 import path·filesystem mount·object-storage credential을 제공하지 않는다. Blind artifact hash가 기록된 뒤 scorer를 실행하고, score bundle이 생성될 때만 `truth_reveal_at`을 기록한다.

## 7. 구현 순서

| 단계 | 구현 범위 | 기존 Order에 대한 영향 |
|---|---|---|
| P0 | `BenchmarkRun` schema, preflight API, Order Detail 버튼과 read-only modal | 없음 |
| P1 | BlindContextBuilder, sanitized workspace, source input snapshot, worker denylist | 없음; benchmark task만 신규 |
| P2 | locked scorer, score/figure bundle, immutable export | 없음 |
| P3 | strict/literature-assisted/perturbation run type 및 result tab | 없음; 기존 Report와 분리 |

## 8. 사용자 경험 요약

사용자는 새 Order를 만들 때 기존처럼 실제 treatment와 research question을 입력해 정상적인 생물학적 분석을 한다. Benchmark가 필요한 경우에만 완료된 Order에서 **한 번의 `Benchmark Evaluation` 클릭**으로 locked modal을 열고, 입력 없이 strict primary snapshot을 시작한다. 이 설계가 원자료 재업로드 부담은 없애면서도 실제 stimulus-blind·question-blind 평가를 보장하는 가장 안전한 방식이다.
