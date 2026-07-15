/**
 * CoScientistPage — Standalone multi-order hypothesis generation.
 *
 * Lets researchers select any number of completed Orders and run the
 * Generate → Debate → Evolve pipeline across all selected experiments,
 * surfacing cross-experiment consensus signals that no single-order
 * analysis can reveal.
 */

import { useEffect, useRef, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
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
  Search,
  X,
  ExternalLink,
  LayersIcon,
  Cpu,
  StopCircle,
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface OrderMeta {
  id: number;
  order_code: string;
  project_name: string;
  ptm_type: string;
  species: string;
  created_at: string | null;
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
  evidence_for: { source: string; text: string }[];
  evidence_against: { source: string; text: string }[];
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
}

// ─── Pipeline step visualization ──────────────────────────────────────────────

const CS_STEPS = [
  { label: "Generate", Icon: Lightbulb, color: "text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950 dark:border-blue-800" },
  { label: "Debate",   Icon: Swords,    color: "text-orange-600 bg-orange-50 border-orange-200 dark:text-orange-400 dark:bg-orange-950 dark:border-orange-800" },
  { label: "Evolve",   Icon: Sparkles,  color: "text-emerald-600 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-950 dark:border-emerald-800" },
  { label: "Design",   Icon: Microscope,color: "text-violet-600 bg-violet-50 border-violet-200 dark:text-violet-400 dark:bg-violet-950 dark:border-violet-800" },
] as const;

function PipelineSteps({ running, completed }: { running: boolean; completed: boolean }) {
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {CS_STEPS.map((step, i) => {
        const StepIcon = step.Icon;
        return (
          <div key={step.label} className="flex items-center gap-1">
            <div className={[
              "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-all",
              completed
                ? "text-emerald-600 bg-emerald-50 border-emerald-200 dark:text-emerald-400 dark:bg-emerald-950 dark:border-emerald-800"
                : running && i < 3
                ? step.color
                : step.color + " opacity-40",
            ].join(" ")}>
              {running && !completed && i < 3 ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : completed ? (
                <CheckCircle2 className="h-3 w-3" />
              ) : (
                <StepIcon className="h-3 w-3" />
              )}
              {step.label}
            </div>
            {i < CS_STEPS.length - 1 && (
              <ArrowRight className="h-3 w-3 text-muted-foreground opacity-40 shrink-0" />
            )}
          </div>
        );
      })}
    </div>
  );
}

const CATEGORY_COLORS: Record<string, string> = {
  mechanistic:  "bg-blue-500/10 text-blue-700 border-blue-500/20 dark:text-blue-400",
  temporal:     "bg-orange-500/10 text-orange-700 border-orange-500/20 dark:text-orange-400",
  predictive:   "bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-400",
  integrative:  "bg-violet-500/10 text-violet-700 border-violet-500/20 dark:text-violet-400",
  therapeutic:  "bg-rose-500/10 text-rose-700 border-rose-500/20 dark:text-rose-400",
};

// ─── Component ────────────────────────────────────────────────────────────────

export default function CoScientistPage() {
  const navigate = useNavigate();

  // Orders
  const [orders, setOrders] = useState<OrderMeta[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [ptmFilter, setPtmFilter] = useState<string>("all");
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(new Set());

  // Service health
  const [serviceOk, setServiceOk] = useState<boolean | null>(null);
  const [collections, setCollections] = useState<string[]>([]);

  // Form
  const [goal, setGoal] = useState("");
  const [maxIterations, setMaxIterations] = useState("3");
  const [ptmType, setPtmType] = useState("phosphorylation");
  const [selectedCollections, setSelectedCollections] = useState<string[]>([]);

  // Session
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // LLM selector
  const [llmProvider, setLlmProvider] = useState("auto");
  const [llmModel, setLlmModel] = useState("");

  // Feedback
  const [feedback, setFeedback] = useState("");
  const [feedbackType, setFeedbackType] = useState("direction");
  const [feedbackPending, setFeedbackPending] = useState(false);
  const [feedbackCount, setFeedbackCount] = useState(0);

  // Experiments
  const [designsLoading, setDesignsLoading] = useState(false);

  // Expanded hypothesis row
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── Load orders + health on mount ──────────────────────────────────────
  useEffect(() => {
    Promise.all([
      api.get<{ orders: OrderMeta[] }>("/coscientist/orders"),
      api.get<any>("/coscientist/health"),
    ])
      .then(([ordersRes, healthRes]) => {
        setOrders(ordersRes.orders);
        setServiceOk(healthRes.status !== "error");
        setCollections(healthRes.checks?.chromadb?.collections ?? []);
      })
      .catch(() => setServiceOk(false))
      .finally(() => setOrdersLoading(false));
  }, []);

  // ─── Poll session ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!sessionId || !running) return;
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.get<SessionResponse>(`/coscientist/session/${sessionId}`);
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
  }, [sessionId, running]);

  // ─── Derived state ────────────────────────────────────────────────────────
  const filteredOrders = useMemo(() => {
    let list = orders;
    if (ptmFilter !== "all") list = list.filter((o) => o.ptm_type === ptmFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (o) =>
          o.order_code.toLowerCase().includes(q) ||
          o.project_name?.toLowerCase().includes(q) ||
          o.species?.toLowerCase().includes(q)
      );
    }
    return list;
  }, [orders, ptmFilter, search]);

  const ptmTypes = useMemo(
    () => [...new Set(orders.map((o) => o.ptm_type).filter(Boolean))],
    [orders]
  );

  const isCompleted = session?.status === "completed";
  const isSessionError = session?.status?.startsWith("error");

  // ─── Handlers ────────────────────────────────────────────────────────────
  function toggleOrder(code: string) {
    setSelectedCodes((prev) => {
      const next = new Set(prev);
      next.has(code) ? next.delete(code) : next.add(code);
      return next;
    });
  }

  async function handleRun() {
    if (selectedCodes.size === 0) return;
    setRunError(null);
    setSession(null);
    setRunning(true);
    setFeedbackCount(0);
    try {
      const res = await api.post<{ session_id: string }>("/coscientist/run", {
        order_codes: [...selectedCodes],
        research_goal: goal,
        ptm_type: ptmType,
        max_iterations: parseInt(maxIterations),
        rag_collections: selectedCollections.length ? selectedCollections : null,
        llm_provider: llmProvider === "auto" ? "" : llmProvider,
        llm_model: llmModel,
      });
      setSessionId(res.session_id);
    } catch (e: any) {
      setRunError(e.message);
      setRunning(false);
    }
  }

  async function handleCancel() {
    if (!sessionId || !running) return;
    try {
      await api.post(`/coscientist/session/${sessionId}/cancel`);
      setSession((s) => s ? { ...s, status: "cancelling" } : s);
    } catch (e: any) {
      setRunError(`Stop failed: ${e.message}`);
    }
  }

  async function handleFeedback() {
    if (!sessionId || !feedback.trim()) return;
    setFeedbackPending(true);
    try {
      await api.post(`/coscientist/session/${sessionId}/feedback`, {
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
      await api.post(`/coscientist/session/${sessionId}/rerun`);
    } catch (e: any) {
      setRunError(e.message);
      setRunning(false);
    }
  }

  async function handleDesignExperiments() {
    if (!sessionId) return;
    setDesignsLoading(true);
    try {
      const res = await api.post<{ designs: ExperimentDesign[] }>(
        `/coscientist/session/${sessionId}/design-experiments?top_n=5`
      );
      setSession((s) => (s ? { ...s, experiment_designs: res.designs } : s));
    } catch (e: any) {
      setRunError(e.message);
    } finally {
      setDesignsLoading(false);
    }
  }

  // ─── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6 p-6">
      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-500/10">
              <FlaskConical className="h-4 w-4 text-violet-500" />
            </div>
            Co-Scientist
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Select completed orders and synthesise cross-experiment hypotheses using accumulated PTM data and RAG literature.
          </p>
        </div>
        {serviceOk === false && (
          <div className="flex items-center gap-1.5 text-xs text-amber-600 bg-amber-500/10 border border-amber-500/20 rounded-md px-3 py-1.5">
            <AlertCircle className="h-3.5 w-3.5" />
            Co-Scientist API unavailable
          </div>
        )}
        {serviceOk === true && (
          <div className="flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-500/10 border border-emerald-500/20 rounded-md px-3 py-1.5">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Service online
          </div>
        )}
      </div>

      <div className="grid lg:grid-cols-[1fr_380px] gap-6 items-start">

        {/* ── Left: Order selector ─────────────────────────────────────── */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center justify-between">
              <span className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-500/10">
                  <LayersIcon className="h-3.5 w-3.5 text-blue-500" />
                </div>
                Select Experiments
              </span>
              <span className="text-xs font-normal text-muted-foreground">
                {selectedCodes.size > 0 && (
                  <span className="text-primary font-medium">{selectedCodes.size} selected · </span>
                )}
                {orders.length} completed
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Filters */}
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Filter by order code, project, species…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9 h-8 text-xs"
                />
                {search && (
                  <button
                    onClick={() => setSearch("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              {ptmTypes.length > 1 && (
                <Select value={ptmFilter} onValueChange={setPtmFilter}>
                  <SelectTrigger className="h-8 text-xs w-[140px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all" className="text-xs">All PTM types</SelectItem>
                    {ptmTypes.map((t) => (
                      <SelectItem key={t} value={t} className="text-xs capitalize">{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            {/* Order table */}
            {ordersLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : filteredOrders.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-muted-foreground">
                <Dna className="h-10 w-10 mb-3 opacity-40" />
                <p className="text-sm font-medium">No completed orders</p>
                <p className="text-xs mt-1">
                  Run PTM analysis first to make orders available for Co-Scientist.
                </p>
              </div>
            ) : (
              <div className="rounded-md border overflow-hidden">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-9" />
                      <TableHead>Order</TableHead>
                      <TableHead className="w-[90px]">PTM Type</TableHead>
                      <TableHead className="w-[80px]">Species</TableHead>
                      <TableHead className="w-[100px]">Date</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredOrders.map((o) => {
                      const checked = selectedCodes.has(o.order_code);
                      return (
                        <TableRow
                          key={o.id}
                          className={[
                            "cursor-pointer",
                            checked ? "bg-primary/5" : "",
                          ].join(" ")}
                          onClick={() => toggleOrder(o.order_code)}
                        >
                          <TableCell>
                            <div
                              className={[
                                "h-4 w-4 rounded border-2 flex items-center justify-center transition-colors",
                                checked
                                  ? "bg-primary border-primary"
                                  : "border-muted-foreground/30",
                              ].join(" ")}
                            >
                              {checked && (
                                <CheckCircle2 className="h-3 w-3 text-primary-foreground" />
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            <p className="text-xs font-medium font-mono">{o.order_code}</p>
                            {o.project_name && (
                              <p className="text-[10px] text-muted-foreground truncate max-w-[200px]">
                                {o.project_name}
                              </p>
                            )}
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[10px] capitalize">
                              {o.ptm_type}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground capitalize">
                            {o.species}
                          </TableCell>
                          <TableCell className="text-[10px] text-muted-foreground">
                            {o.created_at
                              ? new Date(o.created_at).toLocaleDateString("ko-KR")
                              : "—"}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}

            {/* Selected pills */}
            {selectedCodes.size > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {[...selectedCodes].map((code) => (
                  <Badge
                    key={code}
                    variant="secondary"
                    className="text-xs cursor-pointer hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => toggleOrder(code)}
                  >
                    {code} <X className="h-2.5 w-2.5 ml-1" />
                  </Badge>
                ))}
                <button
                  className="text-xs text-muted-foreground hover:text-destructive underline"
                  onClick={() => setSelectedCodes(new Set())}
                >
                  Clear all
                </button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Right: Config + results ───────────────────────────────────── */}
        <div className="space-y-4">
          {/* Config card */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-md bg-violet-500/10">
                    <Lightbulb className="h-3.5 w-3.5 text-violet-500" />
                  </div>
                  AI Research Studio
                </CardTitle>
                {/* LLM quick-pick */}
                <div className="flex items-center gap-1 shrink-0">
                  <Cpu className="h-3 w-3 text-muted-foreground" />
                  <Select value={llmProvider} onValueChange={(v) => { setLlmProvider(v); setLlmModel(""); }} disabled={running}>
                    <SelectTrigger className="h-6 text-[10px] w-20 px-1.5">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto" className="text-xs">Auto</SelectItem>
                      <SelectItem value="ollama" className="text-xs">Ollama</SelectItem>
                      <SelectItem value="openai" className="text-xs">OpenAI</SelectItem>
                      <SelectItem value="gemini" className="text-xs">Gemini</SelectItem>
                    </SelectContent>
                  </Select>
                  {llmProvider === "ollama" && (
                    <Select value={llmModel} onValueChange={setLlmModel} disabled={running}>
                      <SelectTrigger className="h-6 text-[10px] w-28 px-1.5">
                        <SelectValue placeholder="model…" />
                      </SelectTrigger>
                      <SelectContent>
                        {["gemma3:27b","gemma3:12b","gemma3:4b","llama3.3:70b","qwen2.5:7b"].map((m) => (
                          <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                  {llmProvider === "openai" && (
                    <Select value={llmModel} onValueChange={setLlmModel} disabled={running}>
                      <SelectTrigger className="h-6 text-[10px] w-28 px-1.5">
                        <SelectValue placeholder="model…" />
                      </SelectTrigger>
                      <SelectContent>
                        {["gpt-4o","gpt-4o-mini","o3-mini"].map((m) => (
                          <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                  {llmProvider === "gemini" && (
                    <Select value={llmModel} onValueChange={setLlmModel} disabled={running}>
                      <SelectTrigger className="h-6 text-[10px] w-36 px-1.5">
                        <SelectValue placeholder="model…" />
                      </SelectTrigger>
                      <SelectContent>
                        {["gemini-2.5-flash","gemini-2.5-pro","gemini-2.0-flash"].map((m) => (
                          <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <PipelineSteps running={running} completed={!!isCompleted} />
              <Separator />

              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Research Goal</Label>
                <Textarea
                  placeholder="e.g., Identify conserved kinase modules across liver fibrosis experiments"
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  rows={3}
                  disabled={running}
                  className="text-xs resize-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">PTM Type</Label>
                  <Select value={ptmType} onValueChange={setPtmType} disabled={running}>
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="phosphorylation" className="text-xs">Phosphorylation</SelectItem>
                      <SelectItem value="ubiquitylation" className="text-xs">Ubiquitylation</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Iterations</Label>
                  <Select value={maxIterations} onValueChange={setMaxIterations} disabled={running}>
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {["1","2","3","5"].map((v) => (
                        <SelectItem key={v} value={v} className="text-xs">{v} iteration{v!=="1"?"s":""}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {collections.length > 0 && (
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">
                    ChromaDB Collections <span className="opacity-60">(empty = all)</span>
                  </Label>
                  <Select
                    onValueChange={(v) =>
                      setSelectedCollections((p) =>
                        p.includes(v) ? p.filter((c) => c !== v) : [...p, v]
                      )
                    }
                    disabled={running}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue
                        placeholder={selectedCollections.length ? selectedCollections.join(", ") : "All collections"}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {collections.map((c) => (
                        <SelectItem key={c} value={c} className="text-xs">
                          {selectedCollections.includes(c) && "✓ "}{c}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {runError && (
                <div className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                  <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  {runError}
                </div>
              )}

              <div className="flex gap-2">
                <Button
                  className="flex-1"
                  size="sm"
                  onClick={handleRun}
                  disabled={running || selectedCodes.size === 0 || serviceOk === false}
                >
                  {running ? (
                    <><Loader2 className="h-3.5 w-3.5 mr-2 animate-spin" />
                    {session?.status === "cancelling" ? "Stopping…" : "Researching…"}</>
                  ) : (
                    <><Lightbulb className="h-3.5 w-3.5 mr-2" />
                    {selectedCodes.size === 0
                      ? "Select experiments first"
                      : `Start Co-Scientist (${selectedCodes.size})`}
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
                </p>
              )}
            </CardContent>
          </Card>

          {/* Running skeleton */}
          {running && (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}

          {/* Session error */}
          {!running && isSessionError && (
            <div className="flex flex-col items-center py-8 text-muted-foreground">
              <AlertCircle className="h-10 w-10 mb-2 opacity-40" />
              <p className="text-sm">{session?.status?.replace("error: ", "")}</p>
            </div>
          )}

          {/* Feedback (after completion) */}
          {!running && isCompleted && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-500/10">
                    <MessageSquare className="h-3.5 w-3.5 text-blue-500" />
                  </div>
                  Scientist Feedback
                  {feedbackCount > 0 && (
                    <Badge variant="secondary" className="text-xs ml-1">{feedbackCount}</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex gap-2">
                  <Select value={feedbackType} onValueChange={setFeedbackType}>
                    <SelectTrigger className="h-8 text-xs w-[140px] shrink-0">
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
                      placeholder="Guide the next iteration…"
                      value={feedback}
                      onChange={(e) => setFeedback(e.target.value)}
                      rows={2}
                      className="text-xs resize-none pr-10"
                      onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleFeedback(); }}
                    />
                    <button
                      onClick={handleFeedback}
                      disabled={!feedback.trim() || feedbackPending}
                      className="absolute right-2 bottom-2 text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
                    >
                      {feedbackPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
                <Button
                  variant="outline" size="sm" className="w-full"
                  onClick={handleRerun}
                  disabled={running || feedbackCount === 0}
                >
                  <RefreshCw className="h-3.5 w-3.5 mr-2" />
                  Re-run with feedback ({feedbackCount})
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* ── Results: hypotheses + experiment designs ─────────────────────── */}
      {!running && session && isCompleted && (
        <div className="space-y-4">
          {/* Summary */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-violet-500/10">
                <Dna className="h-5 w-5 text-violet-500" />
              </div>
              <div>
                <p className="text-sm font-medium">
                  {session.total_hypotheses} hypotheses generated
                </p>
                <p className="text-xs text-muted-foreground">
                  {session.iteration} iteration{session.iteration !== 1 ? "s" : ""} ·{" "}
                  {[...selectedCodes].length} order{[...selectedCodes].length !== 1 ? "s" : ""} synthesised
                  {feedbackCount > 0 && ` · ${feedbackCount} feedback applied`}
                </p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={handleDesignExperiments} disabled={designsLoading}>
              {designsLoading
                ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                : <Microscope className="h-3.5 w-3.5 mr-1.5" />}
              Design Experiments
            </Button>
          </div>

          {/* Hypotheses */}
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
                      <TableHead className="w-[90px] text-right">Evidence</TableHead>
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
                          <TableCell className="font-mono text-xs text-muted-foreground">{idx + 1}</TableCell>
                          <TableCell>
                            <div className="max-w-2xl">
                              <p className="text-xs font-medium leading-snug">{h.condition}</p>
                              <p className="text-xs text-muted-foreground leading-snug mt-0.5 truncate">→ {h.prediction}</p>
                            </div>
                            <button className="text-muted-foreground mt-1">
                              {expandedId === h.id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                            </button>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant="outline"
                              className={["text-[10px] capitalize border", CATEGORY_COLORS[h.category] ?? ""].join(" ")}
                            >
                              {h.category}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="font-mono text-xs tabular-nums">{h.elo_rating}</span>
                                </TooltipTrigger>
                                <TooltipContent>Elo · confidence {(h.confidence * 100).toFixed(0)}%</TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          </TableCell>
                          <TableCell className="text-right">
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <div className="flex items-center justify-end gap-0.5 text-xs font-mono">
                                    <span className="text-emerald-600">+{h.evidence_for.length}</span>
                                    <span className="text-muted-foreground">/</span>
                                    <span className="text-rose-600">-{h.evidence_against.length}</span>
                                  </div>
                                </TooltipTrigger>
                                <TooltipContent>{h.evidence_for.length} supporting / {h.evidence_against.length} contradicting</TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          </TableCell>
                        </TableRow>

                        {expandedId === h.id && (
                          <TableRow key={`${h.id}-detail`} className="bg-muted/20 hover:bg-muted/20">
                            <TableCell />
                            <TableCell colSpan={4}>
                              <div className="py-2 space-y-3 text-xs">
                                <div>
                                  <span className="font-semibold text-blue-600 dark:text-blue-400">BECAUSE</span>
                                  <p className="mt-1 text-muted-foreground leading-relaxed">{h.mechanism}</p>
                                </div>
                                {h.signaling_chain && (
                                  <div>
                                    <span className="font-semibold">Signaling chain</span>
                                    <p className="mt-0.5 font-mono text-muted-foreground">{h.signaling_chain}</p>
                                  </div>
                                )}
                                {h.testable_prediction && (
                                  <div>
                                    <span className="font-semibold">Testable prediction</span>
                                    <p className="mt-0.5 text-muted-foreground">{h.testable_prediction}</p>
                                  </div>
                                )}
                                {h.supporting_ptms.length > 0 && (
                                  <div className="flex flex-wrap gap-1">
                                    {h.supporting_ptms.map((p) => (
                                      <Badge key={p} variant="secondary" className="text-[10px]">{p}</Badge>
                                    ))}
                                  </div>
                                )}
                                {h.evidence_for.length > 0 && (
                                  <div>
                                    <p className="font-semibold text-emerald-600 dark:text-emerald-400 mb-1">Supporting literature</p>
                                    <ul className="space-y-0.5">
                                      {h.evidence_for.slice(0, 3).map((ev, i) => (
                                        <li key={i} className="flex items-start gap-1.5 text-muted-foreground">
                                          <BookOpen className="h-3 w-3 mt-0.5 shrink-0" />
                                          <span>
                                            <span className="font-medium text-foreground">{ev.source}</span>
                                            {" — "}{ev.text.slice(0, 120)}…
                                          </span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                <Button
                                  variant="ghost" size="sm"
                                  className="h-6 text-xs text-muted-foreground px-2"
                                  onClick={(e) => { e.stopPropagation(); navigate(`/admin/orders`); }}
                                >
                                  <ExternalLink className="h-3 w-3 mr-1" /> View source orders
                                </Button>
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
                      <TableHead>Title & Objective</TableHead>
                      <TableHead className="w-[120px]">Approach</TableHead>
                      <TableHead className="w-[100px]">Timeline</TableHead>
                      <TableHead className="w-[70px]">Priority</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {session.experiment_designs.map((d, i) => (
                      <TableRow key={i}>
                        <TableCell>
                          <p className="text-xs font-medium">{d.title}</p>
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{d.objective}</p>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{d.approach}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">{d.estimated_timeline}</TableCell>
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
        </div>
      )}
    </div>
  );
}
