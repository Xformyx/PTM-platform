/**
 * KinaseModuleAnalysis.tsx
 * ────────────────────────────────────────────────────────────────────────────
 * Kinase Module Analysis panel for the TOP N Time-series tab.
 *
 * Core functions:
 *   1. Co-wave Kinase Module Detection — auto-detect PTM groups co-moving
 *   2. Amplitude Rank Preservation Score — Spearman correlation of amplitude ordering
 *   3. Interactive Kinase Lookup — multi-source kinase annotation for selected PTMs
 *   4. Motif-based Kinase Annotation — per-PTM kinase status (known / motif / novel)
 *   5. Concordance Analysis — motif vs known kinase agreement
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
  pmids?: string[];
  uniprot_ac?: string;
}

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  iPTMnet_direct: { label: "iPTMnet", color: "text-blue-600 bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300" },
  iPTMnet: { label: "iPTMnet (cached)", color: "text-blue-600 bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300" },
  rag_kinase_prediction: { label: "LLM Prediction", color: "text-violet-600 bg-violet-100 dark:bg-violet-900/30 dark:text-violet-300" },
  kinase_substrate_pair: { label: "Literature", color: "text-emerald-600 bg-emerald-100 dark:bg-emerald-900/30 dark:text-emerald-300" },
  upstream_regulator: { label: "Upstream Reg.", color: "text-teal-600 bg-teal-100 dark:bg-teal-900/30 dark:text-teal-300" },
  fulltext_analysis: { label: "Text Mining", color: "text-orange-600 bg-orange-100 dark:bg-orange-900/30 dark:text-orange-300" },
  abstract_analysis: { label: "Abstract", color: "text-pink-600 bg-pink-100 dark:bg-pink-900/30 dark:text-pink-300" },
  string_db: { label: "STRING DB", color: "text-cyan-600 bg-cyan-100 dark:bg-cyan-900/30 dark:text-cyan-300" },
  UniProt: { label: "UniProt", color: "text-green-600 bg-green-100 dark:bg-green-900/30 dark:text-green-300" },
};

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

interface InferredAssignment {
  ptm: string;
  gene: string;
  position: string;
  inferred_kinase: string;
  evidence: string;
  motif_predictions: string[];
}

interface NovelCandidate {
  ptm: string;
  gene: string;
  position: string;
  motif_predictions: string[];
  status: string;
}

interface KinaseModule {
  kinase: string;
  sources: string[];
  confirmed_ptms: string[];
  confirmed_count: number;
  inferred_ptms: string[];
  inferred_count: number;
  total_count: number;
}

interface GroupInference {
  anchor_kinases: KinaseModule[];
  inferred_assignments: InferredAssignment[];
  novel_candidates: NovelCandidate[];
  summary_text: string;
}

interface MotifAnnotationResponse {
  order_id: number;
  ptm_count: number;
  annotations: PtmAnnotation[];
  group_inference?: GroupInference;
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
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());
  const [manualSelection, setManualSelection] = useState<Set<string>>(new Set());

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

  // ── Motif annotation call ────────────────────────────────────────────
  const runMotifAnnotation = useCallback(
    async (moduleKey: string, ptms: PtmInfo[]) => {
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
      const result = await api.post<MotifAnnotationResponse>(
        `/orders/${orderId}/motif-kinase-annotation`,
        {
          ptms: selectedPtms.map((p) => ({ gene: p.gene, position: p.position })),
        }
      );
      setManualAnnotation(result);
    } catch (err: any) {
      console.error("Manual annotation failed:", err);
      setMotifError(err?.message || "Motif annotation request failed");
    } finally {
      setManualAnnotationLoading(false);
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
          Co-wave module detection, multi-source kinase annotation (8 sources + motif prediction), and cascade inference.
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
              const annotation = motifAnnotations[moduleKey];
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
                        disabled={isMotifLoading}
                        onClick={() => runMotifAnnotation(moduleKey, mod.ptms)}
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
              Select PTMs below to highlight them in the chart above. Click "Annotate" to collect kinase information from 8 sources (iPTMnet, UniProt, RAG, motif prediction, etc.) and identify novel substrate candidates.
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
            motifAnnotations={motifAnnotations}
            conditions={conditions}
            runMotifAnnotation={runMotifAnnotation}
            motifLoading={motifLoading}
            motifError={motifError}
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
                  {a.known_kinases.slice(0, 4).map((k, i) => {
                    const srcCfg = SOURCE_LABELS[k.source] || { label: k.source, color: "text-gray-600 bg-gray-100 dark:bg-gray-800/30 dark:text-gray-300" };
                    return (
                      <span key={i} className="px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-800/30 text-green-800 dark:text-green-200 inline-flex items-center gap-1">
                        {k.kinase}
                        <span className={`text-[8px] px-1 rounded ${srcCfg.color}`}>{srcCfg.label}</span>
                      </span>
                    );
                  })}
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
              {concordant.length} PTM(s) where motif prediction matches known kinase.{" "}
            </span>
          )}
          {discordant.length > 0 && (
            <span className="text-red-600">
              {discordant.length} PTM(s) where motif prediction differs from known kinase
              — may indicate context-dependent regulation or novel mechanism.{" "}
            </span>
          )}
        </div>
      )}

      {/* ── Group-level Anchor Kinase Inference ── */}
      {annotation.group_inference && annotation.group_inference.anchor_kinases.length > 0 && (
        <GroupInferencePanel inference={annotation.group_inference} />
      )}
      {annotation.group_inference && annotation.group_inference.anchor_kinases.length === 0 && (
        <div className="text-xs text-muted-foreground bg-muted/50 rounded p-2">
          <strong>Group Inference:</strong> No anchor kinases found in this group.
          Run annotation on more PTMs or include PTMs with known kinase information.
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
                        ? (
                          <div className="flex flex-wrap gap-0.5">
                            {a.known_kinases.map((k, ki) => {
                              const srcCfg = SOURCE_LABELS[k.source] || { label: k.source, color: "text-gray-600 bg-gray-100 dark:bg-gray-800/30" };
                              return (
                                <span key={ki} className="inline-flex items-center gap-0.5">
                                  <span className="font-medium">{k.kinase}</span>
                                  <span className={`text-[8px] px-0.5 rounded ${srcCfg.color}`}>{srcCfg.label}</span>
                                  {ki < a.known_kinases.length - 1 && <span className="text-muted-foreground">,</span>}
                                </span>
                              );
                            })}
                          </div>
                        )
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

// ── Group Inference Panel ────────────────────────────────────────────────────────

function GroupInferencePanel({ inference }: { inference: GroupInference }) {
  const { anchor_kinases, inferred_assignments, novel_candidates, summary_text } = inference;

  return (
    <div className="space-y-3 border rounded-lg p-3 bg-gradient-to-br from-blue-50/50 to-indigo-50/50 dark:from-blue-950/20 dark:to-indigo-950/20">
      {/* Header */}
      <div className="flex items-center gap-2">
        <GitMerge className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        <p className="text-xs font-semibold text-blue-700 dark:text-blue-300">
          Group-level Kinase Inference
        </p>
      </div>

      {/* Summary text */}
      <p className="text-[11px] text-blue-600 dark:text-blue-300 bg-blue-100/50 dark:bg-blue-900/30 rounded p-2">
        {summary_text}
      </p>

      {/* Per-kinase module cards */}
      {anchor_kinases.map((km) => (
        <div
          key={km.kinase}
          className="border rounded-lg p-3 bg-white/70 dark:bg-gray-900/50 space-y-2"
        >
          {/* Kinase header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-yellow-500" />
              <span className="text-sm font-bold text-foreground">{km.kinase}</span>
              <Badge variant="outline" className="text-[10px] h-5">
                {km.total_count} PTMs total
              </Badge>
            </div>
            <div className="flex gap-1">
              {km.sources.map((s) => {
                const srcCfg = SOURCE_LABELS[s] || { label: s, color: "text-gray-600 bg-gray-100 dark:bg-gray-800/30 dark:text-gray-300" };
                return (
                  <span key={s} className={`text-[8px] px-1.5 py-0.5 rounded ${srcCfg.color}`}>
                    {srcCfg.label}
                  </span>
                );
              })}
            </div>
          </div>

          {/* Confirmed PTMs */}
          <div className="space-y-1">
            <p className="text-[10px] font-medium text-green-700 dark:text-green-400 flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" />
              Confirmed ({km.confirmed_count})
            </p>
            <div className="flex flex-wrap gap-1">
              {km.confirmed_ptms.map((ptm) => (
                <span
                  key={ptm}
                  className="px-2 py-0.5 rounded-full text-[10px] bg-green-100 dark:bg-green-800/40 text-green-700 dark:text-green-300 border border-green-300 dark:border-green-600"
                >
                  <CheckCircle2 className="h-2.5 w-2.5 inline mr-0.5" />
                  {ptm}
                </span>
              ))}
            </div>
          </div>

          {/* Inferred PTMs */}
          {km.inferred_count > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-blue-700 dark:text-blue-400 flex items-center gap-1">
                <ArrowRight className="h-3 w-3" />
                Inferred by co-wave + motif match ({km.inferred_count})
              </p>
              <div className="flex flex-wrap gap-1">
                {km.inferred_ptms.map((ptm) => {
                  const ia = inferred_assignments.find((a) => a.ptm === ptm);
                  return (
                    <span
                      key={ptm}
                      className="px-2 py-0.5 rounded-full text-[10px] bg-blue-100 dark:bg-blue-800/40 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-600 cursor-help"
                      title={ia?.evidence || ""}
                    >
                      <ArrowRight className="h-2.5 w-2.5 inline mr-0.5" />
                      {ptm}
                    </span>
                  );
                })}
              </div>
              {/* Evidence details for inferred */}
              <div className="mt-1 space-y-0.5">
                {inferred_assignments
                  .filter((ia) => ia.inferred_kinase.toUpperCase() === km.kinase.toUpperCase())
                  .map((ia) => (
                    <p key={ia.ptm} className="text-[9px] text-muted-foreground ml-4">
                      {ia.ptm}: {ia.evidence}
                    </p>
                  ))}
              </div>
            </div>
          )}
        </div>
      ))}

      {/* Novel Candidates (not matching any anchor) */}
      {novel_candidates.length > 0 && (
        <div className="border rounded-lg p-3 bg-purple-50/50 dark:bg-purple-950/20 space-y-2">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-purple-500" />
            <span className="text-xs font-semibold text-purple-700 dark:text-purple-300">
              Novel Candidates — No Anchor Kinase Match ({novel_candidates.length})
            </span>
          </div>
          <p className="text-[10px] text-purple-600 dark:text-purple-300">
            These PTMs share the same temporal pattern but their motif predictions
            do not match any confirmed kinase in the group. They may be substrates of
            an uncharacterized kinase or a kinase not yet in the databases.
          </p>
          <div className="flex flex-wrap gap-1">
            {novel_candidates.map((nc) => (
              <span
                key={nc.ptm}
                className="px-2 py-0.5 rounded-full text-[10px] bg-purple-100 dark:bg-purple-800/40 text-purple-700 dark:text-purple-300 border border-purple-300 dark:border-purple-600 cursor-help"
                title={nc.motif_predictions.length > 0 ? `Motif: ${nc.motif_predictions.join(", ")}` : "No motif prediction"}
              >
                <Sparkles className="h-2.5 w-2.5 inline mr-0.5" />
                {nc.ptm}
                {nc.motif_predictions.length > 0 && (
                  <span className="opacity-60 ml-1">({nc.motif_predictions.slice(0, 2).join(", ")})</span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


// ── Cascade View ─────────────────────────────────────────────────────────────

/** Collect all unique kinases from an annotation (known + motif + group inference) */
function collectAllKinases(annotation: MotifAnnotationResponse | undefined): { kinase: string; source: string }[] {
  if (!annotation) return [];
  const seen = new Set<string>();
  const result: { kinase: string; source: string }[] = [];
  for (const a of annotation.annotations) {
    for (const k of a.known_kinases) {
      const key = k.kinase.toUpperCase();
      if (!seen.has(key)) { seen.add(key); result.push({ kinase: k.kinase, source: k.source }); }
    }
    for (const m of a.motif_predicted_kinases) {
      const key = m.kinase_family.toUpperCase();
      if (!seen.has(key)) { seen.add(key); result.push({ kinase: m.kinase_family, source: "motif_prediction" }); }
    }
  }
  if (annotation.group_inference) {
    for (const ak of annotation.group_inference.anchor_kinases) {
      const key = ak.kinase.toUpperCase();
      if (!seen.has(key)) { seen.add(key); result.push({ kinase: ak.kinase, source: ak.sources[0] || "group_inference" }); }
    }
  }
  return result;
}

function CascadeView({
  modules,
  motifAnnotations,
  conditions,
  runMotifAnnotation,
  motifLoading,
  motifError,
}: {
  modules: CoWaveModule[];
  motifAnnotations: Record<string, MotifAnnotationResponse>;
  conditions: string[];
  runMotifAnnotation: (moduleKey: string, ptms: PtmInfo[]) => void;
  motifLoading: string | null;
  motifError: string | null;
}) {
  const [expandedCascade, setExpandedCascade] = useState<Set<string>>(new Set());

  const toggleCascadeExpand = (key: string) => {
    setExpandedCascade((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

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

  // ── Build cross-module kinase map ──
  const kinaseModuleMap: Record<string, { modules: string[]; sources: Set<string> }> = {};
  for (const mod of sortedModules) {
    const moduleKey = `module_${mod.id}`;
    const annotation = motifAnnotations[moduleKey];

    // From annotation (8 sources + motif + group inference)
    const allKinases = collectAllKinases(annotation);
    for (const k of allKinases) {
      const key = k.kinase.toUpperCase();
      if (!kinaseModuleMap[key]) kinaseModuleMap[key] = { modules: [], sources: new Set() };
      if (!kinaseModuleMap[key].modules.includes(mod.label)) kinaseModuleMap[key].modules.push(mod.label);
      kinaseModuleMap[key].sources.add(k.source);
    }
  }

  // Shared kinases (appear in 2+ modules)
  const sharedKinases = Object.entries(kinaseModuleMap)
    .filter(([, v]) => v.modules.length >= 2)
    .sort((a, b) => b[1].modules.length - a[1].modules.length);

  // Find shared kinases between adjacent modules for arrow labels
  const getSharedBetween = (modA: CoWaveModule, modB: CoWaveModule): string[] => {
    const keyA = `module_${modA.id}`;
    const keyB = `module_${modB.id}`;
    const kinasesA = new Set<string>();
    const kinasesB = new Set<string>();

    const addFromAnnotation = (ann: MotifAnnotationResponse | undefined, target: Set<string>) => {
      if (!ann) return;
      for (const k of collectAllKinases(ann)) target.add(k.kinase.toUpperCase());
    };

    addFromAnnotation(motifAnnotations[keyA], kinasesA);
    addFromAnnotation(motifAnnotations[keyB], kinasesB);

    return [...kinasesA].filter((k) => kinasesB.has(k));
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">
        Proposed cascade order based on peak timing. Run <strong>Annotate</strong> on each module to collect kinase information from all 8 sources (iPTMnet, UniProt, RAG, motif prediction, etc.).
      </p>

      {/* ── Cascade Flow Diagram ── */}
      <div className="flex items-start gap-0 overflow-x-auto pb-2">
        {sortedModules.map((mod, idx) => {
          const moduleKey = `module_${mod.id}`;
          const annotation = motifAnnotations[moduleKey];
          const isExpanded = expandedCascade.has(moduleKey);
          const isMotifLoading = motifLoading === moduleKey;

          // All kinases from all sources for this module
          const allKinases = collectAllKinases(annotation);

          // Merge kinases with source tracking
          const mergedKinases: { kinase: string; sources: string[] }[] = [];
          const mergedSeen = new Set<string>();
          for (const k of allKinases) {
            const key = k.kinase.toUpperCase();
            if (!mergedSeen.has(key)) {
              mergedSeen.add(key);
              mergedKinases.push({ kinase: k.kinase, sources: [k.source] });
            } else {
              const existing = mergedKinases.find((m) => m.kinase.toUpperCase() === key);
              if (existing && !existing.sources.includes(k.source)) existing.sources.push(k.source);
            }
          }

          // Shared kinases with next module
          const sharedWithNext = idx < sortedModules.length - 1
            ? getSharedBetween(mod, sortedModules[idx + 1])
            : [];

          return (
            <div key={moduleKey} className="flex items-start">
              <div className="rounded-lg border bg-card p-3 min-w-[220px] max-w-[280px] space-y-2">
                {/* Module header */}
                <div className="flex items-center justify-between">
                  <button
                    onClick={() => toggleCascadeExpand(moduleKey)}
                    className="flex items-center gap-1 text-xs font-medium hover:text-primary"
                  >
                    {isExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    {mod.label}
                  </button>
                  <div className="flex items-center gap-1">
                    <Badge variant="outline" className="text-[9px]">
                      {mod.ptms.length} PTMs
                    </Badge>
                    <Badge variant="outline" className="text-[9px] text-muted-foreground">
                      Peak: {mod.peakCondition}
                    </Badge>
                  </div>
                </div>

                {/* Quick stats */}
                <div className="text-[10px] text-muted-foreground flex gap-2">
                  <span>Amp: {mod.avgAmplitude.toFixed(2)}</span>
                  {mod.spearmanScore !== null && <span>ρ={mod.spearmanScore.toFixed(2)}</span>}
                </div>

                {/* ── Integrated Kinase Summary (all sources) ── */}
                {mergedKinases.length > 0 ? (
                  <div className="space-y-1">
                    <div className="text-[10px] font-medium text-muted-foreground">Kinases (all sources):</div>
                    <div className="flex flex-wrap gap-1">
                      {mergedKinases.slice(0, 6).map((mk) => {
                        const isShared = kinaseModuleMap[mk.kinase.toUpperCase()]?.modules.length >= 2;
                        const isMultiSource = mk.sources.length >= 2;
                        return (
                          <span
                            key={mk.kinase}
                            className={`text-[9px] px-1.5 py-0.5 rounded inline-flex items-center gap-0.5 ${
                              isMultiSource
                                ? "bg-green-100 dark:bg-green-800/30 text-green-700 dark:text-green-300 border border-green-400"
                                : isShared
                                ? "bg-blue-100 dark:bg-blue-800/30 text-blue-700 dark:text-blue-300 border border-blue-300"
                                : "bg-muted text-foreground"
                            }`}
                            title={`Sources: ${mk.sources.map((s) => SOURCE_LABELS[s]?.label || s).join(", ")}${isShared ? " | Shared across modules" : ""}${isMultiSource ? " | Multi-source validated" : ""}`}
                          >
                            {isMultiSource && <CheckCircle2 className="h-2.5 w-2.5 text-green-500" />}
                            {mk.kinase}
                            <span className="opacity-50 text-[8px]">({mk.sources.length})</span>
                          </span>
                        );
                      })}
                      {mergedKinases.length > 6 && (
                        <span className="text-[9px] text-muted-foreground">+{mergedKinases.length - 6}</span>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="text-[10px] text-muted-foreground italic">
                    No kinase data yet — click Annotate below
                  </div>
                )}

                {/* Annotation status badges */}
                {annotation && (
                  <div className="flex gap-1 flex-wrap">
                    {annotation.summary.status_counts.known > 0 && (
                      <span className="text-[9px] px-1 py-0 rounded bg-green-100 dark:bg-green-800/30 text-green-600 dark:text-green-300">
                        <ShieldCheck className="h-2.5 w-2.5 inline mr-0.5" />{annotation.summary.status_counts.known} known
                      </span>
                    )}
                    {annotation.summary.status_counts.motif_only > 0 && (
                      <span className="text-[9px] px-1 py-0 rounded bg-amber-100 dark:bg-amber-800/30 text-amber-600 dark:text-amber-300">
                        <FlaskConical className="h-2.5 w-2.5 inline mr-0.5" />{annotation.summary.status_counts.motif_only} motif
                      </span>
                    )}
                    {annotation.summary.status_counts.novel_candidate > 0 && (
                      <span className="text-[9px] px-1 py-0 rounded bg-purple-100 dark:bg-purple-800/30 text-purple-600 dark:text-purple-300">
                        <Sparkles className="h-2.5 w-2.5 inline mr-0.5" />{annotation.summary.status_counts.novel_candidate} novel
                      </span>
                    )}
                  </div>
                )}

                {/* Action button */}
                <div className="flex gap-1 pt-1">
                  <Button
                    variant="default"
                    size="sm"
                    className="text-[9px] h-5 px-1.5"
                    disabled={isMotifLoading}
                    onClick={() => runMotifAnnotation(moduleKey, mod.ptms)}
                  >
                    {isMotifLoading ? <Loader2 className="h-2.5 w-2.5 animate-spin mr-0.5" /> : <FlaskConical className="h-2.5 w-2.5 mr-0.5" />}
                    Annotate
                  </Button>
                </div>

                {/* Loading / error indicators */}
                {isMotifLoading && (
                  <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" /> Annotating {mod.ptms.length} PTMs...
                  </div>
                )}
                {motifError && motifLoading === null && (
                  <div className="text-[10px] text-red-500">{motifError}</div>
                )}

                {/* ── Expanded Detail Panel ── */}
                {isExpanded && (
                  <div className="space-y-2 pt-1 border-t">
                    {/* PTM list with status */}
                    <div className="flex flex-wrap gap-0.5">
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
                            className={`px-1.5 py-0.5 rounded text-[9px] flex items-center gap-0.5 border ${
                              statusCfg ? `${statusCfg.bg} ${statusCfg.border} ${statusCfg.color}` : "bg-muted"
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
                                  }`
                                : p.label
                            }
                          >
                            {StatusIcon && <StatusIcon className="h-2.5 w-2.5" />}
                            {p.label}
                          </span>
                        );
                      })}
                    </div>

                    {/* Full Motif Annotation Panel */}
                    {annotation && <MotifAnnotationPanel annotation={annotation} />}

                  </div>
                )}
              </div>

              {/* Arrow between modules with shared kinases */}
              {idx < sortedModules.length - 1 && (
                <div className="flex flex-col items-center px-2 min-w-[60px] pt-6">
                  <ArrowRight className="h-5 w-5 text-muted-foreground" />
                  {sharedWithNext.length > 0 && (
                    <div className="flex flex-col items-center gap-0.5 mt-1">
                      {sharedWithNext.slice(0, 3).map((k) => (
                        <span key={k} className="text-[8px] px-1 py-0 rounded bg-blue-100 dark:bg-blue-800/30 text-blue-600 dark:text-blue-300 whitespace-nowrap">
                          {k}
                        </span>
                      ))}
                      {sharedWithNext.length > 3 && (
                        <span className="text-[8px] text-muted-foreground">+{sharedWithNext.length - 3}</span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Cross-Module Kinase Map ── */}
      {sharedKinases.length > 0 && (
        <div className="bg-gradient-to-br from-blue-50/50 to-indigo-50/50 dark:from-blue-950/20 dark:to-indigo-950/20 rounded-lg p-3 space-y-2">
          <div className="flex items-center gap-1 text-xs font-medium">
            <GitMerge className="h-3.5 w-3.5 text-blue-500" />
            Cross-Module Kinase Map
            <span className="text-muted-foreground font-normal">— kinases shared across 2+ modules</span>
          </div>
          <div className="space-y-1">
            {sharedKinases.slice(0, 10).map(([kinase, data]) => {
              const srcLabels = [...data.sources].map((s) => SOURCE_LABELS[s]?.label || s);
              return (
                <div key={kinase} className="flex items-center gap-2 text-[10px]">
                  <span className="font-medium min-w-[70px] text-blue-700 dark:text-blue-300">{kinase}</span>
                  <div className="flex gap-1">
                    {data.modules.map((m) => (
                      <span key={m} className="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-800/30 text-blue-600 dark:text-blue-300">
                        {m}
                      </span>
                    ))}
                  </div>
                  <span className="text-muted-foreground">via {srcLabels.join(", ")}</span>
                </div>
              );
            })}
            {sharedKinases.length > 10 && (
              <div className="text-[10px] text-muted-foreground">...and {sharedKinases.length - 10} more shared kinases</div>
            )}
          </div>
        </div>
      )}

      {/* ── Cascade Kinase Flow Summary ── */}
      {sortedModules.length >= 2 && (
        <div className="bg-muted/50 rounded-lg p-3 space-y-2">
          <div className="text-xs font-medium">Cascade Kinase Flow Summary</div>
          <div className="text-[10px] text-muted-foreground">
            <strong>Temporal order:</strong>{" "}
            {sortedModules.map((m) => {
              const moduleKey = `module_${m.id}`;
              const annotation = motifAnnotations[moduleKey];
              const topKinases: string[] = [];
              // Collect from all annotation sources
              if (annotation) {
                const known = annotation.annotations.flatMap((a) => a.known_kinases.map((k) => k.kinase));
                const unique = [...new Set(known.map((k) => k.toUpperCase()))];
                topKinases.push(...unique.slice(0, 2));
                // Fill with motif predicted if needed
                if (topKinases.length < 2) {
                  const motifPred = annotation.annotations.flatMap((a) => a.motif_predicted_kinases.map((m) => m.kinase_family));
                  const uniqueMotif = [...new Set(motifPred.map((k) => k.toUpperCase()))];
                  for (const mk of uniqueMotif) {
                    if (!topKinases.includes(mk)) {
                      topKinases.push(mk);
                      if (topKinases.length >= 2) break;
                    }
                  }
                }
              }
              return `${m.label}${topKinases.length > 0 ? ` [${topKinases.join(", ")}]` : ""}`;
            }).join(" → ")}
          </div>
          <div className="text-[10px] text-muted-foreground">
            <strong>Shared regulators:</strong>{" "}
            {sharedKinases.length > 0
              ? sharedKinases.slice(0, 5).map(([k, v]) => `${k} (${v.modules.join("+")})`).join(", ")
              : "None detected — run Annotate on all modules to discover shared kinases"}
          </div>
          {sharedKinases.length === 0 && (
            <div className="text-[10px] text-amber-600 dark:text-amber-400">
              Tip: Click "Annotate" on each module card above to collect kinase data from iPTMnet, UniProt, RAG enrichment, motif prediction, and more.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
