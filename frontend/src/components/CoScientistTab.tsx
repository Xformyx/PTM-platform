/**
 * CoScientistTab — Hypothesis generation & experiment design via PTM-CoScientist.
 *
 * Proxies requests through the PTM-platform API server
 * (/api/orders/{id}/coscientist/*) to the Co-Scientist service.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  FlaskConical,
  Lightbulb,
  RefreshCw,
  MessageSquare,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Dna,
  Swords,
  Sparkles,
  Send,
  ArrowRight,
  BookOpen,
  Microscope,
  Cpu,
  StopCircle,
  History,
  Clock,
} from "lucide-react";
import { Input } from "@/components/ui/input";

// ─── Types ────────────────────────────────────────────────────────────────────

interface HealthResponse {
  status: string;
  checks: {
    chromadb: {
      reachable: boolean;
      collections: string[];
      collection_count: number;
    };
    ptm_artifacts: {
      accessible: boolean;
      sample_orders: string[];
    };
  };
}

interface EvidenceItem {
  source?: string;
  text?: string;
  title?: string;
  excerpt?: string;
}

function evidenceTitle(ev: EvidenceItem): string {
  return ev.title || ev.source || "Unknown";
}

function evidenceExcerpt(ev: EvidenceItem): string {
  return ev.excerpt || ev.text || "";
}

interface Hypothesis {
  id: string;
  condition: string;
  prediction: string;
  mechanism: string;
  category: string;
  elo_rating: number;
  confidence: number;
  status: string;
  signaling_chain: string;
  supporting_ptms: string[];
  evidence_for: EvidenceItem[];
  evidence_against: EvidenceItem[];
  testable_prediction: string;
}

interface ExperimentDesign {
  title: string;
  objective: string;
  approach: string;
  expected_outcome: string;
  estimated_timeline: string;
  priority: string;
}

interface SessionResponse {
  session_id: string;
  status: string;
  iteration: number;
  total_hypotheses: number;
  top_hypotheses: Hypothesis[];
  experiment_designs: ExperimentDesign[];
  error?: string;
}

interface SessionMeta {
  session_id: string;
  status: string;
  created_at: string;
  order_codes: string[];
  total_hypotheses: number;
  iteration: number;
  research_goal: string;
  ptm_type: string;
}

// ─── Pipeline step visualization ──────────────────────────────────────────────

const CS_STEPS = [
  {
    label: "Generate",
    sub: "PTM context + ChromaDB",
    Icon: Lightbulb,
    color:
      "text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950 dark:border-blue-800",
  },
  {
    label: "Debate",
    sub: "Elo tournament",
    Icon: Swords,
    color:
      "text-orange-600 bg-orange-50 border-orange-200 dark:text-orange-400 dark:bg-orange-950 dark:border-orange-800",
  },
  {
    label: "Evolve",
    sub: "Refine top hypotheses",
    Icon: Sparkles,
    color:
      "text-emerald-600 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-950 dark:border-emerald-800",
  },
  {
    label: "Design",
    sub: "Experiment protocols",
    Icon: Microscope,
    color:
      "text-violet-600 bg-violet-50 border-violet-200 dark:text-violet-400 dark:bg-violet-950 dark:border-violet-800",
  },
] as const;

function PipelineSteps({ running, completed }: { running: boolean; completed: boolean }) {
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {CS_STEPS.map((step, i) => {
        const StepIcon = step.Icon;
        const isDone = completed;
        const isActive = running && i < 3;
        return (
          <div key={step.label} className="flex items-center gap-1">
            <div
              className={[
                "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-all",
                isDone
                  ? "text-emerald-600 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-950 dark:border-emerald-800"
                  : isActive
                  ? step.color + " opacity-100"
                  : step.color + " opacity-40",
              ].join(" ")}
            >
              {isActive && !isDone ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : isDone ? (
                <CheckCircle2 className="h-3 w-3" />
              ) : (
                <StepIcon className="h-3 w-3" />
              )}
              <span>{step.label}</span>
            </div>
            {i < CS_STEPS.length - 1 && (
              <ArrowRight className="h-3 w-3 text-muted-foreground shrink-0 opacity-40" />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Category badge colors ─────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  mechanistic: "bg-blue-500/10 text-blue-700 border-blue-500/20 dark:text-blue-400",
  temporal: "bg-orange-500/10 text-orange-700 border-orange-500/20 dark:text-orange-400",
  predictive: "bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-400",
  integrative: "bg-violet-500/10 text-violet-700 border-violet-500/20 dark:text-violet-400",
  therapeutic: "bg-rose-500/10 text-rose-700 border-rose-500/20 dark:text-rose-400",
};

// ─── Component ────────────────────────────────────────────────────────────────

interface Props {
  orderId: number;
  orderCode: string;
  orderStatus: string;
}

export function CoScientistTab({ orderId, orderCode, orderStatus }: Props) {
  const BASE = `/orders/${orderId}/coscientist`;

  // Health
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);

  // Form
  const [goal, setGoal] = useState("");
  const [researchMode, setResearchMode] = useState<"goal_led" | "data_guided" | "hybrid">("hybrid");
  const [maxIterations, setMaxIterations] = useState("3");
  const [selectedCollections, setSelectedCollections] = useState<string[]>([]);
  const [llmProvider, setLlmProvider] = useState("auto");
  const [llmModel, setLlmModel] = useState("");
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);

  // Session — sessionId persisted in localStorage so tab re-mount restores results
  const _storageKey = `coscientist_session_${orderId}`;
  const [sessionId, _setSessionId] = useState<string | null>(
    () => localStorage.getItem(_storageKey)
  );
  function setSessionId(id: string | null) {
    _setSessionId(id);
    if (id) localStorage.setItem(_storageKey, id);
    else localStorage.removeItem(_storageKey);
  }
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Feedback
  const [feedback, setFeedback] = useState("");
  const [feedbackType, setFeedbackType] = useState("direction");
  const [feedbackPending, setFeedbackPending] = useState(false);
  const [feedbackCount, setFeedbackCount] = useState(0);

  // Experiment designs
  const [designsLoading, setDesignsLoading] = useState(false);

  // Scientific reasoning / lab-in-the-loop
  const [reasoning, setReasoning] = useState<any>(null);
  const [labHypothesisId, setLabHypothesisId] = useState("");
  const [labOutcome, setLabOutcome] = useState("supports");
  const [labSummary, setLabSummary] = useState("");
  const [labPending, setLabPending] = useState(false);
  const [labResultCount, setLabResultCount] = useState(0);

  // Expanded row
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // History
  const [history, setHistory] = useState<SessionMeta[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── Health check on mount ────────────────────────────────────────────────
  useEffect(() => {
    api
      .get<HealthResponse>(`${BASE}/health`)
      .then(setHealth)
      .catch((e: any) => setHealthError(e.message ?? "Connection failed"))
      .finally(() => setHealthLoading(false));
  }, [BASE]);

  // ─── Restore session on mount if sessionId exists in localStorage ─────────
  useEffect(() => {
    if (!sessionId || session) return;
    api.get<SessionResponse>(`${BASE}/session/${sessionId}`)
      .then((data) => {
        setSession(data);
        if (data.status === "running" || data.status === "cancelling") {
          setRunning(true);
        }
      })
      .catch((e: any) => {
        if (String(e?.message).includes("404")) {
          // session expired — clear stored id
          setSessionId(null);
        }
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [BASE]);

  // ─── History loader ───────────────────────────────────────────────────────
  async function loadHistory() {
    setHistoryLoading(true);
    try {
      const data = await api.get<{ sessions: SessionMeta[] }>(`${BASE}/sessions`);
      setHistory(data.sessions ?? []);
    } catch { /* non-fatal */ }
    finally { setHistoryLoading(false); }
  }

  async function loadSessionFromHistory(sid: string) {
    try {
      const data = await api.get<SessionResponse>(`${BASE}/session/${sid}`);
      setSession(data);
      setSessionId(sid);
      setRunning(false);
      setHistoryOpen(false);
      setTimeout(() => {
        document.getElementById(`cs-results-${orderId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 150);
    } catch (e: any) {
      setRunError(`세션 로드 실패: ${e.message}`);
    }
  }

  // ─── Fetch Ollama model list for selector ─────────────────────────────────
  useEffect(() => {
    api
      .get<{ models: { name: string }[] }>("/llm/models")
      .then((res) => setOllamaModels((res.models ?? []).map((m) => m.name)))
      .catch(() => {/* non-fatal */});
  }, []);

  // ─── Poll session ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!sessionId || !running) return;
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.get<SessionResponse>(`${BASE}/session/${sessionId}`);
        setSession(data);
        if (data.status !== "running" && data.status !== "cancelling") {
          setRunning(false);
          clearInterval(pollRef.current!);
        }
      } catch (e: any) {
        // 404 = session gone (container restarted); stop polling
        if (e?.status === 404 || e?.response?.status === 404 || String(e?.message).includes("404")) {
          setRunning(false);
          setRunError("세션이 만료됐습니다. 다시 시작해주세요.");
          clearInterval(pollRef.current!);
        }
        // other errors: ignore (transient network issue)
      }
    }, 4000);
    return () => clearInterval(pollRef.current!);
  }, [sessionId, running, BASE]);

  useEffect(() => {
    if (!sessionId || running) return;
    if (session?.status !== "completed" && session?.status !== "cancelled") return;
    api
      .get(`${BASE}/session/${sessionId}/scientific-reasoning`)
      .then(setReasoning)
      .catch(() => setReasoning(null));
  }, [sessionId, running, session?.status, BASE]);

  // ─── Handlers ────────────────────────────────────────────────────────────

  async function handleRun() {
    setRunError(null);
    setSession(null);
    setRunning(true);
    setFeedbackCount(0);
    setLabResultCount(0);
    setReasoning(null);
    try {
      const res = await api.post<{ session_id: string }>(`${BASE}/run`, {
        research_goal: goal,
        research_mode: researchMode,
        max_iterations: parseInt(maxIterations),
        rag_collections: selectedCollections.length ? selectedCollections : null,
        llm_provider: llmProvider === "auto" ? "" : llmProvider,
        llm_model: llmModel.trim(),
      });
      setSessionId(res.session_id);
    } catch (e: any) {
      setRunError(e.message);
      setRunning(false);
    }
  }

  async function handleFeedback() {
    if (!sessionId || !feedback.trim()) return;
    setFeedbackPending(true);
    try {
      await api.post(`${BASE}/session/${sessionId}/feedback`, {
        feedback_type: feedbackType,
        content: feedback,
      });
      setFeedback("");
      setFeedbackCount((n) => n + 1);
    } catch (e: any) {
      setRunError(e.message);
    } finally {
      setFeedbackPending(false);
    }
  }

  async function handleRerun() {
    if (!sessionId) return;
    setRunError(null);
    setRunning(true);
    try {
      await api.post(`${BASE}/session/${sessionId}/rerun`);
    } catch (e: any) {
      setRunError(e.message);
      setRunning(false);
    }
  }

  async function handleCancel() {
    if (!sessionId || !running) return;
    try {
      await api.post(`${BASE}/session/${sessionId}/cancel`);
      // Optimistically reflect the cancelling state; poller will update to cancelled
      setSession((s) => s ? { ...s, status: "cancelling" } : s);
    } catch (e: any) {
      setRunError(`Stop failed: ${e.message}`);
    }
  }

  async function handleDesignExperiments() {
    if (!sessionId) return;
    setDesignsLoading(true);
    try {
      const res = await api.post<{ designs: ExperimentDesign[] }>(
        `${BASE}/session/${sessionId}/design-experiments?top_n=5`
      );
      setSession((s) => (s ? { ...s, experiment_designs: res.designs } : s));
    } catch (e: any) {
      setRunError(e.message);
    } finally {
      setDesignsLoading(false);
    }
  }

  async function handleLabResult() {
    const hypothesisId = labHypothesisId || session?.top_hypotheses[0]?.id;
    if (!sessionId || !hypothesisId) return;
    setLabPending(true);
    try {
      await api.post(`${BASE}/session/${sessionId}/lab-results`, {
        hypothesis_id: hypothesisId,
        outcome: labOutcome,
        result_summary: labSummary,
      });
      setLabSummary("");
      setLabResultCount((n) => n + 1);
      const next = await api.get(`${BASE}/session/${sessionId}/scientific-reasoning`);
      setReasoning(next);
    } catch (e: any) {
      setRunError(e.message);
    } finally {
      setLabPending(false);
    }
  }

  // ─── Derived state ────────────────────────────────────────────────────────

  const isCompleted = session?.status === "completed";
  // Show results for completed OR cancelled sessions that have hypotheses
  const hasResults = (isCompleted || session?.status === "cancelled") && (session?.top_hypotheses?.length ?? 0) > 0;
  const isSessionError = session?.status?.startsWith("error");
  const analysisReady = orderStatus === "completed";
  const collections = health?.checks?.chromadb?.collections ?? [];

  // ─── Loading ──────────────────────────────────────────────────────────────
  if (healthLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
    );
  }

  // ─── Service unavailable ─────────────────────────────────────────────────
  if (healthError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <FlaskConical className="h-12 w-12 mb-4 opacity-40" />
        <p className="text-lg font-medium">Co-Scientist unavailable</p>
        <p className="text-sm mt-1">{healthError}</p>
        <p className="text-xs mt-3 opacity-60">
          Ensure the <code className="font-mono">ptm-coscientist-api</code> container is running.
        </p>
      </div>
    );
  }

  // ─── Analysis not ready ────────────────────────────────────────────────
  if (!analysisReady) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <Dna className="h-12 w-12 mb-4 opacity-40" />
        <p className="text-lg font-medium">Analysis not complete</p>
        <p className="text-sm mt-1">
          Co-Scientist is available after the PTM analysis pipeline finishes.
        </p>
        <Badge variant="outline" className="mt-3 text-xs">
          Current status: {orderStatus}
        </Badge>
      </div>
    );
  }

  // ─── Main layout ──────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">

      {/* ── Service status bar ────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex items-center gap-1.5 cursor-default">
                {health?.checks.chromadb.reachable ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                ) : (
                  <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
                )}
                ChromaDB
                {health?.checks.chromadb.reachable && (
                  <span className="opacity-60">
                    ({health.checks.chromadb.collection_count} collections)
                  </span>
                )}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              {health?.checks.chromadb.reachable
                ? `Connected — ${health.checks.chromadb.collections.join(", ") || "no collections"}`
                : "ChromaDB not reachable"}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex items-center gap-1.5 cursor-default">
                {health?.checks.ptm_artifacts.accessible ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                ) : (
                  <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
                )}
                PTM Artifacts
              </span>
            </TooltipTrigger>
            <TooltipContent>
              {health?.checks.ptm_artifacts.accessible
                ? `Mounted — ${health.checks.ptm_artifacts.sample_orders.slice(0, 3).join(", ")}${health.checks.ptm_artifacts.sample_orders.length > 3 ? "…" : ""}`
                : "Artifact volume not accessible"}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      {/* ── Run config ─────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-md bg-violet-500/10">
                <FlaskConical className="h-3.5 w-3.5 text-violet-500" />
              </div>
              AI Research Studio
            </CardTitle>
            {/* LLM quick-pick — always visible in header */}
            <div className="flex items-center gap-1 shrink-0">
              <Cpu className="h-3 w-3 text-muted-foreground" />
              <Select
                value={llmProvider}
                onValueChange={(v) => { setLlmProvider(v); setLlmModel(""); }}
                disabled={running}
              >
                <SelectTrigger className="h-7 text-xs w-28 border-dashed">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto" className="text-xs">Auto</SelectItem>
                  <SelectItem value="ollama" className="text-xs">Ollama</SelectItem>
                  <SelectItem value="openai" className="text-xs">OpenAI</SelectItem>
                  <SelectItem value="gemini" className="text-xs">Gemini</SelectItem>
                </SelectContent>
              </Select>
              {llmProvider === "ollama" ? (
                <Select value={llmModel} onValueChange={setLlmModel} disabled={running}>
                  <SelectTrigger className="h-7 text-xs w-32 border-dashed">
                    <SelectValue placeholder={ollamaModels[0] ?? "model"} />
                  </SelectTrigger>
                  <SelectContent>
                    {ollamaModels.map((m) => (
                      <SelectItem key={m} value={m} className="text-xs font-mono">{m}</SelectItem>
                    ))}
                    {ollamaModels.length === 0 && (
                      <SelectItem value="" disabled className="text-xs text-muted-foreground">No models</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              ) : llmProvider === "openai" ? (
                <Select value={llmModel || "gpt-4.1-mini"} onValueChange={setLlmModel} disabled={running}>
                  <SelectTrigger className="h-7 text-xs w-28 border-dashed">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "o4-mini"].map((m) => (
                      <SelectItem key={m} value={m} className="text-xs font-mono">{m}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : llmProvider === "gemini" ? (
                <Select value={llmModel || "gemini-2.5-flash"} onValueChange={setLlmModel} disabled={running}>
                  <SelectTrigger className="h-7 text-xs w-36 border-dashed">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"].map((m) => (
                      <SelectItem key={m} value={m} className="text-xs font-mono">{m}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Pipeline flow */}
          <PipelineSteps running={running} completed={!!isCompleted} />

          <Separator />

          {/* LLM detail (expanded) — only when not auto */}
          <div className="space-y-2 rounded-md border border-dashed border-border/60 px-3 py-2.5">
            <Label className="text-xs text-muted-foreground flex items-center gap-1.5">
              <Cpu className="h-3 w-3" />
              LLM
            </Label>
            <div className="grid grid-cols-2 gap-2">
              <Select value={llmProvider} onValueChange={(v) => { setLlmProvider(v); setLlmModel(""); }} disabled={running}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto" className="text-xs">Auto (server default)</SelectItem>
                  <SelectItem value="ollama" className="text-xs">Ollama (local)</SelectItem>
                  <SelectItem value="openai" className="text-xs">OpenAI</SelectItem>
                  <SelectItem value="gemini" className="text-xs">Gemini</SelectItem>
                </SelectContent>
              </Select>

              {/* Model name — dropdown for Ollama, text input for others */}
              {llmProvider === "ollama" ? (
                <Select value={llmModel} onValueChange={setLlmModel} disabled={running}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder={ollamaModels[0] ?? "model name"} />
                  </SelectTrigger>
                  <SelectContent>
                    {ollamaModels.map((m) => (
                      <SelectItem key={m} value={m} className="text-xs font-mono">{m}</SelectItem>
                    ))}
                    {ollamaModels.length === 0 && (
                      <SelectItem value="" disabled className="text-xs text-muted-foreground">No models found</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              ) : llmProvider === "openai" ? (
                <Select value={llmModel || "gpt-4.1-mini"} onValueChange={setLlmModel} disabled={running}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "o4-mini"].map((m) => (
                      <SelectItem key={m} value={m} className="text-xs font-mono">{m}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : llmProvider === "gemini" ? (
                <Select value={llmModel || "gemini-2.5-flash"} onValueChange={setLlmModel} disabled={running}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"].map((m) => (
                      <SelectItem key={m} value={m} className="text-xs font-mono">{m}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  className="h-8 text-xs font-mono"
                  placeholder="server default"
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                  disabled={running}
                />
              )}
            </div>
            <p className="text-[10px] text-muted-foreground leading-tight">
              {llmProvider === "auto"
                ? "Ollama → OpenAI → Gemini 순으로 자동 선택"
                : llmProvider === "ollama"
                ? "로컬 Ollama — 속도 느림, API 비용 없음"
                : llmProvider === "openai"
                ? "OpenAI API — 빠르고 안정적, API 비용 발생"
                : "Gemini API — 빠르고 안정적, API 비용 발생"}
            </p>
          </div>

          {/* Research direction: goal stays primary; data-derived questions are optional seed context. */}
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Research Mode</Label>
            <Select value={researchMode} onValueChange={(value) => setResearchMode(value as typeof researchMode)} disabled={running}>
              <SelectTrigger className="h-9 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="goal_led" className="text-xs">Goal-led Research — 입력한 Research Goal 중심</SelectItem>
                <SelectItem value="data_guided" className="text-xs">Data-guided Research — Data-Grounded Analysis seed 중심</SelectItem>
                <SelectItem value="hybrid" className="text-xs">Hybrid Research — Research Goal + Data-Grounded seed</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[10px] text-muted-foreground leading-tight">
              {researchMode === "goal_led"
                ? "사용자가 정의한 질문을 중심으로 독립적인 Co-Scientist 연구를 수행합니다."
                : researchMode === "data_guided"
                ? "시간대별 kinase footprint, Temporal PTM Cluster, Local Co-membership Transition 및 receptor context 요약을 연구 방향의 seed context로 사용합니다."
                : "사용자 Research Goal을 주 목표로 유지하면서 Data-Grounded Analysis 요약을 보조 seed context로 제공합니다."}
            </p>
          </div>

          {/* Goal input */}
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Research Goal</Label>
            <Textarea
              placeholder={researchMode === "data_guided" ? "Optional: leave blank to let data-derived seed context guide the study" : "e.g., Find novel therapeutic targets related to MAPK signaling in liver fibrosis"}
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={2}
              disabled={running}
              className="text-sm resize-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            {/* Iterations */}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Iterations</Label>
              <Select value={maxIterations} onValueChange={setMaxIterations} disabled={running}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["1", "2", "3", "5"].map((v) => (
                    <SelectItem key={v} value={v} className="text-xs">
                      {v} iteration{v !== "1" ? "s" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Collections */}
            {collections.length > 0 && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">
                  ChromaDB Collections
                  <span className="ml-1 opacity-60">(empty = all)</span>
                </Label>
                <Select
                  onValueChange={(v) =>
                    setSelectedCollections((prev) =>
                      prev.includes(v) ? prev.filter((c) => c !== v) : [...prev, v]
                    )
                  }
                  disabled={running}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue
                      placeholder={
                        selectedCollections.length
                          ? selectedCollections.join(", ")
                          : "All collections"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {collections.map((c) => (
                      <SelectItem key={c} value={c} className="text-xs">
                        {selectedCollections.includes(c) && "✓ "}
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          {/* Errors */}
          {runError && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/5 px-3 py-2 text-xs text-destructive">
              <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              {runError}
            </div>
          )}

          <div className="flex gap-2">
            <Button
              onClick={handleRun}
              disabled={running}
              className="flex-1"
              size="sm"
            >
              {running ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 mr-2 animate-spin" />
                  {session?.status === "cancelling" ? "Stopping…" : "Researching…"}
                </>
              ) : sessionId ? (
                <>
                  <RefreshCw className="h-3.5 w-3.5 mr-2" />
                  Re-analyze
                </>
              ) : (
                <>
                  <Lightbulb className="h-3.5 w-3.5 mr-2" />
                  Start Co-Scientist
                </>
              )}
            </Button>
            {running && session?.status !== "cancelling" && (
              <Button
                onClick={handleCancel}
                variant="destructive"
                size="sm"
                className="shrink-0 gap-1.5"
                title="파이프라인 중단"
              >
                <StopCircle className="h-3.5 w-3.5" />
                Stop
              </Button>
            )}
          </div>

          {sessionId && (
            <p className="text-[10px] text-muted-foreground text-center font-mono">
              session: {sessionId}
              {session?.status === "cancelled" && (
                <span className="ml-2 text-amber-500">— 중단됨</span>
              )}
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Running skeleton ─────────────────────────────────────────── */}
      {running && (
        <div className="space-y-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-10 w-3/4" />
        </div>
      )}

      {/* ── Session error ─────────────────────────────────────────────── */}
      {!running && isSessionError && (
        <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <AlertCircle className="h-10 w-10 mb-3 opacity-40" />
          <p className="text-sm font-medium">Pipeline error</p>
          <p className="text-xs mt-1">{session?.status?.replace("error: ", "")}</p>
        </div>
      )}

      {/* ── Results ──────────────────────────────────────────────────── */}
      {!running && session && hasResults && (
        <>
          {/* Summary stats */}
          <div id={`cs-results-${orderId}`} className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/10">
                <Dna className="h-5 w-5 text-violet-500" />
              </div>
              <div>
                <p className="text-sm font-medium flex items-center gap-2">
                  {session.total_hypotheses} hypotheses generated
                  {session.status === "cancelled" && (
                    <span className="text-xs font-normal text-amber-500 bg-amber-50 dark:bg-amber-950/30 px-1.5 py-0.5 rounded border border-amber-200 dark:border-amber-800">
                      중단됨 (부분 결과)
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground">
                  {session.iteration} iteration{session.iteration !== 1 ? "s" : ""} ·{" "}
                  {session.top_hypotheses.length} shown
                  {feedbackCount > 0 && ` · ${feedbackCount} feedback applied`}
                </p>
              </div>
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={handleDesignExperiments}
              disabled={designsLoading}
            >
              {designsLoading ? (
                <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
              ) : (
                <Microscope className="h-3.5 w-3.5 mr-1.5" />
              )}
              Design Experiments
            </Button>
          </div>

          {/* Hypotheses table */}
          {session.top_hypotheses.length > 0 && (
            <Card>
              <CardContent className="pt-4">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-10">#</TableHead>
                      <TableHead>Hypothesis (IF → THEN)</TableHead>
                      <TableHead className="w-[110px]">Category</TableHead>
                      <TableHead className="w-[80px] text-right">Elo</TableHead>
                      <TableHead className="w-[80px] text-right">Evidence</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {session.top_hypotheses.map((h, idx) => (
                      <>
                        <TableRow
                          key={h.id}
                          className="cursor-pointer group"
                          onClick={() => setExpandedId(expandedId === h.id ? null : h.id)}
                        >
                          <TableCell className="font-mono text-xs text-muted-foreground">
                            {idx + 1}
                          </TableCell>
                          <TableCell>
                            <div className="max-w-xl">
                              <p className="text-xs font-medium leading-snug">
                                {h.condition}
                              </p>
                              <p className="text-xs text-muted-foreground leading-snug mt-0.5 truncate">
                                → {h.prediction}
                              </p>
                            </div>
                            <button className="text-muted-foreground mt-1">
                              {expandedId === h.id ? (
                                <ChevronUp className="h-3 w-3" />
                              ) : (
                                <ChevronDown className="h-3 w-3" />
                              )}
                            </button>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant="outline"
                              className={[
                                "text-[10px] capitalize border",
                                CATEGORY_COLORS[h.category] ?? "",
                              ].join(" ")}
                            >
                              {h.category}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="font-mono text-xs tabular-nums">
                                    {h.elo_rating}
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent>
                                  Elo rating · confidence{" "}
                                  {(h.confidence * 100).toFixed(0)}%
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          </TableCell>
                          <TableCell className="text-right">
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <div className="flex items-center justify-end gap-0.5 text-xs font-mono">
                                    <span className="text-emerald-600">
                                      +{h.evidence_for.length}
                                    </span>
                                    <span className="text-muted-foreground">/</span>
                                    <span className="text-rose-600">
                                      -{h.evidence_against.length}
                                    </span>
                                  </div>
                                </TooltipTrigger>
                                <TooltipContent>
                                  {h.evidence_for.length} supporting /{" "}
                                  {h.evidence_against.length} contradicting
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          </TableCell>
                        </TableRow>

                        {/* Expanded row */}
                        {expandedId === h.id && (
                          <TableRow key={`${h.id}-detail`} className="bg-muted/20 hover:bg-muted/20">
                            <TableCell />
                            <TableCell colSpan={4}>
                              <div className="py-2 space-y-3 text-xs">
                                <div>
                                  <span className="font-semibold text-blue-600 dark:text-blue-400">
                                    BECAUSE
                                  </span>
                                  <p className="mt-1 text-muted-foreground leading-relaxed">
                                    {h.mechanism}
                                  </p>
                                </div>
                                {h.signaling_chain && (
                                  <div>
                                    <span className="font-semibold">Signaling chain</span>
                                    <p className="mt-0.5 font-mono text-muted-foreground">
                                      {h.signaling_chain}
                                    </p>
                                  </div>
                                )}
                                {h.testable_prediction && (
                                  <div>
                                    <span className="font-semibold">Testable prediction</span>
                                    <p className="mt-0.5 text-muted-foreground">
                                      {h.testable_prediction}
                                    </p>
                                  </div>
                                )}
                                {h.supporting_ptms.length > 0 && (
                                  <div className="flex flex-wrap gap-1">
                                    {h.supporting_ptms.map((p) => (
                                      <Badge key={p} variant="secondary" className="text-[10px]">
                                        {p}
                                      </Badge>
                                    ))}
                                  </div>
                                )}
                                {h.evidence_for.length > 0 && (
                                  <div>
                                    <p className="font-semibold text-emerald-600 dark:text-emerald-400 mb-1">
                                      Supporting literature
                                    </p>
                                    <ul className="space-y-0.5">
                                      {h.evidence_for.slice(0, 3).map((ev, i) => (
                                        <li key={i} className="flex items-start gap-1.5 text-muted-foreground">
                                          <BookOpen className="h-3 w-3 mt-0.5 shrink-0" />
                                          <span>
                                            <span className="font-medium text-foreground">
                                              {evidenceTitle(ev)}
                                            </span>
                                            {evidenceExcerpt(ev)
                                              ? ` — ${evidenceExcerpt(ev).slice(0, 120)}…`
                                              : ""}
                                          </span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>
                        )}
                      </>
                    ))}
                  </TableBody>
                </Table>
                <p className="text-xs text-muted-foreground mt-3 text-right">
                  Showing {session.top_hypotheses.length} of {session.total_hypotheses} hypotheses
                </p>
              </CardContent>
            </Card>
          )}

          {/* Experiment designs */}
          {session.experiment_designs.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-md bg-violet-500/10">
                    <Microscope className="h-3.5 w-3.5 text-violet-500" />
                  </div>
                  Experiment Designs
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Title</TableHead>
                      <TableHead className="w-[100px]">Approach</TableHead>
                      <TableHead className="w-[100px]">Timeline</TableHead>
                      <TableHead className="w-[70px]">Priority</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {session.experiment_designs.map((d, i) => (
                      <TableRow key={i}>
                        <TableCell>
                          <p className="text-xs font-medium">{d.title}</p>
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                            {d.objective}
                          </p>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {d.approach}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {d.estimated_timeline}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={
                              d.priority === "high"
                                ? "text-rose-600 bg-rose-500/10 border-rose-500/20 text-[10px]"
                                : d.priority === "medium"
                                ? "text-orange-600 bg-orange-500/10 border-orange-500/20 text-[10px]"
                                : "text-[10px]"
                            }
                          >
                            {d.priority}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {(reasoning || session.top_hypotheses.length > 0) && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-md bg-emerald-500/10">
                    <BookOpen className="h-3.5 w-3.5 text-emerald-500" />
                  </div>
                  Scientific Reasoning & Lab Results
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-xs">
                {reasoning?.meta_review?.executive_summary && (
                  <p className="text-muted-foreground">{reasoning.meta_review.executive_summary}</p>
                )}
                {reasoning?.evidence_graph?.summary && (
                  <p className="text-muted-foreground">
                    Graph: {reasoning.evidence_graph.summary.node_count ?? 0} nodes ·{" "}
                    {reasoning.evidence_graph.summary.edge_count ?? 0} edges
                    {reasoning.lab_results?.length
                      ? ` · ${reasoning.lab_results.length} lab result(s)`
                      : ""}
                  </p>
                )}
                <div className="grid gap-2 sm:grid-cols-[1fr_140px_1fr_auto]">
                  <Select
                    value={labHypothesisId || session.top_hypotheses[0]?.id || ""}
                    onValueChange={setLabHypothesisId}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="Hypothesis" />
                    </SelectTrigger>
                    <SelectContent>
                      {session.top_hypotheses.map((h) => (
                        <SelectItem key={h.id} value={h.id} className="text-xs">
                          {h.id} · {h.prediction.slice(0, 40)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select value={labOutcome} onValueChange={setLabOutcome}>
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="supports" className="text-xs">Supports</SelectItem>
                      <SelectItem value="contradicts" className="text-xs">Contradicts</SelectItem>
                      <SelectItem value="inconclusive" className="text-xs">Inconclusive</SelectItem>
                    </SelectContent>
                  </Select>
                  <Textarea
                    value={labSummary}
                    onChange={(e) => setLabSummary(e.target.value)}
                    placeholder="Observed assay result…"
                    rows={1}
                    className="text-xs resize-none min-h-8"
                  />
                  <Button size="sm" onClick={handleLabResult} disabled={labPending || !labSummary.trim()}>
                    {labPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Record"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Session History */}
          <Card>
            <CardHeader
              className="pb-3 cursor-pointer select-none"
              onClick={() => { setHistoryOpen((o) => !o); if (!historyOpen) loadHistory(); }}
            >
              <CardTitle className="text-sm flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-500/10">
                    <History className="h-3.5 w-3.5 text-slate-500" />
                  </div>
                  Session History
                </div>
                <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${historyOpen ? "rotate-180" : ""}`} />
              </CardTitle>
            </CardHeader>
            {historyOpen && (
              <CardContent className="pt-0 space-y-1">
                {historyLoading ? (
                  <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>
                ) : history.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-3">이전 세션 없음</p>
                ) : (
                  <div className="space-y-1">
                    {history.map((h) => {
                      const isActive = h.session_id === sessionId;
                      const dt = h.created_at ? new Date(h.created_at).toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
                      const statusColor = h.status === "completed" ? "text-emerald-600 bg-emerald-50 border-emerald-200 dark:bg-emerald-950/30 dark:border-emerald-800" : h.status === "cancelled" ? "text-amber-600 bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800" : h.status.startsWith("error") ? "text-red-600 bg-red-50 border-red-200 dark:bg-red-950/30 dark:border-red-800" : "text-slate-600 bg-slate-50 border-slate-200";
                      return (
                        <button
                          key={h.session_id}
                          onClick={() => loadSessionFromHistory(h.session_id)}
                          className={`w-full text-left rounded-md border px-3 py-2 text-xs transition-colors hover:bg-muted/60 ${isActive ? "border-violet-400 bg-violet-50/60 dark:bg-violet-950/20" : "border-border"}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-mono text-[10px] text-muted-foreground">{h.session_id}</span>
                            <span className={`px-1.5 py-0.5 rounded border text-[10px] font-medium ${statusColor}`}>
                              {h.status === "completed" ? "완료" : h.status === "cancelled" ? "중단" : h.status.startsWith("error") ? "오류" : h.status}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 mt-1 text-muted-foreground">
                            <Clock className="h-2.5 w-2.5 shrink-0" />
                            <span>{dt}</span>
                            <span>·</span>
                            <span>{h.total_hypotheses}개 가설</span>
                            <span>·</span>
                            <span>{h.iteration} iter</span>
                          </div>
                          {h.research_goal && (
                            <p className="mt-1 text-[10px] text-muted-foreground truncate">{h.research_goal}</p>
                          )}
                          {isActive && <span className="text-[10px] text-violet-500 font-medium">현재 보는 세션</span>}
                        </button>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            )}
          </Card>

          {/* Scientist feedback */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-500/10">
                  <MessageSquare className="h-3.5 w-3.5 text-blue-500" />
                </div>
                Scientist-in-the-Loop Feedback
                {feedbackCount > 0 && (
                  <Badge variant="secondary" className="text-xs ml-1">
                    {feedbackCount} applied
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Guide the next iteration by providing research direction, constraints, or seed ideas.
              </p>

              <div className="flex gap-2">
                <Select value={feedbackType} onValueChange={setFeedbackType}>
                  <SelectTrigger className="h-8 text-xs w-[160px] shrink-0">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="direction" className="text-xs">Direction</SelectItem>
                    <SelectItem value="constraint" className="text-xs">Constraint</SelectItem>
                    <SelectItem value="seed_idea" className="text-xs">Seed Idea</SelectItem>
                  </SelectContent>
                </Select>
                <div className="flex-1 relative">
                  <Textarea
                    placeholder="Enter your research direction, constraint, or seed idea…"
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    rows={2}
                    className="text-xs resize-none pr-10"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleFeedback();
                    }}
                  />
                  <button
                    onClick={handleFeedback}
                    disabled={!feedback.trim() || feedbackPending}
                    className="absolute right-2 bottom-2 text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
                  >
                    {feedbackPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>

              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={handleRerun}
                disabled={running || (feedbackCount === 0 && labResultCount === 0)}
              >
                <RefreshCw className="h-3.5 w-3.5 mr-2" />
                Re-run with feedback ({feedbackCount})
              </Button>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
