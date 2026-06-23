/**
 * MekiiChat — Context-aware AI chat for general users.
 * 
 * Upgraded from Potato AI (ChatPanel.tsx):
 * - Always visible in the result view (not collapsible side panel)
 * - Provides executive summary on analysis completion
 * - Answers questions about the user's data using RAG + analysis results
 * - Highlights relevant visualizations based on conversation
 * 
 * Model: 27B+ (configurable by admin)
 * Context: Order data + enriched PTM data + ChromaDB RAG + Report
 */
import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Order } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sparkles,
  Send,
  Loader2,
  Bot,
  User,
  Trash2,
  RotateCcw,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────
interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  stats?: { tokens: number; tokens_per_sec: number };
}

interface MekiiChatProps {
  orderId: number;
  order: Order | null;
  activeTab: string;
}

// ── Component ──────────────────────────────────────────────────────────────
export default function MekiiChat({ orderId, order, activeTab }: MekiiChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Load chat history on mount
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const res = await fetch(`/api/orders/${orderId}/chat/history`, {
          headers: { Authorization: `Bearer ${localStorage.getItem("ptm-token")}` },
        });
        if (res.ok) {
          const history: ChatMessage[] = await res.json();
          setMessages(history);
        }
      } catch {
        // No history yet, that's fine
      }
    };
    loadHistory();
  }, [orderId]);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamContent]);

  // Provide initial greeting when analysis is completed and no messages exist
  useEffect(() => {
    if (order?.status === "completed" && messages.length === 0) {
      setMessages([
        {
          role: "assistant",
          content: `분석이 완료되었습니다! **${order.project_name}** 결과에 대해 궁금한 점을 물어보세요.\n\n예시 질문:\n- "어떤 kinase가 가장 활성화되었어?"\n- "MAPK 경로에서 어떤 변화가 있었어?"\n- "이 결과를 논문에 쓸 때 어떤 포인트를 잡으면 좋을까?"`,
          timestamp: Date.now(),
        },
      ]);
    }
  }, [order?.status, order?.project_name]);

  // ── Send message ─────────────────────────────────────────────────────────
  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg: ChatMessage = { role: "user", content: text, timestamp: Date.now() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setStreaming(true);
    setStreamContent("");

    try {
      const res = await fetch(`/api/orders/${orderId}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("ptm-token")}`,
        },
        body: JSON.stringify({
          message: text,
          context: {
            active_tab: activeTab,
            order_status: order?.status,
            ptm_type: order?.ptm_type,
            species: order?.species,
          },
        }),
      });

      if (!res.ok) throw new Error("Chat request failed");

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let fullContent = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              const data = line.slice(6);
              if (data === "[DONE]") break;
              try {
                const parsed = JSON.parse(data);
                if (parsed.content) {
                  fullContent += parsed.content;
                  setStreamContent(fullContent);
                }
              } catch {
                // Skip malformed JSON
              }
            }
          }
        }
      }

      const assistantMsg: ChatMessage = {
        role: "assistant",
        content: fullContent,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setStreamContent("");
    } catch (err) {
      const errorMsg: ChatMessage = {
        role: "assistant",
        content: "죄송합니다. 응답 생성 중 오류가 발생했습니다. 다시 시도해 주세요.",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setStreaming(false);
    }
  }, [input, streaming, orderId, activeTab, order]);

  // ── Clear chat ───────────────────────────────────────────────────────────
  const clearChat = async () => {
    try {
      await fetch(`/api/orders/${orderId}/chat/history`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${localStorage.getItem("ptm-token")}` },
      });
    } catch {}
    setMessages([]);
  };

  // ── Key handler ──────────────────────────────────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
          </div>
          <span className="font-semibold text-sm">Mekii AI</span>
          <Badge variant="secondary" className="text-[9px]">Beta</Badge>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={clearChat} title="Clear chat">
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2 ${msg.role === "user" ? "justify-end" : ""}`}>
            {msg.role === "assistant" && (
              <div className="h-6 w-6 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                <Bot className="h-3 w-3 text-primary" />
              </div>
            )}
            <div
              className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted"
              }`}
            >
              {msg.role === "assistant" ? (
                <div className="prose prose-sm dark:prose-invert max-w-none [&>p]:mb-2 [&>ul]:mb-2 [&>ol]:mb-2">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
            {msg.role === "user" && (
              <div className="h-6 w-6 rounded-full bg-secondary flex items-center justify-center shrink-0 mt-0.5">
                <User className="h-3 w-3" />
              </div>
            )}
          </div>
        ))}

        {/* Streaming indicator */}
        {streaming && streamContent && (
          <div className="flex gap-2">
            <div className="h-6 w-6 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
              <Bot className="h-3 w-3 text-primary" />
            </div>
            <div className="max-w-[85%] rounded-xl px-3 py-2 text-sm bg-muted">
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {streamContent}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}

        {streaming && !streamContent && (
          <div className="flex gap-2 items-center">
            <div className="h-6 w-6 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
              <Bot className="h-3 w-3 text-primary" />
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Thinking...
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t p-3 shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your analysis results..."
            rows={1}
            className="flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring min-h-[36px] max-h-[120px]"
            style={{ height: "auto", overflow: "hidden" }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = "auto";
              target.style.height = Math.min(target.scrollHeight, 120) + "px";
            }}
          />
          <Button
            size="icon"
            disabled={!input.trim() || streaming}
            onClick={sendMessage}
            className="h-9 w-9 shrink-0"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="text-[10px] text-muted-foreground mt-1.5 text-center">
          Mekii AI uses your analysis data + ChromaDB references for context-aware answers
        </p>
      </div>
    </div>
  );
}
