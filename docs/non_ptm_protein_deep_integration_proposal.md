# Non-PTM Protein 심층 활용 전략 제안서

## 현재 상태 분석 (As-Is)

### 현재 Non-PTM Protein 데이터 활용 현황

| 모듈 | 활용 방식 | 활용 수준 |
|------|-----------|-----------|
| `unified_enricher.py` | PTM 없는 단백질의 Protein_Log2FC 값 보존 | 데이터 수집만 |
| `network_node.py` | STRING/BioGRID edge로 연결된 Non-PTM 노드 표시 (protein_log2fc 포함) | 네트워크 시각화 |
| `temporal_comovement_node.py` | PTM cluster와의 correlation, time-lag 계산, mechanism_hint 추론 | **가장 적극적** |
| `temporal_analysis.py` | Non-PTM effector temporal dynamics 테이블 (LLM context) | 패턴 분류 + 테이블 |
| `writer_node.py` | `aux_nonptm_temporal` → supplement_blocks Priority 1 | LLM 참조 자료 |
| `drug_repositioning.py` | Non-PTM 노드 중 known kinase 식별 → drug target 연결 | 제한적 |
| `SignalPropagationTimeline.tsx` | Effector response pattern 시각화 | 프론트엔드 표시 |

### 현재의 한계점

1. **"Validation evidence" 수준에 머물러 있음** — Non-PTM 단백질은 PTM 결과를 "확인"하는 보조 역할만 수행
2. **독립적 분석 부재** — Non-PTM 단백질 자체의 functional enrichment, pathway 분석이 없음
3. **단백질 복합체 정보 미활용** — 같은 complex 내 단백질들의 coordinated change가 기전 추론에 핵심적
4. **Transcription factor activity 미추론** — Non-PTM 단백질 변화로부터 TF activity를 역추론 가능
5. **Stoichiometry 변화 미분석** — PTM protein vs Non-PTM protein 비율 변화가 complex assembly/disassembly 시사
6. **Subcellular compartment-level 분석 부재** — 같은 구획 내 단백질들의 coordinated change 미활용

---

## 제안 전략 (To-Be)

### Strategy 1: Non-PTM Functional Enrichment Module (신규)

**개념**: Non-PTM 단백질 중 significantly changed된 것들에 대해 독립적 GO/KEGG enrichment 수행

**구현 위치**: `workers/report_generation/core/nodes/` 에 새 노드 또는 `temporal_analysis.py` 확장

```
Input: Non-PTM proteins with |Log2FC| > threshold (각 timepoint별)
Process:
  1. Up-regulated non-PTM set → GO Biological Process enrichment
  2. Down-regulated non-PTM set → GO Biological Process enrichment
  3. Timepoint별 enriched term 변화 추적 (어떤 기능이 언제 활성화/억제되는지)
Output: "Non-PTM Functional Landscape" context → LLM에 주입
```

**생물학적 의미**: 
- PTM 변화가 downstream에서 어떤 기능적 결과를 초래하는지 직접 보여줌
- 예: "5min에 kinase PTM 활성화 → 15min에 cytoskeletal protein abundance 증가 → cell migration 관련"

---

### Strategy 2: Protein Complex Stoichiometry Analysis (신규)

**개념**: CORUM/ComplexPortal DB 기반으로 같은 complex 내 단백질들의 coordinated abundance change 분석

```
Input: All protein Log2FC values (PTM + Non-PTM)
Reference DB: CORUM complex membership
Process:
  1. 각 complex의 subunit들의 Log2FC 패턴 비교
  2. Coordinated increase → complex assembly 시사
  3. Coordinated decrease → complex disassembly/degradation 시사
  4. Divergent change → subunit exchange/remodeling 시사
  5. PTM subunit만 변화 + Non-PTM subunit 불변 → PTM이 complex 내 regulation
Output: "Complex Dynamics" context → LLM에 주입
```

**생물학적 의미**:
- 단백질 복합체의 assembly/disassembly dynamics를 시간에 따라 추적
- PTM이 complex 형성을 촉진/억제하는지 직접적 증거 제공
- 예: "MAPK complex의 모든 subunit이 30min에 동시 증가 → complex stabilization by upstream phosphorylation"

---

### Strategy 3: Transcription Factor Activity Inference (신규)

**개념**: Non-PTM 단백질 변화 패턴으로부터 upstream TF activity를 역추론

```
Input: Delayed non-PTM protein changes (>30min time-lag)
Reference DB: TRRUST, DoRothEA (TF-target relationships)
Process:
  1. Delayed responder genes의 known TF regulators 조회
  2. 같은 TF의 target들이 coordinated change → TF activation 추론
  3. TF 자체의 PTM 상태와 cross-reference
     (예: STAT3 S727 phosphorylation ↑ at 5min → STAT3 target genes ↑ at 60min)
Output: "Inferred TF Activity" context → LLM에 주입
```

**생물학적 의미**:
- PTM → TF activation → gene expression → protein abundance 전체 cascade 추적
- 현재 time-lag "transcriptional_coregulation" hint를 구체적 TF로 resolve
- 예: "STAT3(S727) phosphorylation at 5min → 12 STAT3 target proteins increased at 60min"

---

### Strategy 4: Pathway Flux Estimation (기존 확장)

**개념**: Non-PTM 단백질의 temporal abundance를 pathway 내 위치와 결합하여 signal flux 방향 추정

```
Input: KEGG pathway membership + protein temporal profiles
Process:
  1. Pathway 내 단백질들을 upstream→downstream 순서로 정렬
  2. 각 단백질의 response onset time 계산
  3. Onset time이 pathway 순서와 일치하면 → forward signal propagation 확인
  4. 역순이면 → feedback loop 증거
  5. PTM 변화 onset vs Non-PTM abundance onset 비교 → signal relay speed 추정
Output: "Pathway Signal Flow" context → LLM에 주입
```

**생물학적 의미**:
- 단순 time-lag를 넘어서 pathway topology 위에서의 signal flow 시각화
- 어느 pathway가 active하고 어느 방향으로 signal이 흐르는지 정량적 추정

---

### Strategy 5: Degradation/Stabilization Signature Detection (신규)

**개념**: Non-PTM 단백질의 급격한 감소가 ubiquitin-proteasome 또는 autophagy 경로 활성화를 시사

```
Input: Non-PTM proteins with strong decrease (Log2FC < -1)
Process:
  1. 급격히 감소하는 단백질들의 known degradation motif (degron) 확인
  2. 동시에 E3 ligase PTM 활성화 여부 확인
  3. Proteasome/autophagy component의 abundance 변화 확인
  4. Temporal correlation: E3 ligase PTM ↑ → target protein ↓ (time-lag)
Output: "Active Degradation Events" context → LLM에 주입
```

**생물학적 의미**:
- Ubiquitylation 분석 시 특히 강력 — PTM(Ub)과 substrate degradation의 직접적 인과관계
- Phosphorylation 분석에서도 유용 — phospho-degron mediated degradation 탐지

---

### Strategy 6: Subcellular Compartment Dynamics (신규)

**개념**: UniProt localization 정보 + protein abundance change → compartment-level signaling event 추론

```
Input: All protein changes + UniProt subcellular localization
Process:
  1. 각 compartment (nucleus, cytoplasm, membrane, mitochondria 등)별 protein change 집계
  2. Compartment-specific enrichment score 계산
  3. Temporal shift: 어떤 compartment에서 먼저 변화가 시작되는지
  4. PTM proteins vs Non-PTM proteins의 compartment distribution 비교
Output: "Subcellular Signal Topology" context → LLM에 주입
```

**생물학적 의미**:
- "Membrane에서 시작 → Cytoplasm 경유 → Nucleus 도달" 같은 signal flow 추적
- Nuclear translocation event 간접 추론 가능

---

## 구현 우선순위 제안

| 순위 | 전략 | 난이도 | 영향력 | 이유 |
|------|------|--------|--------|------|
| 1 | Strategy 1 (Functional Enrichment) | 낮음 | 높음 | 기존 MCP STRING enrichment API 활용 가능, 즉시 LLM context 강화 |
| 2 | Strategy 3 (TF Activity Inference) | 중간 | 매우 높음 | PTM→TF→target 전체 cascade 완성, 기전 설명력 극대화 |
| 3 | Strategy 2 (Complex Stoichiometry) | 중간 | 높음 | CORUM DB 연동 필요하지만 complex dynamics는 매우 설득력 있는 증거 |
| 4 | Strategy 5 (Degradation Signature) | 낮음 | 중간~높음 | Ub 분석에서 특히 강력, 기존 데이터만으로 가능 |
| 5 | Strategy 4 (Pathway Flux) | 높음 | 높음 | KEGG topology 파싱 필요, 하지만 완성되면 매우 강력 |
| 6 | Strategy 6 (Subcellular Dynamics) | 낮음 | 중간 | UniProt localization 이미 수집 중, 집계 로직만 추가 |

---

## LLM Report에의 통합 방안

### 현재 구조
```
supplement_blocks (Priority 1):
  - temporal_coordination (PTM co-movement clusters)
  - temporal_kinase (kinase activity heatmap)
  - receptor_ctx (receptor signaling)
  - ip_overlay (IP physical interaction)
  - nonptm_temporal (effector dynamics — 현재)
```

### 제안 구조
```
supplement_blocks (Priority 1):
  - temporal_coordination
  - temporal_kinase
  - receptor_ctx
  - ip_overlay
  - nonptm_temporal (기존 유지)
  - nonptm_functional_landscape (Strategy 1) ← NEW
  - tf_activity_inference (Strategy 3) ← NEW
  - complex_dynamics (Strategy 2) ← NEW
  - degradation_signatures (Strategy 5) ← NEW
```

### Discussion 프롬프트 확장 (제안)

현재 Discussion Topic 5가 "Non-PTM Validation Evidence (inline)"인데, 이를 다음과 같이 확장:

```
5. **Non-PTM Mechanistic Evidence** (UPGRADED from validation to mechanistic):
   - Functional enrichment of responsive Non-PTM proteins reveals downstream 
     biological consequences of PTM signaling
   - Protein complex stoichiometry changes indicate PTM-driven complex 
     assembly/disassembly events
   - Inferred TF activity connects PTM events to transcriptional outcomes
   - Degradation signatures link ubiquitylation/phospho-degron PTMs to 
     substrate turnover
   - Integrate these as MECHANISTIC EVIDENCE, not just validation
```

---

## 핵심 철학 변화

> **Before**: Non-PTM protein = PTM 결과의 "확인자" (concordant downstream evidence)
> 
> **After**: Non-PTM protein = 세포 신호전달의 "기능적 결과물" (functional readout of signaling)

이 관점 전환으로:
- PTM 변화가 실제로 세포에 어떤 기능적 영향을 미치는지 설명 가능
- "이 kinase가 활성화되면 → 이 complex가 형성되고 → 이 TF가 활성화되어 → 이 기능이 수행된다" 전체 narrative 완성
- 단순 correlation에서 **mechanistic causality** 추론으로 격상

---

## 다음 단계

어떤 전략부터 구현할지 결정해 주시면, 해당 모듈의 상세 설계 및 코드 작성을 진행하겠습니다.
