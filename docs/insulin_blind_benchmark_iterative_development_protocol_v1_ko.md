# Insulin Blind Benchmark: 반복 개선·과적합 방지·논문용 검증 프로토콜 v1

## 결론

**Benchmark 결과를 검토하고, 오류 원인을 분석하고, 알고리즘을 개선한 뒤 다시 benchmark를 실행하는 반복 과정은 논문에 매우 도움이 된다.** PTM-platform의 방법론적 기여를 “정답을 맞힌 한 번의 분석”이 아니라, time-course data의 실패 양상을 구조화해 개선하고 그 개선을 정량적으로 검증한 evidence chain으로 보여줄 수 있기 때문이다.

다만 같은 insulin benchmark 전체를 반복해서 보고 수정하면 그 dataset의 anchor, branch, time window에 과적합될 위험이 있다. 그러므로 반복 자체를 금지할 것이 아니라, **개발용 feedback loop와 최종 검증용 hold-out을 분리**해야 한다.

> 논문에서 방어할 수 있는 주장은 “insulin truth를 보고 규칙을 맞췄다”가 아니라, “사전 정의된 오류 분류로 일반적 evidence layer를 개선했고, frozen internal test 및 독립 stimulus/dataset에서도 개선이 유지되었다”이다.

## 1. 반복 개선이 학술적으로 주는 가치

| 반복 단계 | 과학적 산출물 | 논문 기여 |
|---|---|---|
| Blind baseline | 어떤 anchor/branch/time window가 회복·누락되는지 | 초기 방법의 정량적 한계 제시 |
| Error review | acquisition, mapping, protein normalization, TMM ambiguity, temporal stability, narrative error 분류 | 실패 원인을 생물학적·기술적 오류와 분리 |
| One-layer improvement | Wave, TMM, directionality, multisite gate, report guardrail 중 하나를 변경 | 개선의 기전과 범위를 설명 |
| Version re-evaluation | 동일 scorer·동일 manifest에서 paired metric 비교 | 개선이 우연이 아닌지 정량화 |
| Final validation | hold-out branch 또는 별도 stimulus/dataset에서 freeze된 version 평가 | insulin-specific fitting이 아님을 검증 |

이 과정은 특히 PTM-platform처럼 co-wave, TMM, temporal precedence, multisite divergence, data-grounded report라는 여러 evidence layer를 갖는 시스템에 적합하다. 각 개선은 “정확도를 높였다”가 아니라, 예를 들어 “sparse profile을 높은 confidence로 과대해석하던 오류를 줄였다”처럼 **오류 범주와 연결된 일반화 가능한 변경**으로 기록해야 한다.

## 2. 권장 데이터 분할

가장 강한 설계는 insulin time-course를 개발 자료로 사용하고, 별도 stimulus 또는 독립 time-course dataset을 최종 검증으로 사용하는 것이다. 독립 자료가 아직 준비되지 않았다면 insulin workbook 내부에서도 최소한 access level을 나누어야 한다.

| 층 | 접근 시점 | 사용 목적 | 수정 허용 여부 |
|---|---|---|---|
| Development subset | 최초부터 공개 | error taxonomy, hypothesis, algorithm design, version iteration | 허용 |
| Frozen internal test | version 후보가 정의된 뒤 공개 | candidate version 비교의 내부 확인 | 선택 이후 수정 금지 |
| External final validation | algorithm freeze 뒤 공개 | 별도 stimulus/dataset 또는 inhibitor perturbation의 일반화·선택성 검증 | 수정 금지 |

### 2.1 Insulin workbook 내부 분할

동일 workbook을 사용할 경우, split은 random anchor split보다 **생물학적으로 관련된 unit이 함께 누출되지 않도록** 해야 한다. 예를 들어 같은 protein의 multi-site pair, 동일 kinase module, 강하게 연결된 branch chain이 development와 test에 함께 들어가면 test의 독립성이 약해진다.

| 권장 split 단위 | 이유 | 주의점 |
|---|---|---|
| Branch/module block | PI3K–AKT, RAS–ERK, mTORC1 등 관련 anchor가 함께 누출되는 것을 감소 | branch 수가 적으므로 불확실성이 큼 |
| Protein/family block | 같은 protein의 multiple phosphosite와 isoform을 함께 보관 | 단일 branch 지표가 불안정할 수 있음 |
| Time-window block | early/late recovery 일반화 확인 | 같은 site trajectory를 완전히 분리하기 어려움 |

내부 split만으로는 충분하지 않다. 논문의 최종 generalization claim은 별도 stimulus, 다른 cell context, 또는 독립 perturbation dataset을 이용해 보강한다. Inhibitor data는 primary blind discovery의 입력은 아니지만, freeze된 model의 target-branch selective attenuation을 확인하는 외부 검증으로 사용할 수 있다.

## 3. Version ladder와 변경 요청

각 개선 전에는 `ChangeRequest`를 작성한다. 이 기록은 benchmark truth 자체를 보는 것이 아니라 error audit에서 발견된 **일반적인 분석 결함**에 근거해야 한다.

| 필드 | 내용 |
|---|---|
| `change_id` | 예: `CR-004` |
| Base version | 변경 전 code/manifest/scorer commit |
| Triggering error category | mapping, detectability, TMM ambiguity, sparse confidence, temporal stability 등 |
| Root-cause evidence | 관련 anchor ID가 아니라 일반적인 error pattern과 artifact reference |
| Proposed change | 한 evidence layer에 국한된 변경 설명 |
| Predeclared expected effect | 어떤 primary/secondary metric이 왜 변할 것으로 예상되는지 |
| Guardrails | 악화되면 안 되는 branch/negative-control/safety metric |
| Evaluation split | development 또는 frozen test 여부 |
| Decision | accept, reject, defer와 근거 |

권장 version ladder는 다음과 같다.

```text
V0  Current baseline
V1  Canonical Temporal Wave + stability evidence
V2  V1 + TMM fractional multi-kinase attribution
V3  V2 + minute onset/peak lag + D0–D3 directionality
V4  V3 + multisite divergence evidence gate
V5  V4 + Data-Grounded/Report evidence-aware guardrail
```

Version 하나에는 하나의 핵심 변경만 넣는다. 여러 변경을 한꺼번에 추가하면 성능 변화의 원인을 설명할 수 없다. 변경이 필요해도 insulin-specific gene, site, exact window, target kinase를 코드에 직접 넣는 것은 금지한다. Dataset-specific information은 locked scorer·manifest에만 존재해야 한다.

## 4. 각 version의 판정 규칙

| 판정 영역 | Primary criterion | 안전성 criterion |
|---|---|---|
| Anchor recovery | evidence-weighted component score 또는 사전등록 component metric의 paired bootstrap Δ와 95% CI | measurable denominator와 Tier rule 불변 |
| Branch balance | macro-average 및 branch별 component score | 핵심 branch의 material decline 없음 |
| Temporal validity | peak-window accuracy, D-tier stability, time-permutation empirical p | exact-minute fitting으로 window score를 부당하게 올리지 않음 |
| Kinase attribution | Top-k recovery, reciprocal rank, TMM confidence | sparse fallback 또는 high residual 결과를 high-confidence로 승격하지 않음 |
| Specificity | negative-control/stress-module activation rate | false positive receptor/kinase module 증가 없음 |
| Narrative safety | claim ledger의 evidence-linked 문장 비율 | causal wording 또는 unsupported literature claim 증가 없음 |

Algorithm change는 development subset에서 primary criterion을 개선하고 safety criterion을 해치지 않을 때만 candidate로 승격한다. Candidate가 정해지면 frozen internal test를 한 번 평가한다. Test 결과를 본 뒤 새 변경이 필요하면, 그것은 새 development cycle로 기록하고 기존 test를 “final test”로 계속 사용하지 않는다.

## 5. 반복 개선의 실행 흐름

```text
Pre-register metric, split, stop rule, scorer hash
        ↓
V0 strict-blind development run
        ↓
Error taxonomy review (no direct insulin-specific hardcoding)
        ↓
ChangeRequest + one-layer implementation
        ↓
V(n+1) development re-run with identical scorer
        ↓
Paired comparison + branch/negative-control safety gate
        ↓
Candidate freeze
        ↓
One-time frozen internal test
        ↓
Final algorithm freeze
        ↓
External stimulus/dataset or perturbation validation
```

Stop rule도 사전등록한다. 예를 들어 “각 evidence layer에서 허용되는 ChangeRequest는 root-cause가 해소될 때까지로 제한하고, frozen internal test는 candidate freeze 후 한 번만 본다”와 같이 정한다. 목표 score를 보며 무한히 threshold를 조정하는 방식은 피한다.

## 6. 논문에서 제시할 그림과 표

| 결과물 | 내용 | 목적 |
|---|---|---|
| Main Fig. 5A | V0–V5의 paired Δmetric과 bootstrap CI | 어떤 evidence layer가 어떤 개선을 만들었는지 제시 |
| Main Fig. 5B | observed score 대 time-permutation null | temporal information이 우연한 ordering이 아님을 제시 |
| Main Fig. 5C | version별 error taxonomy | 단순 score 상승이 아니라 실패 범주 감소를 제시 |
| Supplementary table | 모든 ChangeRequest, commit, split, decision, metric, guardrail | 개발 과정의 투명성 |
| Supplementary figure | branch별 safety metric 및 negative control | 한 branch만 좋아진 trade-off 방지 |
| Final validation figure | frozen internal test와 external dataset/inhibitor 결과 | 일반화와 perturbation-supported support 제시 |

Methods에는 “All development iterations were recorded prospectively in a version ledger; each iteration modified one pre-specified evidence layer and was evaluated with a fixed scorer. The final frozen model was evaluated once on held-out data.”와 같은 구조로 기재할 수 있다. 실제 적용 시에는 기록된 사실만 서술한다.

## 7. LLM/사용자 피드백의 안전한 역할

사용자가 benchmark bundle을 제공하고 AI가 개선 후보를 제안하는 것은 괜찮다. 다만 AI는 다음 역할로 제한한다.

| 허용되는 역할 | 금지되는 역할 |
|---|---|
| error taxonomy 요약, failure cluster 탐색, code path 점검, 일반적인 개선 가설 제안 | insulin anchor·gene·time window·expected kinase를 코드 규칙으로 하드코딩 |
| ChangeRequest 초안과 guardrail 제안 | frozen test 결과를 본 뒤 test에 맞추어 threshold를 반복 조정 |
| data/ChromaDB에 근거한 narrative guardrail 점검 | benchmark truth를 LLM report/RAG prompt에 주입 |

AI의 제안과 사용자의 의사결정은 모두 `ChangeRequest`에 기록한다. 이렇게 하면 반복은 숨겨야 할 tuning이 아니라, 재현 가능한 algorithm-development history가 된다.

## 8. 이 연구에서의 권장 주장 범위

논문은 다음처럼 단계적으로 주장하는 것이 적절하다.

1. PTM-platform은 stimulus/question-blind 조건에서 measurable Tier 1/2 anchor, temporal window 및 branch coherence를 정량적으로 평가할 수 있다.
2. Error taxonomy에 의해 유도된 TMM·temporal wave·directionality·multisite evidence 개선은 development split에서 미리 정의한 metric을 개선한다.
3. Freeze된 version은 internal hold-out과 독립 stimulus/dataset 또는 inhibitor validation에서 성능/선택성을 유지한다.
4. Perturbation은 discovery를 사전제약하지 않고, analysis 종료 후 제안된 target branch의 validation evidence를 제공한다.

동일 insulin benchmark의 반복 평가만으로 “범용적으로 우수하다”고 주장해서는 안 된다. 그러나 version ledger, internal freeze, external validation을 갖추면, 반복은 방법론 논문에서 강력한 개선·재현성 증거가 된다.
