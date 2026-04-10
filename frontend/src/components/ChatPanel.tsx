/**
 * ChatPanel — Context-aware AI chat for PTM analysis results.
 *
 * Streams responses from the backend via SSE, renders markdown,
 * and automatically passes current view state as context.
 * Chat history is persisted to DB and loaded on mount.
 *
 * Model: exaone-deep:7.8b (fixed, Ollama)
 */

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  MessageSquare,
  Send,
  X,
  Loader2,
  Bot,
  User,
  Trash2,
  ChevronDown,
  Database,
  Info,
  Sparkles,
  AlertCircle,
  History,
  PanelRightClose,
  PanelRightOpen,
  FileOutput,
} from "lucide-react";
import { Button } from "@/components/ui/button";

// ── Types ───────────────────────────────────────────────────────────────────

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  stats?: { tokens: number; tokens_per_sec: number };
  error?: boolean;
}

interface RagCollection {
  id: number;
  name: string;
  tier: string;
  document_count: number;
}

interface ContextInfo {
  model: string;
  available_context: {
    report: boolean;
    enriched_ptms: boolean;
    kinase_modules: boolean;
    comovement: boolean;
    methodology: boolean;
  };
  enriched_ptm_count: number;
  rag_collections: RagCollection[];
}

interface ViewContext {
  active_tab?: string;
  checked_ptms?: string[];
  selected_module?: number | null;
  metric?: string;
  trend_filter?: string;
  activity_filter?: string;
}

interface ChatPanelProps {
  orderId: number;
  viewContext?: ViewContext;
  isOpen: boolean;
  onToggle: () => void;
}

// ── Component ───────────────────────────────────────────────────────────────

export default function ChatPanel({ orderId, viewContext, isOpen, onToggle }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [contextInfo, setContextInfo] = useState<ContextInfo | null>(null);
  const [selectedCollections, setSelectedCollections] = useState<number[]>([]);
  const [showCollections, setShowCollections] = useState(false);
  const [showContextInfo, setShowContextInfo] = useState(false);
  const [responseLang, setResponseLang] = useState<"auto" | "ko" | "en">("auto");
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [applyingInsights, setApplyingInsights] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load context info on mount
  useEffect(() => {
    if (!orderId) return;
    const token = localStorage.getItem("ptm-token");
    fetch(`/api/orders/${orderId}/chat-context-info`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.json())
      .then((data) => setContextInfo(data))
      .catch(() => {});
  }, [orderId]);

  // Load chat history from DB on mount
  useEffect(() => {
    if (!orderId || historyLoaded) return;
    const token = localStorage.getItem("ptm-token");
    fetch(`/api/orders/${orderId}/chat-history`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.messages && data.messages.length > 0) {
          const loaded: ChatMessage[] = data.messages.map((m: any) => ({
            role: m.role,
            content: m.content,
            timestamp: m.created_at ? new Date(m.created_at).getTime() : Date.now(),
          }));
          setMessages(loaded);
        }
        setHistoryLoaded(true);
      })
      .catch(() => {
        setHistoryLoaded(true);
      });
  }, [orderId, historyLoaded]);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 200);
    }
  }, [isOpen]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    const userMsg: ChatMessage = { role: "user", content: text, timestamp: Date.now() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);

    // Prepare conversation history (exclude current message)
    const history = messages.map((m) => ({ role: m.role, content: m.content }));

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const token = localStorage.getItem("ptm-token");
      const response = await fetch(`/api/orders/${orderId}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
          body: JSON.stringify({
          message: text,
          conversation_history: history,
          view_context: viewContext || {},
          rag_collection_ids: selectedCollections.length > 0 ? selectedCollections : null,
          response_language: responseLang,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let assistantContent = "";
      let stats: { tokens: number; tokens_per_sec: number } | undefined;

      // Add empty assistant message that we'll update
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "", timestamp: Date.now() },
      ]);

      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);

            if (data.error) {
              assistantContent += `\n\n**Error:** ${data.error}`;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: assistantContent,
                  error: true,
                };
                return updated;
              });
              break;
            }

            if (data.content) {
              assistantContent += data.content;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: assistantContent,
                };
                return updated;
              });
            }

            if (data.done && data.stats) {
              stats = data.stats;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: assistantContent,
                  stats,
                };
                return updated;
              });
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err: any) {
      if (err.name === "AbortError") {
        // User cancelled
        setMessages((prev) => {
          const updated = [...prev];
          if (updated.length > 0 && updated[updated.length - 1].role === "assistant") {
            updated[updated.length - 1].content += "\n\n*[Cancelled]*";
          }
          return updated;
        });
      } else {
        setMessages((prev) => [
          ...prev.filter((m) => !(m.role === "assistant" && m.content === "")),
          {
            role: "assistant",
            content: `**Connection Error:** ${err.message}\n\nOllama 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.`,
            timestamp: Date.now(),
            error: true,
          },
        ]);
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [input, isStreaming, messages, orderId, viewContext, selectedCollections, responseLang]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = useCallback(async () => {
    // Clear from DB
    const token = localStorage.getItem("ptm-token");
    try {
      await fetch(`/api/orders/${orderId}/chat-history`, {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch {
      // Continue clearing UI even if DB delete fails
    }
    setMessages([]);
  }, [orderId]);

  const stopStreaming = () => {
    abortRef.current?.abort();
  };

  const applyToReport = useCallback(async () => {
    if (messages.length === 0) return;
    setApplyingInsights(true);
    const token = localStorage.getItem("ptm-token");
    try {
      const resp = await fetch(`/api/orders/${orderId}/chat/apply-to-report`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: "{}",
      });
      const data = await resp.json();
      if (!resp.ok) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `⚠️ ${data.detail || "Failed to extract insights"}`, timestamp: Date.now(), error: true },
        ]);
        return;
      }
      const insightCount = data.extracted?.insights?.length || 0;
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `📋 **Report Insight Extraction Complete**\n\n${data.message}\n\n` +
            (data.extracted?.insights?.map((i: { type: string; content: string; target_section: string; priority: string }, idx: number) =>
              `${idx + 1}. **[${i.type}]** ${i.content} → _${i.target_section}_ (${i.priority})`
            ).join("\n") || "") +
            (data.extracted?.additional_questions?.length
              ? `\n\n**New Questions:**\n${data.extracted.additional_questions.map((q: string) => `- ${q}`).join("\n")}`
              : ""),
          timestamp: Date.now(),
        },
      ]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "⚠️ Failed to apply insights to report.", timestamp: Date.now(), error: true },
      ]);
    } finally {
      setApplyingInsights(false);
    }
  }, [orderId, messages]);

  const toggleCollection = (id: number) => {
    setSelectedCollections((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  // Context availability badges
  const contextBadges = useMemo(() => {
    if (!contextInfo) return [];
    const ctx = contextInfo.available_context;
    return [
      { key: "report", label: "Report", available: ctx.report },
      { key: "ptms", label: `PTMs (${contextInfo.enriched_ptm_count})`, available: ctx.enriched_ptms },
      { key: "kinase", label: "Kinase Modules", available: ctx.kinase_modules },
      { key: "comovement", label: "Co-movement", available: ctx.comovement },
      { key: "methodology", label: "Methodology", available: ctx.methodology },
    ];
  }, [contextInfo]);

  if (!isOpen) {
    return (
      <div
        className="flex flex-col items-center py-3 gap-2 border-l border-border bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors w-10"
        onClick={onToggle}
        title="Open AI Chat"
      >
        <PanelRightOpen className="h-4 w-4 text-primary shrink-0" />
        <span className="text-[11px] font-semibold text-primary [writing-mode:vertical-lr]">
          POTATO AI
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full border-l border-border bg-background">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 -ml-1"
            onClick={onToggle}
            title="Collapse panel"
          >
            <PanelRightClose className="h-4 w-4 text-muted-foreground" />
          </Button>
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="font-semibold text-sm">POTATO AI</span>
          {historyLoaded && messages.length > 0 && (
            <span className="text-[10px] text-muted-foreground flex items-center gap-1">
              <History className="h-3 w-3" />
              {messages.length} msgs
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => setShowContextInfo(!showContextInfo)}
            title="Context info"
          >
            <Info className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={applyToReport}
            title="Apply insights to report"
            disabled={isStreaming || applyingInsights || messages.length === 0}
          >
            {applyingInsights
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <FileOutput className="h-3.5 w-3.5" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={clearChat}
            title="Clear chat history"
            disabled={isStreaming}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Context Info Panel (collapsible) */}
      {showContextInfo && (
        <div className="px-4 py-3 border-b border-border bg-muted/20 space-y-2">
          <p className="text-[11px] font-medium text-muted-foreground">Available Context:</p>
          <div className="flex flex-wrap gap-1.5">
            {contextBadges.map((b) => (
              <span
                key={b.key}
                className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                  b.available
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                    : "bg-zinc-100 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-500 line-through"
                }`}
              >
                {b.label}
              </span>
            ))}
          </div>

          {/* RAG Collection selector */}
          {contextInfo && contextInfo.rag_collections.length > 0 && (
            <div>
              <button
                className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
                onClick={() => setShowCollections(!showCollections)}
              >
                <Database className="h-3 w-3" />
                RAG Collections ({selectedCollections.length}/{contextInfo.rag_collections.length})
                <ChevronDown
                  className={`h-3 w-3 transition-transform ${showCollections ? "rotate-180" : ""}`}
                />
              </button>
              {showCollections && (
                <div className="mt-1 space-y-1 max-h-32 overflow-y-auto">
                  {contextInfo.rag_collections.map((c) => (
                    <label
                      key={c.id}
                      className="flex items-center gap-2 text-[11px] cursor-pointer hover:bg-muted/50 rounded px-1 py-0.5"
                    >
                      <input
                        type="checkbox"
                        checked={selectedCollections.includes(c.id)}
                        onChange={() => toggleCollection(c.id)}
                        className="rounded h-3 w-3"
                      />
                      <span className="truncate">{c.name}</span>
                      <span className="text-muted-foreground ml-auto flex-shrink-0">
                        {c.document_count} docs
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-3 py-8">
            <div className="rounded-full bg-primary/10 p-3">
              <MessageSquare className="h-6 w-6 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium">POTATO AI</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-[260px]">
                분석 결과에 대해 질문하세요. Report, Kinase Module, Signal Flow, Evidence Scoring 데이터를 참조하여 답변합니다.
              </p>
            </div>
            <div className="space-y-1.5 w-full max-w-[280px]">
              {[
                "이 receptor는 얼마나 신뢰할 만해?",
                "Signal flow에서 주요 kinase는?",
                "Temporal pattern의 생물학적 의미는?",
              ].map((q) => (
                <button
                  key={q}
                  className="w-full text-left text-[11px] px-3 py-2 rounded-lg border border-border hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => {
                    setInput(q);
                    setTimeout(() => inputRef.current?.focus(), 50);
                  }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-2.5 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            {msg.role === "assistant" && (
              <div className="flex-shrink-0 mt-0.5">
                <div className={`rounded-full p-1.5 ${msg.error ? "bg-destructive/10" : "bg-primary/10"}`}>
                  {msg.error ? (
                    <AlertCircle className="h-3.5 w-3.5 text-destructive" />
                  ) : (
                    <Bot className="h-3.5 w-3.5 text-primary" />
                  )}
                </div>
              </div>
            )}

            <div
              className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm ${
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : msg.error
                  ? "bg-destructive/5 border border-destructive/20"
                  : "bg-muted/60"
              }`}
            >
              {msg.role === "assistant" ? (
                <div className="prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content || (isStreaming && i === messages.length - 1 ? "..." : "")}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}

              {/* Stats footer */}
              {msg.stats && (
                <div className="mt-2 pt-1.5 border-t border-border/30 text-[10px] text-muted-foreground flex items-center gap-2">
                  <span>{msg.stats.tokens} tokens</span>
                  <span>{msg.stats.tokens_per_sec} tok/s</span>
                </div>
              )}
            </div>

            {msg.role === "user" && (
              <div className="flex-shrink-0 mt-0.5">
                <div className="rounded-full bg-muted p-1.5">
                  <User className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
              </div>
            )}
          </div>
        ))}

        {/* Streaming indicator */}
        {isStreaming && messages.length > 0 && messages[messages.length - 1].content === "" && (
          <div className="flex gap-2.5">
            <div className="flex-shrink-0 mt-0.5">
              <div className="rounded-full bg-primary/10 p-1.5">
                <Bot className="h-3.5 w-3.5 text-primary animate-pulse" />
              </div>
            </div>
            <div className="bg-muted/60 rounded-xl px-3.5 py-2.5">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Thinking...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-border px-4 py-3 bg-muted/10">
        {isStreaming && (
          <div className="flex justify-center mb-2">
            <Button variant="outline" size="sm" onClick={stopStreaming} className="text-xs h-7">
              <X className="h-3 w-3 mr-1" /> Stop generating
            </Button>
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="분석 결과에 대해 질문하세요..."
            className="flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 min-h-[40px] max-h-[120px]"
            rows={1}
            disabled={isStreaming}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = "auto";
              target.style.height = Math.min(target.scrollHeight, 120) + "px";
            }}
          />
          <Button
            size="icon"
            className="h-10 w-10 flex-shrink-0"
            onClick={sendMessage}
            disabled={!input.trim() || isStreaming}
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex items-center justify-between mt-1.5">
          <div className="flex items-center gap-1">
            {(["auto", "ko", "en"] as const).map((lang) => (
              <button
                key={lang}
                onClick={() => setResponseLang(lang)}
                className={`text-[10px] px-2 py-0.5 rounded-full transition-colors ${
                  responseLang === lang
                    ? "bg-primary text-primary-foreground font-medium"
                    : "bg-muted text-muted-foreground hover:text-foreground"
                }`}
              >
                {lang === "auto" ? "Auto" : lang === "ko" ? "한국어" : "English"}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground">
            대화 내용은 자동 저장됩니다.
          </p>
        </div>
      </div>
    </div>
  );
}
