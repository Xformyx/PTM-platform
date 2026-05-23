# LLM Context 보강 분석

## 현재 LLM에 전달되는 정보 (kinase_annotation_node.py)
- `_build_frontend_kinase_llm_context()` (line 1436):
  - A. Analysis Summary (total modules, confirmed/inferred counts)
  - B. Top 15 Kinase Modules (kinase name, sources, substrate list)
  - C. Temporal Kinase Activation Order (timepoint → active kinases)
  - D. Kinase Transition Between Timepoints (persistent/new/lost)
  - Instructions for LLM

## 현재 LLM에 전달되지 않는 정보 (추가 필요)
1. **CW Groups (Co-Wave Kinase Groups)** — `kinase_activity_heatmap.cowave_groups`
   - group_id, kinases, size, mean_correlation, dominant_peak
   - 의미: temporal substrate activity 상관관계 r≥0.7 기반 그룹핑
   
2. **Kinase Activity Scores per Condition** — `kinase_activity_heatmap.kinase_scores`
   - kinase, scores (per condition), substrate_count, confidence, peak_condition, peak_score
   - coherence (intra-group substrate correlation)
   - direction (activation/inactivation/neutral)
   - cowave_group assignment

3. **Peak Synchronization** — `kinase_activity_heatmap.peak_sync`
   - Conditions where 3+ kinases peak simultaneously

4. **Signal Propagation Data** — `signal_propagation_data`
   - Already in state but not used by any node

## 구현 계획
- `_build_frontend_kinase_llm_context()`에 새 섹션 추가:
  - E. Co-Wave Kinase Groups (CW Groups)
  - F. Kinase Activity Scores (per-condition weighted mean Log2FC)
  - G. Peak Synchronization Events
- kinase_annotation_node에서 `kinase_activity_heatmap` state를 읽어서 context에 추가
