/**
 * Design: evidence-first benchmark control surface. It exposes only neutral
 * lineage categories and immutable run provenance; source treatment, cell-line,
 * research questions, RAG and locked truth are intentionally not rendered.
 */
import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, FlaskConical, Loader2, LockKeyhole, Play, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type BenchmarkRun = {
  id: number;
  run_code: string;
  benchmark_order_id?: number | null;
  dataset_id: string;
  status: string;
  production_contract: { id?: string; temporal_contract?: string };
  blind_context: { cell_context?: { lineage_class?: string } };
  score_summary?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at?: string | null;
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

function runTone(status: string): string {
  if (status === "completed") return "bg-emerald-100 text-emerald-700 border-emerald-200";
  if (status === "failed") return "bg-red-100 text-red-700 border-red-200";
  if (ACTIVE.has(status)) return "bg-sky-100 text-sky-700 border-sky-200";
  return "bg-muted text-muted-foreground";
}

function metricLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (char: string) => char.toUpperCase());
}

function formattedMetric(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value >= 0 && value <= 1 ? `${(value * 100).toFixed(1)}%` : value.toFixed(3);
}

export function BenchmarkEvaluationPanel({ orderId, readOnly }: { orderId: number; readOnly: boolean }) {
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [lineage, setLineage] = useState("other_cultured_cells");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const response = await api.get<{ runs: BenchmarkRun[] }>(`/benchmarks/source-orders/${orderId}/runs`);
      setRuns(response.runs);
    } catch (error: any) {
      setMessage(error?.message || "Could not load benchmark runs.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, [orderId]);
  useEffect(() => {
    if (!runs.some((run) => ACTIVE.has(run.status))) return;
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [runs]);

  const latest = runs[0];
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
      const run = await api.post<BenchmarkRun>(`/benchmarks/source-orders/${orderId}/runs`, {
        dataset_id: "insulin_signaling_v1",
        lineage_class: lineage,
      });
      await api.post(`/benchmarks/runs/${run.id}/start`);
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
    try {
      await api.post(`/benchmarks/runs/${runId}/run-temporal-analysis`);
      await refresh();
    } catch (error: any) {
      setMessage(error?.message || "Blind preprocessing may still be running. Try again after it completes.");
    } finally {
      setSubmitting(false);
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

      {message && <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertTitle>Benchmark action needs attention</AlertTitle><AlertDescription>{message}</AlertDescription></Alert>}

      <Card>
        <CardHeader className="flex-row items-center justify-between pb-3">
          <div><CardTitle className="text-sm">Benchmark Runs</CardTitle><CardDescription>Immutable source snapshot and offline locked-scoring status.</CardDescription></div>
          <Button variant="ghost" size="sm" onClick={() => void refresh()} className="gap-1"><RefreshCw className="h-3.5 w-3.5" /> Refresh</Button>
        </CardHeader>
        <CardContent>
          {loading ? <div className="py-8 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div> : runs.length === 0 ? (
            <p className="py-6 text-sm text-muted-foreground">No blind benchmark run has been registered for this Order.</p>
          ) : (
            <div className="space-y-3">
              {runs.map((run) => (
                <div key={run.id} className="border rounded-lg p-4 space-y-3">
                  <div className="flex flex-wrap justify-between items-start gap-2">
                    <div>
                      <div className="flex items-center gap-2"><span className="font-mono text-sm font-medium">{run.run_code}</span><Badge variant="outline" className={runTone(run.status)}>{run.status.replace(/_/g, " ")}</Badge></div>
                      <p className="mt-1 text-xs text-muted-foreground">{run.dataset_id} · {run.production_contract?.id || "tmm_full_temporal"} · lineage: {LINEAGE_LABELS[run.blind_context?.cell_context?.lineage_class || ""] || "controlled"}</p>
                    </div>
                    {run.status === "preprocessing" && !readOnly && (
                      <Button size="sm" variant="outline" disabled={submitting} onClick={() => void runTemporalAndScore(run.id)} className="gap-1"><FlaskConical className="h-3.5 w-3.5" /> Run TMM + locked score</Button>
                    )}
                    {run.status === "failed" && !readOnly && (
                      <Button size="sm" variant="outline" disabled={submitting} onClick={() => void retryStart(run.id)} className="gap-1"><RefreshCw className="h-3.5 w-3.5" /> Retry preprocessing</Button>
                    )}
                  </div>
                  {ACTIVE.has(run.status) && <Progress value={run.status === "preprocessing" ? 35 : run.status === "temporal_analysis" ? 65 : 80} className="h-1.5" />}
                  {run.status === "completed" && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      {scoreMetrics.length ? scoreMetrics.map(([key, value]) => <div key={key} className="rounded bg-muted/60 px-3 py-2"><p className="text-[10px] uppercase text-muted-foreground">{metricLabel(key)}</p><p className="font-mono text-sm font-semibold">{formattedMetric(value)}</p></div>) : <p className="text-sm text-muted-foreground">Score bundle completed. Detailed figures and source data are available in the result bundle.</p>}
                    </div>
                  )}
                  {run.error_message && <p className="text-xs text-destructive">{run.error_message}</p>}
                </div>
              ))}
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
