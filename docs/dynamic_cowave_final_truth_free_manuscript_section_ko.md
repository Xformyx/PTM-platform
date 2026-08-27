# Dynamic Co-Wave Transition을 이용한 Truth-Free Temporal Structure 평가

## 연구 목적

본 분석의 목적은 enrichment-free PTM/PG time-course에서 먼저 확정된 canonical static Wave를 유지하면서, 동일 Wave 내부 PTM site의 local co-movement가 시간 구간에 따라 persistence, split, merge, recruitment 또는 exit하는 양상을 별도의 **dynamic co-wave transition** annotation으로 기록할 수 있는지 평가하는 것이었다. 핵심 질문은 dynamic transition이 static Wave나 TMM kinase attribution을 변경하지 않고도, 시간 의존적 signaling hypothesis의 해상도와 재현 가능한 우선순위화 정보를 추가하는지였다.

이 평가는 알려진 기전을 얼마나 맞히는지를 최적화하는 benchmark가 아니다. 분석 중에는 reference workbook, anchor ID, expected kinase label, stimulus identity, biological question, literature, RAG, LLM 및 기존 report context를 배제하였다. 따라서 아래 지표는 모두 raw numeric temporal structure의 안정성·coverage·nontriviality를 측정하며, kinase identity 또는 인과관계를 검증하지 않는다.

## Methods

### Input과 strict truth-free boundary

분석에는 protein-normalized PTM numerical trajectory, PG-derived protein numerical trajectory, ordered numeric time axis, replicate design, retained canonical Wave membership 및 이미 truth-free로 생성된 numerical TMM output만 사용하였다. Final artifact는 2,447 PTM site observation, 8 retained canonical Wave, 55 TMM profile, 8,905 protein trajectory 및 1,600 PTM→protein observational edge를 포함했다. Mixed-species FASTA는 site mapping provenance 유지에만 사용했으며, workbook truth는 final artifact 생성과 candidate selection에 읽히지 않았다.

Static Wave의 member site 가운데 최소 4개 timepoint가 관측된 site만 dynamic local-state 계산에 포함하였다. 각 adjacent timepoint interval의 종료점에서 절대 relative log2FC가 activity threshold 이상이고 두 site의 부호가 같을 때, 동일 static Wave에 속하는 pair를 locally same-sign co-active로 정의하였다. 시간에 따른 pair 또는 site local-state 변화는 persistence, split, merge, recruitment 또는 exit로 기록하였다. 이 label은 관측된 local membership 변화이며 kinase switching, upstream/downstream 관계 또는 causal propagation을 의미하지 않는다.

### Preregistered candidate grid와 selection rule

후보 threshold는 분석 전에 0.40, 0.50, 0.60 absolute relative log2FC의 세 값으로 고정했다. 모든 후보는 minimum observed timepoint 4, retained static Wave member universe, leave-one-timepoint-out(LOTO) stability를 동일하게 사용하였다. 실행 도중 추가 threshold나 data-dependent candidate는 만들지 않았다.

Eligible candidate의 prespecified objective는 다음과 같았다.

> `0.45 × mean pair-transition LOTO Jaccard + 0.25 × mean site-transition LOTO Jaccard + 0.20 × local active-pair coverage + 0.10 × transition resolution`

선택을 위해서는 canonical Wave membership과 TMM output 불변성, pair 및 site LOTO Jaccard 각각 0.50 이상, local active-pair coverage 0.10 이상, transition resolution 0 초과·0.95 미만, transition-supported Wave 최소 1개, primary semantic noninferiority를 모두 만족해야 했다. Cross-layer alignment는 descriptive metric으로만 계산했고, 어떤 score나 causal label도 승격하지 않았다.

### Robustness 및 output compaction

LOTO에서는 6개 timepoint를 하나씩 제거한 뒤, 제거된 timepoint를 포함하지 않는 comparable transition identity에 한하여 full-data와 reduced-data event set의 Jaccard overlap을 계산했다. 모든 metric은 complete event set으로 계산했다. 다만 production artifact 크기를 통제하기 위해 serialized output은 deterministic pair-transition example 500개, site-transition example 500개, membership example 250개 및 complete per-Wave aggregate count로 제한했다. 이 compaction은 저장 규칙이며 selection variable이 아니다.

## Results

### Candidate selection과 채택 결정

세 candidate 모두 preregistered stability/coverage gate를 통과했지만, threshold 0.40이 objective 0.6354로 가장 높아 선택되었다. Threshold를 높이면 transition resolution은 증가했으나 local active-pair coverage가 감소했고, objective는 0.6245 및 0.6101로 낮아졌다(Figure TF1).

| Activity threshold | Pair LOTO Jaccard | Site LOTO Jaccard | Local active-pair coverage | Transition resolution | Dynamic cross-layer alignment | Objective | Decision |
|---:|---:|---:|---:|---:|---:|---:|---|
| **0.40** | **0.7102** | **0.7222** | **0.3002** | 0.7519 | 0.7219 | **0.6354** | Selected |
| 0.50 | 0.7086 | 0.7222 | 0.2366 | 0.7774 | 0.7219 | 0.6245 | Rejected |
| 0.60 | 0.7017 | 0.7222 | 0.1753 | 0.7866 | 0.7219 | 0.6101 | Rejected |

선택된 annotation은 8개 retained static Wave 전체에서 transition-support를 보였다. 834개의 static Wave member와 5개의 adjacent local window에서 262,940개의 same-Wave pair-window opportunity가 평가됐고, 이 중 78,930개가 same-sign co-active였다. Complete event set에는 pair transition 105,538개, site transition 3,336개, non-persistence pair transition 79,358개가 포함됐다. 이는 static co-wave가 전체 time-course에서 유지되는 단일 집단이 아니라, local temporal context에 따라 재구성 가능한 membership pattern을 가질 수 있음을 나타낸다(Figures TF3–TF4).

### LOTO stability

LOTO 평균은 pair-transition Jaccard 0.7102, site-transition Jaccard 0.7222였다. 1분, 5분 및 180분 omission에서는 두 Jaccard가 1.0이었고, 60분 omission에서는 각각 0.6604 및 0.6667이었다. 반면 15분 omission에서는 0.3658 및 0.3333, 30분 omission에서는 0.2348 및 0.3333으로 낮았다(Figure TF2). 따라서 overall stability는 gate를 통과했지만, intermediate timepoint가 dynamic state boundary 정의에 실질적으로 기여한다는 점이 확인되었다.

이 결과는 15–30분 사이의 transition annotation이 특히 data-density에 민감할 수 있음을 의미한다. 그러므로 individual transition을 확정적 biological event로 해석하는 것은 부적절하며, 이후 더 조밀한 time-course 또는 replicate-resolved validation에서 우선 검토해야 할 hypothesis indicator로 다뤄야 한다.

### Cross-layer temporal alignment와 invariance

Dynamic transition-support가 있는 static Wave에서 시작되고 target protein peak보다 앞선 PTM→protein observational edge는 1,155개/1,600개(72.19%)였다. 이 비율은 해당 temporal architecture가 PTM Wave와 후행 protein trajectory를 time-aware hypothesis packet으로 연결할 수 있음을 보여 주지만, protein 변화가 kinase action의 downstream consequence임을 증명하지는 않는다.

Dynamic annotation 추가 뒤에도 static Wave membership, 55 TMM profile, kinase ranking 및 locked primary composite score 0.7333은 변경되지 않았다. Immutable golden semantic noninferiority verifier 및 dynamic-aware handoff verifier가 모두 통과하여, new layer가 existing primary contract를 대체하지 않는다는 점을 확인했다.

## Discussion

Dynamic co-wave transition은 static co-wave를 더 작은 independent cluster로 재분할하는 방법이 아니다. 이를 static membership 위에서 계산되는 local temporal annotation으로 한정함으로써, 기존 canonical Wave/TMM의 재현성과 새로 얻는 time-resolved specificity를 동시에 보존했다. Threshold 0.40은 더 높은 threshold보다 더 많은 same-sign local pair information을 유지하면서 pair/site LOTO stability 및 nontrivial transition resolution을 만족해 선택되었다.

이 representation은 이후 RAG/LLM 기반 report에서 유용할 수 있다. LLM은 단순한 kinase list가 아니라, site group이 어느 time interval에서 함께 움직였고 언제 분리·유입·병합되었는지, 그리고 후행 protein trajectory가 temporal consistency를 보이는지를 구분하여 서술할 수 있다. RAG는 candidate kinase, substrate, target protein 및 transition window와 일치하는 문헌을 보조 근거로 제공할 수 있다. 그러나 RAG/LLM은 transition을 생성하거나 threshold를 선택하거나 primary score를 변경해서는 안 되며, numerical evidence packet을 설명하는 후단 소비자로만 기능해야 한다.

본 결과에는 세 가지 주요 한계가 있다. 첫째, 6 timepoint만 존재하므로 15분과 30분 omission에 민감한 local state boundary가 있다. 둘째, 현재 PG trajectory는 condition-level summary이므로 PTM-protein lag concordance의 replicate-level stability를 계산하지 않았다. 셋째, local co-movement와 PTM→protein temporal precedence는 causation 또는 direct kinase assignment를 증명하지 않는다. 따라서 결과는 `observational`, `temporally consistent`, `hypothesis-generating`, `requires perturbation validation`의 claim tier로 제한해야 한다.

## Figure legends

**Figure TF1. Preregistered dynamic co-wave candidate comparison.** Three predeclared absolute relative log2FC activity thresholds were compared using only numeric temporal structure. The selected 0.40 configuration maximized the prespecified objective while preserving LOTO stability and local active-pair coverage.

**Figure TF2. Leave-one-timepoint-out stability.** Pair- and site-transition Jaccard overlap were calculated using only comparable transition identities after omission of one timepoint. Intermediate timepoints contributed substantially to the dynamic boundary, which is displayed rather than masked.

**Figure TF3. Within-static-Wave transition composition.** Complete pair-transition aggregates are shown per immutable static Wave. Stack colors indicate observed local persistence, merge, recruitment, and split labels; counts are not sampled examples and do not imply kinase switching.

**Figure TF4. Truth-free evidence scale and retained observational scope.** Left, prespecified structural metrics for the selected configuration. Right, complete numerical evidence counts on a logarithmic axis. Dynamic transition annotation prioritizes time-resolved hypotheses but neither provides kinase attribution nor establishes causality.

## Reproducibility record

The final truth-free artifact was generated at code revision `d73dc52abf5bd977512ae771a093230e85b18e9c` from numeric normalized PTM/PG vectors, mixed-species FASTA and a pre-existing truth-free TMM artifact. The final artifact SHA-256 was `3e1090a8a2e583f0611d098664da0f7b7e9869b760eddf69f462e332159992a9`. Candidate selection used the registered 12-record blind ledger with SHA-256 `02ab551eb3c345250fa1e76758599e18026fa6b8c72889d95b7c533ebede882e`. The dynamic selection record SHA-256 was `2d12157f12eed4a3322a9a0253257352003e84044534d53dec03336770b1a08e`.
