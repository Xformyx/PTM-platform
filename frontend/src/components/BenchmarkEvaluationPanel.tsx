/**
 * Design: evidence-first benchmark control surface. It exposes only neutral
 * lineage categories and immutable run provenance; source treatment, cell-line,
 * research questions, RAG and locked truth are intentionally not rendered.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Download, FlaskConical, Loader2, LockKeyhole, Play, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { BenchmarkFigure2, type Figure2Source } from "@/components/BenchmarkFigure2";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type BenchmarkRun = {
  id: number;
  run_code: string;
  benchmark_order_id?: number | null;
  dataset_id: string;
  status: string;
  phase?: string;
  tmm_job?: "running" | "interrupted" | null;
  execution?: {
    stage?: string;
    label?: string;
    detail?: string;
    heartbeat_at_utc?: string | null;
    step_index?: number;
    step_count?: number;
    snapshot_progress_pct?: number;
  };
  production_contract: { id?: string; temporal_contract?: string };
  blind_context: { cell_context?: { lineage_class?: string } };
  score_summary?: Record<string, unknown> | null;
  figure2?: Figure2Source | null;
  bundle_files?: string[];
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  child_order?: {
    id: number;
    order_code: string;
    status: string;
    progress_pct: number;
    current_stage?: string | null;
    error_message?: string | null;
  } | null;
};

type Preflight = {
  eligible: boolean;
  issues: string[];
  dataset_id: string;
  production_contract: { id?: string; temporal_contract?: string };
  blind_policy: { rag_policy?: string };
  lineage_options: string[];
};

const LINEAGE_LABELS: Record<string, string> = {
  fibroblast_like: "Fibroblast-like cells",
  epithelial_like: "Epithelial-like cells",
  immune_like: "Immune-like cells",
  muscle_like: "Muscle-like cells",
  neuronal_like: "Neuronal-like cells",
  other_cultured_cells: "Other cultured cells",
};

const ACTIVE = new Set(["registered", "snapshot_pending", "preprocessing", "temporal_analysis", "scoring_queued", "scoring"]);
const CHILD_ACTIVE = new Set(["queued", "preprocessing"]);

function isLive(run: BenchmarkRun): boolean {
  return Boolean(run.child_order && CHILD_ACTIVE.has(run.child_order.status))
    || ["temporal_analysis", "scoring_queued", "scoring"].includes(run.status);
}

function isReadyForTmm(run: BenchmarkRun): boolean {
  return run.phase === "ready_for_tmm" || (run.child_order?.status === "completed" && run.status === "preprocessing");
}

function isStaleTmm(run: BenchmarkRun): boolean {
  if (run.tmm_job === "running") return false;
  if (run.tmm_job === "interrupted") return true;
  return run.child_order?.status === "completed"
    && (run.status === "temporal_analysis" || run.phase === "temporal_analysis");
}

function canStartTmm(run: BenchmarkRun): boolean {
  return isReadyForTmm(run) || isStaleTmm(run);
}

function isLeftover(run: BenchmarkRun): boolean {
  return run.phase === "abandoned" || run.status === "cancelled" || (run.status === "failed" && run.child_order?.status === "cancelled");
}

function runTone(run: BenchmarkRun): string {
  if (run.status === "completed" || isReadyForTmm(run)) return "bg-emerald-100 text-emerald-700 border-emerald-200";
  if (run.status === "failed" || run.status === "cancelled" || isLeftover(run)) return "bg-red-100 text-red-700 border-red-200";
  if (isLive(run) || ACTIVE.has(run.status)) return "bg-sky-100 text-sky-700 border-sky-200";
  return "bg-muted text-muted-foreground";
}

function runLabel(run: BenchmarkRun): string {
  if (isReadyForTmm(run)) return "ready for TMM";
  if (isLeftover(run)) return "abandoned";
  if (isStaleTmm(run)) return "TMM interrupted";
  if (run.status === "temporal_analysis" || run.phase === "temporal_analysis") return "TMM running";
  if (run.phase === "snapshot_running") return (run.child_order?.status || run.status).replace(/_/g, " ");
  return run.status.replace(/_/g, " ");
}

function metricLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (char: string) => char.toUpperCase());
}

function formattedMetric(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value >= 0 && value <= 1 ? `${(value * 100).toFixed(1)}%` : value.toFixed(3);
}

function figure2FromRun(run: BenchmarkRun): Figure2Source | null {
  if (run.figure2 && typeof run.figure2 === "object") return run.figure2;
  const nested = run.score_summary?.figure2;
  return nested && typeof nested === "object" ? nested as Figure2Source : null;
}

const EXECUTION_STEPS = ["Blind snapshot", "TMM full temporal", "Locked scoring", "Figures + data"];

function heartbeatText(value?: string | null): string | null {
  if (!value) return null;
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? null : timestamp.toLocaleTimeString();
}

function RunCard({
  run,
  readOnly,
  submitting,
  leftover,
  scoreMetrics,
  onTemporal,
  onRetry,
  onDownload,
}: {
  run: BenchmarkRun;
  readOnly: boolean;
  submitting: boolean;
  leftover?: boolean;
  scoreMetrics: [string, unknown][];
  onTemporal: () => void;
  onRetry: () => void;
  onDownload: (path: string) => void;
}) {
  const ready = isReadyForTmm(run);
  const staleTmm = isStaleTmm(run);
  const execution = run.execution;
  const currentStep = execution?.step_index ?? 0;
  return (
    <div className={`border rounded-lg p-4 space-y-3 ${leftover ? "bg-muted/30" : ""}`}>
      <div className="flex flex-wrap justify-between items-start gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium">{run.run_code}</span>
            <Badge variant="outline" className={runTone(run)}>{runLabel(run)}</Badge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {run.dataset_id} · {run.production_contract?.id || "tmm_full_temporal"} · lineage: {LINEAGE_LABELS[run.blind_context?.cell_context?.lineage_class || ""] || "controlled"}
            {run.child_order ? ` · snapshot ${run.child_order.status.replace(/_/g, " ")}` : ""}
          </p>
        </div>
        {canStartTmm(run) && !readOnly && (
          <Button type="button" size="sm" variant="outline" disabled={submitting} onClick={onTemporal} className="gap-1"><FlaskConical className="h-3.5 w-3.5" /> {staleTmm ? "Retry TMM + locked score" : "Run TMM + locked score"}</Button>
        )}
        {run.status === "failed" && !ready && !leftover && !readOnly && (
          <Button size="sm" variant="outline" disabled={submitting} onClick={onRetry} className="gap-1"><RefreshCw className="h-3.5 w-3.5" /> Retry preprocessing</Button>
        )}
      </div>
      {isLive(run) && (
        <div className="rounded-md border bg-muted/20 px-3 py-2 space-y-2" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-medium text-sky-700 dark:text-sky-300">{execution?.label || "Benchmark stage in progress"}</span>
            {heartbeatText(execution?.heartbeat_at_utc) && <span className="text-muted-foreground">Worker heartbeat {heartbeatText(execution?.heartbeat_at_utc)}</span>}
          </div>
          <p className="text-xs text-muted-foreground">{execution?.detail || "Status updates are derived from the durable worker state."}</p>
          <div className="grid grid-cols-2 gap-1 sm:grid-cols-4">
            {EXECUTION_STEPS.map((label, index) => {
              const step = index + 1;
              const active = step === currentStep;
              const complete = step < currentStep || run.status === "completed";
              return <div key={label} className={`rounded px-2 py-1 text-[10px] ${complete ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-200" : active ? "bg-sky-100 text-sky-800 dark:bg-sky-950/60 dark:text-sky-200" : "bg-muted text-muted-foreground"}`}>{complete ? "✓ " : active ? "• " : "○ "}{label}</div>;
            })}
          </div>
          {execution?.stage === "snapshot" && typeof execution.snapshot_progress_pct === "number" && <p className="text-[10px] text-muted-foreground">Snapshot preprocessing: {execution.snapshot_progress_pct.toFixed(0)}%</p>}
        </div>
      )}
      {run.phase === "snapshot_running" && run.child_order && CHILD_ACTIVE.has(run.child_order.status) && run.child_order.status !== "preprocessing" && run.child_order.status !== "queued" && (
        <p className="text-xs text-amber-700">This leftover snapshot is still finishing an Order-list restart ({run.child_order.status.replace(/_/g, " ")}). Locked scoring uses 0층 outputs only.</p>
      )}
      {ready && <p className="text-xs text-emerald-700">0층 snapshot is ready. This is the run to score — do not start another blind benchmark.</p>}
      {staleTmm && (
        <p className="text-xs text-amber-700">The last TMM accept did not finish. Click Retry TMM + locked score — do not start another blind benchmark.</p>
      )}
      {run.tmm_job === "running" && (
        <p className="text-xs text-sky-700">TMM is running on the durable benchmark worker. The stage tracker is qualitative: it does not imply that a solver call is percentage-complete.</p>
      )}
      {run.status === "completed" && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {scoreMetrics.length ? scoreMetrics.map(([key, value]) => <div key={key} className="rounded bg-muted/60 px-3 py-2"><p className="text-[10px] uppercase text-muted-foreground">{metricLabel(key)}</p><p className="font-mono text-sm font-semibold">{formattedMetric(value)}</p></div>) : <p className="text-sm text-muted-foreground">Score bundle completed. Detailed figures and source data are available in the result bundle.</p>}
          </div>
          {figure2FromRun(run) && <BenchmarkFigure2 figure2={figure2FromRun(run)!} />}
          <div className="rounded border bg-muted/30 p-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium">Paper figures and source data</p>
                <p className="text-xs text-muted-foreground">This strict-primary run emits Figure 1–4 only. Figure 5 and later require an inhibitor/perturbation set and are intentionally excluded.</p>
              </div>
              {(run.bundle_files || []).includes("benchmark_source_data.zip") && <Button size="sm" variant="outline" onClick={() => onDownload("benchmark_source_data.zip")}><Download className="mr-1 h-3.5 w-3.5" />Source data ZIP</Button>}
            </div>
            <div className="flex flex-wrap gap-2">
              {[1, 2, 3, 4].map((number) => {
                const file = `figures/Fig${number}.svg`;
                return (run.bundle_files || []).includes(file) ? <Button key={file} size="sm" variant="secondary" onClick={() => onDownload(file)}><Download className="mr-1 h-3.5 w-3.5" />Figure {number} SVG</Button> : null;
              })}
            </div>
          </div>
        </div>
      )}
      {run.error_message && !ready && <p className="text-xs text-destructive">{run.error_message}</p>}
    </div>
  );
}

export function BenchmarkEvaluationPanel({ orderId, readOnly }: { orderId: number; readOnly: boolean }) {
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [lineage, setLineage] = useState("other_cultured_cells");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pollWarning, setPollWarning] = useState<string | null>(null);
  const [pollDelayMs, setPollDelayMs] = useState(5000);

  const refresh = useCallback(async (background = false) => {
    try {
      const response = await api.get<{ runs: BenchmarkRun[] }>(`/benchmarks/source-orders/${orderId}/runs`);
      setRuns(response.runs);
      setPollWarning(null);
      setPollDelayMs(5000);
    } catch (error: any) {
      if (background) {
        setPollWarning("Status API is temporarily unavailable. The last known BenchmarkRun state is retained and polling will retry automatically.");
        setPollDelayMs((delay) => Math.min(delay * 2, 30000));
      } else {
        setMessage(error?.message || "Could not load benchmark runs.");
      }
    } finally {
      setLoading(false);
    }
  }, [orderId]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!runs.some(isLive)) return;
    const timer = window.setTimeout(() => void refresh(true), pollDelayMs);
    return () => window.clearTimeout(timer);
  }, [runs, refresh, pollDelayMs]);

  const latest = runs[0];
  const currentRuns = useMemo(() => runs.filter((run) => !isLeftover(run)), [runs]);
  const leftoverRuns = useMemo(() => runs.filter(isLeftover), [runs]);
  const scoreMetrics = useMemo(() => {
    if (!latest?.score_summary || typeof latest.score_summary !== "object") return [];
    return Object.entries(latest.score_summary).filter(([, value]) => typeof value === "number");
  }, [latest]);

  const openPreflight = async () => {
    setMessage(null);
    setSubmitting(true);
    try {
      const response = await api.get<Preflight>(`/benchmarks/source-orders/${orderId}/preflight`);
      setPreflight(response);
      setLineage(response.lineage_options.includes(lineage) ? lineage : response.lineage_options[0] || "other_cultured_cells");
      setDialogOpen(true);
    } catch (error: any) {
      setMessage(error?.message || "Benchmark preflight failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const createAndStart = async () => {
    setSubmitting(true);
    setMessage(null);
    try {
      const latest = runs[0];
      if (latest && isLive(latest)) {
        setDialogOpen(false);
        setMessage("A blind benchmark run is already in progress for this Order.");
        await refresh();
        return;
      }
      if (latest && isReadyForTmm(latest)) {
        setDialogOpen(false);
        setMessage("A 0층 snapshot is already ready. Use Run TMM + locked score on that run.");
        await refresh();
        return;
      }
      let runId = latest && latest.status === "failed" && !isLeftover(latest) ? latest.id : null;
      if (runId == null) {
        const run = await api.post<BenchmarkRun>(`/benchmarks/source-orders/${orderId}/runs`, {
          dataset_id: "insulin_signaling_v1",
          lineage_class: lineage,
        });
        runId = run.id;
      }
      await api.post(`/benchmarks/runs/${runId}/start`);
      setDialogOpen(false);
      await refresh();
    } catch (error: any) {
      setMessage(error?.message || "Could not create the blind benchmark run.");
      await refresh();
    } finally {
      setSubmitting(false);
    }
  };

  const retryStart = async (runId: number) => {
    setSubmitting(true);
    setMessage(null);
    try {
      await api.post(`/benchmarks/runs/${runId}/start`);
      await refresh();
    } catch (error: any) {
      setMessage(error?.message || "Could not restart the blind benchmark run.");
      await refresh();
    } finally {
      setSubmitting(false);
    }
  };

  const runTemporalAndScore = async (runId: number) => {
    setSubmitting(true);
    setMessage(null);
    setNotice(null);
    try {
      await api.post(`/benchmarks/runs/${runId}/run-temporal-analysis`, {});
      setNotice("TMM was accepted and started. The badge should change to TMM running. Wait here — do not start another benchmark.");
      await refresh();
    } catch (error: any) {
      const text = String(error?.message || "");
      if (/\b524\b/.test(text) || /timeout/i.test(text)) {
        setMessage("The gateway timed out. TMM is a long job — Refresh in a minute. If the badge says TMM running, wait; do not start another benchmark.");
      } else {
        setMessage(text || "Blind preprocessing may still be running. Try again after it completes.");
      }
      await refresh();
    } finally {
      setSubmitting(false);
    }
  };

  const downloadBundle = async (runId: number, path: string) => {
    setMessage(null);
    try {
      const filename = path.split("/").pop() || "benchmark_bundle_file";
      await api.downloadFile(`/benchmarks/runs/${runId}/bundle/${path}`, filename);
    } catch (error: any) {
      setMessage(error?.message || "Could not download benchmark output.");
    }
  };

  return (
    <div className="space-y-4">
      <Card className="border-sky-200/70 dark:border-sky-900/70">
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-base"><FlaskConical className="h-4 w-4 text-sky-600" /> Benchmark Evaluation</CardTitle>
              <CardDescription>
                Runs a separate strict-primary snapshot. The source Order, its report, and its research context are never modified.
              </CardDescription>
            </div>
            <Button onClick={openPreflight} disabled={readOnly || submitting} className="gap-2">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Start Blind Benchmark
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3 text-sm">
          <div className="flex gap-2"><LockKeyhole className="h-4 w-4 mt-0.5 text-sky-600" /><span><strong>Masked:</strong> treatment, source cell-line, transgene, research question, project/order/file labels.</span></div>
          <div className="flex gap-2"><ShieldCheck className="h-4 w-4 mt-0.5 text-emerald-600" /><span><strong>Preserved:</strong> matrix values, time axis, replicate structure, FASTA and lineage class.</span></div>
          <div className="flex gap-2"><FlaskConical className="h-4 w-4 mt-0.5 text-violet-600" /><span><strong>Contract:</strong> 0층 preprocessing + 1층 TMM full temporal; RAG/LLM/representation excluded.</span></div>
        </CardContent>
      </Card>

      {notice && <Alert><CheckCircle2 className="h-4 w-4" /><AlertTitle>TMM started</AlertTitle><AlertDescription>{notice}</AlertDescription></Alert>}
      {message && <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertTitle>Benchmark action needs attention</AlertTitle><AlertDescription>{message}</AlertDescription></Alert>}
      {pollWarning && <Alert><RefreshCw className="h-4 w-4" /><AlertTitle>Reconnecting to benchmark status</AlertTitle><AlertDescription>{pollWarning}</AlertDescription></Alert>}

      <Card>
        <CardHeader className="flex-row items-center justify-between pb-3">
          <div><CardTitle className="text-sm">Benchmark Runs</CardTitle><CardDescription>Each Start created a history row. Child snapshot Orders stay hidden from the Order list.</CardDescription></div>
          <Button variant="ghost" size="sm" onClick={() => void refresh()} className="gap-1"><RefreshCw className="h-3.5 w-3.5" /> Refresh</Button>
        </CardHeader>
        <CardContent>
          {loading ? <div className="py-8 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div> : runs.length === 0 ? (
            <p className="py-6 text-sm text-muted-foreground">No blind benchmark run has been registered for this Order.</p>
          ) : (
            <div className="space-y-3">
              {currentRuns.map((run) => (
                <RunCard
                  key={run.id}
                  run={run}
                  readOnly={readOnly}
                  submitting={submitting}
                  scoreMetrics={scoreMetrics}
                  onTemporal={() => void runTemporalAndScore(run.id)}
                  onRetry={() => void retryStart(run.id)}
                  onDownload={(path) => void downloadBundle(run.id, path)}
                />
              ))}
              {leftoverRuns.length > 0 && (
                <details className="rounded-lg border border-dashed px-4 py-3">
                  <summary className="cursor-pointer text-sm text-muted-foreground">Previous attempts ({leftoverRuns.length}) — cancelled or failed leftovers</summary>
                  <div className="mt-3 space-y-3">
                    {leftoverRuns.map((run) => (
                      <RunCard
                        key={run.id}
                        run={run}
                        readOnly={readOnly}
                        submitting={submitting}
                        scoreMetrics={scoreMetrics}
                        leftover
                        onTemporal={() => void runTemporalAndScore(run.id)}
                        onRetry={() => void retryStart(run.id)}
                        onDownload={(path) => void downloadBundle(run.id, path)}
                      />
                    ))}
                  </div>
                </details>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader><DialogTitle>Lock a strict blind benchmark snapshot</DialogTitle><DialogDescription>Only a neutral cell lineage is allowed. This action does not edit the original Order.</DialogDescription></DialogHeader>
          {preflight && <div className="space-y-4 py-2">
            {preflight.issues.length > 0 ? <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertTitle>Not eligible</AlertTitle><AlertDescription>{preflight.issues.join(" · ")}</AlertDescription></Alert> : <Alert><ShieldCheck className="h-4 w-4" /><AlertTitle>Blind policy verified</AlertTitle><AlertDescription>RAG and report generation are disabled. The scorer receives locked truth only after the 0층+1층 artifact is archived.</AlertDescription></Alert>}
            <div className="space-y-2"><Label>Cell lineage context</Label><Select value={lineage} onValueChange={setLineage}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{preflight.lineage_options.map((option) => <SelectItem key={option} value={option}>{LINEAGE_LABELS[option] || option}</SelectItem>)}</SelectContent></Select><p className="text-xs text-muted-foreground">Exact cell-line, engineering/transgene, disease label, stimulus and biological question are not sent to the blind run.</p></div>
          </div>}
          <DialogFooter><Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button><Button onClick={createAndStart} disabled={submitting || !preflight?.eligible}>{submitting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}Lock snapshot and start</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
