export interface DualPTMProtein {
  gene: string;
  primary_sites: string[];
  secondary_sites: string[];
  primary_ptm_type: string;
  secondary_ptm_type: string;
  shared_timepoints: string[];
  primary_timepoints: string[];
  secondary_timepoints: string[];
  concordant_ratio: number;
  pattern: 'concordant' | 'discordant' | 'mixed';
  temporal_comparison: Record<string, {
    primary_state: string;
    secondary_state: string;
    primary_ptm_log2fc: number;
    secondary_ptm_log2fc: number;
    concordant: boolean;
  }>;
}

// ============================================================================
// Clustering Sort Utilities
// ============================================================================

/**
 * Compute a feature vector for each protein based on its temporal concordance pattern.
 * Each timepoint gets a value: +1 (concordant), -1 (discordant), 0 (no data).
 */
function buildFeatureVector(protein: DualPTMProtein, timepoints: string[]): number[] {
  return timepoints.map(tp => {
    const comp = protein.temporal_comparison[tp];
    if (!comp) return 0;
    return comp.concordant ? 1 : -1;
  });
}

/**
 * Euclidean distance between two feature vectors.
 */
function euclideanDistance(a: number[], b: number[]): number {
  let sum = 0;
  for (let i = 0; i < a.length; i++) {
    const diff = (a[i] || 0) - (b[i] || 0);
    sum += diff * diff;
  }
  return Math.sqrt(sum);
}

/**
 * Simple agglomerative hierarchical clustering (single-linkage).
 * Returns an ordered list of indices that groups similar proteins together.
 *
 * Algorithm:
 * 1. Start with each protein as its own cluster.
 * 2. Repeatedly merge the two closest clusters.
 * 3. The merge order defines a dendrogram traversal → leaf order.
 */
function hierarchicalClusterOrder(proteins: DualPTMProtein[], timepoints: string[]): number[] {
  const n = proteins.length;
  if (n <= 1) return proteins.map((_, i) => i);

  // Build feature vectors
  const vectors = proteins.map(p => buildFeatureVector(p, timepoints));

  // Compute pairwise distance matrix (upper triangle)
  const dist: number[][] = Array.from({ length: n }, () => Array(n).fill(Infinity));
  for (let i = 0; i < n; i++) {
    dist[i][i] = 0;
    for (let j = i + 1; j < n; j++) {
      const d = euclideanDistance(vectors[i], vectors[j]);
      dist[i][j] = d;
      dist[j][i] = d;
    }
  }

  // Each cluster is represented as an ordered list of original indices
  type Cluster = number[];
  let clusters: Cluster[] = proteins.map((_, i) => [i]);

  // Merge until one cluster remains
  while (clusters.length > 1) {
    // Find the two closest clusters (single-linkage: min distance between any pair)
    let minDist = Infinity;
    let mergeA = 0;
    let mergeB = 1;

    for (let i = 0; i < clusters.length; i++) {
      for (let j = i + 1; j < clusters.length; j++) {
        // Single-linkage: minimum distance between any member of cluster i and cluster j
        let clusterDist = Infinity;
        for (const a of clusters[i]) {
          for (const b of clusters[j]) {
            if (dist[a][b] < clusterDist) {
              clusterDist = dist[a][b];
            }
          }
        }
        if (clusterDist < minDist) {
          minDist = clusterDist;
          mergeA = i;
          mergeB = j;
        }
      }
    }

    // Merge: append cluster B to cluster A
    const merged = [...clusters[mergeA], ...clusters[mergeB]];
    clusters = clusters.filter((_, idx) => idx !== mergeA && idx !== mergeB);
    clusters.push(merged);
  }

  return clusters[0];
}

/**
 * Group-aware clustering: first group by pattern (concordant → mixed → discordant),
 * then apply hierarchical clustering within each group.
 */
export function clusterSortProteins(proteins: DualPTMProtein[], timepoints: string[]): {
  sorted: DualPTMProtein[];
  groupBoundaries: { label: string; startIndex: number; count: number; color: string }[];
} {
  const patternOrder: Array<{ key: 'concordant' | 'mixed' | 'discordant'; label: string; color: string }> = [
    { key: 'concordant', label: 'Concordant', color: 'emerald' },
    { key: 'mixed', label: 'Mixed', color: 'slate' },
    { key: 'discordant', label: 'Discordant', color: 'rose' },
  ];

  const groups: Record<string, DualPTMProtein[]> = {
    concordant: [],
    mixed: [],
    discordant: [],
  };

  proteins.forEach(p => {
    groups[p.pattern]?.push(p);
  });

  const sorted: DualPTMProtein[] = [];
  const groupBoundaries: { label: string; startIndex: number; count: number; color: string }[] = [];

  for (const { key, label, color } of patternOrder) {
    const group = groups[key];
    if (group.length === 0) continue;

    const startIndex = sorted.length;

    // Apply hierarchical clustering within this group
    const clusterOrder = hierarchicalClusterOrder(group, timepoints);
    const clusteredGroup = clusterOrder.map(i => group[i]);
    sorted.push(...clusteredGroup);

    groupBoundaries.push({ label, startIndex, count: group.length, color });
  }

  return { sorted, groupBoundaries };
}
