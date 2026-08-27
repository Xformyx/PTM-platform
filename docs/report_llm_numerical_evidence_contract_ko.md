# Report LLM 정량 Temporal Evidence 계약 v2

## 목적과 적용 범위

이 계약은 PTM 플랫폼의 최종 Report가 temporal 분석 산출물을 일반적인 pathway narrative로 대체하는 과정에서 **수치, 시간축, 불확실성, 반증 근거 및 관찰 연구의 한계**를 잃지 않게 한다. 일반 Order의 Report LLM은 canonical Wave, contribution-weighted TMM, PTM→protein cross-layer temporal sidecar, dynamic co-wave transition에서 결정론적으로 생성된 evidence packet만을 수치 temporal 근거로 사용한다.

이 계약은 benchmark truth, locked workbook, locked score, benchmark label을 Report LLM에 전달하지 않는다. benchmark는 공용 production numerical engine을 오프라인으로 평가할 수 있으나, 일반 Order Report의 생물학적 해석은 해당 Order의 사용자 데이터와 허용된 ChromaDB/RAG context 안에 한정한다.

> Dynamic co-wave 전이, TMM contribution, PTM→protein lag는 모두 **observational evidence**이다. 이들은 kinase switching, 직접 kinase-substrate 조절, PTM이 protein 변화를 유발했다는 인과성을 증명하지 않는다.

## 생성·전달·감사 흐름

```text
Order numerical analysis
  → canonical Wave + TMM-weighted temporal cascade
  → PTM–protein sidecar + dynamic co-wave transition + counterevidence
  → compact DB-safe summary
  → report temporal evidence packet v2
  → Results / Research Questions / Discussion / Conclusion / Abstract prompt
  → raw LLM-draft fidelity audit
  → Results·Discussion fallback addendum if required
  → label-free final Report + packet/fidelity JSON snapshots + Order telemetry
```

packet builder는 sidecar와 `state['kinase_activity_heatmap']['tmm_weighted_temporal_cascade']`만 사용한다. legacy raw heatmap score만 존재하고 persisted contribution-weighted cascade가 없으면 TMM candidate record를 임의로 만들지 않는다. 마찬가지로 persisted uncertainty 또는 counterevidence가 없으면 해당 record class를 만들지 않으며, LLM에게 없는 값을 채우도록 요구하지 않는다.

## Packet record schema

| Record class | Internal ID | 포함하는 수치·상태 | 사용 경계 |
|---|---|---|---|
| 전체 scope | `DATA-TEMPORAL-SUMMARY` | protein trajectory, same-gene PTM–protein pair, edge, eligible edge, mechanism candidate, kinase timing status | 관찰 범위 요약 |
| Dynamic 요약 | `DATA-DYNAMIC-SUMMARY` | transition-supported Wave 수, pair/site transition 수, resolution, pair/site LOTO 평균 | local membership 변화의 안정성 |
| Wave별 전이 | `DATA-DYNAMIC-WAVE-n` | static Wave, pair/site transition, persistence/split/merge/recruitment/exit count | Wave-interval 특이 관찰 |
| TMM 후보 | `DATA-TMM-KINASE-n` | kinase, timepoint, selected contribution-weighted activity, raw weighted activity, substrate support, direction, metric, evidence profile | 후보 attribution; direct proof 아님 |
| TMM 불확실성 | `DATA-TMM-UNCERTAINTY` | persisted relative TMM uncertainty summary | ranking/추정 안정성의 제한 |
| PTM→protein 후보 | `DATA-CROSS-LAYER-n` | source Wave, target protein, onset/peak lag, direction, lag-aware similarity, mechanism eligibility, temporal interpretation | temporal precedence 후보; causality=`not_tested` |
| 반증 근거 | `DATA-COUNTEREVIDENCE-n` | chain ID, insufficient-evidence status, observed limitation reason | 대안 설명·불충분성 명시 |

Record는 deterministic ordering과 bounded count를 사용한다. raw event 전체를 LLM에 보내지 않아 context overflow를 낮추되, Results와 Discussion이 필요한 numerical layer를 선택적으로 잃지 않게 한다.

## Section별 필수 사용 규칙

모든 temporal section은 evidence packet을 large vector plot과 lower-priority context보다 앞선 priority로 prompt에 넣는다. Results와 Discussion에는 packet formatter가 다음을 명시적으로 지시한다.

| Evidence class가 packet에 존재하는 경우 | Results / Discussion에서 필요한 처리 |
|---|---|
| Dynamic | 적어도 하나의 dynamic summary 또는 Wave-specific transition을 수치와 함께 서술 |
| TMM candidate | 적어도 하나의 candidate의 contribution-weighted activity, support 또는 metric을 조건부 표현으로 서술 |
| PTM→protein | 적어도 하나의 source Wave, target, onset/peak lag 또는 lag-aware similarity를 관찰 표현으로 서술 |
| Counterevidence | 적어도 하나의 insufficient evidence 또는 대안 설명을 limitation으로 서술 |
| 해당 class 부재 | 값을 보완·추정·환각하지 않고 `not_evaluable` 또는 현재 data limitation으로 명시 |

Research Question Answers, Conclusion, Abstract는 해당 section에 필요한 record를 사용하되, Results/Discussion처럼 모든 available class를 동시에 강제하지 않는다. LLM draft에서는 추적성을 위해 `[DATA-*]` label을 문장 끝에 남기게 하며, 최종 DOCX/HTML/Markdown에서는 label을 제거한다.

## Fidelity audit과 deterministic fallback

`audit_report_temporal_fidelity()`는 supplied record ID, unsafe causal wording, section type, available evidence class, missing required class를 검사한다. Results/Discussion에서 raw LLM draft가 `untraced` 또는 `review_required`이면, writer는 동일 packet에서 만든 **label-bearing deterministic temporal-evidence traceability addendum**을 원문 뒤에 넣고 다시 감사한다. label은 최종 사용자-facing Report에서 제거되지만, 수치와 관찰 경계는 남는다.

| Final fidelity status | Raw LLM-draft status | 의미와 운영 조치 |
|---|---|---|
| `pass` | `pass` | LLM 자체가 available numerical evidence classes를 traceable하게 사용함 |
| `pass` | `untraced` 또는 `review_required`, `deterministic_addendum_applied=true` | final Report에는 deterministic evidence가 보존되었으나 LLM 자체가 필요한 class를 누락했음; prompt/model QA 대상으로 기록 |
| `review_required` | `review_required` | unsupported record ID 또는 causal overclaim 등 fallback으로 해결되지 않은 문제가 남음; delivery 전에 QA 필요 |
| `unavailable` | `unavailable` | temporal sidecar가 없음; temporal PTM–protein/TMM/dynamic 결과를 만들어서는 안 됨 |

`llm_draft_status`와 `llm_draft_missing_required_groups`는 fallback 후에도 원본 LLM output의 failure mode를 보존한다. 따라서 final Report가 안전하게 보정되었더라도 “LLM이 실제로 evidence를 소비했는가”를 운영자가 구분할 수 있다.

## 저장 artifact와 Order telemetry

`output_dir`가 있는 새 Report run은 아래 파일을 저장한다.

| 파일 | 목적 |
|---|---|
| `report_temporal_evidence_packet.json` | LLM에 넣은 structured numerical records, contract version, source artifact path |
| `temporal_report_fidelity.json` | section별 final status, raw LLM-draft status, cited/available record count, missing classes, unsafe claim count, deterministic fallback 여부 |

Order `result_files.temporal_evidence` 및 완료 progress metadata에는 `packet_status`, `record_count`, `section_status`, `llm_draft_section_status`, `review_required_sections`, `llm_draft_review_required_sections`, `llm_draft_untraced_sections`, `deterministic_addendum_sections`, `packet_snapshot`, `fidelity_snapshot`가 들어간다. 기존 Order Detail의 Data Files 목록은 JSON snapshot을 일반 결과 파일처럼 preview/download할 수 있다.

## 검증 기준

실제 `final_adopted_dynamic_cowave` integrated temporal artifact를 packet audit으로 재생성했을 때 packet은 **33 records, 11,454 formatted prompt characters**였고 Dynamic, TMM candidate, TMM uncertainty, cross-layer, counterevidence class가 모두 존재했다. 이 offline audit은 sidecar와 persisted TMM fields만 읽고 workbook truth, locked score, RAG context, LLM output을 읽거나 호출하지 않는다.

회귀 검증은 packet class presence/absence, raw-heatmap-only TMM 억제, Results mandatory coverage, label stripping, fallback audit, writer heatmap 연결, snapshot/Order telemetry persistence를 포함한다. production packet/report 경로에 benchmark truth reader import가 없는지도 별도로 검사한다.

## 운영 반영 및 새 Report 검증 절차

새 코드를 pull한 뒤 Report worker를 재기동한다. 이 compose 구성에서는 Report worker service name이 `celery-worker-report`이며, worker와 shared sidecar는 source volume mount를 사용하지만 Celery process는 재시작해야 새 Python module을 읽는다.

```bash
cd /path/to/ptm-platform
git pull --ff-only github main
docker compose up -d --force-recreate celery-worker-report
docker compose ps celery-worker-report
docker compose logs --tail=200 celery-worker-report
```

그 다음 **새 Order Report를 생성**하고 다음을 확인한다. 기존 19:00 DOCX는 소급해서 바뀌지 않으므로, 그 파일에 개선 효과가 있었다고 주장해서는 안 된다.

1. 결과 파일에 `report_temporal_evidence_packet.json`과 `temporal_report_fidelity.json`이 있는지 확인한다.
2. packet의 record class가 해당 Order의 persisted sidecar/TMM에 맞는지 확인한다. 없던 TMM·uncertainty·counterevidence가 새로 생기면 안 된다.
3. fidelity snapshot의 Results와 Discussion에서 final `status`, `llm_draft_status`, `missing_required_groups`, `deterministic_addendum_applied`를 함께 확인한다.
4. final prose가 Wave interval/type/count/stability, TMM conditional contribution/support/uncertainty, PTM→protein lag/direction/similarity, counterevidence를 **available data 범위에서** 실제로 서술하는지 semantic QA 한다.
5. temporal observation을 causal propagation, direct regulation, kinase switching으로 과장하지 않았는지 확인한다.

## 제한

PG protein profile이 condition-level summary라면 protein-level replicate stability를 주장할 수 없다. 6개 timepoint에서 관찰된 dynamic transition은 local co-wave membership 변화 후보이며 kinase switching 또는 인과성의 증거가 아니다. site-level direct evidence와 positive TMM contribution이 연결되지 않은 kinase timing은 `not_evaluable`로 남겨야 하며, timing accuracy를 산출하거나 direct target으로 확정해서는 안 된다.
