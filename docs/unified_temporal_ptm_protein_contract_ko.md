# Unified Temporal PTM–Protein Contract

## 목적

일반 Order 분석과 strict-blind benchmark는 **동일한 `enrichment_free_temporal_mechanism.v2.sidecar` 분석 engine과 result schema**를 사용한다. Benchmark는 별도 생물학 알고리즘이 아니라, 일반 분석 결과를 immutable artifact로 고정한 뒤 runner-only 환경에서 locked workbook truth로 평가하는 실행 모드다.

| 계층 | 일반 Order | Strict-blind benchmark |
|---|---|---|
| PTM input | Observed-only protein-normalized PTM vectors | Immutable raw-data child snapshot |
| Wave | `temporal_wave_engine.analyze_temporal_waves` | 동일 canonical engine의 archived Wave contract |
| PTM–protein sidecar | `build_production_temporal_ptm_protein_analysis()` | `build_v2_sidecar()` |
| Cross-layer numeric config | `CROSS_LAYER_CONFIG` | 동일 frozen config와 config provenance |
| Output schema | `enrichment_free_temporal_mechanism.v2.sidecar` | 동일 schema의 `v2_extensions` |
| Truth / score | 없음 | Artifact freeze 후 runner-only locked truth/scorer만 접근 |

## 공용 결과 계약

공용 full artifact는 다음 항목을 포함한다.

| Section | 의미 | 해석 경계 |
|---|---|---|
| `temporal_wave_contract` | PTM complete observed-only vectors의 canonical Wave | Wave는 관측 temporal pattern임 |
| `protein_time_series` | PG-derived condition-level protein trajectory | 현재 protein replicate stability는 unavailable일 수 있음 |
| `ptm_protein_pairs` | Same-gene PTM site–protein pair | Peak order는 observational only |
| `cross_layer_edges` | Wave→non-PTM protein directed temporal relation | `causality_status=not_tested` |
| `kinase_timing_predictions` | TMM profile timing 및 direct-evidence class | Direct denominator 0이면 `not_evaluable` |
| `mechanism_chains` / `hypothesis_evidence_packets` | Falsifiable evidence packet과 counterevidence | Causal mechanism proof가 아님 |

일반 Order는 full object를 `<order-output>/temporal_ptm_protein_analysis_v2.json`으로 저장하며, DB에는 `temporal_ptm_protein_analysis` compact summary만 저장한다. 전체 object는 `GET /orders/{order_id}/temporal-ptm-protein-analysis`로 접근한다. 이 분리는 큰 numeric artifact가 DB JSON과 일반 heatmap response를 과도하게 키우지 않도록 하기 위한 저장·전송 최적화이며, 분석 engine이나 schema를 분리하는 것이 아니다.

## 소비 경로

일반 UI는 Kinase Activity Heatmap 안에 접이식 **Shared PTM–Protein Temporal Evidence** panel을 표시한다. Chat, Data-Grounded Analysis/Co-Scientist, comparative analysis, Report question generation 및 Results/Discussion/Abstract writer는 compact evidence packet을 같은 contract로 소비한다. 모든 LLM context에는 temporal precedence가 causal proof가 아니며 counterexample과 orthogonal validation을 요구한다는 boundary를 포함한다.

## Blind boundary

`v2_truth_adapter`, `v2_scorer`, optional v2 workbook sheets와 primary score는 benchmark runner-only 영역이다. 일반 Order의 shared sidecar는 raw numeric production output, canonical Wave, TMM result만 사용하며 workbook truth, RAG label, LLM output, stimulus identity 또는 expected mechanism label을 numeric selection에 사용하지 않는다.

## 운영 적용

새 배포 후 기존 cached heatmap에는 `unified_temporal_ptm_protein.v1` cache-version suffix가 없으므로, 각 Order에서 Kinase Activity Heatmap을 한 번 재계산해야 shared artifact와 summary가 생성된다. Protein-level normalized TSV가 없으면 sidecar는 오류 없이 `unavailable` provenance를 기록하고 기존 kinase analysis를 유지한다.
