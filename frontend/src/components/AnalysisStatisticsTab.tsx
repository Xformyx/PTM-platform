/**
 * AnalysisStatisticsTab — Pipeline statistics visualization
 * Displays preprocessing pipeline statistics from pipeline_statistics.json
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ReTooltip,
  ResponsiveContainer, Cell, PieChart, Pie, Legend,
} from "recharts";
import {
  Database, FlaskConical, FileOutput,
  ArrowRight, Loader2, BarChart3, ChevronUp, ChevronDown,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PipelineStats {
  metadata?: { ptm_mode?: string; ptm_mode_name?: string; timestamp?: string };
  step1_input?: Record<string, any>;
  step2_quantification?: Record<string, any>;
  step3_enrichment?: Record<string, any>;
  step4_biological?: Record<string, any>;
  final_output?: Record<string, any>;
}

interface PtmFiltering {
  ptm_sites?: number;
  phospho_sites?: number;
  ubi_sites?: number;
  ptm_proteins?: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function fmt(n: number | undefined | null): string {
  if (n == null || isNaN(Number(n))) return "—";
  return Number(n).toLocaleString();
}


/* ------------------------------------------------------------------ */
/*  Stat helpers                                                       */
/* ------------------------------------------------------------------ */

function StatValue({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="space-y-0.5">
      <p className="text-[11px] text-muted-foreground leading-tight">{label}</p>
      <p className="text-lg font-semibold tabular-nums font-mono leading-none">{typeof value === "number" ? fmt(value) : value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Pipeline Flow Stepper                                              */
/* ------------------------------------------------------------------ */

const STEP_COLORS = [
  "text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950 dark:border-blue-800",
  "text-orange-600 bg-orange-50 border-orange-200 dark:text-orange-400 dark:bg-orange-950 dark:border-orange-800",
  "text-rose-600 bg-rose-50 border-rose-200 dark:text-rose-400 dark:bg-rose-950 dark:border-rose-800",
];

const STEP_ICONS = [Database, FlaskConical, FileOutput];

function PipelineFlowCard({ stats }: { stats: PipelineStats }) {
  const s1 = stats.step1_input ?? {};
  const s2 = stats.step2_quantification ?? {};
  const sf = stats.final_output ?? {};
  const filt = (s2.ptm_filtering ?? {}) as PtmFiltering;

  const quantLines: string[] = [];
  if (filt.phospho_sites != null && filt.phospho_sites > 0) {
    quantLines.push(`${fmt(filt.phospho_sites)} Phosphorylation sites`);
  }
  if (filt.ubi_sites != null && filt.ubi_sites > 0) {
    quantLines.push(`${fmt(filt.ubi_sites)} Ubiquitylation sites`);
  }
  if (quantLines.length === 0 && filt.ptm_sites != null) {
    const siteLabel = stats.metadata?.ptm_mode_name ? `${stats.metadata.ptm_mode_name} sites` : "PTM sites";
    quantLines.push(`${fmt(filt.ptm_sites)} ${siteLabel}`);
  }
  if (filt.ptm_proteins != null) {
    quantLines.push(`${fmt(filt.ptm_proteins)} proteins`);
  }

  const steps = [
    {
      title: "Input Data",
      lines: [
        `${fmt(s1.total_precursors)} precursors`,
        `${fmt(s1.total_protein_groups)} protein groups`,
      ],
      done: !!s1.total_precursors,
    },
    {
      title: "Quantification",
      lines: quantLines.length > 0 ? quantLines : ["—"],
      done: !!s2.ptm_filtering,
    },
    {
      title: "Final Output",
      lines: [
        `${fmt(sf.total_rows)} rows`,
        `${fmt(sf.total_columns)} columns`,
      ],
      done: !!sf.total_rows,
    },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <BarChart3 className="h-4 w-4" />
          Pipeline Flow
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-stretch gap-1 overflow-x-auto pb-2">
          {steps.map((step, i) => {
            const Icon = STEP_ICONS[i];
            return (
              <div key={i} className="flex items-center gap-1 min-w-0">
                <div
                  className={`rounded-lg border px-3 py-2.5 min-w-[130px] transition-opacity ${STEP_COLORS[i]} ${
                    step.done ? "opacity-100" : "opacity-40"
                  }`}
                >
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="text-xs font-semibold truncate">{step.title}</span>
                  </div>
                  {step.lines.map((l, j) => (
                    <p key={j} className="text-[10px] leading-tight opacity-80 tabular-nums font-mono truncate">
                      {l}
                    </p>
                  ))}
                </div>
                {i < steps.length - 1 && (
                  <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Input Data Card                                                    */
/* ------------------------------------------------------------------ */

function InputDataCard({ s1 }: { s1: Record<string, any> }) {
  const conditions = s1.conditions ?? s1.treatment_conditions ?? {};
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Database className="h-4 w-4 text-blue-500" />
          Step 1 — Input Data
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid md:grid-cols-3 gap-6">
          {/* PR Matrix */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">PR Matrix</p>
            <StatValue label="Precursors" value={s1.total_precursors} />
            <StatValue label="Proteins" value={s1.total_proteins_pr} />
            <StatValue label="Peptides" value={s1.total_peptides} />
          </div>
          {/* PG Matrix */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">PG Matrix</p>
            <StatValue label="Protein Groups" value={s1.total_protein_groups} />
            <StatValue label="Total Samples" value={s1.total_samples} />
          </div>
          {/* Conditions & FASTA */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">FASTA & Conditions</p>
            <StatValue label="FASTA Proteins" value={s1.fasta_proteins} />
            <StatValue label="Control Samples" value={s1.control_samples} />
            {Object.keys(conditions).length > 0 && (
              <div>
                <p className="text-[11px] text-muted-foreground mb-1">Treatment Conditions</p>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(conditions).map(([k, v]) => (
                    <Badge key={k} variant="secondary" className="text-[10px] font-mono">
                      {k}: {fmt(v as number)}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Quantification Card                                                */
/* ------------------------------------------------------------------ */

const BAR_COLORS = { up: "#ef4444", down: "#3b82f6", unchanged: "#9ca3af" };

function QuantificationCard({ s2, ptmModeName }: { s2: Record<string, any>; ptmModeName?: string }) {
  const norm = s2.normalization ?? {};
  const filt = s2.ptm_filtering ?? {};
  const rq = s2.relative_quant ?? {};
  const comp = s2.comparisons ?? {};
  const prot = s2.protein_changes ?? {};
  const vec = s2.ptm_vector ?? {};
  const quad = vec.quadrant_analysis ?? {};

  // Bar chart data
  const perCond = comp.per_condition ?? {};
  const barData = Object.entries(perCond).map(([name, v]: [string, any]) => ({
    name: name.length > 18 ? name.slice(0, 15) + "..." : name,
    fullName: name,
    Up: v.up_regulated ?? 0,
    Down: v.down_regulated ?? 0,
    Unchanged: v.unchanged ?? 0,
    meanLog2FC: v.mean_log2fc ?? 0,
  }));

  // Donut data
  const donutData = [
    { name: "PTM", value: filt.ptm_precursors ?? 0, fill: "#f97316" },
    { name: "non-PTM", value: Math.max((filt.total_precursors ?? 0) - (filt.ptm_precursors ?? 0), 0), fill: "#d1d5db" },
  ];

  const quadrantItems = [
    { label: "Q1 Prot+ PTM+", value: quad.Q1_up_up, icon: <ChevronUp className="h-3 w-3" />, color: "text-red-500" },
    { label: "Q2 Prot- PTM+", value: quad.Q2_down_up, icon: <ChevronUp className="h-3 w-3" />, color: "text-orange-500" },
    { label: "Q3 Prot- PTM-", value: quad.Q3_down_down, icon: <ChevronDown className="h-3 w-3" />, color: "text-blue-500" },
    { label: "Q4 Prot+ PTM-", value: quad.Q4_up_down, icon: <ChevronDown className="h-3 w-3" />, color: "text-cyan-500" },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-orange-500" />
          Step 2 — PTM Quantification
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Normalization & Batch Correction Description */}
        <div className="rounded-lg border bg-muted/30 px-4 py-3 text-xs text-muted-foreground space-y-1.5">
          <p className="font-medium text-foreground">Normalization & Batch Variation Correction</p>
          <p>
            <strong>Median normalization</strong>: Sample-wise scaling to align intensity distributions. Each sample&apos;s median is scaled to the global median to correct for technical variation.
          </p>
          <p>
            <strong>Batch variation correction</strong>: The same median normalization step corrects for sample-to-sample (batch) variation, ensuring comparable intensity levels across conditions before PTM quantification.
          </p>
        </div>

        {/* Row 1: Normalization + PTM Filtering + Relative Quant */}
        <div className="grid md:grid-cols-3 gap-6">
          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Normalization</p>
            <StatValue label="PR Precursors" value={norm.pr_precursors_before} />
            <StatValue label="PG Proteins" value={norm.pg_proteins_before} />
            {norm.samples_corrected != null && (
              <StatValue label="Samples Corrected" value={norm.samples_corrected} sub={norm.method === "median" ? "Median method" : undefined} />
            )}
            {Array.isArray(norm.factor_range) && norm.factor_range.length === 2 && (
              <p className="text-[10px] text-muted-foreground">
                Factor range: {norm.factor_range[0]} – {norm.factor_range[1]}
              </p>
            )}
          </div>
          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">PTM Filtering</p>
            <StatValue label="PTM Precursors" value={filt.ptm_precursors} sub={`${filt.ptm_ratio ?? 0}% of total`} />
            <StatValue label="PTM Proteins" value={filt.ptm_proteins} />
            {(filt.phospho_sites != null || filt.ubi_sites != null) ? (
              <>
                {filt.phospho_sites != null && filt.phospho_sites > 0 && (
                  <StatValue label="Phosphorylation Sites" value={filt.phospho_sites} />
                )}
                {filt.ubi_sites != null && filt.ubi_sites > 0 && (
                  <StatValue label="Ubiquitylation Sites" value={filt.ubi_sites} />
                )}
              </>
            ) : (
              <StatValue label={ptmModeName ? `${ptmModeName} Sites` : "PTM Sites"} value={filt.ptm_sites} />
            )}
          </div>
          <div className="space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Relative Quantification</p>
            <StatValue label="Total Entries" value={rq.total_entries} />
            <StatValue label="Unique Proteins" value={rq.unique_proteins} />
            <StatValue label={ptmModeName ? `${ptmModeName} Sites` : "Unique Sites"} value={rq.unique_sites} />
          </div>
        </div>

        {/* Row 2: PTM ratio donut + Condition comparison bar chart */}
        <div className="grid md:grid-cols-2 gap-6">
          {/* Donut */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">PTM Precursor Ratio</p>
            <div className="h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={donutData}
                    cx="50%"
                    cy="50%"
                    innerRadius={55}
                    outerRadius={80}
                    paddingAngle={2}
                    dataKey="value"
                    label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(1)}%`}
                  >
                    {donutData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Pie>
                  <ReTooltip formatter={(v: unknown) => fmt(Number(v))} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Bar chart */}
          {barData.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
                Condition Comparison (|Log2FC| &gt; 1)
              </p>
              <div className="h-[200px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={barData} barGap={1} barCategoryGap="20%">
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={50} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <ReTooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const d = payload[0].payload;
                        return (
                          <div className="rounded-md border bg-popover p-2 text-xs shadow-md">
                            <p className="font-semibold mb-1">{d.fullName}</p>
                            <p className="text-red-500">Up: {fmt(d.Up)}</p>
                            <p className="text-blue-500">Down: {fmt(d.Down)}</p>
                            <p className="text-muted-foreground">Unchanged: {fmt(d.Unchanged)}</p>
                            <p className="mt-1 text-muted-foreground">Mean Log2FC: {d.meanLog2FC}</p>
                          </div>
                        );
                      }}
                    />
                    <Bar dataKey="Up" fill={BAR_COLORS.up} radius={[2, 2, 0, 0]} />
                    <Bar dataKey="Down" fill={BAR_COLORS.down} radius={[2, 2, 0, 0]} />
                    <Bar dataKey="Unchanged" fill={BAR_COLORS.unchanged} radius={[2, 2, 0, 0]} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>

        {/* Row 3: Protein Changes + Quadrant */}
        <div className="grid md:grid-cols-2 gap-6">
          {/* Protein Changes */}
          {prot.all_proteins && (
            <div className="space-y-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Protein Level Changes</p>
              <div className="grid grid-cols-3 gap-3">
                <StatValue label="All Proteins" value={prot.all_proteins?.unique_proteins} />
                <StatValue label="PTM Proteins" value={prot.ptm_proteins?.unique_proteins} />
                <StatValue label="non-PTM" value={prot.non_ptm_proteins} />
              </div>
            </div>
          )}

          {/* Quadrant */}
          {(quad.Q1_up_up != null) && (
            <div className="space-y-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Quadrant Analysis</p>
              <div className="grid grid-cols-2 gap-2">
                {quadrantItems.map((q, i) => (
                  <div key={i} className="rounded-md border px-3 py-2 flex items-center gap-2">
                    <span className={q.color}>{q.icon}</span>
                    <div>
                      <p className="text-[10px] text-muted-foreground">{q.label}</p>
                      <p className="text-sm font-semibold tabular-nums font-mono">{fmt(q.value)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}



/* ------------------------------------------------------------------ */
/*  Final Output Card                                                  */
/* ------------------------------------------------------------------ */

function FinalOutputCard({ sf }: { sf: Record<string, any> }) {
  return (
    <Card className="border-rose-200 dark:border-rose-800">
      <CardContent className="py-4">
        <div className="flex items-center gap-3 mb-3">
          <FileOutput className="h-5 w-5 text-rose-500" />
          <span className="text-sm font-semibold">Final Output</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatValue label="Total Rows" value={sf.total_rows} />
          <StatValue label="Total Columns" value={sf.total_columns} />
          <StatValue label="Unique Proteins" value={sf.unique_proteins} />
          <StatValue label="Conditions" value={sf.conditions} />
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Tab Component                                                 */
/* ------------------------------------------------------------------ */

export function AnalysisStatisticsTab({ orderId }: { orderId: number }) {
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .get<{ statistics: PipelineStats | null; available: boolean }>(`/orders/${orderId}/statistics`)
      .then((res) => {
        if (res.available && res.statistics) {
          setStats(res.statistics);
        } else {
          setStats(null);
        }
      })
      .catch((err) => {
        setError(err?.message ?? "Failed to load statistics");
      })
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Loading pipeline statistics...</p>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
          <BarChart3 className="h-10 w-10 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">{error}</p>
        </CardContent>
      </Card>
    );
  }

  if (!stats) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
          <BarChart3 className="h-10 w-10 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">
            Analysis statistics will appear here after preprocessing completes.
          </p>
        </CardContent>
      </Card>
    );
  }

  const s1 = stats.step1_input ?? {};
  const s2 = stats.step2_quantification ?? {};
  const sf = stats.final_output ?? {};

  return (
    <div className="space-y-4">
      {/* Pipeline Flow */}
      <PipelineFlowCard stats={stats} />

      {/* Step 1: Input Data */}
      {Object.keys(s1).length > 0 && <InputDataCard s1={s1} />}

      {/* Step 2: Quantification */}
      {Object.keys(s2).length > 0 && <QuantificationCard s2={s2} ptmModeName={stats.metadata?.ptm_mode_name} />}

      {/* Final Output */}
      {Object.keys(sf).length > 0 && <FinalOutputCard sf={sf} />}

      {/* Metadata */}
      {stats.metadata && (
        <p className="text-[10px] text-muted-foreground text-right">
          {stats.metadata.ptm_mode_name} analysis
          {stats.metadata.timestamp ? ` — ${stats.metadata.timestamp}` : ""}
        </p>
      )}
    </div>
  );
}
