/**
 * KinaseModuleAnalysis.tsx
 * ────────────────────────────────────────────────────────────────────────────
 * Kinase Module Analysis panel for the TOP N Time-series tab.
 *
 * Core functions:
 *   1. Co-wave Kinase Module Detection — auto-detect PTM groups co-moving
 *   2. Amplitude Rank Preservation Score — Spearman correlation of amplitude ordering
 *   3. Interactive Kinase Lookup — KEA3 enrichment for selected PTMs
 *   4. Motif-based Kinase Annotation — per-PTM kinase status (known / motif / novel)
 *   5. Concordance Analysis — motif vs known kinase agreement
 *
 * Receives time-series data + selected PTMs from the parent TopNTimeSeriesPlot.
 */

import { useState, useMemo, useCallback, useEffect } from "react";
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
  FlaskConical,
  Sparkles,
  HelpCircle,
  ShieldCheck,
  ShieldAlert,
  ShieldQuestion,
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
  value: number;
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

// ── Motif Annotation Types ──────────────────────────────────────────────────

interface MotifPredictedKinase {
  kinase_family: string;
  motif: string;
  source: string;
}

interface KnownKinase {
  kinase: string;
  confidence: string;
  mechanism: string;
  source: string;
  pmid?: string;
}

interface PtmAnnotation {
  gene: string;
  position: string;
  label: string;
  status: "known" | "motif_only" | "novel_candidate";
  known_kinases: KnownKinase[];
  motif_predicted_kinases: MotifPredictedKinase[];
  sequence_window: string;
  concordance: "concordant" | "discordant" | "not_applicable";
  concordance_details: string[];
}

interface MotifAnnotationResponse {
  order_id: number;
  ptm_count: number;
  annotations: PtmAnnotation[];
  summary: {
    status_counts: Record<string, number>;
    concordance_counts: Record<string, number>;
  };
}

interface KinaseModuleAnalysisProps {
  orderId: number;
  vectorData: PtmTimeSeriesRow[];
  topNPtms: PtmInfo[];
  checkedPtms: Record<string, boolean>;
  conditions: string[];
  onSelectPtms?: (keys: string[]) => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

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

function detectCoWaveModules(
  ptms: PtmInfo[],
  vectorData: PtmTimeSeriesRow[],
  conditions: string[]
): CoWaveModule[] {
  if (conditions.length < 2 || ptms.length < 2) return [];

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

  const modules: CoWaveModule[] = [];
  let moduleId = 0;

  const sortedPeaks = Array.from(peakGroups.entries()).sort(
    (a, b) => conditions.indexOf(a[0]) - conditions.indexOf(b[0])
  );

  for (const [peakCond, groupPtms] of sortedPeaks) {
    if (groupPtms.length < 2) continue;
    moduleId++;

    const amplitudes = groupPtms.map((p) => {
      const key = `${p.gene}_${p.position}`;
      const series = ptmSeries.get(key) || [];
      const idx = conditions.indexOf(peakCond);
      return idx >= 0 ? series[idx] : 0;
    });
    const avgAmplitude = amplitudes.reduce((s, v) => s + v, 0) / amplitudes.length;

    const amplitudeRanking = amplitudes
      .map((v, i) => ({ v: Math.abs(v), i }))
      .sort((a, b) => b.v - a.v)
      .map((x) => x.i);

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

// ── Status icon/badge helpers ───────────────────────────────────────────────

const STATUS_CONFIG = {
  known: {
    icon: ShieldCheck,
    label: "Known Kinase",
    color: "text-green-600 dark:text-green-400",
    bg: "bg-green-50 dark:bg-green-900/20",
    border: "border-green-300 dark:border-green-700",
    badgeCls: "border-green-500 text-green-700 dark:text-green-400",
  },
  motif_only: {
    icon: FlaskConical,
    label: "Motif Predicted",
    color: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-50 dark:bg-amber-900/20",
    border: "border-amber-300 dark:border-amber-700",
    badgeCls: "border-amber-500 text-amber-700 dark:text-amber-400",
  },
  novel_candidate: {
    icon: Sparkles,
    label: "Novel Candidate",
    color: "text-purple-600 dark:text-purple-400",
    bg: "bg-purple-50 dark:bg-purple-900/20",
    border: "border-purple-300 dark:border-purple-700",
    badgeCls: "border-purple-500 text-purple-700 dark:text-purple-400",
  },
} as const;

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

  // ── Motif annotation state ──────────────────────────────────────────────
  const [motifAnnotations, setMotifAnnotations] = useState<Record<string, MotifAnnotationResponse>>({});
  const [motifLoading, setMotifLoading] = useState<string | null>(null);
  const [motifError, setMotifError] = useState<string | null>(null);

  // ── Manual (Kinase Lookup) annotation state ────────────────────────────
  const [manualAnnotation, setManualAnnotation] = useState<MotifAnnotationResponse | null>(null);
  const [manualAnnotationLoading, setManualAnnotationLoading] = useState(false);

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

  // ── Motif annotation call ────────────────────────────────────────────
  const runMotifAnnotation = useCallback(
    async (moduleKey: string, ptms: PtmInfo[], kea3TopKinases: string[]) => {
      setMotifLoading(moduleKey);
      setMotifError(null);
      // Auto-expand the module so results are visible
      setExpandedModules((prev) => {
        const next = new Set(prev);
        next.add(moduleKey);
        return next;
      });
      try {
        const result = await api.post<MotifAnnotationResponse>(
          `/orders/${orderId}/motif-kinase-annotation`,
          {
            ptms: ptms.map((p) => ({ gene: p.gene, position: p.position })),
            kea3_top_kinases: kea3TopKinases,
          }
        );
        setMotifAnnotations((prev) => ({ ...prev, [moduleKey]: result }));
      } catch (err: any) {
        console.error("Motif annotation failed:", err);
        setMotifError(err?.message || "Motif annotation request failed");
      } finally {
        setMotifLoading(null);
      }
    },
    [orderId]
  );

  // ── Manual (Kinase Lookup) motif annotation call ────────────────────────
  const runManualAnnotation = useCallback(async () => {
    const selectedPtms = topNPtms.filter((p) => manualSelection.has(`${p.gene}_${p.position}`));
    if (selectedPtms.length === 0) return;
    setManualAnnotationLoading(true);
    setMotifError(null);
    try {
      const kea3Top = manualEnrichment?.kea3_results?.slice(0, 10).map((k) => k.kinase) || [];
      const result = await api.post<MotifAnnotationResponse>(
        `/orders/${orderId}/motif-kinase-annotation`,
        {
          ptms: selectedPtms.map((p) => ({ gene: p.gene, position: p.position })),
          kea3_top_kinases: kea3Top,
        }
      );
      setManualAnnotation(result);
    } catch (err: any) {
      console.error("Manual annotation failed:", err);
      setMotifError(err?.message || "Motif annotation request failed");
    } finally {
      setManualAnnotationLoading(false);
    }
  }, [orderId, manualSelection, topNPtms, manualEnrichment]);

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
      if (onSelectPtms && next.size > 0) {
        onSelectPtms(Array.from(next));
      }
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
          Co-wave module detection, KEA3 kinase enrichment, motif-based kinase prediction, and cascade inference.
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
              const annotation = motifAnnotations[moduleKey];
              const isLoading = loadingModule === moduleKey;
              const isMotifLoading = motifLoading === moduleKey;
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
                      {/* Annotation summary badges */}
                      {annotation && (
                        <div className="flex gap-1">
                          {annotation.summary.status_counts.known > 0 && (
                            <Badge variant="outline" className="text-[9px] border-green-500 text-green-600 dark:text-green-400">
                              <ShieldCheck className="h-2.5 w-2.5 mr-0.5" />
                              {annotation.summary.status_counts.known} Known
                            </Badge>
                          )}
                          {annotation.summary.status_counts.motif_only > 0 && (
                            <Badge variant="outline" className="text-[9px] border-amber-500 text-amber-600 dark:text-amber-400">
                              <FlaskConical className="h-2.5 w-2.5 mr-0.5" />
                              {annotation.summary.status_counts.motif_only} Motif
                            </Badge>
                          )}
                          {annotation.summary.status_counts.novel_candidate > 0 && (
                            <Badge variant="outline" className="text-[9px] border-purple-500 text-purple-600 dark:text-purple-400">
                              <Sparkles className="h-2.5 w-2.5 mr-0.5" />
                              {annotation.summary.status_counts.novel_candidate} Novel
                            </Badge>
                          )}
                        </div>
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
                      <Button
                        variant="outline"
                        size="sm"
                        className="text-[10px] h-6 px-2"
                        disabled={isMotifLoading}
                        onClick={() => {
                          const kea3Top = enrichment?.kea3_results?.slice(0, 10).map((k) => k.kinase) || [];
                          runMotifAnnotation(moduleKey, mod.ptms, kea3Top);
                        }}
                      >
                        {isMotifLoading ? (
                          <Loader2 className="h-3 w-3 animate-spin mr-1" />
                        ) : (
                          <FlaskConical className="h-3 w-3 mr-1" />
                        )}
                        Annotate
                      </Button>
                    </div>
                  </div>

                  {/* Motif error display */}
                  {motifError && motifLoading === null && (
                    <Alert variant="destructive" className="mt-2">
                      <AlertTriangle className="h-4 w-4" />
                      <AlertTitle>Annotation Error</AlertTitle>
                      <AlertDescription className="text-xs">{motifError}</AlertDescription>
                    </Alert>
                  )}

                  {/* Loading indicator */}
                  {isMotifLoading && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground mt-2 py-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Running motif annotation for {mod.ptms.length} PTMs...
                    </div>
                  )}

                  {/* Expanded content */}
                  {isExpanded && (
                    <div className="space-y-3 pt-2">
                      {/* PTM list with annotation status */}
                      <div className="flex flex-wrap gap-1">
                        {mod.ptms.map((p) => {
                          const ptmKey = `${p.gene}_${p.position}`;
                          const ann = annotation?.annotations?.find(
                            (a) => a.gene === p.gene && a.position === p.position
                          );
                          const statusCfg = ann ? STATUS_CONFIG[ann.status] : null;
                          const StatusIcon = statusCfg?.icon;

                          return (
                            <span
                              key={ptmKey}
                              className={`px-2 py-0.5 rounded-full text-xs flex items-center gap-1 border ${
                                statusCfg
                                  ? `${statusCfg.bg} ${statusCfg.border} ${statusCfg.color}`
                                  : "bg-muted"
                              }`}
                              title={
                                ann
                                  ? `${statusCfg?.label}${
                                      ann.known_kinases.length > 0
                                        ? ` | Known: ${ann.known_kinases.map((k) => k.kinase).join(", ")}`
                                        : ""
                                    }${
                                      ann.motif_predicted_kinases.length > 0
                                        ? ` | Motif: ${ann.motif_predicted_kinases.map((m) => m.kinase_family).join(", ")}`
                                        : ""
                                    }${
                                      ann.concordance !== "not_applicable"
                                        ? ` | ${ann.concordance}`
                                        : ""
                                    }`
                                  : p.label
                              }
                            >
                              {StatusIcon && <StatusIcon className="h-3 w-3" />}
                              {p.label}
                            </span>
                          );
                        })}
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

                      {/* ── Motif Annotation Detail Panel ────────────────── */}
                      {annotation && (
                        <MotifAnnotationPanel annotation={annotation} />
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
              Select PTMs below to highlight them in the chart above. Click "Run KEA3 Enrichment" to find common upstream kinases,
              or "Annotate" to check motif-based kinase predictions and identify novel substrate candidates.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1 max-h-48 overflow-y-auto border rounded p-2">
              {topNPtms.map((p) => {
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
              <Button
                variant="outline"
                size="sm"
                className="text-xs"
                disabled={manualSelection.size === 0 || manualAnnotationLoading}
                onClick={runManualAnnotation}
              >
                {manualAnnotationLoading ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <FlaskConical className="h-3 w-3 mr-1" />
                )}
                Annotate ({manualSelection.size} PTMs)
              </Button>
              {manualSelection.size > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs"
                  onClick={() => {
                    setManualSelection(new Set());
                    setManualAnnotation(null);
                    if (onSelectPtms) {
                      onSelectPtms(topNPtms.map((p) => `${p.gene}_${p.position}`));
                    }
                  }}
                >
                  Clear (Show All)
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

            {/* Motif error in lookup tab */}
            {motifError && !manualAnnotationLoading && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Annotation Error</AlertTitle>
                <AlertDescription className="text-xs">{motifError}</AlertDescription>
              </Alert>
            )}

            {/* Loading indicator for manual annotation */}
            {manualAnnotationLoading && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Running motif annotation for {manualSelection.size} PTMs...
              </div>
            )}

            {manualEnrichment && <EnrichmentResultPanel result={manualEnrichment} />}

            {/* Manual Annotation Results */}
            {manualAnnotation && (
              <div className="mt-2">
                <Separator className="mb-3" />
                <MotifAnnotationPanel annotation={manualAnnotation} />
              </div>
            )}
          </div>
        )}

        {/* ── Tab: Cascade View ─────────────────────────────────────────── */}
        {activeTab === "cascade" && (
          <CascadeView
            modules={coWaveModules}
            enrichmentResults={enrichmentResults}
            motifAnnotations={motifAnnotations}
            conditions={conditions}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ── Motif Annotation Panel ──────────────────────────────────────────────────

function MotifAnnotationPanel({ annotation }: { annotation: MotifAnnotationResponse }) {
  const { summary, annotations } = annotation;
  const [showAll, setShowAll] = useState(false);

  const novelCandidates = annotations.filter((a) => a.status === "novel_candidate");
  const motifOnly = annotations.filter((a) => a.status === "motif_only");
  const known = annotations.filter((a) => a.status === "known");
  const concordant = annotations.filter((a) => a.concordance === "concordant");
  const discordant = annotations.filter((a) => a.concordance === "discordant");

  return (
    <div className="space-y-3 border rounded-lg p-3 bg-muted/30">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium flex items-center gap-1">
          <FlaskConical className="h-3.5 w-3.5 text-amber-500" />
          Kinase Annotation Summary
        </p>
        <div className="flex gap-2 text-[10px]">
          <span className="flex items-center gap-0.5 text-green-600 dark:text-green-400">
            <ShieldCheck className="h-3 w-3" /> {summary.status_counts.known || 0} Known
          </span>
          <span className="flex items-center gap-0.5 text-amber-600 dark:text-amber-400">
            <FlaskConical className="h-3 w-3" /> {summary.status_counts.motif_only || 0} Motif-only
          </span>
          <span className="flex items-center gap-0.5 text-purple-600 dark:text-purple-400">
            <Sparkles className="h-3 w-3" /> {summary.status_counts.novel_candidate || 0} Novel
          </span>
        </div>
      </div>

      {/* Novel Candidates highlight */}
      {novelCandidates.length > 0 && (
        <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-3 space-y-1.5">
          <div className="flex items-center gap-1 text-xs font-medium text-purple-700 dark:text-purple-400">
            <Sparkles className="h-3.5 w-3.5" />
            Novel Substrate Candidates ({novelCandidates.length})
          </div>
          <p className="text-[10px] text-purple-600 dark:text-purple-300">
            These PTMs co-move with the module but have no known kinase in any database.
            They represent potential novel kinase-substrate relationships for experimental validation.
          </p>
          <div className="flex flex-wrap gap-1 mt-1">
            {novelCandidates.map((a) => (
              <span
                key={`${a.gene}_${a.position}`}
                className="px-2 py-0.5 rounded-full text-[10px] bg-purple-100 dark:bg-purple-800/40 text-purple-700 dark:text-purple-300 border border-purple-300 dark:border-purple-600"
              >
                <Sparkles className="h-2.5 w-2.5 inline mr-0.5" />
                {a.label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Motif-only with concordance info */}
      {motifOnly.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-900/20 rounded-lg p-3 space-y-1.5">
          <div className="flex items-center gap-1 text-xs font-medium text-amber-700 dark:text-amber-400">
            <FlaskConical className="h-3.5 w-3.5" />
            Motif-Predicted Only ({motifOnly.length})
          </div>
          <p className="text-[10px] text-amber-600 dark:text-amber-300">
            Kinase family predicted from flanking sequence motif or residue type, but no literature-confirmed kinase.
          </p>
          <div className="space-y-1 mt-1">
            {motifOnly.map((a) => {
              const seqMotifs = a.motif_predicted_kinases.filter((m) => m.source !== "residue_prediction");
              const resMotifs = a.motif_predicted_kinases.filter((m) => m.source === "residue_prediction");
              return (
              <div key={`${a.gene}_${a.position}`} className="flex items-start gap-2 text-[10px]">
                <span className="font-medium min-w-[80px] text-amber-700 dark:text-amber-300">
                  {a.label}
                </span>
                <div className="flex flex-wrap gap-1">
                  {seqMotifs.map((m, i) => (
                    <span key={`s${i}`} className="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-800/30 text-amber-800 dark:text-amber-200">
                      {m.kinase_family} <span className="opacity-60">({m.motif})</span>
                    </span>
                  ))}
                  {resMotifs.length > 0 && seqMotifs.length === 0 && (
                    <span className="px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400 italic">
                      Residue-based: {resMotifs.map((m) => m.kinase_family).join(", ")}
                    </span>
                  )}
                </div>
                {a.concordance === "concordant" && (
                  <Badge variant="outline" className="text-[9px] border-green-500 text-green-600 h-4">
                    <CheckCircle2 className="h-2.5 w-2.5 mr-0.5" /> Concordant
                  </Badge>
                )}
                {a.concordance === "discordant" && (
                  <Badge variant="outline" className="text-[9px] border-red-500 text-red-600 h-4">
                    <ShieldAlert className="h-2.5 w-2.5 mr-0.5" /> Discordant
                  </Badge>
                )}
              </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Known kinases with concordance */}
      {known.length > 0 && (
        <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 space-y-1.5">
          <div className="flex items-center gap-1 text-xs font-medium text-green-700 dark:text-green-400">
            <ShieldCheck className="h-3.5 w-3.5" />
            Known Kinase Substrates ({known.length})
          </div>
          <div className="space-y-1 mt-1">
            {known.map((a) => (
              <div key={`${a.gene}_${a.position}`} className="flex items-start gap-2 text-[10px]">
                <span className="font-medium min-w-[80px] text-green-700 dark:text-green-300">
                  {a.label}
                </span>
                <div className="flex flex-wrap gap-1">
                  {a.known_kinases.slice(0, 3).map((k, i) => (
                    <span key={i} className="px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-800/30 text-green-800 dark:text-green-200">
                      {k.kinase} <span className="opacity-60">({k.confidence})</span>
                    </span>
                  ))}
                  {a.motif_predicted_kinases.length > 0 && (
                    <>
                      <span className="text-muted-foreground">|</span>
                      {a.motif_predicted_kinases.slice(0, 2).map((m, i) => (
                        <span key={`m${i}`} className="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-800/30 text-amber-800 dark:text-amber-200">
                          Motif: {m.kinase_family}
                        </span>
                      ))}
                    </>
                  )}
                </div>
                {a.concordance === "concordant" && (
                  <Badge variant="outline" className="text-[9px] border-green-500 text-green-600 h-4">
                    <CheckCircle2 className="h-2.5 w-2.5 mr-0.5" /> Match
                  </Badge>
                )}
                {a.concordance === "discordant" && (
                  <Badge variant="outline" className="text-[9px] border-red-500 text-red-600 h-4">
                    <ShieldAlert className="h-2.5 w-2.5 mr-0.5" /> Mismatch
                  </Badge>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Concordance summary */}
      {(concordant.length > 0 || discordant.length > 0) && (
        <div className="text-xs text-muted-foreground bg-muted/50 rounded p-2">
          <strong>Concordance Summary:</strong>{" "}
          {concordant.length > 0 && (
            <span className="text-green-600">
              {concordant.length} PTM(s) where motif prediction matches known/KEA3 kinase.{" "}
            </span>
          )}
          {discordant.length > 0 && (
            <span className="text-red-600">
              {discordant.length} PTM(s) where motif prediction differs from known/KEA3 kinase
              — may indicate context-dependent regulation or novel mechanism.
            </span>
          )}
        </div>
      )}

      {/* Detailed annotation table (collapsible) */}
      <button
        onClick={() => setShowAll(!showAll)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        {showAll ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        Full Annotation Table ({annotations.length} PTMs)
      </button>
      {showAll && (
        <div className="max-h-64 overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-[10px]">PTM</TableHead>
                <TableHead className="text-[10px] w-20">Status</TableHead>
                <TableHead className="text-[10px]">Known Kinase</TableHead>
                <TableHead className="text-[10px]">Motif Prediction</TableHead>
                <TableHead className="text-[10px] w-20">Concordance</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {annotations.map((a) => {
                const cfg = STATUS_CONFIG[a.status];
                const Icon = cfg.icon;
                return (
                  <TableRow key={`${a.gene}_${a.position}`} className={cfg.bg}>
                    <TableCell className="text-[10px] font-medium">{a.label}</TableCell>
                    <TableCell className="text-[10px]">
                      <span className={`flex items-center gap-0.5 ${cfg.color}`}>
                        <Icon className="h-3 w-3" />
                        {cfg.label}
                      </span>
                    </TableCell>
                    <TableCell className="text-[10px]">
                      {a.known_kinases.length > 0
                        ? a.known_kinases.map((k) => k.kinase).join(", ")
                        : <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="text-[10px]">
                      {a.motif_predicted_kinases.length > 0
                        ? a.motif_predicted_kinases.map((m) => m.kinase_family).join(", ")
                        : <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="text-[10px]">
                      {a.concordance === "concordant" && (
                        <span className="text-green-600 flex items-center gap-0.5">
                          <CheckCircle2 className="h-3 w-3" /> Match
                        </span>
                      )}
                      {a.concordance === "discordant" && (
                        <span className="text-red-600 flex items-center gap-0.5">
                          <ShieldAlert className="h-3 w-3" /> Mismatch
                        </span>
                      )}
                      {a.concordance === "not_applicable" && (
                        <span className="text-muted-foreground">N/A</span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
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
          KEA3 Integrated Ranking (Top 15) <span className="text-muted-foreground font-normal">(lower score = stronger evidence)</span>
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
  motifAnnotations,
  conditions,
}: {
  modules: CoWaveModule[];
  enrichmentResults: Record<string, KinaseEnrichmentResponse>;
  motifAnnotations: Record<string, MotifAnnotationResponse>;
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
          const annotation = motifAnnotations[moduleKey];
          const topKinase = enrichment?.kea3_results?.[0];
          const doubleValidated = enrichment?.double_validated_kinases || [];

          return (
            <div key={moduleKey} className="flex items-center">
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
                {/* Annotation status in cascade */}
                {annotation && (
                  <div className="flex gap-1 flex-wrap">
                    {annotation.summary.status_counts.novel_candidate > 0 && (
                      <span className="text-[9px] px-1 py-0 rounded bg-purple-100 dark:bg-purple-800/30 text-purple-600 dark:text-purple-300">
                        {annotation.summary.status_counts.novel_candidate} novel
                      </span>
                    )}
                    {annotation.summary.status_counts.motif_only > 0 && (
                      <span className="text-[9px] px-1 py-0 rounded bg-amber-100 dark:bg-amber-800/30 text-amber-600 dark:text-amber-300">
                        {annotation.summary.status_counts.motif_only} motif
                      </span>
                    )}
                    {annotation.summary.status_counts.known > 0 && (
                      <span className="text-[9px] px-1 py-0 rounded bg-green-100 dark:bg-green-800/30 text-green-600 dark:text-green-300">
                        {annotation.summary.status_counts.known} known
                      </span>
                    )}
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
