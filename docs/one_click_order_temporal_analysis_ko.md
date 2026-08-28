# One-Click Order Temporal PTM–Protein Analysis Contract

## 목적

일반 사용자는 Order를 한 번 시작한 뒤 Global Annotation, kinase heatmap, canonical Wave, TMM, PTM–protein sidecar, dynamic co-wave transition을 별도로 실행하거나 화면을 열어 둘 필요가 없다. 이 문서는 서버-side worker chain이 수치 분석을 완료하고, UI·Report·AI consumer가 동일 결과를 읽는 운영 계약을 정의한다.

## 실행 순서

| 순서 | 실행 주체 | 산출물 | 사용자 동작 |
|---|---|---|---|
| 1 | Preprocessing worker | normalized PTM/PG output, timepoint metadata | Order 시작 |
| 2 | RAG enrichment worker | enriched PTM table 및 Global Kinase Modules | 없음 |
| 3 | 같은 RAG worker | canonical TMM-weighted kinase heatmap | 없음 |
| 4 | 같은 RAG worker | canonical Wave, PTM–protein sidecar, dynamic transition artifact | 없음 |
| 5 | DB/API/UI/Report | compact summary와 full JSON artifact 소비 | 완료 후 조회/Report 생성 |

Preprocessing은 `run_temporal_ptm_protein_analysis=true`를 기본값으로 RAG stage에 전달한다. Admin-started 및 user-created Order는 동일한 default를 사용한다. RAG worker는 API heatmap endpoint와 동일한 canonical TMM scorer source를 read-only mount로 import하며, 별도의 worker-specific TMM implementation을 유지하지 않는다.

## Artifact 및 progress

분석이 완료되면 preprocessing output directory에 `temporal_ptm_protein_analysis_v2.json`이 기록된다. DB heatmap cache와 `kinase_analysis_data`에는 full artifact가 아니라 provenance-rich compact summary만 저장한다. API의 `GET /orders/{order_id}/temporal-ptm-protein-analysis`는 authenticated full artifact retrieval을 제공한다.

진행 상태는 기존 `rag_enrichment` stage 안에서 `global_analysis`, `temporal_ptm_protein_analysis`, 또는 report rerun preflight의 `temporal_evidence_preparation` step으로 전달된다. 사용자에게는 canonical Wave, TMM, PTM–protein analysis, dynamic co-wave transition이 생성 중이라는 메시지와 완료 메시지가 표시된다. 새 coarse-grained Order status를 추가하지 않아 기존 queue/status contract를 보존한다.

## Cache와 재실행

정상 Order start는 server-side에서 current temporal artifact를 생성한다. 기존 legacy cache에는 frozen dynamic configuration SHA가 없으므로, 현재 heatmap을 요청할 때 cache freshness 검사가 이를 감지하고 current shared contract로 재계산한다. UI의 **Re-run Global Annotation** 또는 Refresh는 수동 재계산/diagnostic 용도이며 normal Order completion의 필수 단계가 아니다.

### Report-only rerun preflight

Report만 재생성할 때는 kinase module의 존재만으로 temporal numerical evidence가 준비되었다고 간주하지 않는다. API는 다음 source를 순서대로 확인하여 `temporal_evidence_readiness`를 Order Detail과 Rerun modal에 반환한다.

| Readiness source | `ready` 기준 |
|---|---|
| `orders.kinase_analysis_data` | non-unavailable compact sidecar + `full_artifact_available=true` |
| `orders.kinase_activity_heatmap` | non-unavailable compact sidecar + `full_artifact_available=true` |
| output directory | readable `temporal_ptm_protein_analysis_v2.json` full artifact |

`ready`이면 기존처럼 Report worker만 dispatch한다. `missing`이면 버튼과 modal은 **“Temporal evidence will be prepared before Report generation”**을 표시하고, backend는 `rag_enrichment.tasks.prepare_temporal_evidence_for_report`를 먼저 queue에 넣는다. 이 task는 enriched PTM JSON에서 기존 canonical global analysis를 재사용하여 heatmap/TMM/full sidecar/compact DB projection을 만들고, full artifact가 확인된 경우에만 matching heatmap과 함께 Report worker를 dispatch한다.

따라서 legacy Order의 “Re-run Report Generation”은 더 이상 빈 evidence packet Report로 즉시 끝나지 않는다. temporal preparation이 실패하면 Report 생성은 중단되고 Order는 `failed` 상태와 actionable error message를 남긴다. Report worker가 자체적으로 수치를 재계산하지 않으므로 numerical lineage는 canonical RAG/heatmap path 하나로 유지된다.

## Failure semantics 및 claim boundary

PTM–protein sidecar는 non-fatal downstream artifact이다. normalized protein output의 부재, incomplete temporal vector 또는 sidecar-specific exception이 있을 때 기존 Global Annotation/heatmap/TMM result는 보존하고 compact summary는 `status=unavailable`, `causality_status=not_tested`를 기록한다. Dynamic co-wave transition은 local co-movement의 observational annotation이며 kinase switching, direct kinase identity, or causal propagation의 증거가 아니다.

## Target-server deployment checks

배포 전에 worker image와 compose runtime을 재기동해야 한다. RAG worker service에는 `./api-server/app:/opt/api_server_app:ro` mount와 `PYTHONPATH=/app:/opt:/opt/api_server_app`가 포함되어야 한다.

```bash
git pull --ff-only github main
docker compose config --quiet
docker compose up -d --build celery-worker-rag api-server frontend
docker compose logs --tail=200 celery-worker-rag
```

신규 test Order에서 `temporal_ptm_protein_analysis` 또는 `temporal_evidence_preparation` progress message, `tmm_execution_status=computed`, `temporal_ptm_protein_analysis_v2.json`, compact `full_artifact_available=true`를 확인한다. Report rerun acceptance criteria는 다음과 같다.

```text
GET /orders/{id}
  temporal_evidence_readiness.status == "ready"

report_temporal_evidence_packet.json
  status == "available"
  record_count > 0

temporal_report_fidelity.json
  sections.results.packet_status == "available"
  sections.discussion.packet_status == "available"
```

가능한 numerical evidence class는 실제 persisted sidecar/TMM에 한정된다. TMM, uncertainty, counterevidence가 없으면 새 값을 만들지 않으며, final prose는 dynamic co-wave/lag를 kinase switching 또는 causal propagation으로 과장하지 않아야 한다.
