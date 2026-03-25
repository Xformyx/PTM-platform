/**
 * KinaseModuleAnalysis.tsx
 * ────────────────────────────────────────────────────────────────────────────
 * Kinase Module Analysis panel for the TOP N Time-series tab.
 *
 * Three core functions:
 *   1. Co-wave Kinase Module Detection — auto-detect PTM groups co-moving
 *   2. Amplitude Rank Preservation Score — Spearman correlation of amplitude ordering
 *   3. Interactive Kinase Lookup — KEA3 enrichment for selected PTMs
 *
 * Receives time-series data + selected PTMs from the parent TopNTimeSeriesPlot.
 */

import { useState, useMemo, useCallback } from "react";
import {
  Loader2,
  Search,
  Zap,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  CheckCircle2,
  Info,
  BarChart3,
  GitMerge,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface PtmTimeSeriesRow {
  gene: string;
  position: string;
  condition: string;
  value: number; // ptm_relative_log2fc or ptm_absolute_log2fc
}

interface PtmInfo {
  gene: string;
  position: string;
  label: string;
}

interface CoWaveModule {
  id: number;
  label: string;
  ptms: PtmInfo[];
  peakCondition: string;
  avgAmplitude: number;
  amplitudeRanking: number[];
  spearmanScore: number | null;
}

interface Kea3Kinase {
  kinase: string;
  rank: number;
  score: number;
  overlapping_genes: string[];
  library?: string;
}

interface PerPtmKinaseData {
  gene: string;
  position: string;
  predicted_kinases: Array<{
    kinase: string;
    confidence: string;
    mechanism: string;
    score: number;
  }>;
  upstream_regulators: string[];
  kinase_substrate: Array<{
    kinase: string;
    substrate: string;
    pmid: string;
  }>;
}

interface KinaseEnrichmentResponse {
  module_label: string;
  gene_count: number;
  genes: string[];
  confidence_level: string;
  kea3_results: Kea3Kinase[];
  kea3_libraries: Record<string, Kea3Kinase[]>;
  kea3_error: string | null;
  per_ptm_kinases: Record<string, PerPtmKinaseData>;
  double_validated_kinases: string[];
}

interface KinaseModuleAnalysisProps {
  orderId: number;
  /** All vector data rows for the top N PTMs */
  vectorData: PtmTimeSeriesRow[];
  /** Unique top N PTMs */
  topNPtms: PtmInfo[];
  /** Currently checked PTMs (key = gene_position) */
  checkedPtms: Record<string, boolean>;
  /** Sorted condition labels (time points) */
  conditions: string[];
  /** Callback to update checked PTMs from module selection */
  onSelectPtms?: (keys: string[]) => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Spearman rank correlation between two arrays */
function spearmanCorrelation(a: number[], b: number[]): number | null {
  if (a.length !== b.length || a.length < 3) return null;
  const n = a.length;

  const rank = (arr: number[]) => {
    const sorted = arr.map((v, i) => ({ v, i })).sort((x, y) => x.v - y.v);
    const ranks = new Array(n);
    for (let i = 0; i < n; i++) {
      ranks[sorted[i].i] = i + 1;
    }
    return ranks;
  };

  const ra = rank(a);
  const rb = rank(b);

  let d2 = 0;
  for (let i = 0; i < n; i++) {
    d2 += (ra[i] - rb[i]) ** 2;
  }

  return 1 - (6 * d2) / (n * (n * n - 1));
}

/** Detect co-wave modules: group PTMs that peak at the same time point */
function detectCoWaveModules(
  ptms: PtmInfo[],
  vectorData: PtmTimeSeriesRow[],
  conditions: string[]
): CoWaveModule[] {
  if (conditions.length < 2 || ptms.length < 2) return [];

  // Build per-PTM time series
  const ptmSeries = new Map<string, number[]>();
  ptms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    const series = conditions.map((cond) => {
      const row = vectorData.find(
        (r) => r.gene === p.gene && r.position === p.position && r.condition === cond
      );
      return row?.value ?? 0;
    });
    ptmSeries.set(key, series);
  });

  // Group by peak condition (condition with max |value|)
  const peakGroups = new Map<string, PtmInfo[]>();
  ptms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    const series = ptmSeries.get(key) || [];
    const maxIdx = series.reduce(
      (best, v, i) => (Math.abs(v) > Math.abs(series[best]) ? i : best),
      0
    );
    const peakCond = conditions[maxIdx] || "unknown";
    if (!peakGroups.has(peakCond)) peakGroups.set(peakCond, []);
    peakGroups.get(peakCond)!.push(p);
  });

  // Build modules from groups with 2+ PTMs
  const modules: CoWaveModule[] = [];
  let moduleId = 0;

  // Sort by condition order
  const sortedPeaks = Array.from(peakGroups.entries()).sort(
    (a, b) => conditions.indexOf(a[0]) - conditions.indexOf(b[0])
  );

  for (const [peakCond, groupPtms] of sortedPeaks) {
    if (groupPtms.length < 2) continue;
    moduleId++;

    // Calculate average amplitude at peak
    const amplitudes = groupPtms.map((p) => {
      const key = `${p.gene}_${p.position}`;
      const series = ptmSeries.get(key) || [];
      const idx = conditions.indexOf(peakCond);
      return idx >= 0 ? series[idx] : 0;
    });
    const avgAmplitude = amplitudes.reduce((s, v) => s + v, 0) / amplitudes.length;

    // Amplitude ranking (sorted by absolute amplitude descending)
    const amplitudeRanking = amplitudes
      .map((v, i) => ({ v: Math.abs(v), i }))
      .sort((a, b) => b.v - a.v)
      .map((x) => x.i);

    // Spearman score: compare amplitude ordering across all conditions
    // For each pair of conditions, check if amplitude ordering is preserved
    let spearmanScore: number | null = null;
    if (conditions.length >= 3 && groupPtms.length >= 3) {
      const condAmplitudes = conditions.map((cond) =>
        groupPtms.map((p) => {
          const key = `${p.gene}_${p.position}`;
          const series = ptmSeries.get(key) || [];
          const idx = conditions.indexOf(cond);
          return idx >= 0 ? Math.abs(series[idx]) : 0;
        })
      );

      // Average pairwise Spearman between consecutive conditions
      const scores: number[] = [];
      for (let i = 0; i < condAmplitudes.length - 1; i++) {
        const s = spearmanCorrelation(condAmplitudes[i], condAmplitudes[i + 1]);
        if (s !== null) scores.push(s);
      }
      if (scores.length > 0) {
        spearmanScore = scores.reduce((a, b) => a + b, 0) / scores.length;
      }
    }

    modules.push({
      id: moduleId,
      label: `Module ${moduleId} (peak: ${peakCond})`,
      ptms: groupPtms,
      peakCondition: peakCond,
      avgAmplitude,
      amplitudeRanking,
      spearmanScore,
    });
  }

  return modules;
}

// ── Confidence badge ─────────────────────────────────────────────────────────

function ConfidenceBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    low: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    medium: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
    high: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
    very_high: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${styles[level] || styles.medium}`}>
      {level === "very_high" ? "Very High" : level.charAt(0).toUpperCase() + level.slice(1)} Confidence
    </span>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────

export default function KinaseModuleAnalysis({
  orderId,
  vectorData,
  topNPtms,
  checkedPtms,
  conditions,
  onSelectPtms,
}: KinaseModuleAnalysisProps) {
  const [activeTab, setActiveTab] = useState<"cowave" | "lookup" | "cascade">("cowave");
  const [enrichmentResults, setEnrichmentResults] = useState<Record<string, KinaseEnrichmentResponse>>({});
  const [loadingModule, setLoadingModule] = useState<string | null>(null);
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());
  const [manualSelection, setManualSelection] = useState<Set<string>>(new Set());
  const [manualEnrichment, setManualEnrichment] = useState<KinaseEnrichmentResponse | null>(null);
  const [manualLoading, setManualLoading] = useState(false);

  // ── Co-wave module detection ─────────────────────────────────────────────
  const checkedPtmList = useMemo(
    () => topNPtms.filter((p) => checkedPtms[`${p.gene}_${p.position}`]),
    [topNPtms, checkedPtms]
  );

  const vectorRows = useMemo<PtmTimeSeriesRow[]>(() => vectorData, [vectorData]);

  const coWaveModules = useMemo(
    () => detectCoWaveModules(checkedPtmList, vectorRows, conditions),
    [checkedPtmList, vectorRows, conditions]
  );

  // ── KEA3 enrichment call ─────────────────────────────────────────────────
  const runEnrichment = useCallback(
    async (moduleKey: string, genes: string[], label: string) => {
      setLoadingModule(moduleKey);
      try {
        const result = await api.post<KinaseEnrichmentResponse>(
          `/orders/${orderId}/kinase-enrichment`,
          { genes, module_label: label }
        );
        setEnrichmentResults((prev) => ({ ...prev, [moduleKey]: result }));
      } catch (err) {
        console.error("KEA3 enrichment failed:", err);
      } finally {
        setLoadingModule(null);
      }
    },
    [orderId]
  );

  const runManualEnrichment = useCallback(async () => {
    const genes = Array.from(manualSelection).map((key) => {
      const ptm = topNPtms.find((p) => `${p.gene}_${p.position}` === key);
      return ptm?.gene || key.split("_")[0];
    });
    if (genes.length === 0) return;
    setManualLoading(true);
    try {
      const result = await api.post<KinaseEnrichmentResponse>(
        `/orders/${orderId}/kinase-enrichment`,
        { genes, module_label: "manual_selection" }
      );
      setManualEnrichment(result);
    } catch (err) {
      console.error("Manual KEA3 enrichment failed:", err);
    } finally {
      setManualLoading(false);
    }
  }, [orderId, manualSelection, topNPtms]);

  const toggleModuleExpand = (key: string) => {
    setExpandedModules((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleManualPtm = (key: string) => {
    setManualSelection((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <Card className="mt-6 border-dashed border-2 border-blue-200 dark:border-blue-800">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Zap className="h-4 w-4 text-amber-500" />
          Kinase Module Analysis
          <Badge variant="outline" className="text-[10px] ml-2">
            Experimental
          </Badge>
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          Co-wave module detection, KEA3 kinase enrichment, and cascade inference.
          PTMs co-moving in the same time-point waves likely share common upstream kinases.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Tab navigation */}
        <div className="flex gap-1 border-b pb-2">
          <Button
            variant={activeTab === "cowave" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => setActiveTab("cowave")}
          >
            <GitMerge className="h-3 w-3 mr-1" /> Co-wave Modules
          </Button>
          <Button
            variant={activeTab === "lookup" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => setActiveTab("lookup")}
          >
            <Search className="h-3 w-3 mr-1" /> Kinase Lookup
          </Button>
          <Button
            variant={activeTab === "cascade" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => setActiveTab("cascade")}
          >
            <BarChart3 className="h-3 w-3 mr-1" /> Cascade View
          </Button>
        </div>

        {/* ── Tab: Co-wave Modules ──────────────────────────────────────── */}
        {activeTab === "cowave" && (
          <div className="space-y-3">
            {conditions.length < 3 && (
              <Alert>
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Insufficient Time Points</AlertTitle>
                <AlertDescription className="text-xs">
                  Co-wave detection requires at least 3 time points. Current: {conditions.length}
                </AlertDescription>
              </Alert>
            )}

            {coWaveModules.length === 0 && conditions.length >= 3 && (
              <div className="text-center py-6 text-sm text-muted-foreground">
                <Info className="h-8 w-8 mx-auto mb-2 opacity-40" />
                No co-wave modules detected. Enable more PTMs in the checklist above, or try a different trend filter.
              </div>
            )}

            {coWaveModules.map((mod) => {
              const moduleKey = `module_${mod.id}`;
              const isExpanded = expandedModules.has(moduleKey);
              const enrichment = enrichmentResults[moduleKey];
              const isLoading = loadingModule === moduleKey;
              const genes = mod.ptms.map((p) => p.gene);
              const uniqueGenes = [...new Set(genes)];

              return (
                <div
                  key={moduleKey}
                  className="rounded-lg border bg-card p-3 space-y-2"
                >
                  {/* Module header */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => toggleModuleExpand(moduleKey)}
                        className="flex items-center gap-1 text-sm font-medium hover:text-primary"
                      >
                        {isExpanded ? (
                          <ChevronUp className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5" />
                        )}
                        {mod.label}
                      </button>
                      <Badge variant="outline" className="text-[10px]">
                        {mod.ptms.length} PTMs
                      </Badge>
                      <Badge variant="outline" className="text-[10px]">
                        {uniqueGenes.length} genes
                      </Badge>
                      {mod.spearmanScore !== null && (
                        <Badge
                          variant="outline"
                          className={`text-[10px] ${
                            mod.spearmanScore > 0.7
                              ? "border-green-500 text-green-700 dark:text-green-400"
                              : mod.spearmanScore > 0.3
                              ? "border-amber-500 text-amber-700 dark:text-amber-400"
                              : "border-red-500 text-red-700 dark:text-red-400"
                          }`}
                        >
                          ρ = {mod.spearmanScore.toFixed(2)}
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {onSelectPtms && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-[10px] h-6 px-2"
                          onClick={() =>
                            onSelectPtms(mod.ptms.map((p) => `${p.gene}_${p.position}`))
                          }
                        >
                          Highlight in Chart
                        </Button>
                      )}
                      <Button
                        variant="default"
                        size="sm"
                        className="text-[10px] h-6 px-2"
                        disabled={isLoading || uniqueGenes.length === 0}
                        onClick={() => runEnrichment(moduleKey, uniqueGenes, mod.label)}
                      >
                        {isLoading ? (
                          <Loader2 className="h-3 w-3 animate-spin mr-1" />
                        ) : (
                          <Zap className="h-3 w-3 mr-1" />
                        )}
                        Run KEA3
                      </Button>
                    </div>
                  </div>

                  {/* Expanded content */}
                  {isExpanded && (
                    <div className="space-y-3 pt-2">
                      {/* PTM list */}
                      <div className="flex flex-wrap gap-1">
                        {mod.ptms.map((p) => (
                          <span
                            key={`${p.gene}_${p.position}`}
                            className="px-2 py-0.5 rounded-full bg-muted text-xs"
                          >
                            {p.label}
                          </span>
                        ))}
                      </div>

                      {/* Amplitude Rank Preservation */}
                      {mod.spearmanScore !== null && (
                        <div className="text-xs text-muted-foreground bg-muted/50 rounded p-2">
                          <strong>Amplitude Rank Preservation Score:</strong>{" "}
                          ρ = {mod.spearmanScore.toFixed(3)}
                          {mod.spearmanScore > 0.7 ? (
                            <span className="text-green-600 ml-1">
                              — High preservation: likely same kinase module
                            </span>
                          ) : mod.spearmanScore > 0.3 ? (
                            <span className="text-amber-600 ml-1">
                              — Moderate: possible shared regulation
                            </span>
                          ) : (
                            <span className="text-red-600 ml-1">
                              — Low: different kinase involvement likely
                            </span>
                          )}
                        </div>
                      )}

                      {/* KEA3 Results */}
                      {enrichment && <EnrichmentResultPanel result={enrichment} />}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* ── Tab: Kinase Lookup ────────────────────────────────────────── */}
        {activeTab === "lookup" && (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Select PTMs below, then click "Run KEA3 Enrichment" to find common upstream kinases.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1 max-h-48 overflow-y-auto border rounded p-2">
              {checkedPtmList.map((p) => {
                const key = `${p.gene}_${p.position}`;
                const isSelected = manualSelection.has(key);
                return (
                  <label
                    key={key}
                    className={`flex items-center gap-1.5 cursor-pointer rounded px-2 py-1 text-xs ${
                      isSelected ? "bg-blue-100 dark:bg-blue-900/40" : "hover:bg-muted/50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleManualPtm(key)}
                      className="rounded"
                    />
                    <span className="truncate">{p.label}</span>
                  </label>
                );
              })}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="default"
                size="sm"
                className="text-xs"
                disabled={manualSelection.size === 0 || manualLoading}
                onClick={runManualEnrichment}
              >
                {manualLoading ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Zap className="h-3 w-3 mr-1" />
                )}
                Run KEA3 Enrichment ({manualSelection.size} PTMs)
              </Button>
              {manualSelection.size > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs"
                  onClick={() => setManualSelection(new Set())}
                >
                  Clear
                </Button>
              )}
            </div>

            {manualSelection.size > 0 && manualSelection.size < 3 && (
              <Alert>
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Low Confidence Warning</AlertTitle>
                <AlertDescription className="text-xs">
                  KEA3 results with fewer than 3 genes have low statistical confidence.
                  Consider selecting more PTMs for reliable kinase predictions.
                </AlertDescription>
              </Alert>
            )}

            {manualEnrichment && <EnrichmentResultPanel result={manualEnrichment} />}
          </div>
        )}

        {/* ── Tab: Cascade View ─────────────────────────────────────────── */}
        {activeTab === "cascade" && (
          <CascadeView
            modules={coWaveModules}
            enrichmentResults={enrichmentResults}
            conditions={conditions}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ── Enrichment Result Panel ──────────────────────────────────────────────────

function EnrichmentResultPanel({ result }: { result: KinaseEnrichmentResponse }) {
  const [showLibraries, setShowLibraries] = useState(false);

  if (result.kea3_error) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>KEA3 API Error</AlertTitle>
        <AlertDescription className="text-xs">{result.kea3_error}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-3 border-t pt-3">
      {/* Header info */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <ConfidenceBadge level={result.confidence_level} />
        <span className="text-muted-foreground">
          {result.gene_count} genes queried: {result.genes.join(", ")}
        </span>
      </div>

      {/* Double-validated kinases */}
      {result.double_validated_kinases.length > 0 && (
        <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-1 text-xs font-medium text-green-700 dark:text-green-400">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Double-Validated Kinases (KEA3 + Per-PTM Predictions)
          </div>
          <div className="flex flex-wrap gap-1">
            {result.double_validated_kinases.map((k) => (
              <Badge key={k} variant="outline" className="text-[10px] border-green-500 text-green-700 dark:text-green-400">
                {k}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* KEA3 Integrated results */}
      <div>
        <p className="text-xs font-medium mb-1">
          KEA3 Integrated Ranking (Top 15)
        </p>
        <div className="max-h-64 overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-[10px] w-10">#</TableHead>
                <TableHead className="text-[10px]">Kinase</TableHead>
                <TableHead className="text-[10px] w-16">Score</TableHead>
                <TableHead className="text-[10px]">Overlapping Genes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.kea3_results.slice(0, 15).map((k, i) => {
                const isDoubleValidated = result.double_validated_kinases.includes(k.kinase.toUpperCase()) ||
                  result.double_validated_kinases.includes(k.kinase);
                return (
                  <TableRow
                    key={`${k.kinase}_${i}`}
                    className={isDoubleValidated ? "bg-green-50/50 dark:bg-green-900/10" : ""}
                  >
                    <TableCell className="text-[10px] font-mono">{k.rank}</TableCell>
                    <TableCell className="text-[10px] font-medium">
                      {k.kinase}
                      {isDoubleValidated && (
                        <CheckCircle2 className="h-3 w-3 inline ml-1 text-green-500" />
                      )}
                    </TableCell>
                    <TableCell className="text-[10px] font-mono">
                      {typeof k.score === "number" ? k.score.toFixed(2) : k.score}
                    </TableCell>
                    <TableCell className="text-[10px] text-muted-foreground">
                      {k.overlapping_genes.filter(Boolean).join(", ") || "—"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Individual library results (collapsible) */}
      {Object.keys(result.kea3_libraries).length > 0 && (
        <div>
          <button
            onClick={() => setShowLibraries(!showLibraries)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {showLibraries ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            Individual Library Results ({Object.keys(result.kea3_libraries).length} libraries)
          </button>
          {showLibraries && (
            <div className="mt-2 space-y-2">
              {Object.entries(result.kea3_libraries).map(([lib, kinases]) => (
                <div key={lib} className="border rounded p-2">
                  <p className="text-[10px] font-medium mb-1">{lib}</p>
                  <div className="flex flex-wrap gap-1">
                    {kinases.slice(0, 5).map((k, i) => (
                      <span key={`${k.kinase}_${i}`} className="text-[10px] px-1.5 py-0.5 rounded bg-muted">
                        #{k.rank} {k.kinase}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Per-PTM kinase predictions */}
      {Object.keys(result.per_ptm_kinases).length > 0 && (
        <div>
          <p className="text-xs font-medium mb-1">
            Per-PTM Kinase Predictions (from RAG Enrichment)
          </p>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {Object.entries(result.per_ptm_kinases).map(([ptmKey, data]) => (
              <div key={ptmKey} className="flex items-start gap-2 text-[10px] border-b pb-1">
                <span className="font-medium min-w-[80px]">{ptmKey}</span>
                <div className="flex flex-wrap gap-1">
                  {data.predicted_kinases.slice(0, 3).map((k, i) => (
                    <span key={i} className="px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300">
                      {k.kinase} ({k.confidence})
                    </span>
                  ))}
                  {data.kinase_substrate.slice(0, 2).map((ks, i) => (
                    <span key={`ks_${i}`} className="px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300">
                      {ks.kinase}→{ks.substrate}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Cascade View ─────────────────────────────────────────────────────────────

function CascadeView({
  modules,
  enrichmentResults,
  conditions,
}: {
  modules: CoWaveModule[];
  enrichmentResults: Record<string, KinaseEnrichmentResponse>;
  conditions: string[];
}) {
  if (modules.length === 0) {
    return (
      <div className="text-center py-6 text-sm text-muted-foreground">
        <BarChart3 className="h-8 w-8 mx-auto mb-2 opacity-40" />
        Run co-wave detection first (enable PTMs in the chart above).
        Cascade view shows temporal ordering of kinase modules.
      </div>
    );
  }

  // Sort modules by peak condition order
  const sortedModules = [...modules].sort(
    (a, b) => conditions.indexOf(a.peakCondition) - conditions.indexOf(b.peakCondition)
  );

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Proposed cascade order based on peak timing. Earlier peaks suggest upstream position in signaling cascade.
      </p>

      <div className="flex items-center gap-0 overflow-x-auto pb-2">
        {sortedModules.map((mod, idx) => {
          const moduleKey = `module_${mod.id}`;
          const enrichment = enrichmentResults[moduleKey];
          const topKinase = enrichment?.kea3_results?.[0];
          const doubleValidated = enrichment?.double_validated_kinases || [];

          return (
            <div key={moduleKey} className="flex items-center">
              {/* Module card */}
              <div className="rounded-lg border bg-card p-3 min-w-[180px] space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">{mod.label}</span>
                  <Badge variant="outline" className="text-[9px]">
                    {mod.ptms.length} PTMs
                  </Badge>
                </div>
                <div className="text-[10px] text-muted-foreground">
                  Avg amplitude: {mod.avgAmplitude.toFixed(2)}
                </div>
                {topKinase && (
                  <div className="text-[10px]">
                    <span className="text-muted-foreground">Top kinase: </span>
                    <span className="font-medium text-amber-600 dark:text-amber-400">
                      {topKinase.kinase}
                    </span>
                    {doubleValidated.includes(topKinase.kinase.toUpperCase()) && (
                      <CheckCircle2 className="h-3 w-3 inline ml-0.5 text-green-500" />
                    )}
                  </div>
                )}
                {mod.spearmanScore !== null && (
                  <div className="text-[10px] text-muted-foreground">
                    Rank preservation: ρ={mod.spearmanScore.toFixed(2)}
                  </div>
                )}
                <div className="flex flex-wrap gap-0.5">
                  {mod.ptms.slice(0, 4).map((p) => (
                    <span
                      key={`${p.gene}_${p.position}`}
                      className="text-[9px] px-1 py-0 rounded bg-muted"
                    >
                      {p.gene}
                    </span>
                  ))}
                  {mod.ptms.length > 4 && (
                    <span className="text-[9px] text-muted-foreground">
                      +{mod.ptms.length - 4}
                    </span>
                  )}
                </div>
              </div>

              {/* Arrow between modules */}
              {idx < sortedModules.length - 1 && (
                <div className="flex items-center px-2 text-muted-foreground">
                  <ArrowRight className="h-4 w-4" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Cascade hypothesis */}
      {sortedModules.length >= 2 && (
        <div className="bg-muted/50 rounded-lg p-3 text-xs text-muted-foreground">
          <strong>Cascade Hypothesis:</strong> Based on peak timing,{" "}
          {sortedModules.map((m) => m.label).join(" → ")} represents the proposed
          signaling cascade order. PTMs peaking earlier are likely upstream in the
          kinase cascade. Verify with KEA3 enrichment results for each module.
        </div>
      )}
    </div>
  );
}
