# PubMed 문맥 키워드 & API Key 검토

Special Conditions, Biological Question의 PubMed 검색 사용 여부, 및 NCBI/STRINGDB API Key 관리 현황 검토 결과입니다.

---

## 1. 기존 소스(ptm-rag-backend) — Special Conditions, Biological Question

### ✅ PubMed 검색에 사용됨

**파일:** `latest/ptm-rag-backend/src/pubmedClient.ts`  
**함수:** `extractContextKeywords(context?: ExperimentalContext)`

```typescript
// STEP 1: Extract user input keywords
const userWords: string[] = [];
if (context.cellType) userWords.push(...extractMeaningfulWords(context.cellType));
if (context.treatment) userWords.push(...extractMeaningfulWords(context.treatment));
if (context.biologicalQuestion) userWords.push(...extractMeaningfulWords(context.biologicalQuestion));
if (context.specialConditions) userWords.push(...extractMeaningfulWords(context.specialConditions));
```

- **biologicalQuestion**: `extractMeaningfulWords()`로 분해 후 PubMed 쿼리 키워드에 사용
- **specialConditions**: 동일하게 사용
- 4자 이상, stopword 제거 후 키워드 추출 → Tier 2 (context-enhanced query)에 반영

### comprehensiveReportV3Client 타입

```typescript
// dist/comprehensiveReportV3Client.d.ts
specialConditions?: string;
biologicalQuestion?: string;
```

---

## 2. ptm-platform — PubMed 검색 시 문맥 사용

### 현재 구조

| 구간 | 파일 | 문맥 키 사용 |
|------|------|--------------|
| 문맥 키워드 추출 | `workers/rag_enrichment/core/enrichment_pipeline.py` | `_extract_context_keywords()` |
| PubMed 검색 | `mcp-server/app/tools/pubmed.py` | `context_keywords` 인자로 수신 |

### enrichment_pipeline.py - _extract_context_keywords

```python
for key in ("tissue", "treatment", "condition", "disease", "cell_type", "organism"):
    val = context.get(key)
    if val and isinstance(val, str):
        keywords.append(val)
```

- **biological_question**: ❌ 미사용  
- **special_conditions**: ❌ 미사용 (UI에 해당 필드 없음)  
- **condition**: ✅ 지원되나 UI에서 별도 입력 없음 → Special Conditions에 활용 가능

---

## 3. ptm-platform API Key 관리

### docker-compose.yml - mcp-server

```yaml
mcp-server:
  environment:
    NCBI_EMAIL: ${NCBI_EMAIL:-user@example.com}
    NCBI_API_KEY: ${NCBI_API_KEY:-}
    STRINGDB_API_KEY: ${STRINGDB_API_KEY:-}
```

### .env

```env
# External API Keys
NCBI_EMAIL=user@example.com
NCBI_API_KEY=
STRINGDB_API_KEY=
```

### NCBI (PubMed) — 사용 여부

| 항목 | ptm-platform | 비고 |
|------|--------------|------|
| NCBI_EMAIL | 사용 | `mcp-server/app/tools/pubmed.py` - esearch, efetch에 `email` 파라미터 |
| NCBI_API_KEY | 사용 | `api_key` 파라미터로 전달 (있을 때만) |

```python
# mcp-server/app/tools/pubmed.py
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "user@example.com")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
...
if NCBI_API_KEY:
    params["api_key"] = NCBI_API_KEY
```

→ `docker compose` 실행 시 `.env`의 `NCBI_EMAIL`, `NCBI_API_KEY`가 mcp-server에 전달되며 PubMed 요청에 사용됩니다.

### STRING-DB — 사용 여부

| 항목 | ptm-platform | 비고 |
|------|--------------|------|
| STRINGDB_API_KEY | 설정은 전달 | docker-compose에서 mcp-server로 전달 |
| 실제 API 호출 | 미사용 | `mcp-server/app/tools/stringdb.py`에서 key 미사용 |

```python
# mcp-server/app/tools/stringdb.py - 현재 요청
params={
    "identifiers": gene_name,
    "species": species,
    "limit": limit,
}
# STRINGDB_API_KEY를 params에 넣는 코드 없음
```

STRING-DB REST API는 기본 엔드포인트에서 key 없이도 동작하며, key는 주로 rate limit 완화용입니다. ptm-platform에서는 key가 설정되어 있어도 아직 활용하지 않습니다.

---

## 4. ptm-rag-backend vs ptm-platform

| 항목 | ptm-rag-backend | ptm-platform |
|------|-----------------|--------------|
| biologicalQuestion → PubMed | 사용 (extractMeaningfulWords) | 미사용 |
| specialConditions → PubMed | 사용 (extractMeaningfulWords) | 미사용 (필드 자체 없음) |
| NCBI_EMAIL | .env | .env + docker-compose |
| NCBI_API_KEY | .env | .env + docker-compose, 사용 |
| NCBI_TOOL | .env에 존재 | 없음 (NCBI 요청에 tool 파라미터 미사용) |
| STRINGDB_API_KEY | .env | .env + docker-compose, 미사용 |

---

## 5. 개선 제안

### 5.1 Biological Question, Special Conditions를 PubMed에 반영

`workers/rag_enrichment/core/enrichment_pipeline.py`의 `_extract_context_keywords`에 추가:

```python
# biological_question: 문장 → 의미 있는 단어들 추출 (ptm-rag-backend와 유사하게)
# special_conditions 또는 condition: 동일 처리
```

- `biological_question`, `special_conditions`(또는 `condition`) 문자열을 받아 stopword 제거, 4자 이상 단어로 분해
- 기존 `tissue`, `treatment` 등과 동일한 방식으로 `keywords` 리스트에 추가 후 PubMed에 전달

### 5.2 Special Conditions UI

- OrderCreate, RerunOptionsModal에 "Special Conditions" 입력 필드 추가
- `analysis_context.special_conditions` 또는 `condition`으로 저장

### 5.3 STRINGDB_API_KEY 사용 (선택)

STRING-DB 문서 확인 후, key를 요청 파라미터에 포함하는 방식으로 수정. 공개된 REST API 사용 방식에 따라 query parameter로 전달할 수 있는지 확인 필요.

---

## 6. Key 설정 방법 (ptm-platform)

1. 프로젝트 루트의 `.env` 수정:

```env
NCBI_EMAIL=your-email@example.com
NCBI_API_KEY=your-ncbi-api-key
STRINGDB_API_KEY=your-stringdb-api-key
```

2. `docker compose up` 시 해당 값이 mcp-server로 전달됨.  
3. NCBI key는 PubMed 요청에 즉시 반영됨. STRINGDB key는 현재 미사용.
