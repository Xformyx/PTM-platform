# Temporal Event/Order Iteration v1 — known-insulin baseline 결정 기록

**작성일:** 2026-08-28
**대상 commit:** `0ee80df` 기반 worktree
**범위:** insulin known-biology benchmark를 우선 관찰하는 additive temporal event/order 구현의 첫 iteration

## 1. 목적과 해석 경계

이번 iteration의 직접 목표는 insulin 신호전달의 known temporal biology와 플랫폼 출력이 얼마나 일치하는지 더 정밀하게 관찰하는 것이었다. 이는 unknown candidate 우선순위화보다 앞선 목표이다. 다만, locked reference의 label·expected time·anchor identity는 production 분석, Wave/TMM, Report, RAG, LLM에 전달하지 않고, truth-free artifact를 archive한 뒤 runner-only scorer가 읽는 경계는 유지한다.

`temporal_event_order.v1`은 기존 canonical Wave, TMM coefficient, kinase ranking, Dynamic Co-Wave v2 transition을 변경하지 않는다. 이 계약은 immutable static Wave member의 condition-mean protein-normalized trajectory에서 signed half-amplitude crossing (`t50`)을 추출하고, left-censoring, endpoint peak의 right-censoring, unresolved crossing을 명시한다. 따라서 **observed event descriptor**이며, site-to-site precedence, kinase activation, direct regulation, propagation, causality의 증거가 아니다.

## 2. Frozen insulin replay 결과

| 항목 | baseline | event/order v1 | 판정 |
|---|---:|---:|---|
| Canonical weighted score | 0.733333 | 0.733333 | 유지 |
| Detectable anchor recall | 1.000000 (3/3) | 1.000000 (3/3) | 유지 |
| Regulated anchor recall | 0.333333 (1/3) | 0.333333 (1/3) | 유지 |
| Direction accuracy | 1.000000 (1/1) | 1.000000 (1/1) | 유지 |
| Peak-window accuracy | 1.000000 (1/1) | 1.000000 (1/1) | 유지 |
| Kinase reference coverage | 0.466667 | 0.466667 | 유지 |
| Kinase expected timing accuracy | 0.000000 | 0.000000 | 유지 |
| Temporal layer coverage | 0.857143 | 0.857143 | 유지 |
| Static Wave members read | – | 834 | 새 coverage |
| Resolved condition-mean `t50` | – | 591/834 (0.708633) | 새 instrumentation |
| Replicate event-time CI | – | not evaluable | replicate source artifact에 없음 |

두 번의 independently assembled candidate artifact는 동일 SHA-256을 보였고, primary score input projection (`site_availability`, `site_observations`, `temporal_wave_contract`, `tmm_full_temporal`, provenance)은 baseline과 동일했다. candidate artifact에서 `Anchor_ID`, locked truth, expected temporal label, locked score configuration을 포함하는 forbidden path는 발견되지 않았으며, RAG/LLM 사용 표시는 모두 `false`였다.

> 결론적으로 `temporal_event_order.v1`은 known-insulin score를 올린 개선이 아니라, **기존 score를 훼손하지 않고 event-time의 estimability와 censoring을 드러낸 instrumentation layer**이다. 이 결과를 biological accuracy improvement로 표현해서는 안 된다.

## 3. Dynamic Co-Wave time-order 문제는 해결되지 않았다

frozen insulin artifact의 6개 timepoint 순서 720개 전체를 다시 열거했다. 기존 `transition_resolution`의 observed value는 0.751938이었고 exact random order distribution에서 `p(resolution >= observed)=0.586111`이었다. 따라서 이번 additive layer는 이 ratio를 바꾸지도 않았고, 바꾸려 시도하지도 않았다.

| Diagnostic | 결과 | 해석 |
|---|---:|---|
| Wave-membership label permutation | p=0.001996 | static Wave membership의 structural grouping 관련 결과 |
| Common time-index permutation, 500회 | p=0.570858 | chronological order support 없음 |
| Common time-index permutation, exact 720 orders | p=0.586111 | Monte Carlo fluctuation이 아닌 metric 구조의 한계 |
| `temporal_event_order.v1` | condition-mean event descriptor | ratio의 대체 p-value가 아님 |

따라서 Report/UI에서는 `transition_resolution`을 **same-static-Wave local reorganization의 descriptive metric**으로만 다뤄야 한다. temporal-order support라는 표현은 exact diagnostic이 non-significant인 현재 insulin input에서 금지한다.

## 4. 알려진 insulin biology 개선을 위해 허용/거절한 다음 조치

| 후보 조치 | 판정 | 이유 |
|---|---|---|
| Dynamic ratio threshold 조정 | 거절 | 720-order failure를 p-value tuning으로 덮는 행위이며 chronology를 측정하지 않음 |
| TMM Gaussian fallback을 known insulin expected time에 맞춰 조정 | 거절 | locked knowledge fitting이며 future data에 일반화되지 않음 |
| motif-only MAPK profile을 data-anchored로 승격 | 거절 | current frozen input의 MAPK profile은 `gaussian_fallback`, `tmm_prior_assisted`; direct evidence가 아님 |
| raw replicate가 있을 때만 `t50` bootstrap CI 산출 | 채택 | condition mean을 replicate uncertainty로 과장하지 않음 |
| observed kinase regulatory PTM의 별도 evidence channel | 보류 | sequence/isoform/species match와 curated activating/inhibitory site annotation이 모두 필요; current archived TMM input은 motif-only source뿐이므로 임의 승격 불가 |
| Trametinib factorial cohort → mirdametinib chemical holdout | 다음 confirmatory 단계 | known insulin matching 이후 실제 perturbation response 예측을 독립적으로 확인하는 경로 |

현재 locked primary denominator는 measurable anchor 3개, regulated denominator 1개로 작다. 따라서 score가 조금 변해도 안정적인 우월성 근거가 되지 않는다. score를 높이기 위해 unmeasured anchor를 규칙으로 구조하거나 candidate threshold를 benchmark label에 맞춰 조절하는 방식은 허용하지 않는다.

## 5. 반복 실행 규칙

각 revision은 다음 순서를 따른다.

1. same frozen input으로 truth-free artifact를 먼저 archive한다.
2. Wave/TMM/primary observation의 semantic hash와 Dynamic v2 acceptance ledger를 baseline과 비교한다.
3. event coverage, censoring, raw replicate CI availability, runtime, artifact determinism을 기록한다.
4. 그 뒤에만 runner-only known-insulin scorer를 실행하고, numerator·denominator를 함께 비교한다.
5. primary/secondary endpoint가 좋아져도 denominator 감소, truth injection, direct-evidence tier 승격, non-significant temporal claim이 있으면 revision을 거절한다.
6. iteration ledger에 accepted, instrumentation-only, rejected 중 하나를 기록한다. raw user data, workbook, large artifact, temporary audit script는 repository에 commit하지 않는다.

## 6. 다음 실질적 validation requirement

현재 archive에는 raw replicate values가 없으므로 event-time CI는 의도적으로 `not_evaluable_condition_mean_only`이다. 실제 strict runner input에서 `site_level_relative_quantification_normalized_phospho.tsv`가 제공되면, same timepoint within-site replicate bootstrap으로 CI를 산출하되 raw replicate values 자체는 sidecar/Report에 persist하지 않는다.

그 다음 time-order claim은 single-site `t50`로 끝내지 않고, 사전 지정된 source–target relation과 endpoint를 이용해 평가해야 한다. insulin benchmark에서는 known temporal biology endpoint를 runner-only로 비교하고, confirmatory performance은 factorial Trametinib interaction response에서 평가한 뒤 mirdametinib chemical holdout으로 고정된 method를 검증한다.
