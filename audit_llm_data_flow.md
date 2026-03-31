# LLM Report Generation - Data Flow Audit

## Current Data Flowing to LLM (via writer_node.py _build_section_prompt)

### Per-Section Prompt Inputs:
1. **experimental_context** (dict): tissue, treatment, organism, timepoints, biological_question, special_conditions, ptm_type
2. **parsed_ptms** (list): Top 50 PTMs with gene, position, Log2FC, rag_enrichment data
3. **research_results** (list): Per-question stats (relevant PTM count, up/downregulated, activated PTMs, enriched pathways)
4. **hypotheses / validated_hypotheses** (list): Generated and validated hypotheses
5. **network_analysis** (dict): Cytoscape network legends, fig1_pathway_names (KEGG+Reactome+STRING)
6. **comprehensive_summary** (str): MD report summary (up to 12000 chars)
7. **ChromaDB RAG results** (list): Vector-searched literature excerpts
8. **PubMed references** (list): From enriched PTM data
9. **comovement_llm_context** (str): Temporal co-movement cluster analysis (injected into results/discussion)
10. **temporal_kinase_cascade_llm_context** (str): Kinase cascade across timepoints (injected into results/discussion)
11. **figure_context** (str): Figure descriptions for LLM to reference (Figure 1, 2, etc.)
12. **prev_sections** (dict): Previously written sections (for abstract/conclusion)

### Via initial_state (tasks.py):
- **frontend_kinase_analysis** (dict): Pre-computed kinase module results from DB (kinase_analysis_data)

## Data NOT Currently Flowing to LLM:

### 1. **Inferred Upstream Receptors** ❌ NOT PASSED
- Source: orders.py vector-plot-data endpoint
- Contains: receptor names, classes, downstream PTM counts, via_kinases, pathways, source (R/T/U)
- NOT in ReportState, NOT in initial_state, NOT in any prompt
- **Impact**: LLM cannot discuss receptor-level signaling (e.g., "Irisin activates αV/β5 Integrin → downstream kinases → observed PTMs")

### 2. **Treatment Validation / Typo Detection** ❌ NOT PASSED
- Source: orders.py validate-treatment endpoint
- Contains: fuzzy match results, suggested corrections
- Not relevant for report (UI-only feature)

### 3. **Signal Propagation Data** ⚠️ PARTIALLY PASSED
- Source: order.signal_propagation_data (DB field)
- build_signal_propagation_json() is called in writer_node for Results section
- But only injected as auxiliary block, not prominently featured

### 4. **Cross-Talk Data** ✅ PASSED (when analysis_mode == "cross_talk")
- Source: order.cross_talk_data
- Handled by crosstalk_node.py

### 5. **Kinase Module Analysis (Global)** ⚠️ PARTIALLY PASSED
- Source: frontend_kinase_analysis in initial_state
- Used by kinase_annotation_node.py
- But the detailed kinase→PTM mapping and source attribution (iPTMnet, UniProt, KEA3) is not in LLM prompts

### 6. **Ligand-Receptor Database Mappings** ❌ NOT PASSED
- Source: ligand_receptor_db.py (101 ligands, 119 receptors, downstream kinase mappings)
- Contains: known ligand→receptor→kinase→PTM signaling chains
- NOT available to LLM at all
- **Impact**: LLM cannot construct complete signaling narratives from ligand to PTM

### 7. **iPTMnet / UniProt Direct API Results** ❌ NOT PASSED (as structured data)
- Source: kinase_module.py Sources 7-8
- Real-time kinase lookup results
- Only indirectly available through kinase_analysis_data summary

## Priority Recommendations:

### HIGH PRIORITY - Inferred Receptors → LLM
The receptor inference data should be passed to LLM for:
- Introduction: "Irisin is known to bind αV/β5 Integrin receptor..."
- Results: "The inferred upstream receptors include αV/β5 Integrin (Source T), which activates CDK5 and MAPK1..."
- Discussion: "The receptor-kinase-PTM signaling chain from αV/β5 Integrin → CDK5 → downstream substrates..."

### MEDIUM PRIORITY - Kinase Module Details → LLM
More detailed kinase source attribution would help LLM write more specific mechanistic narratives.

### LOW PRIORITY - Ligand-Receptor DB Context
General DB context is less critical since specific matches are already in receptor inference.
