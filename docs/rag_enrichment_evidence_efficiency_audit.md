# RAG Enrichment의 PubMed Literature Retrieval과 Structured Database Evidence 효율 감사

작성일: 2026-08-17 (GMT+9)
상태: **코드 감사 완료 — database-first selective literature routing 권고**

## 핵심 결론

현재 RAG Enrichment가 PubMed를 사용하는 것은 필요하다. PTM site의 실험적 맥락, 세포 유형·처리 조건·시간적 반응, 상충하는 결과, 최신 primary paper는 KEGG·Reactome·UniProt·STRING·iPTMnet 같은 structured database만으로 얻을 수 없기 때문이다. PubMed는 4천만 건 이상 biomedical citation과 abstract를 검색하는 문헌 retrieval resource이며, 초록 자체는 full text를 포함하지 않는다.[1]

그러나 **모든 PTM site에 대해 PubMed 검색, context-aware 재검색, cross-site 재검색, LLM abstract analysis, LLM kinase prediction, LLM functional analysis, full-text search를 병렬로 수행하는 현재 방식은 비용 대비 정보 이득이 낮을 가능성이 높다.** 특히 이미 exact site/kinase evidence 또는 pathway context가 structured database에 존재하는 site에도 반복적인 문헌 검색과 여러 Qwen call이 발생한다.

> 최종 권고는 PubMed를 제거하는 것이 아니라, **structured database를 먼저 이용해 evidence gap을 판정하고 high-value PTM에만 문헌·LLM을 escalation하는 database-first evidence-routing architecture**로 바꾸는 것이다.

## 현재 코드의 evidence source와 역할

`RAGEnrichmentPipeline._enrich_single_ptm_parallel()`은 PTM site마다 Phase A에서 PubMed, KEGG, STRING-DB, UniProt, HPA, GTEx, BioGRID, Reactome을 병렬 호출한다. Phase B에서는 같은 PubMed article set을 regulation regex extractor, LLM abstract analyzer, LLM kinase predictor, LLM functional impact analyzer, optional PMC full-text analyzer, PTM validation으로 다시 사용한다. Phase C에서 KEGG pathway가 3개 미만일 때만 STRING indirect inference를 호출한다.

| Source | 현재 코드 역할 | PubMed와의 중복 정도 | 고유한 가치 | 권장 기본 우선순위 |
|---|---|---|---|---|
| iPTMnet | site novelty, known PTM/KSA, PMID link | 낮음 | PTM site·enzyme/substrate structured evidence, organism filter | **exact site/KSA first** |
| UniProt | protein function, localization, GO, canonical protein context | 부분 중복 | canonical annotation과 stable accession context | **gene/protein first** |
| KEGG/Reactome | curated pathway assignment | 부분 중복 | pathway membership와 signaling context | **gene first** |
| STRING/BioGRID | PPI/interaction partners | 부분 중복 | interaction network topology | **conditional context** |
| HPA/GTEx | human expression/localization context | 낮음 | human tissue/cell abundance context | human PTM 또는 human transgene에만 조건부 |
| PubMed abstract | primary-paper context, treatment/time/cell type, contradiction, uncurated recent finding | 높지 않음; database의 source paper와 보완 | specific experiment and claim evidence | **evidence gap 또는 high-priority PTM에서만** |
| PMC full text | method, precise site/condition, figure-level detail | 낮음 | abstract로 확인 불가한 detailed evidence | **one-article escalation only** |
| Qwen 14B | selected source를 structured evidence/hypothesis로 변환 | database를 대체하지 않음 | cross-source comparison and JSON extraction | **gated, source-grounded synthesis only** |

iPTMnet은 PTM networks를 systems biology 맥락에서 통합적으로 탐색하기 위한 resource이며, 여러 PTM type와 human/mouse/rat organism filter를 제공한다.[2] 따라서 exact site novelty와 known kinase–substrate evidence를 먼저 확인하는 데 PubMed keyword search보다 적합하다.

## 현재 효율의 장점

현재 구현이 비효율적이기만 한 것은 아니다.

| 현재 장점 | 코드 근거 | 효과 |
|---|---|---|
| Gene-level in-memory cache | KEGG, STRING, UniProt, HPA, GTEx, BioGRID, Reactome을 gene key로 cache | multiple modified sites가 같은 gene에 있을 때 중복 DB query 감소 |
| Species-aware source routing | HPA/GTEx는 non-human에서 skip, FASTA-native taxon은 external annotation species에 우선 적용 | Rat_hir에서 rat background와 human INSR transgene을 구분 |
| Small default PubMed budget | `RAG_MAX_ARTICLES` default 3 | 기본 site search의 abstract 수 제한 |
| Abstract batch mode | 여러 article을 one LLM call로 처리하며 per-article fallback | LLM abstract extraction 호출 수 감소 |
| Persistent Phase B cache | 30일 TTL, site/PTM/task/PMID key | 동일 evidence set의 repeat LLM work 감소 |
| Conditional STRING indirect | KEGG pathways가 3개 미만일 때만 실행 | 추론성 PPI pathway expansion을 제한 |
| LLM failure isolation | LLM disable/failure 시 deterministic annotation path 유지 | report generation이 LLM에 종속되지 않음 |

## 발견된 중복과 위험

### 1. Site별 literature fan-out

기본 Phase A는 PTM site마다 PubMed search를 한 번 수행한다. 그런데 `PTMValidator.validate()`가 활성화되면 iPTMnet과 UniProt을 별도로 호출하고, context가 있으면 PubMed를 최대 세 전략으로 다시 검색한다.

| Validation context search | 현재 최대 article budget | 목적 |
|---|---:|---|
| Gene + exact PTM/site + context | 10 | exact site context evidence |
| Gene + kinase/phosphatase + context | 5 | regulator context |
| Gene + regulation/signaling + context | 5 | broad signaling context |

또한 cross-site PTM search도 PubMed·PMC·iPTMnet을 추가 호출한다. 따라서 context와 validation이 켜진 PTM 하나는 Phase A 외에 여러 PubMed query를 만들 수 있다. default Phase A의 3 articles라는 제한은 이 later-stage fan-out에는 적용되지 않는다.

이 접근은 genuinely novel/high-priority site에서는 타당하지만, 모든 site에 적용할 경우 same-gene related PTM에서 쿼리와 abstract pool이 크게 중복될 수 있다.

### 2. 동일 article set에 대한 다중 Qwen call

Phase B는 같은 `articles`를 다음 작업에 병렬 전달한다.

| 작업 | LLM 여부 | 목적 | 중복 가능성 |
|---|---|---|---|
| RegulationExtractor | 아니오 | explicit regulation phrase 추출 | low-cost; 유지 적절 |
| AbstractAnalyzer | 예 | article evidence JSON, key findings | 문헌 claim extraction |
| LLMKinasePredictor | 예 | candidate kinase/alternative regulator | TMM/motif candidate가 존재하면 부분 중복 |
| LLMFunctionalImpact | 예 | PTM/protein abundance와 pathway context의 기능 해석 | report writer와 일부 중복 |
| FullTextAnalyzer | 경우에 따라 | article full text detail | 모든 site에 필요하지 않음 |

Qwen 14B는 JSON quality를 위해 필요한 모델이지만, 같은 1–3 articles를 세 개의 prompt로 해석하는 것은 expensive repetition이다. 특히 TMM/co-wave가 이미 candidate kinase를 제공하는 high-confidence temporal dataset에서는 LLMKinasePredictor를 de novo candidate generator로 쓰기보다 **literature support/contradiction annotator**로 좁히는 편이 더 data-grounded하다.

### 3. Phase B cache의 correctness와 reuse 문제

Phase B persistent cache key는 `gene + position + PTM type + task + PMID set`이다. 그러나 kinase and functional tasks에는 experimental context, species, PTM/protein log2FC, pathway set, selected model/prompt version이 입력된다. 따라서 같은 PMID set이 다른 treatment, time-course, species 또는 model에서 재사용되면 **context-specific interpretation이 오래된 cache로 대체될 수 있다.**

또한 source comment는 “기존 PMID subset cache를 더 많은 PMID 요청에 재사용한다”고 설명하지만, 현재 `get_cached_best_match()` implementation은 `cached_pmids == requested`만 허용한다. 실제 partial subset reuse가 수행되지 않아, 설정상 article count가 변할 때 예상한 cache 효율을 얻지 못한다.

cache를 강화하기 전에 다음처럼 immutable article evidence와 order-specific interpretation을 분리해야 한다.

| Cache layer | key에 포함해야 할 값 | 저장해도 되는 결과 |
|---|---|---|
| `article_evidence_cache` | PMID, article text hash, extractor/model/prompt version | exact quote/claim, explicit regulation phrase, article-level structured fact |
| `site_literature_set_cache` | gene, site/form, PTM type, species, retrieval query version | ranked PMID list and retrieval provenance |
| `order_context_interpretation_cache` | order ID 또는 full context signature, Track 2/Track 1 summary, protein state, pathway set, model/prompt version | context-specific kinase/functional interpretation; short TTL 또는 no cross-order reuse |

## Evidence-routing 권장 설계

### Step 0: 분석 대상 우선순위화

literature/LLM enrichment 대상은 모든 modified peptide가 아니라 quality gate를 통과한 site/form으로 제한한다. 예를 들어 significant Track 2 regulation, sufficient time-course completeness, canonical wave membership, TMM candidate ambiguity, Track1/Track2 discordance, novel iPTMnet status, receptor/kinase/effector relevance를 기준으로 candidate tier를 생성한다.

### Step 1: structured database-first packet

각 gene에는 UniProt, KEGG/Reactome, 필요 시 STRING/BioGRID를 한 번씩 가져온다. 각 site/form에는 iPTMnet exact-site lookup을 수행한다. 이 packet만으로 충분한 경우에는 database citation/provenance를 남기고 PubMed/LLM을 생략한다.

```text
gene-level: UniProt + KEGG/Reactome + optional interaction context
site/form-level: iPTMnet exact-site/KSA/novelty + vector quality + temporal/TMM evidence
                         ↓
                  evidence-gap decision
```

### Step 2: selective PubMed retrieval

PubMed는 아래 조건 중 하나에 해당할 때만 실행한다.

| Trigger | PubMed가 필요한 이유 |
|---|---|
| exact site가 iPTMnet/UniProt에 없거나 ambiguity가 큼 | potential novelty 및 primary paper 확인 |
| high-confidence TMM/co-wave candidate와 curated evidence가 불일치 | contradiction resolution |
| treatment, cell type, disease, time-window 특이성이 결과 해석에 핵심 | structured database가 보통 제공하지 않는 experimental context 확보 |
| receptor/transgene 또는 mixed-species FASTA site | species/ortholog-specific literature 확인 |
| report에서 strong mechanistic statement가 필요 | claim-level primary citation 확보 |

검색은 **exact site/PTM query 1개, max 3 articles**로 시작한다. exact query가 0 result 또는 low relevance일 때에만 gene + context fallback을 하나 실행한다. broad `kinase OR phosphatase`와 `regulation OR signaling OR pathway` search는 default path가 아니라 escalation path로 이동한다.

### Step 3: one evidence packet, one LLM synthesis

같은 article set에 대해 abstract, kinase, functional prompt를 무조건 세 번 보내지 않는다. high-priority literature route에서는 하나의 `LiteratureEvidencePacket`을 만들고, Qwen이 다음을 한 JSON response로 반환하도록 한다.

```json
{
  "article_claims": [],
  "exact_site_evidence": [],
  "kinase_support_or_contradiction": [],
  "functional_context": [],
  "limitations": [],
  "pmid_provenance": []
}
```

TMM/co-wave candidate는 input context로 제공하되 LLM이 새로운 direct kinase score를 생성하게 하지 않는다. LLM output은 `supports`, `contradicts`, `insufficient literature`, `context mismatch` 같은 evidence labels로 제한한다.

### Step 4: full-text escalation

PMC full text는 top article 하나에만, 그리고 abstract evidence가 ambiguous하거나 method/site/residue/condition detail이 필요할 때 실행한다. full text를 모든 PTM·모든 abstract에 적용하면 latency와 token volume은 증가하지만, site-level conclusion의 정확도는 항상 비례해 증가하지 않는다.

## Recommended evidence budgets

| Route | 대상 | DB calls | PubMed | LLM | PMC full text |
|---|---|---|---|---|---|
| `db_only` | low-priority 또는 curated exact-site evidence 충분 | gene packet + iPTMnet | 0 | 0 | 0 |
| `abstract_targeted` | novelty/ambiguity/high-priority TMM or wave | gene packet + iPTMnet | exact query ≤3, one fallback only if needed | 1 unified evidence packet | 0 |
| `fulltext_escalated` | strong claim, contradiction, publication figure candidate | same | reuse targeted results | reuse packet + optional focused follow-up | top 1 |
| `report_synthesis` | final selected findings | stored evidence packet only | no new retrieval | report writer uses provenance-limited evidence | no new fetch |

## Implementation priority

| Priority | Change | Expected effect | Risk |
|---|---|---|---|
| P0 | PubMed Phase A article list를 PTMValidator/cross-site validator에 전달하고 duplicate search를 제거 | external API latency와 duplicate articles 즉시 감소 | validation function signature 변경 필요 |
| P0 | Phase B cache key를 immutable article facts와 context-specific interpretation으로 분리 | stale cross-condition interpretation 방지 | cache migration/invalidations 필요 |
| P0 | `get_cached_best_match()`의 subset logic을 specification에 맞게 수정하거나 name/docs를 exact match로 정정 | actual cache behavior와 contract 일치 | stale/partial evidence policy를 명확히 해야 함 |
| P1 | `evidence_gap_decision`과 route reason 저장 | 모든 PubMed/LLM call의 필요성·provenance 감사 가능 | routing thresholds validation 필요 |
| P1 | default PubMed context fallback을 broad 3-query fan-out에서 exact-first single fallback으로 축소 | unnecessary PubMed calls와 article noise 감소 | rare broad literature recall 저하 가능; user opt-in full mode 제공 |
| P1 | three LLM tasks를 one `LiteratureEvidencePacket` call로 통합 | Qwen 14B latency/token reduction, consistent source grounding | JSON schema와 report consumer migration 필요 |
| P2 | PubMedBERT reranking | small article budget에서 semantic relevance 개선 가능 | relevance benchmark 없이는 도입 근거 부족 |
| P2 | fixed audit dashboard | per-route latency, cache-hit, article utility, citation usage 측정 | telemetry schema 추가 필요 |

## 무엇을 유지해야 하는가

PubMed retrieval을 완전히 제거하면 exact-site DB가 부족한 novel PTM, condition-specific signaling, new literature, contradictory evidence, primary citation quality에서 정보 손실이 발생한다. 반대로 PubMed abstract만으로 `direct kinase-substrate` 또는 causality를 판정하면 안 된다. database evidence와 raw temporal evidence가 기본이고, literature는 **claim validation and contextualization layer**여야 한다.

Qwen 14B도 제거할 필요가 없다. 다만 Qwen은 broad knowledge answerer가 아니라, selected source text와 raw vector/TMM packet을 structured evidence label로 변환하는 **conditional synthesis tool**로 제한해야 한다.

## Final recommendation

현재 시스템은 “여러 DB를 이미 연결했으므로 PubMed가 불필요하다”는 상태가 아니다. 올바른 결론은 “structured DB가 canonical and curated evidence의 기본층을 제공하므로, PubMed/LLM은 모든 PTM에 default로 적용할 비용이 아니라 evidence gap을 메우는 selective escalation 층이어야 한다”이다.

가장 먼저 구현할 것은 새 external data source가 아니라 **중복 PubMed query 제거, cache correctness 분리, and evidence-route telemetry**다. 이후 실제 insulin dataset에서 db-only/abstract-targeted/fulltext-escalated route별 citation recall, user-accepted finding rate, latency, Qwen token volume을 비교해 article budget을 조정해야 한다.

## References

[1] National Library of Medicine. *About PubMed.* https://pubmed.ncbi.nlm.nih.gov/about/

[2] iPTMnet. *Integrated resource for understanding PTMs in systems biology context.* https://research.bioinformatics.udel.edu/iptmnet/
