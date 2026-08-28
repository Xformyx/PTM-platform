# Dynamic Co-Wave Developer Handoff

> **문서 목적:** PTM Platform의 현재 production Dynamic Co-Wave 구현을 다른 개발자가 안전하게 유지·확장·검증할 수 있도록, 분석의 의미와 data lineage를 코드 기준으로 정리한다. 이 기능은 benchmark 전용 기능이 아니며 일반 Order와 strict-blind benchmark가 **동일한 canonical temporal analysis engine**을 사용한다. 다만 benchmark truth, locked score, workbook reader는 runner-only 경계에 남으며 production 분석·Report·LLM packet에는 절대 전달되지 않는다.

**기준 브랜치:** `main`
**핵심 구현 커밋:** `7174d1b` (`fix(report): prepare temporal evidence before rerun`)
**문서 기준 최신 커밋:** P0 v2 corrective patch 이후 main
**주요 계약 버전:** `dynamic_co_wave_transition.v2`, `time_varying_comovement.v1`, `enrichment_free_temporal_mechanism.v2.sidecar`, `report_temporal_evidence_packet.v2`

## 1. 기능의 범위와 해석 원칙

Dynamic Co-Wave는 immutable static Wave에 속한 PTM site/form들이 인접한 시간 구간에서 보이는 **국소적 활성 상태와 동반 운동의 변화**를 추가로 주석화한다. static Wave는 전체 time-course trajectory를 바탕으로 이미 확정된 집단이며, Dynamic Co-Wave는 이 membership을 변경하지 않는다. 따라서 이 기능은 “같은 Wave의 구성원이 어느 interval에서 함께 active였고, 다음 interval에서 그 관계가 유지·분리·합류·유입되었는가”를 정량화하는 observational layer이다.

> Dynamic Co-Wave는 kinase switching, direct kinase–substrate regulation, PTM→protein causal propagation 또는 pathway causality를 증명하지 않는다. 모든 output은 **observational, falsifiable candidate**로만 표현해야 한다.

| 구분 | Dynamic Co-Wave가 하는 일 | 하지 않는 일 |
|---|---|---|
| Static Wave | canonical Wave membership을 입력으로 사용 | Wave ID·membership·threshold를 변경하지 않음 |
| Kinase / TMM | TMM-weighted kinase inference와 병렬로 사용 | TMM coefficient·kinase ranking을 수정하지 않음 |
| PTM–protein layer | Wave→non-PTM protein temporal candidate의 보조 문맥 | direct regulation이나 causal arrow를 생성하지 않음 |
| Report / LLM | numerical evidence record로 전달하고 use 여부를 감사 | data가 없을 때 숫자·기전을 만들어내지 않음 |

## 2. Canonical 계산 정의

### 2.1 입력 및 qualification

입력은 canonical temporal Wave contract의 `timepoints`, `waves[].members`, `waves[].member_details[].temporal_values`이다. `dynamic_cowave_transition.py`는 static Wave에 이미 속한 member만 membership universe로 인정하고, timepoint 수가 충분한 trajectory만 계산에 사용한다. 기본 production configuration은 `ptm_shared/temporal_optimization_config.py`의 `DYNAMIC_COWAVE_CONFIG`에서 단일 진실원으로 관리된다.

| 항목 | Production 값 | 의미 |
|---|---:|---|
| `activity_threshold_fc` | `0.40` | production 및 no-config direct call 모두 동일; 각 local window 끝 시점의 absolute FC가 이 값 이상일 때 active |
| `minimum_observed_timepoints` | `4` | 관측치 부족 trajectory 제외 기준 |
| membership universe | `retained_canonical_wave_members_only` | static Wave 밖 site는 Dynamic Co-Wave에 포함하지 않음 |
| pair scope | `same_static_wave_only` | pair transition과 site partner count는 immutable static Wave 내부에서만 계산 |
| site event policy | `record_noninert_transitions_only` | state/group relation이 실제로 변한 site event만 transition artifact에 기록 |
| local window | 인접 timepoint 구간 | 예: `5min→15min`, `15min→30min` |
| stability | leave-one-timepoint-out | 한 timepoint를 제외하고 transition ID의 Jaccard를 계산 |
| stored examples | pair 500, site 500, membership 250 | metric은 full event set으로 계산하고 example만 cap 적용 |

low-level state는 다음 세 가지다. `value is None` 또는 `abs(value) < activity_threshold_fc`이면 `inactive`, 양수 임계치 이상이면 `positive_active`, 음수 임계치 이하이면 `negative_active`이다. **pair co-activity는 두 site가 모두 non-inactive이고 같은 sign일 때만** 성립한다. 단순 상관이나 two-point local change는 shared control의 증거로 취급하지 않는다.

### 2.2 Pair 및 site transition

각 adjacent window 쌍에서 full pair event와 site event를 만든다. **P0 v2에서는 pair transition과 site partner count를 동일 static Wave 내에서만 계산한다.** pair transition은 이전·다음 window 모두에서 co-active인지와 active/inactive state를 이용한다. site transition은 해당 site의 same-Wave partner 수 변화를 별도로 사용하며, `state_unchanged_or_inactive`는 transition event list에 넣지 않고 exposure count로 분리한다.

| 관찰 단위 | Event type | 계산적 정의 | 해석 가능한 최소 표현 |
|---|---|---|---|
| Pair | `persistence` | 두 window에서 모두 같은 sign co-active | local co-activity가 유지됨 |
| Pair | `split` | 이전에는 co-active, 다음에는 co-active 아님 | local co-activity가 분리됨 |
| Pair | `recruitment` | 다음 window에서 새 co-activity이고 이전에 한 member가 inactive | co-active pair가 새로 유입됨 |
| Pair | `merge` | 다음 window에서 새 co-activity이나 이전에 양쪽 모두 active | 이전에 분리된 active trajectories가 합류함 |
| Site | `exit` | active → inactive | 해당 site가 local active state에서 이탈 |
| Site | `independent_activation` | inactive → active, 이후 partner 0 | 동반 partner 없이 activation 관찰 |
| Site | `joined_group` | partner 0 → 1 이상 | 기존 local co-active group에 합류 |
| Site | `split_from_group` | partner 1 이상 → 0, 계속 active | active 상태이지만 group에서 분리 |
| Site | `group_persistence` | 전후 모두 partner 1 이상 | group-level local co-activity 유지 |

### 2.3 불변식과 reproducibility

`analyze_dynamic_co_wave_transitions()`은 계산이 끝난 뒤 `provenance.membership_mutation="forbidden"`, `provenance.tmm_mutation="forbidden"`을 저장한다. `effective configuration`과 SHA-256 hash, static Wave contract/config hash를 함께 저장해 cache freshness와 재현성을 확보한다. P0 v2는 config SHA와 contract version을 변경하므로 v1 cached dynamic output은 current contract로 간주하지 않는다. LOTO는 각 timepoint를 하나씩 제외하여 comparable pair/site transition ID의 Jaccard를 계산하며, mean pair/site Jaccard와 evaluable fold count를 sidecar에 저장한다.

## 3. Data lineage와 실행 구조

일반 full Order에서 RAG worker가 canonical global analysis를 실행하고 canonical heatmap/TMM/sidecar를 생성한다. API heatmap endpoint와 RAG worker는 같은 canonical scorer source를 사용한다. Dynamic Co-Wave는 sidecar builder가 static Wave와 TMM result를 받은 뒤 additive annotation으로 생성한다.

```text
Normalized PTM + non-PTM protein outputs
  → canonical temporal Wave contract
  → canonical TMM-weighted kinase heatmap / temporal cascade
  → build_production_temporal_ptm_protein_analysis()
      ├─ PTM→protein directed temporal candidates
      ├─ TMM kinase timing candidates
      ├─ dynamic co-wave transition annotation
      ├─ mechanism candidates + counterevidence
      └─ full sidecar JSON + compact projection
  → DB/API/UI/Report consumer
```

### 3.1 Sidecar 생성 및 persistence

`POST /orders/{order_id}/kinase-activity-heatmap`의 `api-server/app/api/orders.py`는 canonical heatmap/TMM 계산 후 `build_production_temporal_ptm_protein_analysis()`를 호출한다. 결과는 아래 두 곳에 저장된다.

| 저장 위치 | 내용 | 목적 |
|---|---|---|
| `${OUTPUT_DIR}/{order_code}/temporal_ptm_protein_analysis_v2.json` | full sidecar | 재현·다운로드·Report-only recovery용 artifact |
| `orders.kinase_activity_heatmap` | heatmap + compact sidecar projection | frontend/Report consumer |
| `orders.kinase_analysis_data` | compact sidecar projection | chat/Data-Grounded Analysis/legacy report handoff |

full artifact는 `GET /orders/{order_id}/temporal-ptm-protein-analysis`으로 조회한다. compact summary는 `summarize_temporal_ptm_protein_analysis()`가 만든 DB/API-context-safe projection이며 full event list가 아니라 summary와 bounded example만 포함한다.

### 3.2 Report-only rerun preflight

Report-only rerun은 이제 `orders.py::_temporal_evidence_readiness()`를 통해 아래 source 순서로 sidecar를 확인한다.

| 우선순위 | Source | `ready` 조건 |
|---:|---|---|
| 1 | `orders.kinase_analysis_data` | compact sidecar가 non-unavailable이고 `full_artifact_available=true` |
| 2 | `orders.kinase_activity_heatmap` | compact sidecar가 non-unavailable이고 `full_artifact_available=true` |
| 3 | `${OUTPUT_DIR}/{order_code}/temporal_ptm_protein_analysis_v2.json` | full artifact JSON이 readable |

`ready`인 경우 기존처럼 `report_generation.tasks.run_report_generation`을 바로 dispatch한다. `missing`인 경우 API는 `rag_enrichment.tasks.prepare_temporal_evidence_for_report`를 먼저 queue한다. 이 task는 enriched PTM JSON에서 `_auto_run_global_analysis()`를 재사용하고, canonical heatmap/TMM/full sidecar/compact DB projection이 성공적으로 생성되었을 때에만 matching heatmap과 함께 Report worker를 dispatch한다.

sidecar를 만들지 못하면 Order를 `failed`로 종료하고 Report 생성은 중지한다. 이는 evidence가 없는 상태에서 LLM이 static/general context만으로 그럴듯한 report를 만드는 것을 방지하는 failure semantics이다. Report worker가 numerical analysis를 독립적으로 다시 계산해서 lineage를 두 갈래로 만드는 방식은 금지한다.

## 4. Full sidecar와 compact summary schema

### 4.1 Full sidecar의 핵심 key

`enrichment_free_temporal_mechanism.v2.sidecar` full artifact는 다음 top-level key를 가진다.

| Key | 내용 | 해석 경계 |
|---|---|---|
| `temporal_wave_contract` | canonical static Wave와 member trajectory | Dynamic layer의 immutable input |
| `protein_time_series` | non-PTM protein condition-level time series | replicate-level stability는 current output에서 unavailable |
| `ptm_protein_pairs` | same-gene PTM–protein peak comparison | observational peak order only |
| `cross_layer_edges` | Wave→non-PTM protein lag-aware candidate | causal relation 아님 |
| `kinase_timing_predictions` | TMM profile 기반 kinase timing candidate | direct evidence 없으면 not evaluable |
| `dynamic_co_wave_transition` | Dynamic Co-Wave v1 annotation | local observed membership transitions only |
| `mechanism_chains` | kinase→Wave→protein evidence chain | ordered observation, not causal mechanism |
| `mechanism_counterevidence` | missing data anchor/network support/gate failure reason | causal promotion 차단 근거 |
| `provenance` | source, config, RAG/LLM/truth use flag | `rag_used=false`, `llm_used=false`, `benchmark_truth_used=false` |

### 4.2 Compact summary에서 Report가 직접 읽는 Dynamic fields

| Compact key | 설명 |
|---|---|
| `dynamic_co_wave_transition_status` | `computed`, `disabled_by_caller`, `not_requested` 등 |
| `dynamic_co_wave_transition_contract_version` | `dynamic_co_wave_transition.v1` |
| `dynamic_co_wave_transition_config_sha256` | effective config hash |
| `dynamic_transition_supported_wave_count` | non-persistence pair event가 있는 static Wave 수 |
| `dynamic_transition_pair_count` / `dynamic_transition_site_count` | full event set 기반 transition count |
| `dynamic_transition_resolution` | non-persistence pair / all pair transitions |
| `dynamic_transition_loto` | fold detail 및 mean pair/site Jaccard |
| `dynamic_transition_per_wave` | Wave별 pair/site transition count와 type histogram |
| `dynamic_transition_pair_scope` | qualified/group/pair count, excluded cross-Wave pair count, pair-window comparison count |
| `dynamic_transition_event_exposure` | site transition opportunity, inert observation, recorded non-inert transition count |
| `top_cross_layer_edges` | Wave, target, onset/peak lag, similarity, eligibility가 있는 bounded edge list |
| `top_mechanism_counterevidence` | chain ID, insufficient-evidence status, reason list |

## 5. TMM·cross-layer와의 관계

Dynamic Co-Wave와 TMM은 보완 관계이지만 동등하거나 서로를 덮어쓰는 관계가 아니다. TMM은 shared PTM trajectory를 candidate kinase profile의 contribution-weighted mixture로 해석하는 attribution layer이다. Dynamic Co-Wave는 static Wave 안에서 local same-sign co-activity와 transition을 요약한다. 따라서 “dynamic group이 바뀌었으므로 kinase가 switch했다”는 결론은 금지된다.

cross-layer edge는 Wave의 mean profile과 non-PTM protein trajectory에 `DirectedTemporalRelationship`을 적용한다. `source_precedes_target`, sufficient lag-aware similarity, LOTO stability threshold를 통과해야 `eligible_for_mechanism_chain=true`가 된다. 그래도 `causality_status="not_tested"`이며 network support는 별도 정보가 없으면 `not_evaluated`이다.

counterevidence는 failure가 아니라 intentional output이다. 대표 reason은 `kinase_timing_not_data_anchored`, `network_relation_not_evaluated`, `cross_layer_temporal_gate_failed`이다. Report는 evidence-supported mechanism candidate와 temporal candidate를 구분하고, counterevidence가 있으면 causal claim으로 올리지 않아야 한다.

## 6. Report / LLM 소비 계약

`workers/report_generation/core/dynamic_prompt_generator.py`가 compact sidecar와 matching heatmap을 `report_temporal_evidence_packet.v2`로 변환한다. packet은 plain prompt block이 아니라 record ID가 붙은 auditable numerical evidence 목록이다.

| Record ID | Payload |
|---|---|
| `DATA-TEMPORAL-SUMMARY` | protein trajectory, PTM–protein pair, edge, mechanism candidate count |
| `DATA-DYNAMIC-SUMMARY` | dynamic status, transition-supported Wave, pair/site count, resolution, LOTO Jaccard |
| `DATA-DYNAMIC-WAVE-*` | static Wave별 transition count와 pair/site transition type histogram |
| `DATA-TMM-KINASE-*` | persisted TMM cascade의 kinase, contribution-weighted activity, substrate support, direction, metric, evidence profile |
| `DATA-TMM-UNCERTAINTY` | persisted relative TMM uncertainty summary가 있을 때만 생성 |
| `DATA-CROSS-LAYER-*` | source Wave, target protein, onset/peak lag, similarity, eligibility |
| `DATA-COUNTEREVIDENCE-*` | mechanism chain failure/limitation reason |

Results와 Discussion prompt에는 available class마다 적어도 하나씩 사용하는 dedicated temporal-evidence paragraph를 요구한다. raw LLM draft는 `[DATA-*]` label을 보존한 채 fidelity audit을 거치며, available group의 citation이 누락되면 `review_required` 또는 `untraced`가 된다. 이 경우 Results/Discussion에는 deterministic numerical traceability addendum을 붙이고 재감사한다. 최종 DOCX에서는 internal label만 제거하고, label-bearing packet/fidelity snapshot은 운영 artifact로 유지한다.

| 출력 artifact | 목적 |
|---|---|
| `report_temporal_evidence_packet.json` | 실제 LLM input record와 status/record count 감사 |
| `temporal_report_fidelity.json` | section별 raw LLM/final status, cited/untraced/review required, fallback 여부 감사 |
| Order `result_files.temporal_evidence` / progress metadata | UI/API 레벨 운영 telemetry |

packet `status=unavailable`이면 Report는 temporal numerical claim을 만들 수 없고, fidelity `pass`는 “evidence를 잘 사용했다”가 아니라 “available record가 0개라 missing citation이 없다”는 뜻이다. 운영자는 반드시 `packet.status=available`과 `record_count>0`을 먼저 확인해야 한다.

## 7. Frontend behavior

`GET /orders/{id}`는 `temporal_evidence_readiness`를 반환한다. `RerunOptionsModal`은 kinase module badge와 별도로 다음 상태를 보여준다.

| UI 상태 | 사용자에게 보이는 문구 | 클릭 후 backend 동작 |
|---|---|---|
| `ready` | `Temporal evidence ready` | Report worker direct dispatch |
| `missing` | `Temporal evidence will be prepared before Report generation` | canonical preparation → Report chain |

`OrderDetail`은 missing일 때 confirm label을 `Confirm & Prepare Temporal Evidence + Re-run Report`로 바꾼다. 이 표시는 “kinase module exists”와 “temporal numerical evidence ready”를 의도적으로 구분한다.

## 8. 주요 source file map

| 파일 | 책임 |
|---|---|
| `ptm_shared/time_varying_comovement.py` | local state, window membership, optional group-scoped pair/site transition low-level algorithm |
| `ptm_shared/dynamic_cowave_transition.py` | static-Wave-scoped additive wrapper, provenance, LOTO, bounded example contract |
| `ptm_shared/temporal_optimization_config.py` | frozen config, SHA provenance, truth-free selection objective |
| `ptm_shared/tmm_multikinase_integration.py` | TMM-weighted cascade와 kinase directionality candidate |
| `ptm_shared/enrichment_free_temporal_sidecar.py` | full sidecar, cross-layer candidates, mechanism/counterevidence, compact summary |
| `api-server/app/api/orders.py` | heatmap persistence, sidecar API, readiness endpoint response, report-rerun preflight dispatch |
| `workers/rag_enrichment/tasks.py` | normal auto global analysis 및 `prepare_temporal_evidence_for_report` task |
| `workers/report_generation/core/temporal_sidecar_resolution.py` | DB/config/full artifact source priority로 Report state sidecar recovery |
| `workers/report_generation/core/dynamic_prompt_generator.py` | packet v2 record, section-specific instruction, fallback addendum |
| `workers/report_generation/core/report_temporal_fidelity.py` | `DATA-*` citation audit, required group audit, label stripping |
| `workers/report_generation/core/nodes/writer_node.py` | section writer, fallback integration, packet/fidelity artifact persistence |
| `workers/report_generation/tasks.py` | Report state assembly와 Order result/progress telemetry persistence |
| `frontend/src/components/KinaseModuleAnalysis.tsx` | sidecar summary display와 current temporal artifact readiness calculation |
| `frontend/src/components/RerunOptionsModal.tsx` | Report rerun readiness badge·user-facing warning |
| `frontend/src/pages/OrderDetail.tsx` | rerun modal orchestration와 dynamic confirm label |

## 9. Failure semantics 및 debugging 순서

### 9.1 정상 acceptance criteria

```text
GET /orders/{id}
  temporal_evidence_readiness.status == "ready"

${OUTPUT_DIR}/{order_code}/temporal_ptm_protein_analysis_v2.json
  exists and is readable

report_temporal_evidence_packet.json
  status == "available"
  record_count > 0

temporal_report_fidelity.json
  sections.results.packet_status == "available"
  sections.discussion.packet_status == "available"
```

availability는 모든 class가 항상 존재한다는 뜻이 아니다. sidecar에는 cross-layer edge가 없거나 TMM uncertainty가 없을 수 있다. 이 경우 packet은 해당 class를 만들지 않고 Report는 `not_evaluable` 또는 explicit limitation을 사용해야 한다. 없던 evidence를 fallback이 생성하는 것은 버그다.

### 9.2 권장 diagnosis 순서

1. `GET /orders/{id}`의 `temporal_evidence_readiness`부터 확인한다.
2. missing이면 Order log의 `temporal_evidence_preparation`과 `rag_enrichment` progress를 확인한다.
3. `temporal_ptm_protein_analysis_v2.json` 및 compact `orders.kinase_activity_heatmap.temporal_ptm_protein_analysis`를 확인한다.
4. Report 뒤에는 packet `status`와 `record_count`를 본다.
5. packet이 available이면 fidelity JSON의 raw LLM status, final status, `deterministic_addendum_applied`를 점검한다.
6. 마지막으로 DOCX prose를 확인한다. DOCX만 보고 packet delivery 또는 LLM uptake를 추정하지 않는다.

```bash
cd /path/to/ptm-platform
git pull --ff-only github main
docker compose up -d --build --force-recreate \
  api-server celery-worker-rag celery-worker-report frontend
docker compose logs --tail=200 celery-worker-rag celery-worker-report
```

### 9.3 절대 피해야 할 변경

| 금지 변경 | 이유 |
|---|---|
| Dynamic output으로 canonical Wave membership 변경 | frozen canonical Wave contract와 benchmark/production comparability 훼손 |
| Dynamic event로 TMM coefficient 또는 kinase rank 재가중 | local co-movement을 attribution/causality로 오해하게 됨 |
| Report worker 내부에서 arbitrary sidecar 재계산 | RAG/heatmap와 Report의 numerical lineage가 분리됨 |
| benchmark workbook/truth/locked score를 production sidecar 또는 packet에 전달 | strict-blind boundary 위반 |
| unavailable evidence를 generic pathway knowledge로 대체 | user data + allowed ChromaDB bounded Report 원칙 위반 |
| `temporal_report_fidelity.status=pass`만 보고 success 선언 | packet unavailable인 vacuous pass와 실제 evidence coverage를 혼동 |

## 10. Regression test map

| Test | 보호하는 계약 |
|---|---|
| `ptm_shared/tests/test_dynamic_cowave_transition.py` | membership/TMM 불변, v2 default/config hash, cross-Wave isolation, inert exposure 분리, single-Wave equivalence, LOTO, compact provenance |
| `workers/tests/test_tmm_multikinase_integration.py` | TMM contribution과 raw membership 분리, prior-assisted labeling, non-causal boundary |
| `workers/tests/test_temporal_sidecar_resolution.py` | DB/config/full artifact resolver priority와 matching heatmap handoff |
| `workers/tests/test_temporal_report_evidence_packet.py` | packet v2 records, section coverage, fallback, label-free final prose |
| `workers/tests/test_one_click_temporal_orchestration.py` | RAG→Report chain 및 temporal preparation task contract |
| `api-server/tests/test_report_temporal_readiness.py` | API readiness response, missing-sidecar preparation dispatch, UI indicator source contract |
| `api-server/tests/test_benchmark_v2_sidecar.py` | benchmark/production shared sidecar contract compatibility |

권장 검증 명령은 다음과 같다. optional iPTMnet live-test의 `aiohttp` dependency 문제는 Dynamic Co-Wave 수정의 결함과 분리해서 해석한다.

```bash
cd /path/to/ptm-platform
PYTHONPATH=workers:. pytest -q workers/tests \
  --ignore=workers/tests/test_iptmnet_live.py \
  --ignore=workers/tests/test_cross_species_iptmnet.py
PYTHONPATH=api-server:workers:. pytest -q api-server/tests
python3 -m py_compile \
  api-server/app/api/orders.py \
  workers/rag_enrichment/tasks.py \
  workers/report_generation/tasks.py
./frontend/node_modules/.bin/tsc --noEmit -p frontend/tsconfig.json
git diff --check
```

## 11. 다음 개발 시 의사결정 원칙

Dynamic Co-Wave의 개선은 **same static Wave 안에서 time-local state transition을 더 잘 관찰·quantify하는가**를 기준으로 판단한다. P0 v2의 non-inert event count와 site LOTO는 v1과 직접 수치 비교하면 안 되며, pre-P0 artifact는 canonical heatmap/TMM/sidecar를 다시 생성해야 한다. 새로운 event type, stability measure 또는 visualization을 추가할 수 있으나, canonical Wave/TMM/causal inference를 implicit하게 바꾸면 안 된다. 새로운 numerical parameter 또는 event semantics는 `temporal_optimization_config.py`에 versioned provenance와 config hash를 남기고, normal Order와 strict-blind runner가 같은 engine/config를 사용하도록 해야 한다.

Report quality 개선은 prompt만 길게 만드는 방식보다 packet availability, numerical record coverage, fidelity snapshot, and final-prose traceability를 함께 확인하는 방식으로 진행한다. 새 feature가 Report에서 보이지 않으면 먼저 sidecar artifact → compact persistence → Report resolver → packet status → fidelity → final DOCX 순서로 data lineage를 역추적한다.
