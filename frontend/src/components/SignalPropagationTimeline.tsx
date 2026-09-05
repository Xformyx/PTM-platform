import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Legend, ReferenceLine, Cell, BarChart, Bar, LineChart, Line,
} from "recharts";
import { Activity, ArrowRight, Clock, Zap, Timer, RefreshCw, TrendingUp, TrendingDown, Dna, CheckCircle2, AlertCircle, Upload } from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface EffectorData {
  gene: string;
  role: string;
  pattern: string;
  temporal_data: Record<string, number>;
  max_change: number;
}

interface SelfTimeLag {
  ptm_key: string;
  gene: string;
  site: string;
  ptm_first_tp: string;
  ptm_first_minutes: number;
  ptm_log2fc: number;
  protein_first_tp: string;
  protein_first_minutes: number;
  protein_log2fc: number;
  time_lag_minutes: number;
  direction: string;
  cascade_type: string;
  directionality_tier?: string;
  causality_status?: string;
  directionality?: {
    onset_lag_minutes?: number | null;
    peak_lag_minutes?: number | null;
    evidence_profile?: { time_permutation_p_value?: number | null };
  };
}

interface CascadeTimeLag {
  ptm_substrate: string;
  effector: string;
  ptm_first_tp: string;
  ptm_first_minutes: number;
  ptm_log2fc: number;
  effector_first_tp: string;
  effector_first_minutes: number;
  effector_log2fc: number;
  time_lag_minutes: number;
  direction: string;
  directionality_tier?: string;
  causality_status?: string;
  directionality?: SelfTimeLag['directionality'];
}

interface Summary {
  total_effectors: number;
  responsive_effectors: number;
  pattern_counts: Record<string, number>;
  total_self_timelags: number;
  temporal_precedence_count?: number;
  reverse_temporal_precedence_count?: number;
  causal_count?: number;
  feedback_count?: number;
  simultaneous_count: number;
  total_cascade_timelags: number;
  cascade_temporal_precedence_count?: number;
  forward_propagation_count?: number;
  immediate_count: number;
  rapid_relay_count: number;
  transcriptional_count: number;
}

interface TFInference {
  tf: string;
  n_overlap: number;
  pvalue: number;
  fdr: number;
  fold_enrichment: number;
  dominant_mode: string;
  overlap_genes: string[];
  cross_validated: boolean;
  validation_type: string;
}
interface TFInferenceData {
  species: string;
  n_changed_proteins: number;
  n_early_changed: number;
  n_late_changed: number;
  all_inferred_tfs: TFInference[];
  cross_validated_tfs: TFInference[];
  nonptm_only_tfs: TFInference[];
  temporal_inference: {
    early: TFInference[];
    late: TFInference[];
  };
  sources: string[];
  ptm_modified_proteins_checked: number;
}
interface SignalPropagationData {
  mode: 'ptm_only' | 'crosstalk';
  ptm_type?: string;
  primary_ptm_type?: string;
  secondary_ptm_type?: string;
  timepoints: string[];
  timepoint_minutes: number[];
  nonptm_effectors: EffectorData[];
  self_timelags: SelfTimeLag[];
  cascade_timelags: CascadeTimeLag[];
  summary: Summary;
  tf_inferences?: TFInferenceData;
}

interface Props {
  data: SignalPropagationData;
  orderId?: number;
}

// ─── Color mappings ───────────────────────────────────────────────────────────

const PATTERN_COLORS: Record<string, string> = {
  immediate_early_response: '#ef4444',   // red-500
  delayed_effector_response: '#f59e0b',  // amber-500
  sustained_response: '#3b82f6',         // blue-500
  biphasic_switch: '#8b5cf6',            // violet-500
  stable_baseline: '#9ca3af',            // gray-400
};

const PATTERN_LABELS: Record<string, string> = {
  immediate_early_response: 'Immediate Early',
  delayed_effector_response: 'Delayed Effector',
  sustained_response: 'Sustained',
  biphasic_switch: 'Biphasic Switch',
  stable_baseline: 'Stable',
};

const DIRECTION_COLORS: Record<string, string> = {
  source_precedes_target: '#0f766e',
  target_precedes_source: '#f97316',
  unresolved: '#9ca3af',
  causal: '#22c55e', // legacy persisted orders only
  forward_propagation: '#22c55e', // legacy persisted orders only
  feedback: '#f97316', // legacy persisted orders only
  reverse_signaling: '#f97316', // legacy persisted orders only
  simultaneous: '#3b82f6',     // blue-500
  co_activation: '#3b82f6',
  co_regulated: '#3b82f6',
};

const CASCADE_COLORS: Record<string, string> = {
  immediate: '#ef4444',
  rapid_relay: '#f59e0b',
  transcriptional: '#8b5cf6',
  feedback: '#f97316',
  co_regulated: '#3b82f6',
};

// ─── Component ────────────────────────────────────────────────────────────────

export default function SignalPropagationTimeline({ data, orderId }: Props) {
  const [activeTab, setActiveTab] = useState('overview');
  const [perturbationFile, setPerturbationFile] = useState<File | null>(null);
  const [interventionDescription, setInterventionDescription] = useState('');
  const [uploadingPerturbation, setUploadingPerturbation] = useState(false);
  const [perturbationMessage, setPerturbationMessage] = useState<string | null>(null);

  const uploadPerturbationEvidence = async () => {
    if (!orderId || !perturbationFile) return;
    setUploadingPerturbation(true);
    setPerturbationMessage(null);
    try {
      const formData = new FormData();
      formData.append('file', perturbationFile);
      formData.append('alpha', '0.05');
      formData.append('intervention_description', interventionDescription);
      const response = await fetch(`/api/orders/${orderId}/perturbation-evidence`, {
        method: 'POST',
        body: formData,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || 'Unable to evaluate perturbation evidence');
      const summary = payload.evaluation?.summary ?? {};
      setPerturbationMessage(
        `Evaluated ${summary.uploaded_rows_evaluated ?? 0} relationship(s): ${summary.perturbation_supported ?? 0} perturbation-supported, ${summary.perturbation_not_supported ?? 0} not supported.`
      );
      setPerturbationFile(null);
    } catch (error) {
      setPerturbationMessage(error instanceof Error ? error.message : 'Unable to evaluate perturbation evidence');
    } finally {
      setUploadingPerturbation(false);
    }
  };

  const ptmLabel = data.mode === 'crosstalk'
    ? `${data.primary_ptm_type || 'Phos'} × ${data.secondary_ptm_type || 'Ub'}`
    : (data.ptm_type || 'PTM');

  // ── Prepare scatter data for time lag visualization ──
  const timeLagScatterData = useMemo(() => {
    const selfPoints = data.self_timelags.map((tl, i) => ({
      x: tl.ptm_first_minutes,
      y: tl.time_lag_minutes,
      name: tl.ptm_key,
      type: 'self' as const,
      direction: tl.direction,
      cascade_type: tl.cascade_type,
      ptm_log2fc: tl.ptm_log2fc,
      protein_log2fc: tl.protein_log2fc,
      idx: i,
    }));

    const cascadePoints = data.cascade_timelags.map((tl, i) => ({
      x: tl.ptm_first_minutes,
      y: tl.time_lag_minutes,
      name: `${tl.ptm_substrate}→${tl.effector}`,
      type: 'cascade' as const,
      direction: tl.direction,
      cascade_type: tl.direction === 'source_precedes_target' ? 'temporal_precedence' : tl.direction,
      ptm_log2fc: tl.ptm_log2fc,
      protein_log2fc: tl.effector_log2fc,
      directionality_tier: tl.directionality_tier,
      causality_status: tl.causality_status,
      idx: i + selfPoints.length,
    }));

    return [...selfPoints, ...cascadePoints];
  }, [data]);

  // ── Effector temporal heatmap data ──
  const effectorHeatmapData = useMemo(() => {
    const responsive = data.nonptm_effectors.filter(e => e.pattern !== 'stable_baseline');
    return responsive.slice(0, 20).map(e => ({
      gene: e.gene,
      role: e.role,
      pattern: e.pattern,
      ...Object.fromEntries(
        data.timepoints.map(tp => [tp, e.temporal_data[tp] || 0])
      ),
    }));
  }, [data]);

  // ── Pattern distribution bar data ──
  const patternBarData = useMemo(() => {
    return Object.entries(data.summary?.pattern_counts ?? {})
      .filter(([k]) => k !== 'stable_baseline')
      .map(([pattern, count]) => ({
        pattern: PATTERN_LABELS[pattern] || pattern,
        count,
        fill: PATTERN_COLORS[pattern] || '#9ca3af',
      }))
      .sort((a, b) => b.count - a.count);
  }, [data]);

  // ── Mechanism distribution ──
  const mechanismData = useMemo(() => {
    const immediate_count = data.summary?.immediate_count ?? 0;
    const rapid_relay_count = data.summary?.rapid_relay_count ?? 0;
    const transcriptional_count = data.summary?.transcriptional_count ?? 0;
    return [
      { name: 'Post-translational (≤5min)', value: immediate_count, fill: '#ef4444' },
      { name: 'Rapid relay (5-20min)', value: rapid_relay_count, fill: '#f59e0b' },
      { name: 'Transcriptional (>20min)', value: transcriptional_count, fill: '#8b5cf6' },
    ].filter(d => d.value > 0);
  }, [data]);

  // ── Effector line chart data ──
  const effectorLineData = useMemo(() => {
    const responsive = data.nonptm_effectors.filter(e => e.pattern !== 'stable_baseline');
    const top8 = responsive.slice(0, 8);
    return (data.timepoints ?? []).map((tp, i) => {
      const point: Record<string, any> = { timepoint: tp, minutes: data.timepoint_minutes?.[i] ?? 0 };
      top8.forEach(e => {
        point[e.gene] = e.temporal_data[tp] || 0;
      });
      return point;
    });
  }, [data]);

  const top8Effectors = useMemo(() => {
    return data.nonptm_effectors
      .filter(e => e.pattern !== 'stable_baseline')
      .slice(0, 8);
  }, [data]);

  const LINE_COLORS = ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Activity className="h-5 w-5 text-emerald-600" />
          Signal Propagation Timeline
        </CardTitle>
        <CardDescription>
          {ptmLabel} → Effector Protein 간 시간적 선후관계 분석 ({data.mode === 'crosstalk' ? 'Cross-Talk' : 'PTM-Only'} Mode). 관찰형 time-course만으로 인과성을 주장하지 않습니다.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* Summary Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <div className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-center">
            <p className="text-2xl font-bold text-emerald-700">{data.summary?.responsive_effectors ?? 0}</p>
            <p className="text-xs text-emerald-600">Responsive Effectors</p>
          </div>
          <div className="p-3 rounded-lg bg-green-50 border border-green-200 text-center">
            <p className="text-2xl font-bold text-green-700">{data.summary?.temporal_precedence_count ?? data.summary?.causal_count ?? 0}</p>
            <p className="text-xs text-green-600">PTM Precedes Protein</p>
          </div>
          <div className="p-3 rounded-lg bg-orange-50 border border-orange-200 text-center">
            <p className="text-2xl font-bold text-orange-700">{data.summary?.reverse_temporal_precedence_count ?? data.summary?.feedback_count ?? 0}</p>
            <p className="text-xs text-orange-600">Protein Precedes PTM</p>
          </div>
          <div className="p-3 rounded-lg bg-blue-50 border border-blue-200 text-center">
            <p className="text-2xl font-bold text-blue-700">{data.summary?.cascade_temporal_precedence_count ?? data.summary?.forward_propagation_count ?? 0}</p>
            <p className="text-xs text-blue-600">PPI-linked Precedence</p>
          </div>
        </div>

        {orderId && (
          <div className="mb-6 rounded-lg border border-dashed border-slate-300 bg-slate-50/70 p-4">
            <div className="flex flex-col gap-1 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-sm font-semibold flex items-center gap-2"><Upload className="h-4 w-4 text-slate-600" /> Optional post-analysis perturbation evidence</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Upload only after unbiased discovery is complete. This does not change Temporal Phosphosite Trajectory Clustering or directionality; it evaluates the uploaded condition against existing source-precedes-target candidates.
                </p>
              </div>
              <Badge variant="outline" className="w-fit text-[10px]">Optional validation layer</Badge>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1.5fr_auto] md:items-end">
              <label className="grid gap-1 text-xs font-medium">
                CSV/TSV evidence table
                <input
                  type="file"
                  accept=".csv,.tsv,text/csv,text/tab-separated-values"
                  className="block w-full text-xs"
                  onChange={(event) => setPerturbationFile(event.target.files?.[0] ?? null)}
                />
              </label>
              <label className="grid gap-1 text-xs font-medium">
                Intervention description (optional)
                <input
                  value={interventionDescription}
                  onChange={(event) => setInterventionDescription(event.target.value)}
                  placeholder="e.g., independent follow-up condition"
                  className="h-9 rounded-md border bg-background px-2 text-xs"
                />
              </label>
              <button
                type="button"
                disabled={!perturbationFile || uploadingPerturbation}
                onClick={uploadPerturbationEvidence}
                className="h-9 rounded-md bg-slate-800 px-3 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {uploadingPerturbation ? 'Evaluating…' : 'Upload & evaluate'}
              </button>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Required columns: <code>source</code>, <code>target</code>, <code>control_mean</code>, <code>perturbed_mean</code>, <code>expected_target_change</code> (<code>up</code>/<code>down</code>), <code>q_value</code>.
            </p>
            {perturbationMessage && <p className="mt-2 text-xs text-slate-700">{perturbationMessage}</p>}
          </div>
        )}

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="grid w-full grid-cols-5 mb-4">
            <TabsTrigger value="overview" className="text-xs">
              <Zap className="h-3 w-3 mr-1" />
              Overview
            </TabsTrigger>
            <TabsTrigger value="timelag" className="text-xs">
              <Timer className="h-3 w-3 mr-1" />
              Time Lag
            </TabsTrigger>
            <TabsTrigger value="effectors" className="text-xs">
              <TrendingUp className="h-3 w-3 mr-1" />
              Effectors
            </TabsTrigger>
            <TabsTrigger value="cascade" className="text-xs">
              <ArrowRight className="h-3 w-3 mr-1" />
              Cascade
            </TabsTrigger>
            <TabsTrigger value="tf_activity" className="text-xs" disabled={!data.tf_inferences}>
              <Dna className="h-3 w-3 mr-1" />
              TF Activity
            </TabsTrigger>
          </TabsList>

          {/* ── Overview Tab ── */}
          <TabsContent value="overview">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Effector Response Pattern Distribution */}
              <div className="border rounded-lg p-4">
                <h4 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
                  <RefreshCw className="h-4 w-4 text-blue-500" />
                  Effector Response Patterns
                </h4>
                {patternBarData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={patternBarData} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                      <XAxis type="number" fontSize={11} />
                      <YAxis type="category" dataKey="pattern" fontSize={10} width={120} />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 8 }}
                        formatter={(value: unknown) => [`${Number(value ?? 0)} proteins`, 'Count']}
                      />
                      <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                        {patternBarData.map((entry, i) => (
                          <Cell key={i} fill={entry.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">No responsive effectors detected</p>
                )}
              </div>

              {/* Signal Propagation Mechanism Distribution */}
              <div className="border rounded-lg p-4">
                <h4 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
                  <Clock className="h-4 w-4 text-purple-500" />
                  Temporal Lag Distribution
                </h4>
                {mechanismData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={mechanismData}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                      <XAxis dataKey="name" fontSize={10} />
                      <YAxis fontSize={11} />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 8 }}
                        formatter={(value: unknown) => [`${Number(value ?? 0)} events`, 'Count']}
                      />
                      <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                        {mechanismData.map((entry, i) => (
                          <Cell key={i} fill={entry.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="text-sm text-muted-foreground text-center py-8">No time lag data available</p>
                )}
              </div>
            </div>

            {/* Legend */}
            <div className="mt-4 p-3 bg-muted/30 rounded-lg">
              <p className="text-xs font-medium mb-2">Temporal Lag Interpretation</p>
              <div className="flex flex-wrap gap-3 text-xs">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full" style={{ backgroundColor: '#ef4444' }} />
                  Short lag (≤5min): temporal proximity only
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full" style={{ backgroundColor: '#f59e0b' }} />
                  Intermediate lag (5-20min): candidate temporal relay
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full" style={{ backgroundColor: '#8b5cf6' }} />
                  Long lag (&gt;20min): delayed response candidate
                </span>
              </div>
            </div>
          </TabsContent>

          {/* ── Time Lag Scatter Tab ── */}
          <TabsContent value="timelag">
            <div className="border rounded-lg p-4">
              <h4 className="text-sm font-semibold mb-3">
                PTM Event Timing vs Signal Propagation Delay
              </h4>
              <p className="text-xs text-muted-foreground mb-3">
                X축: PTM 변화 최초 감지 시점 (min), Y축: PTM→Protein abundance 변화 시간 차이 (min).
                양수 = PTM이 시간적으로 선행, 음수 = Protein abundance가 선행하며, 어느 경우도 단독으로 인과성을 뜻하지 않습니다.
              </p>
              {timeLagScatterData.length > 0 ? (
                <ResponsiveContainer width="100%" height={350}>
                  <ScatterChart margin={{ top: 10, right: 30, bottom: 20, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis
                      type="number"
                      dataKey="x"
                      name="PTM Event Time"
                      unit="min"
                      fontSize={11}
                      label={{ value: 'PTM First Change (min)', position: 'bottom', fontSize: 11, offset: 5 }}
                    />
                    <YAxis
                      type="number"
                      dataKey="y"
                      name="Time Lag"
                      unit="min"
                      fontSize={11}
                      label={{ value: 'Time Lag (min)', angle: -90, position: 'insideLeft', fontSize: 11 }}
                    />
                    <ReferenceLine y={0} stroke="#666" strokeDasharray="5 5" />
                    <ReferenceLine y={5} stroke="#ef4444" strokeDasharray="3 3" opacity={0.4} />
                    <ReferenceLine y={20} stroke="#f59e0b" strokeDasharray="3 3" opacity={0.4} />
                    <Tooltip
                      contentStyle={{ fontSize: 11, borderRadius: 8 }}
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const d = payload[0].payload;
                        return (
                          <div className="bg-white border rounded-lg p-2 shadow-lg text-xs">
                            <p className="font-semibold">{d.name}</p>
                            <p>Type: {d.type === 'self' ? 'Self-regulation' : 'Cascade'}</p>
                            <p>PTM at: {d.x} min (Log2FC: {d.ptm_log2fc?.toFixed(2)})</p>
                            <p>Time lag: {d.y} min</p>
                            <p>Direction: <span style={{ color: DIRECTION_COLORS[d.direction] || '#666' }}>{d.direction}</span></p>
                            <p>Directionality tier: {d.directionality_tier || 'legacy / not evaluated'}</p>
                            <p>Causality: {d.causality_status || 'not tested'}</p>
                          </div>
                        );
                      }}
                    />
                    <Legend
                      verticalAlign="top"
                      content={() => (
                        <div className="flex gap-4 justify-center text-xs mb-2">
                          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-teal-700" /> PTM precedes protein</span>
                          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-orange-500" /> Protein precedes PTM</span>
                          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-blue-500" /> Simultaneous</span>
                          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full border border-gray-400" /> Self</span>
                          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm border border-gray-400" /> Cascade</span>
                        </div>
                      )}
                    />
                    <Scatter data={timeLagScatterData} shape="circle">
                      {timeLagScatterData.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={DIRECTION_COLORS[entry.direction] || '#9ca3af'}
                          r={entry.type === 'cascade' ? 6 : 4}
                          opacity={0.75}
                        />
                      ))}
                    </Scatter>
                  </ScatterChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-12">No time lag data available</p>
              )}
            </div>

            {/* Time Lag Table */}
            {data.self_timelags.length > 0 && (
              <div className="mt-4 border rounded-lg overflow-hidden">
                <div className="p-3 bg-muted/30 border-b">
                  <h4 className="text-sm font-semibold">PTM → Protein Abundance Temporal Precedence Details</h4>
                </div>
                <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/20 sticky top-0">
                      <tr>
                        <th className="text-left p-2 font-medium">Protein</th>
                        <th className="text-left p-2 font-medium">PTM First</th>
                        <th className="text-right p-2 font-medium">PTM Log2FC</th>
                        <th className="text-left p-2 font-medium">Protein First</th>
                        <th className="text-right p-2 font-medium">Prot Log2FC</th>
                        <th className="text-right p-2 font-medium">Lag (min)</th>
                        <th className="text-left p-2 font-medium">Direction</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.self_timelags.map((tl, i) => (
                        <tr key={i} className="border-t hover:bg-muted/10">
                          <td className="p-2 font-mono font-medium">{tl.ptm_key}</td>
                          <td className="p-2">{tl.ptm_first_tp}</td>
                          <td className="p-2 text-right" style={{ color: tl.ptm_log2fc > 0 ? '#ef4444' : '#3b82f6' }}>
                            {tl.ptm_log2fc > 0 ? '+' : ''}{tl.ptm_log2fc.toFixed(2)}
                          </td>
                          <td className="p-2">{tl.protein_first_tp}</td>
                          <td className="p-2 text-right" style={{ color: tl.protein_log2fc > 0 ? '#ef4444' : '#3b82f6' }}>
                            {tl.protein_log2fc > 0 ? '+' : ''}{tl.protein_log2fc.toFixed(2)}
                          </td>
                          <td className="p-2 text-right font-medium">{tl.time_lag_minutes}</td>
                          <td className="p-2">
                            <Badge
                              variant="outline"
                              className="text-[10px] px-1.5"
                              style={{ borderColor: DIRECTION_COLORS[tl.direction] || '#9ca3af', color: DIRECTION_COLORS[tl.direction] || '#9ca3af' }}
                            >
                              {tl.direction === 'source_precedes_target' ? '→ PTM precedes' : tl.direction === 'target_precedes_source' ? '← Protein precedes' : tl.direction === 'simultaneous' ? '⇄ Simultaneous' : '• Unresolved'}
                              {tl.directionality_tier ? ` (${tl.directionality_tier.split('_')[0]})` : ''}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </TabsContent>

          {/* ── Effectors Tab ── */}
          <TabsContent value="effectors">
            {/* Temporal Line Chart */}
            <div className="border rounded-lg p-4 mb-4">
              <h4 className="text-sm font-semibold mb-3">
                Top Effector Protein Temporal Profiles
              </h4>
              <p className="text-xs text-muted-foreground mb-3">
                Non-PTM effector protein의 시간에 따른 abundance 변화 (Log2FC)
              </p>
              {effectorLineData.length > 0 && top8Effectors.length > 0 ? (
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={effectorLineData} margin={{ top: 5, right: 30, bottom: 20, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis
                      dataKey="timepoint"
                      fontSize={10}
                      label={{ value: 'Timepoint', position: 'bottom', fontSize: 11, offset: 5 }}
                    />
                    <YAxis
                      fontSize={11}
                      label={{ value: 'Protein Log2FC', angle: -90, position: 'insideLeft', fontSize: 11 }}
                    />
                    <ReferenceLine y={0} stroke="#666" strokeDasharray="5 5" />
                    <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                    <Legend verticalAlign="top" wrapperStyle={{ fontSize: 10 }} />
                    {top8Effectors.map((e, i) => (
                      <Line
                        key={e.gene}
                        type="monotone"
                        dataKey={e.gene}
                        stroke={LINE_COLORS[i % LINE_COLORS.length]}
                        strokeWidth={2}
                        dot={{ r: 3 }}
                        activeDot={{ r: 5 }}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-12">No effector data available</p>
              )}
            </div>

            {/* Effector Table */}
            {effectorHeatmapData.length > 0 && (
              <div className="border rounded-lg overflow-hidden">
                <div className="p-3 bg-muted/30 border-b">
                  <h4 className="text-sm font-semibold">Effector Protein Temporal Dynamics</h4>
                </div>
                <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/20 sticky top-0">
                      <tr>
                        <th className="text-left p-2 font-medium min-w-[80px]">Gene</th>
                        <th className="text-left p-2 font-medium min-w-[60px]">Pattern</th>
                        {data.timepoints.map(tp => (
                          <th key={tp} className="text-right p-2 font-medium min-w-[60px]">{tp}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {effectorHeatmapData.map((row, i) => (
                        <tr key={i} className="border-t hover:bg-muted/10">
                          <td className="p-2 font-mono font-medium">{row.gene}</td>
                          <td className="p-2">
                            <Badge
                              variant="outline"
                              className="text-[10px] px-1"
                              style={{ borderColor: PATTERN_COLORS[row.pattern] || '#9ca3af', color: PATTERN_COLORS[row.pattern] || '#9ca3af' }}
                            >
                              {PATTERN_LABELS[row.pattern] || row.pattern}
                            </Badge>
                          </td>
                          {data.timepoints.map(tp => {
                            const val = (row as Record<string, any>)[tp] as number || 0;
                            const intensity = Math.min(Math.abs(val) / 2, 1);
                            const bg = val > 0
                              ? `rgba(239, 68, 68, ${intensity * 0.3})`
                              : val < 0
                                ? `rgba(59, 130, 246, ${intensity * 0.3})`
                                : 'transparent';
                            return (
                              <td key={tp} className="p-2 text-right font-mono" style={{ backgroundColor: bg }}>
                                {val !== 0 ? (val > 0 ? '+' : '') + val.toFixed(2) : '-'}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </TabsContent>

          {/* ── Cascade Tab ── */}
          <TabsContent value="cascade">
            {data.cascade_timelags.length > 0 ? (
              <>
                {/* Cascade Visualization */}
                <div className="border rounded-lg p-4 mb-4">
                  <h4 className="text-sm font-semibold mb-3">
                    PTM Substrate → Effector Signal Cascade
                  </h4>
                  <p className="text-xs text-muted-foreground mb-3">
                    PTM 기질 단백질에서 downstream effector로의 신호 전파 경로와 시간 지연
                  </p>
                  <div className="space-y-2">
                    {data.cascade_timelags.map((tl, i) => {
                      const maxMinutes = Math.max(...data.timepoint_minutes, 1);
                      const ptmPos = (tl.ptm_first_minutes / maxMinutes) * 100;
                      const effPos = (tl.effector_first_minutes / maxMinutes) * 100;
                      const isForward = tl.direction === 'forward_propagation';

                      return (
                        <div key={i} className="relative border rounded-lg p-3 hover:bg-muted/10 transition-colors">
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <span className="font-mono font-semibold text-sm">{tl.ptm_substrate}</span>
                              <ArrowRight className="h-4 w-4 text-muted-foreground" />
                              <span className="font-mono font-semibold text-sm">{tl.effector}</span>
                            </div>
                            <Badge
                              variant="outline"
                              className="text-[10px]"
                              style={{
                                borderColor: isForward ? '#22c55e' : '#f97316',
                                color: isForward ? '#22c55e' : '#f97316',
                              }}
                            >
                              {isForward ? `+${tl.time_lag_minutes}min lag` : `${tl.time_lag_minutes}min (reverse)`}
                            </Badge>
                          </div>
                          {/* Timeline bar */}
                          <div className="relative h-6 bg-gray-100 rounded-full overflow-hidden">
                            {/* PTM event marker */}
                            <div
                              className="absolute top-0 h-full w-1 bg-red-500 z-10"
                              style={{ left: `${Math.min(ptmPos, 98)}%` }}
                              title={`PTM at ${tl.ptm_first_tp}`}
                            />
                            {/* Effector response marker */}
                            <div
                              className="absolute top-0 h-full w-1 z-10"
                              style={{
                                left: `${Math.min(effPos, 98)}%`,
                                backgroundColor: isForward ? '#22c55e' : '#f97316',
                              }}
                              title={`Effector at ${tl.effector_first_tp}`}
                            />
                            {/* Connection line */}
                            <div
                              className="absolute top-1/2 h-0.5 -translate-y-1/2"
                              style={{
                                left: `${Math.min(ptmPos, effPos)}%`,
                                width: `${Math.abs(effPos - ptmPos)}%`,
                                backgroundColor: isForward ? 'rgba(34,197,94,0.3)' : 'rgba(249,115,22,0.3)',
                              }}
                            />
                          </div>
                          <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
                            <span>PTM: {tl.ptm_first_tp} (Log2FC: {tl.ptm_log2fc > 0 ? '+' : ''}{tl.ptm_log2fc.toFixed(2)})</span>
                            <span>Effector: {tl.effector_first_tp} (Log2FC: {tl.effector_log2fc > 0 ? '+' : ''}{tl.effector_log2fc.toFixed(2)})</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Cascade Table */}
                <div className="border rounded-lg overflow-hidden">
                  <div className="p-3 bg-muted/30 border-b">
                    <h4 className="text-sm font-semibold">Signal Cascade Details</h4>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/20">
                        <tr>
                          <th className="text-left p-2 font-medium">PTM Substrate</th>
                          <th className="text-left p-2 font-medium">Effector</th>
                          <th className="text-left p-2 font-medium">PTM at</th>
                          <th className="text-left p-2 font-medium">Effector at</th>
                          <th className="text-right p-2 font-medium">Lag (min)</th>
                          <th className="text-left p-2 font-medium">Direction</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.cascade_timelags.map((tl, i) => (
                          <tr key={i} className="border-t hover:bg-muted/10">
                            <td className="p-2 font-mono font-medium">{tl.ptm_substrate}</td>
                            <td className="p-2 font-mono">{tl.effector}</td>
                            <td className="p-2">{tl.ptm_first_tp}</td>
                            <td className="p-2">{tl.effector_first_tp}</td>
                            <td className="p-2 text-right font-medium">{tl.time_lag_minutes}</td>
                            <td className="p-2">
                              <Badge
                                variant="outline"
                                className="text-[10px] px-1.5"
                                style={{
                                  borderColor: DIRECTION_COLORS[tl.direction] || '#9ca3af',
                                  color: DIRECTION_COLORS[tl.direction] || '#9ca3af',
                                }}
                              >
                                {tl.direction === 'forward_propagation' ? '→ Forward' : tl.direction === 'reverse_signaling' ? '← Reverse' : '⇄ Co-activation'}
                              </Badge>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            ) : (
              <div className="text-center py-12 text-muted-foreground">
                <ArrowRight className="h-12 w-12 mx-auto mb-3 opacity-30" />
                <p className="text-sm font-medium">No cascade data available</p>
                <p className="text-xs mt-1">PTM substrate → effector protein 간 시간적 연결이 감지되지 않았습니다</p>
              </div>
            )}
          </TabsContent>

          {/* ── TF Activity Tab ── */}
          <TabsContent value="tf_activity">
            {data.tf_inferences ? (
              <div className="space-y-4">
                {/* Summary Stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-muted/50 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-primary">{data.tf_inferences.n_changed_proteins}</p>
                    <p className="text-xs text-muted-foreground">Changed Proteins</p>
                  </div>
                  <div className="bg-muted/50 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-green-500">{data.tf_inferences.cross_validated_tfs.length}</p>
                    <p className="text-xs text-muted-foreground">Cross-Validated TFs</p>
                  </div>
                  <div className="bg-muted/50 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-amber-500">{data.tf_inferences.nonptm_only_tfs.length}</p>
                    <p className="text-xs text-muted-foreground">NonPTM-Inferred TFs</p>
                  </div>
                  <div className="bg-muted/50 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-blue-500">{data.tf_inferences.all_inferred_tfs.length}</p>
                    <p className="text-xs text-muted-foreground">Total Inferred TFs</p>
                  </div>
                </div>

                {/* Cross-Validated TFs (High Confidence) */}
                {data.tf_inferences.cross_validated_tfs.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold flex items-center gap-1 mb-2">
                      <CheckCircle2 className="h-4 w-4 text-green-500" />
                      Cross-Validated TFs (PTM + Target Gene Convergent)
                    </h4>
                    <div className="space-y-2">
                      {data.tf_inferences.cross_validated_tfs.map((tf, i) => (
                        <div key={i} className="border rounded-lg p-3 bg-green-500/5">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Badge variant="default" className="bg-green-600 text-xs">{tf.tf}</Badge>
                              <span className="text-xs text-muted-foreground">
                                {tf.n_overlap} targets | fold={tf.fold_enrichment.toFixed(1)}x
                              </span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Badge variant="outline" className="text-xs">
                                {tf.dominant_mode === 'activation' ? '↑' : tf.dominant_mode === 'repression' ? '↓' : '↕'} {tf.dominant_mode}
                              </Badge>
                              <Badge variant="outline" className="text-xs">
                                FDR={tf.fdr < 0.001 ? tf.fdr.toExponential(1) : tf.fdr.toFixed(3)}
                              </Badge>
                            </div>
                          </div>
                          {tf.overlap_genes.length > 0 && (
                            <p className="text-xs text-muted-foreground mt-1">
                              Targets: {tf.overlap_genes.slice(0, 8).join(', ')}
                              {tf.overlap_genes.length > 8 && ` (+${tf.overlap_genes.length - 8} more)`}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* NonPTM-Only Inferred TFs */}
                {data.tf_inferences.nonptm_only_tfs.length > 0 && (
                  <div>
                    <h4 className="text-sm font-semibold flex items-center gap-1 mb-2">
                      <AlertCircle className="h-4 w-4 text-amber-500" />
                      NonPTM-Inferred TFs (Target Gene Evidence Only)
                    </h4>
                    <div className="space-y-2">
                      {data.tf_inferences.nonptm_only_tfs.slice(0, 5).map((tf, i) => (
                        <div key={i} className="border rounded-lg p-3 bg-amber-500/5">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Badge variant="secondary" className="text-xs">{tf.tf}</Badge>
                              <span className="text-xs text-muted-foreground">
                                {tf.n_overlap} targets | p={tf.pvalue < 0.001 ? tf.pvalue.toExponential(1) : tf.pvalue.toFixed(3)}
                              </span>
                            </div>
                            <Badge variant="outline" className="text-xs">
                              {tf.dominant_mode === 'activation' ? '↑' : '↓'} {tf.dominant_mode}
                            </Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Temporal Resolution */}
                {(data.tf_inferences.temporal_inference.early.length > 0 || data.tf_inferences.temporal_inference.late.length > 0) && (
                  <div>
                    <h4 className="text-sm font-semibold flex items-center gap-1 mb-2">
                      <Clock className="h-4 w-4 text-blue-500" />
                      Temporal Resolution
                    </h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {data.tf_inferences.temporal_inference.early.length > 0 && (
                        <div className="border rounded-lg p-3">
                          <p className="text-xs font-medium text-muted-foreground mb-1">Early Responders (≤15min)</p>
                          <p className="text-xs text-muted-foreground italic mb-1">Post-translational activation</p>
                          <div className="flex flex-wrap gap-1">
                            {data.tf_inferences.temporal_inference.early.filter(t => t.fdr < 0.1).slice(0, 5).map((tf, i) => (
                              <Badge key={i} variant="outline" className="text-xs">{tf.tf}</Badge>
                            ))}
                          </div>
                        </div>
                      )}
                      {data.tf_inferences.temporal_inference.late.length > 0 && (
                        <div className="border rounded-lg p-3">
                          <p className="text-xs font-medium text-muted-foreground mb-1">Late Responders (&gt;15min)</p>
                          <p className="text-xs text-muted-foreground italic mb-1">Transcriptional program</p>
                          <div className="flex flex-wrap gap-1">
                            {data.tf_inferences.temporal_inference.late.filter(t => t.fdr < 0.1).slice(0, 5).map((tf, i) => (
                              <Badge key={i} variant="outline" className="text-xs">{tf.tf}</Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Data Sources */}
                <div className="text-xs text-muted-foreground flex items-center gap-2 pt-2 border-t">
                  <span>Sources: {data.tf_inferences.sources.join(', ')}</span>
                  <span>|</span>
                  <span>Species: {data.tf_inferences.species}</span>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                <Dna className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p className="text-sm font-medium">TF Activity Inference not available</p>
                <p className="text-xs mt-1">리포트 생성 시 자동으로 계산됩니다 (DoRothEA + TRRUST)</p>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
