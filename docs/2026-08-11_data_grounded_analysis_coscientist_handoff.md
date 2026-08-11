# Data-Grounded Analysis 및 외부 Co-Scientist 연동 핸드오프

> **작성일:** 2026-08-11  
> **대상 브랜치:** `main`  
> **주요 구현 커밋:** `846fa53`  
> **후속 체크리스트 커밋:** `0e6c6ac`  
> **프로젝트:** `Xformyx/PTM-platform` / `/home/ubuntu/ptm-pipeline-docs`

## 1. 이 문서의 목적

이 문서는 다음 AI agent 또는 개발자가 **내부 Data-Grounded Analysis**와 **외부 PTM-CoScientist 서비스**를 혼동하지 않고, 오늘 추가된 Discussion Evidence Packet 기반 보고서 연동을 안전하게 유지·확장할 수 있도록 작성되었다.

이번 구현의 핵심은 외부 Co-Scientist의 긴 연구 결과나 ELO 토너먼트 원자료를 Report에 무분별하게 넣는 것이 아니다. 사용자가 선택한 완료 세션에서 **버전이 고정된 Discussion Evidence Packet**만 가져오고, 플랫폼이 다시 PTM site와 문헌 식별자를 확인한 뒤, 가설을 **분리된 Addendum** 또는 **명시적으로 opt-in한 Discussion 보강**에만 사용하는 구조다.

---

## 2. 용어와 역할 분리

| 구분 | 사용자 표시명 | 내부 식별자 / 서비스 | 책임 |
|---|---|---|---|
| 내부 분석 파이프라인 | **Data-Grounded Analysis (데이터 기반 가설·검증)** | 기존 `report_type='co_scientist'` | temporal cascade, co-wave, autophosphorylation, TMM과 실험 PTM 데이터를 이용해 질문·가설·검증 결과 생성 |
| 외부 연구 서비스 | **Co-Scientist** | `ptm-coscientist-api` | Generate → Debate → Evolve → Experiment Design, ChromaDB 기반 문헌 심화 연구 |
| 외부 결과의 Report 입력 | **Discussion Evidence Packet** | `discussion_evidence_packet`, schema `1.0` | 선택된 가설, 지지/반증 근거, 한계, 검증 가능 예측을 Report에 안전하게 전달 |

### 반드시 유지할 원칙

1. 내부 report type의 Python 식별자 `co_scientist`는 기존 Order 호환성을 위해 **변경하지 않았다**. 변경된 것은 UI와 Report 상의 표시명이다.
2. 외부 Co-Scientist는 내부 Data-Grounded Analysis보다 더 넓은 연구·토론·실험 설계 기능을 수행한다. 두 기능을 하나의 이름으로 부르지 않는다.
3. 외부 가설은 **측정된 결과가 아니며**, Results에는 넣지 않는다.
4. 외부 packet은 항상 사용자가 명시적으로 세션을 선택해야 한다. 최신 세션을 자동 선택하지 않는다.

---

## 3. 사용자 흐름

### 3.1 Data-Grounded Analysis

Order 생성 또는 rerun의 `Report Type`에서 다음 항목을 선택한다.

```text
Data-Grounded Analysis (데이터 기반 가설·검증)
```

이 모드에서는 사용자의 수동 Research Questions 입력을 숨기고 빈 배열을 전송한다. 백엔드의 `question_generator.py`가 temporal cascade, top kinase, co-wave, self-PTM, TMM 정보를 기반으로 연구 질문을 자동 생성한다.

### 3.2 외부 Co-Scientist 연구

각 Order의 **Co-Scientist 탭**에서 세 가지 연구 모드를 선택할 수 있다.

| 모드 | 외부 서비스에 전달되는 Research Goal | 권장 사용 사례 |
|---|---|---|
| `goal_led` | 사용자가 작성한 Research Goal만 전달 | 특정 단백질·수용체·기전을 독립적으로 연구 |
| `data_guided` | Data-Grounded seed만 전달 | PTM 데이터에서 보이는 신호의 넓은 해석 |
| `hybrid` | 사용자 Goal + Data-Grounded seed | 기본 권장. 사용자 목표를 유지하면서 데이터 기반 후보를 보조 맥락으로 제공 |

Data-Grounded seed는 **강제 연구 질문이 아니다**. 외부 Co-Scientist가 반증·대체 기전을 탐색할 수 있도록 시간대별 kinase, co-wave, receptor, TMM 요약 및 우선 질문을 보조 컨텍스트로 제공한다.

### 3.3 Report에 외부 세션 포함

외부 Co-Scientist 세션이 `completed`가 된 후 Report rerun 창의 **External Co-Scientist Discussion**에서 다음을 선택한다.

| UI 선택 | `co_scientist_integration.mode` | Report 효과 |
|---|---|---|
| `Do not include external Co-Scientist` | 없음 / disabled | 외부 결과를 사용하지 않음 |
| `Hypothesis & Validation Addendum` | `addendum` | Conclusion 뒤에 provenance 중심의 독립 Addendum 추가 |
| `Enhanced Discussion (opt-in)` | `enhanced_discussion` | 최대 2개 검증 후보를 Discussion 해석 보조 자료로만 전달 |

Report Options overview에는 선택된 모드와 session ID 앞부분이 표시된다.

---

## 4. 외부 서비스 API 연동

### 4.1 Order-scoped proxy

파일: `api-server/app/api/coscientist.py`

기존 프록시를 확장했다.

| 엔드포인트 | 용도 |
|---|---|
| `POST /api/orders/{order_id}/coscientist/run` | `research_mode`를 받아 외부 연구 세션 시작 |
| `GET /api/orders/{order_id}/coscientist/sessions` | 해당 Order의 완료/진행 세션 목록 |
| `GET /api/orders/{order_id}/coscientist/session/{session_id}` | 세션 상태·결과 polling |
| `GET /api/orders/{order_id}/coscientist/session/{session_id}/discussion-packet?max_hypotheses=2` | versioned Discussion Evidence Packet 조회 |

`POST .../run`에서 외부 최신 계약에 맞게 다음 payload를 만든다.

```json
{
  "order_codes": ["<order_code>"],
  "research_goal": "<goal-led / data-guided / hybrid 결과>",
  "ptm_type": "phosphorylation",
  "rag_collections": ["..."],
  "max_iterations": 3,
  "llm_provider": "...",
  "llm_model": "..."
}
```

`_build_data_grounded_seed(order)`가 read-only seed를 생성한다. 완전한 PTM artifact를 프론트엔드에서 전송하지 않으며, 외부 Co-Scientist는 기존의 read-only artifact volume에서 실제 Order 데이터를 읽는다.

---

## 5. Report option 전파 경로

선택된 외부 세션 정보는 `report_options.co_scientist_integration`에 저장되고, 전체 파이프라인을 따라 보존된다.

```json
{
  "enabled": true,
  "mode": "addendum",
  "session_id": "<completed_session_id>",
  "max_hypotheses": 2
}
```

### 전파 수정 파일

| 파일 | 책임 |
|---|---|
| `frontend/src/components/RerunOptionsModal.tsx` | 완료 세션 조회·선택, Addendum/Enhanced Discussion 설정 저장 |
| `api-server/app/api/orders.py` | Order 재실행/생성 request config에 integration 전달 |
| `workers/preprocessing/tasks.py` | preprocessing → RAG handoff에 integration 보존 |
| `workers/rag_enrichment/tasks.py` | RAG → report handoff에 integration 보존 |
| `workers/report_generation/tasks.py` | LangGraph initial state에 integration 삽입 |
| `workers/report_generation/core/graph.py` | `ReportState` field 및 external context node 삽입 |

### LangGraph 흐름

기존 흐름에 다음 노드가 들어갔다.

```text
... → temporal_comovement → kinase_annotation → rq_refinement
    → external_coscientist_context → write_sections
    → report_copilot → cascade_mediator → ...
```

Node 위치는 중요하다. `rq_refinement` 이후여야 Data-Grounded 결과와 기존 분석 컨텍스트가 준비된 상태이며, `write_sections` 이전이어야 선택된 packet을 Discussion prompt 또는 Addendum에 안전하게 반영할 수 있다.

---

## 6. Discussion Evidence Packet 소비 규칙

핵심 구현 파일: `workers/report_generation/core/nodes/external_coscientist_node.py`

### 6.1 Feature flag

외부 packet 연동은 기본적으로 **비활성화**되어 있다.

```env
COSCIENTIST_ENABLED=false
COSCIENTIST_BASE_URL=http://ptm-coscientist-api:8080
COSCIENTIST_MAX_HYPOTHESES=2
COSCIENTIST_REQUEST_TIMEOUT_SECONDS=20
```

실제 운영 시에만 `COSCIENTIST_ENABLED=true`로 설정하고 API server 및 Report worker를 재시작한다. 기능이 disabled이거나 integration 설정이 없으면 원격 HTTP 요청을 전혀 보내지 않는다.

### 6.2 packet 수용 품질 게이트

아래 조건 중 하나라도 만족하지 않으면 packet 또는 해당 가설을 사용하지 않는다.

| 검증 | 조건 |
|---|---|
| Schema | `schema_version == '1.0'` |
| Type | `packet_type == 'discussion_evidence_packet'` |
| Status | `status == 'ready'` |
| Session | 선택한 `session_id`와 packet의 session ID가 일치 |
| Hypothesis quality | `quality_gate.passed == true` |
| PTM site | `supporting_ptm_sites` 중 하나 이상이 플랫폼 관측 PTM site와 일치 |
| Literature | PMID/DOI/title이 플랫폼 ChromaDB에서 재해결됨 |
| Scientific caveat | `limitations` 또는 `counter_evidence`가 존재 |
| Count | 최대 `COSCIENTIST_MAX_HYPOTHESES`개, 기본 2개 |

### 6.3 실패 격리

다음 상황은 Report failure가 아니라 `co_scientist_status` 상태 변화와 warning만 남기는 **non-blocking skip**이다.

| 상황 | 상태 |
|---|---|
| feature disabled | `disabled` |
| integration 미선택 / session ID 없음 | `skipped` |
| 외부 HTTP 오류, timeout, malformed JSON, schema mismatch | `failed` 또는 `timed_out` |
| 세션 미완료 / packet not ready | `skipped` |
| PTM 또는 문헌 검증 후 남은 후보 없음 | `skipped` |
| 성공 | `ready` |

사용한 정규화 packet은 Report output directory에 재현성 snapshot으로 저장된다.

```text
coscientist_discussion_packet_<session_id>.json
```

---

## 7. Writer와 최종 Report 반영

파일: `workers/report_generation/core/nodes/writer_node.py`

### Addendum mode

`mode='addendum'`에서는 LLM이 Results/Discussion 본문을 다시 작성하지 않는다. packet에서 결정론적으로 다음 성격의 별도 섹션을 생성한다.

```text
## Hypothesis & Validation Addendum: External Co-Scientist
```

섹션은 source session, research goal, 각 hypothesis claim, data support, re-resolved literature, counter-evidence, limitations, testable prediction을 포함한다. `format_citations()`가 Conclusion 뒤에 이 Addendum을 붙인다.

### Enhanced Discussion mode

`mode='enhanced_discussion'`에서는 검증된 외부 후보만 `Discussion` prompt의 별도 컨텍스트 블록으로 전달한다. 다음 경계 문구는 유지해야 한다.

> 외부 Co-Scientist 후보는 exploratory interpretation이다. Results에 보고하지 말고, 확정 인과 관계로 표현하지 않으며, limitation/counter-evidence와 함께 제시한다.

Writer는 Discussion에서 `suggests`, `may`, `is consistent with`, `warrants experimental testing` 같은 제한적 표현을 사용하도록 지시받는다.

### 문헌 reference 처리

packet이 제공한 문헌은 그대로 믿지 않는다. `resolved_literature`로 다시 찾은 문헌만 `collected_references`에 추가해 최종 `## References`에 넣는다.

---

## 8. UI 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `frontend/src/components/CoScientistTab.tsx` | Goal-led / Data-guided / Hybrid Research select 추가, `research_mode` 전송 |
| `frontend/src/components/RerunOptionsModal.tsx` | Data-Grounded Analysis rename, 완료 session select, Addendum/Enhanced Discussion option 추가 |
| `frontend/src/pages/OrderCreate.tsx` | 내부 report type 표시명을 Data-Grounded Analysis로 변경 |
| `frontend/src/pages/OrderDetail.tsx` | 선택된 외부 session provenance를 Report Options overview에 표시 |

### UI 관련 주의사항

1. Rerun modal은 `completed` 상태의 외부 session만 선택 목록에 보인다.
2. 외부 session이 없으면 Addendum/Enhanced Discussion은 저장해도 실질 integration이 disabled로 전송된다.
3. 새 Order 생성 단계에서는 아직 외부 세션이 존재하지 않으므로 외부 session 선택 UI를 넣지 않았다. 먼저 Order 분석 완료 → Co-Scientist 실행 → Report rerun 순서가 맞다.

---

## 9. 검증 상태

### 완료한 검증

```bash
cd /home/ubuntu/ptm-pipeline-docs

python3 -m py_compile \
  api-server/app/api/coscientist.py \
  api-server/app/api/orders.py \
  api-server/app/config.py \
  workers/report_generation/core/graph.py \
  workers/report_generation/core/nodes/external_coscientist_node.py \
  workers/report_generation/core/nodes/writer_node.py

PYTHONPATH=workers python3 -m unittest workers/tests/test_external_coscientist_node.py
PYTHONPATH=workers python3 -c "from report_generation.core.graph import build_report_graph; build_report_graph(); print('GRAPH_COMPILE_OK')"
```

회귀 테스트는 다음 3개를 통과했다.

| 테스트 | 목적 |
|---|---|
| feature disabled | remote service를 호출하지 않고 `disabled` 반환 |
| ready packet | schema, quality gate, PTM site, literature 조건을 만족하면 `ready` 반환 |
| invalid schema | `2.0` schema를 fail-closed 하되 Report를 중단하지 않음 |

### 알려진 환경 제약

* local sandbox에는 Docker CLI가 없어 `docker compose config -q`를 실행하지 못했다.
* frontend TypeScript 검사에서 `react-router-dom` 모듈 누락 오류가 보일 수 있다. 이는 이번 변경이 아니라 sandbox의 frontend dependency 설치 상태 문제다. 수정 파일에서 별도의 신규 TypeScript 오류는 확인되지 않았다.

---

## 10. 다음 AI agent의 우선 점검 항목

| 우선순위 | 점검/개선 항목 | 이유 |
|---|---|---|
| 높음 | 실제 배포 환경에서 `COSCIENTIST_ENABLED=true`로 Addendum happy path 실행 | mock test만 통과했으며 live network/volume mount까지는 검증하지 않음 |
| 높음 | PTM-CoScientist `/discussion-packet` 응답이 handoff schema `1.0`과 정확히 일치하는지 확인 | schema mismatch 시 안전하게 skip되므로 Report에는 영향 없지만 기능은 나타나지 않음 |
| 높음 | PTM site 문자열 정규화 보완 | 외부 site 표기(`SRC-Y416`, `SRC_Y416`, `SRC:Y416`)와 platform raw-data 표기의 실제 차이를 확인 |
| 중간 | Addendum의 inline citation 번호와 외부 re-resolved reference mapping 개선 | 현재 재해결 reference는 References에 추가되지만 deterministic Addendum의 citation 번호를 별도 고정하지 않음 |
| 중간 | packet retrieval telemetry 추가 | skip/failed 이유를 Order UI 또는 worker log dashboard에서 쉽게 확인 가능하도록 개선 |
| 낮음 | `report_type='co_scientist'` 내부 식별자 migration 검토 | 현 단계에서는 backward compatibility 때문에 유지하는 것이 맞음 |

### 절대 회귀시키면 안 되는 동작

1. `COSCIENTIST_ENABLED=false`일 때 기존 standard/extended/Data-Grounded Report가 외부 HTTP 호출 없이 정상 수행되어야 한다.
2. 외부 Co-Scientist 오류가 Report task failure로 전파되면 안 된다.
3. 외부 가설을 Results의 측정 사실처럼 쓰면 안 된다.
4. `Enhanced Discussion`은 명시적 선택이 있어야 하며, 자동으로 활성화되면 안 된다.
5. `Data-Grounded Analysis`는 외부 Co-Scientist의 단순 별칭이 아니다.

---

## 11. 관련 파일 색인

```text
docs/coscientist_discussion_packet_contract.md
docs/2026-08-11_data_grounded_analysis_coscientist_handoff.md

api-server/app/api/coscientist.py
api-server/app/api/orders.py
api-server/app/config.py
docker-compose.yml

frontend/src/components/CoScientistTab.tsx
frontend/src/components/RerunOptionsModal.tsx
frontend/src/pages/OrderCreate.tsx
frontend/src/pages/OrderDetail.tsx

workers/preprocessing/tasks.py
workers/rag_enrichment/tasks.py
workers/report_generation/tasks.py
workers/report_generation/core/graph.py
workers/report_generation/core/nodes/external_coscientist_node.py
workers/report_generation/core/nodes/writer_node.py
workers/tests/test_external_coscientist_node.py
```

## 12. Git 이력

| Commit | 설명 |
|---|---|
| `6cb978a` | Co-Scientist 모드에서 질문 자동 생성 및 수동 질문 입력 비노출 |
| `b672f36` | Data-Grounded 내부 모드의 수동 질문 UI 정합성 보완 |
| `846fa53` | Data-Grounded rename + 외부 Discussion Evidence Packet 연동 구현 |
| `0e6c6ac` | 구현·검증 체크리스트 반영 |

---

## References

[1] `docs/coscientist_discussion_packet_contract.md` — 이번 구현에서 따르는 Discussion Evidence Packet 계약 요약.  
[2] `workers/report_generation/core/nodes/external_coscientist_node.py` — packet 조회, 검증, snapshot 및 writer context/addendum 생성 구현.  
[3] `workers/tests/test_external_coscientist_node.py` — disabled, ready, invalid schema failure-isolation 회귀 테스트.
