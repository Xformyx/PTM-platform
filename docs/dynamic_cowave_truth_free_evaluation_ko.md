# Dynamic Co-Wave Transition: Truth-Free 후보 평가 및 채택 기록

## 목적과 분석 경계

본 평가는 고정된 canonical Wave 내부에서 시간 구간별 PTM membership이 지속, 분리, 병합, 유입 또는 이탈하는 양상을 별도 annotation으로 기록하는 것이 유용한지를 평가하였다. 분석에는 normalized numeric PTM/PG time-course, numeric time axis, canonical Wave, TMM 결과 및 기존 cross-layer observational edge만 사용하였다. Reference workbook, anchor, stimulus identity, biological question, RAG, LLM 및 알고리즘 예측으로부터 생성된 truth는 후보 선택에 사용하지 않았다.

Dynamic co-wave는 static Wave membership이나 TMM contribution을 대체하지 않는다. 각 adjacent timepoint interval에서 같은 static Wave의 두 site가 activity threshold를 넘고 같은 부호를 가질 때만 local co-active pair로 계산하였다. site 또는 pair의 상태 변화는 observed temporal membership transition이며, kinase switching이나 인과 전파를 증명하지 않는다.

## 사전등록 후보와 채택 기준

후보는 activity threshold만 달리한 세 구성으로 사전등록하였다. 모든 후보는 minimum observed timepoint 4, retained canonical Wave member만 사용하는 universe, leave-one-timepoint-out(LOTO) stability를 공유하였다. 선택 목적함수는 pair LOTO Jaccard 0.45, site LOTO Jaccard 0.25, local active-pair coverage 0.20, transition resolution 0.10의 가중합이었다. Static membership/TMM 불변성, primary semantic noninferiority, compact serialization이 반드시 유지되어야 했다.

| 후보 | Activity threshold (absolute log2FC) | Pair LOTO Jaccard | Site LOTO Jaccard | Local active-pair coverage | Transition resolution | Objective | 판정 |
|---|---:|---:|---:|---:|---:|---:|---|
| dynamic_cowave_activity_040 | 0.40 | 0.7102 | 0.7222 | 0.3002 | 0.7519 | **0.6354** | 선택 |
| dynamic_cowave_activity_050 | 0.50 | 0.7068 | 0.7222 | 0.2440 | 0.7700 | 0.6245 | 기각 |
| dynamic_cowave_activity_060 | 0.60 | 0.7017 | 0.7222 | 0.1753 | 0.7866 | 0.6101 | 기각 |

선택된 0.40 구성은 사전등록 objective가 가장 높았고, 모든 채택 gate를 통과했다. 선택 record SHA-256은 `2d12157f12eed4a3322a9a0253257352003e84044534d53dec03336770b1a08e`이며, 12-record strict-blind ledger의 SHA-256은 `02ab551eb3c345250fa1e76758599e18026fa6b8c72889d95b7c533ebede882e`이다.

## 선택 구성의 실제 output

선택 구성은 8개 모든 retained static Wave에서 transition-support를 보고했다. Complete event set으로 계산한 결과는 pair transition 105,538개, site transition 3,336개, local membership observation 4,170개였다. Cross-layer observational edge 중 dynamic time axis와 aligned된 row는 1,155개(72.1875%)였다.

Complete event를 artifact에 모두 저장하면 payload가 과도하게 커지므로, metric과 LOTO 계산에는 전 event set을 사용하되 artifact에는 deterministic pair example 최대 500개, site example 최대 500개, membership example 최대 250개 및 per-Wave complete count만 저장한다. 이 제한은 engineering serialization policy이며 threshold selection parameter가 아니다.

## 견고성 및 한계

LOTO 평균은 pair 0.7102, site 0.7222였다. 그러나 15분 또는 30분을 제외하는 일부 fold의 pair Jaccard는 각각 0.3658 및 0.2348로 낮았다. 이는 6개 timepoint에서 intermediate transition boundary의 해상도가 제한적임을 뜻한다. 따라서 dynamic annotation은 discrete state transition의 확정 판정이 아니라, 후속 dense time-course 또는 replicate-resolved protein trajectory에서 확인할 observational priority signal로 해석해야 한다.

현재 PG layer는 condition-level summary이므로 dynamic PTM membership과 protein trajectory 사이의 replicate-level concordance는 검증하지 않았다. 또한 direct kinase-site evidence와 positive same-kinase TMM contribution의 연결은 여전히 없어 data-anchored kinase timing accuracy는 `not_evaluable` 상태를 유지한다.

## 채택 범위

Dynamic co-wave transition은 production Order와 strict-blind benchmark가 공유하는 PTM–protein sidecar의 기본 additive annotation으로 채택되었다. API/DB에는 compact summary와 full artifact path를 저장하며, UI 및 report evidence packet은 status, transition-supported Wave 수, pair count를 표시한다. Canonical static Wave membership, TMM output, kinase ranking, primary score 및 runner-only locked scoring contract에는 변경을 가하지 않는다.

## Current-commit 재실행 및 acceptance 검증

채택 commit의 current code에서 normalized numeric vector 및 mixed-species FASTA와 frozen truth-free TMM output만으로 artifact를 다시 생성하였다. 재생성 artifact SHA-256은 `ba62202d9564cfa3bc0b1844145da963858465ff5e58ac79038ad41837ef0e02`이며, artifact는 2,447 site observation, 8 canonical Wave, 55 TMM profile을 유지했다. Dynamic annotation은 transition-supported Wave 8개, pair LOTO 0.7102, site LOTO 0.7222, compact pair example 500/complete pair transition 105,538개를 기록했다.

Immutable v1 golden semantic noninferiority verifier와 dynamic-aware server handoff verifier는 모두 통과했다. Primary score는 0.7333으로 유지됐으며, runner-only optional reference evaluation에서 53개의 workbook-derived curated kinase-output target은 descriptive mechanism reference로만 평가되었다. Curated PTM Wave→non-PTM protein relation과 lag/direction truth가 workbook에 없으므로 cross-layer recovery는 여전히 `not_evaluable`이다.

Python regression 30개, TypeScript compiler, Vite production build가 통과했다. Production service에는 locked truth/optional truth adapter/scorer import가 없음을 별도로 검사했다. 따라서 dynamic transition은 production analysis의 truth-free numerical annotation이며, workbook reference는 artifact freeze 이후 runner-only evaluation에만 사용된다.
