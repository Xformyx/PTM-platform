# Design: Substrate Temporal Clustering for Kinase Activity Score

## Problem

Current implementation averages Log2FC across ALL substrates of a kinase per condition.
When substrates have opposing temporal patterns (early-up vs late-up), they cancel each other,
producing near-zero scores and low coherence (0.05-0.08) across all kinases.

## Solution: Minimal-Change Cluster-Aware Scoring

### Core Idea
1. **Cluster substrates by temporal trajectory** (K-Means on per-substrate condition vectors)
2. **Score each cluster independently** per condition (no cross-cluster averaging)
3. **Report the dominant cluster** as the kinase's primary activity signal
4. **Expose cluster metadata** so frontend can show sub-patterns

### Architecture (Minimal Changes)

#### Where: `_compute_kinase_activity_heatmap()` in `tasks.py` (worker path)
#### Where: `kinase_activity_heatmap()` in `orders.py` (API path)

### Algorithm

```
For each kinase module:
  1. Build substrate trajectory matrix: rows=substrates, cols=conditions
     - Each row = [Log2FC_6h, Log2FC_12h, Log2FC_24h, Log2FC_48h]
     - Filter: only substrates with at least 1 non-zero value

  2. Determine optimal K (2-4 clusters):
     - If n_substrates < 10: skip clustering, use all as single cluster
     - If n_substrates >= 10: K = min(4, n_substrates // 10)
     - Use K-Means with L2-normalized trajectories (shape-based, not magnitude)

  3. For each cluster:
     - Compute per-condition weighted score (existing _get_weight logic)
     - Compute intra-cluster coherence (existing Pearson mean logic)
     - Compute cluster size and direction

  4. Select dominant cluster:
     - Dominant = cluster with highest (coherence * sqrt(size) * max(|score|))
     - This balances: pattern consistency, statistical power, signal strength

  5. Output (backward-compatible):
     - scores: dominant cluster's per-condition scores (replaces naive average)
     - substrate_count: dominant cluster size (replaces total member count)
     - coherence: dominant cluster's coherence (replaces whole-kinase coherence)
     - peak_score/peak_condition/direction: from dominant cluster
     
     NEW fields (additive, won't break frontend):
     - total_substrates: original total member count
     - n_clusters: number of clusters found
     - cluster_details: [{cluster_id, size, scores, coherence, direction, is_dominant}]
```

### Key Design Decisions

1. **L2-normalize before clustering**: We cluster by SHAPE (trajectory pattern),
   not magnitude. A substrate going [+0.5, +1.0, +0.5, 0] and one going
   [+2, +4, +2, 0] should be in the same cluster (both "early peak" pattern).

2. **Dominant cluster selection**: Not just "biggest cluster" but a composite
   score that rewards coherent, large, strong-signal clusters.

3. **Backward compatibility**: Existing frontend fields (scores, substrate_count,
   coherence, direction) are preserved with better values. New fields are additive.

4. **Fallback**: If clustering fails or n < 10, falls back to current behavior.

### Changes Required

#### tasks.py (`_compute_kinase_activity_heatmap`)
- Add `_cluster_substrates(members, ptm_values, conditions)` helper
- Replace naive scoring loop (lines 454-486) with cluster-aware scoring
- Replace naive coherence (lines 488-517) with dominant-cluster coherence
- Add cluster_details to output

#### orders.py (`kinase_activity_heatmap`)
- Add same `_cluster_substrates()` helper
- Replace Co-activation Sum loop (lines 6498-6624) with cluster-aware version
- Keep existing up/down split but compute per dominant cluster only

#### Frontend (KinaseModuleAnalysis.tsx)
- Update types: add total_substrates, n_clusters, cluster_details
- Show "#Sub" as dominant cluster size, with tooltip showing total
- Optionally show cluster breakdown in expanded view
```
