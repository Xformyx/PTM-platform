# 중장기 개선 설계 문서: Upstream Receptor Inference 안정화

## 개요

본 문서는 Ubiquitylation 분석 시 upstream receptor 추론 결과가 불안정한 문제의 근본적 해결을 위한 중장기 개선 방안 3가지를 설계합니다.

---

## 4. Kinase Module Analysis → E3 Module Analysis 확장

### 현재 문제

`kinase_weight_manager.py`의 8가지 추론 전략은 **인산화(phosphorylation)** 전용으로 설계되어 있습니다:

| 전략 | 인산화 적합성 | 유비퀴틴화 적합성 |
|------|-------------|-----------------|
| Strategy 1: PSSM | 높음 (PhosphoSitePlus PSSM) | **낮음** (E3 PSSM 부재) |
| Strategy 2: PhosphoSitePlus | 높음 | **불가** (E3 DB 아님) |
| Strategy 3: KEA3 | 높음 | **불가** (kinase 전용) |
| Strategy 4: Network-Edge | 중간 | 중간 (STRING-DB 활용 가능) |
| Strategy 5: Temporal-Correlation | 높음 | 높음 (PTM 유형 무관) |
| Strategy 6: Literature-Mining | 높음 | 중간 (E3 문헌 상대적 부족) |
| Strategy 7: Substrate-Motif | 높음 (consensus motif) | **낮음** (E3 motif 다양) |
| Strategy 8: Pathway-Context | 높음 | 중간 |

### 설계 방안

```
┌─────────────────────────────────────────────────────────────┐
│                  E3 Module Analysis                          │
├─────────────────────────────────────────────────────────────┤
│ Strategy 1: UbiSite PSSM (ubiquitylation site specificity)  │
│ Strategy 2: UbiNet DB (실험 검증 E3-substrate 관계)          │
│ Strategy 3: E3-substrate enrichment (Fisher exact test)      │
│ Strategy 4: STRING-DB PPI (E3-substrate interaction)         │
│ Strategy 5: Temporal-Correlation (동일 — PTM 유형 무관)       │
│ Strategy 6: Literature-Mining (E3 키워드 확장)               │
│ Strategy 7: Degron Motif (destruction box, PEST 등)          │
│ Strategy 8: Pathway-Context (동일)                           │
└─────────────────────────────────────────────────────────────┘
```

### 구현 계획

1. `enhanced_motif_analyzer_v2.py`에 `predict_e3_ligase()` 함수 추가
2. `kinase_weight_manager.py`를 `regulator_weight_manager.py`로 일반화
3. Order의 PTM 유형에 따라 kinase/E3 모듈 자동 선택:
   ```python
   if order.ptm_type in ("ubiquitylation", "ubiquitination", "ub"):
       module = E3ModuleAnalysis(strategies=E3_STRATEGIES)
   else:
       module = KinaseModuleAnalysis(strategies=KINASE_STRATEGIES)
   ```

### 필요 외부 리소스

| 리소스 | URL | 용도 |
|--------|-----|------|
| UbiNet 2.0 | http://ubinet.ncpsb.org.cn | E3-substrate 관계 DB |
| E3Atlas | http://e3atlas.org | E3 리가아제 종합 DB |
| iPTMnet | https://research.bioinformatics.udel.edu/iptmnet/ | PTM 유형별 효소-기질 관계 |
| PhosphoSitePlus (Ub) | https://www.phosphosite.org | 유비퀴틴화 부위 데이터 |

### 예상 소요 시간: 2-3주

---

## 5. Source A에서 LLM temperature=0 강제

### 현재 문제

RAG enrichment 파이프라인에서 LLM 호출 시 temperature가 명시적으로 설정되지 않아, 기본값(보통 0.7~1.0)이 적용됩니다. 이로 인해 동일한 PTM 부위에 대해 매번 다른 `upstream_regulators`가 생성됩니다.

### 설계 방안

```python
# workers/preprocessing/core/rag_enrichment.py (또는 해당 LLM 호출 위치)

# 현재:
response = await llm_client.chat(
    messages=messages,
    model="gpt-4o",
    # temperature 미지정 → 기본값 사용
)

# 수정:
response = await llm_client.chat(
    messages=messages,
    model="gpt-4o",
    temperature=0,  # 결정론적 출력 보장
    seed=42,        # OpenAI seed 파라미터 (추가 결정론성)
)
```

### 적용 범위

| 파일 | LLM 호출 위치 | temperature 설정 |
|------|--------------|-----------------|
| `rag_enrichment.py` | upstream_regulators 추론 | **0** (결정론적) |
| `kinase_annotation_node.py` | kinase 예측 | **0** (결정론적) |
| `report_generation/nodes/*.py` | 보고서 생성 | 0.3 (약간의 다양성 허용) |
| `integrated_analysis_node.py` | 통합 분석 | 0.3 (약간의 다양성 허용) |

### 주의사항

- `temperature=0`으로 설정해도 OpenAI API는 100% 결정론적이지 않음 (내부 batching 등)
- `seed` 파라미터를 함께 사용하면 결정론성이 크게 향상됨
- 보고서 생성 등 창의성이 필요한 부분은 temperature를 유지

### 예상 소요 시간: 1일

---

## 6. Reactome 대안 DB: UbiNet, E3Atlas 통합

### 현재 문제

`reactome_client.py`의 `get_receptors_for_kinases()` 함수는 Reactome API에서 "Signaling by {RECEPTOR}" 패턴을 찾는데, E3 리가아제는 이 패턴에 잘 매핑되지 않습니다.

### 설계 방안

```
┌──────────────────────────────────────────────────────────────┐
│           Unified Upstream Receptor Resolver                  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Input: regulator_names (kinase OR E3 ligase)                │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Reactome   │  │   UbiNet    │  │  E3Atlas/iPTMnet    │  │
│  │  (kinase→   │  │  (E3→sub→  │  │  (E3→pathway→       │  │
│  │   receptor) │  │   pathway→  │  │   receptor)         │  │
│  │             │  │   receptor) │  │                     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
│         └────────────────┼─────────────────────┘             │
│                          ▼                                   │
│              Merge & Score (confidence-weighted)              │
│                          ▼                                   │
│              Unified Receptor List                            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### UbiNet 통합 방법

```python
# api-server/app/services/ubinet_client.py (신규 파일)

import httpx
from functools import lru_cache

UBINET_BASE_URL = "http://ubinet.ncpsb.org.cn/api"

async def get_e3_substrates(e3_name: str) -> list[dict]:
    """UbiNet에서 E3 리가아제의 기질 목록 조회"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{UBINET_BASE_URL}/e3/{e3_name}/substrates")
        if resp.status_code == 200:
            return resp.json().get("substrates", [])
    return []

async def get_e3_pathways(e3_name: str) -> list[str]:
    """UbiNet에서 E3 리가아제가 관여하는 경로 목록 조회"""
    substrates = await get_e3_substrates(e3_name)
    # 기질들의 pathway annotation을 수집하여 receptor 추론
    pathways = set()
    for sub in substrates:
        for pathway in sub.get("pathways", []):
            pathways.add(pathway)
    return list(pathways)
```

### 통합 우선순위

| DB | 신뢰도 | 커버리지 | 통합 난이도 |
|----|--------|---------|------------|
| Patch 02 (정적 E3 매핑) | 높음 | 낮음 (~25 E3) | 완료 |
| iPTMnet API | 높음 | 중간 | 낮음 (REST API 제공) |
| UbiNet 2.0 | 높음 | 높음 | 중간 (API 불안정) |
| E3Atlas | 중간 | 높음 | 중간 |

### 예상 소요 시간: 1-2주

---

## 구현 로드맵

| 주차 | 작업 | 파일 |
|------|------|------|
| Week 1 | Patch 01-02 적용 + temperature=0 설정 | orders.py, ligand_receptor_db.py, rag_enrichment.py |
| Week 2 | iPTMnet API 통합 (E3-substrate 조회) | ubinet_client.py (신규) |
| Week 3 | E3 Module Analysis 프로토타입 | e3_module_analysis.py (신규) |
| Week 4 | UbiNet/E3Atlas 통합 + 통합 테스트 | unified_receptor_resolver.py (신규) |

---

## 성공 지표

| 지표 | 현재 | 목표 |
|------|------|------|
| 동일 order 반복 호출 시 receptor 일치율 | ~40-60% | **100%** (캐싱) |
| Ubiquitylation order의 receptor 추론 성공률 | ~30-50% | **>80%** |
| Phosphorylation order의 receptor 추론 성공률 | ~70-85% | **>90%** |
| Source B (DB 기반) 커버리지 | ~40% (Reactome only) | **>70%** (Reactome + E3 DB + UbiNet) |
