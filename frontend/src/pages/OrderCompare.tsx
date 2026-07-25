import { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { ArrowLeft, GitCompareArrows, Loader2, AlertCircle, RefreshCw, Send, MessageSquare, FileDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, getAuthHeader } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAuth } from "@/contexts/AuthContext";
import { CLOUD_MODEL_PRESETS, CLOUD_PROVIDER_SENTINEL, type CloudProvider } from "@/lib/llm-models";

/* ─── Types ─── */
interface CompareMetadata {
  order_a: { id: number; order_code: string; project_name: string; species: string; ptm_type: string; conditions: string[] };
  order_b: { id: number; order_code: string; project_name: string; species: string; ptm_type: string; conditions: string[] };
  shared_genes: number;
  unique_a_genes: number;
  unique_b_genes: number;
  shared_sites: number;
  unique_a_sites: number;
  unique_b_sites: number;
}

interface LlmModelOption {
  id: number;
  name: string;
  provider: string;
  model_id: string;
  is_active: boolean;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/* ─── Helpers ─── */
function SummaryCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="flex flex-col items-center justify-center p-4 rounded-lg bg-muted/50 border min-w-[120px]">
      <span className="text-2xl font-bold text-primary">{value}</span>
      <span className="text-xs text-muted-foreground mt-1 text-center">{label}</span>
      {sub && <span className="text-[10px] text-muted-foreground/70 mt-0.5">{sub}</span>}
    </div>
  );
}

function OrderInfoCard({ order }: { order: CompareMetadata["order_a"] }) {
  return (
    <Card className="flex-1">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Link to={`/admin/orders/${order.id}`} className="font-mono text-primary hover:underline">
            {order.order_code}
          </Link>
          <Badge variant="outline" className="text-[10px]">{order.ptm_type}</Badge>
          <Badge variant="secondary" className="text-[10px]">{order.species}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <p className="text-sm text-muted-foreground">{order.project_name}</p>
        <p className="text-xs text-muted-foreground/70 mt-1">
          Conditions: {order.conditions.join(", ")}
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * Throw on HTTP errors; redirect to /login on 401 (expired/missing token).
 * Mirrors the behaviour of the api module's request() for raw fetch calls.
 */
async function assertOk(res: Response): Promise<void> {
  if (res.ok) return;
  if (res.status === 401) {
    localStorage.removeItem("ptm-token");
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
  throw new Error(errData.detail || `HTTP ${res.status}`);
}

/** Parse model selector value into provider + model_id */
function parseModelValue(value: string): { provider: string; model: string } {
  const idx = value.indexOf(":");
  if (idx < 0) return { provider: "ollama", model: value };
  const provider = value.slice(0, idx);
  const model = value.slice(idx + 1);
  return { provider, model: model === CLOUD_PROVIDER_SENTINEL ? "" : model };
}

/* ─── Main Component ─── */
export default function OrderCompare() {
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const orderAId = searchParams.get("a");
  const orderBId = searchParams.get("b");

  // State
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<CompareMetadata | null>(null);

  // LLM Model
  const [llmModels, setLlmModels] = useState<LlmModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");

  // User instructions
  const [userInstructions, setUserInstructions] = useState("");

  // Report language
  const [reportLanguage, setReportLanguage] = useState<"ko" | "en">("ko");

  // Report streaming
  const [report, setReport] = useState<string>("");
  const [reportSavedAt, setReportSavedAt] = useState<string | null>(null);
  const [savedReportId, setSavedReportId] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Chat Q&A
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatStreaming, setChatStreaming] = useState(false);
  const chatAbortRef = useRef<AbortController | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // PDF Export
  const [pdfExporting, setPdfExporting] = useState(false);

  /* Fetch LLM models */
  useEffect(() => {
    api.get<{ models: LlmModelOption[] }>("/llm/models").then((d: { models: LlmModelOption[] }) => {
      const active = d.models.filter((m: LlmModelOption) => m.is_active);
      setLlmModels(active);
      if (active.length > 0 && !selectedModel) {
        // Prefer gemma3:27b, then any gemma3/qwen2.5 (known Korean-capable models),
        // then first Ollama model, then first available.
        const preferred = ["gemma3:27b", "qwen2.5:14b", "qwen3.5:27b", "gemma3:12b", "gemma3:4b"];
        const bestMatch = preferred
          .map((id) => active.find((m: LlmModelOption) => m.model_id === id && m.provider === "ollama"))
          .find(Boolean);
        const ollamaModel = active.find((m: LlmModelOption) => m.provider === "ollama");
        const defaultModel = bestMatch || ollamaModel || active[0];
        setSelectedModel(`${defaultModel.provider}:${defaultModel.model_id}`);
      }
    }).catch(() => {});
  }, []);

  /* Fetch metadata (summary) */
  const fetchMetadata = useCallback(async () => {
    if (!orderAId || !orderBId) {
      setError("Two order IDs are required (query params: a, b)");
      setLoading(false);
      return;
    }
    try {
      const res = await fetch("/api/compare/summary", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeader(),
        },
        body: JSON.stringify({ order_id_a: parseInt(orderAId), order_id_b: parseInt(orderBId) }),
      });
      await assertOk(res);
      const data = await res.json();
      // Map the summary response to CompareMetadata format
      setMetadata({
        order_a: data.order_a,
        order_b: data.order_b,
        shared_genes: data.stats?.total_shared || 0,
        unique_a_genes: data.stats?.total_a_only || 0,
        unique_b_genes: data.stats?.total_b_only || 0,
        shared_sites: data.stats?.total_shared || 0,
        unique_a_sites: data.stats?.total_a_only || 0,
        unique_b_sites: data.stats?.total_b_only || 0,
      });
      setError(null);
    } catch (err: unknown) {
      setError((err as Error).message || "Failed to load comparison metadata");
    } finally {
      setLoading(false);
    }
  }, [orderAId, orderBId]);

  /* Stream comparative report */
  const streamReport = useCallback(async () => {
    if (!orderAId || !orderBId) return;
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);
    setReport("");

    const { provider, model } = parseModelValue(selectedModel);

    try {
      const res = await fetch("/api/compare/report", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeader(),
        },
        body: JSON.stringify({
          order_id_a: parseInt(orderAId),
          order_id_b: parseInt(orderBId),
          llm_model: model || undefined,
          llm_provider: provider || undefined,
          user_instructions: userInstructions.trim() || undefined,
          language: reportLanguage,
        }),
        signal: controller.signal,
      });
      await assertOk(res);
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const payload = line.slice(6);
            if (payload === "[DONE]") break;
            try {
              const parsed = JSON.parse(payload);
              if (parsed.type === "token" && parsed.content) {
                setReport((prev) => prev + parsed.content);
              } else if (parsed.type === "error") {
                setReport((prev) => prev + `\n\n---\n**Error:** ${parsed.message}`);
              }
            } catch {
              // non-JSON line
            }
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        setReport((prev) => prev + `\n\n---\n**Error:** ${(err as Error).message}`);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      // Auto-save completed report to DB
      setReport((finalReport) => {
        if (finalReport && !finalReport.includes("**Error:**") && orderAId && orderBId) {
          const { model } = parseModelValue(selectedModel);
          fetch("/api/compare/save", {
            method: "POST",
            headers: { "Content-Type": "application/json", ...getAuthHeader() },
            body: JSON.stringify({
              order_id_a: parseInt(orderAId),
              order_id_b: parseInt(orderBId),
              report_text: finalReport,
              llm_model: model || undefined,
              user_instructions: userInstructions.trim() || undefined,
            }),
          })
            .then((r) => r.json())
            .then((d) => {
              if (d.id) {
                setSavedReportId(d.id);
                const kst = new Date(d.updated_at + "Z").toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
                setReportSavedAt(kst);
              }
            })
            .catch(() => { /* save failed silently */ });
        }
        return finalReport;
      });
    }
  }, [orderAId, orderBId, selectedModel, userInstructions]);

  /* Send chat message */
  const sendChatMessage = useCallback(async () => {
    if (!chatInput.trim() || !orderAId || !orderBId || chatStreaming) return;
    const userMsg: ChatMessage = { role: "user", content: chatInput.trim() };
    const updatedMessages = [...chatMessages, userMsg];
    setChatMessages(updatedMessages);
    setChatInput("");
    setChatStreaming(true);

    if (chatAbortRef.current) chatAbortRef.current.abort();
    const controller = new AbortController();
    chatAbortRef.current = controller;

    const { provider, model } = parseModelValue(selectedModel);

    // Add empty assistant message that will be filled by streaming
    setChatMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const res = await fetch("/api/compare/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeader(),
        },
        body: JSON.stringify({
          order_id_a: parseInt(orderAId),
          order_id_b: parseInt(orderBId),
          messages: updatedMessages,
          llm_model: model || undefined,
          llm_provider: provider || undefined,
          language: reportLanguage,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const payload = line.slice(6);
            try {
              const parsed = JSON.parse(payload);
              if (parsed.type === "token" && parsed.content) {
                setChatMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === "assistant") {
                    updated[updated.length - 1] = { ...last, content: last.content + parsed.content };
                  }
                  return updated;
                });
              } else if (parsed.type === "error") {
                setChatMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === "assistant") {
                    updated[updated.length - 1] = { ...last, content: last.content + `\n\n**Error:** ${parsed.message}` };
                  }
                  return updated;
                });
              }
            } catch {}
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== "AbortError") {
        setChatMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === "assistant") {
            updated[updated.length - 1] = { ...last, content: `**Error:** ${(err as Error).message}` };
          }
          return updated;
        });
      }
    } finally {
      setChatStreaming(false);
      chatAbortRef.current = null;
    }
  }, [chatInput, chatMessages, orderAId, orderBId, selectedModel, chatStreaming]);

  /* Persist chat messages to DB whenever they change (debounced) */
  useEffect(() => {
    if (!orderAId || !orderBId || chatMessages.length === 0 || !savedReportId) return;
    const timer = setTimeout(() => {
      fetch("/api/compare/save-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({
          order_id_a: parseInt(orderAId),
          order_id_b: parseInt(orderBId),
          chat_messages: chatMessages,
        }),
      }).catch(() => { /* ignore */ });
    }, 1000);
    return () => clearTimeout(timer);
  }, [chatMessages, orderAId, orderBId, savedReportId]);

  useEffect(() => { fetchMetadata(); }, [fetchMetadata]);

  /* Load saved report from DB on mount */
  useEffect(() => {
    if (!orderAId || !orderBId) return;
    fetch(`/api/compare/saved?a=${orderAId}&b=${orderBId}`, {
      headers: { ...getAuthHeader() },
    })
      .then((r) => {
        if (r.status === 401) {
          localStorage.removeItem("ptm-token");
          window.location.href = "/login";
          return null;
        }
        if (r.status === 404) return null;
        return r.json();
      })
      .then((d) => {
        if (d && d.report_text) {
          setReport(d.report_text);
          setSavedReportId(d.id);
          if (d.chat_messages?.length > 0) setChatMessages(d.chat_messages);
          const kst = new Date(d.updated_at + "Z").toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
          setReportSavedAt(kst);
        }
      })
      .catch(() => { /* no saved report */ });
  }, [orderAId, orderBId]);

  /* Auto-start streaming only when no saved report exists */
  useEffect(() => {
    if (metadata && !report && !streaming) {
      streamReport();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metadata, report]);

  /* Scroll chat to bottom */
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  /* Cleanup on unmount */
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
      if (chatAbortRef.current) chatAbortRef.current.abort();
    };
  }, []);

  // Build model options for selector
  const modelOptions: { value: string; label: string; group: string }[] = [];
  // Ollama models from DB
  llmModels.filter((m) => m.provider === "ollama").forEach((m) => {
    modelOptions.push({ value: `ollama:${m.model_id}`, label: m.name, group: "Ollama (Local)" });
  });
  // Cloud models
  (Object.keys(CLOUD_MODEL_PRESETS) as CloudProvider[]).forEach((provider) => {
    // Check if this provider has a registered key in llmModels
    const hasProvider = llmModels.some((m: LlmModelOption) => m.provider === provider);
    if (hasProvider) {
      CLOUD_MODEL_PRESETS[provider].forEach((preset: { id: string; name: string }) => {
        modelOptions.push({
          value: `${provider}:${preset.id}`,
          label: preset.name,
          group: provider.charAt(0).toUpperCase() + provider.slice(1),
        });
      });
    }
  });

  if (!orderAId || !orderBId) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <AlertCircle className="h-12 w-12 text-muted-foreground/40" />
        <p className="text-muted-foreground">Select two completed orders from the Order List to compare.</p>
        <Button variant="outline" asChild>
          <Link to="/admin/orders"><ArrowLeft className="mr-2 h-4 w-4" />Back to Orders</Link>
        </Button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-2 gap-4"><Skeleton className="h-24" /><Skeleton className="h-24" /></div>
        <Skeleton className="h-[400px]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <AlertCircle className="h-12 w-12 text-destructive/60" />
        <p className="text-destructive font-medium">{error}</p>
        <Button variant="outline" asChild>
          <Link to="/admin/orders"><ArrowLeft className="mr-2 h-4 w-4" />Back to Orders</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/admin/orders"><ArrowLeft className="h-4 w-4" /></Link>
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
              <GitCompareArrows className="h-6 w-6 text-primary" />
              Comparative Analysis
            </h1>
            <p className="text-sm text-muted-foreground">Cross-order PTM comparison</p>
          </div>
        </div>
      </div>

      {/* Order Info Cards */}
      {metadata && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <OrderInfoCard order={metadata.order_a} />
          <OrderInfoCard order={metadata.order_b} />
        </div>
      )}

      {/* Summary Statistics */}
      {metadata && (
        <div className="flex flex-wrap gap-3 justify-center">
          <SummaryCard label="Shared Genes" value={metadata.shared_genes} />
          <SummaryCard label="Unique to A" value={metadata.unique_a_genes} sub={metadata.order_a.order_code} />
          <SummaryCard label="Unique to B" value={metadata.unique_b_genes} sub={metadata.order_b.order_code} />
          <SummaryCard label="Shared Sites" value={metadata.shared_sites} />
          <SummaryCard label="Unique Sites A" value={metadata.unique_a_sites} sub={metadata.order_a.order_code} />
          <SummaryCard label="Unique Sites B" value={metadata.unique_b_sites} sub={metadata.order_b.order_code} />
        </div>
      )}

      {/* LLM Model Selector + User Instructions */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Analysis Settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Model Selector + Language */}
          <div className="flex items-center gap-4 flex-wrap">
            <label className="text-sm font-medium text-muted-foreground whitespace-nowrap">LLM Model</label>
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger className="w-[280px]">
                <SelectValue placeholder="Select model..." />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    <span className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[9px] px-1">{opt.group}</Badge>
                      {opt.label}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="flex items-center gap-2 ml-auto">
              <label className="text-sm font-medium text-muted-foreground whitespace-nowrap">Language</label>
              <Select value={reportLanguage} onValueChange={(v: "ko" | "en") => setReportLanguage(v)}>
                <SelectTrigger className="w-[120px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ko">한국어</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* User Instructions */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-muted-foreground">
              비교 분석 주요 요지 (Focus Points)
            </label>
            <Textarea
              placeholder="비교 분석 시 집중할 내용을 입력하세요. 여러 문장 입력 가능합니다.&#10;예: 두 물질의 ERK/MAPK pathway 활성화 차이를 중점적으로 분석해줘.&#10;예: AKT substrate의 temporal dynamics가 어떻게 다른지 비교해줘."
              value={userInstructions}
              onChange={(e) => setUserInstructions(e.target.value)}
              rows={3}
              className="resize-y"
            />
          </div>

          {/* Generate Button */}
          <div className="flex justify-end">
            <Button
              onClick={streamReport}
              disabled={streaming}
              size="sm"
            >
              <RefreshCw className={`h-4 w-4 mr-1 ${streaming ? "animate-spin" : ""}`} />
              {streaming ? "Generating..." : report ? "Regenerate Report" : "Generate Report"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Comparative Report (Streaming Markdown) */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2 flex-wrap">
            Comparative Report
            {streaming && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
            {!streaming && report && (
              <Badge variant="secondary" className="text-[10px]">
                {parseModelValue(selectedModel).model || "default"}
              </Badge>
            )}
            {!streaming && reportSavedAt && (
              <span className="text-xs text-muted-foreground font-normal ml-auto flex items-center gap-1">
                <span className="text-green-500">●</span> 저장됨 {reportSavedAt}
              </span>
            )}
            {!streaming && report && reportSavedAt && (
              <Button
                variant="outline"
                size="sm"
                className="ml-2 gap-1.5"
                disabled={pdfExporting}
                onClick={async () => {
                  if (!orderAId || !orderBId) return;
                  setPdfExporting(true);
                  try {
                    const res = await fetch("/api/compare/export-pdf", {
                      method: "POST",
                      headers: { "Content-Type": "application/json", ...getAuthHeader() },
                      body: JSON.stringify({ order_id_a: Number(orderAId), order_id_b: Number(orderBId) }),
                    });
                    if (!res.ok) {
                      const err = await res.json().catch(() => ({ detail: "PDF 생성 실패" }));
                      alert(err.detail || "PDF 생성에 실패했습니다.");
                      return;
                    }
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    const disposition = res.headers.get("Content-Disposition");
                    const filenameMatch = disposition?.match(/filename="?([^"]+)"?/);
                    a.href = url;
                    a.download = filenameMatch?.[1] || "comparative_report.pdf";
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                  } catch (e) {
                    alert("PDF 내보내기 중 오류가 발생했습니다.");
                  } finally {
                    setPdfExporting(false);
                  }
                }}
              >
                {pdfExporting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <FileDown className="h-3.5 w-3.5" />
                )}
                PDF
              </Button>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="prose prose-sm dark:prose-invert max-w-none">
            {report ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
            ) : streaming ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Analyzing and comparing two orders...</span>
              </div>
            ) : (
              <p className="text-muted-foreground">Report will appear here after generation.</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Q&A Chat Panel */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            Follow-up Q&A
            <span className="text-xs text-muted-foreground font-normal ml-2">
              비교 결과에 대해 추가 질문을 할 수 있습니다 (데이터 기반 답변)
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Chat Messages */}
          {chatMessages.length > 0 && (
            <div className="max-h-[500px] overflow-y-auto space-y-4 border rounded-lg p-4 bg-muted/20">
              {chatMessages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[85%] rounded-lg px-4 py-2 ${
                      msg.role === "user"
                        ? "bg-primary text-primary-foreground"
                        : "bg-card border"
                    }`}
                  >
                    {msg.role === "assistant" ? (
                      <div className="prose prose-sm dark:prose-invert max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content || "..."}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    )}
                  </div>
                </div>
              ))}
              {chatStreaming && (
                <div className="flex justify-start">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
          )}

          {/* Chat Input */}
          <div className="flex gap-2">
            <Textarea
              placeholder="비교 결과에 대해 질문하세요...&#10;예: ERK pathway가 두 물질에서 공통으로 활성화되는 이유는?&#10;예: Drug A에서만 나타나는 AKT substrate들의 기능은?"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendChatMessage();
                }
              }}
              rows={2}
              className="resize-y flex-1"
              disabled={chatStreaming}
            />
            <Button
              onClick={sendChatMessage}
              disabled={!chatInput.trim() || chatStreaming}
              size="icon"
              className="h-auto"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
