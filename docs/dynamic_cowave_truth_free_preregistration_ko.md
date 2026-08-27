# Dynamic Co-Wave Transition: Truth-Free Preregistration

## Question

Static canonical Wave membership은 유지한 채, adjacent temporal window에서 관찰되는 co-activity의 persistence, split, merge, recruitment, exit를 additive annotation으로 기록할 때 temporal specificity가 재현성 있게 향상되는지 평가한다.

## Blind Boundary

Candidate selection 및 execution은 protein-normalized PTM numerical trajectories, ordered numeric time axis, replicate structure, static Wave membership, TMM numerical output, and PG numerical protein trajectories만 사용한다. Workbook truth, anchor IDs, expected kinase labels, stimulus identity, biological question, RAG, LLM, literature, report context는 입력에서 제외한다.

## Frozen Candidate Input List

아래 세 입력은 evaluation 전에 고정한 전체 목록이며 추가 후보는 실행 중 생성하지 않는다.

| Trial ID | Activity threshold (absolute relative log2FC) | Minimum observed points | Static membership use | LOTO |
|---|---:|---:|---|---|
| `dynamic_cowave_activity_040` | 0.40 | 4 | Retained canonical Wave members only | Leave one timepoint out |
| `dynamic_cowave_activity_050` | 0.50 | 4 | Retained canonical Wave members only | Leave one timepoint out |
| `dynamic_cowave_activity_060` | 0.60 | 4 | Retained canonical Wave members only | Leave one timepoint out |

Each local window is an observed interval between adjacent ordered timepoints. A pair is locally co-active only when both sites exceed the threshold at the window end with the same sign. The output labels observed membership state transitions and contains no causal arrows.

All transition counts and LOTO metrics use complete event sets internally. To keep ordinary production and benchmark artifacts operationally safe, serialized output is limited to 500 deterministic pair-transition examples, 500 site-transition examples, and 250 membership examples plus complete per-Wave counts. This is an engineering payload constraint, not a candidate-selection parameter and does not depend on truth or biological labels.

## Metrics

| Metric | Definition | Direction |
|---|---|---|
| Local active-pair coverage | Fraction of static same-Wave pair-window opportunities that are locally same-sign active | Higher, subject to guardrails |
| Transition resolution | Fraction of active pair transitions that are split, merge, recruitment, or exit rather than persistence | Nonzero, below saturation |
| LOTO transition Jaccard | Mean Jaccard overlap of comparable adjacent-window transition identities after one timepoint is removed | Higher |
| LOTO site-transition Jaccard | Mean Jaccard overlap for site-level transition identities | Higher |
| Transition-supported Wave fraction | Fraction of retained static Waves with at least one stable local transition | Higher |
| Cross-layer temporal alignment | Fraction of retained PTM→protein observational edges whose source Wave contains stable transition evidence before target protein peak | Descriptive, no causal interpretation |

## Candidate Selection Objective

For an eligible candidate, maximize:

`0.45 × mean_pair_LOTO_Jaccard + 0.25 × mean_site_LOTO_Jaccard + 0.20 × local_active_pair_coverage + 0.10 × transition_resolution`.

No metric uses workbook truth. Undefined LOTO metric renders a candidate ineligible rather than imputing zero or selecting it.

## Adoption Gate

The selected candidate is adopted only as an additive annotation when all conditions hold:

| Gate | Requirement |
|---|---|
| Static invariance | Canonical Wave membership and TMM outputs remain byte-for-byte unchanged in the shadow artifact comparison |
| Pair LOTO stability | Mean comparable-pair Jaccard ≥ 0.50 |
| Site LOTO stability | Mean comparable-site Jaccard ≥ 0.50 |
| Local coverage | Active-pair coverage ≥ 0.10 |
| Nontrivial resolution | Transition resolution > 0 and < 0.95 |
| Stable support | At least one retained canonical Wave has a stable transition |
| Cross-layer boundary | Cross-layer alignment is descriptive only; it cannot promote causality or alter primary scoring |
| Noninferiority | Primary score and existing artifact/figure source semantics remain unchanged |

Failure of any gate means that dynamic transition output is retained, if at all, as experimental diagnostic metadata and not enabled in the shared production/benchmark default contract.
