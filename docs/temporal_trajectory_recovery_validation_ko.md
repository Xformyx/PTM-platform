# Temporal Trajectory Recovery 및 Report Claim Gate 검증 기록

**기준 커밋:** `316412f`에서 분기한 implementation branch
**검증 목적:** RAG collapse 이후에도 실제 multi-timepoint PTM trajectory를 canonical temporal layer로 전달하고, recovery된 Dynamic Co-Wave/cross-layer/event evidence가 Report에서 evidence-supported observational wording으로만 소비되는지 검증한다.

## 1. 발견한 손실과 복구 원칙

Insulin V3의 RAG-collapsed PTM records는 각 site/form의 `condition_data` 안에 1/5/15/30/60/180분 정량값을 보존하고 있었다. 그러나 기존 `_build_relative_ptm_timeseries()`는 top-level primary row의 단일 `Condition`을 읽어 2,447개 PTM site 모두를 one-timepoint series로 축소했다. 이 때문에 canonical complete-case Wave projection의 eligible site가 0이 되었고, Wave/Dynamic/cross-layer/precedence evidence가 계산 불가로 나타났다.

새 shared reconstructor는 다음 source priority를 사용한다.

| 우선순위 | Source | 처리 |
|---:|---|---|
| 1 | canonical temporal input bundle | preprocessing이 저장한 versioned normalized site×timepoint input을 그대로 사용 |
| 2 | collapsed `condition_data` | same site/form의 declared grid 값을 deterministic하게 복원 |
| 3 | site-form observation aggregate | duplicate site/form은 timepoint별 median으로 집계하고 provenance를 저장 |

결측값은 biological zero로 바꾸지 않는다. reconstruction provenance는 source type, declared grid, site/form aggregation과 input hash만 보존하며 raw replicate values, benchmark truth, locked score, RAG prose, LLM output은 sidecar/Report에 기록하지 않는다.

## 2. 동일 raw insulin input의 sandbox recovery

동일 normalized insulin input의 direct replay에서 2,447 input site 중 2,022개가 6개 모든 timepoint를 실제로 갖고 있었다. collapsed `condition_data` route를 통해 이 coverage가 정확히 복원됐다. frozen canonical configuration을 변경하지 않은 replay 결과는 다음과 같다.

| Layer | Recovery result | Claim ceiling |
|---|---:|---|
| Canonical Wave | 656 members; 8 Waves | observed co-trajectory module |
| Dynamic Co-Wave v2 | 59,348 pair transitions | local same-Wave reorganization only |
| Cross-layer PTM→protein | 1,600 candidate edges | observed lag/direction/similarity candidate |
| Event descriptor | 656 sites; 491 resolved | condition-mean timing descriptor |
| Temporal precedence | computed; 615 evaluable records | observed timing only |

이 수치는 causal propagation, direct kinase–substrate regulation 또는 kinase switching을 확립하지 않는다.

## 3. Report packet v4 및 claim gate

recovered compact sidecar는 `report_temporal_evidence_packet.v4`에서 27개의 typed `DATA-*` records로 전달됐다. local Dynamic evidence와 directed receptor/kinase mechanism evidence는 분리한다.

| Gate | Required computed layers | Effect |
|---|---|---|
| `dynamic_context_allowed` | Dynamic Co-Wave pair transitions | local co-movement/reorganization wording만 허용 |
| `directed_temporal_context_allowed` | TMM kinase + cross-layer + temporal precedence | directionality, receptor/kinase cascade, signal propagation context 허용 |
| `mechanism_context_allowed` | directed gate와 동일 | base prompt의 receptor/temporal-kinase fields 전달 여부 |

이번 insulin recovery audit에는 persisted TMM evidence record가 없어 Dynamic/cross-layer/precedence는 computed였으나 directed mechanism gate는 false였다. 따라서 Results/Discussion/Conclusion/Abstract에서 generic receptor cascade, temporal kinase cascade, signal propagation, timelag, mechanism few-shot example은 전달되지 않고, Dynamic/Cross-layer record의 allowed verb만 남는다. Introduction과 Methods의 study framing은 보존한다.

## 4. Rewrite 및 release telemetry

Results/Discussion draft가 available evidence class를 인용하지 않거나 unsafe temporal claim을 포함하면 writer는 deterministic addendum을 붙이지 않는다. 원 draft와 packet을 함께 제공해 0-temperature constrained rewrite를 한 번 요청하고 재감사한다. rewrite 뒤에도 high-severity unsafe claim이 남으면 section status는 `blocked_for_review`, `release_blocked=true`가 된다.

task metadata는 `blocked_for_review_sections`, `constrained_rewrite_sections`, `release_status`를 저장한다. draft fidelity는 traceability/wording audit이지 biological correctness 또는 causality validation이 아니다.

## 5. Validation

다음 targeted tests 및 compilation이 통과했다.

```text
135 passed
6 passed (benchmark runtime-boundary)
python3 -m compileall -q ptm_shared workers/rag_enrichment workers/report_generation api-server/app
```

raw insulin recovery audit에서는 packet v4 record count=27, Dynamic/Cross-layer/precedence computed, `dynamic_context_allowed=true`, `directed_temporal_context_allowed=false`, `mechanism_context_allowed=false`가 확인됐다.

## 6. 남은 범위와 운영 요구사항

이 branch는 source reconstruction과 Report evidence gating을 검증했다. 실제 deployed Order에서 raw replicate bootstrap confidence를 얻으려면 preprocessing output의 replicate matrix locator가 canonical input bundle과 함께 보존되어야 한다. historical Order는 bundle이 없을 수 있으므로 collapsed `condition_data` fallback을 사용하며, source/provenance status를 Report에 남긴다.

strict runner-only locked scorer manifest는 현재 sandbox archive에서 발견되지 않아 primary score를 이번 branch에서 재계산하지 않았다. 본 변경은 benchmark scorer/locked contract를 변경하지 않으며, runtime-boundary regression이 runner isolation을 확인했다. deployment 전에는 user environment의 existing manifest로 canonical score non-regression을 재확인한다.
