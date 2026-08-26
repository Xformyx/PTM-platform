# Benchmark v1 + Additive v2 통합 계획

**작성자:** Manus AI

## 1. 통합 원칙

Benchmark v2는 v1을 교체하지 않는다. **v1은 canonical phosphosite recovery와 blind temporal attribution의 기준선으로 계속 유지**하고, v2는 enrichment-free protein time-course, PTM–protein cross-layer relation과 mechanism-chain 평가를 별도 계층으로 추가한다.

> **통합 원칙:** v1에서 이미 검증된 결과는 보존하고, v2는 새로운 evidence layer와 metric을 추가하되 v1 primary score, blind boundary, discovery retention과 Figure 1–4의 과학적 의미를 변경하지 않는다.

## 2. v1에서 반드시 보존할 좋은 점

| v1 자산 | 보존 이유 | 통합 후 위치 |
|---|---|---|
| Stimulus·question·exact model blind | 분석 결과가 insulin identity에 역으로 맞춰지는 것을 차단 | v1/v2 공통 최상위 boundary |
| Immutable child snapshot | 동일 raw input과 metadata를 재현 가능하게 보존 | 공통 BenchmarkRun snapshot |
| Truth scorer-only isolation | workbook truth의 analysis/RAG/LLM leakage 방지 | runner-only locked evaluation |
| Hash-chained trial ledger | parameter 선택·기각 이유와 input/config/code hash 추적 | v2 변수 최적화에도 동일 사용 |
| 0층 production preprocessing | 일반 Order와 benchmark가 같은 PR/PG/FASTA parsing을 사용 | B0 공통 layer |
| Sequence·isoform·species mapping | site-level canonical 비교와 Rat+human mixed FASTA provenance | B1 공통 mapping contract |
| Detectable-anchor denominator | 미측정 site를 algorithm miss로 계산하지 않음 | `primary_v1` 그대로 유지 |
| Direction·peak-window scoring | 단순 검출을 넘어 temporal regulation을 평가 | `primary_v1` 그대로 유지 |
| Tier 1/2 canonical scoring | 높은 신뢰도의 known biology만 primary score에 사용 | `primary_v1` 그대로 유지 |
| Tier 3/4·de novo discovery retention | canonical benchmark가 신규 signal을 제거하지 않음 | `discovery_v1` 그대로 유지 |
| Canonical Temporal Wave | 시계열 co-movement를 단일 contract로 계산 | v1 core, v2 protein Wave에 재사용 |
| Multi-candidate TMM | shared substrate의 kinase 기여도를 분리 | v1 core, v2 mechanism edge에 참조 |
| Motif prior와 data anchor 분리 | prior-assisted prediction을 direct evidence로 오인하지 않음 | 공통 evidence-tier contract |
| Consensus Wave·soft membership | replicate stability와 경계 site 불확실성을 보존 | v1 core |
| Adaptive bootstrap·LOTO uncertainty | contribution과 timing claim의 견고성 제공 | v1 core, v2 cross-layer에 재사용 |
| Relative·occupancy track 분리 | protein normalization과 occupancy-like evidence 혼동 방지 | v1 core |
| Shrunken activity + evidence mass | module-size bias를 줄이고 support 양을 별도 표현 | v1 cascade 유지 |
| D0–D3 directionality tier | temporal precedence와 causality를 분리 | v1/v2 공통 관계 contract |
| Evidence-gated directionality | prior-only edge가 main scientific edge로 승격되는 것을 차단 | v1/v2 공통 gate |
| Figure 1–4 + source TSV | 논문 figure와 수치의 추적 가능성 | 통합 Figure 1–4의 core panel |
| Durable TMM/scorer workers | 장시간 계산과 truth isolation을 운영 환경에서 보장 | 공통 실행 구조 |

## 3. v1을 변경하지 않을 항목

다음 항목은 v2 개발 중에도 **교체하거나 재최적화하지 않는다**.

| 불변 항목 | 통합 규칙 |
|---|---|
| v1 locked workbook anchors | 기존 anchor ID, tier, direction, peak window를 그대로 유지 |
| v1 primary component weights | 기존 weighted score를 변경하지 않음 |
| v1 score denominator | sequence/isoform/species + detectability 기준 유지 |
| v1 Wave/TMM frozen config | v2 protein/cross-layer parameter와 독립적으로 유지 |
| v1 discovery classification | DQ1–DQ4와 Tier 3/4 retention 유지 |
| v1 `tmm_full_temporal.v1` contract | baseline contract로 계속 실행 가능해야 함 |
| v1 Figure 1–4 source rows | 기존 column을 삭제·의미 변경하지 않음 |

v2의 결과를 v1 weighted score에 혼합하지 않는다. 초기 통합에서는 `primary_v1`, `mechanism_v2`, `discovery_v1`을 세 개의 독립 결과로 보고한다.

## 4. v2에서 추가할 계층

| v2 extension | 새 artifact | 새 평가 |
|---|---|---|
| Protein time-course | `protein_time_series` | protein temporal coverage·replicate stability |
| PTM–same-gene protein relation | `ptm_protein_pairs` | onset/peak lag·direction·interval overlap |
| Network-linked non-PTM effector | `cross_layer_edges` | relation coverage·source provenance·lag accuracy |
| Accession-aware direct kinase evidence | `kinase_direct_evidence` | data-anchored kinase coverage·timing coverage |
| Ordered signaling chain | `mechanism_chains` | E0–E3 chain completeness·branch macro-average |
| Counterexample | `mechanism_counterevidence` | refutation sensitivity·overclaim rate |
| Interpretation-ready evidence | `hypothesis_evidence_packets` | 후속 RAG·LLM의 input contract; primary score에서는 제외 |

v2 extension은 v1 core artifact를 복사하지 않고 참조한다. 동일 site, Wave, kinase score와 contribution을 중복 생성하지 않으며, 모든 v2 relation은 v1 observation ID를 foreign key처럼 사용한다.

## 5. Versioned 통합 artifact

```json
{
  "schema_version": "ptm_blind_benchmark_artifact.v2",
  "v1_core": {
    "site_observations": [],
    "temporal_wave_contract": {},
    "tmm": {},
    "mapping_audit": {},
    "discovery_candidates": []
  },
  "v2_extensions": {
    "protein_time_series": [],
    "ptm_protein_pairs": [],
    "kinase_direct_evidence": [],
    "cross_layer_edges": [],
    "mechanism_chains": [],
    "mechanism_counterevidence": [],
    "hypothesis_evidence_packets": []
  },
  "provenance": {
    "v1_contract": "tmm_full_temporal.v1",
    "v2_contract": "enrichment_free_temporal_mechanism.v2"
  }
}
```

v1 scorer는 `v1_core`만 읽어 기존 score를 재현한다. v2 scorer는 `v1_core`의 observation과 `v2_extensions` relation을 함께 읽는다. Ordinary analysis, RAG와 LLM은 어느 scorer truth도 읽지 않는다.

## 6. Score 통합 구조

| Score block | 내용 | 최종 사용 |
|---|---|---|
| `primary_v1` | detectable/regulated anchor recall, direction, peak window, v1 chain completeness | 기존 benchmark 핵심 결과 |
| `kinase_evidence_v2` | direct/empirical kinase coverage, family resolution, data-anchored timing | 신규 독립 결과 |
| `cross_layer_v2` | protein coverage, PTM→protein relation, lag/window accuracy | 신규 독립 결과 |
| `mechanism_v2` | ordered E0–E3 chain completeness, branch macro-average | 신규 독립 결과 |
| `refutation_v2` | counterexample rejection, insufficient-data 처리, overclaim rate | 신규 안전성 결과 |
| `discovery_v1` | DQ1–DQ4와 canonical truth 밖의 network-supported candidates | 기존 discovery 결과 |

초기 논문에서는 단일 overall score를 만들지 않는다. 서로 다른 과학적 질문을 하나의 숫자로 합치면 canonical recovery가 cross-layer discovery를 가리거나 반대로 protein coverage가 kinase accuracy를 가릴 수 있다.

## 7. Figure 1–4의 additive 통합

Figure 수는 현재 요청대로 1–4를 유지한다. v1 panel을 삭제하지 않고 v2 panel을 병렬 추가한다.

| Figure | 보존할 v1 내용 | 추가할 v2 내용 |
|---|---|---|
| Figure 1 | Blind design, preprocessing, mapping, data availability | PR/PG dual-layer coverage와 v1→v2 artifact flow |
| Figure 2 | Canonical phosphosite recall, direction, peak-window accuracy | 없음. v1 canonical panel을 그대로 유지 |
| Figure 3 | TMM profiles, contribution, uncertainty, prior/data-anchor provenance | accession-aware direct evidence와 data-anchored timing subpanel |
| Figure 4 | TMM-weighted cascade와 evidence-gated directionality | PTM Wave→protein effector follow-through와 mechanism-chain completeness |

기존 Figure 1–4 source TSV column은 유지하고, v2 source sheet를 별도 파일로 추가한다. Inhibitor data가 없으므로 Figure 5 이상은 만들지 않는다.

## 8. Locked truth의 additive 확장

기존 `insulin_signaling_v1.truth.json`을 수정하지 않는다. 새로운 runner-only v2 truth가 v1을 참조한다.

```json
{
  "schema_version": "ptm_locked_truth_bundle.v2",
  "inherits": {
    "dataset_id": "insulin_signaling_v1",
    "truth_sha256": "<existing-v1-hash>"
  },
  "protein_effectors": [],
  "cross_layer_relations": [],
  "kinase_direct_evidence": [],
  "mechanism_chains": [],
  "counterexamples": []
}
```

이 구조는 v1 score 재현성을 보존하면서 v2 reference를 독립적으로 versioning한다. v2 reference를 수정하면 v2 hash와 benchmark version만 증가하며 v1 결과는 변하지 않는다.

## 9. 구현 단계

### Phase A — v1 Golden Baseline 고정

현재 frozen-v2라는 명칭으로 개발된 temporal 개선을 **v1 core baseline**으로 취급한다. Supplied PR/PG/FASTA의 artifact, primary score, Figure 1–4 source values와 config hash를 golden fixture로 보존한다.

| Gate | 기준 |
|---|---|
| Mapped sites | 2,447 유지 |
| Canonical score | 0.7333 유지 |
| Wave count | 8 유지 |
| Relative contribution sites | 2,243 유지 |
| Primary score denominators | 기존 값과 동일 |
| Blind boundary | truth/RAG/identity leakage 0 |

### Phase B — v2 Artifact Sidecar

Protein time-course와 PTM–protein relation을 `v2_extensions`로만 추가한다. 이 단계에서 scorer와 Figure를 변경하지 않는다. v1 artifact를 동일 raw input에서 semantic equality로 비교한다.

### Phase C — Direct Kinase Evidence와 Timing

Accession-first, FASTA record-level OX taxonomy, isoform-aligned site와 observed kinase PTM channel을 추가한다. 기존 motif/TMM 결과는 삭제하지 않고 `prior_assisted`로 유지한다.

### Phase D — Cross-layer Mechanism Engine

Canonical DirectedTemporalRelationship를 PTM–protein 및 network-linked effector에 재사용한다. 모든 관계는 `causality_status=not_tested`를 기본값으로 갖는다.

### Phase E — v2 Locked Scorer

기존 v1 scorer를 호출해 `primary_v1`을 먼저 생성한 뒤 v2 scorer를 별도 호출한다. v2 오류가 v1 score 생성을 실패시키지 않도록 isolation한다.

### Phase F — Figure 1–4 Additive Rendering

v1 panel을 golden snapshot test로 보호하고, v2 panel과 source sheet만 추가한다. Text-to-path SVG와 existing download bundle을 유지한다.

### Phase G — Shadow Run과 서버 승격

동일 BenchmarkRun에서 v1-only와 v1+v2를 동시에 실행한다. UI 기본값과 논문 artifact는 acceptance gate 통과 전까지 v1-only를 유지한다.

## 10. Noninferiority와 승격 기준

| 영역 | 필수 승격 기준 |
|---|---|
| v1 primary score | 모든 component와 denominator가 동일 |
| v1 mapped sites | 감소 없음 |
| v1 Wave/TMM | profile·contribution·uncertainty semantic regression 없음 |
| v1 discovery | Tier 3/4·DQ 후보 손실 없음 |
| v2 protein artifact | expected 8,905 gene trajectory가 provenance와 함께 보존 |
| v2 PTM–protein pair | expected 2,447 same-gene pair 보존 |
| Kinase timing | data-anchored denominator 0이면 `not_evaluable` |
| Causal wording | perturbation 없는 run에서 causal/validated claim 0 |
| Blind isolation | v2 analysis/RAG/LLM truth access 0 |
| Performance | BenchmarkRun timeout·stale threshold 내 완료 |
| Publication | Figure/source value consistency와 portable SVG pass |

## 11. Rollback 구조

`production_contract.id`를 feature flag로 사용한다.

| Contract | 동작 |
|---|---|
| `tmm_full_temporal.v1` | 현재 v1-only 실행 |
| `enrichment_free_temporal_mechanism.v2_shadow` | v1 결과를 공식으로 유지하며 v2 sidecar 생성 |
| `enrichment_free_temporal_mechanism.v2` | acceptance 후 v1+v2 공식 결과 생성 |

v2 worker 실패 시 v1 artifact와 score는 계속 완료될 수 있어야 한다. Rollback은 contract flag를 v1로 되돌리는 방식으로 수행하며 v1 truth, score와 Figure renderer를 삭제하지 않는다.

## 12. 최종 권장안

통합 순서는 **v1 golden baseline 고정 → v2 artifact sidecar → direct kinase/timing → cross-layer mechanism → v2 scorer → additive Figure → shadow run → 승격**으로 한다.

가장 중요한 설계 결정은 다음 세 가지다.

1. **v1 primary score를 그대로 보존한다.**
2. **v2는 별도 mechanism score로 시작하며 하나의 overall score로 합치지 않는다.**
3. **플랫폼 전체 RAG·LLM 적용은 v1+v2 numeric benchmark가 동결된 다음 단계로 분리한다.**

이 방식이면 v1의 강점인 blind canonical validation, TMM uncertainty, discovery retention과 운영 안정성을 잃지 않으면서 enrichment-free PTM–protein mechanism이라는 플랫폼 경쟁력을 추가할 수 있다.
