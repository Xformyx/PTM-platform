# PTM 통합 계약과 이행 경계

작성: 2026-09-18. 현재 기준 HEAD: `6e4b2b88b4d0a7098d1ac3cd593a42338d859144`. 감사 기준은 `319a6adba2832a4b5cee7058c311f44396381446`이며, 사용자 최신 커밋의 TMM CPU 격리 변경을 보존했다.
이 문서는 현재 작업 트리의 구현을 설명한다. 배포 또는 전체 요구사항 완료 선언이 아니다.

## Producer → contract → consumer

| 책임 | Producer | 계약 / artifact | 실제 consumer |
|---|---|---|---|
| 원자료 전수 기록 | preprocessing `PTMQuantificationAnalyzer.load_data`, 완료 시 재기록 | `source_observation_inventory.v1`, 내용 hash 파일 + current pointer | report task → authoring coverage → immutable packet |
| form / charge / mapping / QC | `ptm_quantification.py` | 기존 precursor/site-form v2 유지, `peptide_mapping_assertion.v1` 추가 | `vector_projection.py` → measured feature cards → section packet |
| loss / 분모 | 정량 sample 관측 grid | 기존 axis fields, detection counts, missing reason, NA | temporal adapter, vector projection, reader, comparison |
| 생물학적 단위 | orders → preprocessing config | `sample_manifest.v1`, `sample_manifest_crosswalk.v1` | primary/secondary tests, report context, temporal adapter |
| temporal 반복측정 | 실제 sample별 relative table | `biological_temporal_adapter.v1`, `paired_biological_sample_ratio_contrast.v1` | RAG temporal call / API regeneration |
| 정규화 | API analysis_context → preprocessing | `legacy_median.v1` / `already_normalized.v1` | vector policy, source manifest, Methods, comparison eligibility |
| source query | KEA3 / UniProt / STRING / KEGG / Reactome / PubMed / InterPro adapters | shared `source_query.v1`; source payload hash, query status | enrichment, caches, source evidence columns |
| 문헌 해석 | finding retrieval | `finding_retrieval.v5`, exact source span, proposed paraphrase/relationship, 별도 support status | reference cards → section packet → citation registry |
| 관계 | regulation extraction / network | polarity/directness assertion, `legacy_relation_view.v1` | ordered network edges; PPI는 gene 수준 |
| 전수 / 심층 검토 / 본문 범위 | measured feature cards + retrieval | `report_coverage_inventory.v1`, `module_evidence_index.v1`, adaptive selection trace | plan / section projection / immutable authoring packet |
| 저술 입력 | `build_authoring_packet` | 기존 evidence envelope / ClaimTier / value-token schema + `section_model_packet.v2` | 실제 writer의 narrative generation / validator |
| 검토 수정 | copilot | `evidence_bound_review.v1` + issue ledger + `bounded_report_repair.v1` | 기존 문장 validator → dependent sections → common release resolver |
| 인용 | graph `format_citations` | resolved identity + display_number + source paths | report task → HTML / DOCX / revision / PPTX notes |
| source snapshot | report task | `report_input_snapshot.v1`, source/config/design/model/collection 상태 | artifact manifest → revision → comparison |
| 공개 / 파일 | finalization | 기존 `reader_report_release.v7` + `report_revision.v1` | report listing / preview / direct download / UI / PPTX / comparison |

## 의미와 호환성

- 기존 `precursor_identity.v2`, `site_form_provenance.v2`, ClaimTier와 temporal directionality namespace를 대체하지 않았다. mapping assertion은 추가 provenance다. multisite form을 여러 독립 n으로 복제하지 않는다.
- 기존 정상 PR/PG 산술과 estimator ID는 유지한다. `ptm_quantitation_estimators.v2`는 정규화 policy가 명시된 새 보고서에만 적용한다. 기본 호출은 v1을 유지한다. 이미 정규화된 입력의 추가 scaling 생략은 명시적 opt-in이며 frozen benchmark에 소급 적용하지 않는다.
- 실제 생물학적 단위가 명시되면 technical repeats를 unit 안에서 평균한다. 반복측정 adapter는 별도 버전의 paired sample-ratio uncertainty 입력이며 condition means를 replicate라고 부르지 않는다. pairing이나 완전한 unit trajectory가 없으면 no-call이다.
- source no-hit은 검색 결과다. novelty, absence, probability가 아니다. 문헌의 exact quote 일치와 현재 claim 지지는 별개다. paraphrase는 보존하되 독립 source-faithfulness 판정 없이 검증 완료로 승격하지 않는다.
- `finding_review_budget.v1` 기본값은 queries 128, model calls 32, prompt UTF-8 bytes 100000이다. `report_config.finding_review_policy`로 명시적으로 변경한다. 예산 제한 항목도 기록하며 main finding 수 제한으로 분석 분모를 바꾸지 않는다.
- 모델 tokenizer가 제공되지 않으면 UTF-8 byte upper bound를 fallback으로 표시한다. output reserve를 빼고 card 경계에서 분할한다. indivisible packet이 크면 review 사유를 반환하며 잘린 JSON을 보내지 않는다.
- 새 interpretation cache는 v3 namespace와 전체 context/PMID/model/prompt key를 사용한다. 기존 cache 전체를 지우지 않는다. preprocessing stage key는 입력 bytes, policy, 관련 producer code를 사용한다. transitive dependency 전체와 운영 source snapshot을 완전히 동결하는 작업은 남아 있다.
- `report_revision.v1`은 기존 immutable artifact/release contract 위의 filesystem 인덱스다. DB report status를 대체하지 않는다. unknown schema / hash mismatch는 거부한다. `completed`는 `final_ready`와 같지 않다.
- 비교 artifact는 자체 revision과 두 source revision/hash를 가진다. 현재 order의 species 변경은 과거 comparison 계산을 바꾸지 않는다. source study scope/design/estimator가 없으면 차이를 계산하지 않는다.
- PPTX는 승인된 source revision의 plan/packet/figure를 읽는다. slide layout 검토가 없으면 파생 PPTX는 review draft다. queued 요청에는 source revision ID가 필수다.

## 이행과 rollback

운영 파일을 이 작업에서 backfill하거나 current pointer를 변경하지 않았다. 아래 명령은 유지보수 도구이며, 실제 대상 디렉터리와 명시적 파일 목록을 확인한 뒤 사용한다. glob/mtime 기반 자동 선택은 없다.

```sh
PYTHONPATH=. "$PTM_PYTHON" -m ptm_shared.report_revision verify "$ORDER_OUTPUT"
PYTHONPATH=. "$PTM_PYTHON" -m ptm_shared.report_revision backfill "$ORDER_OUTPUT" --file historical_report.md --file historical_report.docx --audience researcher_manuscript
PYTHONPATH=. "$PTM_PYTHON" -m ptm_shared.report_revision rollback "$ORDER_OUTPUT" --revision-id "$VERIFIED_REVISION_ID"
```

Backfill은 기존 bytes를 보존하고 `legacy_not_gated`로 등록한다. 이미 current revision이 있으면 CLI가 backfill을 거부한다. 신규 `legacy_unverified` enum은 도입하지 않았으며 기존 `legacy_not_gated` 의미를 사용한다. registry 없는 과거 파일은 `legacy_report_files`로 구분하고 일반 Report 다운로드로 승격하지 않는다.

Rollback은 검증된 기존 revision을 current로 선택하고 이력을 추가한다. artifact와 새 revision은 삭제하지 않는다. 이전 revision의 공개 정책도 유지한다. 신규 compare 저장 요청에는 `source_revision_ids`가 필요하며 구형 요청은 409로 재생성을 요구한다. 구형 PPTX queued task에 pin이 없으면 실패 상태를 반환한다.

## 아직 연결을 더 검증해야 하는 경계

- cross-talk 원관측은 실제 TypedDict의 `cross_talk_data`를 사용해 writer 전에 전달한다. module prose/figure/QA 전체의 claim 수준 의미 검증은 끝나지 않았다.
- cascade context는 저술 전에 template/input/figure hash와 함께 동결하며, 이후 본문으로 edge를 다시 계산하지 않는다. template 관계의 생물학적 source 검증과 별도 relation/layout API 분리는 추가 작업이다.
- 검토자는 같은 section packet과 전체 section 본문을 읽는다. `review_policy`의 `max_model_calls=12`, `context_tokens=32768`, `output_reserve=4096` 기본 예산을 쓰며 packet별 실제 prompt/hash와 검토하지 못한 범위를 기록한다. bounded repair는 한 번의 validator 수리 후 관련 section·요약을 재검증한다. 실행 가능한 숫자 binding/causal wording 규칙 외의 issue는 unresolved다. 추가 검색→새 evidence attempt 자동 재저술은 미완료다.
- 보고서 task는 기존 generation lock을 사용한다. rendering은 attempt 디렉터리에서 수행하지만 graph의 모든 중간 artifact까지 attempt별로 격리한 것은 아니다.
- fixture의 API helper / compiled LangGraph / converter 검증은 실제 Celery·DB·UI 서비스의 end-to-end 완료를 뜻하지 않는다.

## 이번 정책 변경의 적용 범위

- `cross_ptm_observation.v2` / `unambiguous_form_descriptive_comparison.v1`: 전체 vector를 읽고 원관측을 보존한다. 동일 gene/condition의 여러 form·충돌 값은 하나의 gene 값으로 축약하지 않는다. 시간차는 `first_sampled_nonzero_contrast.v1` 관측이며 직접 기전을 생성하지 않는다. replicate 통계가 아니며 PTM→protein causal time-lag 분석은 not_evaluable이다.
- `anchored_local_motif.v2`: legacy unified consumer까지 named PTM anchor를 적용한다. sequence hash/policy를 cache key에 포함하고 ambiguous protein group과 residue 불일치는 no-call이다. 일반 regulator context는 site prediction이 아니다.
- `interpro_full_source.v2`: 표시용 5개와 full_domains/source_pages를 분리한다. 최대 20페이지를 넘으면 미완료 상태다. 오류는 성공 cache에 저장하지 않으며 hit/no-hit TTL은 각각 7일/1시간, local derived domain cache는 source fetched_at 기준 최대 1일이다.
- `question_and_claim_coverage.v2`: 문헌 20편 조건을 품질 gate에서 제거했다. reference 수는 기술 지표이며 claim binding·질문 범위·필수 module 상태를 별도로 검사한다. 과거 artifact의 release 판정을 소급 변경하지 않는다.
- FASTA 중복 accession의 서로 다른 sequence는 mapping assertion에 모두 남긴다. conflicting gene annotation은 Unknown이며 정렬 순서로 결정하지 않는다.
- reference mount 경로는 `PTM_MAPPING_SNAPSHOT_HOST_PATH` / `PTM_RELATION_SNAPSHOT_HOST_PATH`로 지정할 수 있다. 기존 frozen bundle hash와 컨테이너 경로는 그대로다. 배포 확인 없이 사용 가능하다고 표시하지 않는다.
