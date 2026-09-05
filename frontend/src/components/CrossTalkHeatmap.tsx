import { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface DualPTMProtein {
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

interface CrossTalkHeatmapProps {
  dualPTMProteins: DualPTMProtein[];
  primaryPtmType: string;
  secondaryPtmType: string;
}

type SortMode = 'cluster' | 'concordant_ratio' | 'gene' | 'pattern';
type ViewMode = 'concordance' | 'primary_log2fc' | 'secondary_log2fc';

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
function clusterSortProteins(proteins: DualPTMProtein[], timepoints: string[]): {
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

// ============================================================================
// Component
// ============================================================================

export default function CrossTalkHeatmap({
  dualPTMProteins,
  primaryPtmType,
  secondaryPtmType,
}: CrossTalkHeatmapProps) {
  const [sortMode, setSortMode] = useState<SortMode>('cluster');
  const [viewMode, setViewMode] = useState<ViewMode>('concordance');
  const [maxProteins, setMaxProteins] = useState(30);

  const pType = primaryPtmType?.charAt(0).toUpperCase() + primaryPtmType?.slice(1) || 'Primary';
  const sType = secondaryPtmType?.charAt(0).toUpperCase() + secondaryPtmType?.slice(1) || 'Secondary';

  // Collect all unique timepoints
  const allTimepoints = useMemo(() => {
    const tps = new Set<string>();
    dualPTMProteins.forEach(p => {
      Object.keys(p.temporal_comparison).forEach(tp => tps.add(tp));
    });
    return Array.from(tps).sort((a, b) => {
      const numA = parseFloat(a.replace(/[^\d.]/g, ''));
      const numB = parseFloat(b.replace(/[^\d.]/g, ''));
      if (!isNaN(numA) && !isNaN(numB)) return numA - numB;
      return a.localeCompare(b);
    });
  }, [dualPTMProteins]);

  // Sort proteins with clustering support
  const { sortedProteins, groupBoundaries } = useMemo(() => {
    if (sortMode === 'cluster') {
      const { sorted, groupBoundaries } = clusterSortProteins(dualPTMProteins, allTimepoints);
      return {
        sortedProteins: sorted.slice(0, maxProteins),
        groupBoundaries: groupBoundaries.filter(g => g.startIndex < maxProteins).map(g => ({
          ...g,
          count: Math.min(g.count, maxProteins - g.startIndex),
        })),
      };
    }

    const sorted = [...dualPTMProteins];
    switch (sortMode) {
      case 'concordant_ratio':
        sorted.sort((a, b) => b.concordant_ratio - a.concordant_ratio);
        break;
      case 'gene':
        sorted.sort((a, b) => a.gene.localeCompare(b.gene));
        break;
      case 'pattern':
        sorted.sort((a, b) => {
          const order = { concordant: 0, mixed: 1, discordant: 2 };
          return order[a.pattern] - order[b.pattern];
        });
        break;
    }
    return { sortedProteins: sorted.slice(0, maxProteins), groupBoundaries: [] };
  }, [dualPTMProteins, sortMode, maxProteins, allTimepoints]);

  // Get cell color based on view mode
  const getCellColor = (protein: DualPTMProtein, tp: string): string => {
    const comp = protein.temporal_comparison[tp];
    if (!comp) return 'bg-gray-100';

    switch (viewMode) {
      case 'concordance':
        return comp.concordant ? 'bg-emerald-400' : 'bg-rose-400';
      case 'primary_log2fc': {
        const v = comp.primary_ptm_log2fc;
        if (v > 1.5) return 'bg-red-600 text-white';
        if (v > 0.5) return 'bg-red-400 text-white';
        if (v > 0) return 'bg-red-200';
        if (v > -0.5) return 'bg-blue-200';
        if (v > -1.5) return 'bg-blue-400 text-white';
        return 'bg-blue-600 text-white';
      }
      case 'secondary_log2fc': {
        const v = comp.secondary_ptm_log2fc;
        if (v > 1.5) return 'bg-red-600 text-white';
        if (v > 0.5) return 'bg-red-400 text-white';
        if (v > 0) return 'bg-red-200';
        if (v > -0.5) return 'bg-blue-200';
        if (v > -1.5) return 'bg-blue-400 text-white';
        return 'bg-blue-600 text-white';
      }
      default:
        return 'bg-gray-100';
    }
  };

  const getCellValue = (protein: DualPTMProtein, tp: string): string => {
    const comp = protein.temporal_comparison[tp];
    if (!comp) return '-';

    switch (viewMode) {
      case 'concordance':
        return comp.concordant ? 'C' : 'D';
      case 'primary_log2fc':
        return comp.primary_ptm_log2fc.toFixed(1);
      case 'secondary_log2fc':
        return comp.secondary_ptm_log2fc.toFixed(1);
      default:
        return '-';
    }
  };

  const [hoveredCell, setHoveredCell] = useState<{ gene: string; tp: string } | null>(null);

  const hoveredInfo = useMemo(() => {
    if (!hoveredCell) return null;
    const protein = sortedProteins.find(p => p.gene === hoveredCell.gene);
    if (!protein) return null;
    const comp = protein.temporal_comparison[hoveredCell.tp];
    if (!comp) return null;
    return { protein, comp, tp: hoveredCell.tp };
  }, [hoveredCell, sortedProteins]);

  // Determine if a row is the first in a cluster group (for separator rendering)
  const isGroupStart = (rowIndex: number): { label: string; count: number; color: string } | null => {
    if (sortMode !== 'cluster') return null;
    const boundary = groupBoundaries.find(g => g.startIndex === rowIndex);
    return boundary || null;
  };

  if (dualPTMProteins.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          Dual-PTM 단백질이 없어 Heatmap을 생성할 수 없습니다.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <CardTitle className="text-lg">Cross-Talk Temporal Heatmap</CardTitle>
            <CardDescription>
              시간대별 {pType} × {sType} Concordant/Discordant 패턴
            </CardDescription>
          </div>
          <div className="flex gap-2 flex-wrap">
            <Select value={viewMode} onValueChange={(v) => setViewMode(v as ViewMode)}>
              <SelectTrigger className="w-[180px] h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="concordance">Concordance Change</SelectItem>
                <SelectItem value="primary_log2fc">{pType} Log2FC</SelectItem>
                <SelectItem value="secondary_log2fc">{sType} Log2FC</SelectItem>
              </SelectContent>
            </Select>
            <Select value={sortMode} onValueChange={(v) => setSortMode(v as SortMode)}>
              <SelectTrigger className="w-[200px] h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="cluster">Sort: Cluster (Group + Similarity)</SelectItem>
                <SelectItem value="concordant_ratio">Sort: Concordance Ratio</SelectItem>
                <SelectItem value="gene">Sort: Gene Name</SelectItem>
                <SelectItem value="pattern">Sort: Pattern Only</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Cluster mode info banner */}
        {sortMode === 'cluster' && groupBoundaries.length > 0 && (
          <div className="mt-3 flex items-center gap-3 flex-wrap text-xs">
            <span className="text-muted-foreground font-medium">Clusters:</span>
            {groupBoundaries.map(g => (
              <div key={g.label} className="flex items-center gap-1.5">
                <div className={`w-2.5 h-2.5 rounded-full ${
                  g.color === 'emerald' ? 'bg-emerald-500' :
                  g.color === 'rose' ? 'bg-rose-500' : 'bg-slate-400'
                }`} />
                <span className="font-medium">{g.label}</span>
                <span className="text-muted-foreground">({g.count})</span>
              </div>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="border-collapse text-xs">
            <thead>
              <tr>
                {sortMode === 'cluster' && groupBoundaries.length > 0 && (
                  <th className="w-1 p-0 border-b" />
                )}
                <th className="sticky left-0 bg-background z-10 text-left py-1.5 px-2 font-semibold border-b min-w-[80px]">
                  Gene
                </th>
                <th className="text-center py-1.5 px-1 font-semibold border-b min-w-[40px]">
                  Pattern
                </th>
                {allTimepoints.map(tp => (
                  <th key={tp} className="text-center py-1.5 px-1 font-medium border-b min-w-[48px]">
                    {tp}
                  </th>
                ))}
                <th className="text-center py-1.5 px-2 font-semibold border-b min-w-[50px]">
                  Ratio
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedProteins.map((protein, rowIndex) => {
                const groupStart = isGroupStart(rowIndex);

                return (
                  <tr key={protein.gene} className="hover:bg-muted/30 transition-colors">
                    {/* Cluster group color bar */}
                    {sortMode === 'cluster' && groupBoundaries.length > 0 && (
                      <td
                        className={`w-1 p-0 border-b ${
                          // Find which group this row belongs to
                          (() => {
                            const group = groupBoundaries.find(
                              g => rowIndex >= g.startIndex && rowIndex < g.startIndex + g.count
                            );
                            if (!group) return '';
                            return group.color === 'emerald' ? 'bg-emerald-500' :
                                   group.color === 'rose' ? 'bg-rose-500' : 'bg-slate-400';
                          })()
                        }`}
                        style={groupStart ? { borderTop: '2px solid var(--border)' } : undefined}
                      />
                    )}
                    <td
                      className={`sticky left-0 bg-background z-10 py-1 px-2 font-mono font-semibold border-b ${
                        groupStart ? 'border-t-2' : ''
                      }`}
                    >
                      {protein.gene}
                    </td>
                    <td className={`text-center py-1 px-1 border-b ${groupStart ? 'border-t-2' : ''}`}>
                      <Badge variant="outline" className={`text-[9px] px-1 py-0 ${
                        protein.pattern === 'concordant' ? 'border-emerald-300 text-emerald-700 bg-emerald-50' :
                        protein.pattern === 'discordant' ? 'border-rose-300 text-rose-700 bg-rose-50' :
                        'border-slate-300 text-slate-600 bg-slate-50'
                      }`}>
                        {protein.pattern === 'concordant' ? 'CON' : protein.pattern === 'discordant' ? 'DIS' : 'MIX'}
                      </Badge>
                    </td>
                    {allTimepoints.map(tp => {
                      const hasData = !!protein.temporal_comparison[tp];
                      return (
                        <td
                          key={tp}
                          className={`text-center py-1 px-1 border-b cursor-pointer transition-all ${
                            hasData ? getCellColor(protein, tp) : 'bg-gray-50'
                          } ${
                            hoveredCell?.gene === protein.gene && hoveredCell?.tp === tp ? 'ring-2 ring-primary ring-inset' : ''
                          } ${groupStart ? 'border-t-2' : ''}`}
                          onMouseEnter={() => setHoveredCell({ gene: protein.gene, tp })}
                          onMouseLeave={() => setHoveredCell(null)}
                        >
                          {hasData ? (
                            <span className="font-mono text-[10px]">{getCellValue(protein, tp)}</span>
                          ) : (
                            <span className="text-gray-300">-</span>
                          )}
                        </td>
                      );
                    })}
                    <td className={`text-center py-1 px-2 border-b font-mono text-[10px] ${groupStart ? 'border-t-2' : ''}`}>
                      {(protein.concordant_ratio * 100).toFixed(0)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Hover tooltip */}
        {hoveredInfo && (
          <div className="mt-3 p-3 bg-muted/50 rounded-lg border text-sm animate-in fade-in duration-150">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-bold">{hoveredInfo.protein.gene}</span>
              <span className="text-muted-foreground">@ {hoveredInfo.tp}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
              <div>
                <span className="text-muted-foreground">{pType}:</span>{' '}
                <span className={hoveredInfo.comp.primary_state === 'active' ? 'text-blue-600 font-medium' : 'text-purple-600 font-medium'}>
                  {hoveredInfo.comp.primary_state}
                </span>
                {' '}(Log2FC: <span className="font-mono">{hoveredInfo.comp.primary_ptm_log2fc.toFixed(2)}</span>)
              </div>
              <div>
                <span className="text-muted-foreground">{sType}:</span>{' '}
                <span className={hoveredInfo.comp.secondary_state === 'active' ? 'text-amber-600 font-medium' : 'text-purple-600 font-medium'}>
                  {hoveredInfo.comp.secondary_state}
                </span>
                {' '}(Log2FC: <span className="font-mono">{hoveredInfo.comp.secondary_ptm_log2fc.toFixed(2)}</span>)
              </div>
            </div>
            <div className="mt-1 text-xs">
              Pattern: {hoveredInfo.comp.concordant ? (
                <span className="text-emerald-600 font-semibold">Concordant</span>
              ) : (
                <span className="text-rose-600 font-semibold">Discordant</span>
              )}
            </div>
          </div>
        )}

        {/* Show more button */}
        {dualPTMProteins.length > maxProteins && (
          <div className="mt-3 text-center">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMaxProteins(prev => prev + 30)}
            >
              Show More ({dualPTMProteins.length - maxProteins} remaining)
            </Button>
          </div>
        )}

        {/* Color Legend */}
        <div className="mt-4 flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
          {viewMode === 'concordance' ? (
            <>
              <div className="flex items-center gap-1">
                <div className="w-4 h-3 rounded bg-emerald-400" />
                <span>Concordant (C)</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-4 h-3 rounded bg-rose-400" />
                <span>Discordant (D)</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-4 h-3 rounded bg-gray-100 border" />
                <span>No data</span>
              </div>
            </>
          ) : (
            <>
              <span className="font-medium">Log2FC Scale:</span>
              <div className="flex items-center gap-0.5">
                <div className="w-4 h-3 rounded bg-blue-600" />
                <div className="w-4 h-3 rounded bg-blue-400" />
                <div className="w-4 h-3 rounded bg-blue-200" />
                <div className="w-4 h-3 rounded bg-red-200" />
                <div className="w-4 h-3 rounded bg-red-400" />
                <div className="w-4 h-3 rounded bg-red-600" />
              </div>
              <span>Down &larr; 0 &rarr; Up</span>
            </>
          )}
          {sortMode === 'cluster' && (
            <>
              <span className="mx-2 text-muted-foreground/50">|</span>
              <span className="font-medium">Group bars:</span>
              <div className="flex items-center gap-1">
                <div className="w-2 h-3 rounded-sm bg-emerald-500" />
                <span>CON</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-2 h-3 rounded-sm bg-slate-400" />
                <span>MIX</span>
              </div>
              <div className="flex items-center gap-1">
                <div className="w-2 h-3 rounded-sm bg-rose-500" />
                <span>DIS</span>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
