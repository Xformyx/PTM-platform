# Strict-blind enrichment-free temporal Benchmark v2: 최종 Methods, Results 및 claim boundary

**작성일:** 2026-08-27
**분석 범위:** enrichment-free PR+PG time-course, additive Benchmark v2 sidecar
**핵심 원칙:** immutable v1 primary contract 보존, truth-free parameter selection, runner-only locked evaluation, observational mechanism hypothesis

## 초록

본 연구는 기존 strict-blind insulin Benchmark v1의 장점인 **immutable blind child snapshot, runner-only locked truth, Tier 1/2 primary score, canonical Wave/TMM, uncertainty 및 Figures 1–4**를 변경하지 않으면서, PG-derived non-PTM protein time course와 PTM trajectory를 연결하는 additive Benchmark v2를 구현하였다. v2는 `v2_extensions` sidecar로만 추가되며 v1 primary score와 결합되지 않는다. 모든 v2 parameter는 raw numeric time-course와 FASTA-derived accession/OX provenance만으로 선택하였고, workbook truth·stimulus identity·research question·RAG·LLM은 configuration freeze 이전 분석에 사용하지 않았다.

실원자료 replay에서 2,447개 PTM site와 8개 Wave, 55개 TMM profile, 2,243개 relative contribution site, 768개 occupancy contribution site 및 6개 cascade timepoint가 유지되었다. additive v2는 8,905개 protein trajectory, 2,447개 same-gene PTM–protein pair, 1,600개 retained Wave→non-PTM protein edge, 1,154개 temporally eligible edge 및 8,000개 falsifiable mechanism candidate를 생성하였다. 9개 사전 정의 cross-layer configuration의 truth-free 최적화 결과 `minimum_absolute_change=0.30`, `minimum_lag_aware_similarity=0.40`, `minimum_loto_stability=0.60`이 선택되었다. v1 semantic noninferiority verifier는 실패 0건으로 통과했고 locked v1 primary score는 **0.7333333333**으로 유지되었다.

Accession-first UniProt replay는 1,388개 query를 모두 HTTP 200으로 처리하여 27개 observed site에서 47개 exact-site direct evidence row를 확인하였다. 그러나 동일 kinase가 해당 site의 frozen TMM contribution에 양의 기여를 보인 경우는 0건이었다. 따라서 data-anchored kinase timing denominator는 0이며 timing accuracy는 0이 아니라 **`not_evaluable`**이다. 또한 현재 workbook에는 analyst-authored optional v2 truth sheet가 없으므로 cross-layer score는 `not_evaluable_missing_locked_cross_layer_reference`, mechanism score는 descriptive-only, refutation score는 `not_evaluable_ambiguous_site_policy_only`로 보고하였다. 본 결과가 지지하는 주장은 **blind enrichment-free PTM+protein temporal evidence graph와 검증 가능한 observational mechanism hypothesis의 생성**이며, causal mechanism의 확정이나 알려진 pathway의 자동 복원은 아니다.

## 연구 설계

v1과 v2는 하나의 결합 점수가 아니라 **보존된 primary-v1 계약과 독립 additive-v2 계약**으로 구성하였다. v1은 기존 scorer와 golden baseline을 유지하고, v2는 protein trajectory, same-gene PTM–protein pair, cross-layer temporal edge, direct-evidence audit, kinase timing evaluability, mechanism chain 및 counterevidence를 sidecar에 저장한다.

| 계층 | 입력 | 산출물 | truth 사용 | score 영향 |
|---|---|---|---|---|
| v1 primary | blind PR/PG-derived PTM artifact, time axis, FASTA | site, Wave, TMM, contribution, cascade | configuration freeze 후 runner-only | 기존 primary score만 계산 |
| v2 protein | condition-level normalized PG | 8,905 protein trajectories | 없음 | v1 score 영향 없음 |
| v2 cross-layer | Wave profiles와 non-PTM protein profiles | 1,600 observational edges | 없음 | 독립 v2 evaluation만 가능 |
| v2 direct evidence | FASTA accession, OX taxonomy, exact observed site | 47 UniProt exact-site rows | 없음 | timing anchor gate에만 사용 |
| v2 locked evaluation | frozen sidecar와 optional analyst truth | protein/cross-layer/mechanism/refutation metrics | runner-only | combined score 없음 |

> **Blind boundary:** parameter selection과 shadow replay에는 workbook truth, stimulus identity, exact biological question, RAG corpus, LLM output 및 expected kinase/mechanism label을 전달하지 않았다. Locked truth는 artifact/configuration freeze 이후 runner-only scorer에서만 읽는다.

## Methods

### v1 semantic preservation

Authoritative frozen v1 artifact의 top-level site, Wave, TMM, contribution, cascade 및 provenance를 수정하지 않고 `extension_schema_versions`, `v2_extensions`, `compatibility`만 추가하였다. Golden verifier는 site observations, canonical Wave, TMM profile, relative·occupancy contribution, cascade, primary score 및 publication source invariants를 비교한다. 최종 artifact는 모든 v1 invariant를 exact preservation으로 통과하였다.

### Protein time-course 구성

PG production output `all_protein_level_changes_normalized_phospho.tsv`를 사용하여 gene×condition 값을 구성하였다. 동일 gene·condition 내 값은 median으로 집계하였다. 6개 condition은 1, 5, 15, 30, 60 및 180분이었다. 현재 production PG output에는 replicate-level protein values가 보존되지 않으므로 protein replicate stability는 계산하지 않았으며 provenance에 `condition_level_only`와 `unavailable_for_protein_layer`를 명시하였다.

### Same-gene PTM–protein 연결

각 frozen PTM site observation을 동일 gene의 protein trajectory와 연결하였다. 이 연결은 PTM relative change와 total-protein change를 분리하여 보여 주지만 occupancy의 직접 측정으로 간주하지 않는다. 최종 sidecar에는 2,447개 PTM–protein pair가 생성되었다.

### Wave→non-PTM protein cross-layer 관계

Canonical Wave profile을 source, PTM이 관측되지 않은 protein profile을 target으로 사용하였다. Directionality engine은 onset/peak lag, lag-aware similarity 및 leave-one-timepoint-out stability를 산출하였다. 관계는 `source_precedes_target` 등의 temporal interpretation으로만 표현하고 모든 edge에 `causality_status=not_tested`를 유지하였다.

Parameter selection은 다음 9개 조합을 한 번에 preregister하였다.

| Parameter | 후보값 |
|---|---|
| minimum absolute change | 0.30, 0.40, 0.50 |
| minimum lag-aware similarity | 0.40 고정 |
| minimum LOTO stability | 0.60, 0.75, 0.90 |

선택 objective는 candidate coverage, temporally eligible fraction, median LOTO stability, median absolute lag-aware similarity 및 causal-overclaim penalty를 결합하였다. Locked workbook truth와 biological identity는 objective에 포함하지 않았다. 선택 configuration은 별도 additive-v2 hash로 동결하여 기존 v1 `CONFIG_SHA256`를 변경하지 않았다.

### Accession-first direct kinase evidence audit

Frozen site observations의 FASTA-derived accession, taxonomy ID, mapping method 및 exact site를 query contract로 변환하였다. 모든 1,388개 query는 accession-first였으며 taxonomy는 OX=10116으로 보존되었다. UniProt `Modified residue` 및 PTM comment 중 exact numeric site와 명시적 positive kinase attribution이 일치한 경우만 direct evidence로 인정하였다. `dephosphorylated by`, cell-cycle phase prose, qualifier suffix 및 비식별적 문자열은 kinase로 분류하지 않도록 parser를 보강하였다. UniProt REST API는 1,388/1,388 query에서 HTTP 200을 반환하였다.[1] iPTMnet accession endpoint는 bounded retry에서 HTTP 503이었으므로 해당 source는 unavailable로 기록했으며 UniProt 결과로 대체했다고 주장하지 않았다.[2]

Exact-site database evidence는 site-level kinase–substrate annotation을 지지하지만 그 자체로 kinase activity time-course를 제공하지 않는다. Timing anchor는 **동일 kinase identity가 frozen TMM profile에 존재하고, 해당 exact site에 동일 kinase의 양의 contribution이 존재하는 경우**로 제한하였다.

### Mechanism evidence chain

각 chain은 kinase timing prediction, Wave, cross-layer protein target을 연결한다. Chain은 kinase→Wave와 Wave→protein evidence packet, falsification target 및 counterevidence를 포함한다. Direct timing anchor 또는 network relation이 부족하면 `temporal_candidate` 또는 `insufficient_evidence`로 유지하며 `evidence_supported_mechanism_candidate`로 승격하지 않는다.

### Runner-only additive truth와 scorer

기존 v1 truth JSON의 canonical hash를 `parent_v1_truth_sha256`로 저장하였다. Optional sheets가 없는 현재 workbook에서는 v2 protein/cross-layer/mechanism/counterexample truth를 만들지 않는다. 별도의 analyst template은 `Protein_Effectors`, `Cross_Layer_Relations`, `Mechanism_Chains`, `Counterexamples` header만 포함하며 biological row는 0개이다. Algorithm output, raw-data candidate, RAG 또는 LLM으로 template을 자동 채우는 기능은 의도적으로 구현하지 않았다.

독립 v2 scorer는 protein effector recovery, cross-layer reference recovery, explicit mechanism recovery, counterexample refutation 및 kinase timing을 별도 metric으로 계산한다. Denominator가 0이면 accuracy를 0으로 반환하지 않고 `null`과 `not_evaluable` reason을 기록한다. `combined_weighted_score`는 항상 `null`이며 `primary_v1_unchanged=true`이다.

### Figures와 source data

Canonical renderer는 Figures 1–4만 생성하고 Figure 5 이상은 제외한다. 모든 SVG text는 path로 변환하였다. Figure 4E에는 protein trajectory, PTM–protein pair, retained·eligible cross-layer edge, mechanism candidate, evidence-supported mechanism 및 data-anchored timing status를 표시한다. Figure 4 source TSV에는 기존 Wave/cascade/directionality row와 함께 protein, PTM pair, cross-layer edge, exact-site direct evidence, kinase timing, mechanism chain 및 counterevidence section을 저장한다.

## Results

### v1 primary 성능과 semantic noninferiority

| 항목 | 최종값 |
|---|---:|
| canonical weighted score | 0.7333333333 |
| detectable anchor recall | 1.0000 |
| regulated anchor recall | 0.3333 |
| direction accuracy | 1.0000 |
| peak-window accuracy | 1.0000 |
| Tier 1/2 detectable denominator | 3 |
| semantic noninferiority failures | 0 |

v2 sidecar 부착 전후 v1 site/Wave/TMM/contribution/cascade/primary score/Figure-source invariants는 모두 동일하였다. 따라서 v2 structural extension의 개선 효과와 v1 locked score를 혼합하여 해석하지 않는다.

### Truth-free cross-layer optimization

| 항목 | 선택 결과 |
|---|---:|
| minimum absolute change | 0.30 |
| minimum lag-aware similarity | 0.40 |
| minimum LOTO stability | 0.60 |
| objective | 0.73233978 |
| non-PTM-only proteins | 7,539 |
| candidate proteins | 2,691 |
| candidate coverage | 0.35694389 |
| retained edges | 1,600 |
| temporally eligible edges | 1,154 |
| eligible fraction | 0.72125 |
| median LOTO stability | 0.833333 |
| median absolute lag-aware similarity | 0.8257625 |
| causal overclaim rate | 0.0 |

Amplitude 0.30은 benchmark additive-v2 frozen configuration에만 적용된다. 이 값은 일반 production caller의 biological universal threshold라는 주장이 아니라, 현재 blind numeric dataset에서 preregistered structural objective가 선택한 benchmark configuration이다.

### Additive-v2 structural output

| 산출물 | 최종 개수 | 해석 경계 |
|---|---:|---|
| protein trajectories | 8,905 | condition-level, protein replicate unavailable |
| same-gene PTM–protein pairs | 2,447 | occupancy 직접 측정 아님 |
| retained cross-layer edges | 1,600 | observational temporal relation |
| temporally eligible edges | 1,154 | causal proof 아님 |
| kinase timing predictions | 55 | motif/prior 포함 |
| mechanism chains | 8,000 | falsifiable candidates |
| evidence-supported mechanisms | 0 | evidence gate 유지 |
| counterevidence rows | 8,000 | insufficient-evidence reason 보존 |

### Direct evidence와 timing evaluability

| 항목 | 최종값 |
|---|---:|
| accession-first queries | 1,388 |
| UniProt HTTP 200 | 1,388 |
| iPTMnet status | unavailable HTTP 503 |
| exact-site direct evidence rows | 47 |
| observed sites with exact evidence | 27/2,447 (1.1034%) |
| exact evidence rows matching a TMM profile identifier | 16 |
| positive same-kinase site contribution rows | 0 |
| timing-anchor-eligible rows | 0 |
| data-anchored timing denominator | 0 |
| timing accuracy | `null` / `not_evaluable` |

본 결과는 **direct site evidence coverage가 완전히 0은 아니지만 timing accuracy를 평가할 수 있는 profile-linked anchor는 0**임을 보여 준다. Exact-site evidence row가 발견되었다는 이유만으로 motif-only 또는 다른 kinase에 귀속된 TMM profile을 direct data anchor로 승격하지 않았다. 따라서 이전의 0 accuracy 표현은 과학적으로 부정확하며 최종 결과에서는 denominator 0의 `not_evaluable`로 교정하였다.

### Independent v2 locked evaluation

| Metric group | 상태 | 이유 |
|---|---|---|
| kinase timing | `not_evaluable` | data-anchored denominator 0 |
| protein effector | `not_evaluable_missing_locked_protein_reference` | optional analyst truth 없음 |
| cross-layer | `not_evaluable_missing_locked_cross_layer_reference` | optional analyst truth 없음 |
| mechanism | `descriptive_only_no_explicit_v2_chain_truth` | v1 kinase output token만 존재 |
| refutation | `not_evaluable_ambiguous_site_policy_only` | explicit counterexample truth 없음 |
| combined score | `null` | v1 primary와 의도적으로 분리 |

Not-evaluable은 algorithm failure score 0과 다르다. 이는 현재 locked reference가 답할 수 없는 질문을 score로 위장하지 않는 평가 상태이다.

## Claim boundary

> **지지되는 핵심 주장:** 엄격한 blind 조건에서 enrichment-free PTM과 non-PTM protein time-course를 결합하여, uncertainty와 temporal precedence evidence를 포함하는 재현 가능한 evidence graph 및 실험으로 반증 가능한 mechanism candidate를 생성할 수 있다.

| 주장 | 허용 여부 | 근거 |
|---|---|---|
| v1 primary 성능이 보존되었다 | 허용 | golden noninferiority failure 0, score 0.7333333333 |
| PTM과 protein cross-layer temporal 후보를 생성했다 | 허용 | 1,600 retained, 1,154 eligible edges |
| 알려진 mechanism을 복원했다 | 현재 불허 | optional locked v2 truth 없음 |
| data-anchored kinase timing accuracy가 높다 | 불허 | denominator 0 |
| cross-layer edge가 causal하다 | 불허 | `causality_status=not_tested` |
| protein replicate stability가 확인되었다 | 불허 | condition-level PG output만 존재 |
| exact-site kinase evidence가 일부 존재한다 | 허용 | UniProt 47 rows, 27 observed sites |
| direct evidence가 현재 TMM timing을 검증한다 | 불허 | positive same-kinase contribution 0 |

## 재현성 및 server handoff

다음 명령은 target server에서 frozen artifact와 score bundle의 acceptance를 확인한다. Workbook truth는 benchmark runner에서만 mount해야 하며 API server와 benchmark TMM runner에는 전달하지 않는다.

```bash
PYTHONPATH=.:api-server python3 scripts/verify_temporal_benchmark_handoff.py \
  --artifact /path/to/final_selected_v1_plus_v2.json \
  --locked-score /path/to/locked_score_result.json \
  --additive-score /path/to/additive_v2_score.json \
  --figures-dir /path/to/figures \
  --source-data-dir /path/to/source_data \
  --require-additive-v2 \
  --output /path/to/final_handoff_verification.json
```

권장 서비스 경계는 다음과 같다.

| 서비스 | 허용 입력 | 금지 입력 |
|---|---|---|
| `api-server` | raw order metadata와 production data | locked workbook truth |
| `benchmark-tmm-runner` | immutable blind child snapshot, FASTA, frozen config | stimulus/question/RAG/LLM/workbook truth |
| `benchmark-runner` | archived artifact, locked truth, frozen score config | analysis parameter 변경 |

### Final integrity hashes

| 산출물 | SHA-256 |
|---|---|
| `final_selected_v1_plus_v2.json` | `de9568e3e8a9331a717005fb98c7dd78dbfb722e416f73421e250118e7523799` |
| `additive_v2_score.json` | `48647d92030ca87a5158c482776a16d34c4ad8525a9cd99f6f18064e901de204` |
| `final_handoff_verification.json` | `090a86124d2ab550756583f16d722927da5686f72c1fff337080a353152d3980` |
| analyst truth template | `95b2386872b8782d50e0526fedebf8e7b41ae0b49e5ab75c0e7eb95a8222456b` |
| Figure source-data ZIP | `fd3a15f38631ef21c150f74ba304813ffdbe73f3832d49bdadb5d0e11f7c25f0` |
| additive-v2 config | `c4cdd0b4a02ada54d9808d9964a3c1e9b1ffc706098843ccb9f3305d2d757790` |
| strict-blind ledger | `818b7ef4e9ea27b61791ad85f919ab3b1812284edf80c267c078a637cd2ee114` |
| selected ledger tail | `8464787a5bd1d43feecaf072de74fe283956f294812be431f68f72c7f7b092b0` |

## 한계와 다음 검증 단계

현재 가장 큰 한계는 세 가지이다. 첫째, PG protein layer가 condition-level summary이므로 protein replicate stability를 산출할 수 없다. 둘째, iPTMnet source가 replay 시점에 HTTP 503이었으므로 source-complete direct evidence audit가 아니다. 셋째, analyst-authored optional v2 truth가 없어 cross-layer/mechanism recovery를 정량 평가할 수 없다.

다음 단계에서는 raw PG replicate loader를 구현하고, 독립 analyst가 blank template에 reference를 작성한 후, 동일 frozen artifact를 변경하지 않은 채 runner-only scorer를 재실행해야 한다. Direct timing 평가를 가능하게 하려면 exact-site kinase–substrate evidence가 해당 site의 positive same-kinase TMM contribution과 연결되거나, observed kinase regulatory PTM profile이 제공되어야 한다. Perturbation 또는 inhibitor data가 추가될 경우에만 causal validation layer와 Figure 5 이상을 별도 계약으로 활성화한다.

## References

[1]: https://rest.uniprot.org/ "UniProt REST API"
[2]: https://research.bioinformatics.udel.edu/iptmnet/ "iPTMnet"
