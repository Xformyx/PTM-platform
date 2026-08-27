# Report LLM Numerical Evidence Contract

## 목적

이 계약은 PTM 플랫폼의 최종 Report가 temporal 분석 결과를 일반적인 pathway narrative로 바꾸는 과정에서 수치·시간축·불확실성·관찰 경계를 잃지 않게 한다. LLM은 PTM site, canonical Wave, TMM, PTM–protein temporal sidecar, dynamic co-wave transition이 생성한 **결정론적 evidence packet**을 먼저 받고 그 범위 안에서만 결과를 서술한다.

이 계약은 benchmark truth를 Report에 전달하지 않는다. benchmark는 알고리즘 및 report-fidelity의 오프라인 평가에만 사용하며, 일반 Order Report는 해당 Order의 numerical artifact와 ChromaDB/RAG evidence만 사용한다.

## 생성 및 전달 흐름

```text
Order numerical analysis
  → canonical Wave + TMM + PTM–protein sidecar + dynamic transition
  → compact DB summary
  → report temporal evidence packet
  → Results / Research Questions / Discussion / Conclusion / Abstract prompts
  → per-section report-fidelity audit
  → final Report prose + auditable JSON snapshot
```

`temporal_ptm_protein_analysis_v2.json`의 compact summary는 `build_temporal_evidence_packet()`에서 아래 4종의 record로 변환된다.

| Record type | Internal ID | 포함 내용 | Claim tier |
|---|---|---|---|
| 전체 요약 | `DATA-TEMPORAL-SUMMARY` | protein trajectory, PTM–protein pair, edge, eligible edge, mechanism count | observational |
| 동적 전이 요약 | `DATA-DYNAMIC-SUMMARY` | supported Wave 수, pair/site transition 수, resolution, LOTO 평균 | observational |
| Wave별 전이 | `DATA-DYNAMIC-WAVE-n` | persistence, split, merge, recruitment, exit count 및 Wave별 transition 규모 | observational |
| PTM→protein 후보 | `DATA-CROSS-LAYER-n` | source Wave, target protein, onset/peak lag, direction, similarity, eligibility, causality status | observational / hypothesis |

동적 전이와 cross-layer record는 deterministic ordering과 최대 개수를 사용한다. 전체 raw event를 LLM에 전달하지 않으므로 context overflow를 줄이되, complete aggregate와 top candidate의 수치적 provenance는 보존한다.

## LLM 작성 규칙

Results, Research Question Answers, Discussion, Conclusion, Abstract에서는 `temporal_evidence_packet`을 large vector-plot 및 lower-priority context보다 먼저 넣는다. 따라서 기존 budget selector가 긴 vector table 때문에 temporal PTM–protein 근거를 건너뛰는 문제를 방지한다.

LLM에는 internal record ID를 문장에 붙여 traceability를 남기도록 지시한다. 초안 생성 직후 `report_temporal_fidelity`가 ID 존재 여부와 evidence-linked unsafe causal wording을 검사한다. 최종 사용자-facing prose에서는 internal `DATA-*` label을 제거하지만, `report_temporal_evidence_packet.json`과 state의 `temporal_report_fidelity`에는 어떤 packet이 전달됐고 어느 section이 trace되지 않았는지가 남는다.

| 허용 표현 | 금지 표현 |
|---|---|
| “temporal co-movement와 정합적이다” | “kinase switching을 증명한다” |
| “후행 protein trajectory가 관찰되었다” | “PTM Wave가 protein 변화를 유발했다” |
| “observational mechanism hypothesis” | “causal propagation이 입증되었다” |
| “direct evidence가 없으므로 not evaluable” | motif/TMM만으로 “direct target” 확정 |

## Report fidelity audit

각 section은 다음 status를 얻는다.

| Status | 의미 | 운영 처리 |
|---|---|---|
| `pass` | 유효한 packet record만 인용했고 unsafe causal phrase 없음 | 정상 생성 |
| `untraced` | packet은 있었지만 LLM이 record label을 전혀 사용하지 않음 | report QA review 권고 |
| `review_required` | 존재하지 않는 record ID 또는 evidence-linked causal wording 발견 | QA review 필요 |
| `unavailable` packet | 해당 Order에 temporal sidecar 없음 | temporal PTM–protein claim 생성 금지 |

이 audit은 biological truth score가 아니다. LLM prose가 supplied numerical record에 추적 가능한지와 claim boundary를 지켰는지만 측정한다.

## 현재 artifact replay 확인

final selected dynamic co-wave artifact에서 만든 packet은 22 records, 6,065 characters였다. 구성은 전체 요약 1개, dynamic summary 1개, Wave별 record 8개, cross-layer record 12개였다. 이 packet-generation audit은 workbook truth, locked score, RAG context, LLM을 읽거나 호출하지 않았다.

## 운영 및 재현성

Order server-side chain이 canonical Wave/TMM와 `temporal_ptm_protein_analysis_v2.json`을 먼저 생성한 뒤 Report를 실행해야 한다. `output_dir`가 있는 Report에는 `report_temporal_evidence_packet.json`을 저장한다. report-fidelity status가 `untraced` 또는 `review_required`이면 artifact와 section draft를 함께 QA 대상으로 표시해야 하며, numerical packet 자체를 재해석하거나 algorithm score를 변경해서는 안 된다.

## 제한

현재 PG protein profile이 condition-level summary이면 protein-level replicate stability를 주장할 수 없다. 6개 timepoint에서의 dynamic transition은 temporal reorganization 후보이지 kinase switching 또는 인과성의 증거가 아니다. direct kinase timing이 site-level direct evidence와 positive TMM contribution으로 연결되지 않으면 timing accuracy를 계산하지 않는다.
