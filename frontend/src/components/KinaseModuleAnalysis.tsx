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
  Clock,
  Timer,
  Network,
  TrendingUp,
  Layers,
  GitBranch,
  Link2,
  Scissors,
  Activity,
  Boxes,
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
  control_pseudocount_used?: boolean;
  q_value?: number | null;
}

interface PtmInfo {
  gene: string;
  position: string;
  label: string;
  activity_class?: "de_novo" | "regulated" | "minor";
}

interface CoWaveModule {
  id: number;
  label: string;
  ptms: PtmInfo[];
  peakCondition: string;
  avgAmplitude: number;
  amplitudeRanking: number[];
  spearmanScore: number | null;
  // v9.27: activity class breakdown
  activity_class_counts: { de_novo: number; regulated: number; minor: number };
  dominant_activity_class: "de_novo" | "regulated" | "minor";
}

// ── Motif Annotation Types ──────────────────────────────────────────────────

interface MotifPredictedKinase {
  kinase_family: string;
  canonical_family?: string;
  display_family?: string;
  motif: string;
  source: string;
}

interface KnownKinase {
  kinase: string;
  canonical_name?: string;
  display_name?: string;
  original_name?: string;
  merged_sources?: string[];
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
  inferred_canonical?: string;
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
  canonical?: string;
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

// ── Global Kinase Module Types ──────────────────────────────────────────────

interface GlobalModuleMember {
  key: string;
  gene: string;
  position: string;
  membership: "confirmed" | "inferred";
  evidence: string;
}

interface CowaveOverlap {
  cowave_id: number;
  cowave_label: string;
  shared_ptms: string[];
}

interface GlobalKinaseModule {
  kinase: string;
  canonical: string;
  sources: string[];
  source_count: number;
  members: GlobalModuleMember[];
  confirmed_count: number;
  inferred_count: number;
  total_count: number;
  cowave_overlap: CowaveOverlap[];
}

interface CowaveCrossEntry {
  cowave_id: number;
  cowave_label: string;
  total_ptms: number;
  overlapping_kinases: {
    kinase: string;
    canonical: string;
    shared_count: number;
    shared_ptms: string[];
  }[];
}

// ── Temporal Cascade Types ─────────────────────────────────────────────────

interface TemporalCascadeKinase {
  kinase: string;
  canonical: string;
  sources: string[];
  ptm_count: number;
  confirmed: number;
  inferred: number;
}

interface TemporalCascadeTimepoint {
  condition: string;
  minutes: number;
  ptm_count: number;
  cowave_ids: number[];
  cowave_labels: string[];
  kinases: TemporalCascadeKinase[];
}

interface KinaseActivityEntry {
  kinase: string;
  canonical: string;
  sources: string[];
  timepoints: { condition: string; ptm_count: number; confirmed: number; inferred: number }[];
}

interface CascadeFlowEntry {
  from: string;
  to: string;
  shared_kinases: string[];
  new_kinases: string[];
  lost_kinases: string[];
}

interface TemporalCascade {
  timepoints: TemporalCascadeTimepoint[];
  kinase_activity: KinaseActivityEntry[];
  cascade_flow: CascadeFlowEntry[];
}

// ── Non-PTM Effector Types ──────────────────────────────────────────────────
interface EffectorTemporalEntry {
  condition: string;
  protein_log2fc: number;
}
interface EffectorConnectedSubstrate {
  gene: string;
  kinases: string[];
  source: string;
  substrate_peak_fc?: number;
  substrate_peak_cond?: string;
  concordant?: boolean;
}
interface EffectorProtein {
  gene: string;
  data_type: string;
  connected_substrates: EffectorConnectedSubstrate[];
  temporal_profile: EffectorTemporalEntry[];
  max_abs_fc: number;
  peak_condition: string;
  peak_fc: number;
  peak_minutes?: number;
  sources: string[];
  // Evidence scoring (v9.34.2)
  concordant_count?: number;
  discordant_count?: number;
  directionality?: "concordant" | "discordant" | "mixed" | "unknown";
  time_lag_minutes?: number | null;
  evidence_strength?: "strong" | "moderate" | "weak" | "expression_only";
  evidence_score?: number;
}

interface GlobalKinaseModuleResponse {
  order_id: number;
  kinase_modules: GlobalKinaseModule[];
  unassigned_ptms: { key: string; gene: string; position: string; motif_families: string[] }[];
  annotation_details: PtmAnnotation[];
  summary: {
    total_ptms: number;
    total_kinase_modules: number;
    total_confirmed: number;
    total_inferred: number;
    total_unassigned: number;
    status_counts: Record<string, number>;
    top_kinases: { kinase: string; canonical: string; total: number }[];
  };
  cowave_cross_analysis: Record<string, CowaveCrossEntry>;
  temporal_cascade?: TemporalCascade;
  effector_proteins?: EffectorProtein[];
  wave_kinase_profile?: WaveKinaseProfile[];
}

interface WaveKinaseProfile {
  wave_id: number;
  wave_label: string;
  peak_minutes: number;
  tier: string;
  kinases: { canonical: string; kinase: string; ptm_count: number; is_anchor: boolean }[];
  cascade_context: string;
  suggested_receptors: string[];
}

// ── Kinase Module Colors ───────────────────────────────────────────────────

const KINASE_MODULE_COLORS = [
  { bg: "bg-blue-100 dark:bg-blue-900/30", border: "border-blue-400", text: "text-blue-700 dark:text-blue-300", hex: "#3b82f6" },
  { bg: "bg-rose-100 dark:bg-rose-900/30", border: "border-rose-400", text: "text-rose-700 dark:text-rose-300", hex: "#f43f5e" },
  { bg: "bg-emerald-100 dark:bg-emerald-900/30", border: "border-emerald-400", text: "text-emerald-700 dark:text-emerald-300", hex: "#10b981" },
  { bg: "bg-amber-100 dark:bg-amber-900/30", border: "border-amber-400", text: "text-amber-700 dark:text-amber-300", hex: "#f59e0b" },
  { bg: "bg-violet-100 dark:bg-violet-900/30", border: "border-violet-400", text: "text-violet-700 dark:text-violet-300", hex: "#8b5cf6" },
  { bg: "bg-cyan-100 dark:bg-cyan-900/30", border: "border-cyan-400", text: "text-cyan-700 dark:text-cyan-300", hex: "#06b6d4" },
  { bg: "bg-pink-100 dark:bg-pink-900/30", border: "border-pink-400", text: "text-pink-700 dark:text-pink-300", hex: "#ec4899" },
  { bg: "bg-teal-100 dark:bg-teal-900/30", border: "border-teal-400", text: "text-teal-700 dark:text-teal-300", hex: "#14b8a6" },
];

interface InferredReceptor {
  name: string;
  receptor_class: string;
  downstream_ptm_count: number;
  downstream_ptms: string[];
  via_kinases?: string[];
  pathway?: string;
  signaling_pathway?: string;
  source?: string;
  has_receptor_specific_db?: boolean;
  uniqueness_score?: number;
  unique_kinases?: string[];
  shared_kinases?: string[];
  kinase_group_id?: string | null;
  kinase_group_members?: string[];
  unique_ptms?: string[];
  shared_ptms?: string[];
  unique_ptm_ratio?: number;
}

interface KinaseModuleAnalysisProps {
  orderId: number;
  vectorData: PtmTimeSeriesRow[];
  topNPtms: PtmInfo[];
  checkedPtms: Record<string, boolean>;
  conditions: string[];
  onSelectPtms?: (keys: string[]) => void;
  highlightedPtmKeys?: Set<string>; // keys currently highlighted in chart (gene_position)
  ptmType?: string; // v9.14: 'phosphorylation' | 'ubiquitylation'
  highlightedKinase?: string | null; // v9.21: from receptor panel click
  inferredReceptors?: InferredReceptor[]; // v9.21: for Signal Flow tab + receptor badges
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
  // v9.27: compute activity_class per PTM from vectorData
  const ptmActivityClassMap = new Map<string, "de_novo" | "regulated" | "minor">();
  ptms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    const series = conditions.map((cond) => {
      const row = vectorData.find(
        (r) => r.gene === p.gene && r.position === p.position && r.condition === cond
      );
      return row?.value ?? 0;
    });
    ptmSeries.set(key, series);

    // Determine activity_class: check all rows for this PTM across conditions
    const rows = vectorData.filter((r) => r.gene === p.gene && r.position === p.position);
    const isDenovo = rows.some((r) => r.control_pseudocount_used === true);
    const maxAbsFC = Math.max(...series.map(Math.abs));
    const qValues = rows.map((r) => r.q_value).filter((v): v is number => v != null && !isNaN(v));
    const minQValue = qValues.length > 0 ? Math.min(...qValues) : null;
    const hasQValue = minQValue != null;
    let actClass: "de_novo" | "regulated" | "minor";
    if (isDenovo) {
      actClass = "de_novo";
    } else if (hasQValue) {
      // q_value available: Regulated = |Log2FC| >= 1.0 AND q_value < 0.05
      actClass = (minQValue < 0.05 && maxAbsFC >= 1.0) ? "regulated" : "minor";
    } else {
      // Fallback (old data without q_value): use maxAbsChange > 0.8
      const baselineVal = series[0] ?? 0;
      const maxAbsChange = Math.max(...series.map((v) => Math.abs(v - baselineVal)));
      actClass = maxAbsChange > 0.8 ? "regulated" : "minor";
    }
    ptmActivityClassMap.set(key, actClass);
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
    // Attach activity_class to PtmInfo
    peakGroups.get(peakCond)!.push({ ...p, activity_class: ptmActivityClassMap.get(key) ?? "minor" });
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

    // v9.27: activity class statistics
    const class_counts = { de_novo: 0, regulated: 0, minor: 0 };
    groupPtms.forEach((p) => {
      const ac = p.activity_class ?? "minor";
      class_counts[ac] = (class_counts[ac] ?? 0) + 1;
    });
    const dominant_activity_class: "de_novo" | "regulated" | "minor" =
      class_counts.de_novo > 0 ? "de_novo" :
      class_counts.regulated > 0 ? "regulated" : "minor";

    modules.push({
      id: moduleId,
      label: `Module ${moduleId} (peak: ${peakCond})`,
      ptms: groupPtms,
      peakCondition: peakCond,
      avgAmplitude,
      amplitudeRanking,
      spearmanScore,
      activity_class_counts: class_counts,
      dominant_activity_class,
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
  highlightedPtmKeys,
  ptmType = "phosphorylation",
  highlightedKinase,
  inferredReceptors = [],
}: KinaseModuleAnalysisProps) {
  const isUbi = ptmType.toLowerCase().includes("ubiquityl") || ptmType.toLowerCase().includes("ubiquitin");
  const [activeTab, setActiveTab] = useState<"cowave" | "lookup" | "cascade" | "kinaseModules" | "signalFlow">("cowave");
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());
  const [manualSelection, setManualSelection] = useState<Set<string>>(new Set());

  // ── Motif annotation state ──────────────────────────────────────────────
  const [motifAnnotations, setMotifAnnotations] = useState<Record<string, MotifAnnotationResponse>>({});
  const [motifLoading, setMotifLoading] = useState<string | null>(null);
  const [motifError, setMotifError] = useState<string | null>(null);

  // ── Manual (Kinase Lookup) annotation state ────────────────────────────
  const [manualAnnotation, setManualAnnotation] = useState<MotifAnnotationResponse | null>(null);
  const [manualAnnotationLoading, setManualAnnotationLoading] = useState(false);

  // ── Global Kinase Module state ─────────────────────────────────────────
  const [globalKinaseResult, setGlobalKinaseResult] = useState<GlobalKinaseModuleResponse | null>(null);
  const [globalKinaseLoading, setGlobalKinaseLoading] = useState(false);
  const [globalKinaseError, setGlobalKinaseError] = useState<string | null>(null);
  const [globalKinaseBatchProgress, setGlobalKinaseBatchProgress] = useState<{ current: number; total: number; phase: string } | null>(null);

  // ── Receptor→Kinase reverse mapping (v9.21) ─────────────────────────────
  // Maps canonical kinase name (uppercase) → list of receptor names that route through it
  const kinaseToReceptors = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const rec of inferredReceptors) {
      for (const k of (rec.via_kinases || [])) {
        const key = k.toUpperCase();
        if (!map[key]) map[key] = [];
        if (!map[key].includes(rec.name)) map[key].push(rec.name);
      }
    }
    return map;
  }, [inferredReceptors]);

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

  // ── Global Kinase Module annotation call (batched to avoid 524 timeout) ─
  const GLOBAL_ANNOTATE_BATCH_SIZE = 150; // PTMs per batch (keeps each call < 60s)

  const runGlobalKinaseModules = useCallback(async () => {
    setGlobalKinaseLoading(true);
    setGlobalKinaseError(null);
    setGlobalKinaseBatchProgress(null);
    try {
      const allPtms = checkedPtmList.length > 0 ? checkedPtmList : topNPtms;
      const cowaveModulesPayload = coWaveModules.map((m) => ({
        id: m.id,
        label: m.label,
        ptms: m.ptms.map((p) => `${p.gene}_${p.position}`),
      }));

      // If PTM count is small enough, do a single call (no batching needed)
      if (allPtms.length <= GLOBAL_ANNOTATE_BATCH_SIZE) {
        setGlobalKinaseBatchProgress({ current: 1, total: 1, phase: "Annotating..." });
        const result = await api.post<GlobalKinaseModuleResponse>(
          `/orders/${orderId}/global-kinase-modules`,
          {
            ptms: allPtms.map((p) => ({ gene: p.gene, position: p.position })),
            cowave_modules: cowaveModulesPayload,
          }
        );
        setGlobalKinaseResult(result);
        setActiveTab("kinaseModules");
        return;
      }

      // ── Batched processing ─────────────────────────────────────────────
      const batches: { gene: string; position: string }[][] = [];
      const ptmPayload = allPtms.map((p) => ({ gene: p.gene, position: p.position }));
      for (let i = 0; i < ptmPayload.length; i += GLOBAL_ANNOTATE_BATCH_SIZE) {
        batches.push(ptmPayload.slice(i, i + GLOBAL_ANNOTATE_BATCH_SIZE));
      }

      const totalBatches = batches.length;
      const batchResults: GlobalKinaseModuleResponse[] = [];

      for (let bIdx = 0; bIdx < totalBatches; bIdx++) {
        setGlobalKinaseBatchProgress({
          current: bIdx + 1,
          total: totalBatches,
          phase: `Batch ${bIdx + 1}/${totalBatches} (${batches[bIdx].length} PTMs)`,
        });

        const batchResult = await api.post<GlobalKinaseModuleResponse>(
          `/orders/${orderId}/global-kinase-modules`,
          {
            ptms: batches[bIdx],
            cowave_modules: cowaveModulesPayload,
          }
        );
        batchResults.push(batchResult);
      }

      // ── Merge batch results ────────────────────────────────────────────
      setGlobalKinaseBatchProgress({ current: totalBatches, total: totalBatches, phase: "Merging results..." });

      // Merge kinase_modules: combine by canonical name
      const mergedModulesMap = new Map<string, GlobalKinaseModule>();
      for (const br of batchResults) {
        for (const km of br.kinase_modules) {
          const existing = mergedModulesMap.get(km.canonical);
          if (!existing) {
            mergedModulesMap.set(km.canonical, { ...km });
          } else {
            // Merge members (deduplicate by key)
            const existingKeys = new Set(existing.members.map((m) => m.key));
            for (const m of km.members) {
              if (!existingKeys.has(m.key)) {
                existing.members.push(m);
                existingKeys.add(m.key);
              }
            }
            // Merge sources
            const srcSet = new Set([...existing.sources, ...km.sources]);
            existing.sources = Array.from(srcSet);
            existing.source_count = existing.sources.length;
            // Recount
            existing.confirmed_count = existing.members.filter((m) => m.membership === "confirmed").length;
            existing.inferred_count = existing.members.filter((m) => m.membership === "inferred").length;
            existing.total_count = existing.members.length;
            // Merge cowave_overlap
            const existingCwIds = new Set(existing.cowave_overlap.map((c) => c.cowave_id));
            for (const cw of km.cowave_overlap) {
              if (!existingCwIds.has(cw.cowave_id)) {
                existing.cowave_overlap.push(cw);
              } else {
                const existCw = existing.cowave_overlap.find((c) => c.cowave_id === cw.cowave_id);
                if (existCw) {
                  const sharedSet = new Set([...existCw.shared_ptms, ...cw.shared_ptms]);
                  existCw.shared_ptms = Array.from(sharedSet);
                }
              }
            }
          }
        }
      }
      const mergedModules = Array.from(mergedModulesMap.values())
        .sort((a, b) => b.total_count - a.total_count);

      // Merge unassigned_ptms (deduplicate by key, remove those now assigned)
      const assignedKeys = new Set<string>();
      for (const km of mergedModules) {
        for (const m of km.members) assignedKeys.add(m.key);
      }
      const mergedUnassigned: GlobalKinaseModuleResponse["unassigned_ptms"] = [];
      const seenUnassigned = new Set<string>();
      for (const br of batchResults) {
        for (const ua of br.unassigned_ptms) {
          if (!assignedKeys.has(ua.key) && !seenUnassigned.has(ua.key)) {
            mergedUnassigned.push(ua);
            seenUnassigned.add(ua.key);
          }
        }
      }

      // Merge annotation_details (deduplicate by gene+position)
      const mergedAnnotations: GlobalKinaseModuleResponse["annotation_details"] = [];
      const seenAnnot = new Set<string>();
      for (const br of batchResults) {
        for (const ann of br.annotation_details) {
          const k = `${ann.gene}_${ann.position}`;
          if (!seenAnnot.has(k)) {
            mergedAnnotations.push(ann);
            seenAnnot.add(k);
          }
        }
      }

      // Merge summary
      const mergedSummary: GlobalKinaseModuleResponse["summary"] = {
        total_ptms: mergedAnnotations.length,
        total_kinase_modules: mergedModules.length,
        total_confirmed: mergedModules.reduce((s, km) => s + km.confirmed_count, 0),
        total_inferred: mergedModules.reduce((s, km) => s + km.inferred_count, 0),
        total_unassigned: mergedUnassigned.length,
        status_counts: { known: 0, motif_only: 0, novel_candidate: 0 },
        top_kinases: mergedModules.slice(0, 10).map((km) => ({
          kinase: km.kinase, canonical: km.canonical, total: km.total_count,
        })),
      };
      for (const ann of mergedAnnotations) {
        const st = (ann as any).status || "novel_candidate";
        mergedSummary.status_counts[st] = (mergedSummary.status_counts[st] || 0) + 1;
      }

      // Merge cowave_cross_analysis (union)
      const mergedCowaveCross: Record<string, CowaveCrossEntry> = {};
      for (const br of batchResults) {
        for (const [cwId, entry] of Object.entries(br.cowave_cross_analysis || {})) {
          if (!mergedCowaveCross[cwId]) {
            mergedCowaveCross[cwId] = { ...entry, overlapping_kinases: [...entry.overlapping_kinases] };
          } else {
            // Merge overlapping kinases
            const existing = mergedCowaveCross[cwId];
            for (const ok of entry.overlapping_kinases) {
              const found = existing.overlapping_kinases.find((e) => e.canonical === ok.canonical);
              if (!found) {
                existing.overlapping_kinases.push(ok);
              } else {
                const sharedSet = new Set([...found.shared_ptms, ...ok.shared_ptms]);
                found.shared_ptms = Array.from(sharedSet);
                found.shared_count = found.shared_ptms.length;
              }
            }
          }
        }
      }

      // Use temporal_cascade and effector_proteins from the LAST batch (which has full cowave context)
      // Actually, re-request the final merge call with all PTM keys for temporal cascade
      // For simplicity, merge temporal_cascade from all batches
      let mergedTemporal: TemporalCascade | undefined;
      let mergedEffectors: EffectorProtein[] | undefined;
      // Use the result from the first batch that has temporal data (all batches get same cowave_modules)
      for (const br of batchResults) {
        if (br.temporal_cascade && br.temporal_cascade.timepoints.length > 0) {
          mergedTemporal = br.temporal_cascade;
          break;
        }
      }
      // Merge effector_proteins (deduplicate by gene)
      const effectorMap = new Map<string, EffectorProtein>();
      for (const br of batchResults) {
        for (const eff of (br.effector_proteins || [])) {
          if (!effectorMap.has(eff.gene.toUpperCase())) {
            effectorMap.set(eff.gene.toUpperCase(), eff);
          }
        }
      }
      mergedEffectors = Array.from(effectorMap.values())
        .sort((a, b) => (b.evidence_score || 0) - (a.evidence_score || 0));

      // Merge wave_kinase_profile — use the first batch that has it (all batches get same cowave context)
      let mergedWaveProfile: WaveKinaseProfile[] | undefined;
      for (const br of batchResults) {
        if (br.wave_kinase_profile && br.wave_kinase_profile.length > 0) {
          mergedWaveProfile = br.wave_kinase_profile;
          break;
        }
      }

      const mergedResult: GlobalKinaseModuleResponse = {
        order_id: orderId,
        kinase_modules: mergedModules,
        unassigned_ptms: mergedUnassigned,
        annotation_details: mergedAnnotations,
        summary: mergedSummary,
        cowave_cross_analysis: mergedCowaveCross,
        temporal_cascade: mergedTemporal,
        effector_proteins: mergedEffectors,
        wave_kinase_profile: mergedWaveProfile,
      };

      setGlobalKinaseResult(mergedResult);
      setActiveTab("kinaseModules");

      // Save merged result to DB (so Receptor Inference uses complete data)
      try {
        await api.post(`/orders/${orderId}/save-kinase-analysis-data`, {
          kinase_modules: mergedModules.map((km) => ({
            ...km,
            // Strip members to reduce payload size for DB storage
            members: km.members.map((m) => ({ key: m.key, gene: m.gene, position: m.position, membership: m.membership })),
          })),
          temporal_cascade: mergedTemporal || {},
          cowave_cross_analysis: mergedCowaveCross,
          summary: mergedSummary,
          effector_proteins: (mergedEffectors || []).map((eff) => ({
            gene: eff.gene,
            data_type: eff.data_type,
            max_abs_fc: eff.max_abs_fc,
            peak_condition: eff.peak_condition,
            peak_fc: eff.peak_fc,
            sources: eff.sources,
            evidence_strength: eff.evidence_strength,
            evidence_score: eff.evidence_score,
            directionality: eff.directionality,
            connected_substrates: eff.connected_substrates,
          })),
          wave_kinase_profile: mergedWaveProfile || [],
        });
        console.log("[Global Annotate] Merged kinase_analysis_data saved to DB");
      } catch (saveErr) {
        console.warn("[Global Annotate] Failed to save merged data to DB:", saveErr);
        // Non-fatal: the UI still shows the merged result
      }
    } catch (err: any) {
      console.error("Global kinase module failed:", err);
      setGlobalKinaseError(err?.message || "Global kinase module request failed");
    } finally {
      setGlobalKinaseLoading(false);
      setGlobalKinaseBatchProgress(null);
    }
  }, [orderId, checkedPtmList, topNPtms, coWaveModules]);

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
          {isUbi ? <Link2 className="h-4 w-4 text-orange-500" /> : <Zap className="h-4 w-4 text-amber-500" />}
          {isUbi ? "E3 Ligase & Ubiquitylation Module Analysis" : "Kinase Module Analysis"}
          <Badge variant="outline" className="text-[10px] ml-2">
            Experimental
          </Badge>
          {isUbi && (
            <Badge className="text-[10px] ml-1 bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300 border-orange-300">
              Ubiquitylation Mode
            </Badge>
          )}
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {isUbi
            ? "Co-wave module detection, E3 Ligase annotation (RING/HECT/RBR), Ubiquitin chain type classification (K48/K63/Mono), and Phospho-Ub cross-talk inference."
            : "Co-wave module detection, multi-source kinase annotation (8 sources + motif prediction), and cascade inference. PTMs co-moving in the same time-point waves likely share common upstream kinases."}
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
            <Search className="h-3 w-3 mr-1" /> {isUbi ? "E3 Lookup" : "Kinase Lookup"}
          </Button>
          <Button
            variant={activeTab === "cascade" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => setActiveTab("cascade")}
          >
            <BarChart3 className="h-3 w-3 mr-1" /> {isUbi ? "Ubi Cascade" : "Cascade View"}
          </Button>
          <Button
            variant={activeTab === "kinaseModules" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => setActiveTab("kinaseModules")}
          >
            {isUbi ? <Boxes className="h-3 w-3 mr-1" /> : <Sparkles className="h-3 w-3 mr-1" />}
            {isUbi ? "E3 Modules" : "Kinase Modules"}
            {globalKinaseResult && (
              <Badge variant="secondary" className="text-[9px] ml-1 h-4 px-1">
                {globalKinaseResult.kinase_modules.length}
              </Badge>
            )}
          </Button>
          {!isUbi && inferredReceptors.length > 0 && (
            <Button
              variant={activeTab === "signalFlow" ? "default" : "ghost"}
              size="sm"
              className="text-xs h-7"
              onClick={() => setActiveTab("signalFlow")}
            >
              <GitBranch className="h-3 w-3 mr-1" /> Signal Flow
            </Button>
          )}
          <div className="ml-auto">
            <Button
              variant="outline"
              size="sm"
              className="text-xs h-7 border-amber-400 text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-900/20"
              disabled={globalKinaseLoading || checkedPtmList.length === 0}
              onClick={runGlobalKinaseModules}
            >
              {globalKinaseLoading ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <Sparkles className="h-3 w-3 mr-1" />
              )}
              {globalKinaseLoading ? "Analyzing..." : isUbi ? "E3 Annotate" : "Global Annotate"}
              <Badge variant="outline" className="text-[9px] ml-1 h-4 px-1">
                {checkedPtmList.length} PTMs
              </Badge>
            </Button>
          </div>
        </div>

        {/* Global annotation loading/error with batch progress */}
        {globalKinaseLoading && (
          <div className="flex flex-col gap-1 text-xs text-muted-foreground py-3 px-2 bg-amber-50 dark:bg-amber-900/10 rounded">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              {isUbi ? `Running E3 Ligase module analysis for ${checkedPtmList.length} ubiquitylation sites across all sources...` : `Running global kinase module analysis for ${checkedPtmList.length} PTMs across all sources...`}
            </div>
            {globalKinaseBatchProgress && globalKinaseBatchProgress.total > 1 && (
              <div className="ml-6 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-amber-700 dark:text-amber-300">
                    {globalKinaseBatchProgress.phase}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    ({Math.round((globalKinaseBatchProgress.current / globalKinaseBatchProgress.total) * 100)}%)
                  </span>
                </div>
                <div className="w-full bg-amber-200 dark:bg-amber-800 rounded-full h-1.5">
                  <div
                    className="bg-amber-500 dark:bg-amber-400 h-1.5 rounded-full transition-all duration-300"
                    style={{ width: `${(globalKinaseBatchProgress.current / globalKinaseBatchProgress.total) * 100}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        )}
        {globalKinaseError && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Global Annotation Error</AlertTitle>
            <AlertDescription className="text-xs">{globalKinaseError}</AlertDescription>
          </Alert>
        )}

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
                      {/* v9.27: Activity class badges */}
                      {mod.activity_class_counts.de_novo > 0 && (
                        <Badge variant="outline" className="text-[9px] border-orange-500 text-orange-600 dark:text-orange-400">
                          ★ {mod.activity_class_counts.de_novo} De novo
                        </Badge>
                      )}
                      {mod.activity_class_counts.regulated > 0 && (
                        <Badge variant="outline" className="text-[9px] border-blue-500 text-blue-600 dark:text-blue-400">
                          ● {mod.activity_class_counts.regulated} Regulated
                        </Badge>
                      )}
                      {mod.activity_class_counts.minor > 0 && (
                        <Badge variant="outline" className="text-[9px] border-green-500 text-green-600 dark:text-green-400">
                          ◇ {mod.activity_class_counts.minor} Minor
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
                      {onSelectPtms && (() => {
                        const modKeys = mod.ptms.map((p) => `${p.gene}_${p.position}`);
                        const isActive = highlightedPtmKeys && highlightedPtmKeys.size > 0 &&
                          modKeys.every((k) => highlightedPtmKeys.has(k)) &&
                          modKeys.length === highlightedPtmKeys.size;
                        return (
                          <Button
                            variant={isActive ? "default" : "outline"}
                            size="sm"
                            className={`text-[10px] h-6 px-2 transition-colors ${isActive ? "bg-amber-500 hover:bg-amber-600 border-amber-500 text-white" : ""}`}
                            onClick={() => onSelectPtms(modKeys)}
                          >
                            {isActive ? "★ Highlighted" : "Highlight in Chart"}
                          </Button>
                        );
                      })()}
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

                          // v9.27: activity class indicator
                          const actClass = p.activity_class ?? "minor";
                          const actClassConfig = {
                            de_novo: { symbol: "★", color: "text-[#E65100]", title: "De novo (no control signal)" },
                            regulated: { symbol: "●", color: "text-[#1565C0]", title: "Regulated (q<0.05, |FC|≥1)" },
                            minor: { symbol: "◇", color: "text-[#4CAF50]", title: "Minor (sub-threshold but patterned)" },
                          }[actClass];

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
                                  ? `[${actClassConfig.title}] ${statusCfg?.label}${
                                      ann.known_kinases.length > 0
                                        ? ` | Known: ${ann.known_kinases.map((k) => k.display_name || k.kinase).join(", ")}`
                                        : ""
                                    }${
                                      ann.motif_predicted_kinases.length > 0
                                        ? ` | Motif: ${ann.motif_predicted_kinases.map((m) => m.canonical_family || m.kinase_family).join(", ")}`
                                        : ""
                                    }${
                                      ann.concordance !== "not_applicable"
                                        ? ` | ${ann.concordance}`
                                        : ""
                                    }`
                                  : `[${actClassConfig.title}] ${p.label}`
                              }
                            >
                              {actClassConfig.symbol && (
                                <span className={`${actClassConfig.color} text-[10px]`}>{actClassConfig.symbol}</span>
                              )}
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
                              — High preservation: likely same {isUbi ? "E3 ligase module" : "kinase module"}
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
                        <MotifAnnotationPanel annotation={annotation} isUbi={isUbi} />
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
              {isUbi
                ? 'Select ubiquitylation sites below to highlight them in the chart above. Click "Annotate" to collect E3 ligase information from 8 sources (iPTMnet, UniProt, RAG, degron motif prediction, etc.) and identify novel E3-substrate relationships.'
                : 'Select PTMs below to highlight them in the chart above. Click "Annotate" to collect kinase information from 8 sources (iPTMnet, UniProt, RAG, motif prediction, etc.) and identify novel substrate candidates.'}
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
                {isUbi ? `E3 Annotate (${manualSelection.size} sites)` : `Annotate (${manualSelection.size} PTMs)`}
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
                <MotifAnnotationPanel annotation={manualAnnotation} isUbi={isUbi} />
              </div>
            )}
          </div>
        )}

        {/* ── Tab: Cascade View / Ubi Cascade ────────────────────────────────────── */}
        {activeTab === "cascade" && (
          <CascadeView
            modules={coWaveModules}
            motifAnnotations={motifAnnotations}
            conditions={conditions}
            runMotifAnnotation={runMotifAnnotation}
            motifLoading={motifLoading}
            motifError={motifError}
            globalKinaseResult={globalKinaseResult}
            globalKinaseLoading={globalKinaseLoading}
            onRunGlobalKinase={runGlobalKinaseModules}
            isUbi={isUbi}
            highlightedKinase={highlightedKinase}
            kinaseToReceptors={kinaseToReceptors}
          />
        )}

        {/* ── Tab: Signal Flow ────────────────────────────────────────────────────── */}
        {activeTab === "signalFlow" && (
          <SignalFlowView
            inferredReceptors={inferredReceptors}
            globalKinaseResult={globalKinaseResult}
            topNPtms={topNPtms}
            vectorData={vectorData}
            conditions={conditions}
          />
        )}

        {/* ── Tab: Kinase Modules / E3 Modules ──────────────────────────────── */}
        {activeTab === "kinaseModules" && (
          <GlobalKinaseModulesPanel
            result={globalKinaseResult}
            loading={globalKinaseLoading}
            onRun={runGlobalKinaseModules}
            ptmCount={checkedPtmList.length}
            vectorData={vectorData}
            conditions={conditions}
            onSelectPtms={onSelectPtms}
            highlightedPtmKeys={highlightedPtmKeys}
            isUbi={isUbi}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ── Motif Annotation Panel ──────────────────────────────────────────────────

function MotifAnnotationPanel({ annotation, isUbi = false }: { annotation: MotifAnnotationResponse; isUbi?: boolean }) {
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
          {isUbi ? "E3 Ligase Annotation Summary" : "Kinase Annotation Summary"}
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
            {isUbi
            ? "These ubiquitylation sites co-move with the module but have no known E3 ligase in any database. They represent potential novel E3 ligase-substrate relationships for experimental validation."
            : "These PTMs co-move with the module but have no known kinase in any database. They represent potential novel kinase-substrate relationships for experimental validation."}
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
            {isUbi
            ? "E3 ligase predicted from degron motif or sequence context, but no literature-confirmed E3 ligase."
            : "Kinase family predicted from flanking sequence motif or residue type, but no literature-confirmed kinase."}
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
                    <span key={`s${i}`} className="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-800/30 text-amber-800 dark:text-amber-200 cursor-help" title={`Canonical: ${m.canonical_family || m.kinase_family}\nRaw: ${m.kinase_family}\nMotif: ${m.motif}`}>
                      {m.canonical_family || m.kinase_family} <span className="opacity-60">({m.motif})</span>
                    </span>
                  ))}
                  {resMotifs.length > 0 && seqMotifs.length === 0 && (
                    <span className="px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400 italic">
                      Residue-based: {resMotifs.map((m) => m.canonical_family || m.kinase_family).join(", ")}
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
                    const displayName = k.display_name || k.kinase;
                    const canonicalName = k.canonical_name || k.kinase.toUpperCase();
                    const allSources = k.merged_sources ? [k.source, ...k.merged_sources] : [k.source];
                    const tooltip = `${canonicalName}${k.original_name && k.original_name !== displayName ? ` (raw: ${k.original_name})` : ""}\nSources: ${allSources.map(s => SOURCE_LABELS[s]?.label || s).join(", ")}`;
                    return (
                      <span key={i} className="px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-800/30 text-green-800 dark:text-green-200 inline-flex items-center gap-1 cursor-help" title={tooltip}>
                        {displayName}
                        {allSources.length > 1 && <span className="text-[8px] text-green-600 dark:text-green-400">({allSources.length})</span>}
                        <span className={`text-[8px] px-1 rounded ${srcCfg.color}`}>{srcCfg.label}</span>
                      </span>
                    );
                  })}
                  {a.motif_predicted_kinases.length > 0 && (
                    <>
                      <span className="text-muted-foreground">|</span>
                      {a.motif_predicted_kinases.slice(0, 2).map((m, i) => (
                        <span key={`m${i}`} className="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-800/30 text-amber-800 dark:text-amber-200 cursor-help" title={`Canonical: ${m.canonical_family || m.kinase_family}\nMotif: ${m.motif}`}>
                          Motif: {m.canonical_family || m.kinase_family}
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
                <TableHead className="text-[10px]">{isUbi ? "Known E3 Ligase" : "Known Kinase"}</TableHead>
                <TableHead className="text-[10px]">{isUbi ? "Motif/Degron Prediction" : "Motif Prediction"}</TableHead>
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
                                <span key={ki} className="inline-flex items-center gap-0.5 cursor-help" title={`Canonical: ${k.canonical_name || k.kinase}${k.original_name && k.original_name !== (k.display_name || k.kinase) ? ` (raw: ${k.original_name})` : ""}`}>
                                  <span className="font-medium">{k.display_name || k.kinase}</span>
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
                        ? a.motif_predicted_kinases.map((m) => m.canonical_family || m.kinase_family).join(", ")
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
              <span className="text-sm font-bold text-foreground" title={km.canonical ? `Canonical: ${km.canonical}` : ""}>{km.kinase}</span>
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
                  .filter((ia) => (ia.inferred_canonical || ia.inferred_kinase.toUpperCase()) === (km.canonical || km.kinase.toUpperCase()))
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

/** Collect all unique kinases from an annotation (known + motif + group inference), using canonical names for dedup */
function collectAllKinases(annotation: MotifAnnotationResponse | undefined): { kinase: string; canonical: string; source: string }[] {
  if (!annotation) return [];
  const seen = new Set<string>();
  const result: { kinase: string; canonical: string; source: string }[] = [];
  for (const a of annotation.annotations) {
    for (const k of a.known_kinases) {
      const key = (k.canonical_name || k.kinase).toUpperCase();
      if (!seen.has(key)) { seen.add(key); result.push({ kinase: k.display_name || k.kinase, canonical: key, source: k.source }); }
    }
    for (const m of a.motif_predicted_kinases) {
      const key = (m.canonical_family || m.kinase_family).toUpperCase();
      if (!seen.has(key)) { seen.add(key); result.push({ kinase: m.canonical_family || m.kinase_family, canonical: key, source: "motif_prediction" }); }
    }
  }
  if (annotation.group_inference) {
    for (const ak of annotation.group_inference.anchor_kinases) {
      const key = (ak.canonical || ak.kinase).toUpperCase();
      if (!seen.has(key)) { seen.add(key); result.push({ kinase: ak.kinase, canonical: key, source: ak.sources[0] || "group_inference" }); }
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
  globalKinaseResult,
  globalKinaseLoading,
  onRunGlobalKinase,
  isUbi = false,
  highlightedKinase,
  kinaseToReceptors = {},
}: {
  modules: CoWaveModule[];
  motifAnnotations: Record<string, MotifAnnotationResponse>;
  conditions: string[];
  runMotifAnnotation: (moduleKey: string, ptms: PtmInfo[]) => void;
  motifLoading: string | null;
  motifError: string | null;
  globalKinaseResult: GlobalKinaseModuleResponse | null;
  globalKinaseLoading: boolean;
  onRunGlobalKinase: () => void;
  isUbi?: boolean;
  highlightedKinase?: string | null;
  kinaseToReceptors?: Record<string, string[]>;
}) {
  const [expandedTimepoint, setExpandedTimepoint] = useState<string | null>(null);
  const [showSwimlane, setShowSwimlane] = useState(true);

  if (modules.length === 0) {
    return (
      <div className="text-center py-6 text-sm text-muted-foreground">
        <BarChart3 className="h-8 w-8 mx-auto mb-2 opacity-40" />
        Run co-wave detection first (enable PTMs in the chart above).
        {isUbi ? "Cascade view shows temporal ordering of E3 ligase modules and ubiquitylation dynamics." : "Cascade view shows temporal ordering of kinase modules."}
      </div>
    );
  }

  const tc = globalKinaseResult?.temporal_cascade;
  const hasTemporalData = tc && tc.timepoints && tc.timepoints.length > 0;

  // Fallback: build basic temporal info from co-wave modules if no global kinase result
  const sortedModules = [...modules].sort(
    (a, b) => conditions.indexOf(a.peakCondition) - conditions.indexOf(b.peakCondition)
  );

  // Color palette for kinases in swimlane
  const SWIMLANE_COLORS = [
    { bg: "bg-blue-500", text: "text-white", light: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300", hex: "#3b82f6" },
    { bg: "bg-rose-500", text: "text-white", light: "bg-rose-100 dark:bg-rose-900/40 text-rose-700 dark:text-rose-300", hex: "#f43f5e" },
    { bg: "bg-emerald-500", text: "text-white", light: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300", hex: "#10b981" },
    { bg: "bg-amber-500", text: "text-white", light: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300", hex: "#f59e0b" },
    { bg: "bg-violet-500", text: "text-white", light: "bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300", hex: "#8b5cf6" },
    { bg: "bg-cyan-500", text: "text-white", light: "bg-cyan-100 dark:bg-cyan-900/40 text-cyan-700 dark:text-cyan-300", hex: "#06b6d4" },
    { bg: "bg-pink-500", text: "text-white", light: "bg-pink-100 dark:bg-pink-900/40 text-pink-700 dark:text-pink-300", hex: "#ec4899" },
    { bg: "bg-teal-500", text: "text-white", light: "bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300", hex: "#14b8a6" },
  ];

  return (
    <div className="space-y-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          <Clock className="h-3 w-3 inline mr-1" />
          {isUbi
            ? "Temporal ubiquitylation cascade: shows which E3 ligases are active at each timepoint, chain type dynamics, and DUB activity inference."
            : "Temporal kinase cascade: shows which kinases are active at each timepoint and how signaling flows over time."}
        </p>
        {!hasTemporalData && (
          <Button
            variant="default"
            size="sm"
            className={`text-xs h-7 ${isUbi ? "bg-orange-600 hover:bg-orange-700" : ""}`}
            disabled={globalKinaseLoading}
            onClick={onRunGlobalKinase}
          >
            {globalKinaseLoading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Network className="h-3 w-3 mr-1" />}
            {isUbi ? "Build Ubi Cascade" : "Build Temporal Cascade"}
          </Button>
        )}
      </div>

      {/* ── Loading state ── */}
      {globalKinaseLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" />
          {isUbi
            ? "Building temporal ubiquitylation cascade — E3 ligases, chain types, DUB activity..."
            : "Building temporal kinase cascade from all PTM annotations..."}
        </div>
      )}

      {/* ── No temporal data yet ── */}
      {!hasTemporalData && !globalKinaseLoading && (
        <div className="space-y-3">
          <Alert>
            <Info className="h-4 w-4" />
            <AlertTitle>{isUbi ? "Ubiquitylation Cascade Not Yet Built" : "Temporal Cascade Not Yet Built"}</AlertTitle>
            <AlertDescription className="text-xs">
              Click <strong>{isUbi ? "\"Build Ubi Cascade\"" : "\"Build Temporal Cascade\""}</strong> above (or run <strong>{isUbi ? "\"E3 Modules\"" : "\"Global Kinase Modules\""}</strong> from the {isUbi ? "E3 Modules" : "Kinase Modules"} tab) to generate the temporal {isUbi ? "ubiquitylation" : "kinase"} cascade.
              This will annotate all PTMs with 8 sources and build a time-ordered kinase activation map.
            </AlertDescription>
          </Alert>

          {/* Fallback: basic co-wave module timeline */}
          <div className="text-xs font-medium text-muted-foreground mb-2">Basic Co-wave Module Timeline (preview):</div>
          <div className="flex items-center gap-0 overflow-x-auto pb-2">
            {sortedModules.map((mod, idx) => (
              <div key={mod.id} className="flex items-center">
                <div className="rounded-lg border bg-card p-2.5 min-w-[160px] space-y-1">
                  <div className="text-[10px] font-medium">{mod.label}</div>
                  <div className="flex items-center gap-1">
                    <Badge variant="outline" className="text-[9px]">{mod.ptms.length} PTMs</Badge>
                    <Badge variant="outline" className="text-[9px] text-muted-foreground">Peak: {mod.peakCondition}</Badge>
                  </div>
                </div>
                {idx < sortedModules.length - 1 && (
                  <ArrowRight className="h-4 w-4 text-muted-foreground mx-1 shrink-0" />
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ──────────────────────────────────────────────────────────────────────────── */}
      {/* TEMPORAL CASCADE VISUALIZATION                                            */}
      {/* ──────────────────────────────────────────────────────────────────────────── */}
      {hasTemporalData && tc && (
        <>
          {/* ── Section 1: Timeline with Kinase/E3 Cards ── */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs font-medium">
              <Timer className={`h-3.5 w-3.5 ${isUbi ? "text-orange-500" : "text-blue-500"}`} />
              {isUbi ? "Temporal E3 Ligase Activation Timeline" : "Temporal Kinase Activation Timeline"}
              <span className="text-muted-foreground font-normal">— {tc.timepoints.length} timepoints</span>
            </div>

            {/* Timeline bar */}
            <div className="relative">
              {/* Timeline axis line */}
              <div className="absolute top-[28px] left-0 right-0 h-[2px] bg-border" />

              <div className="flex items-start overflow-x-auto pb-2" style={{ gap: 0 }}>
                {tc.timepoints.map((tp, tpIdx) => {
                  const isExpanded = expandedTimepoint === tp.condition;
                  const flow = tc.cascade_flow?.[tpIdx]; // flow FROM this tp to next

                  return (
                    <div key={tp.condition} className="flex items-start">
                      {/* Timepoint column */}
                      <div className="flex flex-col items-center min-w-[200px] max-w-[280px]">
                        {/* Time label */}
                        <div className="text-[11px] font-semibold text-foreground mb-1">{tp.condition}</div>

                        {/* Timeline dot */}
                        <div className="w-4 h-4 rounded-full bg-blue-500 border-2 border-background shadow-sm z-10 mb-2" />

                        {/* Kinase card */}
                        <div
                          className="rounded-lg border bg-card p-2.5 w-full space-y-2 cursor-pointer hover:border-blue-400 transition-colors"
                          onClick={() => setExpandedTimepoint(isExpanded ? null : tp.condition)}
                        >
                          {/* Card header */}
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1">
                              <Badge variant="outline" className="text-[9px]">
                                {tp.ptm_count} PTMs
                              </Badge>
                              <Badge variant="outline" className="text-[9px] text-blue-600 dark:text-blue-400 border-blue-300">
                                {tp.kinases.length} kinases
                              </Badge>
                            </div>
                            {isExpanded ? <ChevronUp className="h-3 w-3 text-muted-foreground" /> : <ChevronDown className="h-3 w-3 text-muted-foreground" />}
                          </div>

                          {/* Top kinases */}
                          <div className="flex flex-wrap gap-1">
                            {tp.kinases.slice(0, 5).map((k, ki) => {
                              const colorIdx = ki % SWIMLANE_COLORS.length;
                              const isPersistent = (tc.kinase_activity || []).some(
                                (ka) => ka.canonical === k.canonical && ka.timepoints.length >= 2
                              );
                              // v9.21: highlight if matches receptor-clicked kinase
                              const kinaseKey = (k.canonical || k.kinase).toUpperCase();
                              const isHighlighted = highlightedKinase
                                ? kinaseKey === highlightedKinase.toUpperCase() ||
                                  k.kinase.toUpperCase() === highlightedKinase.toUpperCase()
                                : false;
                              // v9.21: receptor badges
                              const receptorSources = kinaseToReceptors[kinaseKey] || [];
                              return (
                                <span
                                  key={k.canonical}
                                  className={`text-[9px] px-1.5 py-0.5 rounded inline-flex items-center gap-0.5 transition-all ${
                                    isHighlighted
                                      ? "bg-yellow-200 dark:bg-yellow-700/60 text-yellow-900 dark:text-yellow-100 border border-yellow-400 ring-1 ring-yellow-400 scale-110"
                                      : isPersistent
                                        ? "bg-blue-100 dark:bg-blue-800/30 text-blue-700 dark:text-blue-300 border border-blue-400"
                                        : SWIMLANE_COLORS[colorIdx].light
                                  }`}
                                  title={`${k.kinase}: ${k.ptm_count} PTMs (${k.confirmed} confirmed, ${k.inferred} inferred)\nSources: ${k.sources.join(", ")}${isPersistent ? "\nPersistent across timepoints" : ""}${receptorSources.length ? "\nUpstream receptors: " + receptorSources.join(", ") : ""}`}
                                >
                                  {isPersistent && <Layers className="h-2.5 w-2.5" />}
                                  {isHighlighted && <Activity className="h-2.5 w-2.5 text-yellow-600 dark:text-yellow-300" />}
                                  {k.kinase}
                                  <span className="opacity-60">({k.ptm_count})</span>
                                  {receptorSources.length > 0 && (
                                    <span
                                      className="ml-0.5 text-[8px] bg-sky-200 dark:bg-sky-800/50 text-sky-700 dark:text-sky-300 px-0.5 rounded"
                                      title={`Downstream of: ${receptorSources.join(", ")}`}
                                    >
                                      {receptorSources.length === 1
                                        ? receptorSources[0].split(" ")[0]
                                        : `${receptorSources.length}R`}
                                    </span>
                                  )}
                                </span>
                              );
                            })}
                            {tp.kinases.length > 5 && (
                              <span className="text-[9px] text-muted-foreground">+{tp.kinases.length - 5}</span>
                            )}
                          </div>

                          {/* Co-wave module labels */}
                          <div className="text-[9px] text-muted-foreground">
                            {tp.cowave_labels.join(", ")}
                          </div>

                          {/* Expanded detail */}
                          {isExpanded && (
                            <div className="space-y-2 pt-2 border-t">
                              <div className="text-[10px] font-medium">{isUbi ? `All E3 Ligases at ${tp.condition}:` : `All Kinases at ${tp.condition}:`}</div>
                              <Table>
                                <TableHeader>
                                  <TableRow>
                                    <TableHead className="text-[9px] py-1 h-auto">{isUbi ? "E3 Ligase" : "Kinase"}</TableHead>
                                    <TableHead className="text-[9px] py-1 h-auto">{isUbi ? "Sites" : "PTMs"}</TableHead>
                                    <TableHead className="text-[9px] py-1 h-auto">Confirmed</TableHead>
                                    <TableHead className="text-[9px] py-1 h-auto">Inferred</TableHead>
                                    <TableHead className="text-[9px] py-1 h-auto">Sources</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {tp.kinases.map((k) => (
                                    <TableRow key={k.canonical}>
                                      <TableCell className="text-[9px] py-0.5 font-medium">{k.kinase}</TableCell>
                                      <TableCell className="text-[9px] py-0.5">{k.ptm_count}</TableCell>
                                      <TableCell className="text-[9px] py-0.5">
                                        <span className="text-green-600 dark:text-green-400">{k.confirmed}</span>
                                      </TableCell>
                                      <TableCell className="text-[9px] py-0.5">
                                        <span className="text-amber-600 dark:text-amber-400">{k.inferred}</span>
                                      </TableCell>
                                      <TableCell className="text-[9px] py-0.5">
                                        <div className="flex flex-wrap gap-0.5">
                                          {k.sources.slice(0, 3).map((s) => (
                                            <span key={s} className={`px-1 py-0 rounded text-[8px] ${SOURCE_LABELS[s]?.color || "bg-muted"}`}>
                                              {SOURCE_LABELS[s]?.label || s}
                                            </span>
                                          ))}
                                          {k.sources.length > 3 && <span className="text-[8px] text-muted-foreground">+{k.sources.length - 3}</span>}
                                        </div>
                                      </TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Arrow + flow info between timepoints */}
                      {tpIdx < tc.timepoints.length - 1 && flow && (
                        <div className="flex flex-col items-center px-2 pt-6 min-w-[80px]">
                          <ArrowRight className="h-5 w-5 text-blue-400" />
                          {flow.shared_kinases.length > 0 && (
                            <div className="flex flex-col items-center gap-0.5 mt-1">
                              <span className="text-[8px] text-blue-500 font-medium">Persistent:</span>
                              {flow.shared_kinases.slice(0, 3).map((k) => (
                                <span key={k} className="text-[8px] px-1 py-0 rounded bg-blue-100 dark:bg-blue-800/30 text-blue-600 dark:text-blue-300 whitespace-nowrap">
                                  {k}
                                </span>
                              ))}
                              {flow.shared_kinases.length > 3 && (
                                <span className="text-[8px] text-muted-foreground">+{flow.shared_kinases.length - 3}</span>
                              )}
                            </div>
                          )}
                          {flow.new_kinases.length > 0 && (
                            <div className="flex flex-col items-center gap-0.5 mt-1">
                              <span className="text-[8px] text-green-500 font-medium">New:</span>
                              {flow.new_kinases.slice(0, 2).map((k) => (
                                <span key={k} className="text-[8px] px-1 py-0 rounded bg-green-100 dark:bg-green-800/30 text-green-600 dark:text-green-300 whitespace-nowrap">
                                  {k}
                                </span>
                              ))}
                              {flow.new_kinases.length > 2 && (
                                <span className="text-[8px] text-muted-foreground">+{flow.new_kinases.length - 2}</span>
                              )}
                            </div>
                          )}
                          {flow.lost_kinases.length > 0 && (
                            <div className="flex flex-col items-center gap-0.5 mt-1">
                              <span className="text-[8px] text-red-400 font-medium">Lost:</span>
                              {flow.lost_kinases.slice(0, 2).map((k) => (
                                <span key={k} className="text-[8px] px-1 py-0 rounded bg-red-100 dark:bg-red-800/30 text-red-500 dark:text-red-400 whitespace-nowrap line-through">
                                  {k}
                                </span>
                              ))}
                              {flow.lost_kinases.length > 2 && (
                                <span className="text-[8px] text-muted-foreground">+{flow.lost_kinases.length - 2}</span>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <Separator />

          {/* ── Section 2: Kinase/E3 Activity Swimlane ── */}
          {tc.kinase_activity && tc.kinase_activity.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-medium">
                  <TrendingUp className={`h-3.5 w-3.5 ${isUbi ? "text-orange-500" : "text-emerald-500"}`} />
                  {isUbi ? "E3 Ligase Activity Swimlane" : "Kinase Activity Swimlane"}
                  <span className="text-muted-foreground font-normal">— when each {isUbi ? "E3 ligase" : "kinase"} is active</span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-[10px] h-6"
                  onClick={() => setShowSwimlane(!showSwimlane)}
                >
                  {showSwimlane ? "Hide" : "Show"}
                </Button>
              </div>

              {showSwimlane && (
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left py-1.5 px-2 min-w-[100px] font-medium text-muted-foreground">{isUbi ? "E3 Ligase" : "Kinase"}</th>
                        {tc.timepoints.map((tp) => (
                          <th key={tp.condition} className="text-center py-1.5 px-2 min-w-[80px] font-medium text-muted-foreground">
                            {tp.condition}
                          </th>
                        ))}
                        <th className="text-center py-1.5 px-2 min-w-[60px] font-medium text-muted-foreground">Span</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tc.kinase_activity.slice(0, 20).map((ka, kaIdx) => {
                        const colorIdx = kaIdx % SWIMLANE_COLORS.length;
                        const activeTps = new Set(ka.timepoints.map((t) => t.condition));
                        const isPersistent = ka.timepoints.length >= 2;

                        return (
                          <tr key={ka.canonical} className={`border-b border-border/50 ${isPersistent ? "bg-blue-50/30 dark:bg-blue-950/10" : ""}`}>
                            <td className="py-1 px-2 font-medium">
                              <div className="flex items-center gap-1">
                                {isPersistent && <Layers className="h-2.5 w-2.5 text-blue-500" />}
                                <span className={isPersistent ? "text-blue-700 dark:text-blue-300" : ""}>{ka.kinase}</span>
                              </div>
                            </td>
                            {tc.timepoints.map((tp) => {
                              const tpData = ka.timepoints.find((t) => t.condition === tp.condition);
                              if (!tpData) {
                                return (
                                  <td key={tp.condition} className="py-1 px-2 text-center">
                                    <span className="text-muted-foreground/30">—</span>
                                  </td>
                                );
                              }
                              return (
                                <td key={tp.condition} className="py-1 px-2 text-center">
                                  <div className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded ${SWIMLANE_COLORS[colorIdx].light}`}>
                                    <span className="font-medium">{tpData.ptm_count}</span>
                                    <span className="opacity-60">PTMs</span>
                                  </div>
                                </td>
                              );
                            })}
                            <td className="py-1 px-2 text-center">
                              <span className={`px-1.5 py-0.5 rounded text-[9px] ${
                                isPersistent
                                  ? "bg-blue-100 dark:bg-blue-800/30 text-blue-600 dark:text-blue-300 font-medium"
                                  : "bg-muted text-muted-foreground"
                              }`}>
                                {ka.timepoints.length}/{tc.timepoints.length}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {tc.kinase_activity.length > 20 && (
                    <div className="text-[10px] text-muted-foreground text-center py-1">
                      Showing top 20 of {tc.kinase_activity.length} {isUbi ? "E3 ligases" : "kinases"}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <Separator />

          {/* ── Section 3: Cascade Flow Summary ── */}
          <div className={`bg-gradient-to-br ${isUbi ? "from-orange-50/50 to-amber-50/50 dark:from-orange-950/20 dark:to-amber-950/20" : "from-blue-50/50 to-indigo-50/50 dark:from-blue-950/20 dark:to-indigo-950/20"} rounded-lg p-3 space-y-3`}>
            <div className="flex items-center gap-2 text-xs font-medium">
              <GitBranch className={`h-3.5 w-3.5 ${isUbi ? "text-orange-500" : "text-indigo-500"}`} />
              {isUbi ? "Ubiquitylation Cascade Flow Summary" : "Signaling Cascade Flow Summary"}
            </div>

            {/* Flow text */}
            <div className="text-[11px] text-foreground leading-relaxed">
              <strong>Temporal order:</strong>{" "}
              {tc.timepoints.map((tp) => {
                const topK = tp.kinases.slice(0, 3).map((k) => k.kinase);
                return `${tp.condition} [${topK.length > 0 ? topK.join(", ") : "unknown"}]`;
              }).join(" \u2192 ")}
            </div>

            {/* Persistent kinases / E3 ligases */}
            {tc.kinase_activity && (() => {
              const persistent = tc.kinase_activity.filter((ka) => ka.timepoints.length >= 2);
              if (persistent.length === 0) return null;
              return (
                <div className="space-y-1">
                  <div className={`text-[10px] font-medium ${isUbi ? "text-orange-700 dark:text-orange-300" : "text-blue-700 dark:text-blue-300"}`}>
                    <Layers className="h-3 w-3 inline mr-1" />
                    {isUbi ? "Persistent E3 Ligases (active across 2+ timepoints):" : "Persistent Kinases (active across 2+ timepoints):"}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {persistent.map((ka) => (
                      <span
                        key={ka.canonical}
                        className="text-[9px] px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-800/30 text-blue-700 dark:text-blue-300 border border-blue-300"
                        title={`Active at: ${ka.timepoints.map((t) => t.condition).join(", ")}`}
                      >
                        {ka.kinase} ({ka.timepoints.map((t) => t.condition).join(" \u2192 ")})
                      </span>
                    ))}
                  </div>
                </div>
              );
            })()}

            {/* Cascade flow transitions */}
            {tc.cascade_flow && tc.cascade_flow.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] font-medium">Transition Details:</div>
                {tc.cascade_flow.map((flow, fi) => (
                  <div key={fi} className="text-[10px] flex items-start gap-2 pl-2">
                    <span className="font-medium whitespace-nowrap">{flow.from} \u2192 {flow.to}:</span>
                    <div className="flex flex-wrap gap-1">
                      {flow.shared_kinases.length > 0 && (
                        <span className="text-blue-600 dark:text-blue-400">
                          Persistent: {flow.shared_kinases.slice(0, 4).join(", ")}{flow.shared_kinases.length > 4 ? ` (+${flow.shared_kinases.length - 4})` : ""}
                        </span>
                      )}
                      {flow.new_kinases.length > 0 && (
                        <span className="text-green-600 dark:text-green-400">
                          | New: {flow.new_kinases.slice(0, 4).join(", ")}{flow.new_kinases.length > 4 ? ` (+${flow.new_kinases.length - 4})` : ""}
                        </span>
                      )}
                      {flow.lost_kinases.length > 0 && (
                        <span className="text-red-500 dark:text-red-400">
                          | Lost: {flow.lost_kinases.slice(0, 4).join(", ")}{flow.lost_kinases.length > 4 ? ` (+${flow.lost_kinases.length - 4})` : ""}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* v9.34: Non-PTM Effector Temporal Overlay */}
          {globalKinaseResult?.effector_proteins && globalKinaseResult.effector_proteins.length > 0 && (
            <>
              <Separator />
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-medium">
                  <ArrowRight className="h-3.5 w-3.5 text-teal-500" />
                  Non-PTM Effector Temporal Response
                  <span className="text-muted-foreground font-normal">— protein abundance changes of downstream effectors</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px]">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left py-1.5 px-2 min-w-[100px] font-medium text-muted-foreground">Effector</th>
                        {tc.timepoints.map(tp => (
                          <th key={tp.condition} className="text-center py-1.5 px-2 min-w-[80px] font-medium text-muted-foreground">
                            {tp.condition}
                          </th>
                        ))}
                        <th className="text-center py-1.5 px-2 min-w-[80px] font-medium text-muted-foreground">Peak</th>
                        <th className="text-center py-1.5 px-2 min-w-[60px] font-medium text-muted-foreground">Evidence</th>
                        <th className="text-center py-1.5 px-2 min-w-[60px] font-medium text-muted-foreground">Direction</th>
                        <th className="text-center py-1.5 px-2 min-w-[60px] font-medium text-muted-foreground">Time-lag</th>
                        <th className="text-center py-1.5 px-2 min-w-[80px] font-medium text-muted-foreground">Sources</th>
                      </tr>
                    </thead>
                    <tbody>
                      {globalKinaseResult.effector_proteins.map(eff => {
                        const tpMap: Record<string, number> = {};
                        for (const tp of eff.temporal_profile) {
                          tpMap[tp.condition] = tp.protein_log2fc;
                        }
                        return (
                          <tr key={eff.gene} className="border-b border-border/50">
                            <td className="py-1 px-2 font-medium">
                              <span className={eff.peak_fc > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}>
                                {eff.peak_fc > 0 ? "▲" : "▼"} {eff.gene}
                              </span>
                            </td>
                            {tc.timepoints.map(tp => {
                              const fc = tpMap[tp.condition];
                              if (fc === undefined || fc === null) {
                                return (
                                  <td key={tp.condition} className="py-1 px-2 text-center">
                                    <span className="text-muted-foreground/30">—</span>
                                  </td>
                                );
                              }
                              const isUp = fc > 0.3;
                              const isDown = fc < -0.3;
                              return (
                                <td key={tp.condition} className="py-1 px-2 text-center">
                                  <span className={`inline-block px-1.5 py-0.5 rounded text-[9px] font-medium ${
                                    isUp ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300" :
                                    isDown ? "bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300" :
                                    "bg-muted text-muted-foreground"
                                  }`}>
                                    {fc > 0 ? "+" : ""}{fc.toFixed(2)}
                                  </span>
                                </td>
                              );
                            })}
                            <td className="py-1 px-2 text-center">
                              <span className={`text-[9px] font-medium ${
                                eff.peak_fc > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"
                              }`}>
                                {eff.peak_fc > 0 ? "+" : ""}{eff.peak_fc.toFixed(2)} @ {eff.peak_condition}
                              </span>
                            </td>
                            <td className="py-1 px-2 text-center">
                              <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded ${
                                (eff.evidence_strength || "weak") === "strong" ? "bg-emerald-900/30 text-emerald-300" :
                                (eff.evidence_strength || "weak") === "moderate" ? "bg-amber-900/30 text-amber-300" :
                                (eff.evidence_strength || "weak") === "expression_only" ? "bg-sky-900/30 text-sky-300" :
                                "bg-muted text-muted-foreground"
                              }`}>
                                {eff.evidence_strength || "weak"}
                              </span>
                            </td>
                            <td className="py-1 px-2 text-center">
                              <span className={`text-[9px] ${
                                eff.directionality === "concordant" ? "text-emerald-400" :
                                eff.directionality === "discordant" ? "text-rose-400" :
                                "text-yellow-400"
                              }`}>
                                {eff.directionality === "concordant" ? `\u2713 ${eff.concordant_count || 0}/${(eff.concordant_count || 0) + (eff.discordant_count || 0)}` :
                                 eff.directionality === "discordant" ? `\u2717 ${eff.discordant_count || 0}/${(eff.concordant_count || 0) + (eff.discordant_count || 0)}` :
                                 eff.directionality === "mixed" ? `~ ${eff.concordant_count || 0}\u2713/${eff.discordant_count || 0}\u2717` :
                                 "—"}
                              </span>
                            </td>
                            <td className="py-1 px-2 text-center">
                              <span className={`text-[9px] ${
                                eff.time_lag_minutes != null && eff.time_lag_minutes > 0 ? "text-emerald-400" :
                                eff.time_lag_minutes != null && eff.time_lag_minutes < 0 ? "text-rose-400" :
                                "text-muted-foreground"
                              }`}>
                                {eff.time_lag_minutes != null ? `${eff.time_lag_minutes > 0 ? "+" : ""}${eff.time_lag_minutes}m` : "—"}
                              </span>
                            </td>
                            <td className="py-1 px-2 text-center">
                              <span className="text-[9px] text-muted-foreground">{eff.sources.join(", ")}</span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>

                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}


// ── Global Kinase Modules Panel ──────────────────────────────────────────────

// ── Chain type color mapping ────────────────────────────────────────────────
const CHAIN_TYPE_COLORS: Record<string, { bg: string; text: string; border: string; label: string }> = {
  K48: { bg: "bg-red-100 dark:bg-red-900/30", text: "text-red-700 dark:text-red-300", border: "border-red-400", label: "K48 (Degradation)" },
  K63: { bg: "bg-blue-100 dark:bg-blue-900/30", text: "text-blue-700 dark:text-blue-300", border: "border-blue-400", label: "K63 (Signaling)" },
  K11: { bg: "bg-purple-100 dark:bg-purple-900/30", text: "text-purple-700 dark:text-purple-300", border: "border-purple-400", label: "K11 (Cell Cycle)" },
  K27: { bg: "bg-green-100 dark:bg-green-900/30", text: "text-green-700 dark:text-green-300", border: "border-green-400", label: "K27 (Chromatin)" },
  K29: { bg: "bg-yellow-100 dark:bg-yellow-900/30", text: "text-yellow-700 dark:text-yellow-300", border: "border-yellow-400", label: "K29 (Stress)" },
  K33: { bg: "bg-cyan-100 dark:bg-cyan-900/30", text: "text-cyan-700 dark:text-cyan-300", border: "border-cyan-400", label: "K33 (Kinase)" },
  K6:  { bg: "bg-orange-100 dark:bg-orange-900/30", text: "text-orange-700 dark:text-orange-300", border: "border-orange-400", label: "K6 (DNA Repair)" },
  mono: { bg: "bg-teal-100 dark:bg-teal-900/30", text: "text-teal-700 dark:text-teal-300", border: "border-teal-400", label: "Mono-Ub (Signaling)" },
  mixed: { bg: "bg-gray-100 dark:bg-gray-800", text: "text-gray-600 dark:text-gray-400", border: "border-gray-400", label: "Mixed" },
  unknown: { bg: "bg-gray-50 dark:bg-gray-900", text: "text-gray-500", border: "border-gray-300", label: "Unknown" },
};

const E3_FAMILY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  RING: { bg: "bg-violet-100 dark:bg-violet-900/30", text: "text-violet-700 dark:text-violet-300", border: "border-violet-400" },
  HECT: { bg: "bg-rose-100 dark:bg-rose-900/30", text: "text-rose-700 dark:text-rose-300", border: "border-rose-400" },
  RBR:  { bg: "bg-amber-100 dark:bg-amber-900/30", text: "text-amber-700 dark:text-amber-300", border: "border-amber-400" },
  SCF:  { bg: "bg-emerald-100 dark:bg-emerald-900/30", text: "text-emerald-700 dark:text-emerald-300", border: "border-emerald-400" },
  APC:  { bg: "bg-sky-100 dark:bg-sky-900/30", text: "text-sky-700 dark:text-sky-300", border: "border-sky-400" },
  unknown: { bg: "bg-gray-100 dark:bg-gray-800", text: "text-gray-500", border: "border-gray-300" },
};

function GlobalKinaseModulesPanel({
  result,
  loading,
  onRun,
  ptmCount,
  vectorData,
  conditions,
  onSelectPtms,
  highlightedPtmKeys,
  isUbi = false,
}: {
  result: GlobalKinaseModuleResponse | null;
  loading: boolean;
  onRun: () => void;
  ptmCount: number;
  vectorData: PtmTimeSeriesRow[];
  conditions: string[];
  onSelectPtms?: (keys: string[]) => void;
  highlightedPtmKeys?: Set<string>;
  isUbi?: boolean;
}) {
  const [expandedKinase, setExpandedKinase] = useState<string | null>(null);
  const [showCrossAnalysis, setShowCrossAnalysis] = useState(false);

  if (!result && !loading) {
    return (
      <div className="text-center py-8 space-y-3">
        {isUbi
          ? <Boxes className="h-10 w-10 mx-auto text-orange-400 opacity-50" />
          : <Sparkles className="h-10 w-10 mx-auto text-amber-400 opacity-50" />}
        <div className="text-sm text-muted-foreground">
          <strong>{isUbi ? "E3 Ligase Module Analysis" : "Global Kinase Module Analysis"}</strong>
        </div>
        <p className="text-xs text-muted-foreground max-w-md mx-auto">
          {isUbi
            ? "Annotate all checked ubiquitylation sites using 8 sources, classify Ubiquitin chain types (K48/K63/Mono), group by E3 Ligase (RING/HECT/RBR), and detect degron motifs."
            : "Annotate all checked PTMs at once using 8 sources (iPTMnet, UniProt, RAG, motif prediction, etc.), then group them by regulating kinase — regardless of time-point."}
        </p>
        <Button
          variant="default"
          size="sm"
          className={`text-xs ${isUbi ? "bg-orange-600 hover:bg-orange-700" : ""}`}
          disabled={ptmCount === 0}
          onClick={onRun}
        >
          {isUbi ? <Boxes className="h-3 w-3 mr-1" /> : <Sparkles className="h-3 w-3 mr-1" />}
          {isUbi ? `Run E3 Annotate (${ptmCount} sites)` : `Run Global Annotate (${ptmCount} PTMs)`}
        </Button>
      </div>
    );
  }

  if (loading || !result) {
    return (
      <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground py-8">
        <Loader2 className="h-5 w-5 animate-spin" />
        {isUbi
          ? `Classifying ${ptmCount} ubiquitylation sites — chain types, E3 families, degron motifs...`
          : `Analyzing ${ptmCount} PTMs across 8 sources + motif prediction...`}
      </div>
    );
  }

  const { kinase_modules, unassigned_ptms, summary, cowave_cross_analysis } = result;

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <div className="rounded-lg border p-3 text-center">
          <div className="text-2xl font-bold text-primary">{summary.total_kinase_modules}</div>
          <div className="text-[10px] text-muted-foreground">{isUbi ? "E3 Ligase Modules" : "Kinase Modules"}</div>
        </div>
        <div className="rounded-lg border p-3 text-center">
          <div className="text-2xl font-bold text-green-600">{summary.total_confirmed}</div>
          <div className="text-[10px] text-muted-foreground">{isUbi ? "Literature Evidence" : "Confirmed (Known)"}</div>
        </div>
        <div className="rounded-lg border p-3 text-center">
          <div className="text-2xl font-bold text-blue-600">{summary.total_inferred}</div>
          <div className="text-[10px] text-muted-foreground">{isUbi ? "Degron Motif" : "Inferred (Motif)"}</div>
        </div>
        <div className="rounded-lg border p-3 text-center">
          <div className="text-2xl font-bold text-muted-foreground">{summary.total_unassigned}</div>
          <div className="text-[10px] text-muted-foreground">Unassigned</div>
        </div>
      </div>

      {/* v9.34: Non-PTM Effector Summary */}
      {result.effector_proteins && result.effector_proteins.length > 0 && (
        <div className="rounded-lg border border-teal-500/30 bg-teal-50/5 dark:bg-teal-900/10 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-xs font-semibold text-teal-600 dark:text-teal-400 flex items-center gap-1">
              <ArrowRight className="h-3 w-3" /> Non-PTM Effector Layer
            </div>
            <span className="text-[10px] text-muted-foreground">
              {result.effector_proteins.length} non-PTM proteins
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {result.effector_proteins.map(eff => {
              const isUp = eff.peak_fc > 0;
              const strength = eff.evidence_strength || "weak";
              const strengthBorder = strength === "strong" ? "border-2" : strength === "moderate" ? "border" : strength === "expression_only" ? "border border-dotted" : "border border-dashed";
              const dirIcon = eff.directionality === "concordant" ? "✓" : eff.directionality === "discordant" ? "✗" : eff.directionality === "mixed" ? "~" : "";
              const lagStr = eff.time_lag_minutes != null ? `lag:${eff.time_lag_minutes > 0 ? "+" : ""}${eff.time_lag_minutes}m` : "";
              return (
                <span
                  key={eff.gene}
                  className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                    strength === "expression_only"
                      ? (isUp
                          ? `bg-sky-900/20 text-sky-400 ${strengthBorder} border-sky-500/50`
                          : `bg-sky-900/20 text-sky-300 ${strengthBorder} border-sky-500/50`)
                      : (isUp
                          ? `bg-emerald-900/20 text-emerald-400 ${strengthBorder} border-emerald-500/50`
                          : `bg-rose-900/20 text-rose-400 ${strengthBorder} border-rose-500/50`)
                  }`}
                  title={`${eff.gene} | FC: ${eff.peak_fc > 0 ? "+" : ""}${eff.peak_fc.toFixed(2)} @ ${eff.peak_condition}\nEvidence: ${strength} (score ${eff.evidence_score || 0})\nDirection: ${eff.directionality || "unknown"} (${eff.concordant_count || 0}✓ / ${eff.discordant_count || 0}✗)\nTime-lag: ${lagStr || "N/A"}\nSubstrates: ${eff.connected_substrates.map(s => s.gene).join(", ")}\nSources: ${eff.sources.join(", ")}`}
                >
                  {isUp ? "▲" : "▼"}
                  {dirIcon && <span className={`mx-0.5 ${eff.directionality === "concordant" ? "text-emerald-300" : eff.directionality === "discordant" ? "text-rose-300" : "text-yellow-300"}`}>{dirIcon}</span>}
                  {eff.gene} ({eff.peak_fc > 0 ? "+" : ""}{eff.peak_fc.toFixed(1)})
                  {lagStr && <span className="ml-0.5 opacity-50 text-[8px]">{lagStr}</span>}
                </span>
              );
            })}

          </div>
          {/* Evidence strength legend */}
          <div className="flex items-center gap-3 text-[9px] text-muted-foreground">
            <span>Evidence: <span className="border-2 border-muted-foreground/30 px-1 rounded">strong</span></span>
            <span><span className="border border-muted-foreground/30 px-1 rounded">moderate</span></span>
            <span><span className="border border-dashed border-muted-foreground/30 px-1 rounded">weak</span></span>
            <span><span className="border border-dotted border-sky-500/50 px-1 rounded text-sky-400">expr. only</span></span>
            <span className="ml-2">✓ concordant</span>
            <span>✗ discordant</span>
            <span>~ mixed</span>
          </div>
          <div className="text-[10px] text-muted-foreground">
            Non-PTM proteins with significant protein abundance changes (|Log2FC| &gt; 0.3). PPI-connected proteins are scored by temporal concordance, directionality, and multi-substrate support. Expression-only proteins show abundance changes without known PPI links.
          </div>
        </div>
      )}

      {/* Ubiquitylation: Chain Type Distribution */}
      {isUbi && (() => {
        // Collect chain type distribution from members
        const chainCounts: Record<string, number> = {};
        kinase_modules.forEach(mod => {
          mod.members.forEach((m: any) => {
            const ct = (m.chain_type || "unknown").toLowerCase();
            const key = ct.startsWith("k") ? ct.toUpperCase() : ct;
            chainCounts[key] = (chainCounts[key] || 0) + 1;
          });
        });
        const total = Object.values(chainCounts).reduce((a, b) => a + b, 0);
        if (total === 0) return null;
        return (
          <div className="rounded-lg border p-3 space-y-2">
            <div className="text-xs font-semibold text-muted-foreground flex items-center gap-1">
              <Link2 className="h-3 w-3" /> Ubiquitin Chain Type Distribution
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(chainCounts).sort((a, b) => b[1] - a[1]).map(([ct, cnt]) => {
                const color = CHAIN_TYPE_COLORS[ct] || CHAIN_TYPE_COLORS.unknown;
                const pct = Math.round((cnt / total) * 100);
                return (
                  <div key={ct} className={`flex items-center gap-1 rounded px-2 py-1 border text-[10px] font-medium ${color.bg} ${color.text} ${color.border}`}>
                    <span>{color.label || ct}</span>
                    <span className="opacity-70">{cnt} ({pct}%)</span>
                  </div>
                );
              })}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1">
              K48 → proteasomal degradation &nbsp;|&nbsp; K63 → signaling/DNA repair &nbsp;|&nbsp; K11 → cell cycle &nbsp;|&nbsp; Mono → gene regulation
            </div>
          </div>
        );
      })()}

      {/* Top kinases / E3 ligases bar */}
      {summary.top_kinases && summary.top_kinases.length > 0 && (
        <div className="text-xs text-muted-foreground bg-muted/50 rounded p-2">
          <strong>{isUbi ? "Top E3 Ligases:" : "Top Kinases:"}</strong>{" "}
          {summary.top_kinases.map((k, i) => (
            <span key={k.canonical}>
              {i > 0 && " · "}
              <span className="font-medium text-foreground">{k.canonical}</span>
              <span className="text-[10px]"> ({k.total} {isUbi ? "sites" : "PTMs"})</span>
            </span>
          ))}
        </div>
      )}

      {/* Kinase Module Cards */}
      <div className="space-y-2">
        {kinase_modules.map((mod, idx) => {
          const colorIdx = idx % KINASE_MODULE_COLORS.length;
          const color = KINASE_MODULE_COLORS[colorIdx];
          const isExpanded = expandedKinase === mod.canonical;
          const memberKeys = mod.members.map((m) => m.key);

          return (
            <div
              key={mod.canonical}
              className={`rounded-lg border-2 ${color.border} ${color.bg} p-3 space-y-2`}
            >
              {/* Module header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setExpandedKinase(isExpanded ? null : mod.canonical)}
                    className={`flex items-center gap-1 text-sm font-bold ${color.text} hover:opacity-80`}
                  >
                    {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                    {mod.canonical}
                  </button>
                  <Badge variant="outline" className="text-[9px]">
                    {mod.total_count} {isUbi ? "sites" : "PTMs"}
                  </Badge>
                  {/* E3 family badge (ubiquitylation mode) */}
                  {isUbi && (() => {
                    const family = (mod as any).e3_family || "unknown";
                    const fc = E3_FAMILY_COLORS[family] || E3_FAMILY_COLORS.unknown;
                    return (
                      <Badge className={`text-[9px] border ${fc.bg} ${fc.text} ${fc.border}`}>
                        {family}
                      </Badge>
                    );
                  })()}
                  {/* Chain type badges (ubiquitylation mode) */}
                  {isUbi && (() => {
                    const chainTypes: Record<string, number> = {};
                    mod.members.forEach((m: any) => {
                      const ct = (m.chain_type || "unknown").toLowerCase();
                      const key = ct.startsWith("k") ? ct.toUpperCase() : ct;
                      chainTypes[key] = (chainTypes[key] || 0) + 1;
                    });
                    return Object.entries(chainTypes).slice(0, 3).map(([ct, cnt]) => {
                      const color = CHAIN_TYPE_COLORS[ct] || CHAIN_TYPE_COLORS.unknown;
                      return (
                        <Badge key={ct} className={`text-[9px] border ${color.bg} ${color.text} ${color.border}`}>
                          {ct} ×{cnt}
                        </Badge>
                      );
                    });
                  })()}
                  <Badge variant="outline" className="text-[9px] border-green-500 text-green-600 dark:text-green-400">
                    <ShieldCheck className="h-2.5 w-2.5 mr-0.5" />
                    {mod.confirmed_count} {isUbi ? "lit." : "confirmed"}
                  </Badge>
                  {mod.inferred_count > 0 && (
                    <Badge variant="outline" className="text-[9px] border-blue-500 text-blue-600 dark:text-blue-400">
                      <FlaskConical className="h-2.5 w-2.5 mr-0.5" />
                      {mod.inferred_count} {isUbi ? "degron" : "inferred"}
                    </Badge>
                  )}
                  <Badge variant="outline" className="text-[9px]">
                    {mod.source_count} sources
                  </Badge>
                </div>
                <div className="flex items-center gap-1">
                  {onSelectPtms && (() => {
                    const isActive = highlightedPtmKeys && highlightedPtmKeys.size > 0 &&
                      memberKeys.every((k) => highlightedPtmKeys.has(k)) &&
                      memberKeys.length === highlightedPtmKeys.size;
                    return (
                      <Button
                        variant={isActive ? "default" : "outline"}
                        size="sm"
                        className={`text-[10px] h-6 px-2 transition-colors ${isActive ? "bg-amber-500 hover:bg-amber-600 border-amber-500 text-white" : ""}`}
                        onClick={() => onSelectPtms(memberKeys)}
                      >
                        {isActive ? "★ Highlighted" : "Highlight in Chart"}
                      </Button>
                    );
                  })()}
                </div>
              </div>

              {/* Member PTMs as badges */}
              <div className="flex flex-wrap gap-1">
                {mod.members.map((m) => {
                  const chainType = isUbi ? ((m as any).chain_type || "unknown").toLowerCase() : null;
                  const chainKey = chainType ? (chainType.startsWith("k") ? chainType.toUpperCase() : chainType) : null;
                  const chainColor = chainKey ? (CHAIN_TYPE_COLORS[chainKey] || CHAIN_TYPE_COLORS.unknown) : null;
                  return (
                    <span
                      key={m.key}
                      className={`px-2 py-0.5 rounded-full text-[10px] flex items-center gap-0.5 border ${
                        m.membership === "confirmed"
                          ? "bg-green-100 dark:bg-green-900/30 border-green-400 text-green-700 dark:text-green-300"
                          : "bg-blue-100 dark:bg-blue-900/30 border-blue-400 text-blue-700 dark:text-blue-300"
                      }`}
                      title={`${m.gene} ${m.position} — ${m.membership}: ${m.evidence}${chainKey ? ` | Chain: ${chainKey}` : ""}`}
                    >
                      {m.membership === "confirmed" ? (
                        <ShieldCheck className="h-2.5 w-2.5" />
                      ) : (
                        <FlaskConical className="h-2.5 w-2.5" />
                      )}
                      {m.gene} {m.position}
                      {isUbi && chainKey && chainKey !== "unknown" && (
                        <span className={`ml-0.5 px-1 rounded text-[8px] font-bold ${chainColor?.bg} ${chainColor?.text}`}>
                          {chainKey}
                        </span>
                      )}
                    </span>
                  );
                })}
              </div>

              {/* Co-wave overlap badges */}
              {mod.cowave_overlap && mod.cowave_overlap.length > 0 && (
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                  <GitMerge className="h-3 w-3" />
                  Co-wave overlap:
                  {mod.cowave_overlap.map((ov) => (
                    <Badge key={ov.cowave_id} variant="outline" className="text-[9px]">
                      {ov.cowave_label} ({ov.shared_ptms.length} PTMs)
                    </Badge>
                  ))}
                </div>
              )}

              {/* Expanded: time-series mini-profile */}
              {isExpanded && (
                <div className="space-y-2 pt-2 border-t">

                  {/* Ubiquitylation-specific: E3 family, degron motifs, E2 partners */}
                  {isUbi && (() => {
                    const modAny = mod as any;
                    const family = modAny.e3_family || "unknown";
                    const degrons = modAny.degron_motifs || [];
                    const e2Partners = modAny.e2_partners || [];
                    const chainPreference = modAny.chain_preference || "unknown";
                    const fc = E3_FAMILY_COLORS[family] || E3_FAMILY_COLORS.unknown;
                    return (
                      <div className="rounded border p-2 space-y-1.5 bg-orange-50 dark:bg-orange-900/10 border-orange-200 dark:border-orange-800">
                        <div className="text-[10px] font-semibold text-orange-700 dark:text-orange-300 flex items-center gap-1">
                          <Boxes className="h-3 w-3" /> E3 Ligase Properties
                        </div>
                        <div className="flex flex-wrap gap-2 text-[10px]">
                          <span className="text-muted-foreground">Family:</span>
                          <span className={`px-1.5 py-0.5 rounded border font-medium ${fc.bg} ${fc.text} ${fc.border}`}>{family}</span>
                          {chainPreference !== "unknown" && (
                            <>
                              <span className="text-muted-foreground">Chain preference:</span>
                              {(() => {
                                const cc = CHAIN_TYPE_COLORS[chainPreference.toUpperCase()] || CHAIN_TYPE_COLORS.unknown;
                                return <span className={`px-1.5 py-0.5 rounded border font-medium ${cc.bg} ${cc.text} ${cc.border}`}>{chainPreference}</span>;
                              })()}
                            </>
                          )}
                        </div>
                        {degrons.length > 0 && (
                          <div className="flex items-center gap-1 flex-wrap">
                            <span className="text-[10px] text-muted-foreground">Degron motifs:</span>
                            {degrons.map((d: string) => (
                              <Badge key={d} className="text-[9px] bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-400">
                                <Scissors className="h-2.5 w-2.5 mr-0.5" />{d}
                              </Badge>
                            ))}
                          </div>
                        )}
                        {e2Partners.length > 0 && (
                          <div className="flex items-center gap-1 flex-wrap">
                            <span className="text-[10px] text-muted-foreground">E2 partners:</span>
                            {e2Partners.map((e2: string) => (
                              <Badge key={e2} variant="outline" className="text-[9px]">{e2}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Sources */}
                  <div className="text-[10px] text-muted-foreground">
                    <strong>Evidence sources:</strong>{" "}
                    {mod.sources.map((s) => {
                      const sl = SOURCE_LABELS[s];
                      return sl ? (
                        <span key={s} className={`inline-block px-1 py-0 rounded text-[9px] mr-1 ${sl.color}`}>
                          {sl.label}
                        </span>
                      ) : (
                        <span key={s} className="inline-block px-1 py-0 rounded text-[9px] mr-1 bg-muted">
                          {s}
                        </span>
                      );
                    })}
                  </div>

                  {/* Member detail table */}
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-[10px] h-7">PTM</TableHead>
                        <TableHead className="text-[10px] h-7">Status</TableHead>
                        {isUbi && <TableHead className="text-[10px] h-7">Chain Type</TableHead>}
                        <TableHead className="text-[10px] h-7">Evidence</TableHead>
                        <TableHead className="text-[10px] h-7">Time Profile</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {mod.members.map((m) => {
                        const timeValues = conditions.map((c) => {
                          const row = vectorData.find(
                            (v) => v.gene === m.gene && v.position === m.position && v.condition === c
                          );
                          return row?.value ?? 0;
                        });
                        const maxVal = Math.max(...timeValues.map(Math.abs), 1);
                        const chainType = isUbi ? ((m as any).chain_type || "unknown").toLowerCase() : null;
                        const chainKey = chainType ? (chainType.startsWith("k") ? chainType.toUpperCase() : chainType) : null;
                        const chainColor = chainKey ? (CHAIN_TYPE_COLORS[chainKey] || CHAIN_TYPE_COLORS.unknown) : null;

                        return (
                          <TableRow key={m.key}>
                            <TableCell className="text-[10px] font-medium py-1">
                              {m.gene} {m.position}
                            </TableCell>
                            <TableCell className="text-[10px] py-1">
                              <Badge
                                variant="outline"
                                className={`text-[9px] ${
                                  m.membership === "confirmed"
                                    ? "border-green-500 text-green-600"
                                    : "border-blue-500 text-blue-600"
                                }`}
                              >
                                {m.membership === "confirmed" ? (isUbi ? "literature" : "confirmed") : (isUbi ? "degron" : "inferred")}
                              </Badge>
                            </TableCell>
                            {isUbi && (
                              <TableCell className="text-[10px] py-1">
                                {chainKey && chainKey !== "unknown" ? (
                                  <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${chainColor?.bg} ${chainColor?.text} ${chainColor?.border}`}>
                                    {chainKey}
                                  </span>
                                ) : (
                                  <span className="text-muted-foreground text-[9px]">?</span>
                                )}
                              </TableCell>
                            )}
                            <TableCell className="text-[10px] py-1 max-w-[200px] truncate" title={m.evidence}>
                              {m.evidence}
                            </TableCell>
                            <TableCell className="py-1">
                              <div className="flex items-end gap-[2px] h-5">
                                {timeValues.map((v, ti) => (
                                  <div
                                    key={ti}
                                    className={`w-2 rounded-t ${v >= 0 ? "bg-blue-400" : "bg-red-400"}`}
                                    style={{ height: `${Math.max(2, (Math.abs(v) / maxVal) * 20)}px` }}
                                    title={`${conditions[ti]}: ${v.toFixed(2)}`}
                                  />
                                ))}
                              </div>
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
        })}
      </div>

      {/* Unassigned PTMs */}
      {unassigned_ptms.length > 0 && (
        <div className="rounded-lg border border-dashed p-3 space-y-2">
          <div className="flex items-center gap-2 text-xs">
            <HelpCircle className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="font-medium">Unassigned PTMs</span>
            <Badge variant="outline" className="text-[9px]">{unassigned_ptms.length}</Badge>
          </div>
          <div className="flex flex-wrap gap-1">
            {unassigned_ptms.map((p) => (
              <span
                key={p.key}
                className="px-2 py-0.5 rounded-full text-[10px] bg-muted border"
                title={p.motif_families.length > 0 ? `Motif: ${p.motif_families.join(", ")}` : "No kinase match"}
              >
                {p.gene} {p.position}
                {p.motif_families.length > 0 && (
                  <span className="text-[8px] ml-1 text-muted-foreground">({p.motif_families.join(", ")})</span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Co-wave × Kinase Module Cross Analysis */}
      {cowave_cross_analysis && Object.keys(cowave_cross_analysis).length > 0 && (
        <div className="space-y-2">
          <button
            onClick={() => setShowCrossAnalysis(!showCrossAnalysis)}
            className="flex items-center gap-1 text-xs font-medium hover:text-primary"
          >
            {showCrossAnalysis ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            <GitMerge className="h-3.5 w-3.5" />
            {isUbi ? "Co-wave × E3 Ligase Module Cross Analysis" : "Co-wave × Kinase Module Cross Analysis"}
          </button>

          {showCrossAnalysis && (
            <div className="space-y-2">
              <p className="text-[10px] text-muted-foreground">
                {isUbi
                  ? "Ubiquitylation sites that belong to the same E3 ligase module AND the same co-wave group have the strongest evidence for coordinated ubiquitylation — regulated by the same E3 AND moving together temporally."
                  : "PTMs that belong to the same kinase module AND the same co-wave group have the strongest evidence for shared regulation — they are regulated by the same kinase AND move together temporally."}
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-[10px] h-7">Co-wave Module</TableHead>
                    <TableHead className="text-[10px] h-7">{isUbi ? "Total Sites" : "Total PTMs"}</TableHead>
                    <TableHead className="text-[10px] h-7">{isUbi ? "Overlapping E3 Modules" : "Overlapping Kinase Modules"}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.values(cowave_cross_analysis).map((entry) => (
                    <TableRow key={entry.cowave_id}>
                      <TableCell className="text-[10px] font-medium py-1">{entry.cowave_label}</TableCell>
                      <TableCell className="text-[10px] py-1">{entry.total_ptms}</TableCell>
                      <TableCell className="text-[10px] py-1">
                        {entry.overlapping_kinases.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {entry.overlapping_kinases.map((ok) => {
                              const modIdx = kinase_modules.findIndex((m) => m.canonical === ok.canonical);
                              const colorIdx = modIdx >= 0 ? modIdx % KINASE_MODULE_COLORS.length : 0;
                              const c = KINASE_MODULE_COLORS[colorIdx];
                              return (
                                <span
                                  key={ok.canonical}
                                  className={`px-1.5 py-0.5 rounded text-[9px] border ${c.border} ${c.bg} ${c.text}`}
                                  title={`Shared PTMs: ${ok.shared_ptms.join(", ")}`}
                                >
                                  {ok.canonical} ({ok.shared_count})
                                </span>
                              );
                            })}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">No overlap</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}

      {/* Refresh button */}
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          className="text-xs"
          disabled={loading}
          onClick={onRun}
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Sparkles className="h-3 w-3 mr-1" />}
          Re-run Analysis
        </Button>
      </div>
    </div>
  );
}


// ── Signal Flow View (v9.21) ──────────────────────────────────────────────────
// Visualizes Receptor → Kinase → PTM signal chain

function SignalFlowView({
  inferredReceptors,
  globalKinaseResult,
  topNPtms,
  vectorData = [],
  conditions = [],
}: {
  inferredReceptors: InferredReceptor[];
  globalKinaseResult: GlobalKinaseModuleResponse | null;
  topNPtms: { gene: string; position: string; label: string }[];
  vectorData?: PtmTimeSeriesRow[];
  conditions?: string[];
}) {
  const [selectedReceptor, setSelectedReceptor] = useState<string | null>(null);
  const [showEffectors, setShowEffectors] = useState(true);

  // v9.34: Non-PTM effector proteins from API
  const effectorProteins = globalKinaseResult?.effector_proteins || [];
  const hasEffectors = effectorProteins.length > 0;

  // Build substrate → effector mapping
  const substrateToEffectors = useMemo(() => {
    const map: Record<string, EffectorProtein[]> = {};
    for (const eff of effectorProteins) {
      for (const sub of eff.connected_substrates) {
        const key = sub.gene.toUpperCase();
        if (!map[key]) map[key] = [];
        // Avoid duplicates
        if (!map[key].some(e => e.gene === eff.gene)) {
          map[key].push(eff);
        }
      }
    }
    return map;
  }, [effectorProteins]);

  // v9.25: Build PTM activity classification: de_novo | regulated | minor
  // Uses q_value (Welch's t-test + BH correction) when available
  const ptmActivityClass = useMemo(() => {
    const map: Record<string, "de_novo" | "regulated" | "minor"> = {};
    if (!vectorData.length || !conditions.length) return map;
    const baseline = conditions[0];
    const ptmKeys = new Set(vectorData.map(r => `${r.gene}_${r.position}`));
    for (const key of ptmKeys) {
      const rows = vectorData.filter(r => `${r.gene}_${r.position}` === key);
      const hasPseudocount = rows.some(r => r.control_pseudocount_used === true);
      const maxVal = Math.max(...rows.map(r => r.value));
      const minVal = Math.min(...rows.map(r => r.value));
      const maxAbsLog2FC = Math.max(Math.abs(maxVal), Math.abs(minVal));
      // Find minimum q_value across conditions
      const qValues = rows.map(r => r.q_value).filter((v): v is number => v != null && !isNaN(v));
      const minQVal = qValues.length > 0 ? Math.min(...qValues) : null;
      const hasQValue = minQVal != null;

      if (hasPseudocount) {
        map[key] = "de_novo";
      } else if (hasQValue) {
        // q_value available: Regulated = |Log2FC| >= 1.0 AND q_value < 0.05
        map[key] = (maxAbsLog2FC >= 1.0 && minQVal < 0.05) ? "regulated" : "minor";
      } else {
        // Fallback (old data without q_value): use maxAbsChange > 0.8
        const baselineVal = rows.find(r => r.condition === baseline)?.value ?? 0;
        const maxAbsChange = Math.max(Math.abs(maxVal - baselineVal), Math.abs(minVal - baselineVal));
        map[key] = maxAbsChange > 0.8 ? "regulated" : "minor";
      }
    }
    return map;
  }, [vectorData, conditions]);

  // Build kinase → PTM mapping from globalKinaseResult
  const kinaseToPtms = useMemo(() => {
    const map: Record<string, { gene: string; position: string; label: string; membership: string }[]> = {};
    if (!globalKinaseResult) return map;
    for (const mod of globalKinaseResult.kinase_modules) {
      const key = (mod.canonical || mod.kinase).toUpperCase();
      if (!map[key]) map[key] = [];
      for (const member of mod.members) {
        const ptmInfo = topNPtms.find(p => p.gene === member.gene && p.position === member.position);
        map[key].push({
          gene: member.gene,
          position: member.position,
          label: ptmInfo?.label || `${member.gene}_${member.position}`,
          membership: member.membership,
        });
      }
    }
    return map;
  }, [globalKinaseResult, topNPtms]);

  // Source color
  const sourceColor = (src?: string) => {
    if (src === "treatment_context" || src === "treatment_context_uniprot") return "#38bdf8";
    if (src === "reactome") return "#fb7185";
    return "#a78bfa";
  };

  // v9.37: Group receptors with identical kinase sets
  const groupedReceptors = useMemo(() => {
    const groups: Map<string, InferredReceptor[]> = new Map();
    const ungrouped: InferredReceptor[] = [];

    for (const rec of inferredReceptors) {
      const groupId = rec.kinase_group_id;
      if (groupId) {
        if (!groups.has(groupId)) groups.set(groupId, []);
        groups.get(groupId)!.push(rec);
      } else {
        ungrouped.push(rec);
      }
    }

    const result: { primary: InferredReceptor; members: InferredReceptor[] }[] = [];

    for (const [, members] of groups) {
      const sorted = [...members].sort(
        (a, b) => (b.downstream_ptm_count || 0) - (a.downstream_ptm_count || 0)
      );
      result.push({ primary: sorted[0], members: sorted });
    }

    for (const rec of ungrouped) {
      result.push({ primary: rec, members: [rec] });
    }

    return result.sort(
      (a, b) => (b.primary.downstream_ptm_count || 0) - (a.primary.downstream_ptm_count || 0)
    );
  }, [inferredReceptors]);

  const groupsToShow = selectedReceptor
    ? groupedReceptors.filter(g =>
        g.members.some(m => m.name === selectedReceptor)
      )
    : groupedReceptors.slice(0, 6);

  if (inferredReceptors.length === 0) {
    return (
      <div className="text-center py-8 text-sm text-muted-foreground">
        <GitBranch className="h-8 w-8 mx-auto mb-2 opacity-40" />
        No inferred receptors available. Visit the Vector Plot page to generate receptor inference.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground flex items-center gap-1">
          <GitBranch className="h-3.5 w-3.5 text-sky-400" />
          Signal chain: Upstream Receptor → Kinase → PTM substrate{hasEffectors ? " → Non-PTM Effector" : ""}
        </p>
        <div className="flex items-center gap-2">
          {hasEffectors && (
            <button
              className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                showEffectors
                  ? "bg-teal-50 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300 border-teal-400"
                  : "border-border text-muted-foreground hover:border-foreground/50"
              }`}
              onClick={() => setShowEffectors(!showEffectors)}
            >
              {showEffectors ? "◉" : "○"} Effectors ({effectorProteins.length})
            </button>
          )}
          {!globalKinaseResult && (
            <span className="text-[10px] text-amber-500 bg-amber-50 dark:bg-amber-900/20 px-2 py-0.5 rounded border border-amber-300">
              Run Global Annotate to see Kinase→PTM links
            </span>
          )}
        </div>
      </div>

      {/* Receptor selector — group-aware */}
      <div className="flex flex-wrap gap-1.5">
        <button
          className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
            selectedReceptor === null
              ? "bg-foreground text-background border-foreground"
              : "border-border text-muted-foreground hover:border-foreground/50"
          }`}
          onClick={() => setSelectedReceptor(null)}
        >
          All ({groupedReceptors.length} groups)
        </button>
        {groupedReceptors.map(({ primary, members }) => (
          <button
            key={primary.name}
            className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
              members.some(m => m.name === selectedReceptor)
                ? "bg-foreground text-background border-foreground"
                : "border-border text-muted-foreground hover:border-foreground/50"
            }`}
            onClick={() => setSelectedReceptor(
              primary.name === selectedReceptor ? null : primary.name
            )}
          >
            {members.length > 1
              ? `${primary.name.length > 12 ? primary.name.slice(0, 10) + "…" : primary.name} +${members.length - 1}`
              : primary.name.length > 20 ? primary.name.slice(0, 18) + "…" : primary.name
            }
            {primary.uniqueness_score != null && (
              <span className={`ml-1 text-[8px] ${
                (primary.uniqueness_score || 0) > 0.6 ? "text-green-400" :
                (primary.uniqueness_score || 0) > 0.3 ? "text-yellow-400" : "text-red-400"
              }`}>
                {((primary.uniqueness_score || 0) * 100).toFixed(0)}%
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Flow chains — grouped */}
      <div className="space-y-3">
        {groupsToShow.map(({ primary, members }) => {
          const viaKinases = primary.via_kinases || [];
          const isGrouped = members.length > 1;

          return (
            <div key={primary.name} className="rounded-lg border bg-card/50 p-3 space-y-2">
              {/* Receptor node(s) */}
              <div className="flex items-center gap-2 flex-wrap">
                {members.map((rec, i) => (
                  <div
                    key={rec.name}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border-2 text-xs font-semibold"
                    style={{
                      borderColor: sourceColor(rec.source),
                      color: sourceColor(rec.source),
                      backgroundColor: `${sourceColor(rec.source)}18`,
                      opacity: i === 0 ? 1 : 0.75,
                    }}
                  >
                    <Activity className="h-3 w-3" />
                    {rec.name}
                  </div>
                ))}
                <span className="text-[10px] text-muted-foreground">
                  {primary.receptor_class} · {primary.downstream_ptm_count} PTMs ·{" "}
                  <span style={{ color: sourceColor(primary.source) }}>
                    {primary.source === "treatment_context" ? "T" : primary.source === "reactome" ? "R" : "L"}
                  </span>
                </span>
                {isGrouped && (
                  <span className="text-[9px] text-amber-500 bg-amber-50 dark:bg-amber-900/20 px-1.5 py-0.5 rounded border border-amber-300/50">
                    {members.length} receptors share identical kinase pathway
                  </span>
                )}
                {primary.has_receptor_specific_db === false && (
                  <span className="text-[9px] text-muted-foreground/50 bg-muted/50 px-1.5 py-0.5 rounded">
                    Limited kinase mapping
                  </span>
                )}
                {primary.uniqueness_score != null && (
                  <div className="flex items-center gap-1 text-[9px] text-muted-foreground ml-auto">
                    <div className="w-10 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${(primary.uniqueness_score || 0) * 100}%`,
                          backgroundColor: (primary.uniqueness_score || 0) > 0.6
                            ? "#22c55e"
                            : (primary.uniqueness_score || 0) > 0.3
                            ? "#eab308"
                            : "#ef4444",
                        }}
                      />
                    </div>
                    <span>{((primary.uniqueness_score || 0) * 100).toFixed(0)}%</span>
                  </div>
                )}
              </div>

              {/* Kinase layer */}
              {viaKinases.length > 0 ? (
                <div className="ml-4 space-y-2">
                  <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                    <ArrowRight className="h-3 w-3" />
                    <span>via kinases:</span>
                  </div>
                  <div className="flex flex-wrap gap-2 ml-4">
                    {viaKinases.map(kinase => {
                      const kinaseKey = kinase.toUpperCase();
                      const ptms = kinaseToPtms[kinaseKey] || [];
                      const isUnique = primary.unique_kinases?.includes(kinase);

                      return (
                        <div key={kinase} className="space-y-1">
                          <div className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
                            isUnique
                              ? "border-2 border-amber-400 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300"
                              : "border border-dashed border-amber-400/50 bg-amber-50/50 dark:bg-amber-900/10 text-amber-700/60 dark:text-amber-300/60"
                          }`}>
                            <Zap className="h-2.5 w-2.5" />
                            {kinase}
                            {isUnique && <span className="ml-0.5 text-[8px] text-amber-500">★</span>}
                          </div>
                          {/* PTM substrates */}
                          {ptms.length > 0 && (
                            <div className="ml-2 space-y-0.5">
                              <div className="flex items-center gap-0.5 text-[9px] text-muted-foreground">
                                <ArrowRight className="h-2.5 w-2.5" />
                                <span>{ptms.length} substrates:</span>
                              </div>
                              <div className="flex flex-wrap gap-1 ml-3">
                                {ptms.map(ptm => {
                                  const ptmKey = `${ptm.gene}_${ptm.position}`;
                                  const actClass = ptmActivityClass[ptmKey] || "minor";
                                  const chipStyle =
                                    actClass === "de_novo"
                                      ? "bg-orange-900/30 text-orange-300 border border-orange-500 font-semibold"
                                      : actClass === "regulated"
                                      ? "bg-blue-900/30 text-blue-300 border border-blue-500 font-semibold"
                                      : "bg-green-900/30 text-green-300 border border-green-500";
                                  const actLabel =
                                    actClass === "de_novo" ? "De novo (control imputed)" :
                                    actClass === "regulated" ? "Regulated (|Log2FC| ≥ 1.0 AND q < 0.05)" :
                                    "Minor (sub-threshold)";
                                  return (
                                    <span
                                      key={ptmKey}
                                      className={`text-[9px] px-1.5 py-0.5 rounded ${chipStyle}`}
                                      title={`${ptm.gene} ${ptm.position} | ${actLabel} | kinase evidence: ${ptm.membership}`}
                                    >
                                      {actClass === "de_novo" && <span className="mr-0.5">★</span>}
                                      {actClass === "regulated" && <span className="mr-0.5">●</span>}
                                      {actClass === "minor" && <span className="mr-0.5">◇</span>}
                                      {ptm.label || ptmKey}
                                    </span>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                          {ptms.length === 0 && globalKinaseResult && (
                            <div className="ml-2 text-[9px] text-muted-foreground/50">
                              no annotated substrates in current PTM set
                            </div>
                          )}

                          {/* 4th Layer: Non-PTM Effectors */}
                          {showEffectors && ptms.length > 0 && (() => {
                            const kinaseEffectors: EffectorProtein[] = [];
                            const seen = new Set<string>();
                            for (const ptm of ptms) {
                              const geneKey = ptm.gene.toUpperCase();
                              const effs = substrateToEffectors[geneKey] || [];
                              for (const e of effs) {
                                if (!seen.has(e.gene)) {
                                  seen.add(e.gene);
                                  kinaseEffectors.push(e);
                                }
                              }
                            }
                            if (kinaseEffectors.length === 0) return null;
                            return (
                              <div className="ml-2 mt-1 space-y-0.5">
                                <div className="flex items-center gap-0.5 text-[9px] text-muted-foreground">
                                  <ArrowRight className="h-2.5 w-2.5 text-teal-400" />
                                  <span className="text-teal-400">{kinaseEffectors.length} Non-PTM effectors:</span>
                                </div>
                                <div className="flex flex-wrap gap-1 ml-3">
                                  {kinaseEffectors.slice(0, 8).map(eff => {
                                    const isUp = eff.peak_fc > 0;
                                    const strength = eff.evidence_strength || "weak";
                                    const strengthBorder = strength === "strong" ? "border-2" : strength === "moderate" ? "border" : strength === "expression_only" ? "border border-dotted" : "border border-dashed";
                                    const chipStyle = isUp
                                      ? `bg-emerald-900/30 text-emerald-300 ${strengthBorder} border-emerald-500`
                                      : `bg-rose-900/30 text-rose-300 ${strengthBorder} border-rose-500`;
                                    const arrow = isUp ? "▲" : "▼";
                                    const dirIcon = eff.directionality === "concordant" ? "✓" : eff.directionality === "discordant" ? "✗" : eff.directionality === "mixed" ? "~" : "";
                                    const lagStr = eff.time_lag_minutes != null ? `${eff.time_lag_minutes > 0 ? "+" : ""}${eff.time_lag_minutes}min` : "";
                                    return (
                                      <span
                                        key={eff.gene}
                                        className={`text-[9px] px-1.5 py-0.5 rounded ${chipStyle}`}
                                        title={`${eff.gene} | FC: ${eff.peak_fc > 0 ? "+" : ""}${eff.peak_fc.toFixed(2)} @ ${eff.peak_condition}\nEvidence: ${strength} (score ${eff.evidence_score || 0})\nDirection: ${eff.directionality || "unknown"} (${eff.concordant_count || 0} concordant / ${eff.discordant_count || 0} discordant)\nTime-lag: ${lagStr || "N/A"}\nSubstrates: ${eff.connected_substrates.map(s => `${s.gene}${s.concordant ? "✓" : "✗"}`).join(", ")}\nSources: ${eff.sources.join(", ")}`}
                                      >
                                        <span className="mr-0.5">{arrow}</span>
                                        {dirIcon && <span className={`mr-0.5 ${eff.directionality === "concordant" ? "text-emerald-400" : eff.directionality === "discordant" ? "text-rose-400" : "text-yellow-400"}`}>{dirIcon}</span>}
                                        {eff.gene}
                                        <span className="ml-0.5 opacity-70">{eff.peak_fc > 0 ? "+" : ""}{eff.peak_fc.toFixed(1)}</span>
                                        {lagStr && <span className="ml-0.5 opacity-50 text-[8px]">{lagStr}</span>}
                                      </span>
                                    );
                                  })}
                                  {kinaseEffectors.length > 8 && (
                                    <span className="text-[9px] text-muted-foreground/50">+{kinaseEffectors.length - 8} more</span>
                                  )}
                                </div>
                              </div>
                            );
                          })()}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="ml-4 text-[10px] text-muted-foreground/50 flex items-center gap-1">
                  <ArrowRight className="h-3 w-3" />
                  Direct receptor (no intermediate kinase mapping)
                  {primary.downstream_ptms?.length > 0 && (
                    <span className="ml-1">→ {primary.downstream_ptms.slice(0, 3).join(", ")}{primary.downstream_ptms.length > 3 ? ` +${primary.downstream_ptms.length - 3}` : ""}</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="space-y-1.5 pt-1 border-t">
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
          <span className="font-medium text-muted-foreground/70">Receptor source:</span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-sky-400 inline-block" /> Treatment context (T)
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-rose-400 inline-block" /> Reactome (R)
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-violet-400 inline-block" /> Literature (L)
          </span>
        </div>
        {/* v9.37: Kinase specificity legend */}
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
          <span className="font-medium text-muted-foreground/70">Kinase specificity:</span>
          <span className="flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 border-2 border-amber-400 text-[9px]">★ Unique</span>
            <span className="text-[9px]">receptor-specific kinase (from curated DB)</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-amber-50/50 dark:bg-amber-900/10 text-amber-700/60 dark:text-amber-300/60 border border-dashed border-amber-400/50 text-[9px]">Shared</span>
            <span className="text-[9px]">kinase shared across multiple receptors</span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
          <span className="font-medium text-muted-foreground/70">Uniqueness score:</span>
          <span className="flex items-center gap-1">
            <span className="w-6 h-1.5 rounded-full bg-green-500 inline-block" />
            <span className="text-[9px]">&gt;60% — highly unique kinase set</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="w-6 h-1.5 rounded-full bg-yellow-500 inline-block" />
            <span className="text-[9px]">30–60% — moderate overlap</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="w-6 h-1.5 rounded-full bg-red-500 inline-block" />
            <span className="text-[9px]">&lt;30% — mostly shared (consider grouping)</span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
          <span className="font-medium text-muted-foreground/70">DB coverage:</span>
          <span className="flex items-center gap-1">
            <span className="text-[9px] bg-muted/50 px-1.5 py-0.5 rounded">Limited kinase mapping</span>
            <span className="text-[9px]">receptor not in curated DB (82 receptors) — class-level fallback used</span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
          <span className="font-medium text-muted-foreground/70">Substrate activity:</span>
          <span className="flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-red-900/30 text-red-300 border border-red-500 text-[9px]">★ De novo</span>
            <span className="text-[9px]">not detected in control (imputed)</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-emerald-900/30 text-emerald-300 border border-emerald-500 text-[9px]">● Regulated</span>
            <span className="text-[9px]">detected in control, meaningful change</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-green-900/30 text-green-300 border border-green-500 text-[9px]">◇ Minor</span>
            <span className="text-[9px]">sub-threshold but patterned</span>
          </span>
        </div>
        {hasEffectors && (
          <div className="space-y-1.5">
            {/* Row 1: Direction (Up/Down) */}
            <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
              <span className="font-medium text-muted-foreground/70 w-[110px] shrink-0">Non-PTM Effector:</span>
              <span className="flex items-center gap-1">
                <span className="px-1.5 py-0.5 rounded bg-emerald-900/30 text-emerald-300 border border-emerald-500 text-[9px]">▲ Up</span>
                <span className="text-[9px]">Protein abundance increased</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="px-1.5 py-0.5 rounded bg-rose-900/30 text-rose-300 border border-rose-500 text-[9px]">▼ Down</span>
                <span className="text-[9px]">Protein abundance decreased</span>
              </span>
              <span className="text-[9px] text-muted-foreground/50 ml-1">
                ({effectorProteins.length} proteins via STRING/BioGRID, |Log2FC| &gt; 0.3)
              </span>
            </div>
            {/* Row 2: Directionality (concordant/discordant/mixed) */}
            <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
              <span className="font-medium text-muted-foreground/70 w-[110px] shrink-0">Directionality:</span>
              <span className="flex items-center gap-1">
                <span className="text-emerald-400 font-bold text-[10px]">✓</span>
                <span className="text-[9px]">Concordant — effector changes in same direction as substrate PTM</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="text-rose-400 font-bold text-[10px]">✗</span>
                <span className="text-[9px]">Discordant — effector changes in opposite direction</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="text-yellow-400 font-bold text-[10px]">~</span>
                <span className="text-[9px]">Mixed — inconsistent across substrates</span>
              </span>
            </div>
            {/* Row 3: Evidence strength (border style) */}
            <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
              <span className="font-medium text-muted-foreground/70 w-[110px] shrink-0">Evidence strength:</span>
              <span className="flex items-center gap-1">
                <span className="px-1.5 py-0.5 rounded bg-muted/30 text-muted-foreground border-2 border-muted-foreground/50 text-[9px]">Strong</span>
                <span className="text-[9px]">thick solid border (score ≥ 6)</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="px-1.5 py-0.5 rounded bg-muted/30 text-muted-foreground border border-muted-foreground/50 text-[9px]">Moderate</span>
                <span className="text-[9px]">thin solid border (score 4–5)</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="px-1.5 py-0.5 rounded bg-muted/30 text-muted-foreground border border-dashed border-muted-foreground/50 text-[9px]">Weak</span>
                <span className="text-[9px]">dashed border (score &lt; 4)</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="px-1.5 py-0.5 rounded bg-muted/30 text-muted-foreground border border-dotted border-muted-foreground/50 text-[9px]">Expr.</span>
                <span className="text-[9px]">dotted border (expression-only, no PPI)</span>
              </span>
            </div>
            {/* Row 4: Chip format explanation */}
            <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
              <span className="font-medium text-muted-foreground/70 w-[110px] shrink-0">Chip format:</span>
              <span className="px-1.5 py-0.5 rounded bg-emerald-900/30 text-emerald-300 border border-emerald-500 text-[9px]">▲ ✓ GENE +1.7 +3min</span>
              <span className="text-[9px] text-muted-foreground/60">= direction · directionality · gene name · peak Log2FC · time-lag vs substrate PTM</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
