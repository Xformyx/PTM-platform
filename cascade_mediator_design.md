# Cascade Mediator Agent — Architecture Specification v7.0

## Problem Statement

현재 파이프라인은 cascade diagram을 `network_analysis` 노드에서 **본문 작성 전에** 생성하고,
`figure_context.py`를 통해 LLM에게 "이 pathway를 반드시 언급하라"고 강제합니다.
이는 다이어그램이 본문의 맥락과 무관하게 독립적으로 생성되어 텍스트-다이어그램 불일치를 초래합니다.

## Solution: Content-Driven Cascade Diagram

LLM이 본문을 먼저 작성하고, **Mediator Agent**가 본문에서 실제로 논의된 pathway를 추출하여
그에 맞는 cascade diagram을 생성합니다.

## New Pipeline Flow

```
load_context → generate_questions → research → hypothesize → validate_hypotheses
  → network_analysis (Figure 1 + Cytoscape only, pathway_candidates to state)
  → write_sections (LLM freely writes, sees pathway_candidates as reference)
  → cascade_mediator (extracts pathways from text → generates matching diagrams)
  → generate_qa_report → drug_repositioning → format_citations → edit_report
```

## Key Changes

### 1. network_node.py Changes
- **REMOVE**: cascade diagram generation (lines 2097-2161)
- **ADD**: Export `pathway_candidates` to state — all scored pathways with their genes, scores, compartments
- **KEEP**: Figure 1 (pathway distribution graph) + Cytoscape network images

`pathway_candidates` structure:
```python
{
    "candidates": [
        {
            "name": "MAPK signaling pathway",
            "composite_score": 0.85,
            "genes": ["EGFR", "KRAS", "RAF1", "MAP2K1", "MAPK1"],
            "compartments": ["membrane", "cytoplasm", "nucleus"],
            "fc_score": 0.9,
            "template_match": "mapk",
            "gene_count": 7,
        },
        ...
    ],
    "gene_data": {  # All gene-level data needed for diagram generation
        "EGFR": {
            "gene": "EGFR", "site": "Y1068", "ptm_log2fc": 3.2,
            "protein_log2fc": 2.1, "compartment": "membrane",
            "node_type": "PTM", "pathways": ["MAPK", "PI3K-Akt"],
        },
        ...
    },
    "network_edges": [...],  # For connectivity arrows
}
```

### 2. figure_context.py Changes
- **REMOVE**: `cascade_pathway_names` forced injection into LLM prompts
- **REMOVE**: "You MUST discuss these specific pathways" instructions
- **KEEP**: Figure 1 + Cytoscape figure context (LLM still needs to reference these)
- **ADD**: Provide `pathway_candidates` as informational context (not mandatory)
  - "The following canonical pathways were identified in the data: [list]"
  - LLM can choose which to discuss based on biological relevance

### 3. NEW: cascade_mediator_node.py
Position: After `write_sections`, before `generate_qa_report`

#### Phase 1: Pathway Extraction from Text (Deterministic, no LLM)
```python
def extract_discussed_pathways(sections: dict, pathway_candidates: dict) -> list:
    """
    Extract pathways that the LLM actually discussed in Results/Discussion.
    
    Strategy (deterministic, no LLM needed):
    1. Build a pathway name → candidate mapping from pathway_candidates
    2. Scan Results + Discussion text for pathway name mentions
    3. Also scan for key gene names that belong to specific pathways
    4. Rank matched pathways by:
       a. Number of text mentions (pathway name + gene names)
       b. Original composite score from pathway_candidates
       c. Whether discussed in both Results AND Discussion
    5. Select top N pathways (configurable, default 5)
    """
```

Matching rules:
- Exact pathway name match: "MAPK signaling pathway" → direct match
- Partial match: "MAPK signaling", "MAPK pathway", "MAPK cascade" → fuzzy match
- Gene cluster match: If ≥3 genes from a pathway are mentioned together → pathway match
- Keyword match: "PI3K/Akt", "mTOR", "JAK-STAT" → known abbreviation mapping

#### Phase 2: Diagram Generation
```python
def generate_content_aligned_cascade(
    matched_pathways: list,
    pathway_candidates: dict,
    enriched_data: list,
    network_data: dict,
    output_dir: str,
    condition: str = None,
) -> dict:
    """
    Generate cascade diagram using only pathways that were discussed in text.
    
    Reuses signaling_cascade.py's rendering engine but with:
    - Pathways selected by mediator (not by scoring algorithm)
    - Subtitle: "Key Signaling Pathways Discussed in Analysis"
    """
```

#### Phase 3: State Update
```python
def run_cascade_mediator(state: dict) -> dict:
    """
    LangGraph node: Extract pathways from text → generate diagrams.
    
    Reads: sections (Results, Discussion), pathway_candidates, enriched_data, network_data
    Writes: cascade_diagrams (dict of condition → path), cascade_pathway_names
    """
```

### 4. graph.py Changes
- Add `cascade_mediator` node
- New edge: `write_sections → cascade_mediator → generate_qa_report`
- Add `pathway_candidates` and `cascade_diagrams` to ReportState

### 5. format_citations Changes
- Read `cascade_diagrams` from state (instead of from network_analysis)
- Insert cascade diagrams in Network Visualization section (same position)
- Figure numbering: Figure 1 (pathway graph) → Figure 2+ (cascade) → Figure N+ (Cytoscape)

### 6. generate_network_figure_section Changes
- Accept optional `cascade_diagrams` parameter (from mediator, not from network_analysis)
- If cascade_diagrams not provided, skip cascade section (backward compatible)

## Data Flow

```
network_analysis:
  OUTPUT: pathway_candidates → state["pathway_candidates"]
  OUTPUT: network_analysis (without cascade) → state["network_analysis"]

write_sections:
  INPUT: pathway_candidates (informational, not mandatory)
  OUTPUT: sections (Results, Discussion with naturally chosen pathways)

cascade_mediator:
  INPUT: sections, pathway_candidates, enriched_data, network_data, output_dir
  OUTPUT: cascade_diagrams, cascade_pathway_names → state

format_citations:
  INPUT: sections, network_analysis, cascade_diagrams
  OUTPUT: final_report (with cascade diagrams inserted)
```

## Advantages
1. **Natural alignment**: Diagram shows exactly what the text discusses
2. **LLM autonomy**: LLM chooses pathways based on biological relevance, not forced list
3. **No hallucination risk**: Mediator uses deterministic text matching, not LLM
4. **Backward compatible**: If mediator finds no pathways, no cascade diagram (graceful)
5. **Configurable**: top_n_pathways in mediator is configurable via report_config
