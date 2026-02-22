# Analysis Focus → Report 적용 현황 검토

Create New Order의 **Analysis Focus** 입력값(Cell Type, Treatment, Time Points, Biological Question)이 Reporting 단계에서 어떻게 적용되는지, 및 **Special Conditions** 참조 여부 검토 결과입니다.

---

## 1. 현재 UI 입력 필드 (OrderCreate / RerunOptionsModal)

| 필드 | OrderCreate | RerunOptionsModal | API/DB 키 |
|------|-------------|-------------------|-----------|
| Cell Type | ✅ | ✅ | `cell_type` |
| Treatment | ✅ | ✅ | `treatment` |
| Time Points | ✅ | ✅ | `time_points` |
| Biological Question | ✅ | ✅ | `biological_question` |
| **Special Conditions** | ❌ 없음 | ❌ 없음 | - |

→ **Special Conditions** 입력창은 구현되어 있지 않습니다. 코드 전역에서 `special_conditions` / `specialConditions` 참조가 없습니다.

---

## 2. Reporting 시 `experimental_context` 사용처

`analysis_context`는 백엔드에서 `experimental_context`로 전달됩니다.

### 2.1 RAG Enrichment (PubMed 검색 키워드)

**파일:** `workers/rag_enrichment/core/enrichment_pipeline.py`

```python
def _extract_context_keywords(self, context):
    for key in ("tissue", "treatment", "condition", "disease", "cell_type", "organism"):
        val = context.get(key)
        ...
```

- **cell_type** ✅ 사용됨 (PubMed 검색 키워드)
- **treatment** ✅ 사용됨
- **time_points** ❌ 미사용
- **biological_question** ❌ 미사용
- **condition** ✅ 키는 지원하나 UI에서 입력 안 함 (Special Conditions에 해당 가능)

---

### 2.2 Report Generation – Context Loader (기본 Research Questions 생성)

**파일:** `workers/report_generation/core/nodes/context_loader.py`

```python
def _generate_default_questions(ptms, context):
    tissue = context.get("tissue", "")
    treatment = context.get("treatment", "")
    ...
    if tissue:
        context_desc += f" in {tissue}"
    if treatment:
        context_desc += f" under {treatment}"
```

- **tissue** 사용 (우리 UI는 `cell_type`만 전송 → `tissue` 없음 → 기본 질문에 "in {tissue}" 누락)
- **treatment** ✅ 사용됨
- **time_points**, **biological_question** ❌ 미사용

---

### 2.3 Report Generation – Writer Node (Abstract, Introduction 등)

**파일:** `workers/report_generation/core/nodes/writer_node.py`

```python
keywords = [context.get("tissue", ""), context.get("treatment", ""), ...]
tissue = context.get("tissue", "the experimental system")
treatment = context.get("treatment", "the applied treatment")
# Prompt: "Experimental System: {tissue}, {treatment}"
```

- **tissue** 사용 (없으면 `"the experimental system"` 폴백)
- **treatment** ✅ 사용됨
- **cell_type** ❌ 직접 미사용 (cell_type으로 tissue 보강 필요)

---

### 2.4 Report Generation – Hypothesis Node

**파일:** `workers/report_generation/core/nodes/hypothesis_node.py`

```python
tissue = context.get("tissue", "the given experimental system")
treatment = context.get("treatment", "the applied treatment")
# Prompt: "Experimental Context: {tissue}, {treatment}"
```

- **tissue**, **treatment** 사용 (tissue 없으면 `"the given experimental system"` 폴백)

---

### 2.5 Report Output (Experimental Context 섹션)

**파일:**  
`workers/rag_enrichment/core/report_generator.py`,  
`workers/report_generation/core/nodes/editor_node.py`

```python
for key in ("tissue", "organism", "treatment", "condition", "cell_type"):
    val = context.get(key)
    if val:
        lines.append(f"- **{key}**: {val}")
```

- **tissue**, **organism**, **treatment**, **condition**, **cell_type** 모두 출력에 반영
- UI에서 보내는 것: `cell_type`, `treatment`만 있음 → `tissue`, `condition`, `organism`은 비어 있음

---

## 3. 필드별 요약

| 필드 | UI 입력 | Reporting 사용 | 비고 |
|------|---------|----------------|------|
| **cell_type** | ✅ | RAG 키워드, 최종 리포트 Experimental Context | 일부 노드는 `tissue`를 쓰므로 `tissue` 매핑 필요 |
| **treatment** | ✅ | RAG 키워드, Context Loader, Writer, Hypothesis, 리포트 출력 | 정상 적용 |
| **time_points** | ✅ | ❌ 미사용 | 어디에서도 참조되지 않음 |
| **biological_question** | ✅ | ❌ 미사용 | 어디에서도 참조되지 않음 |
| **Special Conditions** | ❌ 없음 | `condition` 키로 사용 가능 | 별도 입력 UI 없음 |

---

## 4. 개선 제안

### 4.1 `tissue` ↔ `cell_type` 매핑

Writer, Hypothesis, Context Loader가 `tissue`를 사용하므로, 아래 중 하나가 필요합니다.

- 옵션 A: API 제출 시 `tissue: cell_type` 추가  
  (예: `analysis_context`에 `tissue: form.cell_type`)
- 옵션 B: Worker에서 `context.get("tissue") or context.get("cell_type")`로 fallback

### 4.2 `time_points`, `biological_question` 활용

- **time_points**: Writer/Hypothesis 프롬프트에 "Time Points: {time_points}"等形式으로 추가
- **biological_question**:  
  - Research Questions의 기본 후보로 사용  
  - 또는 Context Loader의 `_generate_default_questions`에 `biological_question`이 있으면 우선 반영

### 4.3 Special Conditions 추가

- UI: Analysis Focus에 "Special Conditions" 입력 필드 추가
- API: `analysis_context.special_conditions` 또는 `condition`으로 저장
- Worker: `condition` 또는 `special_conditions`를 experimental_context에 포함해 리포트와 키워드에 반영

---

## 5. Special Conditions 참조 여부

**결론: Special Conditions를 참조하는 코드는 없습니다.**

- 프론트엔드: OrderCreate, RerunOptionsModal에 해당 필드 없음
- API: `analysis_context`에 `special_conditions` / `condition` 키 없음
- Worker: `condition`은 experimental_context에 대한 fallback으로 사용 가능하지만, UI에서 이 값을 채워 보내지 않음
