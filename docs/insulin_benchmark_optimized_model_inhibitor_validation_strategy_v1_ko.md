# Insulin Benchmark 최적화와 동일 Time-course Inhibitor 검증: 논문 전략 v1

## 권장 결론

**가능하며, 이 연구 목적에는 매우 강한 전략이다.** Insulin benchmark에 대해 PTM-platform의 evidence layer를 반복 개선하여 최적화한 뒤, 그 **동결된 최종 모델**을 동일 세포·동일 time grid의 inhibitor perturbation 자료에 적용하면 다음 두 질문을 분리해 답할 수 있다.

1. 최적화된 알고리즘이 canonical insulin temporal signaling을 얼마나 잘 복원하는가?
2. 그 알고리즘이 실제 kinase perturbation에서 target branch의 선택적 약화·지연·재배선을 검출하는가?

첫 질문은 **reference-conditioned development performance**이고, 둘째 질문은 **independent perturbation-supported validation**이다. Inhibitor 자료는 baseline insulin benchmark의 tuning에 사용하지 않고, final model freeze 뒤 한 번의 독립 validation으로 사용해야 한다.

## 1. 증거 역할의 분리

| 단계 | 입력 | 모델 상태 | 목적 | 논문 표현 |
|---|---|---|---|---|
| A. Benchmark optimization | Insulin time-course + locked canonical workbook | 반복 개선 허용 | algorithm evidence layer 최적화 | development/optimization performance |
| B. Model freeze | version ledger·guardrail·scorer hash | 변경 금지 | 최종 version 확정 | frozen analysis specification |
| C. Perturbation validation | vehicle, insulin, inhibitor, insulin+inhibitor time-course | B의 모델을 그대로 적용 | target branch의 perturbation-consistent 변화 검증 | independent perturbation validation |
| D. Optional external generalization | 다른 stimulus 또는 다른 cell context | B의 모델을 그대로 적용 | stimulus 일반화 검증 | external generalization |

동일 insulin benchmark에 최대한 적합화하는 것은 허용된다. 단, 그 성능을 “blind benchmark에서 최적화된 개발 성능”으로 정직하게 기록한다. Inhibitor time-course에서 좋은 결과가 나온다면, 이는 단순 reference match를 넘어서 model의 branch-level perturbation sensitivity와 selectivity를 지지한다.

> 같은 cell system과 time grid를 쓰는 inhibitor 자료는 완전히 다른 biological domain에서의 일반화 검증은 아니다. 그러나 동일 acquisition·species·time design의 장점을 이용해, platform이 **예측한 branch가 실제 perturbation에 반응하는지**를 더 낮은 기술적 교란 속에서 검증하는 강한 실험적 독립성이다.

## 2. 필수 동결 규칙

Inhibitor 자료를 확인하기 전에 아래 항목을 immutable release record로 고정한다.

| 동결 대상 | 기록 내용 |
|---|---|
| Algorithm | code commit, package lock, Temporal Wave/TMM/directionality/divergence version |
| Benchmark protocol | workbook hash, scorer version, detectable rule, Tier rule, time-window rule |
| Analysis policy | strict blind context, lineage policy, RAG policy, report evidence guardrail |
| Selection rule | inhibitor target 및 target branch를 선택한 기준 |
| Endpoints | target activity/rank, TMM contribution, target wave, downstream directionality, branch selectivity |
| Statistics | replicate rule, protein normalization, interaction contrast, CI/FDR procedure |
| Stop rule | inhibitor result을 본 뒤 algorithm/threshold를 수정하지 않음 |

Inhibitor 결과를 본 뒤 algorithm을 다시 고치면 그 결과는 새로운 development cycle이 된다. 그 경우 기존 inhibitor dataset은 더 이상 final validation으로 부를 수 없고, 다음 독립 perturbation 또는 stimulus dataset이 필요하다.

## 3. 동일 time-course perturbation 설계

가능하면 다음 2×2 condition을 동일한 time grid와 biological replicate 구조로 수집한다.

```text
vehicle
insulin
inhibitor only
insulin + inhibitor
```

각 condition은 baseline insulin run과 같은 PTM/protein quantification·Rat_hir reference·sample mapping·QC·protein normalization contract를 사용한다. Early target branch를 평가하려면 1–15분 구간이 유지되어야 하며, late output 또는 feedback을 평가하려면 30–180분 구간도 보존한다.

### 3.1 핵심 interaction contrast

각 phosphosite, Wave, kinase activity score 및 branch summary에서 inhibitor-specific insulin effect를 계산한다.

```text
Δ_inhibitor-insulin
= (insulin + inhibitor − inhibitor only)
− (insulin only − vehicle)
```

이 contrast는 inhibitor-only의 비특이적 변화와 insulin의 기본 반응을 분리한다. PTM 분석에서는 가능한 경우 protein-normalized log2FC를 사용한다. Inhibitory regulatory site는 phosphorylation sign과 kinase activity sign을 구분한 뒤 해석한다.

## 4. 사전등록할 endpoint

성공은 “모든 PTM이 사라지는가”가 아니다. 올바른 endpoint는 **model이 예측한 target branch에서 선택적 perturbation signature가 나타나는가**이다.

| Endpoint | 정량 정의 | 기대 신호 | 해석 경계 |
|---|---|---|---|
| Target kinase activity/rank | insulin 대비 `Δ_inhibitor-insulin` 및 rank shift | target kinase/module score 감소 | score는 attribution이지 direct activity assay가 아님 |
| TMM contribution | target kinase의 shared-site fractional contribution 차이 | target contribution 감소 또는 재분배 | shared substrate는 다른 kinase의 기여를 가질 수 있음 |
| Target Wave | amplitude, AUC, onset, peak, persistence의 interaction effect | amplitude 감소, onset 지연, persistence 소실 중 하나 | 모든 member가 같은 방향일 필요 없음 |
| Directionality | downstream edge의 D-tier·lag·similarity 변화 | D2/D3→weaker/unresolved 또는 lag 증가 | time precedence는 causal proof가 아님 |
| Branch selectivity | target branch effect 대 non-target branch effect의 차이 | target branch가 더 큰 attenuation | broad toxicity/coverage loss와 구분 필요 |
| Negative-control module | stable/irrelevant module의 effect | 불필요한 전역 소실 없음 | context-dependent exception은 사전등록 |

Target branch는 baseline blind run의 결과와 사전등록 selection rule에 의해 결정한다. 예를 들어 “D2 이상, TMM high-confidence, Tier 1/2 anchor support, two ordered layers, negative-control contradiction 없음” 같은 일반 rule을 사용한다. 특정 insulin anchor에 맞춘 규칙을 새로 만들지 않는다.

## 5. 논문 Figure 구성

| Figure panel | 비교 | 핵심 메시지 |
|---|---|---|
| Fig. 2–4 | optimized final model의 insulin benchmark score·TMM·cascade | canonical time-course를 정량적으로 복원한 development performance |
| Fig. 5A | V0→final version paired metric 및 error taxonomy | 어떤 evidence-layer 개선이 성능 변화에 기여했는지 |
| Fig. 5B | model freeze card | commit, manifest/scorer hash, predeclared endpoints·target selection rule |
| Fig. 5C | target kinase/module interaction forest plot | target activity/rank 및 TMM contribution의 perturbation-consistent 변화 |
| Fig. 5D | 4-condition target Wave time-course | vehicle/insulin/inhibitor/insulin+inhibitor의 dynamics 차이 |
| Fig. 5E | branch-selectivity heatmap | target branch attenuation과 non-target branch 보존/교차반응 분리 |
| Supplementary | replicate points, protein-normalization, inhibitor-only effect, target engagement, all endpoints | 결과의 재현성·특이성·한계 공개 |

Figure 5B의 freeze card는 작지만 중요하다. 독자가 inhibitor experiment를 보기 전에 algorithm이 고정되었음을 확인할 수 있게 한다.

## 6. 통계·QC 원칙

| 항목 | 권장 원칙 |
|---|---|
| Replicate | biological replicate를 analysis unit으로 유지하고, site/wave의 group summary만으로 n을 과장하지 않음 |
| Interaction estimate | 위의 2×2 contrast를 replicate 수준에서 계산하거나 model에 interaction term을 포함 |
| Uncertainty | endpoint별 effect size와 95% CI; 다수 site/edge family는 BH FDR를 source data에 기록 |
| Protein abundance | PTM raw change와 protein-normalized change를 분리 표시 |
| Missing/de novo | arbitrary FC imputation 금지; detection count, first detection, persistence를 별도 표기 |
| Inhibitor-only effect | vehicle 대비 inhibitor-only trajectory를 반드시 표시 |
| Run consistency | 동일 FASTA, timepoint parser, threshold config, report/scorer version 사용 |

## 7. 최종 주장 범위

다음과 같이 쓰는 것이 정확하다.

> “The final algorithm was optimized against a preregistered insulin temporal benchmark, frozen before perturbation analysis, and then tested on an independent inhibitor-treated time course. The inhibitor interaction selectively attenuated the predicted target branch while preserving or distinctly modulating non-target modules.”

반대로 피해야 할 표현은 “inhibitor 결과가 insulin benchmark에서의 모든 최적화가 범용적으로 옳음을 증명했다”이다. Perturbation 결과는 선택된 target branch·세포계·시간 grid·inhibitor 조건에서의 external validation이며, 다른 stimulus와 cell context로의 일반화는 별도 dataset이 필요하다.

## 8. 이 전략의 장점

1. Insulin은 canonical, time-resolved benchmark로서 algorithm을 적극적으로 다듬는 개발 자산이 된다.
2. Inhibitor는 discovery를 사전제약하지 않고, freeze 후에만 들어오므로 unbiased discovery 원칙을 보존한다.
3. 동일 time-course design은 technical confounding을 줄여 kinetic endpoint를 강하게 비교하게 한다.
4. TMM contribution, Wave, D-tier, branch selectivity가 같은 perturbation contrast에서 함께 움직이는지 보여줄 수 있다.
5. 논문은 “reference recovery”와 “functional perturbation consistency”를 결합한 더 설득력 있는 구조가 된다.
