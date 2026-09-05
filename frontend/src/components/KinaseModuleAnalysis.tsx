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

import { useState, useMemo, useCallback, useEffect, useRef, Fragment } from "react";
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
  RefreshCw,
  Target,
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
import IPOverlayView from "@/components/IPOverlayView";
import { TEMPORAL_TERMS, formatLocalTransitionStatus, formatTemporalClusterLabel } from "@/lib/temporal-terminology";

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
  activity_class?: "de_novo" | "regulated" | "coordinated" | "minor";
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
  activity_class_counts: { de_novo: number; regulated: number; coordinated: number; minor: number };
  dominant_activity_class: "de_novo" | "regulated" | "coordinated" | "minor";
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
  temporal_filter_applied?: boolean;
  original_total_count?: number;
  enriched_patterns?: string[];
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
  // v9.44: Co-wave confidence scoring
  confidence_score?: number;
  cowave_boost?: number;
  // v11.1: Temporal substrate refinement
  temporal_filter_applied?: boolean;
  original_total_count?: number;
  enriched_clusters?: number[];
  enriched_patterns?: string[];
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
  temporal_ptm_protein_analysis?: {
    status?: string;
    full_artifact_available?: boolean;
    dynamic_co_wave_transition_status?: string;
    dynamic_co_wave_transition_contract_version?: string;
    dynamic_co_wave_transition_config_sha256?: string;
    dynamic_transition_supported_wave_count?: number;
  };
  // v9.44: Cache metadata
  _cached?: boolean;
  _cache_hash?: string;
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
  cowave_score?: number;
  confidence_score?: number;
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
  ipOverlayData?: Record<string, unknown> | null; // saved IP overlay state from order
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
  // v9.44: compute activity_class per PTM from vectorData with co-wave confidence boost
  const ptmActivityClassMap = new Map<string, "de_novo" | "regulated" | "coordinated" | "minor">();
  ptms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    const series = conditions.map((cond) => {
      const row = vectorData.find(
        (r) => r.gene === p.gene && r.position === p.position && r.condition === cond
      );
      return row?.value ?? 0;
    });
    ptmSeries.set(key, series);

    // Determine base activity_class: check all rows for this PTM across conditions
    const rows = vectorData.filter((r) => r.gene === p.gene && r.position === p.position);
    const isDenovo = rows.some((r) => r.control_pseudocount_used === true);
    const maxAbsFC = Math.max(...series.map(Math.abs));
    const qValues = rows.map((r) => r.q_value).filter((v): v is number => v != null && !isNaN(v));
    const minQValue = qValues.length > 0 ? Math.min(...qValues) : null;
    const hasQValue = minQValue != null;
    let actClass: "de_novo" | "regulated" | "coordinated" | "minor";
    if (isDenovo) {
      actClass = "de_novo";
    } else if (hasQValue) {
      actClass = (minQValue < 0.05 && maxAbsFC >= 1.0) ? "regulated" : "minor";
    } else {
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

    // v9.44: Co-wave Confidence Boost — upgrade "minor" PTMs to "coordinated"
    // Rationale: If a PTM is sub-threshold individually but moves in concert with
    // 2+ other PTMs at the same timepoint, it represents a coordinated signaling event.
    // Boost criteria:
    //   - Group has 3+ PTMs (coordinated movement is statistically meaningful)
    //   - PTM has |Log2FC| >= 0.5 at peak (not just noise)
    //   - At least 1 other PTM in the group is de_novo or regulated (anchor signal)
    const hasAnchorSignal = groupPtms.some((p) => {
      const ac = ptmActivityClassMap.get(`${p.gene}_${p.position}`) ?? "minor";
      return ac === "de_novo" || ac === "regulated";
    });
    const groupSizeThreshold = 3;
    const cowaveBoostFcThreshold = 0.5;

    if (groupPtms.length >= groupSizeThreshold && hasAnchorSignal) {
      groupPtms.forEach((p) => {
        const key = `${p.gene}_${p.position}`;
        const currentClass = ptmActivityClassMap.get(key) ?? "minor";
        if (currentClass === "minor") {
          // Check if this PTM has meaningful signal at peak
          const series = ptmSeries.get(key) || [];
          const peakIdx = conditions.indexOf(peakCond);
          const peakFc = peakIdx >= 0 ? Math.abs(series[peakIdx]) : 0;
          if (peakFc >= cowaveBoostFcThreshold) {
            ptmActivityClassMap.set(key, "coordinated");
            // Also update the PtmInfo's activity_class in-place
            p.activity_class = "coordinated";
          }
        }
      });
    }

    // v9.44: activity class statistics (includes coordinated)
    const class_counts = { de_novo: 0, regulated: 0, coordinated: 0, minor: 0 };
    groupPtms.forEach((p) => {
      const key = `${p.gene}_${p.position}`;
      const ac = ptmActivityClassMap.get(key) ?? "minor";
      p.activity_class = ac; // ensure PtmInfo reflects final class
      class_counts[ac] = (class_counts[ac] ?? 0) + 1;
    });
    const dominant_activity_class: "de_novo" | "regulated" | "coordinated" | "minor" =
      class_counts.de_novo > 0 ? "de_novo" :
      class_counts.regulated > 0 ? "regulated" :
      class_counts.coordinated > 0 ? "coordinated" : "minor";

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

const STATUS_CONFIG_BASE = {
  known: {
    icon: ShieldCheck,
    label: "Known Kinase",
    labelUbi: "Known E3 Ligase",
    color: "text-green-600 dark:text-green-400",
    bg: "bg-green-50 dark:bg-green-900/20",
    border: "border-green-300 dark:border-green-700",
    badgeCls: "border-green-500 text-green-700 dark:text-green-400",
  },
  motif_only: {
    icon: FlaskConical,
    label: "Motif Predicted",
    labelUbi: "Motif Predicted",
    color: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-50 dark:bg-amber-900/20",
    border: "border-amber-300 dark:border-amber-700",
    badgeCls: "border-amber-500 text-amber-700 dark:text-amber-400",
  },
  novel_candidate: {
    icon: Sparkles,
    label: "Novel Candidate",
    labelUbi: "Novel Candidate",
    color: "text-purple-600 dark:text-purple-400",
    bg: "bg-purple-50 dark:bg-purple-900/20",
    border: "border-purple-300 dark:border-purple-700",
    badgeCls: "border-purple-500 text-purple-700 dark:text-purple-400",
  },
} as const;
const STATUS_CONFIG = STATUS_CONFIG_BASE;

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
  ipOverlayData,
}: KinaseModuleAnalysisProps) {
  const isUbi = ptmType.toLowerCase().includes("ubiquityl") || ptmType.toLowerCase().includes("ubiquitin");
  const [activeTab, setActiveTab] = useState<"cowave" | "lookup" | "cascade" | "kinaseModules" | "signalFlow" | "heatmap" | "cascadeTimeline" | "chainLinkage" | "ipOverlay">("cowave");
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());
  const [manualSelection, setManualSelection] = useState<Set<string>>(new Set());
   const [internalHighlightedKinase, setInternalHighlightedKinase] = useState<string | null>(null);
  const [highlightedCwGroup, setHighlightedCwGroup] = useState<number | null>(null);
  const [highlightedCwGroupKinases, setHighlightedCwGroupKinases] = useState<string[]>([]);
  // Merge external highlightedKinase (from receptor panel) with internal (from heatmap/timeline click)
  const effectiveHighlightedKinase = internalHighlightedKinase || highlightedKinase || null;

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
  const temporalArtifactReady = Boolean(
    globalKinaseResult?.temporal_ptm_protein_analysis?.full_artifact_available &&
    globalKinaseResult?.temporal_ptm_protein_analysis?.dynamic_co_wave_transition_status === "computed" &&
    globalKinaseResult?.temporal_ptm_protein_analysis?.dynamic_co_wave_transition_contract_version === "dynamic_co_wave_transition.v2"
  );

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

  // ── Auto-load cached Global Annotate result on mount ─────────────────────
  useEffect(() => {
    if (globalKinaseResult || globalKinaseLoading) return; // already loaded or loading
    if (topNPtms.length === 0) return; // no PTMs yet
    // Try to load from cache (force_refresh=false → instant if cached)
    const loadCached = async () => {
      try {
        const allPtms = topNPtms;
        console.log(`[GLOBAL-KINASE] Cache probe: sending ${Math.min(5, allPtms.length)} PTMs for order ${orderId}`);
        const result = await api.post<GlobalKinaseModuleResponse>(
          `/orders/${orderId}/global-kinase-modules`,
          {
            ptms: allPtms.slice(0, 5).map((p) => ({ gene: p.gene, position: p.position })),
            cowave_modules: [],
            force_refresh: false,
            _cache_probe: true, // signal that this is a cache probe, not full computation
          }
        );
        console.log(`[GLOBAL-KINASE] Cache probe response: _cached=${result._cached}, modules=${result.kinase_modules?.length ?? 0}`);
        if (result._cached && result.kinase_modules) {
          // Accept cached result even if kinase_modules is empty (valid cached state)
          setGlobalKinaseResult(result);
          console.log(`[GLOBAL-KINASE] Auto-loaded from cache on mount: ${result.kinase_modules.length} modules`);
        }
      } catch (err) {
        console.error("[GLOBAL-KINASE] Cache probe failed:", err);
        // Silently fail — user can click Global Annotate manually
      }
    };
    loadCached();
  }, [orderId, topNPtms.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const runGlobalKinaseModules = useCallback(async (forceRefresh = false) => {
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
        setGlobalKinaseBatchProgress({ current: 1, total: 1, phase: forceRefresh ? "Re-analyzing..." : "Annotating..." });
        const result = await api.post<GlobalKinaseModuleResponse>(
          `/orders/${orderId}/global-kinase-modules`,
          {
            ptms: allPtms.map((p) => ({ gene: p.gene, position: p.position })),
            cowave_modules: cowaveModulesPayload,
            force_refresh: forceRefresh,
          }
        );
        setGlobalKinaseResult(result);
        setActiveTab("kinaseModules");
        if (result._cached) {
          console.log("[GLOBAL-KINASE] Loaded from cache (instant). Use force_refresh to re-run.");
        } else {
          // Ensure result is persisted to DB (backup save in case API's internal save failed)
          try {
            await api.post(`/orders/${orderId}/save-kinase-analysis-data`, {
              kinase_modules: (result.kinase_modules || []).map((km) => ({
                ...km,
                members: km.members.map((m) => ({ key: m.key, gene: m.gene, position: m.position, membership: m.membership })),
              })),
              temporal_cascade: result.temporal_cascade || {},
              cowave_cross_analysis: result.cowave_cross_analysis || {},
              summary: result.summary || {},
              effector_proteins: (result.effector_proteins || []).map((eff) => ({
                gene: eff.gene, data_type: eff.data_type, max_abs_fc: eff.max_abs_fc,
                peak_condition: eff.peak_condition, peak_fc: eff.peak_fc,
                sources: eff.sources, evidence_strength: eff.evidence_strength,
                evidence_score: eff.evidence_score, directionality: eff.directionality,
                connected_substrates: eff.connected_substrates,
              })),
              wave_kinase_profile: result.wave_kinase_profile || [],
              _cache_hash: result._cache_hash || "",
            });
            console.log("[GLOBAL-KINASE] Single-batch result saved to DB (backup)");
          } catch (saveErr) {
            console.warn("[GLOBAL-KINASE] Backup save failed (non-fatal):", saveErr);
          }
        }
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
            force_refresh: forceRefresh,
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
          _cache_hash: mergedResult._cache_hash || "",
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
            ? "Temporal module detection, E3 Ligase annotation (RING/HECT/RBR), Ubiquitin chain type classification (K48/K63/Mono), and Phospho-Ub cross-talk inference."
            : "Temporal phosphosite trajectory clustering, multi-source kinase annotation (8 sources + motif prediction), and contextual footprint display. Similar trajectories are grouped for inspection; cluster membership alone does not establish a shared regulator, pathway, or causal cascade."}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Tab navigation */}
        <div className="flex gap-1 border-b pb-2">
          <Button
            variant={activeTab === "cowave" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => { setActiveTab("cowave"); setInternalHighlightedKinase(null); }}
          >
            <GitMerge className="h-3 w-3 mr-1" /> {isUbi ? "Temporal Modules" : TEMPORAL_TERMS.clusters}
          </Button>
          <Button
            variant={activeTab === "lookup" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => { setActiveTab("lookup"); setInternalHighlightedKinase(null); }}
          >
            <Search className="h-3 w-3 mr-1" /> {isUbi ? "E3 Lookup" : "Kinase Lookup"}
          </Button>
          <Button
            variant={activeTab === "cascade" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => { setActiveTab("cascade"); setInternalHighlightedKinase(null); }}
          >
            <BarChart3 className="h-3 w-3 mr-1" /> {isUbi ? "Ubi Temporal Context" : "Temporal Context"}
          </Button>
          <Button
            variant={activeTab === "kinaseModules" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => { setActiveTab("kinaseModules"); setInternalHighlightedKinase(null); }}
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
          {globalKinaseResult && (
            <Button
              variant={activeTab === "heatmap" ? "default" : "ghost"}
              size="sm"
              className="text-xs h-7"
              onClick={() => setActiveTab("heatmap")}
            >
              <Activity className="h-3 w-3 mr-1" /> {isUbi ? "E3 Heatmap" : "Kinase Heatmap"}
            </Button>
          )}
          {globalKinaseResult && conditions.length > 1 && (
            <Button
              variant={activeTab === "cascadeTimeline" ? "default" : "ghost"}
              size="sm"
              className="text-xs h-7"
              onClick={() => setActiveTab("cascadeTimeline")}
            >
            <Clock className="h-3 w-3 mr-1" /> Temporal Context Timeline
            </Button>
          )}
          {isUbi && (
            <Button
              variant={activeTab === "chainLinkage" ? "default" : "ghost"}
              size="sm"
              className="text-xs h-7"
              onClick={() => setActiveTab("chainLinkage")}
            >
              <Link2 className="h-3 w-3 mr-1" /> Chain Linkage
            </Button>
          )}
          <Button
            variant={activeTab === "ipOverlay" ? "default" : "ghost"}
            size="sm"
            className="text-xs h-7"
            onClick={() => setActiveTab("ipOverlay")}
          >
            <Target className="h-3 w-3 mr-1" /> IP Overlay
          </Button>
          <div className="ml-auto">
            {temporalArtifactReady && (
              <span className="mr-2 inline-flex items-center rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-[10px] font-medium text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-200">
                Temporal phosphorylation–protein artifact ready
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              className="text-xs h-7 border-amber-400 text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-900/20"
              disabled={globalKinaseLoading || checkedPtmList.length === 0}
              onClick={() => runGlobalKinaseModules(false)}
            >
              {globalKinaseLoading ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <Sparkles className="h-3 w-3 mr-1" />
              )}
              {globalKinaseLoading
                ? "Analyzing..."
                : isUbi
                  ? (globalKinaseResult ? "Re-run E3 Annotation" : "E3 Annotate")
                  : (globalKinaseResult ? "Re-run Global Annotation" : "Global Annotate")}
              <Badge variant="outline" className="text-[9px] ml-1 h-4 px-1">
                {checkedPtmList.length} PTMs
              </Badge>
            </Button>
            {globalKinaseResult && (
              <Button
                variant="ghost"
                size="sm"
                className="text-xs h-7 text-muted-foreground hover:text-amber-600"
                disabled={globalKinaseLoading}
                onClick={() => runGlobalKinaseModules(true)}
                title="Ignore cache and re-run full analysis"
              >
                <RefreshCw className="h-3 w-3 mr-1" />
                Refresh
              </Button>
            )}
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

        {/* ── Tab: Temporal Profile Clusters (internal tab key: cowave) ────────── */}
        {activeTab === "cowave" && (
          <div className="space-y-3">
            {conditions.length < 3 && (
              <Alert>
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Insufficient Time Points</AlertTitle>
                <AlertDescription className="text-xs">
                  {isUbi ? "Temporal module" : "Temporal phosphosite cluster"} detection requires at least 3 time points. Current: {conditions.length}
                </AlertDescription>
              </Alert>
            )}

            {coWaveModules.length === 0 && conditions.length >= 3 && (
              <div className="text-center py-6 text-sm text-muted-foreground">
                <Info className="h-8 w-8 mx-auto mb-2 opacity-40" />
                No {isUbi ? "temporal" : TEMPORAL_TERMS.cluster} detected. Enable more phosphorylation features in the checklist above, or try a different trend filter.
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
                        {formatTemporalClusterLabel(mod.label)}
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
                      {/* v9.48.2: Linked Heatmap CW Groups — use cowave_cross_analysis */}
                      {globalKinaseResult?.cowave_cross_analysis && (() => {
                        const crossEntry = globalKinaseResult.cowave_cross_analysis[`module_${mod.id}`];
                        if (!crossEntry || !crossEntry.overlapping_kinases?.length) return null;
                        const kinaseNames = crossEntry.overlapping_kinases.map((k) => k.canonical);
                        return (
                          <Badge
                            variant="outline"
                            className="text-[9px] border-cyan-500 text-cyan-600 dark:text-cyan-400 cursor-help"
                            title={`Linked ${isUbi ? "E3 ligases" : "kinases"} (Heatmap): ${kinaseNames.slice(0, 6).join(", ")}${kinaseNames.length > 6 ? "..." : ""}\nThese ${isUbi ? "E3 ligases" : "kinases"} have annotated phosphorylation features represented in this ${isUbi ? "temporal" : TEMPORAL_TERMS.cluster}. This is contextual display only.\nSwitch to Heatmap tab to inspect footprint patterns.`}
                          >
                            ↔ {kinaseNames.length} {isUbi ? "E3 ligases" : "kinases"}
                          </Badge>
                        );
                      })()}
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
                          const actClassConfig = ({
                            de_novo: { symbol: "★", color: "text-[#E65100]", title: "De novo (no control signal)" },
                            regulated: { symbol: "●", color: "text-[#1565C0]", title: "Regulated (q<0.05, |FC|≥1)" },
                            coordinated: { symbol: "◆", color: "text-[#7B1FA2]", title: `Patterned (${isUbi ? "temporal" : "local cluster"} membership, |FC|≥0.5)` },
                            minor: { symbol: "◇", color: "text-[#4CAF50]", title: "Minor (sub-threshold)" },
                          } as Record<string, { symbol: string; color: string; title: string }>)[actClass];

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
                                  ? `[${actClassConfig.title}] ${isUbi ? statusCfg?.labelUbi : statusCfg?.label}${
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
            highlightedKinase={effectiveHighlightedKinase}
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
            coWaveModules={coWaveModules}
            highlightedCwGroup={highlightedCwGroup}
            highlightedCwGroupKinases={highlightedCwGroupKinases}
            isUbi={isUbi}
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

        {/* ── Tab: Kinase Activity Heatmap ────────────────────────────────────────── */}
        {activeTab === "heatmap" && globalKinaseResult && (
          <KinaseActivityHeatmapView
            orderId={orderId}
            globalKinaseResult={globalKinaseResult}
            vectorData={vectorData}
            conditions={conditions}
            coWaveModules={coWaveModules}
            isUbi={isUbi}
            onSelectPtms={onSelectPtms}
            onKinaseSelect={(kinase, cwGroup, cwKinases) => {
              setInternalHighlightedKinase(kinase);
              setHighlightedCwGroup(cwGroup ?? null);
              setHighlightedCwGroupKinases(cwKinases || []);
              setActiveTab("signalFlow");
            }}
          />
        )}

        {/* ── Tab: Cascade Timeline ────────────────────────────────────────── */}
        {activeTab === "cascadeTimeline" && globalKinaseResult && (
          <CascadeTimelineView
            globalKinaseResult={globalKinaseResult}
            vectorData={vectorData}
            conditions={conditions}
            inferredReceptors={inferredReceptors}
            onKinaseClick={(kinase) => {
              setInternalHighlightedKinase(kinase);
              setActiveTab("signalFlow");
            }}
          />
        )}

        {/* ── Tab: Chain Linkage (Ubiquitylation only) ────────────────────────── */}
        {activeTab === "chainLinkage" && isUbi && (
          <ChainLinkageView orderId={orderId} conditions={conditions} />
        )}
        {activeTab === "ipOverlay" && (
          <IPOverlayView
            orderId={orderId}
            vectorData={vectorData}
            conditions={conditions}
            globalKinaseModules={globalKinaseResult?.kinase_modules || null}
            inferredReceptors={inferredReceptors}
            savedIpData={ipOverlayData as any}
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
        <GroupInferencePanel inference={annotation.group_inference} isUbi={isUbi} />
      )}
      {annotation.group_inference && annotation.group_inference.anchor_kinases.length === 0 && (
        <div className="text-xs text-muted-foreground bg-muted/50 rounded p-2">
          <strong>Group Inference:</strong> No anchor {isUbi ? "E3 ligases" : "kinases"} found in this group.
          Run annotation on more PTMs or include PTMs with known {isUbi ? "E3 ligase" : "kinase"} information.
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

function GroupInferencePanel({ inference, isUbi = false }: { inference: GroupInference; isUbi?: boolean }) {
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
                {km.temporal_filter_applied && km.original_total_count
                  ? `${km.total_count}/${km.original_total_count} PTMs`
                  : `${km.total_count} PTMs total`}
              </Badge>
              {km.enriched_patterns && km.enriched_patterns.length > 0 && (
                <Badge variant="outline" className="text-[9px] h-4 border-blue-500/50 text-blue-400">
                  {km.enriched_patterns[0]}
                </Badge>
              )}
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
                Context matches: {isUbi ? "temporal" : "local cluster"} membership + motif annotation ({km.inferred_count})
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
  onRunGlobalKinase: (forceRefresh?: boolean) => void;
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
        Run {isUbi ? "temporal module" : "temporal phosphosite cluster"} detection first (enable PTMs in the chart above).
        {isUbi ? "Temporal context view summarizes E3-ligase module and ubiquitylation patterns." : "Temporal context view summarizes kinase-footprint patterns across sampled conditions."}
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
            : "Temporal kinase context: summarizes footprint diagnostics across sampled conditions; it does not establish catalytic activity or signaling flow."}
        </p>
        {!hasTemporalData && (
          <Button
            variant="default"
            size="sm"
            className={`text-xs h-7 ${isUbi ? "bg-orange-600 hover:bg-orange-700" : ""}`}
            disabled={globalKinaseLoading}
            onClick={() => onRunGlobalKinase()}
          >
            {globalKinaseLoading ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Network className="h-3 w-3 mr-1" />}
            {isUbi ? "Build Ubiquitylation Context" : "Build Kinase Temporal Context"}
          </Button>
        )}
      </div>

      {/* ── Loading state ── */}
      {globalKinaseLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4 justify-center">
          <Loader2 className="h-4 w-4 animate-spin" />
          {isUbi
            ? "Building temporal ubiquitylation cascade — E3 ligases, chain types, DUB activity..."
            : "Building kinase temporal context from all PTM annotations..."}
        </div>
      )}

      {/* ── No temporal data yet ── */}
      {!hasTemporalData && !globalKinaseLoading && (
        <div className="space-y-3">
          <Alert>
            <Info className="h-4 w-4" />
            <AlertTitle>{isUbi ? "Ubiquitylation Context Not Yet Built" : "Kinase Temporal Context Not Yet Built"}</AlertTitle>
            <AlertDescription className="text-xs">
              Click <strong>{isUbi ? "\"Build Ubiquitylation Context\"" : "\"Build Kinase Temporal Context\""}</strong> above (or run <strong>{isUbi ? "\"E3 Modules\"" : "\"Global Kinase Modules\""}</strong> from the {isUbi ? "E3 Modules" : "Kinase Modules"} tab) to generate the temporal {isUbi ? "ubiquitylation" : "kinase"} context.
              This will annotate PTMs with eight sources and summarize sampled-condition footprint context; it does not build a directed activation map.
            </AlertDescription>
          </Alert>

          {/* Fallback: basic temporal profile cluster timeline */}
          <div className="text-xs font-medium text-muted-foreground mb-2">Basic {isUbi ? "Temporal" : TEMPORAL_TERMS.cluster} Timeline (preview):</div>
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
              {isUbi ? "Temporal E3 Ligase Footprint Timeline" : "Temporal Kinase Substrate-Footprint Timeline"}
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

// ── EffectorLayerSection: collapsible Non-PTM Effector Layer ──────────────
function EffectorLayerSection({ effectorProteins }: { effectorProteins: EffectorProtein[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-lg border border-teal-500/30 bg-teal-50/5 dark:bg-teal-900/10 p-3 space-y-2">
      <div
        className="flex items-center justify-between cursor-pointer select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="text-xs font-semibold text-teal-600 dark:text-teal-400 flex items-center gap-1">
          <ArrowRight className="h-3 w-3" /> Non-PTM Effector Layer
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">
            {effectorProteins.length} non-PTM proteins
          </span>
          <span className="text-[10px] text-teal-400">{expanded ? "▲ 접기" : "▼ 펼치기"}</span>
        </div>
      </div>
      {expanded && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {effectorProteins.map(eff => {
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
    </div>
  );
}

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
  onRun: (forceRefresh?: boolean) => void;
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
          onClick={() => onRun()}
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
        <EffectorLayerSection effectorProteins={result.effector_proteins} />
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
                    {(mod as any).temporal_filter_applied && (mod as any).original_total_count
                      ? `${mod.total_count}/${(mod as any).original_total_count} ${isUbi ? "sites" : "PTMs"}`
                      : `${mod.total_count} ${isUbi ? "sites" : "PTMs"}`}
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

              {/* Temporal phosphosite cluster overlap badges */}
              {mod.cowave_overlap && mod.cowave_overlap.length > 0 && (
                <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                  <GitMerge className="h-3 w-3" />
                  {isUbi ? "Temporal" : TEMPORAL_TERMS.cluster} overlap:
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

      {/* Temporal profile cluster × kinase context cross-analysis */}
      {cowave_cross_analysis && Object.keys(cowave_cross_analysis).length > 0 && (
        <div className="space-y-2">
          <button
            onClick={() => setShowCrossAnalysis(!showCrossAnalysis)}
            className="flex items-center gap-1 text-xs font-medium hover:text-primary"
          >
            {showCrossAnalysis ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            <GitMerge className="h-3.5 w-3.5" />
            {isUbi ? "Temporal Cluster × E3 Ligase Context Overlap" : "Temporal Profile Cluster × Kinase Context Overlap"}
          </button>

          {showCrossAnalysis && (
            <div className="space-y-2">
              <p className="text-[10px] text-muted-foreground">
                {isUbi
                  ? "Ubiquitylation sites overlapping an E3-ligase module and a temporal cluster are shown as a contextual diagnostic. The overlap does not establish common E3 regulation."
                  : "Phosphorylation features overlapping a kinase module and a Temporal Profile Cluster are shown as a contextual diagnostic. The overlap does not establish shared regulation or a direct kinase–substrate relationship."}
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-[10px] h-7">{isUbi ? "Temporal Module" : "Temporal Profile Cluster"}</TableHead>
                    <TableHead className="text-[10px] h-7">{isUbi ? "Total Sites" : "Total Phosphorylation Features"}</TableHead>
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
          onClick={() => onRun(true)}
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
  coWaveModules = [],
  highlightedCwGroup = null,
  highlightedCwGroupKinases = [],
  isUbi = false,
}: {
  inferredReceptors: InferredReceptor[];
  globalKinaseResult: GlobalKinaseModuleResponse | null;
  topNPtms: { gene: string; position: string; label: string }[];
  vectorData?: PtmTimeSeriesRow[];
  conditions?: string[];
  coWaveModules?: CoWaveModule[];
  highlightedCwGroup?: number | null;
  highlightedCwGroupKinases?: string[];
  isUbi?: boolean;
}) {
  const [selectedReceptor, setSelectedReceptor] = useState<string | null>(null);
  const [showEffectors, setShowEffectors] = useState(true);
  const [showTemporalOverlay, setShowTemporalOverlay] = useState(true);

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

  // v9.44: Build PTM activity classification with co-wave confidence boost
  // Priority: de_novo > regulated > coordinated > minor
  // "coordinated" = sub-threshold PTM that co-moves with 2+ others in a co-wave group
  const ptmActivityClass = useMemo(() => {
    const map: Record<string, "de_novo" | "regulated" | "coordinated" | "minor"> = {};
    if (!vectorData.length || !conditions.length) return map;
    const baseline = conditions[0];
    const ptmKeys = new Set(vectorData.map(r => `${r.gene}_${r.position}`));

    // Step 1: Compute base class (same as before)
    for (const key of ptmKeys) {
      const rows = vectorData.filter(r => `${r.gene}_${r.position}` === key);
      const hasPseudocount = rows.some(r => r.control_pseudocount_used === true);
      const maxVal = Math.max(...rows.map(r => r.value));
      const minVal = Math.min(...rows.map(r => r.value));
      const maxAbsLog2FC = Math.max(Math.abs(maxVal), Math.abs(minVal));
      const qValues = rows.map(r => r.q_value).filter((v): v is number => v != null && !isNaN(v));
      const minQVal = qValues.length > 0 ? Math.min(...qValues) : null;
      const hasQValue = minQVal != null;

      if (hasPseudocount) {
        map[key] = "de_novo";
      } else if (hasQValue) {
        map[key] = (maxAbsLog2FC >= 1.0 && minQVal < 0.05) ? "regulated" : "minor";
      } else {
        const baselineVal = rows.find(r => r.condition === baseline)?.value ?? 0;
        const maxAbsChange = Math.max(Math.abs(maxVal - baselineVal), Math.abs(minVal - baselineVal));
        map[key] = maxAbsChange > 0.8 ? "regulated" : "minor";
      }
    }

    // Step 2: Co-wave Confidence Boost — use pre-computed classes from coWaveModules
    // coWaveModules already applied the boost in detectCoWaveModules (v9.44)
    for (const mod of coWaveModules) {
      for (const ptm of mod.ptms) {
        const key = `${ptm.gene}_${ptm.position}`;
        if (ptm.activity_class === "coordinated" && map[key] === "minor") {
          map[key] = "coordinated";
        }
      }
    }

    return map;
  }, [vectorData, conditions, coWaveModules]);

  // v9.43: Build PTM → co-wave group mapping for Signal Flow visualization
  // Maps each PTM key to its co-wave module info (label, peak condition, group size)
  const ptmCoWaveMap = useMemo(() => {
    const map: Record<string, { moduleId: number; label: string; peakCondition: string; groupSize: number; dominantClass: string }[]> = {};
    for (const mod of coWaveModules) {
      for (const ptm of mod.ptms) {
        const key = `${ptm.gene}_${ptm.position}`;
        if (!map[key]) map[key] = [];
        map[key].push({
          moduleId: mod.id,
          label: mod.label,
          peakCondition: mod.peakCondition,
          groupSize: mod.ptms.length,
          dominantClass: mod.dominant_activity_class,
        });
      }
    }
    return map;
  }, [coWaveModules]);

  // Co-wave color palette for visual grouping (up to 8 distinct colors)
  const cowaveColors = [
    { bg: "bg-cyan-900/20", text: "text-cyan-300", border: "border-cyan-500/50", dot: "bg-cyan-400" },
    { bg: "bg-fuchsia-900/20", text: "text-fuchsia-300", border: "border-fuchsia-500/50", dot: "bg-fuchsia-400" },
    { bg: "bg-amber-900/20", text: "text-amber-300", border: "border-amber-500/50", dot: "bg-amber-400" },
    { bg: "bg-indigo-900/20", text: "text-indigo-300", border: "border-indigo-500/50", dot: "bg-indigo-400" },
    { bg: "bg-lime-900/20", text: "text-lime-300", border: "border-lime-500/50", dot: "bg-lime-400" },
    { bg: "bg-pink-900/20", text: "text-pink-300", border: "border-pink-500/50", dot: "bg-pink-400" },
    { bg: "bg-sky-900/20", text: "text-sky-300", border: "border-sky-500/50", dot: "bg-sky-400" },
    { bg: "bg-orange-900/20", text: "text-orange-300", border: "border-orange-500/50", dot: "bg-orange-400" },
  ];

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

  // v9.44: kinase → module confidence mapping
  const kinaseConfidence = useMemo(() => {
    const map: Record<string, { confidence_score: number; cowave_boost: number }> = {};
    if (!globalKinaseResult) return map;
    for (const mod of globalKinaseResult.kinase_modules) {
      const key = (mod.canonical || mod.kinase).toUpperCase();
      map[key] = {
        confidence_score: mod.confidence_score ?? 0,
        cowave_boost: mod.cowave_boost ?? 0,
      };
    }
    return map;
  }, [globalKinaseResult]);

  // v9.47: Kinase temporal activity map — compute peak timepoint per kinase from vectorData
  const kinaseTemporalMap = useMemo(() => {
    const map: Record<string, {
      peakCondition: string;
      peakScore: number;
      direction: "positive_substrate_footprint" | "negative_substrate_footprint" | "near_zero_footprint";
      scores: Record<string, number>;
      absScores: Record<string, number>; // mean(|FC|) per condition — captures total activity regardless of direction
      peakOrder: number; // 0-based index in conditions array
    }> = {};
    if (!globalKinaseResult || !vectorData.length || !conditions.length) return map;

    const LOG2FC_CAP = 5.0;
    // Build PTM lookup: (gene_upper, pos_upper, condition) → value
    const ptmLookup: Record<string, number> = {};
    for (const row of vectorData) {
      const key = `${row.gene.toUpperCase()}|${row.position.toUpperCase()}|${row.condition}`;
      const capped = Math.max(-LOG2FC_CAP, Math.min(LOG2FC_CAP, row.value));
      ptmLookup[key] = capped;
    }

    for (const mod of globalKinaseResult.kinase_modules) {
      const kinaseKey = (mod.canonical || mod.kinase).toUpperCase();
      if (mod.members.length < 1) continue;

      const scores: Record<string, number> = {};
      const absScores: Record<string, number> = {};
      for (const cond of conditions) {
        let sum = 0;
        let absSum = 0;
        let count = 0;
        for (const m of mod.members) {
          const lookupKey = `${m.gene.toUpperCase()}|${m.position.toUpperCase()}|${cond}`;
          const val = ptmLookup[lookupKey];
          if (val !== undefined) {
            sum += val;
            absSum += Math.abs(val);
            count++;
          }
        }
        scores[cond] = count > 0 ? sum / count : 0;
        absScores[cond] = count > 0 ? absSum / count : 0;
      }

      // Find peak
      let peakCond = conditions[0];
      let peakVal = 0;
      for (const cond of conditions) {
        if (Math.abs(scores[cond]) > Math.abs(peakVal)) {
          peakVal = scores[cond];
          peakCond = cond;
        }
      }

      const direction: "positive_substrate_footprint" | "negative_substrate_footprint" | "near_zero_footprint" =
        peakVal > 0.3 ? "positive_substrate_footprint" : peakVal < -0.3 ? "negative_substrate_footprint" : "near_zero_footprint";

      map[kinaseKey] = {
        peakCondition: peakCond,
        peakScore: peakVal,
        direction,
        scores,
        absScores,
        peakOrder: conditions.indexOf(peakCond),
      };
    }
    return map;
  }, [globalKinaseResult, vectorData, conditions]);

  // v9.47: Temporal color for peak timepoint
  const temporalColors: Record<string, { bg: string; text: string; label: string }> = useMemo(() => {
    const colors: Record<string, { bg: string; text: string; label: string }> = {};
    const palette = [
      { bg: "bg-red-900/40", text: "text-red-300", label: "" },
      { bg: "bg-orange-900/40", text: "text-orange-300", label: "" },
      { bg: "bg-yellow-900/40", text: "text-yellow-300", label: "" },
      { bg: "bg-blue-900/40", text: "text-blue-300", label: "" },
    ];
    conditions.forEach((cond, i) => {
      colors[cond] = { ...palette[i % palette.length], label: cond };
    });
    return colors;
  }, [conditions]);

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
      // Within a group, pick primary by confidence_score (consistent with Inferred Upstream Receptors panel)
      const sorted = [...members].sort(
        (a, b) => (b.confidence_score || 0) - (a.confidence_score || 0) || (b.downstream_ptm_count || 0) - (a.downstream_ptm_count || 0)
      );
      result.push({ primary: sorted[0], members: sorted });
    }

    for (const rec of ungrouped) {
      result.push({ primary: rec, members: [rec] });
    }

    // Sort groups by confidence_score (consistent with Inferred Upstream Receptors panel)
    return result.sort(
      (a, b) => (b.primary.confidence_score || 0) - (a.primary.confidence_score || 0) || (b.primary.downstream_ptm_count || 0) - (a.primary.downstream_ptm_count || 0)
    );
  }, [inferredReceptors]);

  // v9.47: Receptor temporal classification based on earliest kinase peak
  const receptorTemporalClass = useMemo(() => {
    const map: Record<string, { class: "immediate-early" | "secondary" | "late" | "sustained" | "unknown"; earliestPeak: string; latestPeak: string }> = {};
    for (const { primary } of groupedReceptors) {
      const kinases = primary.via_kinases || [];
      let earliest = conditions.length;
      let latest = -1;
      for (const k of kinases) {
        const temporal = kinaseTemporalMap[k.toUpperCase()];
        if (temporal) {
          if (temporal.peakOrder < earliest) earliest = temporal.peakOrder;
          if (temporal.peakOrder > latest) latest = temporal.peakOrder;
        }
      }
      const classLabel =
        earliest === 0 ? "immediate-early" :
        earliest === 1 ? "secondary" :
        earliest <= 2 ? "late" :
        earliest < conditions.length ? "sustained" : "unknown";
      map[primary.name] = {
        class: classLabel,
        earliestPeak: earliest < conditions.length ? conditions[earliest] : "?",
        latestPeak: latest >= 0 ? conditions[latest] : "?",
      };
    }
    return map;
  }, [groupedReceptors, kinaseTemporalMap, conditions]);

  // v11.5e: Temporal Signal Dominance — uses |signed mean FC| for temporal variation.
  // 
  // Key insight: mean(|FC|) across 667 substrates barely changes over time (always ~0.5)
  // because large modules always have "some" activity. But SIGNED mean FC captures the
  // NET directional signal: at 6h it might be +0.8 (strong activation), at 48h it might
  // be -0.2 (mild reversal). |signed mean| varies dramatically across timepoints.
  //
  // Score = confidence × |signed_mean_FC_at_time| / max(|signed_mean_FC| across times)
  // This produces genuine rank changes because different kinases have different temporal
  // profiles in their net directional signal.
  const temporalDominance = useMemo(() => {
    if (!conditions.length) return [];
    const pool = groupedReceptors.slice(0, Math.min(groupedReceptors.length, 12));

    // Step 1: For each receptor, compute |signed mean FC| at each timepoint
    const signalMap: Record<string, Record<string, number>> = {};
    const peakSignal: Record<string, number> = {};
    for (const { primary } of pool) {
      const kinases = primary.via_kinases || [];
      if (!kinases.length) continue;
      signalMap[primary.name] = {};
      let maxSig = 0;
      for (const cond of conditions) {
        let signedSum = 0;
        let cnt = 0;
        for (const k of kinases) {
          const temporal = kinaseTemporalMap[k.toUpperCase()];
          if (temporal && temporal.scores && temporal.scores[cond] !== undefined) {
            signedSum += temporal.scores[cond]; // signed mean FC
            cnt++;
          }
        }
        // Use |signed mean| — captures net directional signal strength
        const signal = cnt > 0 ? Math.abs(signedSum / cnt) : 0;
        signalMap[primary.name][cond] = signal;
        if (signal > maxSig) maxSig = signal;
      }
      peakSignal[primary.name] = maxSig;
    }

    // Step 2: For each timepoint, compute dominance_score and rank
    const result: { condition: string; receptors: { name: string; class: string; score: number; confidence: number }[] }[] = [];
    for (const cond of conditions) {
      const scored: { name: string; class: string; score: number; confidence: number }[] = [];
      for (const { primary } of pool) {
        const signal = signalMap[primary.name]?.[cond] ?? 0;
        const peak = peakSignal[primary.name] || 1;
        const confidence = primary.confidence_score || 0;
        const signalFraction = signal / peak; // 0~1: how strong is NET signal now vs peak
        const dominanceScore = confidence * signalFraction;
        if (dominanceScore > 0.01) {
          scored.push({
            name: primary.name,
            class: primary.receptor_class || "",
            score: dominanceScore,
            confidence,
          });
        }
      }
      scored.sort((a, b) => b.score - a.score);
      result.push({ condition: cond, receptors: scored.slice(0, 3) });
    }
    return result;
  }, [conditions, kinaseTemporalMap, groupedReceptors]);

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
          {/* v9.47: Temporal overlay toggle */}
          {Object.keys(kinaseTemporalMap).length > 0 && (
            <button
              className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                showTemporalOverlay
                  ? "bg-orange-50 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 border-orange-400"
                  : "border-border text-muted-foreground hover:border-foreground/50"
              }`}
              onClick={() => setShowTemporalOverlay(!showTemporalOverlay)}
            >
              {showTemporalOverlay ? "◉" : "○"} Temporal
            </button>
          )}
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

      {/* v9.48.2: CW Group highlight banner from Heatmap click — with substrate PTM list */}
      {highlightedCwGroup !== null && highlightedCwGroupKinases.length > 0 && (() => {
        // Build kinase → substrate map from globalKinaseResult
        const kinaseSubstrateMap: Record<string, { gene: string; position: string; membership: string }[]> = {};
        let totalSubstrates = 0;
        if (globalKinaseResult?.kinase_modules) {
          for (const km of globalKinaseResult.kinase_modules) {
            const kName = km.canonical || km.kinase;
            if (highlightedCwGroupKinases.some(k => k.toLowerCase() === kName.toLowerCase() || k.toLowerCase() === km.kinase.toLowerCase())) {
              kinaseSubstrateMap[kName] = km.members.map(m => ({ gene: m.gene, position: m.position, membership: m.membership }));
              totalSubstrates += km.members.length;
            }
          }
        }
        return (
          <div className="px-3 py-2 rounded-lg border border-cyan-500/50 bg-cyan-900/20 space-y-2">
            {/* Header row */}
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold text-cyan-300">CW Group G{highlightedCwGroup}</span>
              <span className="text-[10px] text-cyan-400/80">({highlightedCwGroupKinases.length} {isUbi ? "E3 ligases" : "kinases"}, {totalSubstrates} substrate PTMs):</span>
              <div className="flex flex-wrap gap-1">
                {highlightedCwGroupKinases.map((k) => (
                  <span key={k} className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-800/40 text-cyan-200 border border-cyan-500/30">
                    {k}
                  </span>
                ))}
              </div>
              <button
                className="ml-auto text-[9px] text-muted-foreground hover:text-foreground"
                title={`CW Group: ${isUbi ? "E3 ligases" : "kinases"} with correlated substrate activity (r≥0.7). Substrates listed below.`}
              >
                ?
              </button>
            </div>
            {/* Substrate PTM list per kinase */}
            {Object.keys(kinaseSubstrateMap).length > 0 && (
              <div className="grid grid-cols-1 gap-1 max-h-[200px] overflow-y-auto">
                {Object.entries(kinaseSubstrateMap).map(([kName, substrates]) => (
                  <div key={kName} className="flex items-start gap-2">
                    <span className="text-[9px] font-semibold text-cyan-200 min-w-[80px] shrink-0">{kName}:</span>
                    <div className="flex flex-wrap gap-0.5">
                      {substrates.slice(0, 12).map((s, i) => (
                        <span
                          key={i}
                          className={`text-[8px] px-1 py-0.5 rounded ${
                            s.membership === "confirmed"
                              ? "bg-emerald-900/40 text-emerald-300 border border-emerald-500/30"
                              : "bg-amber-900/30 text-amber-300 border border-amber-500/20"
                          }`}
                          title={`${s.gene} ${s.position} (${s.membership})`}
                        >
                          {s.gene} {s.position}
                        </span>
                      ))}
                      {substrates.length > 12 && (
                        <span className="text-[8px] text-muted-foreground">+{substrates.length - 12} more</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      {/* v11.4: Temporal Signal Dominance Summary Strip */}
      {showTemporalOverlay && temporalDominance.length > 0 && (
        <div className="rounded-lg border border-border/60 bg-card/30 p-3 space-y-2">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-semibold text-orange-300">⚡ Temporal Signal Dominance</span>
            <span className="text-[9px] text-muted-foreground">— Receptors ranked by confidence × net signal strength (confidence-ranked)</span>
          </div>
          <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${Math.min(temporalDominance.length, 6)}, 1fr)` }}>
            {temporalDominance.map(({ condition, receptors }) => {
              return (
                <div key={condition} className="space-y-1">
                  <div className="text-[10px] font-bold text-center text-foreground/80 border-b border-border/40 pb-0.5">
                    {condition}
                  </div>
                  {receptors.length === 0 && (
                    <div className="text-[8px] text-muted-foreground/50 text-center py-1">—</div>
                  )}
                  {receptors.slice(0, 3).map((rec, idx) => {
                    // score is dominanceScore (confidence × activityFraction), max ~0.68
                    // Normalize bar to column's top scorer for visual clarity
                    const colMax = receptors[0]?.score || 0.01;
                    const barWidth = Math.max(Math.round((rec.score / colMax) * 100), 8);
                    const isTop = idx === 0;
                    return (
                      <div key={rec.name} className="flex items-center gap-1">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-0.5">
                            <span className={`text-[9px] truncate ${isTop ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
                              {rec.name}
                            </span>
                          </div>
                          <div className="h-1 rounded-full bg-muted/30 overflow-hidden mt-0.5">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{
                                width: `${barWidth}%`,
                                backgroundColor: isTop ? "#f97316" : idx === 1 ? "#fb923c" : "#fdba74",
                                opacity: isTop ? 1 : 0.7,
                              }}
                            />
                          </div>
                        </div>
                        <span className={`text-[8px] flex-shrink-0 ${isTop ? "text-orange-300" : "text-muted-foreground"}`}>
                          {Math.round(rec.score * 100)}%
                        </span>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      )}

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
            {primary.confidence_score != null && (
              <span className={`ml-1 text-[8px] ${
                (primary.confidence_score || 0) > 0.6 ? "text-green-400" :
                (primary.confidence_score || 0) > 0.4 ? "text-yellow-400" : "text-red-400"
              }`}>
                {((primary.confidence_score || 0) * 100).toFixed(0)}%
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
                {primary.cowave_score != null && primary.cowave_score > 0 && (
                  <span className="text-[8px] px-1 py-0.5 rounded bg-cyan-900/20 text-cyan-300 border border-cyan-500/40" title={`Within-cluster interval-wise activity-state concordance score: ${primary.cowave_score.toFixed(1)} — descriptive temporal-pattern diagnostic only`}>
                    WC:{primary.cowave_score.toFixed(1)}
                  </span>
                )}
                {/* v9.47: Receptor temporal classification */}
                {showTemporalOverlay && receptorTemporalClass[primary.name] && receptorTemporalClass[primary.name].class !== "unknown" && (
                  <span
                    className={`text-[8px] px-1.5 py-0.5 rounded border ${
                      receptorTemporalClass[primary.name].class === "immediate-early"
                        ? "bg-red-900/30 text-red-300 border-red-500/50"
                        : receptorTemporalClass[primary.name].class === "secondary"
                        ? "bg-orange-900/30 text-orange-300 border-orange-500/50"
                        : receptorTemporalClass[primary.name].class === "late"
                        ? "bg-yellow-900/30 text-yellow-300 border-yellow-500/50"
                        : "bg-blue-900/30 text-blue-300 border-blue-500/50"
                    }`}
                    title={`Receptor activation timing: ${receptorTemporalClass[primary.name].class}\nEarliest kinase peak: ${receptorTemporalClass[primary.name].earliestPeak}\nLatest kinase peak: ${receptorTemporalClass[primary.name].latestPeak}`}
                  >
                    {receptorTemporalClass[primary.name].class === "immediate-early" ? "⚡" :
                     receptorTemporalClass[primary.name].class === "secondary" ? "⏱" :
                     receptorTemporalClass[primary.name].class === "late" ? "⏳" : "♾"}
                    {" "}{receptorTemporalClass[primary.name].earliestPeak}
                  </span>
                )}
              </div>

              {/* Kinase layer */}
              {viaKinases.length > 0 ? (
                <div className="ml-4 space-y-2">
                  <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                    <ArrowRight className="h-3 w-3" />
                    <span>via kinases:</span>
                    {/* v9.48: Edge temporal validation summary */}
                    {showTemporalOverlay && (() => {
                      const recClass = receptorTemporalClass[primary.name];
                      if (!recClass || recClass.class === "unknown") return null;
                      const recOrder = conditions.indexOf(recClass.earliestPeak);
                      let valid = 0;
                      let invalid = 0;
                      let total = 0;
                      for (const k of viaKinases) {
                        const t = kinaseTemporalMap[k.toUpperCase()];
                        if (!t) continue;
                        total++;
                        if (t.peakOrder >= recOrder) valid++;
                        else invalid++;
                      }
                      if (total === 0) return null;
                      return (
                        <span className={`ml-1 text-[8px] px-1 py-px rounded border ${
                          invalid === 0 ? "bg-green-900/30 text-green-300 border-green-500/40" :
                          invalid <= valid ? "bg-yellow-900/30 text-yellow-300 border-yellow-500/40" :
                          "bg-red-900/30 text-red-300 border-red-500/40"
                        }`} title={`Temporal flow validation: ${valid} kinases peak after receptor activation (✓), ${invalid} peak before (⚠️ possible feedback)`}>
                          {invalid === 0 ? "✓" : "⚠️"} {valid}/{total} forward
                        </span>
                      );
                    })()}
                  </div>
                  <div className="flex flex-wrap gap-2 ml-4">
                    {viaKinases.map(kinase => {
                      const kinaseKey = kinase.toUpperCase();
                      const ptms = kinaseToPtms[kinaseKey] || [];
                      const isUnique = primary.unique_kinases?.includes(kinase);
                      const isCwHighlighted = highlightedCwGroupKinases.some(
                        (k) => k.toUpperCase() === kinaseKey
                      );

                      return (
                        <div key={kinase} className="space-y-1">
                          <div className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${
                            isCwHighlighted
                              ? "border-2 border-cyan-400 bg-cyan-900/30 text-cyan-200 ring-1 ring-cyan-400/50"
                              : isUnique
                              ? "border-2 border-amber-400 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300"
                              : "border border-dashed border-amber-400/50 bg-amber-50/50 dark:bg-amber-900/10 text-amber-700/60 dark:text-amber-300/60"
                          }`}>
                            <Zap className="h-2.5 w-2.5" />
                            {kinase}
                            {isCwHighlighted && highlightedCwGroup !== null && (
                              <span className="ml-0.5 text-[8px] px-1 py-px rounded bg-cyan-700/50 text-cyan-200 border border-cyan-500/40">
                                G{highlightedCwGroup}
                              </span>
                            )}
                            {isUnique && <span className="ml-0.5 text-[8px] text-amber-500">★</span>}
                            {kinaseConfidence[kinaseKey]?.cowave_boost > 0.3 && (
                              <span
                                className="ml-0.5 text-[7px] px-0.5 rounded bg-purple-900/30 text-purple-300"
                                title={`Module diagnostic: ${((kinaseConfidence[kinaseKey]?.confidence_score ?? 0) * 100).toFixed(0)}% (within-cluster interval-wise activity-state concordance contribution: ${((kinaseConfidence[kinaseKey]?.cowave_boost ?? 0) * 100).toFixed(0)}%). This is not a direct kinase-confidence estimate.`}
                              >
                                {((kinaseConfidence[kinaseKey]?.confidence_score ?? 0) * 100).toFixed(0)}%
                              </span>
                            )}
                            {/* v9.48: Temporal peak badge + edge validation */}
                            {showTemporalOverlay && kinaseTemporalMap[kinaseKey] && (() => {
                              const t = kinaseTemporalMap[kinaseKey];
                              const recClass = receptorTemporalClass[primary.name];
                              const recOrder = recClass ? conditions.indexOf(recClass.earliestPeak) : -1;
                              const isForward = recOrder < 0 || t.peakOrder >= recOrder;
                              return (
                                <>
                                  <span
                                    className={`ml-0.5 text-[7px] px-1 py-px rounded border ${
                                      t.direction === "positive_substrate_footprint"
                                        ? "bg-red-900/30 text-red-300 border-red-500/40"
                                        : t.direction === "negative_substrate_footprint"
                                        ? "bg-blue-900/30 text-blue-300 border-blue-500/40"
                                        : "bg-gray-900/30 text-gray-400 border-gray-500/40"
                                    }`}
                                    title={`Peak: ${t.peakCondition} (${t.peakScore > 0 ? "+" : ""}${t.peakScore.toFixed(1)})\nDirection: ${t.direction}`}
                                  >
                                    {t.direction === "positive_substrate_footprint" ? "▲" : t.direction === "negative_substrate_footprint" ? "▼" : "—"}
                                    {t.peakCondition}
                                  </span>
                                  {recOrder >= 0 && (
                                    <span
                                      className={`ml-0.5 text-[7px] ${
                                        isForward ? "text-green-400" : "text-amber-400"
                                      }`}
                                      title={isForward
                                        ? `✓ Forward flow: kinase peaks at ${t.peakCondition} (after receptor activation at ${conditions[recOrder]})`
                                        : `⚠️ Feedback: kinase peaks at ${t.peakCondition} (before receptor activation at ${conditions[recOrder]}) — possible negative feedback loop`
                                      }
                                    >
                                      {isForward ? "✓" : "⚠️"}
                                    </span>
                                  )}
                                </>
                              );
                            })()}
                          </div>
                          {/* PTM substrates */}
                          {ptms.length > 0 && (() => {
                            // v9.43: Count co-wave groups among this kinase's substrates
                            const kinaseCowaveGroups = new Map<number, { label: string; count: number; peakCondition: string }>();
                            for (const ptm of ptms) {
                              const key = `${ptm.gene}_${ptm.position}`;
                              const cwInfos = ptmCoWaveMap[key] || [];
                              for (const cw of cwInfos) {
                                if (!kinaseCowaveGroups.has(cw.moduleId)) {
                                  kinaseCowaveGroups.set(cw.moduleId, { label: cw.label, count: 0, peakCondition: cw.peakCondition });
                                }
                                kinaseCowaveGroups.get(cw.moduleId)!.count++;
                              }
                            }
                            const cowaveGroupList = Array.from(kinaseCowaveGroups.entries())
                              .filter(([, v]) => v.count >= 2) // Only show groups with 2+ substrates under this kinase
                              .sort((a, b) => b[1].count - a[1].count);
                            return (
                            <div className="ml-2 space-y-0.5">
                              <div className="flex items-center gap-0.5 text-[9px] text-muted-foreground">
                                <ArrowRight className="h-2.5 w-2.5" />
                                <span>{ptms.length} substrates:</span>
                                {cowaveGroupList.length > 0 && (
                                  <span className="ml-1 flex items-center gap-1">
                                    {cowaveGroupList.slice(0, 3).map(([modId, info]) => {
                                      const colorIdx = (modId - 1) % cowaveColors.length;
                                      return (
                                        <span
                                          key={modId}
                                          className={`inline-flex items-center gap-0.5 px-1 py-px rounded ${cowaveColors[colorIdx].bg} ${cowaveColors[colorIdx].text} border ${cowaveColors[colorIdx].border}`}
                                          title={`${formatTemporalClusterLabel(info.label)}: ${info.count}/${ptms.length} substrates share this observed temporal-cluster profile (peak: ${info.peakCondition})`}
                                        >
                                          <span className={`w-1.5 h-1.5 rounded-full ${cowaveColors[colorIdx].dot}`} />
                                          <span className="text-[8px]">{info.count}/{ptms.length}</span>
                                        </span>
                                      );
                                    })}
                                  </span>
                                )}
                              </div>
                              <div className="flex flex-wrap gap-1 ml-3">
                                {ptms.map(ptm => {
                                  const ptmKey = `${ptm.gene}_${ptm.position}`;
                                  const actClass = ptmActivityClass[ptmKey] || "minor";
                                  const chipStyle =
                                    actClass === "de_novo"
                                      ? "bg-red-900/30 text-red-300 border border-red-500 font-semibold"
                                      : actClass === "regulated"
                                      ? "bg-emerald-900/30 text-emerald-300 border border-emerald-500 font-semibold"
                                      : actClass === "coordinated"
                                      ? "bg-purple-900/30 text-purple-300 border border-purple-500 font-medium"
                                      : "bg-green-900/30 text-green-300 border border-green-500";
                                  const actLabel =
                                    actClass === "de_novo" ? "De novo (control imputed)" :
                                    actClass === "regulated" ? "Regulated (|Log2FC| ≥ 1.0 AND q < 0.05)" :
                                    actClass === "coordinated" ? "Concordant trajectory pattern (within-cluster, |FC|≥0.5 + set≥3)" :
                                    "Minor (sub-threshold)";
                                  const cowaveInfo = ptmCoWaveMap[ptmKey] || [];
                                  const cowaveTooltip = cowaveInfo.length > 0
                                    ? `\nTemporal Profile Cluster: ${cowaveInfo.map(c => `${formatTemporalClusterLabel(c.label)} (n=${c.groupSize}, sampled maximum=${c.peakCondition})`).join("; ")}`
                                    : "";
                                  return (
                                    <span
                                      key={ptmKey}
                                      className={`text-[9px] px-1.5 py-0.5 rounded ${chipStyle} relative`}
                                      title={`${ptm.gene} ${ptm.position} | ${actLabel} | kinase evidence: ${ptm.membership}${cowaveTooltip}`}
                                    >
                                      {actClass === "de_novo" && <span className="mr-0.5">★</span>}
                                      {actClass === "regulated" && <span className="mr-0.5">●</span>}
                                      {actClass === "coordinated" && <span className="mr-0.5">◆</span>}
                                      {actClass === "minor" && <span className="mr-0.5">◇</span>}
                                      {ptm.label || ptmKey}
                                      {cowaveInfo.length > 0 && (
                                        <span className={`ml-0.5 inline-flex items-center gap-px`}>
                                          {cowaveInfo.slice(0, 2).map(cw => {
                                            const colorIdx = (cw.moduleId - 1) % cowaveColors.length;
                                            return (
                                              <span
                                                key={cw.moduleId}
                                                className={`w-1.5 h-1.5 rounded-full inline-block ${cowaveColors[colorIdx].dot}`}
                                                title={`${formatTemporalClusterLabel(cw.label)} (${cw.groupSize} PTMs, peak: ${cw.peakCondition})`}
                                              />
                                            );
                                          })}
                                        </span>
                                      )}
                                    </span>
                                  );
                                })}
                              </div>
                            </div>
                            );
                          })()}
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
            <span className="px-1.5 py-0.5 rounded bg-purple-900/30 text-purple-300 border border-purple-500 text-[9px]">◆ Coordinated</span>
            <span className="text-[9px]">local temporal-cluster membership (|FC|≥0.5, group≥3, anchor signal)</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-green-900/30 text-green-300 border border-green-500 text-[9px]">◇ Minor</span>
            <span className="text-[9px]">sub-threshold, isolated</span>
          </span>
        </div>
        {coWaveModules.length > 0 && (
          <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
            <span className="font-medium text-muted-foreground/70">{TEMPORAL_TERMS.localGroup}:</span>
            <span className="flex items-center gap-1">
              <span className="flex gap-0.5">
                {cowaveColors.slice(0, Math.min(coWaveModules.length, 4)).map((c, i) => (
                  <span key={i} className={`w-2 h-2 rounded-full inline-block ${c.dot}`} />
                ))}
              </span>
              <span className="text-[9px]">colored dots = concordant phosphosite set (similar temporal profile; descriptive context)</span>
            </span>
            <span className="text-[9px] text-muted-foreground/50">
              ({coWaveModules.length} groups detected)
            </span>
          </div>
        )}
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
        {/* v9.47: Temporal overlay legend */}
        {showTemporalOverlay && Object.keys(kinaseTemporalMap).length > 0 && (
          <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
            <span className="font-medium text-muted-foreground/70">Temporal overlay:</span>
            <span className="flex items-center gap-1">
              <span className="px-1 py-0.5 rounded bg-red-900/30 text-red-300 border border-red-500/50 text-[8px]">⚡ 6h</span>
              <span className="text-[9px]">Immediate-early receptor</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="px-1 py-0.5 rounded bg-orange-900/30 text-orange-300 border border-orange-500/50 text-[8px]">⏱ 12h</span>
              <span className="text-[9px]">Secondary</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="px-1 py-0.5 rounded bg-yellow-900/30 text-yellow-300 border border-yellow-500/50 text-[8px]">⏳ 24h</span>
              <span className="text-[9px]">Late</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="px-1 py-0.5 rounded bg-blue-900/30 text-blue-300 border border-blue-500/50 text-[8px]">♾ 48h</span>
              <span className="text-[9px]">Sustained</span>
            </span>
            <span className="text-[9px] text-muted-foreground/50 ml-2">
              Kinase: ▲ activation (red) ▼ inactivation/phosphatase (blue)
            </span>
          </div>
        )}
      </div>
    </div>
  );
}


// ── Kinase Activity Heatmap + Line Chart View ────────────────────────────────────────

interface TierData {
  up_sums: Record<string, number>;
  down_sums: Record<string, number>;
  up_counts: Record<string, number>;
  down_counts: Record<string, number>;
}

interface KinaseActivityScore {
  kinase: string;
  scores: Record<string, number>;
  substrate_count: number;
  confidence?: number | null;
  confidence_status?: string;
  annotation_evidence_score?: number | null;
  peak_condition: string;
  peak_score: number;
  coherence?: number;
  cowave_group?: number;
  direction?: "positive_substrate_footprint" | "negative_substrate_footprint" | "near_zero_footprint";
  footprint_equivalence?: {
    equivalence_group_id: string;
    equivalence: "exact_substrate_set";
    member_count: number;
    site_count: number;
    members: string[];
    interpretation_boundary: string;
  } | null;
  footprint_diagnostics?: {
    status: string;
    effective_substrate_number?: number;
    support_shrinkage_factor?: number;
    dominant_substrate_fraction?: number;
    n_exclusive?: number;
    n_shared?: number;
    shared_fraction?: number;
    support_adjusted_coherence?: number;
    unique_only_footprint?: {
      status: string;
      weighted_site_count?: number;
      peak_condition?: string | null;
      peak_score?: number;
      direction?: string;
    };
    leave_one_substrate_out?: Array<{
      site_key: string;
      leverage_fraction: number;
      peak_condition: string | null;
      peak_score: number;
      direction: string;
      peak_condition_preserved: boolean;
      direction_preserved: boolean;
      max_score_delta: number;
    }>;
    interpretation_boundary?: string;
  };
  // v11.3 Multi-pattern fields
  parent_kinase?: string;          // if this is a sub-pattern, the parent kinase name
  is_sub_pattern?: boolean;        // true for non-dominant cluster entries
  sub_pattern_label?: string;      // "early_response" | "mid_response" | "late_response"
  translocation_flag?: string;     // "potential_nuclear_translocation" if detected
  // Co-activation Sum scoring fields (direction-split)
  up_sums?: Record<string, number>;    // sum of positive FC substrates per condition
  down_sums?: Record<string, number>;  // sum of negative FC substrates per condition (negative values)
  up_counts?: Record<string, number>;  // count of up-regulated substrates per condition
  down_counts?: Record<string, number>; // count of down-regulated substrates per condition
  coact_counts?: Record<string, number>;  // total co-activated substrate count
  exclusive_sums?: Record<string, number>;
  shared_sums?: Record<string, number>;
  exclusive_counts?: Record<string, number>;
  shared_counts?: Record<string, number>;
  // Per-tier breakdown: de_novo (declared detection/LOD representation),
  // regulated (conventional |Log2FC|>=0.58), minor (conventional 0.3<=|Log2FC|<0.58)
  tiers?: Record<"de_novo" | "regulated" | "minor", TierData>;
  // Temporal pattern classification (auto-detected by backend)
  temporal_pattern?: string[];
  // v11.0: Substrate temporal clustering
  total_substrates?: number;   // original total before clustering
  n_clusters?: number;         // number of trajectory clusters found
  cluster_details?: {
    cluster_id: number;
    size: number;
    scores: Record<string, number>;
    coherence: number;
    peak_condition: string;
    peak_score: number;
    direction: string;
    is_dominant: boolean;
    // v11.3: Magnitude tier of this cluster
    tier?: "strong" | "moderate" | "weak" | "mixed";
  }[];
  // v11.3: Substrate list for this kinase's dominant cluster (or sub-pattern cluster)
  substrates?: {
    ptm_key: string;
    gene: string;
    site: string;
    peak_fc: number;
  }[];
  // v11.3: Positional category for translocation detection
  sub_pattern_category?: string;
  // v11.3.1: Same-time clusters (same peak as parent) — shown in tooltip only, not as separate rows
  same_time_clusters?: {
    tier: string;
    size: number;
    peak_score: number;
    substrates: { gene: string; site: string; peak_fc: number }[];
  }[];
  // v11.3.2: Nuclear-exclusive substrate evidence
  nuclear_evidence?: {
    score: number;
    tier1_count: number;
    tier2_count: number;
    tier1_genes: string[];
    tier2_genes: string[];
  };
  // v11.3.3: Regulator self-PTM temporal tracking
  self_ptm?: {
    ptm_key: string;
    gene: string;
    site: string;
    timeseries: Record<string, number>;
    peak_condition: string;
    peak_fc: number;
    correlation_with_activity: number;
    relationship: "concordant" | "discordant" | "independent";
  }[] | null;
  // v11.3.4: Shared-substrate deduplication
  hidden_by_self_ptm?: boolean;   // true if superseded by a self-PTM kinase in same substrate group
  superseded_by?: string[];       // kinase(s) with self-PTM that supersede this one
}

interface PeakSyncEntry {
  kinases: string[];
  count: number;
}

interface CowaveGroupEntry {
  group_id: number;
  kinases: string[];
  size: number;
  mean_correlation: number;
  dominant_peak?: string;
}

interface KinaseHeatmapData {
  kinase_scores: KinaseActivityScore[];
  conditions: string[];
  peak_sync?: Record<string, PeakSyncEntry>;
  cowave_groups?: CowaveGroupEntry[];
  available_patterns?: string[];
  translocation_candidates?: {
    kinase: string;
    early_peak: string;
    late_peak: string;
    cytoplasm_genes: number;
    nucleus_genes: number;
    total_genes: number;
    hypothesis: string;
    description: string;
  }[];
  scoring_method?: string;
  scoring_threshold?: { q_value: number; fc_abs: number };
  temporal_ptm_protein_analysis?: TemporalPtmProteinAnalysisSummary;
  _cached: boolean;
  _cache_hash?: string;
}

interface TemporalPtmProteinAnalysisSummary {
  schema_version?: string;
  full_artifact_available?: boolean;
  artifact_path?: string | null;
  protein_trajectory_count?: number;
  ptm_protein_pair_count?: number;
  cross_layer_edge_count?: number;
  temporally_eligible_edge_count?: number;
  mechanism_chain_count?: number;
  evidence_supported_mechanism_count?: number;
  kinase_timing_status?: string | null;
  dynamic_co_wave_transition_status?: string | null;
  dynamic_transition_supported_wave_count?: number | null;
  dynamic_transition_pair_count?: number | null;
  causality_status?: "not_tested";
  interpretation_boundary?: string;
  top_cross_layer_edges?: Array<{
    edge_id?: string;
    source_wave_id?: string | number;
    target_gene?: string;
    direction?: string;
    onset_lag_minutes?: number | null;
    peak_lag_minutes?: number | null;
    eligible_for_mechanism_chain?: boolean;
    causality_status?: "not_tested";
  }>;
}

// ── Cascade Timeline View ──────────────────────────────────────────────────

interface CascadeTimelineProps {
  globalKinaseResult: GlobalKinaseModuleResponse;
  vectorData: PtmTimeSeriesRow[];
  conditions: string[];
  inferredReceptors: InferredReceptor[];
  onKinaseClick?: (kinase: string) => void;
}

function CascadeTimelineView({
  globalKinaseResult,
  vectorData,
  conditions,
  inferredReceptors,
  onKinaseClick,
}: CascadeTimelineProps) {
  const LOG2FC_CAP = 5.0;

  // Compute temporal data for each kinase
  const kinaseTimeline = useMemo(() => {
    const ptmLookup: Record<string, number> = {};
    for (const row of vectorData) {
      const key = `${row.gene.toUpperCase()}|${row.position.toUpperCase()}|${row.condition}`;
      ptmLookup[key] = Math.max(-LOG2FC_CAP, Math.min(LOG2FC_CAP, row.value));
    }

    const timeline: Array<{
      kinase: string;
      canonical: string;
      peakCondition: string;
      peakOrder: number;
      peakScore: number;
              direction: "positive_substrate_footprint" | "negative_substrate_footprint" | "near_zero_footprint";
      scores: Record<string, number>;
      substrateCount: number;
      upstreamReceptors: string[];
    }> = [];

    for (const mod of globalKinaseResult.kinase_modules) {
      if (mod.members.length < 1) continue;
      const scores: Record<string, number> = {};
      for (const cond of conditions) {
        let sum = 0;
        let count = 0;
        for (const m of mod.members) {
          const val = ptmLookup[`${m.gene.toUpperCase()}|${m.position.toUpperCase()}|${cond}`];
          if (val !== undefined) { sum += val; count++; }
        }
        scores[cond] = count > 0 ? sum / count : 0;
      }
      let peakCond = conditions[0];
      let peakVal = 0;
      for (const cond of conditions) {
        if (Math.abs(scores[cond]) > Math.abs(peakVal)) {
          peakVal = scores[cond];
          peakCond = cond;
        }
      }
      const direction: "positive_substrate_footprint" | "negative_substrate_footprint" | "near_zero_footprint" =
        peakVal > 0.3 ? "positive_substrate_footprint" : peakVal < -0.3 ? "negative_substrate_footprint" : "near_zero_footprint";

      // Find upstream receptors
      const kinaseUpper = (mod.canonical || mod.kinase).toUpperCase();
      const receptors: string[] = [];
      for (const rec of inferredReceptors) {
        if (rec.via_kinases?.some(k => k.toUpperCase() === kinaseUpper)) {
          receptors.push(rec.name);
        }
      }

      timeline.push({
        kinase: mod.kinase,
        canonical: mod.canonical || mod.kinase,
        peakCondition: peakCond,
        peakOrder: conditions.indexOf(peakCond),
        peakScore: peakVal,
        direction,
        scores,
        substrateCount: mod.members.length,
        upstreamReceptors: receptors,
      });
    }

    // Sort by peak order, then by peak score descending
    timeline.sort((a, b) => a.peakOrder - b.peakOrder || Math.abs(b.peakScore) - Math.abs(a.peakScore));
    return timeline;
  }, [globalKinaseResult, vectorData, conditions, inferredReceptors]);

  // Group by peak condition (time phase)
  const phaseGroups = useMemo(() => {
    const groups: Record<string, typeof kinaseTimeline> = {};
    for (const cond of conditions) groups[cond] = [];
    for (const entry of kinaseTimeline) {
      if (groups[entry.peakCondition]) groups[entry.peakCondition].push(entry);
    }
    return groups;
  }, [kinaseTimeline, conditions]);

  // Phase labels
  const phaseLabels: Record<number, string> = {
    0: "Immediate Early",
    1: "Secondary Response",
    2: "Late Response",
    3: "Sustained/Adaptive",
  };

  const phaseColors: Record<number, { bg: string; border: string; text: string; bar: string }> = {
    0: { bg: "bg-red-950/30", border: "border-red-500/30", text: "text-red-300", bar: "bg-red-500" },
    1: { bg: "bg-orange-950/30", border: "border-orange-500/30", text: "text-orange-300", bar: "bg-orange-500" },
    2: { bg: "bg-yellow-950/30", border: "border-yellow-500/30", text: "text-yellow-300", bar: "bg-yellow-500" },
    3: { bg: "bg-blue-950/30", border: "border-blue-500/30", text: "text-blue-300", bar: "bg-blue-500" },
  };

  // Cascade connections: kinases that share receptors across time phases
  const cascadeConnections = useMemo(() => {
    const connections: Array<{ from: string; to: string; sharedReceptors: string[]; fromPhase: number; toPhase: number }> = [];
    for (let i = 0; i < kinaseTimeline.length; i++) {
      for (let j = i + 1; j < kinaseTimeline.length; j++) {
        const a = kinaseTimeline[i];
        const b = kinaseTimeline[j];
        if (a.peakOrder >= b.peakOrder) continue; // only forward connections
        const shared = a.upstreamReceptors.filter(r => b.upstreamReceptors.includes(r));
        if (shared.length > 0) {
          connections.push({
            from: a.canonical,
            to: b.canonical,
            sharedReceptors: shared,
            fromPhase: a.peakOrder,
            toPhase: b.peakOrder,
          });
        }
      }
    }
    // Limit to top 20 connections by shared receptor count
    return connections.sort((a, b) => b.sharedReceptors.length - a.sharedReceptors.length).slice(0, 20);
  }, [kinaseTimeline]);

  if (kinaseTimeline.length === 0) {
    return (
      <div className="text-center py-8 text-sm text-muted-foreground">
        <Clock className="h-8 w-8 mx-auto mb-2 opacity-40" />
        No temporal kinase data available. Run Global Annotate first.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground flex items-center gap-1">
          <Clock className="h-3.5 w-3.5 text-orange-400" />
          Temporal cascade: kinase activation order across {conditions.length} time points
        </p>
        <div className="text-[10px] text-muted-foreground">
          {kinaseTimeline.length} kinases · {cascadeConnections.length} cascade connections
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-4 gap-2">
        {conditions.map((cond, idx) => {
          const group = phaseGroups[cond] || [];
          const positiveFootprints = group.filter(g => g.direction === "positive_substrate_footprint").length;
          const negativeFootprints = group.filter(g => g.direction === "negative_substrate_footprint").length;
          const colors = phaseColors[idx] || phaseColors[3];
          return (
            <div key={cond} className={`rounded-lg p-2 border ${colors.bg} ${colors.border}`}>
              <div className={`text-[10px] font-semibold ${colors.text}`}>
                {cond} — {phaseLabels[idx] || `Phase ${idx + 1}`}
              </div>
              <div className="text-lg font-bold text-foreground">{group.length}</div>
              <div className="text-[9px] text-muted-foreground">
                ▲{positiveFootprints} ▼{negativeFootprints}
              </div>
            </div>
          );
        })}
      </div>

      {/* Timeline visualization */}
      <div className="relative">
        {/* Time axis */}
        <div className="flex items-center mb-4">
          {conditions.map((cond, idx) => {
            const colors = phaseColors[idx] || phaseColors[3];
            return (
              <div key={cond} className="flex-1 flex items-center">
                <div className={`h-1 flex-1 ${colors.bar} rounded-full opacity-60`} />
                <div className={`mx-1 text-[10px] font-semibold ${colors.text} whitespace-nowrap`}>
                  {cond}
                </div>
                {idx < conditions.length - 1 && (
                  <ArrowRight className={`h-3 w-3 ${colors.text} opacity-60`} />
                )}
              </div>
            );
          })}
        </div>

        {/* Phase columns */}
        <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${conditions.length}, 1fr)` }}>
          {conditions.map((cond, idx) => {
            const group = phaseGroups[cond] || [];
            const colors = phaseColors[idx] || phaseColors[3];
            return (
              <div key={cond} className={`rounded-lg border p-2 ${colors.bg} ${colors.border} min-h-[120px]`}>
                <div className={`text-[9px] font-semibold mb-2 ${colors.text}`}>
                  {phaseLabels[idx] || `Phase ${idx + 1}`} ({group.length})
                </div>
                <div className="space-y-1 max-h-[500px] overflow-y-auto">
                  {group.map(entry => (
                    <div
                      key={entry.canonical}
                      className="flex items-center gap-1 text-[9px] cursor-pointer hover:bg-foreground/5 rounded px-1 py-0.5 transition-colors"
                      onClick={() => onKinaseClick?.(entry.canonical)}
                      title={`${entry.kinase}\nPeak: ${entry.peakCondition} (${entry.peakScore > 0 ? "+" : ""}${entry.peakScore.toFixed(2)})\nSubstrates: ${entry.substrateCount}\nReceptors: ${entry.upstreamReceptors.join(", ") || "unknown"}`}
                    >
                      <span className={`text-[8px] ${entry.direction === "positive_substrate_footprint" ? "text-red-400" : entry.direction === "negative_substrate_footprint" ? "text-blue-400" : "text-gray-400"}`}>
                        {entry.direction === "positive_substrate_footprint" ? "▲" : entry.direction === "negative_substrate_footprint" ? "▼" : "—"}
                      </span>
                      <span className="text-foreground font-medium truncate flex-1">{entry.kinase}</span>
                      <span className="text-muted-foreground">{entry.peakScore > 0 ? "+" : ""}{entry.peakScore.toFixed(1)}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Cascade connections */}
      {cascadeConnections.length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] font-semibold text-muted-foreground flex items-center gap-1">
            <ArrowRight className="h-3 w-3" />
            Cross-phase cascade connections (shared upstream receptors)
          </div>
          <div className="grid grid-cols-2 gap-1">
            {cascadeConnections.slice(0, 10).map((conn, i) => {
              const fromColors = phaseColors[conn.fromPhase] || phaseColors[3];
              const toColors = phaseColors[conn.toPhase] || phaseColors[3];
              return (
                <div key={i} className="flex items-center gap-1 text-[9px] px-2 py-1 rounded bg-muted/30 border border-border/50">
                  <span className={`font-medium ${fromColors.text}`}>{conn.from}</span>
                  <ArrowRight className="h-2.5 w-2.5 text-muted-foreground" />
                  <span className={`font-medium ${toColors.text}`}>{conn.to}</span>
                  <span className="text-muted-foreground ml-auto">
                    via {conn.sharedReceptors.slice(0, 2).join(", ")}{conn.sharedReceptors.length > 2 ? ` +${conn.sharedReceptors.length - 2}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-[9px] text-muted-foreground pt-2 border-t border-border/50">
        <span>▲ <span className="text-red-400">Activation</span> (kinase active)</span>
        <span>▼ <span className="text-blue-400">Inactivation</span> (phosphatase/suppressed)</span>
        <span>Click kinase → jump to Signal Flow</span>
        <span className="ml-auto">Cascade = shared upstream receptor across time phases</span>
      </div>
    </div>
  );
}

// ── Kinase Activity Heatmap View ──────────────────────────────────────────────────

type HeatmapSortMode = "peak_score" | "peak_time" | "confidence" | "substrate_count" | "alphabetical" | "cowave_group" | "condition_sort";
type HeatmapViewMode = "heatmap" | "line" | "selfPtm";

function KinaseActivityHeatmapView({
  orderId,
  globalKinaseResult,
  vectorData,
  conditions,
  onKinaseSelect,
  onSelectPtms,
  coWaveModules = [],
  isUbi = false,
}: {
  orderId: number;
  globalKinaseResult: GlobalKinaseModuleResponse;
  vectorData: PtmTimeSeriesRow[];
  conditions: string[];
  onKinaseSelect?: (kinase: string, cwGroup?: number, cwGroupKinases?: string[]) => void;
  onSelectPtms?: (keys: string[]) => void;
  coWaveModules?: CoWaveModule[];
  isUbi?: boolean;
}) {
  const [heatmapData, setHeatmapData] = useState<KinaseHeatmapData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<HeatmapSortMode>("peak_score");
  const [viewMode, setViewMode] = useState<HeatmapViewMode>("heatmap");
  const [topN, setTopN] = useState(20);
   const [selectedKinases, setSelectedKinases] = useState<Set<string>>(new Set());
  const [selectedCwGroupFilter, setSelectedCwGroupFilter] = useState<number | null>(null);
  const [signalTierFilter, setSignalTierFilter] = useState<"all" | "de_novo" | "regulated" | "minor">("all");
  const [sortByCondition, setSortByCondition] = useState<string | null>(null);
  const [patternFilter, setPatternFilter] = useState<string | null>(null);
  const [showSubPatterns, setShowSubPatterns] = useState(false);
  const [showCrossLayerEvidence, setShowCrossLayerEvidence] = useState(false);
  // v11.3: Expandable substrate list state
  const [expandedSubstrates, setExpandedSubstrates] = useState<Set<string>>(new Set());
  // v11.3: GO Localization dashboard state
  const [goLocSelection, setGoLocSelection] = useState<{ kinase: string; condition: string } | null>(null);
  const [goLocData, setGoLocData] = useState<{ gene_localizations: Record<string, string[]>; summary: Record<string, number> } | null>(null);
  const [goLocLoading, setGoLocLoading] = useState(false);
  // v11.3: Accumulative GO cache — stores all fetched gene localizations across all kinases
  const [goLocCache, setGoLocCache] = useState<Record<string, string[]>>({});
  const [hoveredLineKinase, setHoveredLineKinase] = useState<string | null>(null);
  // Track previous globalKinaseResult reference to avoid spurious heatmap re-fetches
  const prevKinaseResultRef = useRef<typeof globalKinaseResult | null>(null);
  const [lineTooltip, setLineTooltip] = useState<{ x: number; y: number; kinase: string; condition: string; score: number } | null>(null);
  // Fetch heatmap data from backend
  const fetchHeatmapData = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const kinase_modules = globalKinaseResult.kinase_modules.map((km) => ({
        kinase: km.kinase,
        ptms: km.members.map((m) => ({ gene: m.gene, position: m.position })),
        confidence_score: Number.isFinite(km.confidence_score) ? km.confidence_score : null,
      }));
      const result = await api.post<KinaseHeatmapData>(
        `/orders/${orderId}/kinase-activity-heatmap`,
        { kinase_modules, force_refresh: forceRefresh }
      );
      setHeatmapData(result);
    } catch (err: any) {
      setError(err?.message || "Failed to compute kinase activity heatmap");
    } finally {
      setLoading(false);
    }
  }, [orderId, globalKinaseResult]);

  useEffect(() => {
    if (!globalKinaseResult?.kinase_modules?.length) return;
    // Skip if the result reference hasn't changed (prevents spurious re-fetches on re-renders)
    if (prevKinaseResultRef.current === globalKinaseResult) return;
    prevKinaseResultRef.current = globalKinaseResult;
    fetchHeatmapData(false);
  }, [fetchHeatmapData, globalKinaseResult]);

  // v11.3: Fetch GO Cellular Component data when a heatmap cell is clicked
  // Accumulative: merges new gene data into goLocCache so all expanded rows can show badges
  useEffect(() => {
    if (!goLocSelection) return;
    const { kinase } = goLocSelection;
    // Find substrate genes for this kinase from globalKinaseResult
    const kinaseUpper = kinase.toUpperCase();
    const genes: string[] = [];
    // Primary source: globalKinaseResult modules
    if (globalKinaseResult) {
      for (const mod of globalKinaseResult.kinase_modules) {
        if (mod.kinase.toUpperCase() === kinaseUpper || (mod.canonical || "").toUpperCase() === kinaseUpper) {
          for (const m of mod.members) {
            const g = m.gene.toUpperCase();
            if (!genes.includes(g)) genes.push(g);
          }
        }
      }
    }
    // Fallback: extract genes from heatmapData kinase_scores substrates
    if (genes.length === 0 && heatmapData) {
      const ksEntry = heatmapData.kinase_scores?.find(
        (ks: any) => (ks.kinase || "").toUpperCase() === kinaseUpper ||
                     (ks.parent_kinase || "").toUpperCase() === kinaseUpper
      );
      if (ksEntry?.substrates) {
        for (const sub of ksEntry.substrates) {
          const g = (sub.gene || "").toUpperCase();
          if (g && !genes.includes(g)) genes.push(g);
        }
      }
    }
    if (genes.length === 0) return;
    // Only fetch genes not already in cache
    const newGenes = genes.filter(g => !(g in goLocCache));
    if (newGenes.length === 0) {
      // Already have all data — just update goLocData for the dashboard
      const summary: Record<string, number> = {};
      for (const g of genes) {
        for (const loc of (goLocCache[g] || [])) {
          summary[loc] = (summary[loc] || 0) + 1;
        }
      }
      setGoLocData({ gene_localizations: goLocCache, summary });
      return;
    }
    setGoLocLoading(true);
    api.post<{ gene_localizations: Record<string, string[]>; summary: Record<string, number> }>(
      `/orders/${orderId}/substrate-go-localization`,
      { genes: newGenes }
    ).then((data) => {
      // Merge into accumulative cache
      setGoLocCache(prev => ({ ...prev, ...data.gene_localizations }));
      // Compute full summary for current selection
      const merged = { ...goLocCache, ...data.gene_localizations };
      const summary: Record<string, number> = {};
      for (const g of genes) {
        for (const loc of (merged[g] || [])) {
          summary[loc] = (summary[loc] || 0) + 1;
        }
      }
      setGoLocData({ gene_localizations: merged, summary });
    }).catch((err) => {
      console.error('[GO-CC] Heatmap cell fetch failed:', err?.message || err);
      // Don't null out existing data on error
    }).finally(() => {
      setGoLocLoading(false);
    });
  }, [goLocSelection, globalKinaseResult, orderId, goLocCache]);

  // Sort kinase scores
  // Helper: get total co-activation magnitude for a kinase in the selected tier
  const getTierTotalSignal = useCallback((ks: KinaseActivityScore) => {
    if (!heatmapData) return 0;
    let total = 0;
    for (const c of heatmapData.conditions) {
      if (signalTierFilter === "all") {
        total += Math.abs(ks.up_sums?.[c] || 0) + Math.abs(ks.down_sums?.[c] || 0);
      } else {
        const tier = ks.tiers?.[signalTierFilter];
        if (tier) {
          total += Math.abs(tier.up_sums?.[c] || 0) + Math.abs(tier.down_sums?.[c] || 0);
        }
      }
    }
    return total;
  }, [heatmapData, signalTierFilter]);

  const sortedScores = useMemo(() => {
    if (!heatmapData) return [];
    let scores = [...heatmapData.kinase_scores];

    // v11.3: Filter sub-patterns based on toggle
    if (!showSubPatterns) {
      scores = scores.filter((ks) => !ks.is_sub_pattern);
    }

    // v11.3.4: Hide kinases superseded by self-PTM kinases in same substrate group
    scores = scores.filter((ks) => !ks.hidden_by_self_ptm);

    // When a specific tier is selected, filter out kinases with zero signal in that tier
    if (signalTierFilter !== "all") {
      scores = scores.filter((ks) => {
        const tier = ks.tiers?.[signalTierFilter];
        if (!tier) return false;
        const conditions = heatmapData.conditions;
        for (const c of conditions) {
          if ((tier.up_sums?.[c] || 0) !== 0 || (tier.down_sums?.[c] || 0) !== 0) return true;
        }
        return false;
      });
    }

    // Sort: when tier filter is active and sort is peak_score, sort by tier signal instead
    if (signalTierFilter !== "all" && (sortMode === "peak_score" || sortMode === "substrate_count")) {
      scores.sort((a, b) => getTierTotalSignal(b) - getTierTotalSignal(a));
    } else {
      switch (sortMode) {
        case "peak_score":
          scores.sort((a, b) => Math.abs(b.peak_score) - Math.abs(a.peak_score));
          break;
        case "peak_time": {
          const condOrder = heatmapData.conditions;
          scores.sort((a, b) => condOrder.indexOf(a.peak_condition) - condOrder.indexOf(b.peak_condition));
          break;
        }
        case "confidence":
          scores.sort((a, b) => (b.footprint_diagnostics?.effective_substrate_number ?? -1) - (a.footprint_diagnostics?.effective_substrate_number ?? -1));
          break;
        case "substrate_count":
          scores.sort((a, b) => b.substrate_count - a.substrate_count);
          break;
        case "alphabetical":
          scores.sort((a, b) => a.kinase.localeCompare(b.kinase));
          break;
        case "cowave_group":
          scores.sort((a, b) => {
            const ga = a.cowave_group ?? 999;
            const gb = b.cowave_group ?? 999;
            if (ga !== gb) return ga - gb;
            if (signalTierFilter !== "all") return getTierTotalSignal(b) - getTierTotalSignal(a);
            return Math.abs(b.peak_score) - Math.abs(a.peak_score);
          });
          break;
        case "condition_sort":
          if (sortByCondition) {
            scores.sort((a, b) => {
              // Sort by total activation (|up| + |down|) at this condition
              const getCondSignal = (ks: KinaseActivityScore) => {
                if (signalTierFilter === "all") {
                  return Math.abs(ks.up_sums?.[sortByCondition] || 0) + Math.abs(ks.down_sums?.[sortByCondition] || 0);
                }
                const tier = ks.tiers?.[signalTierFilter];
                if (!tier) return 0;
                return Math.abs(tier.up_sums?.[sortByCondition] || 0) + Math.abs(tier.down_sums?.[sortByCondition] || 0);
              };
              return getCondSignal(b) - getCondSignal(a);
            });
          }
          break;
      }
    }
    // v11.3: Re-arrange sub-patterns to appear directly after their parent
    if (showSubPatterns) {
      const result: KinaseActivityScore[] = [];
      const subsByParent = new Map<string, KinaseActivityScore[]>();
      for (const s of scores) {
        if (s.is_sub_pattern && s.parent_kinase) {
          if (!subsByParent.has(s.parent_kinase)) subsByParent.set(s.parent_kinase, []);
          subsByParent.get(s.parent_kinase)!.push(s);
        }
      }
      for (const s of scores) {
        if (s.is_sub_pattern) continue;
        result.push(s);
        const children = subsByParent.get(s.kinase);
        if (children) result.push(...children);
      }
      return result.slice(0, topN);
    }
    return scores.slice(0, topN);
  }, [heatmapData, sortMode, topN, signalTierFilter, getTierTotalSignal, sortByCondition, showSubPatterns]);

  // Color scale for heatmap: blue(-) → white(0) → red(+)
  const getHeatmapColor = (value: number, maxAbs: number) => {
    if (maxAbs === 0) return "rgb(30, 30, 40)";
    const norm = Math.max(-1, Math.min(1, value / maxAbs));
    if (norm > 0) {
      const r = Math.round(30 + 225 * norm);
      const g = Math.round(30 + 50 * (1 - norm));
      const b = Math.round(40 * (1 - norm));
      return `rgb(${r}, ${g}, ${b})`;
    } else {
      const intensity = Math.abs(norm);
      const r = Math.round(30 * (1 - intensity));
      const g = Math.round(30 + 100 * intensity);
      const b = Math.round(40 + 215 * intensity);
      return `rgb(${r}, ${g}, ${b})`;
    }
  };

  // Get effective up/down values based on tier filter
  const getEffectiveValues = useCallback((ks: KinaseActivityScore, c: string) => {
    if (signalTierFilter === "all") {
      return {
        upVal: ks.up_sums?.[c] || 0,
        dnVal: ks.down_sums?.[c] || 0,
        upN: ks.up_counts?.[c] || 0,
        dnN: ks.down_counts?.[c] || 0,
      };
    }
    const tier = ks.tiers?.[signalTierFilter];
    if (!tier) return { upVal: 0, dnVal: 0, upN: 0, dnN: 0 };
    return {
      upVal: tier.up_sums?.[c] || 0,
      dnVal: tier.down_sums?.[c] || 0,
      upN: tier.up_counts?.[c] || 0,
      dnN: tier.down_counts?.[c] || 0,
    };
  }, [signalTierFilter]);

  // Bar height = √(count) (sqrt scale to prevent domination by high-substrate kinases)
  // Color intensity = average |FC| per substrate (quality of signal)
  // Number = Sum (total signal)
  const { maxSqrtUp, maxSqrtDown, maxAvgUp, maxAvgDown, maxUp, maxDown } = useMemo(() => {
    if (!sortedScores.length) return { maxSqrtUp: 1, maxSqrtDown: 1, maxAvgUp: 1, maxAvgDown: 1, maxUp: 1, maxDown: 1 };
    let mSqrtUp = 1;
    let mSqrtDn = 1;
    let mAvgUp = 0.1;
    let mAvgDn = 0.1;
    let mUp = 0.1;
    let mDn = 0.1;
    for (const s of sortedScores) {
      for (const c of (heatmapData?.conditions || [])) {
        const { upVal, dnVal, upN, dnN } = getEffectiveValues(s, c);
        mUp = Math.max(mUp, upVal);
        mDn = Math.max(mDn, Math.abs(dnVal));
        mSqrtUp = Math.max(mSqrtUp, Math.sqrt(upN));
        mSqrtDn = Math.max(mSqrtDn, Math.sqrt(dnN));
        if (upN > 0) mAvgUp = Math.max(mAvgUp, upVal / upN);
        if (dnN > 0) mAvgDn = Math.max(mAvgDn, Math.abs(dnVal) / dnN);
      }
    }
    return { maxSqrtUp: mSqrtUp, maxSqrtDown: mSqrtDn, maxAvgUp: mAvgUp, maxAvgDown: mAvgDn, maxUp: mUp, maxDown: mDn };
  }, [sortedScores, heatmapData?.conditions, getEffectiveValues]);

  // Keep maxAbsScore for line chart and legacy uses
  const maxAbsScore = useMemo(() => Math.max(maxUp, maxDown), [maxUp, maxDown]);

  // Line chart colors
  const LINE_COLORS = [
    "#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4",
    "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6", "#f59e0b",
    "#6366f1", "#10b981", "#f43f5e", "#0ea5e9", "#a855f7",
    "#84cc16", "#e11d48", "#0891b2", "#7c3aed", "#d97706",
  ];

  // Co-wave group color palette (expanded to 16 for large datasets)
  const COWAVE_GROUP_COLORS = [
    { bar: "bg-cyan-400", text: "text-cyan-300", hex: "#22d3ee" },
    { bar: "bg-fuchsia-400", text: "text-fuchsia-300", hex: "#e879f9" },
    { bar: "bg-amber-400", text: "text-amber-300", hex: "#fbbf24" },
    { bar: "bg-indigo-400", text: "text-indigo-300", hex: "#818cf8" },
    { bar: "bg-lime-400", text: "text-lime-300", hex: "#a3e635" },
    { bar: "bg-pink-400", text: "text-pink-300", hex: "#f472b6" },
    { bar: "bg-sky-400", text: "text-sky-300", hex: "#38bdf8" },
    { bar: "bg-orange-400", text: "text-orange-300", hex: "#fb923c" },
    { bar: "bg-emerald-400", text: "text-emerald-300", hex: "#34d399" },
    { bar: "bg-rose-400", text: "text-rose-300", hex: "#fb7185" },
    { bar: "bg-violet-400", text: "text-violet-300", hex: "#a78bfa" },
    { bar: "bg-teal-400", text: "text-teal-300", hex: "#2dd4bf" },
    { bar: "bg-red-400", text: "text-red-300", hex: "#f87171" },
    { bar: "bg-blue-400", text: "text-blue-300", hex: "#60a5fa" },
    { bar: "bg-yellow-400", text: "text-yellow-300", hex: "#facc15" },
    { bar: "bg-purple-400", text: "text-purple-300", hex: "#c084fc" },
  ];

  // Coherence color helper (0→gray, 1→green)
  const getCoherenceColor = (val: number) => {
    if (val >= 0.7) return "text-green-400";
    if (val >= 0.4) return "text-yellow-400";
    return "text-muted-foreground";
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-cyan-400 mr-2" />
        <span className="text-sm text-muted-foreground">Computing kinase activity scores...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-red-400 mb-2">{error}</p>
        <Button size="sm" variant="outline" onClick={() => fetchHeatmapData(true)}>
          <RefreshCw className="h-3 w-3 mr-1" /> Retry
        </Button>
      </div>
    );
  }

  if (!heatmapData || !sortedScores.length) {
    return (
      <div className="text-center py-8 text-muted-foreground text-sm">
        No kinase activity data available. Run Global Annotate first.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant={viewMode === "heatmap" ? "default" : "ghost"}
            className="text-xs h-7"
            onClick={() => setViewMode("heatmap")}
          >
            Heatmap
          </Button>
          <Button
            size="sm"
            variant={viewMode === "line" ? "default" : "ghost"}
            className="text-xs h-7"
            onClick={() => setViewMode("line")}
          >
            Line Chart
          </Button>
          <Button
            size="sm"
            variant={viewMode === "selfPtm" ? "default" : "ghost"}
            className="text-xs h-7"
            onClick={() => setViewMode("selfPtm")}
          >
            Self-PTM
          </Button>
        </div>
        <span className="text-xs text-muted-foreground">Sort:</span>
        <select
          className="text-xs h-7 bg-background border border-border rounded px-2"
          value={sortMode}
          onChange={(e) => {
            const mode = e.target.value as HeatmapSortMode;
            setSortMode(mode);
            // Auto-expand to show all when sorting by local co-membership group
            if (mode === "cowave_group") setTopN(9999);
          }}
        >
          <option value="peak_score">Peak Score</option>
          <option value="peak_time">Peak Time</option>
          <option value="confidence">Effective Support</option>
          <option value="substrate_count">Substrate Count</option>
          <option value="alphabetical">Alphabetical</option>
          <option value="cowave_group">{TEMPORAL_TERMS.localGroup}</option>
        </select>
        <span className="text-xs text-muted-foreground">Top:</span>
        <select
          className="text-xs h-7 bg-background border border-border rounded px-2"
          value={topN}
          onChange={(e) => setTopN(Number(e.target.value))}
        >
          <option value={10}>10</option>
          <option value={20}>20</option>
          <option value={30}>30</option>
          <option value={50}>50</option>

          <option value={9999}>All</option>
        </select>
        <span className="text-xs text-muted-foreground">Signal:</span>
        <select
          className="text-xs h-7 bg-background border border-border rounded px-2"
          value={signalTierFilter}
          onChange={(e) => setSignalTierFilter(e.target.value as typeof signalTierFilter)}
          title="Filter by representation/signal tier:\n  de_novo: declared detection/LOD representation only\n  regulated: conventional |Log2FC|≥0.58\n  minor: conventional 0.3≤|Log2FC|<0.58\n\nDe novo pseudo-Log2FC is never used to assign this tier."
        >
          <option value="all">All Tiers</option>
          <option value="de_novo">De Novo (detection/LOD)</option>
          <option value="regulated">Regulated (0.58≤|FC|&lt;2)</option>
          <option value="minor">Minor (0.3≤|FC|&lt;0.58)</option>
        </select>
        {/* v11.3: Multi-pattern toggle */}
        <label className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer ml-2" title="Show non-dominant cluster sub-patterns\n(e.g., early vs late response phases)">
          <input
            type="checkbox"
            checked={showSubPatterns}
            onChange={(e) => setShowSubPatterns(e.target.checked)}
            className="w-3 h-3 rounded"
          />
          Sub-patterns
        </label>
        <div className="ml-auto flex items-center gap-1">
          {heatmapData._cached && (
            <Badge variant="outline" className="text-[10px] h-5 text-green-400 border-green-600">cached</Badge>
          )}
          {(heatmapData as any)._stale && (
            <Badge variant="outline" className="text-[10px] h-5 text-amber-400 border-amber-600">outdated</Badge>
          )}
          <Button size="sm" variant="ghost" className="text-xs h-7" onClick={() => fetchHeatmapData(true)}>
            <RefreshCw className="h-3 w-3 mr-1" /> Refresh
          </Button>
        </div>
      </div>

      {heatmapData.temporal_ptm_protein_analysis && (
        <div className="border border-teal-300/70 dark:border-teal-800 rounded-lg bg-teal-50/50 dark:bg-teal-950/20">
          <button
            type="button"
            onClick={() => setShowCrossLayerEvidence((visible) => !visible)}
            className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left"
            aria-expanded={showCrossLayerEvidence}
          >
            <span className="flex items-center gap-2 text-xs font-medium text-teal-800 dark:text-teal-200">
              <ArrowRight className="h-3.5 w-3.5" />
              Shared PTM–Protein Temporal Evidence
              <span className="font-normal text-teal-700/80 dark:text-teal-300/80">
                — same engine as strict-blind benchmark, observational only
              </span>
            </span>
            <span className="text-[10px] text-teal-700 dark:text-teal-300">
              {showCrossLayerEvidence ? "Hide" : "Show"}
            </span>
          </button>
          {showCrossLayerEvidence && (() => {
            const evidence = heatmapData.temporal_ptm_protein_analysis!;
            const rows = evidence.top_cross_layer_edges || [];
            return (
              <div className="border-t border-teal-200/80 dark:border-teal-900 px-3 py-2 space-y-2">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1 text-[10px] text-teal-900 dark:text-teal-100">
                  <span>Protein trajectories: <b>{evidence.protein_trajectory_count || 0}</b></span>
                  <span>PTM–protein pairs: <b>{evidence.ptm_protein_pair_count || 0}</b></span>
                  <span>Cross-layer edges: <b>{evidence.cross_layer_edge_count || 0}</b></span>
                  <span>Temporal eligible: <b>{evidence.temporally_eligible_edge_count || 0}</b></span>
                  <span>Mechanism candidates: <b>{evidence.mechanism_chain_count || 0}</b></span>
                  <span>Evidence-supported: <b>{evidence.evidence_supported_mechanism_count || 0}</b></span>
                  <span>Kinase timing: <b>{evidence.kinase_timing_status || "not_available"}</b></span>
                  <span>{TEMPORAL_TERMS.localTransition}: <b>{formatLocalTransitionStatus(evidence.dynamic_co_wave_transition_status)}</b></span>
                  <span>Concordance-annotated clusters: <b>{evidence.dynamic_transition_supported_wave_count ?? 0}</b></span>
                  <span>Observed pair transitions: <b>{evidence.dynamic_transition_pair_count ?? 0}</b></span>
                  <span>Causality: <b>not tested</b></span>
                </div>
                <p className="text-[10px] text-teal-800/80 dark:text-teal-200/80">
                  {TEMPORAL_TERMS.localTransition} summarizes retained concordance, concordance gain, or concordance loss from pairwise endpoint activity-state agreement within a fixed {TEMPORAL_TERMS.cluster}. It does not re-estimate cluster membership, change TMM attribution or kinase ranking, or establish co-regulation, kinase switching, or causality.
                </p>
                {rows.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-[10px]">
                      <thead className="text-muted-foreground">
                        <tr className="border-b border-teal-200/70 dark:border-teal-900">
                          <th className="text-left py-1 pr-2">Temporal Profile Cluster</th>
                          <th className="text-left py-1 pr-2">Protein</th>
                          <th className="text-left py-1 pr-2">Temporal direction</th>
                          <th className="text-right py-1 pr-2">Peak lag (min)</th>
                          <th className="text-left py-1">Interpretation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((edge, index) => (
                          <tr key={edge.edge_id || `${edge.source_wave_id}-${edge.target_gene}-${index}`} className="border-b border-teal-100/70 dark:border-teal-950">
                            <td className="py-1 pr-2">{edge.source_wave_id ?? "—"}</td>
                            <td className="py-1 pr-2 font-medium">{edge.target_gene || "—"}</td>
                            <td className="py-1 pr-2">{edge.direction || "unknown"}</td>
                            <td className="py-1 pr-2 text-right">{edge.peak_lag_minutes ?? "—"}</td>
                            <td className="py-1">{edge.eligible_for_mechanism_chain ? "falsifiable temporal candidate" : "observational candidate"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-[10px] text-muted-foreground">No retained cross-layer edge is available for this order.</p>
                )}
                <p className="text-[10px] text-muted-foreground">
                  {evidence.interpretation_boundary || "Temporal precedence is observational; this panel does not assert causal mechanism."}
                </p>
              </div>
            );
          })()}
        </div>
      )}

      {/* Heatmap View */}
      {viewMode === "heatmap" && (
        <div className="overflow-x-auto border border-border rounded-lg">
          <table className="w-full text-xs">
            <thead>
              {/* Peak Sync Indicator Row */}
              {heatmapData.peak_sync && Object.keys(heatmapData.peak_sync).length > 0 && (
                <tr className="border-b border-border/20">
                  <th className="sticky left-0 bg-background z-10" />{/* concordant phosphosite set bar spacer */}
                  <th />{/* Kinase spacer */}
                  <th />{/* Dir spacer */}
                  <th />{/* #Sub spacer */}
                  <th />{/* Conf spacer */}
                  <th />{/* Coh spacer */}
                  {heatmapData.conditions.map((c) => {
                    const sync = heatmapData.peak_sync?.[c];
                    return (
                      <th key={`sync-${c}`} className="text-center px-0 py-0.5">
                        {sync ? (
                          <span
                            className="text-amber-400 text-[9px] cursor-help"
                            title={`Peak Sync: ${sync.count} kinases peak at ${c}\n${sync.kinases.join(", ")}`}
                          >
                            ⚡{sync.count}
                          </span>
                        ) : null}
                      </th>
                    );
                  })}
                </tr>
              )}
              {/* Main header row */}
              <tr className="border-b border-border">
                <th className="w-2 px-0 py-1 cursor-help" title={`${TEMPORAL_TERMS.localGroup} (CS)\n\nColor bar = ${isUbi ? "E3 ligases" : "kinases"} with similar temporal substrate-footprint profiles (Pearson r≥0.7).\nSame color = same descriptive set.\n\nS-label (e.g. S2) = concordant phosphosite set number.\nThis diagnostic does not establish common regulation or direct kinase attribution.\n\nClick a set in the legend below to filter Vector Plot.`}>CS</th>
                <th className="text-left px-2 py-1 sticky left-0 bg-background z-10 min-w-[100px] cursor-help" title={`${isUbi ? "E3 Ligase" : "Kinase"}\n\nName of the ${isUbi ? "E3 ligase" : "kinase"} (or ${isUbi ? "E3 ligase" : "kinase"} family).\nG-label shows its ${TEMPORAL_TERMS.localGroup} number.`}>{isUbi ? "E3 Ligase" : "Kinase"}</th>
                <th className="text-center px-1 py-1 w-8 cursor-help" title={`Signed substrate footprint\n\n  ▲ = positive weighted aggregate substrate footprint\n  ▼ = negative weighted aggregate substrate footprint\n  — = near-zero/mixed footprint\n\nThis is not direct catalytic activation, inhibition, or kinase attribution.`}>Dir</th>
                <th className="text-center px-1 py-1 w-10 cursor-help" title={`Number of Substrates (#Sub)\n\nTotal confirmed + inferred ${isUbi ? "ubiquitylation" : "phosphorylation"} substrates\nfor this ${isUbi ? "E3 ligase" : "kinase"} in the current dataset.`}>#Sub</th>
                <th className="text-center px-1 py-1 w-10 cursor-help" title={`Effective support (n_eff)\n\nContribution-weighted effective substrate number. It falls when one substrate dominates the footprint.\n\nNo scalar confidence percentage is shown because bootstrap, replicate and permutation calibration are not always available.`}>n_eff</th>
                <th className="text-center px-1 py-1 w-10 cursor-help" title={`Coherence (Coh)\n\nRaw mean pairwise |Pearson r| is shown with its support-adjusted diagnostic in the tooltip. The support adjustment is descriptive only; it does not change rank or score.`}>Coh</th>
                {heatmapData.conditions.map((c) => (
                  <th
                    key={c}
                    className={`text-center px-1 py-1 min-w-[40px] max-w-[60px] truncate cursor-pointer select-none transition-colors ${
                      sortByCondition === c && sortMode === "condition_sort" ? "bg-amber-900/40 text-amber-300" : "hover:bg-muted/40 cursor-help"
                    }`}
                    title={`Click to sort by signed substrate-footprint summary at ${c}\n\nFootprint sum at this sampled condition.\n= Sum of Log2FC for substrates passing threshold\n  (q<0.05 or |Log2FC|≥0.3)\n\nPositive (warm) and negative (cool) show observed signed substrate contrasts; neither denotes catalytic activation or inhibition.`}
                    onClick={() => {
                      setSortByCondition(c);
                      setSortMode("condition_sort");
                    }}
                  >
                    {c.replace(/min$/i, "").replace(/hr$/i, "h")}
                    {sortByCondition === c && sortMode === "condition_sort" && <span className="ml-0.5 text-amber-400">▼</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedScores.map((ks) => {
                const cwGroup = ks.cowave_group ?? -1;
                const cwColor = cwGroup >= 0 ? COWAVE_GROUP_COLORS[cwGroup % COWAVE_GROUP_COLORS.length] : null;
                return (
                <Fragment key={ks.kinase}>
                  <tr
                    className="border-b border-border/30 hover:bg-muted/20 cursor-pointer"
                    onClick={() => {
                      setSelectedKinases((prev) => {
                        const next = new Set(prev);
                        if (next.has(ks.kinase)) next.delete(ks.kinase);
                        else next.add(ks.kinase);
                        return next;
                      });
                      const cwKinases = cwGroup >= 0 && heatmapData?.cowave_groups
                        ? heatmapData.cowave_groups.find(g => g.group_id === cwGroup)?.kinases || []
                        : [];
                      onKinaseSelect?.(ks.kinase, cwGroup >= 0 ? cwGroup : undefined, cwKinases);
                    }}
                  >
                    {/* Co-wave Group Color Bar */}
                    <td className="px-0 py-0 w-2">
                      {cwColor ? (() => {
                        const grpInfo = heatmapData.cowave_groups?.find(g => g.group_id === cwGroup);
                        const tipLines = [
                          `${TEMPORAL_TERMS.localGroup} G${cwGroup}`,
                          grpInfo?.dominant_peak ? `Peak: ${grpInfo.dominant_peak}` : "",
                          grpInfo ? `Members (${grpInfo.size}): ${grpInfo.kinases.slice(0, 8).join(", ")}${grpInfo.kinases.length > 8 ? "..." : ""}` : "",
                          grpInfo ? `Correlation: r=${grpInfo.mean_correlation.toFixed(2)}` : "",
                          "",
                          "Kinases in this group have highly correlated",
                          "temporal substrate activity patterns (r≥0.7).",
                        ].filter(Boolean).join("\n");
                        return (
                          <div
                            className={`w-1.5 h-full min-h-[40px] rounded-sm ${cwColor.bar}`}
                            title={tipLines}
                          />
                        );
                      })() : (
                        <div className="w-1.5 min-h-[40px]" />
                      )}
                    </td>
                    {/* Kinase name + v11.3 Tier Badge */}
                    <td className={`px-2 py-1 sticky left-0 bg-background z-10 font-medium whitespace-nowrap ${ks.is_sub_pattern ? "pl-6" : ""}`}>
                      {ks.is_sub_pattern && (
                        <span className="text-muted-foreground/40 mr-1 text-[9px]">└─</span>
                      )}
                      {selectedKinases.has(ks.kinase) && <span className="text-cyan-400 mr-1">●</span>}
                      {ks.is_sub_pattern ? (
                        <span className="text-muted-foreground/80 italic">
                          {ks.parent_kinase}
                          <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-sky-500/20 text-sky-300 border border-sky-500/30">
                            peak@{ks.sub_pattern_label || ks.peak_condition || "?"}
                          </span>
                        </span>
                      ) : (
                        <>
                          {ks.kinase}
                          {ks.footprint_equivalence && (
                            <span
                              className="ml-1 text-[8px] px-1 py-0 rounded border bg-amber-500/15 text-amber-300 border-amber-500/30 cursor-help"
                              title={`Exact footprint equivalence\n\nMembers: ${ks.footprint_equivalence.members.join(", ")}\nObserved sites: ${ks.footprint_equivalence.site_count}\n\n${ks.footprint_equivalence.interpretation_boundary}`}
                            >
                              =F{ks.footprint_equivalence.member_count}
                            </span>
                          )}
                        </>
                      )}
                      {/* v11.3.1: Same-time cluster count badge (tooltip shows details) */}
                      {!ks.is_sub_pattern && ks.same_time_clusters && ks.same_time_clusters.length > 0 && (() => {
                        const stc = ks.same_time_clusters!;
                        const tierMap: Record<string, string> = { strong: "S", moderate: "M", weak: "W", mixed: "?" };
                        const totalSubs = stc.reduce((sum, c) => sum + c.size, 0);
                        const tipLines = stc.map(c =>
                          `[${tierMap[c.tier] || c.tier}] ${c.size} substrates (peak=${c.peak_score > 0 ? "+" : ""}${c.peak_score})\n` +
                          c.substrates.slice(0, 5).map(s => `  ${s.gene} ${s.site} ${s.peak_fc > 0 ? "+" : ""}${s.peak_fc}`).join("\n") +
                          (c.substrates.length > 5 ? `\n  ...+${c.substrates.length - 5} more` : "")
                        ).join("\n\n");
                        return (
                          <span
                            className="ml-1 text-[8px] px-1 py-0 rounded border bg-violet-500/15 text-violet-300 border-violet-500/30 cursor-help"
                            title={`Same-time clusters (peak@${ks.peak_condition})\n${stc.length} additional cluster(s), ${totalSubs} substrates\n\n${tipLines}\n\nThese clusters peak at the same time as the dominant\ncluster but with different magnitude tiers.`}
                          >
                            +{stc.length}
                          </span>
                        );
                      })()}
                      {/* v11.3: Magnitude Tier badge from dominant cluster */}
                      {(() => {
                        const domCluster = ks.cluster_details?.find(cd => cd.is_dominant);
                        const tier = domCluster?.tier;
                        if (!tier || tier === "mixed") return null;
                        const tierStyles: Record<string, string> = {
                          strong: "bg-red-500/20 text-red-300 border-red-500/40",
                          moderate: "bg-amber-500/20 text-amber-300 border-amber-500/40",
                          weak: "bg-slate-500/20 text-slate-300 border-slate-500/40",
                        };
                        const tierLabels: Record<string, string> = {
                          strong: "S",
                          moderate: "M",
                          weak: "W",
                        };
                        const tierTitles: Record<string, string> = {
                          strong: "Tier 1 (Strong): max |Log2FC| > 5.0\nHigh-amplitude dominant-cluster observation; not a direct regulatory-strength claim",
                          moderate: "Tier 2 (Moderate): 2.0 < max |Log2FC| ≤ 5.0\nRegulated substrates",
                          weak: "Tier 3 (Weak): max |Log2FC| ≤ 2.0\nMinor change substrates",
                        };
                        return (
                          <span
                            className={`ml-1 inline-flex items-center justify-center w-3.5 h-3.5 text-[8px] font-bold rounded border cursor-help ${tierStyles[tier] || ""}`}
                            title={tierTitles[tier] || tier}
                          >
                            {tierLabels[tier] || tier[0].toUpperCase()}
                          </span>
                        );
                      })()}
                      {cwColor && (() => {
                        const grpInfo = heatmapData.cowave_groups?.find(g => g.group_id === cwGroup);
                        return (
                          <span
                            className={`ml-1 text-[8px] ${cwColor.text} opacity-70 cursor-help`}
                            title={grpInfo
                              ? `${TEMPORAL_TERMS.localGroup} G${cwGroup}\n\n` +
                                `Members (${grpInfo.size}): ${grpInfo.kinases.slice(0, 6).join(", ")}${grpInfo.kinases.length > 6 ? "..." : ""}\n` +
                                (grpInfo.dominant_peak ? `Peak: ${grpInfo.dominant_peak}\n` : "") +
                                `Correlation: r=${grpInfo.mean_correlation.toFixed(2)}\n\n` +
                                `Kinases whose substrates show correlated\ntemporal footprint patterns (r≥0.7). This is a descriptive diagnostic.\n\nClick group in legend to filter Vector Plot.`
                              : `Group ${cwGroup}`}
                          >
                            G{cwGroup}
                          </span>
                        );
                      })()}
                      {/* v11.3: Substrate expand/collapse button */}
                      {ks.substrates && ks.substrates.length > 0 && (
                        <button
                          className={`ml-1 text-[9px] px-1 py-0 rounded border transition-colors ${
                            expandedSubstrates.has(ks.kinase)
                              ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                              : "bg-muted/30 text-muted-foreground/60 border-border/50 hover:text-foreground/80"
                          }`}
                          title={expandedSubstrates.has(ks.kinase) ? "Hide substrates" : `Show ${ks.substrates.length} substrates with GO localization`}
                          onClick={(e) => {
                            e.stopPropagation();
                            const isExpanding = !expandedSubstrates.has(ks.kinase);
                            setExpandedSubstrates((prev) => {
                              const next = new Set(prev);
                              if (next.has(ks.kinase)) next.delete(ks.kinase);
                              else next.add(ks.kinase);
                              return next;
                            });
                            // Auto-fetch GO data for this row's substrates (independent of goLocLoading)
                            if (isExpanding && ks.substrates) {
                              const rowGenes = ks.substrates.map(s => s.gene.toUpperCase());
                              const missingGenes = rowGenes.filter(g => !(g in goLocCache));
                              if (missingGenes.length > 0) {
                                api.post<{ gene_localizations: Record<string, string[]>; summary: Record<string, number> }>(
                                  `/orders/${orderId}/substrate-go-localization`,
                                  { genes: missingGenes }
                                ).then((data) => {
                                  setGoLocCache(prev => ({ ...prev, ...data.gene_localizations }));
                                }).catch((err) => {
                                  console.error('[GO-CC] Fetch failed:', err);
                                });
                              }
                            }
                          }}
                        >
                          {expandedSubstrates.has(ks.kinase) ? "▾" : "▸"} {ks.substrates.length}
                        </button>
                      )}
                      {/* v11.3: Translocation flag */}
                      {ks.translocation_flag && (
                        <span
                          className="ml-1 text-[9px] cursor-help"
                          title={`🔄 Potential Nuclear Translocation detected\n\nThis kinase shows early cytoplasmic substrate activity\nfollowed by late nuclear substrate activity,\nsuggesting the kinase translocates from\ncytoplasm to nucleus over time.\n\nClick a heatmap cell to view GO localization details.`}
                        >
                          🔄
                        </span>
                      )}
                      {/* v11.3.2: Nuclear-exclusive substrate evidence badge */}
                      {!ks.is_sub_pattern && ks.nuclear_evidence && ks.nuclear_evidence.score > 0 && (() => {
                        const ne = ks.nuclear_evidence!;
                        // Badge style based on evidence strength
                        const badgeStyle = ne.tier1_count > 0
                          ? "bg-purple-500/20 text-purple-300 border-purple-500/40"  // Tier1 = confirmed nuclear
                          : "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"; // Tier2 only = likely nuclear
                        // v11.3.4b: Check cluster membership details
                        const t1Details = (ne as any).tier1_details as { gene: string; in_dominant: boolean }[] | undefined;
                        const t2Details = (ne as any).tier2_details as { gene: string; in_dominant: boolean }[] | undefined;
                        const t1InDom = t1Details?.filter(d => d.in_dominant).map(d => d.gene) || [];
                        const t1NotDom = t1Details?.filter(d => !d.in_dominant).map(d => d.gene) || [];
                        const t2InDom = t2Details?.filter(d => d.in_dominant).map(d => d.gene) || [];
                        const t2NotDom = t2Details?.filter(d => !d.in_dominant).map(d => d.gene) || [];
                        // Build tooltip
                        const tipParts: string[] = [];
                        if (ne.tier1_count > 0) {
                          tipParts.push(`🧬 Tier 1 (Absolute Nuclear Markers): ${ne.tier1_count}`);
                          if (t1InDom.length > 0) tipParts.push(`  ★ In dominant cluster: ${t1InDom.join(", ")}`);
                          if (t1NotDom.length > 0) tipParts.push(`  ○ In other cluster(s): ${t1NotDom.join(", ")}`);
                          tipParts.push("");
                        }
                        if (ne.tier2_count > 0) {
                          tipParts.push(`🔬 Tier 2 (Predominantly Nuclear): ${ne.tier2_count}`);
                          if (t2InDom.length > 0) tipParts.push(`  ★ In dominant cluster: ${t2InDom.slice(0, 8).join(", ")}${t2InDom.length > 8 ? ` +${t2InDom.length - 8}` : ""}`);
                          if (t2NotDom.length > 0) tipParts.push(`  ○ In other cluster(s): ${t2NotDom.slice(0, 8).join(", ")}${t2NotDom.length > 8 ? ` +${t2NotDom.length - 8}` : ""}`);
                          tipParts.push("");
                        }
                        tipParts.push(`Nuclear Evidence Score: ${ne.score} (T1×2 + T2×1)`);
                        tipParts.push("");
                        if (ne.tier1_count > 0) {
                          tipParts.push("Tier 1 substrates (histones, lamins, PCNA, PARP1,");
                          tipParts.push("DNA-PKcs, RNA Pol II) are exclusively nuclear.");
                          tipParts.push("Their phosphorylation is direct evidence that");
                          tipParts.push("this kinase was active inside the nucleus.");
                        } else {
                          tipParts.push("Tier 2 substrates (splicing factors, chromatin");
                          tipParts.push("remodelers, TFs) are predominantly nuclear.");
                          tipParts.push("Suggests likely nuclear kinase activity.");
                        }
                        if (t1NotDom.length > 0 || t2NotDom.length > 0) {
                          tipParts.push("");
                          tipParts.push("Note: Some nuclear markers are in non-dominant");
                          tipParts.push("clusters (different temporal pattern from main activity).");
                        }
                        // Compact display: show genes with cluster indicator
                        // Prioritize genes in dominant cluster, then others
                        const domGenes = [...t1InDom, ...t2InDom];
                        const otherGenes = [...t1NotDom, ...t2NotDom];
                        const displayGenes = domGenes.length > 0
                          ? domGenes.slice(0, 3)
                          : otherGenes.slice(0, 3);
                        const clusterNote = domGenes.length === 0 && otherGenes.length > 0 ? "†" : "";
                        return (
                          <span
                            className={`ml-1 text-[8px] px-1 py-0 rounded border cursor-help inline-flex items-center gap-0.5 ${badgeStyle}`}
                            title={tipParts.join("\n")}
                          >
                            {ne.tier1_count > 0 ? "🧬" : "🔬"}
                            <span className="font-medium">nuc</span>
                            <span className="opacity-70">{displayGenes.join(",")}{clusterNote}</span>
                          </span>
                        );
                      })()}
                      {/* v11.3.3: Regulator self-PTM correlation badge */}
                      {!ks.is_sub_pattern && ks.self_ptm && ks.self_ptm.length > 0 && (() => {
                        const spList = ks.self_ptm!;
                        // Determine badge style based on best relationship
                        const hasConcordant = spList.some(sp => sp.relationship === "concordant");
                        const hasDiscordant = spList.some(sp => sp.relationship === "discordant");
                        let badgeClass = "bg-gray-500/15 text-gray-300 border-gray-500/30"; // independent
                        let emoji = "📊";
                        if (hasConcordant && hasDiscordant) {
                          badgeClass = "bg-amber-500/20 text-amber-300 border-amber-500/40";
                          emoji = "⚡";
                        } else if (hasConcordant) {
                          badgeClass = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
                          emoji = "✓";
                        } else if (hasDiscordant) {
                          badgeClass = "bg-rose-500/20 text-rose-300 border-rose-500/40";
                          emoji = "⊘";
                        }
                        // Build tooltip
                        const tipLines: string[] = [
                          `Self-PTM Temporal Tracking (${spList.length} site${spList.length > 1 ? "s" : ""})`,
                          "",
                          "Compares this regulator's own PTM changes",
                          "with its substrate-inferred activity profile.",
                          "",
                        ];
                        for (const sp of spList.slice(0, 5)) {
                          const r = sp.correlation_with_activity;
                          const relLabel = sp.relationship === "concordant" ? "✓ concordant self-PTM temporal observation"
                            : sp.relationship === "discordant" ? "⊘ discordant self-PTM temporal observation"
                            : "— independent";
                          tipLines.push(`${sp.site}: peak@${sp.peak_condition} (${sp.peak_fc > 0 ? "+" : ""}${sp.peak_fc.toFixed(2)})`);
                          tipLines.push(`  r=${r > 0 ? "+" : ""}${r.toFixed(3)} → ${relLabel}`);
                        }
                        if (spList.length > 5) tipLines.push(`  +${spList.length - 5} more sites`);
                        // Compact display
                        const topSite = spList[0];
                        return (
                          <span
                            className={`ml-1 text-[8px] px-1 py-0 rounded border cursor-help inline-flex items-center gap-0.5 ${badgeClass}`}
                            title={tipLines.join("\n")}
                          >
                            {emoji}
                            <span className="font-medium">self</span>
                            <span className="opacity-70">{topSite.site}(r={topSite.correlation_with_activity > 0 ? "+" : ""}{topSite.correlation_with_activity.toFixed(2)})</span>
                          </span>
                        );
                      })()}
                    </td>
                    {/* Direction indicator */}
                    <td className="text-center px-0.5 py-0.5">
                      {ks.direction === "positive_substrate_footprint" ? (
                        <span className="text-red-400 font-bold text-xs" title="Positive weighted substrate footprint; not direct kinase activation">▲</span>
                      ) : ks.direction === "negative_substrate_footprint" ? (
                        <span className="text-blue-400 font-bold text-xs" title="Negative weighted substrate footprint; not direct kinase inhibition or phosphatase attribution">▼</span>
                      ) : (
                        <span className="text-muted-foreground/50 text-[9px]">—</span>
                      )}
                    </td>
                    {/* Substrate count (dominant cluster / total) */}
                    <td className="text-center px-1 py-0.5 text-muted-foreground"
                      title={(() => {
                        const domCl = ks.cluster_details?.find(cd => cd.is_dominant);
                        const tierStr = domCl?.tier ? `Magnitude Tier: ${domCl.tier.charAt(0).toUpperCase() + domCl.tier.slice(1)}\n` : "";
                        if (ks.total_substrates && ks.total_substrates !== ks.substrate_count) {
                          return `Dominant cluster: ${ks.substrate_count} substrates\n${tierStr}Total substrates: ${ks.total_substrates}\nClusters found: ${ks.n_clusters ?? 1}\n\nv11.3 Stratified Clustering:\nSubstrates grouped by magnitude tier, then\nclustered by Absolute Correlation (1-|r|) K-Means.\nOnly the dominant cluster (coherence × √size × |peak| × tier_bonus) is scored.`;
                        }
                        return `${ks.substrate_count} substrates${tierStr ? "\n" + tierStr : ""}`;
                      })()}
                    >
                      {ks.total_substrates && ks.total_substrates !== ks.substrate_count
                        ? <><span className="text-foreground">{ks.substrate_count}</span><span className="text-muted-foreground/50 text-[9px]">/{ks.total_substrates}</span></>
                        : ks.substrate_count
                      }
                    </td>
                    {/* Contribution-weighted effective support */}
                    <td className="text-center px-1 py-0.5">
                      <span className="text-cyan-300" title={(() => {
                        const diag = ks.footprint_diagnostics;
                        if (!diag || diag.status !== "computed") return "Effective support not evaluable because contribution-weighted site profiles are unavailable.";
                        const loo = diag.leave_one_substrate_out || [];
                        const top = loo[0];
                        return [
                          `Effective support: n_eff=${diag.effective_substrate_number?.toFixed(2) ?? "—"}`,
                          `Unique/shared: ${diag.n_exclusive ?? "—"}/${diag.n_shared ?? "—"} (shared ${(100 * (diag.shared_fraction ?? 0)).toFixed(1)}%)`,
                          `Dominant substrate leverage: ${(100 * (diag.dominant_substrate_fraction ?? 0)).toFixed(1)}%`,
                          top ? `Top leave-one-out: ${top.site_key}; peak ${top.peak_condition ?? "—"}; direction preserved=${top.direction_preserved ? "yes" : "no"}` : "No leave-one-out record",
                          diag.unique_only_footprint ? `Unique-only: ${diag.unique_only_footprint.status}; peak ${diag.unique_only_footprint.peak_condition ?? "—"}` : "",
                          "Diagnostic only: does not establish direct kinase attribution or causal regulation.",
                        ].filter(Boolean).join("\n");
                      })()}>
                        {ks.footprint_diagnostics?.status === "computed"
                          ? (ks.footprint_diagnostics.effective_substrate_number ?? 0).toFixed(1)
                          : "—"}
                      </span>
                    </td>
                    {/* Coherence */}
                    <td className="text-center px-1 py-0.5">
                      <span
                        className={`text-[10px] ${getCoherenceColor(ks.coherence ?? 0)}`}
                        title={`Raw intra-footprint coherence: ${(ks.coherence ?? 0).toFixed(3)}\nSupport-adjusted diagnostic coherence: ${(ks.footprint_diagnostics?.support_adjusted_coherence ?? 0).toFixed(3)}\n\nThe adjusted value shrinks raw coherence by the contribution-weighted effective support, so small-n footprints are not over-interpreted. It does not change the displayed score or rank.${ks.n_clusters && ks.n_clusters > 1 ? `\n\nBased on dominant cluster (${ks.substrate_count}/${ks.total_substrates ?? ks.substrate_count} substrates)\n${ks.n_clusters} trajectory clusters detected` : ""}`}
                      >
                        {(ks.coherence ?? 0).toFixed(2)}
                      </span>
                    </td>
                    {/* Heatmap cells - split up/down with independent normalization */}
                    {heatmapData.conditions.map((c) => {
                      const { upVal, dnVal, upN, dnN } = getEffectiveValues(ks, c);
                      const coactN = ks.coact_counts?.[c] || 0;
                      const exclSum = ks.exclusive_sums?.[c] || 0;
                      const sharedSum = ks.shared_sums?.[c] || 0;
                      const exclN = ks.exclusive_counts?.[c] || 0;
                      const sharedN = ks.shared_counts?.[c] || 0;
                      // Tier info for tooltip
                      const tierLabel = signalTierFilter === "all" ? "All tiers" : signalTierFilter;
                      const domClusterInfo = ks.cluster_details?.find(cd => cd.is_dominant);
                      const clusterScore = domClusterInfo?.scores?.[c];
                      const clusterTier = domClusterInfo?.tier;
                      const tipLines = [
                        `${ks.kinase} @ ${c} [${tierLabel}]`,
                        clusterScore !== undefined ? `Winsorized Mean Score: ${clusterScore.toFixed(3)}` : "",
                        clusterTier ? `Dominant Cluster Tier: ${clusterTier.charAt(0).toUpperCase() + clusterTier.slice(1)}` : "",
                        ``,
                        `▲ Up: ${upN} substrates, sum=+${upVal.toFixed(2)}`,
                        `▼ Down: ${dnN} substrates, sum=${dnVal.toFixed(2)}`,
                        `Total co-activated: ${coactN} / ${ks.substrate_count}${ks.total_substrates && ks.total_substrates !== ks.substrate_count ? ` (dominant cluster of ${ks.total_substrates} total)` : ""}`,
                        ``,
                        `Exclusive: ${exclN} (sum=${exclSum.toFixed(2)})`,
                        `Shared: ${sharedN} (sum=${sharedSum.toFixed(2)})`,
                      ].filter(Boolean);
                      // Height = √(count) sqrt scale (prevents domination by high-substrate kinases)
                      // Color intensity = avg |FC| per substrate (signal quality)
                      // Number = Sum (total signal)
                      const upBarH = upN > 0 ? Math.min(1, Math.sqrt(upN) / maxSqrtUp) : 0;
                      // Suppress blue bar if down signal is negligible vs up signal (< 5% ratio)
                      // This prevents TMM fractional contribution artefacts from appearing as
                      // inactivation when all substrates are actually up-regulated.
                      const dnSignificant = Math.abs(dnVal) > 0 && (
                        upVal <= 0 ||
                        // Compound condition: BOTH absolute threshold AND ratio must be met
                        // - absolute: |down_sums| >= 20 (filters tiny TMM fractional artefacts)
                        // - ratio: |down_sums| / up_sums >= 10% (filters proportionally small noise)
                        // When both are true, it's a genuine mixed-direction signal worth showing
                        (Math.abs(dnVal) >= 20 && Math.abs(dnVal) / Math.max(upVal, 0.001) >= 0.10)
                      );
                      const dnBarH = dnN > 0 && dnSignificant ? Math.min(1, Math.sqrt(Math.abs(dnN)) / maxSqrtDown) : 0;
                      const upAvg = upN > 0 ? upVal / upN : 0;
                      const dnAvg = dnN > 0 ? Math.abs(dnVal) / dnN : 0;
                      // Color: red/blue with intensity based on avg FC (normalized to max avg)
                      const upIntensity = Math.min(1, upAvg / maxAvgUp);
                      const dnIntensity = Math.min(1, dnAvg / maxAvgDown);
                      // Up: dark red (low avg) → bright red (high avg)
                      const upColor = `rgb(${Math.round(80 + 175 * upIntensity)}, ${Math.round(20 + 20 * (1 - upIntensity))}, ${Math.round(20 + 20 * (1 - upIntensity))})`;
                      // Down: dark blue (low avg) → bright blue (high avg)
                      const dnColor = `rgb(${Math.round(20 + 20 * (1 - dnIntensity))}, ${Math.round(40 + 60 * dnIntensity)}, ${Math.round(80 + 175 * dnIntensity)})`;
                      return (
                        <td
                          key={c}
                          className="px-0 py-0 text-center cursor-pointer hover:ring-1 hover:ring-cyan-500/50"
                          title={tipLines.join("\n") + "\n\n🔬 Click to view GO Cellular Component distribution"}
                          onClick={(e) => {
                            e.stopPropagation();
                            setGoLocSelection({ kinase: ks.parent_kinase || ks.kinase, condition: c });
                          }}
                        >
                          <div className="mx-auto w-full h-10 flex flex-col">
                            {/* Up bar (top half): height=√count, color intensity=avg FC */}
                            <div className="flex-1 flex items-end justify-center relative overflow-hidden">
                              {upN > 0 && (
                                <div
                                  className="absolute bottom-0 w-full"
                                  style={{
                                    height: `${upBarH * 100}%`,
                                    backgroundColor: upColor,
                                  }}
                                />
                              )}
                              {upN > 0 && upBarH >= 0.08 && (
                                <span className="relative z-10 text-[8px] text-white/90 leading-none">
                                  +{upVal.toFixed(1)}
                                </span>
                              )}
                            </div>
                            {/* Divider line */}
                            <div className="h-px bg-gray-500/70 w-full flex-shrink-0" />
                            {/* Down bar (bottom half): height=√count, color intensity=avg FC */}
                            <div className="flex-1 flex items-start justify-center relative overflow-hidden">
                              {dnN > 0 && dnSignificant && (
                                <div
                                  className="absolute top-0 w-full"
                                  style={{
                                    height: `${dnBarH * 100}%`,
                                    backgroundColor: dnColor,
                                  }}
                                />
                              )}
                              {dnN > 0 && dnSignificant && dnBarH >= 0.08 && (
                                <span className="relative z-10 text-[8px] text-white/90 leading-none">
                                  {dnVal.toFixed(1)}
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                  {/* v11.3: Expandable substrate list row */}
                  {expandedSubstrates.has(ks.kinase) && ks.substrates && ks.substrates.length > 0 && (
                    <tr key={`${ks.kinase}_substrates`} className="bg-muted/10">
                      <td colSpan={2 + (heatmapData?.conditions?.length || 0) + 4} className="px-4 py-2">
                        <div className="flex flex-wrap gap-1.5 max-h-[120px] overflow-y-auto">
                          {ks.substrates.map((sub: any) => {
                            const isNonDomNuclear = sub.cluster === "non_dominant_nuclear";
                            const locs = goLocCache[sub.gene.toUpperCase()] || goLocData?.gene_localizations?.[sub.gene.toUpperCase()] || [];
                            const locColor: Record<string, string> = {
                              nucleus: "bg-purple-500/20 text-purple-300 border-purple-500/40",
                              cytoplasm: "bg-green-500/20 text-green-300 border-green-500/40",
                              membrane: "bg-blue-500/20 text-blue-300 border-blue-500/40",
                              mitochondrion: "bg-orange-500/20 text-orange-300 border-orange-500/40",
                              "endoplasmic reticulum": "bg-yellow-500/20 text-yellow-300 border-yellow-500/40",
                              "golgi apparatus": "bg-pink-500/20 text-pink-300 border-pink-500/40",
                              cytoskeleton: "bg-teal-500/20 text-teal-300 border-teal-500/40",
                              extracellular: "bg-red-500/20 text-red-300 border-red-500/40",
                              centrosome: "bg-indigo-500/20 text-indigo-300 border-indigo-500/40",
                              ribosome: "bg-amber-500/20 text-amber-300 border-amber-500/40",
                              lysosome: "bg-rose-500/20 text-rose-300 border-rose-500/40",
                              peroxisome: "bg-lime-500/20 text-lime-300 border-lime-500/40",
                            };
                            return (
                              <span
                                key={sub.ptm_key}
                                className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] ${isNonDomNuclear ? "border-purple-500/60 bg-purple-500/10 ring-1 ring-purple-500/30" : "border-border/50 bg-background/50"}`}
                                title={(() => {
                                  let tip = `${sub.gene} ${sub.site}`;
                                  // v11.3.5b: Show current selected condition value + peak info
                                  // Derive peak condition for tooltip
                                  const tipPeakCond = sub.peak_condition
                                    || (sub.temporal && heatmapData?.conditions
                                        ? heatmapData.conditions.reduce((best: string, c: string) => Math.abs(sub.temporal[c] || 0) > Math.abs(sub.temporal[best] || 0) ? c : best, heatmapData.conditions[0])
                                        : null)
                                    || ks.peak_condition
                                    || "?";
                                  if (sortByCondition && sortMode === "condition_sort" && sub.temporal) {
                                    const currentVal = sub.temporal[sortByCondition] || 0;
                                    tip += `\n현재 값: ${currentVal > 0 ? "+" : ""}${currentVal.toFixed(2)} (${sortByCondition})`;
                                    tip += ` | 최고 활성: ${sub.peak_fc > 0 ? "+" : ""}${sub.peak_fc.toFixed(2)} (${tipPeakCond})`;
                                  } else {
                                    tip += `\nPeak |Log2FC|: ${sub.peak_fc > 0 ? "+" : ""}${sub.peak_fc.toFixed(2)} @ ${tipPeakCond}`;
                                  }
                                  if (sub.temporal && heatmapData?.conditions) {
                                    tip += `\nTemporal: ${heatmapData.conditions.map((c: string) => `${c}: ${(sub.temporal[c] || 0) > 0 ? "+" : ""}${(sub.temporal[c] || 0).toFixed(1)}`).join(" | ")}`;
                                  }
                                  if (isNonDomNuclear) {
                                    tip += `\n\n🧬 Nuclear marker (Tier ${sub.nuclear_tier || "?"}) — non-dominant cluster`;
                                  }
                                  tip += `\nGO CC: ${locs.length ? locs.join(", ") : goLocLoading ? "(loading...)" : "(no GO CC annotation)"}`;
                                  return tip;
                                })()}
                              >
                                {isNonDomNuclear && <span className="text-[8px]">🧬</span>}
                                <span className={`font-medium ${isNonDomNuclear ? "text-purple-300" : "text-foreground/90"}`}>{sub.gene}</span>
                                <span className="text-muted-foreground/60">{sub.site}</span>
                                {(() => {
                                  // v11.3.5b: Show FC for selected time column, or peak_fc if none selected
                                  const displayFc = (sortByCondition && sortMode === "condition_sort" && sub.temporal)
                                    ? (sub.temporal[sortByCondition] || 0)
                                    : sub.peak_fc;
                                  // Derive peak condition: prefer sub.peak_condition, then compute from temporal, then use parent ks.peak_condition
                                  const derivedPeakCond = sub.peak_condition
                                    || (sub.temporal && heatmapData?.conditions
                                        ? heatmapData.conditions.reduce((best: string, c: string) => Math.abs(sub.temporal[c] || 0) > Math.abs(sub.temporal[best] || 0) ? c : best, heatmapData.conditions[0])
                                        : null)
                                    || ks.peak_condition
                                    || "";
                                  const displayLabel = (sortByCondition && sortMode === "condition_sort" && sub.temporal)
                                    ? sortByCondition
                                    : derivedPeakCond;
                                  return (
                                    <span className={`text-[8px] ${displayFc > 0 ? "text-red-400" : displayFc < 0 ? "text-blue-400" : "text-gray-400"}`}>
                                      {displayFc > 0 ? "+" : ""}{displayFc.toFixed(1)}
                                      <span className="text-muted-foreground/50 ml-0.5">@{displayLabel}</span>
                                    </span>
                                  );
                                })()}
                                {/* v11.3.4b: Show temporal mini-bars for nuclear markers */}
                                {isNonDomNuclear && sub.temporal && heatmapData?.conditions && (
                                  <span className="inline-flex items-center gap-px ml-0.5">
                                    {heatmapData.conditions.map((cond: string) => {
                                      const fc = sub.temporal[cond] || 0;
                                      const maxAbs = Math.max(...Object.values(sub.temporal as Record<string, number>).map(Math.abs), 0.1);
                                      const intensity = Math.min(Math.abs(fc) / maxAbs, 1);
                                      const bg = fc > 0
                                        ? `rgba(239, 68, 68, ${0.2 + intensity * 0.6})`
                                        : fc < 0
                                        ? `rgba(59, 130, 246, ${0.2 + intensity * 0.6})`
                                        : "rgba(100, 100, 100, 0.2)";
                                      return (
                                        <span
                                          key={cond}
                                          className="inline-block w-[6px] h-[10px] rounded-sm"
                                          style={{ backgroundColor: bg }}
                                          title={`${cond}: ${fc > 0 ? "+" : ""}${fc.toFixed(2)}`}
                                        />
                                      );
                                    })}
                                  </span>
                                )}
                                {locs.slice(0, 2).map((loc) => {
                                  const abbrev: Record<string, string> = {
                                    nucleus: "nuc", cytoplasm: "cyt", membrane: "mem",
                                    mitochondrion: "mit", "endoplasmic reticulum": "ER",
                                    "golgi apparatus": "gol", cytoskeleton: "csk",
                                    extracellular: "ext", centrosome: "cen",
                                    ribosome: "rib", lysosome: "lys", peroxisome: "per",
                                  };
                                  return (
                                    <span
                                      key={loc}
                                      className={`text-[7px] px-0.5 rounded border ${locColor[loc] || "bg-slate-500/20 text-slate-300 border-slate-500/40"}`}
                                      title={loc}
                                    >
                                      {abbrev[loc] || loc.slice(0, 3)}
                                    </span>
                                  );
                                })}
                              </span>
                            );
                          })}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
              })}
            </tbody>
          </table>
          {/* Color legend */}
          <div className="flex items-center justify-between gap-2 py-2 px-3 text-[10px] text-muted-foreground">
            <div className="flex items-center gap-2">
              <span className="flex flex-col items-center gap-0.5">
                <span className="px-2 py-0.5 rounded text-white" style={{ backgroundColor: "rgb(255, 40, 40)" }}>
                  ▲ Up (bright=strong)
                </span>
                <span className="px-2 py-0.5 rounded text-white" style={{ backgroundColor: "rgb(40, 100, 255)" }}>
                  ▼ Down (bright=strong)
                </span>
              </span>
              <span className="ml-2 flex flex-col">
                <span>Bar height = √(count) how many co-activated | Color intensity = avg |FC| per substrate</span>
                <span className="text-[9px] text-muted-foreground/60">
                  Number = ΣFC (total signal sum) | Bright = strong avg signal, Dark = weak avg signal
                </span>
              </span>
              {/* v11.3: Magnitude Tier legend */}
              <span className="ml-3 flex items-center gap-1.5">
                <span className="text-muted-foreground/70 font-medium">Tier:</span>
                <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[8px] font-bold rounded border bg-red-500/20 text-red-300 border-red-500/40" title="Tier 1 (Strong): max |Log2FC| > 5.0">S</span>
                <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[8px] font-bold rounded border bg-amber-500/20 text-amber-300 border-amber-500/40" title="Tier 2 (Moderate): 2.0 < max |Log2FC| ≤ 5.0">M</span>
                <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[8px] font-bold rounded border bg-slate-500/20 text-slate-300 border-slate-500/40" title="Tier 3 (Weak): max |Log2FC| ≤ 2.0">W</span>
              </span>
            </div>
             {/* Co-wave group legend */}
            {heatmapData.cowave_groups && heatmapData.cowave_groups.length > 0 && (
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-1 flex-wrap">
                  <span className="text-muted-foreground/70 font-medium">CW Groups</span>
                  <span className="text-muted-foreground/50 text-[9px]">({isUbi ? "E3 ligases" : "kinases"} with correlated activity, r≥0.7 — <span className="text-cyan-400">click group to filter Vector Plot</span>):</span>
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                  {heatmapData.cowave_groups.map((grp) => {
                    const color = COWAVE_GROUP_COLORS[grp.group_id % COWAVE_GROUP_COLORS.length];

                    const isActive = selectedCwGroupFilter === grp.group_id;
                    return (
                      <span
                        key={grp.group_id}
                        className={`flex items-center gap-1 cursor-pointer rounded px-1 py-0.5 transition-colors ${isActive ? "ring-2 ring-cyan-400 bg-cyan-900/30" : "hover:bg-muted/40"}`}
                        onClick={() => {
                          if (isActive) {
                            setSelectedCwGroupFilter(null);
                            // Clear filter
                            if (onSelectPtms) onSelectPtms([]);
                          } else {
                            setSelectedCwGroupFilter(grp.group_id);
                            // Collect all substrate PTMs for kinases in this CW group
                            const groupKinases = new Set(grp.kinases.map((k: string) => k.toUpperCase()));
                            const substratePtmKeys: string[] = [];
                            for (const mod of globalKinaseResult.kinase_modules) {
                              if (groupKinases.has(mod.kinase.toUpperCase()) || groupKinases.has((mod.canonical || "").toUpperCase())) {
                                for (const member of mod.members) {
                                  substratePtmKeys.push(`${member.gene}_${member.position}`);
                                }
                              }
                            }
                            if (onSelectPtms) onSelectPtms([...new Set(substratePtmKeys)]);
                          }
                        }}
                        title={[
                          `${TEMPORAL_TERMS.localGroup} G${grp.group_id}`,
                          `Members: ${grp.kinases.join(", ")}`,
                          `Mean correlation: r=${grp.mean_correlation.toFixed(2)}`,
                          grp.dominant_peak ? `Dominant peak: ${grp.dominant_peak}` : "",
                          "",
                          "Kinases whose substrates show correlated",
                          "temporal activation patterns (r≥0.7).",
                          "Click to filter Vector Plot by this group's substrates.",
                        ].filter(Boolean).join("\n")}
                      >
                        <span className={`w-2.5 h-2.5 rounded-sm ${color.bar}`} />
                        <span className={`${color.text} font-medium`}>G{grp.group_id}</span>
                        {grp.dominant_peak && (
                          <span className="text-muted-foreground/70 text-[9px]">@{grp.dominant_peak.replace(/min$/i, "m").replace(/hr$/i, "h")}</span>
                        )}

                        <span className="opacity-40 text-[9px]">({grp.size})</span>
                      </span>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
          {/* Peak Sync legend */}
          {heatmapData.peak_sync && Object.keys(heatmapData.peak_sync).length > 0 && (
            <div className="flex items-center gap-2 px-3 pb-2 text-[10px] text-muted-foreground">
              <span className="text-amber-400">⚡</span>
              <span>Peak Sync: conditions where 3+ kinases reach peak activity simultaneously</span>
            </div>
          )}
          {/* Translocation candidates legend */}
          {heatmapData.translocation_candidates && heatmapData.translocation_candidates.length > 0 && (
            <div className="flex items-center gap-2 px-3 pb-2 text-[10px] text-muted-foreground border-t border-border/30 pt-2 mt-1">
              <span>🔄</span>
              <span className="font-medium text-foreground/80">Translocation Detected:</span>
              {heatmapData.translocation_candidates.map((tc) => (
                <span key={tc.kinase} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-purple-500/10 border border-purple-500/30 text-purple-300">
                  <span className="font-medium">{tc.kinase}</span>
                  <span className="text-[8px] text-muted-foreground">({tc.early_peak}→{tc.late_peak})</span>
                </span>
              ))}
              <span className="text-muted-foreground/60 ml-1">Early cytoplasm → Late nucleus</span>
            </div>
          )}
          {/* Direction legend */}
          <div className="flex items-center gap-4 px-3 pb-2 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="text-red-400 font-bold">▲</span>
              <span>Activation: kinase substrates up-phosphorylated (kinase active)</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="text-blue-400 font-bold">▼</span>
              <span>Inactivation: substrates de-phosphorylated (phosphatase action / kinase suppressed)</span>
            </span>
            <span className="ml-auto text-cyan-400">→ Click cell to view GO localization | Click row for Signal Flow</span>
          </div>

          {/* v11.3: GO Cellular Component Localization Dashboard */}
          {goLocSelection && (
            <div className="border-t border-border mt-2 pt-3 px-3 pb-3">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">🔬 GO Cellular Component Distribution</span>
                  <Badge variant="outline" className="text-[10px] h-5">{goLocSelection.kinase} @ {goLocSelection.condition}</Badge>
                </div>
                <Button size="sm" variant="ghost" className="text-xs h-6" onClick={() => setGoLocSelection(null)}>
                  ✕ Close
                </Button>
              </div>
              {goLocLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Fetching GO annotations from UniProt...
                </div>
              ) : goLocData && goLocData.summary && Object.keys(goLocData.summary).length > 0 ? (
                <div className="flex flex-col gap-2">
                  {/* Bar chart - simple CSS bars */}
                  <div className="grid gap-1">
                    {Object.entries(goLocData.summary).slice(0, 10).map(([term, count]) => {
                      const maxCount = Math.max(...Object.values(goLocData.summary));
                      const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
                      const totalGenes = Object.keys(goLocData.gene_localizations).length;
                      // Color coding by compartment
                      const colorMap: Record<string, string> = {
                        nucleus: "bg-purple-500",
                        cytoplasm: "bg-green-500",
                        membrane: "bg-blue-500",
                        mitochondrion: "bg-orange-500",
                        "endoplasmic reticulum": "bg-yellow-500",
                        "golgi apparatus": "bg-pink-500",
                        cytoskeleton: "bg-teal-500",
                        extracellular: "bg-red-500",
                        centrosome: "bg-indigo-500",
                        ribosome: "bg-amber-500",
                        lysosome: "bg-rose-500",
                        peroxisome: "bg-lime-500",
                      };
                      const barColor = colorMap[term] || "bg-slate-500";
                      return (
                        <div key={term} className="flex items-center gap-2 text-xs">
                          <span className="w-28 text-right text-muted-foreground truncate" title={term}>
                            {term.charAt(0).toUpperCase() + term.slice(1)}
                          </span>
                          <div className="flex-1 h-4 bg-muted/30 rounded overflow-hidden relative">
                            <div
                              className={`h-full ${barColor} rounded opacity-80 transition-all`}
                              style={{ width: `${pct}%` }}
                            />
                            <span className="absolute inset-0 flex items-center px-1 text-[9px] text-white/90 font-medium">
                              {count} / {totalGenes} genes ({((count / totalGenes) * 100).toFixed(0)}%)
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  {/* Gene list per compartment (collapsible) */}
                  <details className="text-[10px] text-muted-foreground mt-1">
                    <summary className="cursor-pointer hover:text-foreground">Show gene details per compartment</summary>
                    <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 pl-2">
                      {Object.entries(goLocData.summary).slice(0, 8).map(([term]) => {
                        const genesInTerm = Object.entries(goLocData.gene_localizations)
                          .filter(([, locs]) => locs.includes(term))
                          .map(([g]) => g);
                        return (
                          <div key={term}>
                            <span className="font-medium text-foreground/80">{term}:</span>{" "}
                            <span>{genesInTerm.slice(0, 8).join(", ")}{genesInTerm.length > 8 ? ` +${genesInTerm.length - 8}` : ""}</span>
                          </div>
                        );
                      })}
                    </div>
                  </details>
                  <div className="text-[9px] text-muted-foreground/60 mt-1">
                    Data source: UniProt GO Cellular Component annotations | {Object.keys(goLocData.gene_localizations).length} genes queried
                  </div>
                </div>
              ) : goLocData ? (
                <div className="text-sm text-muted-foreground py-2">No GO Cellular Component annotations found for substrates of {goLocSelection.kinase}.</div>
              ) : null}
            </div>
          )}
        </div>
      )}

      {/* Line Chart View -- All kinases with pattern-based filtering */}
      {viewMode === "line" && (() => {
        // Determine which kinases match the current pattern filter
        const patternMatched = patternFilter
          ? sortedScores.filter((s) => (s.temporal_pattern || []).some((p) => p === patternFilter || p.includes(patternFilter)))
          : [];
        // Highlighted kinases: selected > pattern-filtered > none (show all gray)
        const highlighted = selectedKinases.size > 0
          ? sortedScores.filter((s) => selectedKinases.has(s.kinase))
          : patternFilter
            ? patternMatched
            : [];
        // All available patterns from backend
        const availablePatterns = heatmapData.available_patterns || [];
        // Pattern display labels
        const PATTERN_LABELS: Record<string, { label: string; icon: string; color: string }> = {
          sustained_activation: { label: "Sustained Up", icon: "//", color: "text-red-400" },
          sustained_inactivation: { label: "Sustained Down", icon: "\\\\", color: "text-blue-400" },
          late_onset: { label: "Late Onset", icon: "_/", color: "text-amber-400" },
          early_only: { label: "Early Only", icon: "\\_", color: "text-yellow-400" },
          progressive_amplification: { label: "Amplifying", icon: "/^", color: "text-emerald-400" },
          progressive_decay: { label: "Decaying", icon: "\\v", color: "text-orange-400" },
          mixed: { label: "Mixed", icon: "~", color: "text-gray-400" },
          inactive: { label: "Inactive", icon: "-", color: "text-gray-500" },
        };
        // For dynamic patterns (emergence_at_X, spike_at_X, etc.), generate label
        const getPatternLabel = (p: string) => {
          if (PATTERN_LABELS[p]) return PATTERN_LABELS[p];
          if (p.startsWith("emergence_at_")) return { label: `Emerge @${p.replace("emergence_at_", "")}`, icon: "+", color: "text-green-400" };
          if (p.startsWith("disappearance_at_")) return { label: `Disappear @${p.replace("disappearance_at_", "")}`, icon: "x", color: "text-red-300" };
          if (p.startsWith("spike_at_")) return { label: `Spike @${p.replace("spike_at_", "")}`, icon: "!", color: "text-yellow-300" };
          if (p.startsWith("reversal_at_")) return { label: `Reversal @${p.replace("reversal_at_", "")}`, icon: "<>", color: "text-purple-400" };
          return { label: p, icon: "*", color: "text-gray-400" };
        };
        // Group patterns by category for cleaner UI
        const staticPatterns = availablePatterns.filter((p) => !p.includes("_at_"));
        const dynamicPatterns = availablePatterns.filter((p) => p.includes("_at_"));

        return (
          <div className="border border-border rounded-lg p-4 space-y-3">
            {/* Pattern filter buttons */}
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <Activity className="w-3.5 h-3.5" />
                <span className="font-medium">Temporal Pattern Filter</span>
                <span className="text-muted-foreground/50">-- click to highlight kinases with that pattern</span>
                {patternFilter && (
                  <button
                    className="ml-auto px-2 py-0.5 rounded bg-muted hover:bg-muted/80 text-[9px]"
                    onClick={() => setPatternFilter(null)}
                  >
                    Clear filter
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {staticPatterns.map((p) => {
                  const info = getPatternLabel(p);
                  const count = sortedScores.filter((s) => (s.temporal_pattern || []).includes(p)).length;
                  const isActive = patternFilter === p;
                  return (
                    <button
                      key={p}
                      className={`px-2 py-0.5 rounded text-[9px] border transition-colors ${
                        isActive
                          ? "border-cyan-500 bg-cyan-900/40 text-cyan-300"
                          : "border-border hover:border-muted-foreground/50 text-muted-foreground hover:text-foreground"
                      }`}
                      onClick={() => setPatternFilter(isActive ? null : p)}
                    >
                      <span className={info.color}>{info.icon}</span> {info.label} <span className="opacity-50">({count})</span>
                    </button>
                  );
                })}
                {dynamicPatterns.length > 0 && <span className="text-muted-foreground/30">|</span>}
                {dynamicPatterns.map((p) => {
                  const info = getPatternLabel(p);
                  const count = sortedScores.filter((s) => (s.temporal_pattern || []).some((tp) => tp === p)).length;
                  const isActive = patternFilter === p;
                  return (
                    <button
                      key={p}
                      className={`px-2 py-0.5 rounded text-[9px] border transition-colors ${
                        isActive
                          ? "border-cyan-500 bg-cyan-900/40 text-cyan-300"
                          : "border-border hover:border-muted-foreground/50 text-muted-foreground hover:text-foreground"
                      }`}
                      onClick={() => setPatternFilter(isActive ? null : p)}
                    >
                      <span className={info.color}>{info.icon}</span> {info.label} <span className="opacity-50">({count})</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Chart */}
            <div
              className="relative"
              style={{ height: "420px" }}
              onMouseLeave={() => { setHoveredLineKinase(null); setLineTooltip(null); }}
            >
              {/* Y-axis labels */}
              <div className="absolute left-0 top-0 bottom-8 w-12 flex flex-col justify-between text-[9px] text-muted-foreground">
                <span>{maxAbsScore.toFixed(1)}</span>
                <span>0</span>
                <span>-{maxAbsScore.toFixed(1)}</span>
              </div>
              {/* Chart area */}
              {(() => {
                const svgW = heatmapData.conditions.length * 60;
                const svgH = 400;
                // Clamp Y to [10, 390] to prevent overflow
                const clampY = (rawY: number) => Math.max(10, Math.min(390, rawY));
                const getY = (score: number) => clampY(200 - (score / maxAbsScore) * 180);
                return (
                  <svg
                    className="absolute left-12 top-0 right-0 bottom-8"
                    viewBox={`0 0 ${svgW} ${svgH}`}
                    preserveAspectRatio="none"
                    style={{ width: "calc(100% - 48px)", height: "calc(100% - 32px)", overflow: "hidden" }}
                    onMouseMove={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const mouseX = e.clientX - rect.left;
                      const mouseY = e.clientY - rect.top;
                      // Find closest condition (x-axis)
                      const condIdx = Math.round((mouseX / rect.width * svgW - 30) / 60);
                      const ci = Math.max(0, Math.min(heatmapData.conditions.length - 1, condIdx));
                      const cond = heatmapData.conditions[ci];
                      // Find closest kinase line at this condition
                      const candidates = highlighted.length > 0 ? highlighted : sortedScores;
                      let closest: typeof candidates[0] | null = null;
                      let closestDist = Infinity;
                      const mouseYSvg = mouseY / rect.height * svgH;
                      for (const ks of candidates) {
                        const score = ks.scores[cond] || 0;
                        const lineY = getY(score);
                        const dist = Math.abs(lineY - mouseYSvg);
                        if (dist < closestDist) {
                          closestDist = dist;
                          closest = ks;
                        }
                      }
                      if (closest && closestDist < 40) {
                        setHoveredLineKinase(closest.kinase);
                        setLineTooltip({
                          x: e.clientX - rect.left,
                          y: e.clientY - rect.top,
                          kinase: closest.kinase,
                          condition: cond,
                          score: closest.scores[cond] || 0,
                        });
                      } else {
                        setHoveredLineKinase(null);
                        setLineTooltip(null);
                      }
                    }}
                  >
                    <defs>
                      <clipPath id="lineChartClip">
                        <rect x="0" y="0" width={svgW} height={svgH} />
                      </clipPath>
                    </defs>
                    <g clipPath="url(#lineChartClip)">
                      {/* Grid lines */}
                      <line x1="0" y1="200" x2={svgW} y2="200" stroke="#444" strokeWidth="0.5" strokeDasharray="4" />
                      <line x1="0" y1="100" x2={svgW} y2="100" stroke="#222" strokeWidth="0.5" strokeDasharray="2" />
                      <line x1="0" y1="300" x2={svgW} y2="300" stroke="#222" strokeWidth="0.5" strokeDasharray="2" />
                      {/* Background: ALL kinases as faint gray lines */}
                      {sortedScores.map((ks) => {
                        const isHighlighted = highlighted.length > 0 && highlighted.some((h) => h.kinase === ks.kinase);
                        if (isHighlighted) return null;
                        const points = heatmapData.conditions.map((c, i) => {
                          const x = i * 60 + 30;
                          const y = getY(ks.scores[c] || 0);
                          return `${x},${y}`;
                        }).join(" ");
                        const isHovered = hoveredLineKinase === ks.kinase;
                        return (
                          <polyline
                            key={ks.kinase}
                            points={points}
                            fill="none"
                            stroke={isHovered ? "#fff" : "#555"}
                            strokeWidth={isHovered ? 2.5 : 1}
                            opacity={isHovered ? 0.9 : (hoveredLineKinase ? 0.1 : 0.25)}
                          />
                        );
                      })}
                      {/* Highlighted kinases on top */}
                      {highlighted.map((ks, idx) => {
                        const points = heatmapData.conditions.map((c, i) => {
                          const x = i * 60 + 30;
                          const y = getY(ks.scores[c] || 0);
                          return `${x},${y}`;
                        }).join(" ");
                        const color = LINE_COLORS[idx % LINE_COLORS.length];
                        const isHovered = hoveredLineKinase === ks.kinase;
                        const dimmed = hoveredLineKinase && !isHovered;
                        return (
                          <g key={ks.kinase}>
                            <polyline
                              points={points}
                              fill="none"
                              stroke={color}
                              strokeWidth={isHovered ? 4 : 2.5}
                              opacity={dimmed ? 0.2 : 0.9}
                            />
                            {heatmapData.conditions.map((c, i) => {
                              const x = i * 60 + 30;
                              const y = getY(ks.scores[c] || 0);
                              return <circle key={c} cx={x} cy={y} r={isHovered ? 5 : 3.5} fill={color} opacity={dimmed ? 0.2 : 1} />;
                            })}
                          </g>
                        );
                      })}
                    </g>
                  </svg>
                );
              })()}
              {/* Hover tooltip */}
              {lineTooltip && (
                <div
                  className="absolute pointer-events-none z-50 bg-popover border border-border rounded px-2 py-1 shadow-lg text-[10px]"
                  style={{
                    left: `${Math.min(lineTooltip.x + 12, 300)}px`,
                    top: `${lineTooltip.y - 30}px`,
                    transform: lineTooltip.x > 250 ? "translateX(-110%)" : undefined,
                  }}
                >
                  <div className="font-bold text-foreground">{lineTooltip.kinase}</div>
                  <div className="text-muted-foreground">
                    {lineTooltip.condition}: <span className={lineTooltip.score >= 0 ? "text-red-400" : "text-blue-400"}>{lineTooltip.score >= 0 ? "+" : ""}{lineTooltip.score.toFixed(2)}</span>
                  </div>
                  {(() => {
                    const ks = sortedScores.find((s) => s.kinase === lineTooltip.kinase);
                    if (ks?.temporal_pattern && ks.temporal_pattern.length > 0) {
                      return <div className="text-muted-foreground/70">{ks.temporal_pattern.map((p) => getPatternLabel(p).label).join(", ")}</div>;
                    }
                    return null;
                  })()}
                </div>
              )}
              {/* X-axis labels */}
              <div className="absolute left-12 bottom-0 right-0 flex justify-between text-[9px] text-muted-foreground">
                {heatmapData.conditions.map((c) => (
                  <span key={c} className="text-center flex-1 truncate" title={c}>
                    {c.replace(/min$/i, "'").replace(/hr$/i, "h")}
                  </span>
                ))}
              </div>
            </div>

            {/* Legend for highlighted kinases */}
            {highlighted.length > 0 && (
              <div className="flex flex-wrap gap-2 text-[10px]">
                {highlighted.map((ks, idx) => (
                  <span key={ks.kinase} className="flex items-center gap-1">
                    <span className="w-3 h-0.5 inline-block" style={{ backgroundColor: LINE_COLORS[idx % LINE_COLORS.length] }} />
                    <span>{ks.kinase}</span>
                    {ks.temporal_pattern && ks.temporal_pattern.length > 0 && (
                      <span className="text-muted-foreground/60 text-[8px]">
                        [{ks.temporal_pattern.map((p) => getPatternLabel(p).label).join(", ")}]
                      </span>
                    )}
                  </span>
                ))}
              </div>
            )}
            {highlighted.length === 0 && (
              <p className="text-[10px] text-muted-foreground">
                All {sortedScores.length} kinases shown (gray). Select a pattern filter above or click kinase rows in heatmap to highlight.
              </p>
            )}
            {/* Pattern summary */}
            {patternFilter && patternMatched.length > 0 && (
              <div className="text-[10px] text-muted-foreground bg-muted/20 rounded p-2">
                <span className="font-medium text-cyan-400">{getPatternLabel(patternFilter).label}</span>
                {" "} -- {patternMatched.length} kinase{patternMatched.length > 1 ? "s" : ""}:
                {" "}{patternMatched.slice(0, 15).map((s) => s.kinase).join(", ")}
                {patternMatched.length > 15 && ` ... +${patternMatched.length - 15} more`}
              </div>
            )}
          </div>
        );
      })()}

      {/* Self-PTM Temporal View */}
      {viewMode === "selfPtm" && (() => {
        // Collect all kinases that have self_ptm data
        const selfPtmKinases = sortedScores.filter(
          (ks) => ks.self_ptm && ks.self_ptm.length > 0 && !ks.is_sub_pattern
        );

        if (selfPtmKinases.length === 0) {
          return (
            <div className="text-center text-muted-foreground py-8">
              <p className="text-sm">No self-PTM data detected for any kinase in this dataset.</p>
              <p className="text-xs mt-1">Self-PTM tracking requires the kinase/E3 ligase gene itself to have PTM entries in the experimental data.</p>
            </div>
          );
        }

        // Color scale for FC values
        const getColor = (fc: number) => {
          if (fc >= 2) return "bg-red-600 text-white";
          if (fc >= 1) return "bg-red-500/80 text-white";
          if (fc >= 0.5) return "bg-red-400/60 text-white";
          if (fc > 0.1) return "bg-red-300/40 text-foreground";
          if (fc <= -2) return "bg-blue-600 text-white";
          if (fc <= -1) return "bg-blue-500/80 text-white";
          if (fc <= -0.5) return "bg-blue-400/60 text-white";
          if (fc < -0.1) return "bg-blue-300/40 text-foreground";
          return "bg-muted/20 text-muted-foreground";
        };

        // Relationship badge
        const getRelBadge = (rel: string) => {
          if (rel === "concordant") return { cls: "text-emerald-400", icon: "\u2713", label: "Concordant" };
          if (rel === "discordant") return { cls: "text-rose-400", icon: "\u2298", label: "Discordant" };
          return { cls: "text-gray-400", icon: "\u2014", label: "Independent" };
        };

        return (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-sm font-medium text-foreground">Regulator Self-PTM Temporal Activity</h4>
                <p className="text-[10px] text-muted-foreground">
                  Shows PTM changes on the kinase/E3 ligase protein itself over time. Concordant sites (r\u22650.7) track with substrate activity = likely activation marks. Discordant (r\u2264-0.7) = likely inhibitory.
                </p>
              </div>
              <span className="text-[10px] text-muted-foreground bg-muted/30 px-2 py-1 rounded">
                {selfPtmKinases.length} regulators with self-PTM detected
              </span>
            </div>

            {/* Table header */}
            <div className="overflow-x-auto">
              <table className="w-full text-[10px] border-collapse">
                <thead>
                  <tr className="border-b border-border/50">
                    <th className="text-left px-2 py-1 font-medium text-muted-foreground w-24">Kinase</th>
                    <th className="text-left px-2 py-1 font-medium text-muted-foreground w-20">Site</th>
                    <th className="text-center px-1 py-1 font-medium text-muted-foreground w-14">r</th>
                    <th className="text-center px-1 py-1 font-medium text-muted-foreground w-20">Relationship</th>
                    {heatmapData.conditions.map((c) => (
                      <th key={c} className="text-center px-1 py-1 font-medium text-muted-foreground min-w-[50px]" title={c}>
                        {c.replace(/min$/i, "'").replace(/hr$/i, "h")}
                      </th>
                    ))}
                    <th className="text-center px-1 py-1 font-medium text-muted-foreground w-16">Peak</th>
                  </tr>
                </thead>
                <tbody>
                  {selfPtmKinases.map((ks) => {
                    const sites = ks.self_ptm!;
                    return sites.map((sp, spIdx) => (
                      <tr
                        key={`${ks.kinase}_${sp.site}`}
                        className={`border-b border-border/20 hover:bg-muted/20 ${spIdx === 0 ? "border-t border-border/40" : ""}`}
                      >
                        {/* Kinase name - only show on first site */}
                        <td className="px-2 py-1 font-medium text-foreground">
                          {spIdx === 0 ? (
                            <span title={`${ks.kinase} — ${sites.length} self-PTM site(s)`}>
                              {ks.kinase}
                              {sites.length > 1 && <span className="text-muted-foreground/50 ml-0.5">({sites.length})</span>}
                            </span>
                          ) : null}
                        </td>
                        {/* Site */}
                        <td className="px-2 py-1 font-mono text-cyan-300">{sp.site}</td>
                        {/* Correlation */}
                        <td className="text-center px-1 py-1">
                          <span className={sp.correlation_with_activity >= 0.7 ? "text-emerald-400 font-bold" : sp.correlation_with_activity <= -0.7 ? "text-rose-400 font-bold" : "text-muted-foreground"}>
                            {sp.correlation_with_activity > 0 ? "+" : ""}{sp.correlation_with_activity.toFixed(2)}
                          </span>
                        </td>
                        {/* Relationship */}
                        <td className="text-center px-1 py-1">
                          {(() => {
                            const badge = getRelBadge(sp.relationship);
                            return <span className={`${badge.cls} font-medium`}>{badge.icon} {badge.label}</span>;
                          })()}
                        </td>
                        {/* Temporal values */}
                        {heatmapData.conditions.map((c) => {
                          const val = sp.timeseries[c] ?? 0;
                          return (
                            <td key={c} className="text-center px-0.5 py-0.5">
                              <span
                                className={`inline-block w-full px-1 py-0.5 rounded text-[9px] font-mono ${getColor(val)}`}
                                title={`${sp.gene}_${sp.site} @ ${c}: ${val > 0 ? "+" : ""}${val.toFixed(3)} Log2FC`}
                              >
                                {Math.abs(val) < 0.01 ? "0" : (val > 0 ? "+" : "") + val.toFixed(2)}
                              </span>
                            </td>
                          );
                        })}
                        {/* Peak */}
                        <td className="text-center px-1 py-1 text-[9px]">
                          <span className="text-muted-foreground">{sp.peak_condition?.replace(/min$/i, "'").replace(/hr$/i, "h")}</span>
                          <br />
                          <span className={sp.peak_fc >= 0 ? "text-red-400" : "text-blue-400"}>
                            {sp.peak_fc > 0 ? "+" : ""}{sp.peak_fc.toFixed(2)}
                          </span>
                        </td>
                      </tr>
                    ));
                  })}
                </tbody>
              </table>
            </div>

            {/* Substrate-inferred activity comparison row */}
            <div className="mt-2">
              <h5 className="text-[10px] font-medium text-muted-foreground mb-1">Comparison: Substrate-Inferred Activity (for reference)</h5>
              <div className="overflow-x-auto">
                <table className="w-full text-[10px] border-collapse">
                  <thead>
                    <tr className="border-b border-border/30">
                      <th className="text-left px-2 py-1 font-medium text-muted-foreground w-24">Kinase</th>
                      <th className="text-left px-2 py-1 font-medium text-muted-foreground w-20"></th>
                      <th className="text-center px-1 py-1 font-medium text-muted-foreground w-14"></th>
                      <th className="text-center px-1 py-1 font-medium text-muted-foreground w-20">Type</th>
                      {heatmapData.conditions.map((c) => (
                        <th key={c} className="text-center px-1 py-1 font-medium text-muted-foreground min-w-[50px]" title={c}>
                          {c.replace(/min$/i, "'").replace(/hr$/i, "h")}
                        </th>
                      ))}
                      <th className="text-center px-1 py-1 font-medium text-muted-foreground w-16">Peak</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selfPtmKinases.map((ks) => (
                      <tr key={`activity_${ks.kinase}`} className="border-b border-border/20 bg-muted/10">
                        <td className="px-2 py-1 font-medium text-foreground/70">{ks.kinase}</td>
                        <td className="px-2 py-1 text-muted-foreground/50 italic">activity</td>
                        <td className="text-center px-1 py-1"></td>
                        <td className="text-center px-1 py-1 text-amber-400/70 text-[9px]">substrate-inferred</td>
                        {heatmapData.conditions.map((c) => {
                          const val = ks.scores[c] ?? 0;
                          return (
                            <td key={c} className="text-center px-0.5 py-0.5">
                              <span
                                className={`inline-block w-full px-1 py-0.5 rounded text-[9px] font-mono ${getColor(val)}`}
                                title={`${ks.kinase} substrate activity @ ${c}: ${val > 0 ? "+" : ""}${val.toFixed(3)}`}
                              >
                                {Math.abs(val) < 0.01 ? "0" : (val > 0 ? "+" : "") + val.toFixed(2)}
                              </span>
                            </td>
                          );
                        })}
                        <td className="text-center px-1 py-1 text-[9px]">
                          <span className="text-muted-foreground">{ks.peak_condition?.replace(/min$/i, "'").replace(/hr$/i, "h")}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-4 text-[9px] text-muted-foreground pt-2 border-t border-border/30">
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500/80"></span> Up (Log2FC &gt; 0)</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-blue-500/80"></span> Down (Log2FC &lt; 0)</span>
              <span className="flex items-center gap-1"><span className="text-emerald-400 font-bold">\u2713</span> Concordant (r\u22650.7)</span>
              <span className="flex items-center gap-1"><span className="text-rose-400 font-bold">\u2298</span> Discordant (r\u2264-0.7)</span>
              <span className="flex items-center gap-1"><span className="text-gray-400">\u2014</span> Independent</span>
            </div>
          </div>
        );
      })()}

      {/* Summary stats */}
      <div className="grid grid-cols-6 gap-2 text-xs">
        <div className="bg-muted/30 rounded p-2 text-center">
          <div className="text-lg font-bold text-cyan-400">{heatmapData.kinase_scores.length}</div>
          <div className="text-muted-foreground">Kinases</div>
        </div>
        <div className="bg-muted/30 rounded p-2 text-center">
          <div className="text-lg font-bold text-amber-400">{heatmapData.conditions.length}</div>
          <div className="text-muted-foreground">Conditions</div>
        </div>
        <div className="bg-muted/30 rounded p-2 text-center">
          <div className="text-lg font-bold text-red-400">
            {sortedScores.filter((s) => s.direction === "positive_substrate_footprint").length}
          </div>
          <div className="text-muted-foreground">▲ Positive footprint</div>
        </div>
        <div className="bg-muted/30 rounded p-2 text-center">
          <div className="text-lg font-bold text-blue-400">
            {sortedScores.filter((s) => s.direction === "negative_substrate_footprint").length}
          </div>
          <div className="text-muted-foreground">▼ Negative footprint</div>
        </div>
        <div className="bg-muted/30 rounded p-2 text-center">
          <div className="text-lg font-bold text-purple-400">
            {sortedScores.filter((s) => s.footprint_diagnostics?.status === "computed").length}
          </div>
          <div className="text-muted-foreground">Support diagnostics</div>
        </div>
        <div className="bg-muted/30 rounded p-2 text-center cursor-help" title={`${TEMPORAL_TERMS.localGroups}: descriptive groups of ${isUbi ? "E3 ligases" : "kinases"} whose substrate-footprint profiles are highly correlated (Pearson r≥0.7). ${isUbi ? "E3 ligases" : "Kinases"} in the same group show similar observed temporal signed-footprint patterns; the group does not establish shared regulation.`}>
          <div className="text-lg font-bold text-fuchsia-400">
            {heatmapData.cowave_groups?.length ?? 0}
          </div>
          <div className="text-muted-foreground">CW Groups</div>
        </div>
      </div>
    </div>
  );
}


// ── Chain Linkage View (Ubiquitylation only) ─────────────────────────────────

interface LinkageInterpretation {
  linkage_type: string;
  ratio_percent: number;
  trend: string;
  function: string;
  avg_log2fc: number;
}

interface LinkageData {
  detected: boolean;
  message?: string;
  linkage_data?: Array<{
    linkage_type: string;
    position: number;
    gene: string;
    conditions: Record<string, number>;
  }>;
  temporal_ratios?: {
    conditions: string[];
    ratios: Record<string, Record<string, number>>;
  };
  summary?: {
    detected_types: string[];
    dominant_type: string;
    interpretations: LinkageInterpretation[];
  };
  chart_data?: {
    type: string;
    labels: string[];
    datasets: Array<{
      label: string;
      data: number[];
      backgroundColor: string;
    }>;
  };
}

// Chain type color mapping
const CHAIN_COLORS: Record<string, string> = {
  K48: "#ef4444",   // red — degradation
  K63: "#3b82f6",   // blue — signaling
  K11: "#f59e0b",   // amber — cell cycle
  K27: "#8b5cf6",   // purple — immune
  K29: "#10b981",   // emerald — Wnt
  K33: "#06b6d4",   // cyan — kinase regulation
  K6: "#ec4899",    // pink — DNA repair
  M1: "#6366f1",    // indigo — NF-kB
};

const CHAIN_FUNCTIONS: Record<string, string> = {
  K48: "Proteasomal degradation",
  K63: "Non-degradative signaling (NF-κB, DDR, endosomal)",
  K11: "Cell cycle regulation, ERAD",
  K27: "Innate immune signaling (STING/MAVS)",
  K29: "Wnt signaling, lysosomal degradation",
  K33: "Kinase regulation, TCR signaling",
  K6: "DNA repair, mitophagy (BRCA1/Parkin)",
  M1: "Linear NF-κB activation (LUBAC)",
};

function ChainLinkageView({ orderId, conditions }: { orderId: number; conditions: string[] }) {
  const [data, setData] = useState<LinkageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await api.get<LinkageData>(`/orders/${orderId}/ubiquitin-linkage`);
        if (!cancelled) setData(result);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || "Failed to load linkage data");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => { cancelled = true; };
  }, [orderId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        <span className="text-sm text-muted-foreground">Loading chain linkage analysis...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-12 text-destructive">
        <AlertTriangle className="h-4 w-4 mr-2" />
        <span className="text-sm">{error}</span>
      </div>
    );
  }

  if (!data?.detected) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <Link2 className="h-8 w-8 mb-2 opacity-50" />
        <p className="text-sm font-medium">No ubiquitin chain linkage data detected</p>
        <p className="text-xs mt-1">
          {data?.message || "Ubiquitin protein (UBB/UBC/UBA52/RPS27A) GlyGly peptides were not found in the dataset."}
        </p>
        <p className="text-xs mt-2 text-muted-foreground/70 max-w-md text-center">
          Chain linkage analysis requires detection of GlyGly modifications on ubiquitin's own lysine residues
          (K6, K11, K27, K29, K33, K48, K63). These are typically detected in deep ubiquitylome datasets.
        </p>
      </div>
    );
  }

  const { temporal_ratios, summary, linkage_data } = data;
  const conds = temporal_ratios?.conditions || [];
  const ratios = temporal_ratios?.ratios || {};
  const detectedTypes = summary?.detected_types || [];
  const interpretations = summary?.interpretations || [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Link2 className="h-4 w-4 text-blue-500" />
            Ubiquitin Chain Linkage Analysis
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Empirical chain type distribution from MS-detected GlyGly modifications on ubiquitin protein
          </p>
        </div>
        <Badge variant="secondary" className="text-xs">
          {detectedTypes.length} chain type{detectedTypes.length !== 1 ? "s" : ""} detected
        </Badge>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {interpretations.map((interp) => (
          <div
            key={interp.linkage_type}
            className="border rounded-lg p-2.5 bg-card"
            style={{ borderLeftColor: CHAIN_COLORS[interp.linkage_type] || "#6b7280", borderLeftWidth: "3px" }}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold" style={{ color: CHAIN_COLORS[interp.linkage_type] || "#6b7280" }}>
                {interp.linkage_type}
              </span>
              <span className="text-xs font-mono">{interp.ratio_percent.toFixed(1)}%</span>
            </div>
            <p className="text-[10px] text-muted-foreground mt-1 line-clamp-2">
              {CHAIN_FUNCTIONS[interp.linkage_type] || interp.function}
            </p>
            <div className="flex items-center gap-1 mt-1">
              <TrendingUp className="h-2.5 w-2.5 text-muted-foreground" />
              <span className="text-[10px] text-muted-foreground">{interp.trend}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Temporal Stacked Bar Chart */}
      {conds.length > 0 && (
        <div className="border rounded-lg p-3 bg-card">
          <h4 className="text-xs font-semibold mb-3">Temporal Chain Type Distribution</h4>
          <div className="space-y-2">
            {conds.map((cond) => {
              const condRatios = ratios[cond] || {};
              const sortedTypes = Object.entries(condRatios).sort((a, b) => b[1] - a[1]);
              return (
                <div key={cond} className="flex items-center gap-2">
                  <span className="text-[10px] font-mono w-12 text-right text-muted-foreground shrink-0">
                    {cond}
                  </span>
                  <div className="flex-1 flex h-6 rounded overflow-hidden bg-muted/30">
                    {sortedTypes.map(([lt, pct]) => (
                      <div
                        key={lt}
                        className="h-full flex items-center justify-center text-[9px] font-bold text-white transition-all"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: CHAIN_COLORS[lt] || "#6b7280",
                          minWidth: pct > 3 ? undefined : "0px",
                        }}
                        title={`${lt}: ${pct.toFixed(1)}%`}
                      >
                        {pct >= 10 ? `${lt}` : ""}
                      </div>
                    ))}
                  </div>
                  <span className="text-[10px] text-muted-foreground w-10 shrink-0">
                    {sortedTypes[0]?.[0] || ""}
                  </span>
                </div>
              );
            })}
          </div>
          {/* Legend */}
          <div className="flex flex-wrap gap-2 mt-3 pt-2 border-t">
            {detectedTypes.map((lt) => (
              <div key={lt} className="flex items-center gap-1">
                <div
                  className="w-2.5 h-2.5 rounded-sm"
                  style={{ backgroundColor: CHAIN_COLORS[lt] || "#6b7280" }}
                />
                <span className="text-[10px]">{lt}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Detailed linkage data table */}
      {linkage_data && linkage_data.length > 0 && (
        <div className="border rounded-lg p-3 bg-card">
          <h4 className="text-xs font-semibold mb-2">Detected Ubiquitin Linkage Sites</h4>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px]">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-1 px-1.5 font-medium">Chain Type</th>
                  <th className="text-left py-1 px-1.5 font-medium">Position</th>
                  <th className="text-left py-1 px-1.5 font-medium">Gene</th>
                  {conds.map((c) => (
                    <th key={c} className="text-right py-1 px-1.5 font-medium">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {linkage_data.map((row, i) => (
                  <tr key={i} className="border-b border-muted/30 hover:bg-muted/20">
                    <td className="py-1 px-1.5">
                      <span
                        className="font-bold"
                        style={{ color: CHAIN_COLORS[row.linkage_type] || "#6b7280" }}
                      >
                        {row.linkage_type}
                      </span>
                    </td>
                    <td className="py-1 px-1.5 font-mono">K{row.position}</td>
                    <td className="py-1 px-1.5">{row.gene}</td>
                    {conds.map((c) => {
                      const val = row.conditions[c];
                      return (
                        <td key={c} className="text-right py-1 px-1.5 font-mono">
                          {val !== undefined ? (
                            <span className={val > 0 ? "text-red-500" : val < 0 ? "text-blue-500" : ""}>
                              {val > 0 ? "+" : ""}{val.toFixed(2)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[9px] text-muted-foreground mt-2">
            Values represent Log2FC of GlyGly modification on ubiquitin lysine residues.
            Positive = increased chain formation; Negative = decreased chain formation.
          </p>
        </div>
      )}

      {/* Interpretation note */}
      <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg p-3">
        <div className="flex items-start gap-2">
          <Info className="h-3.5 w-3.5 text-blue-500 mt-0.5 shrink-0" />
          <div className="text-[10px] text-blue-800 dark:text-blue-200 space-y-1">
            <p className="font-medium">How to interpret chain linkage data:</p>
            <p>
              • <strong>K48 dominance</strong>: Suggests proteasomal degradation is the primary ubiquitylation outcome
            </p>
            <p>
              • <strong>K63 dominance</strong>: Indicates non-degradative signaling (NF-κB, DNA damage response, endosomal sorting)
            </p>
            <p>
              • <strong>Temporal shift</strong>: A change from K63→K48 over time may indicate transition from signaling to degradation
            </p>
            <p>
              • <strong>Co-detection of K48+K63</strong>: Mixed chain types suggest complex regulation with both degradative and signaling roles
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
