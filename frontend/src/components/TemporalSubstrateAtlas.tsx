/**
 * Design: evidence-first scientific dashboard. Dense, dark-compatible, and deliberately
 * non-causal: an asymmetric overview-to-site-drawer flow exposes quality before interpretation.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowRight, ChevronRight, CircleDot, Clock3,
  GitBranch, Layers3, Loader2, Network, ShieldCheck, Sparkles,
} from "lucide-react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type ContextItem = { kinase?: string; gene?: string; site?: string; relationship?: string; evidence_type?: string };
type FormProfile = {
  site_form_key?: string; modified_sequence?: string | null; precursor_charge?: number | null;
  precursor_id?: string | null; form_identity_status?: string; primary_pattern?: string;
  atlas_eligible?: boolean; loto_pattern_stability?: number | null;
  threshold_sensitivity_flag?: boolean; qvalue_coverage?: number | null;
  observed_timepoints?: number; missing_timepoints?: number; values?: Array<number | null>;
};
type AtlasSite = {
  site_key: string; claim_id?: string; gene: string; position: string;
  primary_pattern: string; candidate_pattern?: string | null; pattern_modifiers?: string[];
  atlas_eligible: boolean; atlas_eligibility_reasons?: string[];
  amplitude?: number | null; onset_minutes?: number | null; peak_minutes?: number | null;
  auc_signed?: number | null; qvalue_coverage?: number | null;
  loto_pattern_stability?: number | null; threshold_sensitivity_flag?: boolean;
  observed_timepoints?: number; missing_timepoints?: number;
  timepoint_labels: string[]; values: Array<number | null>; site_form_count?: number;
  site_aggregation?: { method?: string; form_keys?: string[] };
  form_profiles?: FormProfile[];
  context_evidence?: {
    kinase_context?: ContextItem[]; self_ptm_candidates?: ContextItem[];
    nuclear_context?: { nucleus_annotated?: boolean; evidence_type?: string };
    non_ptm_follow_through?: ContextItem[];
  };
};
type Transition = {
  site_a?: string; site_b?: string; site_key?: string; from_window: string; to_window: string;
  transition_type: string; prior_states?: string[]; next_states?: string[];
  partner_count_before?: number; partner_count_after?: number;
};
type AtlasResponse = {
  status: string; n_sites?: number; n_atlas_eligible_sites?: number;
  pattern_distribution?: Record<string, number>; sites?: AtlasSite[];
  transition_map?: { status?: string; reason?: string; transition_counts?: Record<string, number>; pair_transitions?: Transition[]; site_transitions?: Transition[]; excluded_sites?: Record<string, string[]>; observed_transition_semantics?: string };
};

const PATTERN_COLORS: Record<string, string> = {
  early_single_pulse: "bg-amber-500/15 text-amber-700 border-amber-500/30 dark:text-amber-300",
  delayed_single_pulse: "bg-orange-500/15 text-orange-700 border-orange-500/30 dark:text-orange-300",
  sustained_activation: "bg-emerald-500/15 text-emerald-700 border-emerald-500/30 dark:text-emerald-300",
  sustained_suppression: "bg-sky-500/15 text-sky-700 border-sky-500/30 dark:text-sky-300",
  rebound: "bg-violet-500/15 text-violet-700 border-violet-500/30 dark:text-violet-300",
  biphasic: "bg-fuchsia-500/15 text-fuchsia-700 border-fuchsia-500/30 dark:text-fuchsia-300",
  multi_peak_candidate: "bg-rose-500/15 text-rose-700 border-rose-500/30 dark:text-rose-300",
  oscillatory_supported: "bg-red-500/15 text-red-700 border-red-500/30 dark:text-red-300",
  monotonic_rise: "bg-lime-500/15 text-lime-700 border-lime-500/30 dark:text-lime-300",
  monotonic_decline: "bg-blue-500/15 text-blue-700 border-blue-500/30 dark:text-blue-300",
};
const FORM_COLORS = ["#0ea5e9", "#f97316", "#a855f7", "#10b981", "#eab308"];

function humanize(value?: string | null) {
  return (value || "unresolved").replace(/_/g, " ");
}

function PatternBadge({ pattern }: { pattern?: string | null }) {
  const p = pattern || "unresolved";
  return <Badge variant="outline" className={cn("text-[10px] capitalize", PATTERN_COLORS[p] || "bg-muted text-muted-foreground")}>{humanize(p)}</Badge>;
}

function QualityBadge({ site }: { site: AtlasSite }) {
  if (!site.atlas_eligible) return <Badge variant="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300">Needs audit</Badge>;
  if (site.threshold_sensitivity_flag || (site.loto_pattern_stability ?? 1) < 0.8) return <Badge variant="outline" className="border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300">Exploratory</Badge>;
  return <Badge variant="outline" className="border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">Atlas eligible</Badge>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><p className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{label}</p><p className="mt-0.5 truncate text-sm font-medium">{value}</p></div>;
}

export function TemporalSubstrateAtlas({ orderId, active }: { orderId: number; active: boolean }) {
  const [data, setData] = useState<AtlasResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [patternFilter, setPatternFilter] = useState("all");
  const [qualityFilter, setQualityFilter] = useState("eligible");
  const [selectedKey, setSelectedKey] = useState("");
  const [yMode, setYMode] = useState("auto");
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!active || !orderId) return;
    let cancelled = false;
    setLoading(true); setError("");
    api.get<AtlasResponse>(`/orders/${orderId}/substrate-temporal`)
      .then((response) => { if (!cancelled) setData(response); })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : "Atlas data could not be loaded."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [active, orderId, reloadToken]);

  const sites = data?.sites || [];
  const visibleSites = useMemo(() => sites.filter((site) =>
    (patternFilter === "all" || site.primary_pattern === patternFilter) &&
    (qualityFilter === "all" || (qualityFilter === "eligible" ? site.atlas_eligible : !site.atlas_eligible)),
  ), [sites, patternFilter, qualityFilter]);
  const selected = useMemo(() => visibleSites.find((site) => site.site_key === selectedKey) || visibleSites[0] || sites[0], [visibleSites, selectedKey, sites]);

  const chartData = useMemo(() => {
    if (!selected) return [];
    return selected.timepoint_labels.map((label, index) => {
      const row: Record<string, string | number | null> = { label, aggregate: selected.values[index] ?? null };
      (selected.form_profiles || []).forEach((form, formIndex) => { row[`form_${formIndex}`] = form.values?.[index] ?? null; });
      return row;
    });
  }, [selected]);
  const yDomain = useMemo(() => {
    if (yMode !== "symmetric" || !selected) return ["auto", "auto"] as const;
    const values = [...selected.values, ...(selected.form_profiles || []).flatMap((form) => form.values || [])].filter((x): x is number => typeof x === "number");
    const max = Math.max(1, ...values.map((value) => Math.abs(value)));
    return [-Math.ceil(max * 1.12), Math.ceil(max * 1.12)] as const;
  }, [selected, yMode]);
  const transitions = [
    ...(data?.transition_map?.pair_transitions || []).map((transition) => ({ ...transition, kind: "pair" })),
    ...(data?.transition_map?.site_transitions || []).map((transition) => ({ ...transition, kind: "site" })),
  ];

  if (loading) return <div className="space-y-4"><Skeleton className="h-28 w-full" /><Skeleton className="h-[420px] w-full" /></div>;
  if (error) return <Card><CardContent className="flex flex-col items-center gap-3 py-12"><AlertTriangle className="h-8 w-8 text-destructive" /><p className="text-sm text-muted-foreground">{error}</p><Button variant="outline" size="sm" onClick={() => setReloadToken((token) => token + 1)}>Retry</Button></CardContent></Card>;
  if (!data || data.status === "no_enriched_data" || sites.length === 0) return <Card><CardContent className="flex flex-col items-center gap-3 py-14 text-center"><Layers3 className="h-10 w-10 text-muted-foreground/50" /><div><p className="font-medium">Temporal Atlas is not available yet</p><p className="mt-1 max-w-md text-sm text-muted-foreground">Run preprocessing with enriched PTM trajectories, then return here. The Atlas never substitutes missing trajectories with inferred patterns.</p></div></CardContent></Card>;

  return <div className="space-y-5">
    <section className="border-y border-primary/20 bg-gradient-to-r from-primary/10 via-background to-amber-500/10 px-5 py-5">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div className="max-w-3xl"><div className="flex items-center gap-2 text-primary"><Activity className="h-5 w-5" /><span className="text-xs font-semibold uppercase tracking-[0.16em]">Evidence-first Temporal Atlas</span></div><h2 className="mt-2 text-xl font-semibold tracking-tight">Substrate dynamics, observed transitions, and context evidence</h2><p className="mt-1 text-sm text-muted-foreground">Pattern labels describe measured trajectories. Transition edges are observed membership changes, not causal arrows or direct kinase assignments.</p></div>
        <div className="grid grid-cols-3 gap-x-6 gap-y-2 border-l border-primary/15 pl-5"><Metric label="Sites" value={String(data.n_sites ?? sites.length)} /><Metric label="Eligible" value={String(data.n_atlas_eligible_sites ?? 0)} /><Metric label="Transitions" value={String(transitions.length)} /></div>
      </div>
    </section>

    <section className="grid gap-4 xl:grid-cols-[1.45fr_0.85fr]">
      <Card className="rounded-lg shadow-none"><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-sm"><Layers3 className="h-4 w-4 text-primary" />Pattern & quality overview</CardTitle></CardHeader><CardContent>
        <div className="flex flex-wrap gap-2">{Object.entries(data.pattern_distribution || {}).sort((a, b) => b[1] - a[1]).map(([pattern, count]) => <button key={pattern} type="button" onClick={() => setPatternFilter(patternFilter === pattern ? "all" : pattern)} className={cn("flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs transition-colors", patternFilter === pattern ? "border-primary bg-primary/10" : "border-border hover:bg-muted/60")} aria-pressed={patternFilter === pattern}><PatternBadge pattern={pattern} /><span className="font-mono text-muted-foreground">{count}</span></button>)}</div>
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4"><Metric label="Eligible" value={String(data.n_atlas_eligible_sites ?? 0)} /><Metric label="Needs audit" value={String(sites.filter((site) => !site.atlas_eligible).length)} /><Metric label="Form-aware" value={`${sites.filter((site) => (site.site_form_count || 0) > 1).length} sites`} /><Metric label="Quality rule" value="P1.1 gate" /></div>
      </CardContent></Card>
      <Card className="rounded-lg shadow-none"><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-sm"><ShieldCheck className="h-4 w-4 text-emerald-600" />Interpretation boundary</CardTitle></CardHeader><CardContent className="space-y-2 text-xs leading-relaxed text-muted-foreground"><p>Only Atlas-eligible trajectories enter high-confidence interpretation. Input-order, duplicate-timepoint, missingness, LOTO, and threshold-sensitivity signals remain visible.</p><p className="font-medium text-foreground">Kinase/TMM, self-PTM, nuclear and non-PTM panels are context evidence—not direct regulatory proof.</p></CardContent></Card>
    </section>

    <section className="grid gap-5 2xl:grid-cols-[0.82fr_1.18fr]">
      <Card className="rounded-lg shadow-none"><CardHeader className="flex-row items-center justify-between space-y-0 pb-3"><CardTitle className="flex items-center gap-2 text-sm"><GitBranch className="h-4 w-4 text-violet-600" />Observed transition map</CardTitle><Badge variant="outline" className="text-[10px]">{data.transition_map?.status || "unavailable"}</Badge></CardHeader><CardContent>
        {transitions.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">{data.transition_map?.reason || "No quality-gated transition was available."}</p> : <div className="max-h-[285px] space-y-2 overflow-y-auto pr-1">{transitions.slice(0, 40).map((transition, index) => <div key={`${transition.kind}-${index}`} className="flex items-center gap-2 border-b border-border/60 py-2 text-xs"><Badge variant="outline" className="min-w-20 justify-center text-[10px] capitalize">{humanize(transition.transition_type)}</Badge><div className="min-w-0 flex-1"><p className="truncate font-mono text-[11px]">{transition.site_a && transition.site_b ? `${transition.site_a} + ${transition.site_b}` : transition.site_key}</p><p className="mt-0.5 flex items-center gap-1 text-muted-foreground"><Clock3 className="h-3 w-3" />{transition.from_window}<ArrowRight className="h-3 w-3" />{transition.to_window}</p></div></div>)}</div>}
        <p className="mt-3 text-[10px] leading-relaxed text-muted-foreground">Edges record changes in observed active membership only. They do not identify a switching kinase or causal cascade arrow.</p>
      </CardContent></Card>

      <Card className="rounded-lg shadow-none"><CardHeader className="pb-3"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><CardTitle className="flex items-center gap-2 text-sm"><CircleDot className="h-4 w-4 text-amber-600" />Quality-gated site explorer</CardTitle><div className="flex gap-2"><Select value={qualityFilter} onValueChange={setQualityFilter}><SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="eligible">Eligible only</SelectItem><SelectItem value="all">All sites</SelectItem><SelectItem value="audit">Needs audit</SelectItem></SelectContent></Select><Button variant="outline" size="sm" className="h-8" onClick={() => { setPatternFilter("all"); setQualityFilter("eligible"); }}>Reset</Button></div></div></CardHeader><CardContent><div className="grid max-h-[310px] gap-2 overflow-y-auto pr-1 md:grid-cols-2">{visibleSites.map((site) => <button key={site.site_key} type="button" onClick={() => setSelectedKey(site.site_key)} className={cn("group flex items-start justify-between gap-3 border px-3 py-3 text-left transition-colors", selected?.site_key === site.site_key ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50")}><div className="min-w-0"><div className="flex items-center gap-2"><span className="font-mono text-sm font-semibold">{site.gene} {site.position}</span><ChevronRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5" /></div><div className="mt-1.5 flex flex-wrap gap-1.5"><PatternBadge pattern={site.primary_pattern} /><QualityBadge site={site} /></div><p className="mt-1.5 text-[11px] text-muted-foreground">onset {site.onset_minutes ?? "—"} min · peak {site.peak_minutes ?? "—"} min · {site.site_form_count || 0} form(s)</p></div></button>)}</div></CardContent></Card>
    </section>

    {selected && <section className="border border-primary/25 bg-card"><div className="grid gap-0 xl:grid-cols-[1.25fr_0.75fr]"><div className="min-w-0 p-5"><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex items-center gap-2"><h3 className="font-mono text-lg font-semibold">{selected.gene} {selected.position}</h3><PatternBadge pattern={selected.primary_pattern} /><QualityBadge site={selected} /></div><p className="mt-1 text-xs text-muted-foreground">Claim <span className="font-mono">{selected.claim_id || "unavailable"}</span></p></div><Select value={yMode} onValueChange={setYMode}><SelectTrigger className="h-8 w-36 text-xs"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="auto">Y: data range</SelectItem><SelectItem value="symmetric">Y: symmetric</SelectItem></SelectContent></Select></div>
        <div className="mt-5 h-[300px] w-full"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartData} margin={{ top: 12, right: 18, bottom: 4, left: -18 }}><CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.12} /><XAxis dataKey="label" tick={{ fontSize: 11 }} /><YAxis domain={yDomain} tick={{ fontSize: 11 }} /><Tooltip contentStyle={{ borderRadius: 6, fontSize: 12 }} /><Legend wrapperStyle={{ fontSize: 11 }} /><Line type="monotone" dataKey="aggregate" name="site aggregate (median form)" stroke="#111827" strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} />{(selected.form_profiles || []).map((form, index) => <Line key={form.site_form_key || index} type="monotone" dataKey={`form_${index}`} name={`form ${index + 1}`} stroke={FORM_COLORS[index % FORM_COLORS.length]} strokeWidth={1.6} strokeDasharray="4 3" dot={{ r: 2 }} connectNulls={false} />)}</LineChart></ResponsiveContainer></div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4"><Metric label="Onset" value={selected.onset_minutes == null ? "—" : `${selected.onset_minutes} min`} /><Metric label="Peak" value={selected.peak_minutes == null ? "—" : `${selected.peak_minutes} min`} /><Metric label="LOTO" value={selected.loto_pattern_stability == null ? "not run" : selected.loto_pattern_stability.toFixed(2)} /><Metric label="Q coverage" value={selected.qvalue_coverage == null ? "not available" : `${Math.round(selected.qvalue_coverage * 100)}%`} /></div>
        {!selected.atlas_eligible && <div className="mt-4 flex gap-2 border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200"><AlertTriangle className="h-4 w-4 shrink-0" /><span>Excluded from high-confidence narrative: {(selected.atlas_eligibility_reasons || []).join(", ")}</span></div>}
      </div>
      <aside className="border-t border-border bg-muted/20 p-5 xl:border-l xl:border-t-0"><h4 className="flex items-center gap-2 text-sm font-semibold"><Network className="h-4 w-4 text-primary" />Context evidence</h4><p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">Persisted annotations are shown without causal upgrade.</p><div className="mt-4 space-y-4">
        <div><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Form provenance</p><div className="mt-1.5 space-y-1.5">{(selected.form_profiles || []).map((form, index) => <div key={form.site_form_key || index} className="border bg-background px-2.5 py-2 text-[11px]"><p className="font-mono">{form.modified_sequence || form.precursor_id || `form ${index + 1}`}{form.precursor_charge ? ` / z${form.precursor_charge}` : ""}</p><p className="mt-0.5 text-muted-foreground">{humanize(form.primary_pattern)} · {form.atlas_eligible ? "eligible" : "needs audit"}</p></div>)}</div></div>
        <div><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Kinase / self-PTM</p><div className="mt-1.5 space-y-1.5">{[...(selected.context_evidence?.self_ptm_candidates || []), ...(selected.context_evidence?.kinase_context || [])].length ? [...(selected.context_evidence?.self_ptm_candidates || []), ...(selected.context_evidence?.kinase_context || [])].map((item, index) => <div key={index} className="border bg-background px-2.5 py-2 text-[11px]"><span className="font-medium">{item.kinase || "candidate kinase"}</span><span className="text-muted-foreground"> · {item.site || item.evidence_type || item.relationship || "persisted context"}</span></div>) : <p className="text-xs text-muted-foreground">No persisted kinase or self-PTM context.</p>}</div></div>
        <div><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Nuclear / non-PTM follow-through</p><div className="mt-1.5 space-y-1.5">{selected.context_evidence?.nuclear_context?.nucleus_annotated && <div className="border bg-background px-2.5 py-2 text-[11px]">Nucleus annotation available</div>}{(selected.context_evidence?.non_ptm_follow_through || []).map((item, index) => <div key={index} className="border bg-background px-2.5 py-2 text-[11px]"><span className="font-medium">{item.gene || "non-PTM protein"}</span><span className="text-muted-foreground"> · {item.evidence_type || "persisted follow-through"}</span></div>)}{!selected.context_evidence?.nuclear_context?.nucleus_annotated && !(selected.context_evidence?.non_ptm_follow_through || []).length && <p className="text-xs text-muted-foreground">No persisted nuclear or non-PTM context.</p>}</div></div>
        <div className="border-l-2 border-primary/50 bg-primary/5 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground"><Sparkles className="mr-1 inline h-3.5 w-3.5 text-primary" />This panel supports temporal interpretation but does not establish direct kinase-site regulation, causal propagation, or cellular localization change.</div>
      </div></aside></div></section>}
  </div>;
}
