# HIRc-B Insulin 리포트 회귀 분석: 2026-08-28/29 대비 2026-09-14

작성일: 2026-09-14  
분석 성격: 결과 열람 후 원인 진단 및 탐색적 품질 감사. Benchmark primary 판정이나 kinase 성능 검증이 아니다.

## 1. 결론

최근 리포트가 짧고 Kinase 설명이 빈약해진 주원인은 분석 알고리즘이 의미 없는 신호를 제거했기 때문이 아니다. 같은 정량 데이터가 대부분 그대로 남아 있는데, 새 reader-authoring 경로가 실제 Results, Discussion, Abstract, Conclusion의 LLM 호출을 프롬프트 크기 초과로 시작조차 하지 못했고, 짧은 deterministic fallback으로 대체했기 때문이다.

가장 직접적인 실행 증거는 2026-09-14 11:33 Order 74의 `report_prose_trace.json`이다.

- Results 프롬프트: 364,325자, provider 호출 0회, `authoring_packet_exceeds_prompt_budget`, fallback 사용.
- Discussion 프롬프트: 374,935자, provider 호출 0회, 같은 이유로 fallback 사용.
- Conclusion 프롬프트: 235,782자, provider 호출 0회, fallback 사용.
- Abstract도 200,000자 상한을 넘어 fallback 사용.
- Introduction과 Methods만 Gemini 2.5 Pro 응답을 실제로 받았다.
- 최종 품질 감사 상태는 `draft_review_required`이며, `interpretation_generation_incomplete`, `research_question_coverage_incomplete`, `section_content_quality_incomplete`, `study_metadata_review_required`가 기록됐다.

따라서 이 산출물을 “최근 알고리즘이 불필요한 biology를 제거한 결과”로만 해석하면 안 된다. 검증 강화로 제거되어야 할 과잉 주장이 실제로 많이 제거된 것은 맞지만, 동시에 보고서 생성 실패 때문에 보존되어야 할 관측 기반 해석도 대량으로 사라졌다.

핵심 판정은 다음과 같다.

1. **좋아진 부분:** de novo/pseudocount를 일반 Log2FC처럼 쓰지 않음, pathway membership을 activation으로 쓰지 않음, PTM 변화를 kinase activity의 직접 proxy로 쓰지 않음, 직접 kinase–substrate 및 인과 주장을 no-call 처리, precursor identity와 U/P/A 축을 분리함.
2. **나빠진 부분:** 실제 LLM이 핵심 절을 쓰지 못함, 최대 4개 feature와 최대 3개 kinase context로 서사가 축소됨, 6개 연구 질문 중 5개가 미답변, 유효한 MAPK1/MAPK3 관측과 kinase trajectory 수치도 최종 본문에서 누락됨, 그림 19개가 5개로 줄고 signaling/kinase 시각화가 본문에서 사라짐.
3. **가장 시급한 결함:** “unsafe claim 차단”과 “substantive but bounded interpretation 생성”이 분리되어 있지 않다. 현재는 검증 실패나 packet 비대화가 곧 템플릿형 축약으로 이어진다.
4. **Kinase가 빈약한 직접 이유:** 최신 Order의 footprint는 `not_evaluable`, direct attribution은 금지된 상태였고, reader-authoring은 kinase supporting card를 최대 3개만 고른다. 더구나 실제로 계산된 trajectory evidence(방향 일치율 0.80, signed correlation 약 0.724, evaluable target 85개)가 validator/fallback 경로에서 최종 11:33 본문에서 잘렸다.

## 2. 비교 대상과 날짜 확인

### 2.1 이전 리포트

사용자가 8월 29일 리포트라고 설명한 DOCX 첨부는 현재 대화의 첨부 저장소에는 전달되지 않았다. 그러나 로컬 Order 산출물에서 다음 DOCX/MD 쌍을 확인했다.

- `data/outputs/Insulin_Signaling_Dynamic_V1_All_PTMs/Insulin_Signaling_Dynamic_V1_All_PTMs_report_260828_1147.docx`
- `data/outputs/Insulin_Signaling_Dynamic_V1_All_PTMs/Insulin_Signaling_Dynamic_V1_All_PTMs_report_260828_1147.md`
- 문서 내부 생성 시각: **2026-08-28 11:47**
- DOCX 크기: 30,684,619 bytes
- MD SHA256: `e76eddc6cd50c27f3902fe228fa96d9ab4455963727175f2e17d373bc911b28e`

사용자가 기억한 8월 29일과 문서 내부 시각에는 하루 차이가 있다. 이 감사에서는 문서 자체의 생성 표기를 우선해 “8월 28일 리포트”라고 부르되, 요청한 코드 비교는 8월 29일 말 기준 커밋까지 별도로 확인했다.

실제 문서 생성 시각 직전의 Git 커밋은 `858d247c146b081179ce2aadbe8ce19b5100103e`이며, 8월 29일 리포트 코드 기준점으로는 `c57ad6ff2c1941ef267ef8f34e8f0fbc5535e4dc`를 사용했다.

### 2.2 최근 리포트

- 첨부/로컬 원본: `data/outputs/Insulin_Signaling_V3_260913_codex_2/Insulin_Signaling_V3_260913_codex_2_report_260914_1133.md`
- 생성 시각: **2026-09-14 11:33**
- MD 크기: 22,458 bytes
- SHA256: `707eaf7964628e65ff81025e54bead3346e404e4cf542b672780d5165094df38`
- 첨부된 이름 없는 원본, `_1`, `_2` 세 MD는 SHA256이 같아 동일 파일의 복제본이다.

생성 직전 마지막 커밋은 `ef5b763b83a50657b1b9953904eba70971e0eb10`이다. 다만 `report_artifact_manifest.json`의 runtime provenance에서 `git_commit_sha`, `tracked_worktree_dirty`, `container_digest`, `worker_version`가 모두 `null`이다. worker가 소스를 bind mount로 읽기 때문에 11:33 실행이 어느 정확한 worktree snapshot을 사용했는지는 사후에 완전히 증명할 수 없다. 특히 kinase trajectory 표시 변경은 12:50의 `ff89ee75cbd96781a26b7c95727c4dff9fafd1c5`에 커밋됐지만, 그 일부가 실행 중 미커밋 상태로 보였을 가능성이 있다.

이 provenance 공백은 별도 결함이다. 결과 리포트마다 실제 Git SHA와 dirty 상태를 강제로 기록해야 코드-산출물 대응이 재현 가능하다.

## 3. 정량적 차이

### 3.1 전체 분량

- 전체 단어: 11,700 → 3,099, **73.5% 감소**, 이전이 3.78배 길다.
- MD byte: 86,758 → 22,458, **74.1% 감소**.
- Figure 참조: 19 → 5, **73.7% 감소**.
- Markdown table row: 60 → 23.
- 참고문헌 항목 수는 양쪽 모두 4개지만, 이전 것은 제목과 식별자가 불완전했고 최신 것은 PMID/DOI가 추적 가능하다.

### 3.2 절별 분량

- Abstract: 378 → 161 words, 57.4% 감소.
- Introduction: 1,533 → 301 words, 80.4% 감소.
- Results: 3,230 → 1,096 words, 66.1% 감소.
- Discussion: 1,612 → 421 words, 73.9% 감소.
- Conclusion: 972 → 71 words, 92.7% 감소.
- Research Question Answers: 1,328 → 독립 절 0 words, 100% 감소.
- 최근 Methods는 460 words로 새로 명시됐고, U/P/A 계산 및 제한을 이전보다 정확히 설명한다.

### 3.3 Kinase 관련 밀도

단순 문자열 빈도는 문장 품질을 대신하지 않지만, 서사 축소를 보여 주는 지표로는 유용하다.

- `kinase`: 93 → 11, **88.2% 감소**.
- `MAPK`: 51 → 4.
- `AKT`: 15 → 1.
- `ERK`: 10 → 0.
- `mTOR`: 7 → 0.
- `INSR`: 14 → 0.
- `substrate`: 50 → 1.
- `pathway`: 155 → 12.

최신 문서의 kinase 11회 중 다수는 새로운 생물학적 설명이 아니라 “not kinase activity”, “not direct regulation”, “not catalytic rate”와 같은 제한 문구다. 실제 후보 내용은 CDK, MAPK, MAPK14 세 family 이름뿐이다.

### 3.4 최근 리포트 내부 반복

최근 본문에는 다음 템플릿이 반복된다.

- “The supplied evidence supports descriptive observations and candidate context”: 5회.
- “Independent footprint diagnostics were not evaluable”: 7회.
- “largest sampled …”: 4회.
- “does not locate a continuous-time biological peak”: 4회.
- 미지원 질문에 대한 동일 문구: 2회.

감사 파일도 Discussion에 `repeated_paragraphs` 및 `repeated_interpretation_template`을 기록했다. 즉 “빈약해 보인다”는 인상은 주관적 평가만이 아니라 시스템 자체 QA에도 잡힌 결함이다.

## 4. 두 리포트의 입력 데이터가 정말 달라졌는가

### 4.1 거의 같은 데이터다

두 `ptm_vector_data_normalized_phospho.tsv`를 다음 복합 키로 직접 비교했다.

`Protein.Group + Gene.Name + Modified.Sequence + PTM_Position + Condition`

결과:

- 이전 고유 feature-condition: 15,927.
- 최신 고유 feature-condition: 15,945.
- 공통: 15,927.
- 이전에만 존재: 0.
- 최신에만 존재: 18.
- Jaccard overlap: 0.99887.
- 이전 gene-position: 2,447.
- 최신 gene-position: 2,451.

더 결정적인 결과는 공통 15,921개 유한 값에서 다음이 모두 성립한다는 점이다.

- 이전 `PTM_Relative_Log2FC`와 최신 `PTM_ProteinAdjusted_Log2FC`의 차이: **전부 0**.
- linked `Protein_Log2FC`의 차이: **전부 0**.

따라서 이전 리포트에서 사용한 주 정량축은 최신 파일 안에 그대로 보존되어 있다. 최신 파이프라인은 여기에 독립 `PTM_Unadjusted_Log2FC`, precursor ID/charge, sample IDs, estimator, test status 등을 추가했다.

보고서 축소를 “새 알고리즘이 기존 신호 대부분을 없앴다”고 설명할 수 없는 이유다. 값이 사라진 것이 아니라 **작성 후보 선정, evidence packet, claim gate, fallback 과정에서 본문으로 전달되지 않았다.**

### 4.2 최신 계산에서 실질적으로 좋아진 부분

최신 TSV는 이전보다 다음을 명시한다.

- `Precursor.Id`, `Precursor.Charge`.
- protein-adjusted, unadjusted, linked protein 세 축.
- 축별 control/treatment sample ID와 N.
- 축별 estimator와 statistical unit.
- p/q 및 test status.
- reconstructed 값과 독립 unadjusted 값의 구분.
- pseudocount 사용 여부와 conventional Log2FC NA.

이 변화는 단순한 “보수화”가 아니라 측정량의 의미를 바로잡는 개선이다.

## 5. 이전 리포트에서 제거된 내용 중 제거가 타당한 것

이전 리포트는 풍부하지만 과학적으로 허용하기 어려운 주장이 많다. 최신 시스템이 이를 그대로 유지하지 않은 판단은 타당하다.

### 5.1 de novo/pseudocount를 거대한 fold change로 해석

이전 리포트는 CFLAR T231 `Log2FC=31.98`, FNBP1L S431 `26.17`, IRS1 S522 `28.97` 등을 강한 phosphorylation 및 signal amplification으로 해석했다.

원 TSV를 확인하면 이 항목들은 `Control_Pseudocount_Used=True`, `Conventional_Log2FC_NA=True`다. 즉 control에서 충분히 검출되지 않아 pseudocount로 만들어진 수치이며, 일반적인 연속 Log2FC scale에서 31.98로 순위화할 수 없다.

특히 이전 문서의 다음 연결은 허용하기 어렵다.

- pseudocount-derived IRS1 S522 28.97을 “key signal amplification step”으로 설명.
- CFLAR/FNBP1L의 20~30대 값을 생물학적 크기로 비교.
- de novo 검출 이벤트를 conventional site trajectory와 같은 cluster magnitude로 사용.

최신 문서가 이들을 numeric color scale과 conventional ranking에서 제외한 것은 맞다. 다만 올바른 대안은 완전 삭제가 아니라 detection/LOD context로 별도 서술하는 것이다.

### 5.2 PTM 변화를 upstream kinase activity의 직접 proxy로 선언

이전 Introduction은 site phosphorylation state가 upstream kinase/phosphatase activity의 “direct proxy”라고 썼고, 양의 Log2FC를 kinase activity 증가 또는 pathway activation으로 연결했다.

이것은 일반적으로 성립하지 않는다. 한 phosphosite의 변화에는 kinase, phosphatase, localization, substrate availability, peptide detectability, parent protein abundance, multiple kinases 및 site occupancy가 함께 영향을 줄 수 있다.

최신 문서가 “measured contrast is not activation, directness, or biological-priority score”라고 제한한 것은 올바르다.

### 5.3 시간 순서를 인과 cascade로 승격

이전 문서는 1분 → 5분 → 15분 → 30분 → 60분 → 180분 cluster를 INSR에서 하류 kinase로 “propagation”하는 hierarchical cascade라고 반복해서 기술했다. 같은 cluster를 shared upstream regulation 및 sequential kinase activation의 증거로도 사용했다.

시간적 선후와 co-clustering만으로는 다음을 입증하지 못한다.

- 앞 cluster가 뒤 cluster를 유발함.
- 같은 cluster가 같은 kinase의 substrate 집합임.
- peak가 kinase activation 시점임.
- 후기 변화가 feedback 또는 transcriptional consequence임.

최신의 observation-only ceiling 및 “Interval concordance is not a catalytic rate” 제한은 이 과잉 해석을 막는 데 필요하다.

### 5.4 pathway enrichment를 pathway activation으로 해석

이전 Results는 q=0.259, 0.453 등의 pathway를 “most significantly modulated” 또는 활성화/조절된 pathway로 설명했다. 이 q 값은 통상적인 0.05 FDR 기준을 통과하지 않는다. 또한 membership enrichment와 pathway activity는 다른 측정량이다.

최신 Figure legend의 “Descriptive membership enrichment. Not pathway activation or kinase activity”가 더 정확하다.

### 5.5 정확한 site 및 직접 kinase 관계의 과잉 확정

이전 문서는 gene-position aggregate 또는 candidate residue를 정확히 localized site로 취급하고, motif/annotation/시간 cluster를 합쳐 kinase–substrate 연결을 서술했다. 당시에는 precursor charge, modified sequence identity, localization confidence, species/site orthology, curated edge provenance가 현재만큼 분리되어 있지 않았다.

8월 31일 이후 도입된 `ptm_shared/kinase_evidence_ledger.py`, `species_site_mapping.py`, `kinase_relation_evidence.py`, `kinase_candidate_allocation.py`의 no-call 및 ambiguity 보존은 필요한 개선이다.

### 5.6 TF 및 장기 기능 결과 과잉 해석

이전 문서는 non-PTM abundance 변화와 target list를 이용해 FOSL2/MYC activation, transcriptional outcome, protein turnover를 비교적 직접적으로 주장했다. 현재 데이터만으로는 TF activity나 전사 변화를 직접 측정했다고 보기 어렵다. 이 부분을 현재 report claim ceiling에서 제외한 것은 타당하다.

### 5.7 문헌 추적성 부족

이전 본문은 `[1]`부터 `[15]`까지 인용하지만 최종 References에는 불완전한 4개 항목만 있다. 제목도 잘렸고 PMID/DOI가 없다. 최신 리포트의 4개 reference는 PMID와 DOI가 있어 추적성이 크게 개선됐다.

## 6. 제거되면 안 되었는데 사라진 내용

안전성 강화가 서사 빈곤을 필연적으로 요구하는 것은 아니다. 아래 내용은 direct/causal claim 없이도 최신 보고서에 남길 수 있었다.

### 6.1 실제 MAPK1/MAPK3 관측 궤적

동일 TSV에서 다음 conventional, non-pseudocount 관측이 확인된다.

MAPK1 Y185:

- 1분 adjusted +1.086, unadjusted +0.998, q=0.0477.
- 5분 adjusted +1.565, unadjusted +1.547, q=0.0362.
- 15분 adjusted +1.905, unadjusted +1.852, q=0.0398.
- 30분 +0.553, 60분 -0.859, 180분 -0.256.
- 모든 시점 detection 3/3, pseudocount 미사용.

MAPK3 Y205:

- 1분 adjusted +0.735, q=0.0667.
- 5분 +1.325, q=0.0589.
- 15분 +1.763, q=0.0283.
- 30분 +0.782, 60분 -0.856, 180분 -0.039.
- 모든 시점 detection 3/3, pseudocount 미사용.

이 데이터로 “MAPK1/3 kinase activity가 입증됐다”고 할 수는 없다. 그러나 “MAPK1 Y185 및 MAPK3 Y205로 표기된 measured precursor features가 15분에 양의 phosphorylation contrast를 보였고 후기에는 감소했다”는 관측은 충분히 쓸 수 있다. 이 서술은 인슐린 biology와 직접 관련되고, 최신 U/P/A 계약에도 맞으며, 사용자가 중요하게 본 kinase 내용을 실질적으로 보강한다.

최근 리포트가 UBE3C, HSP90B1, AP3D1, PDIA3만 선택하고 이러한 canonical measured kinase features를 전혀 언급하지 않은 것은 과잉 주장 제거가 아니라 **finding-selection 및 question-alignment 실패**다.

### 6.2 IRS1 detection/LOD 관측

IRS1 S522의 20대 pseudocount Log2FC를 쓰면 안 되지만, control 대비 treatment detection pattern과 candidate residue라는 한계를 명시해 “insulin-receptor substrate 관련 precursor의 treatment-associated detection event”로 보고할 수 있다.

현재 방식은 conventional axis에서 제외하는 데 성공했지만, reader report가 detection/LOD track을 의미 있는 생물학적 문장으로 번역하지 못해 관측 자체가 사실상 사라졌다.

### 6.3 cluster 규모와 시간대별 descriptive pattern

이전의 “activation wave” 표현은 과하지만 다음은 관측적으로 보존할 수 있다.

- 각 temporal profile cluster의 feature 수.
- 관측된 sampled maximum의 시간대.
- transient/sustained/rebound 등 사전 정의된 shape label.
- missingness와 cluster eligibility.
- adjacent interval의 retained/gain/loss 분자·분모.

최신 보고서는 late interval retained 0.055, gain 0.186, loss 0.467 하나를 Methods에 넣지만, 어떤 feature 집단과 어떤 생물학적 질문에 연결되는지 설명하지 않는다. 숫자가 존재해도 해석 구조가 없다.

### 6.4 protein-adjustment의 생물학적 의미

최신 보고서는 U/P/A를 정확하게 분리했지만 네 feature에 대해 거의 같은 문장을 반복한다. 다음과 같은 비교 축을 더 풍부하게 쓸 수 있다.

- U와 A의 방향이 일치하는지.
- adjustment delta가 작은지 큰지.
- linked protein이 안정적인지, 반대 방향인지.
- 동일 parent의 여러 modified forms가 동조 또는 분기하는지.
- early/middle/late sampled observations에서 관계가 변하는지.

이들은 absolute occupancy나 kinase activity를 주장하지 않고도 가능한 정량 해석이다.

### 6.5 문헌과 current-order observation의 비교

최신 RAG는 AP3D1 등 네 selected finding에 대해 background 8개를 검색했으나 direct gene/site hit가 없고, comparison 문장 다수가 `unbound_quote_context_or_scope`로 제외됐다. 그 결과 Introduction 외에는 문헌 비교가 거의 없다.

올바른 대안은 문헌을 억지로 붙이는 것이 아니라:

- current-order measured statement,
- literature-established pathway context,
- species/cell/time/readout 차이,
- 일치/불일치 여부,
- 남은 대안 설명

을 분리해 Discussion을 구성하는 것이다.

## 7. Kinase 서술이 빈약해진 코드 경로

### 7.1 8월 writer 경로

8월 29일 기준 `workers/report_generation/core/nodes/writer_node.py`는 Results/Discussion 프롬프트에 다음 블록을 우선순위별로 주입했다.

- `temporal_evidence_packet`
- co-movement context
- `temporal_kinase_cascade_llm_context`
- inferred receptor context
- non-PTM temporal context
- TF inference
- structured PTM data
- pathway context
- signal propagation
- PTM/protein time lag
- full vector data
- figure context
- cascade-specific literature

Results max output은 16,384 tokens, Discussion도 16,384 tokens였고 최소 단어는 각각 1,200 및 1,000이었다. 독립 Research Question Answers도 질문 2개씩 batch 처리했다.

이 설계는 풍부한 장문을 만들었지만, 서로 다른 evidence tier를 한 프롬프트에 섞어 LLM이 temporal association을 cascade, activity, feedback, direct regulation으로 승격하기 쉬웠다. 이전 리포트의 과잉 주장은 이 구조와 일치한다.

### 7.2 8월 31일 이후 direct no-call

커밋 `09cb942`는 feature-level exact mapping, localization, curated edge provenance가 없으면 direct kinase attribution을 `no_call`로 만들었다. TMM/RAG/LLM이 이 tier를 승격할 수 없도록 했다.

이는 직접 kinase–substrate 정확도를 말하려면 필요한 보호장치다. 다만 이 guard는 다음 세 층을 구별해야 한다.

1. measured kinase-protein phosphosite observation,
2. substrate-derived family-level activity/candidate context,
3. curated direct kinase–substrate relation.

현재 최종 prose는 2와 3을 강하게 제한하면서 1까지 충분히 활용하지 못한다.

### 7.3 9월 4일 footprint diagnostics

커밋 `19ba1cd`는 contribution-weighted kinase footprint robustness diagnostics를 추가했다. 최신 Order의 stored heatmap에서는 이 status가 `computed`가 아니라 `not_evaluable`이었다.

`reader_authoring.py::_kinase_context_cards`는 computed footprint가 하나도 없으면 availability card를 추가하고, stored ranking이 있으면 family card를 만든다. 따라서 최근 리포트에는 다음 형태가 반복됐다.

> A stored CDK/MAPK/MAPK14 family ranking provided kinase-family candidate context. Independent footprint diagnostics were not evaluable…

즉 빈약함은 “kinase 데이터가 전혀 없음”이 아니라 **독립 footprint는 평가 불가이고, 허용된 fallback 표현이 family ranking 한 문장뿐**이기 때문이다.

### 7.4 reader-authoring shadow mode

커밋 `ddbf06c`(2026-09-07)는 `reader_authoring=shadow`를 추가했다. 이 mode에서:

- legacy auxiliary mechanism context를 model-visible prompt에서 제거한다.
- reader-safe cards만 사용한다.
- sentence별 evidence ID, value token, figure key를 검증한다.
- 금지된 direct/causal 표현은 삭제 또는 제한 문구로 바꾼다.
- LLM 실패 시 `render_reader_section_fallback`을 사용한다.

안전성 방향은 맞다. 문제는 fallback이 보고서의 보조 안전망이 아니라 이번 실행에서 핵심 절 전체를 대신했다는 점이다.

### 7.5 최대 4개 measured finding

`deterministic_authoring_plan`은 selected finding을 동결하고, 이번 실행에서는 F1~F4가 UBE3C, HSP90B1, AP3D1, PDIA3였다. `central_answer`도 처음 세 feature finding만 사용한다.

전체 authoring packet에는:

- measured feature observation 40개,
- candidate discovery 20개,
- temporal profile 11개,
- quantitation comparison 9개,
- kinase context 4개,
- literature 4개

가 있었지만 최종 서사는 네 feature에 과도하게 집중됐다.

이 선택은 질문 관련성보다 numeric support, parent diversity, pattern diversity에 치우쳐 있다. insulin signaling의 중심 measured kinase/adaptor를 별도 narrative role로 보장하지 않으므로 MAPK1/3 같은 항목이 탈락했다.

### 7.6 최대 3개 kinase supporting card

`reader_authoring.py::_supporting_context_cards(..., maximum=3)`은 kinase/module companion을 최대 3개만 선택한다. 이번에는 CDK, MAPK, MAPK14가 들어갔다.

이 세 카드의 fingerprint는 동일했다.

- peak score 6.9524.
- peak condition 180min.
- direction concordance fraction 0.80.
- signed profile correlation 약 0.7237.
- evaluable substrate targets 85.

동일 fingerprint는 이들이 독립적으로 구별된 세 kinase activity 결과라기보다 동일/대칭 substrate evidence 또는 family equivalence를 공유한다는 신호다. 최신 본문은 숫자를 모두 빼고 이름만 나열해, 오히려 독자가 세 개의 독립 결과처럼 오해할 수 있다.

### 7.7 trajectory 값이 packet에는 있었지만 본문에서 소실

`report_authoring_packet.json`의 kinase cards에는 direction concordance 0.80, correlation 0.7237, target 85가 존재한다. 그러나 11:33 최종 Results/Discussion에는 모두 없다.

원인은 두 단계다.

1. 프롬프트가 200,000자를 넘어서 LLM이 해당 card를 문장으로 합성할 기회가 없었다.
2. deterministic fallback/validator는 family 이름과 not-evaluable 제한을 남겼지만 bound interval 수치를 제거했다.

이 문제를 고치려는 커밋 `ff89ee7`이 12:50에 들어갔다. 이 커밋은 “kinase 구간 수치 본문 복원” 테스트를 추가했지만, 11:33 리포트는 그 수정의 최종 live 검증물이 아니다.

## 8. 프롬프트 크기 초과의 구체적 원인

현재 저장 packet을 최신 formatter에 다시 넣어 크기를 분해했다.

- 전체 authoring packet JSON: 약 4.23 MB.
- `focus_authoring_packet` 이후에도 약 1.67 MB.
- card는 93개에서 29개로 줄지만, card 외 대형 audit 필드는 그대로 남는다.
- formatter 기준 Results prompt core만 약 242 KB, Discussion 약 247 KB다. 실제 11:33 trace는 dependency 및 instruction이 더해져 364~375 KB였다.

focused packet의 큰 필드는 다음과 같다.

- `report_evidence_utilization`: 약 552 KB.
- `figure_cards`: 약 298 KB.
- `observation_selection_audit`: 약 276 KB.
- `reader_cards`: 약 245 KB.
- `feature_identity_audit`: 약 149 KB.
- `research_question_evidence_map`: 약 137 KB.

네 measured feature card만 약 211 KB다. 카드 하나가 약 52~54 KB이고, 그중 trajectory가 약 36 KB, literature comparison이 약 9 KB다.

즉 `focus_authoring_packet`은 card 수만 줄일 뿐, 모델이 prose를 쓰는 데 필요 없는 전체 audit, exclusion list, identity audit, 대형 figure binding을 prompt에서 제거하지 않는다. `include_quantitative_records=False`도 packet 전체의 중복 metadata를 충분히 줄이지 못한다.

`writer_node.py`에는 structured packet이 200,000자를 넘으면 JSON/schema를 중간 절단하지 않고 `content=None`으로 두는 보호 코드가 있다. 이 보호 자체는 맞지만, 그 다음 행동이 “압축 packet으로 재시도”가 아니라 “즉시 짧은 fallback”이다. 이번 회귀의 가장 직접적인 코드 결함이다.

## 9. Quality gate가 결함을 발견하고도 최종 파일이 나온 이유

`section_budgets.py` v2 목표는 다음과 같다.

- Abstract 220–300 words.
- Introduction 600–900.
- Results 900–1,400.
- Discussion 1,000–1,600.
- Methods 400–700.
- Conclusion 100–160.

11:33 리포트는 Abstract, Introduction, Results, Discussion, Conclusion이 목표 미달이다. 특히 Discussion 421/1000, Conclusion 71/100이다.

`audit_report_output_correctness`는 이들을 `below_section_target`으로 기록한다. 그러나 `_length_only = {"below_section_target", "language_specific_budget_not_configured"}`로 분류해 length-only 문제만으로는 hard block을 만들지 않는다. 이번에는 반복 Discussion과 missing Conclusion interpretation, 미답변 질문, generation fallback이 있어 `draft_review_required`가 됐다.

`report_release.py`는 `draft_review_required`를 최종 차단이 아니라 경고 상태로 취급한다. 그래서 DOCX/HTML은 만들어졌고 사용자가 일반 리포트처럼 내려받을 수 있었다.

이 정책은 검토용 초안을 보존한다는 장점이 있지만, UI에서 “완성 리포트”와 “LLM 핵심 절 생성 실패 초안”을 명확히 구분하지 않으면 품질 회귀가 정상 결과처럼 보인다.

## 10. Research Question 손실

8월 리포트는 독립 Research Question Answers 절 1,328 words를 생성했다. 내용 중 과잉 주장이 많았지만 질문별로 direct answer, evidence, boundary, next measurement 구조가 있었다.

9월 코드는 독립 Q&A 절을 제거하고 질문을 Results/Discussion evidence map에 통합하도록 바꿨다. 설계 의도는 중복을 줄이고 질문과 finding을 직접 묶는 것이다.

실제 Order 74 결과:

- 질문 총 6개.
- integrated 1개.
- missing 5개.
- 최종 audit: `research_question_coverage_incomplete`.

특히 MAPK8/MAPK14/CDK candidate-context 질문이 evidence IDs까지 갖고 있었지만 최종 Results/Discussion paragraph binding은 비어 있었다. 독립 Q&A를 없앤 뒤 통합 coverage가 실패했으므로, 사용자 관점에서는 질문 답변이 통째로 사라졌다.

이는 문서 분량 감소의 상당 부분을 설명하며, 기능적 회귀다.

## 11. 그림 감소의 의미

이전 리포트는 19개 figure를 포함했다.

- pathway distribution,
- context PTM heatmap,
- inferred signaling pathway,
- cluster plots,
- temporal heatmap,
- signal-flow diagram,
- 시점별 signaling cascade,
- 시점별 PTM/non-PTM network.

최신 reader mode는 5개만 남겼다.

- main: quantitative PTM heatmap.
- main: U/P/A adjustment comparison.
- main: selected joint trajectories.
- supplementary: pathway membership.
- supplementary: interval concordance.

이전 그림 중 receptor→kinase→substrate 화살표와 cascade는 evidence보다 강한 인과 인상을 줄 수 있어 기본 본문에서 제외하는 것이 타당하다. 하지만 대체 kinase 시각화가 전혀 없다.

안전한 대체물은 다음과 같아야 한다.

- family-equivalence-aware candidate heatmap.
- kinase family별 substrate-anchor 수와 missingness.
- footprint status와 trajectory status를 분리한 panel.
- direction concordance 및 signed correlation을 catalytic activity가 아님을 명시한 plot.
- measured kinase-protein phosphosite trajectories(MAPK1/MAPK3 등)와 substrate-derived family context를 분리한 figure.

## 12. 코드 변경 타임라인과 영향

### 8월 28~29일

- `858d247`: 실제 이전 리포트 생성 직전 기준.
- `a3bdd67`, `7631be0`, `c57ad6f`: temporal evidence packet 및 trajectory 회복.
- writer는 대형 free-form biological context와 long-form section 생성을 유지.

### 8월 31일~9월 1일

- `09cb942`: kinase provenance ledger 및 direct no-call.
- `b1db9c0`, `0e8dd09`: feature identity, species/site mapping.
- `16f0ccd`, `9c5872f`, `def8458`: curated relation, iPTMnet snapshot, ambiguity-preserving allocation.

이 구간은 직접 attribution의 과잉 확정을 줄인 핵심 과학적 개선이다.

### 9월 3~5일

- de novo pseudo-Log2FC dominance 방지.
- report evidence boundary, citation, footprint diagnostics 강화.
- observation-only deterministic report 도입.

안전성은 좋아졌으나 narrative가 compact diagnostic으로 기울기 시작했다.

### 9월 7~11일

- `ddbf06c`: reader-authoring shadow mode.
- measured feature cards, figure manifest, sentence-level validator, release gate.
- section budget 및 semantic quality gate 강화.

이 구간이 현재 “검증된 카드만 쓰는 보고서” 구조를 만들었다.

### 9월 12~14일

- U/P/A 및 feature identity 보존.
- finding literature retrieval 및 question mapping.
- deterministic fallback에서 named feature와 kinase context 복구.
- `ff89ee7`: 11:33 보고서에서 잘린 kinase interval 수치 복원 시도.

기능은 계속 보완됐지만 실제 Order 74에서 packet 크기 초과가 해결되지 않았고, live 결과는 계속 draft였다.

## 13. 원인별 기여도 판정

### 원인 A — 프롬프트 크기 초과 및 fallback: 매우 높음

Results, Discussion, Abstract, Conclusion이 실제 LLM 호출 없이 생성됐다. 분량, 반복, 생물학적 연결, 질문 답변 손실의 가장 직접적인 원인이다.

### 원인 B — evidence/claim gate 강화: 높음

이전의 activation, cascade, direct proxy, feedback, kinase switching 표현을 제거했다. 과학적으로 필요한 감소지만, 대체 가능한 bounded interpretation까지 충분히 생성하지 못했다.

### 원인 C — finding/card 상한: 높음

2,451 gene-position과 40 measured cards 중 네 feature만 중심 finding이 됐다. insulin/kinase 중심성 보장이 없다.

### 원인 D — stale/not-evaluable kinase footprint: 높음

저장 heatmap에는 score가 있지만 independent footprint는 evaluable하지 않았다. candidate family 수준으로 제한되는 것은 맞지만, trajectory evidence와 measured kinase features를 별도 층으로 활용했어야 한다.

### 원인 E — Research Question 통합 실패: 중간~높음

독립 Q&A 1,328 words가 없어졌고 6개 중 5개가 missing이다.

### 원인 F — 알고리즘이 신호 자체를 제거: 낮음

공통 정량값이 사실상 동일하다. 다만 최신 표현에서는 de novo/pseudocount, direct attribution, enrichment activation 등 부적절한 “신호 해석”이 제거됐다.

### 원인 G — 문헌 근거 부족: 중간

추적 가능한 reference는 좋아졌지만 4개뿐이고 selected feature 직접 문헌 비교가 거의 생성되지 않았다.

## 14. 권고안

### P0. 핵심 절 LLM 호출 실패를 최종 리포트로 배포하지 않기

다음 조건 중 하나면 UI에서 “완성 리포트”가 아니라 “검토용 fallback draft”로 명확히 표시해야 한다.

- Results 또는 Discussion `fallback_used=True`.
- `authoring_packet_exceeds_prompt_budget`.
- 핵심 절 provider attempt 0회.
- 50% 이상의 사용자 질문이 missing.
- Discussion이 section target의 절반 미만.

현재처럼 DOCX/HTML을 생성하더라도 파일명, badge, 다운로드 경고에 draft를 넣어야 한다.

### P0. model-visible packet과 audit packet을 물리적으로 분리

모델 prompt에는 다음만 넣는다.

- section contract.
- selected finding의 concise identity.
- 각 시점의 최소 U/P/A value tokens.
- claim tier와 allowed verbs.
- selected literature quote 및 stable citation.
- 실제 사용할 figure bindings.
- 관련 질문.

다음은 별도 validator/audit sidecar에만 둔다.

- 전체 exclusion 2,990개.
- full evidence utilization.
- 전체 identity audit.
- 사용하지 않을 figure bindings.
- 전체 trajectory raw support.
- 중복 provenance dictionary.

현재 1.67 MB focused packet을 section별 80~120 KB 이하로 줄이고, size budget test를 실제 Order 74 fixture로 고정해야 한다.

### P0. 200 KB 초과 시 즉시 fallback하지 말고 단계적 축약

권장 순서:

1. audit-only field 제거.
2. trajectory를 first/peak/late + shape summary로 축약.
3. literature quote 길이 제한.
4. figure binding을 section 관련 항목만 유지.
5. 질문도 해당 section 관련 질문만 유지.
6. 그래도 초과하면 finding batch별 생성 후 evidence-safe merge.
7. 모든 축약 단계와 누락 evidence를 trace에 기록.

schema를 중간 절단하지 않는 현재 정책은 유지해야 한다.

### P1. Kinase를 세 층으로 분리해 서술

#### 층 1: measured kinase-protein phosphosite

MAPK1 Y185, MAPK3 Y205처럼 실제 데이터에서 측정된 kinase protein의 candidate-residue precursor trajectory를 U/P/A와 q/N으로 기술한다. 이것은 kinase activity나 direct substrate attribution이 아니다.

#### 층 2: substrate-derived family candidate context

CDK/MAPK/MAPK14 score, footprint status, direction concordance, correlation, target count를 family-equivalence와 함께 기술한다. 동일 fingerprint는 독립 결과처럼 나열하지 않는다.

#### 층 3: direct relation evidence

species/site/localization/curated edge가 통과한 경우만 direct relation을 허용한다. 그렇지 않으면 no-call을 유지한다.

이 세 층을 섞지 않으면 안전성을 유지하면서도 Kinase 설명을 충분히 늘릴 수 있다.

### P1. insulin-specific narrative coverage role 도입

finding selection에 “큰 값”을 추가하라는 뜻이 아니다. 다음 role을 최소 하나씩 보장한다.

- receptor/adaptor-related measured observation.
- measured kinase-protein feature.
- substrate-derived kinase-family context.
- positive adjusted response.
- negative adjusted response.
- early, middle, late pattern.
- protein-adjustment informative case.
- detection/LOD-only case.

각 role은 evidence eligibility를 먼저 통과해야 하며, 특정 gene을 production 코드에 hard-code하면 안 된다. 질문과 literature context로 role을 정하되 selection audit에 이유를 남긴다.

### P1. Research Question coverage를 hard completion gate로 강화

독립 Q&A를 반드시 복원할 필요는 없다. 그러나 통합 방식을 유지하려면:

- 각 질문에 Results 또는 Discussion paragraph ID가 있어야 한다.
- observationally answerable 질문은 최소 한 문단으로 답해야 한다.
- not answerable도 질문별 unavailable reason과 필요한 측정을 표시해야 한다.
- 6개 중 5개 missing인 리포트를 일반 final로 표시하면 안 된다.

### P1. fallback을 template 반복이 아닌 evidence-role composer로 교체

현재 fallback은 feature 이름과 first/extreme/late 문장을 반복한다. 대신 각 paragraph가 하나의 역할만 맡아야 한다.

- landscape.
- canonical measured observations.
- adjustment contrast.
- temporal diversity.
- kinase candidate context.
- pathway/literature comparison.
- alternative explanations.
- discriminating experiment.

같은 no-call 문구는 문서 전체에서 한 번만 쓰고, 각 kinase card에는 서로 다른 실제 evidence만 표시한다.

### P1. 최신 계산 수치가 validator에서 소실되지 않도록 하기

kinase trajectory 0.80/0.724/85가 packet에 있으나 본문에서 사라진 회귀를 end-to-end test로 고정해야 한다. `ff89ee7`의 단위 회귀뿐 아니라 실제 final Markdown assembly까지 검사해야 한다.

### P2. 안전한 kinase figure 추가

receptor→kinase→substrate causal arrow를 복원하지 말고 다음 두 figure를 추가한다.

- measured kinase-feature U/P/A trajectories.
- family candidate score + footprint/trajectory availability matrix.

caption에서 measured feature, candidate context, direct relation의 tier를 명시한다.

### P2. 문헌 수보다 finding-specific 적합도를 우선

20–30편 목표를 기계적으로 채우지 않는다. 먼저 MAPK1/3 measured-site, insulin receptor/adaptor detection event, selected U/P/A findings 각각에 대해 gene/site/pathway 층의 출처를 분리한다. 직접 site 문헌이 없으면 없다고 표시하고 pathway review로 대체하지 않는다.

### P2. runtime provenance를 release 필수로 만들기

`git_commit_sha`, `tracked_worktree_dirty`, container digest, worker version이 null인 현재 manifest는 코드 비교를 약화한다. 최소한 SHA, dirty flag, image digest, report config hash, model/provider/request IDs를 final artifact에 강제로 연결해야 한다.

## 15. 재검증 기준

수정 후 같은 Order 74 input hash로 다시 실행하고 다음을 확인해야 한다.

### 생성 경로

- Results/Discussion/Abstract/Conclusion provider attempt가 각각 1회 이상.
- 핵심 절에서 `fallback_used=False`.
- section prompt가 200,000자 미만.
- provider raw text, usage, finish reason, validation reject 이유 기록.

### 분량과 구조

- 분량을 억지로 채우지는 않되 section target을 만족하거나 evidence-limited 사유를 명시.
- Discussion 반복 template 0.
- Conclusion의 finding/interpretation/limitation/next validation 역할 모두 존재.
- 6개 질문 전부 covered 또는 question-specific unresolved.

### Kinase

- MAPK1/MAPK3 measured features가 eligibility를 통과하면 최소 한 곳에 U/P/A로 등장.
- CDK/MAPK/MAPK14 동일 fingerprint를 family-equivalent 또는 indistinguishable context로 표시.
- footprint `not_evaluable`과 trajectory `computed`를 한 status로 뭉개지 않음.
- direction concordance, correlation, target count가 packet과 본문/figure 사이에서 보존.
- direct kinase–substrate 또는 activity claim은 별도 direct evidence가 없으면 계속 금지.

### 정량 의미

- pseudocount/de novo 값은 conventional Log2FC rank에서 제외.
- q>0.05 pathway를 significant activation으로 쓰지 않음.
- adjusted PTM, unadjusted PTM, linked protein을 혼합하지 않음.
- candidate residue를 확정 localization으로 쓰지 않음.

## 16. 최종 판정

이전 리포트는 길고 biological story가 풍부하지만, 그 상당 부분은 현재 기준에서 근거보다 강하다. 특히 pseudocount 수치를 거대한 fold change로 사용하고, 시간 cluster를 kinase cascade로, pathway membership을 activation으로, phosphosite 변화를 upstream kinase activity의 direct proxy로 해석한 부분은 복원하면 안 된다.

반대로 최신 리포트의 빈약함은 과학적 엄밀성의 불가피한 대가가 아니다. 핵심 절 프롬프트가 상한을 넘어 LLM 호출 자체가 생략됐고, 네 feature 및 세 kinase family의 deterministic 문장으로 대체됐다는 명확한 실행 실패가 있다. 같은 정량 데이터와 계산된 kinase trajectory evidence가 남아 있으므로, **근거 tier를 유지하면서도 현재보다 훨씬 풍부한 Kinase 중심 서사를 작성할 수 있다.**

따라서 목표는 8월 문서를 그대로 되돌리는 것이 아니라 다음 조합이어야 한다.

- 9월의 identity, U/P/A, missingness, de novo, provenance, no-call 계약을 유지.
- 8월의 시간축·pathway·kinase 중심 narrative coverage를 evidence-safe role로 재구성.
- oversized audit packet을 모델 prompt에서 제거.
- 핵심 절 fallback을 final로 위장하지 않음.
- measured kinase features, family candidate context, direct relation evidence를 분리해 보고.

현재 11:33 리포트는 수치 원본과 export 무결성은 검증됐지만, 자체 audit가 말하듯 `draft_review_required`다. 연구자용 최종 리포트로 수용하기 전에 P0 항목을 먼저 고치고 동일 input으로 재생성해야 한다.

## 17. 근거 파일 및 커밋

### 산출물

- 이전 MD/DOCX: `data/outputs/Insulin_Signaling_Dynamic_V1_All_PTMs/`
- 최신 MD/DOCX 및 audit: `data/outputs/Insulin_Signaling_V3_260913_codex_2/`
- 최신 prose trace: `report_prose_trace.json`
- 최신 output audit: `report_output_correctness_audit.json`
- 최신 authoring packet: `report_authoring_packet.json`
- 최신 authoring plan: `report_reader_authoring_plan.json`
- 최신 evidence utilization: `report_report_evidence_utilization.json`
- 최신 temporal fidelity: `temporal_report_fidelity.json`
- 최신 artifact manifest: `report_artifact_manifest.json`

### 주요 코드

- `workers/report_generation/core/nodes/writer_node.py`
- `workers/report_generation/core/reader_authoring.py`
- `workers/report_generation/core/graph.py`
- `workers/common/section_budgets.py`
- `workers/report_generation/core/scientific_semantics.py`
- `workers/report_generation/core/report_release.py`
- `ptm_shared/kinase_evidence_ledger.py`
- `ptm_shared/kinase_footprint_diagnostics.py`
- `ptm_shared/kinase_relation_evidence.py`
- `api-server/app/services/temporal_kinase_scoring.py`

### 주요 커밋

- 실제 이전 문서 직전: `858d247c146b081179ce2aadbe8ce19b5100103e`
- 8월 29일 기준: `c57ad6ff2c1941ef267ef8f34e8f0fbc5535e4dc`
- kinase no-call: `09cb942b0df2b0560a517263a235cd585e561b5e`
- footprint diagnostics: `19ba1cd`
- reader-authoring shadow: `ddbf06cb72994b7fa2ee883ae0c573fe0e0a5e6f`
- 최근 보고서 직전 마지막 commit: `ef5b763b83a50657b1b9953904eba70971e0eb10`
- 11:33 이후 kinase trajectory 표시 보완: `ff89ee75cbd96781a26b7c95727c4dff9fafd1c5`

## 18. 감사 한계

- 대화 첨부 저장소에는 사용자가 말한 DOCX가 직접 전달되지 않았다. 로컬 Order에서 발견한 동일 insulin/HIRc-B의 2026-08-28 11:47 DOCX/MD를 비교 대상으로 사용했다.
- 두 Order의 TSV는 사실상 동일하지만 최신에 18개 feature-condition이 추가되어 완전히 같은 artifact hash는 아니다.
- 이전 보고서의 문장 진위를 개별 외부 논문 원문까지 재검증하지 않았다. 이 감사는 current-order data binding과 코드 경로를 중심으로 했다.
- 최신 manifest의 Git/runtime provenance가 null이므로 11:33 실행의 exact source snapshot은 완전히 동결할 수 없다.
- `ff89ee7` 이후 새 live report는 이 감사에서 생성하지 않았다. 해당 커밋이 11:33 회귀를 전부 해결했다고 주장하지 않는다.
