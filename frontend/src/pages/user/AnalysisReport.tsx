/**
 * AnalysisReport — Result visualization + Mekii AI chat for general users.
 * 
 * Left panel: Visualization tabs (Vector Plot, Kinase Heatmap, Cascade, Timeline, Modules)
 * Right panel: Mekii AI Chat (context-aware, always visible)
 */
import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useOrderProgress } from "@/hooks/useSSE";
import type { Order } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Progress } from "@/components/ui/progress";
// Separator and Skeleton removed (unused)
import MekiiChat from "@/components/user/MekiiChat";
import { AnalysisStatisticsTab } from "@/components/AnalysisStatisticsTab";
import CrossTalkVennDiagram from "@/components/CrossTalkVennDiagram";
import CrossTalkHeatmap from "@/components/CrossTalkHeatmap";
import CrossTalkSequentialGating from "@/components/CrossTalkSequentialGating";
import SignalPropagationTimeline from "@/components/SignalPropagationTimeline";
import {
  ArrowLeft,
  Loader2,
  CheckCircle2,
  XCircle,
  StopCircle,
  Clock,
  ScatterChart as ScatterChartIcon,
  Activity,
  Network,
  Timer,
  Boxes,
  FileText,
  Download,
  MessageSquare,
  PanelRightOpen,
  PanelRightClose,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

const SCATTER_PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];

export default function AnalysisReport() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

  const isRunningCheck = order ? !["completed", "failed", "cancelled"].includes(order.status) : false;
  const { progress } = useOrderProgress(isRunningCheck ? Number(id) : null);

  // Update order state from SSE progress events
  useEffect(() => {
    if (progress && order) {
      setOrder((prev) =>
        prev
          ? {
              ...prev,
              progress_pct:
                progress.progress_pct != null && !Number.isNaN(Number(progress.progress_pct))
                  ? Number(progress.progress_pct)
                  : prev.progress_pct,
              current_stage: progress.stage || prev.current_stage,
              stage_detail: progress.message || prev.stage_detail,
              status: progress.status === "failed" ? "failed" : prev.status,
            }
          : prev,
      );
    }
  }, [progress]);

  // Fetch order data
  useEffect(() => {
    if (!id) return;
    const fetchOrder = async () => {
      try {
        const data = await api.get<Order>(`/orders/${id}`);
        setOrder(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    fetchOrder();

    // Poll for updates if not completed
    const interval = setInterval(async () => {
      try {
        const data = await api.get<Order>(`/orders/${id}`);
        setOrder(data);
        if (data.status === "completed" || data.status === "failed" || data.status === "cancelled") {
          clearInterval(interval);
        }
      } catch {
        clearInterval(interval);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [id]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!order) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <XCircle className="h-12 w-12 text-muted-foreground" />
        <p className="text-muted-foreground">Analysis not found</p>
        <Button variant="outline" onClick={() => navigate("/app")}>
          Back to Dashboard
        </Button>
      </div>
    );
  }

  const isRunning = !["completed", "failed", "cancelled"].includes(order.status);
  const isCompleted = order.status === "completed";
  const isCancelled = order.status === "cancelled";

  return (
    <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
      {/* Left: Visualization Panel */}
      <div className={`flex-1 overflow-y-auto p-6 ${chatOpen ? "" : ""}`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => navigate("/app")}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div>
              <h1 className="text-xl font-bold tracking-tight">{order.project_name}</h1>
              <div className="flex items-center gap-2 mt-0.5">
                <Badge variant="outline" className="text-[10px]">
                  {order.ptm_type === "ubiquitylation" ? "Ubiquitylation" : "Phosphorylation"}
                </Badge>
                <span className="text-xs text-muted-foreground">{order.species}</span>
                <StatusBadge status={order.status} />
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isCompleted && order.result_files && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1"
                onClick={() => {
                  const rf = order.result_files as any;
                  const reports: string[] = rf?.report_files || [];
                  const allFiles: string[] = rf?.all_files || [];
                  // Prefer report files, fallback to all files
                  const toDownload = reports.length > 0 ? reports : allFiles;
                  if (toDownload.length === 0) {
                    alert("No report files available yet.");
                    return;
                  }
                  toDownload.forEach((filename: string) => {
                    api.downloadFile(
                      `/orders/${order.id}/files/${encodeURIComponent(filename)}`,
                      filename,
                    );
                  });
                }}
              >
                <Download className="h-3.5 w-3.5" />
                Report
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setChatOpen(!chatOpen)}
              title={chatOpen ? "Hide Mekii AI" : "Show Mekii AI"}
            >
              {chatOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        {/* Running State */}
        {isRunning && (
          <Card className="mb-6">
            <CardContent className="py-6">
              {/* Stage pipeline indicator */}
              <div className="flex items-center justify-between mb-5">
                {[
                  { key: "registered", label: "시작 중", desc: "분석 준비 중" },
                  { key: "preprocessing", label: "전처리", desc: "데이터 정제 및 PTM 정량" },
                  { key: "rag_enrichment", label: "AI 분석", desc: "문헌 검색 및 생물학적 해석" },
                  { key: "report_generation", label: "보고서 생성", desc: "종합 보고서 작성 중" },
                ].map((stage, idx, arr) => {
                  const stageOrder = ["registered", "queued", "preprocessing", "rag_enrichment", "report_generation"];
                  const currentIdx = stageOrder.indexOf(order.current_stage || order.status);
                  const thisIdx = stageOrder.indexOf(stage.key);
                  const isActive = thisIdx === currentIdx;
                  const isDone = thisIdx < currentIdx;
                  return (
                    <div key={stage.key} className="flex items-center flex-1">
                      <div className="flex flex-col items-center flex-1">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
                          isDone ? "bg-green-500/20 text-green-400 ring-2 ring-green-500/40" :
                          isActive ? "bg-primary/20 text-primary ring-2 ring-primary animate-pulse" :
                          "bg-muted text-muted-foreground"
                        }`}>
                          {isDone ? <CheckCircle2 className="h-4 w-4" /> : idx + 1}
                        </div>
                        <span className={`text-[11px] mt-1.5 text-center leading-tight ${
                          isActive ? "text-primary font-medium" : isDone ? "text-green-400" : "text-muted-foreground"
                        }`}>{stage.label}</span>
                      </div>
                      {idx < arr.length - 1 && (
                        <div className={`h-0.5 flex-1 mx-1 rounded ${isDone ? "bg-green-500/40" : "bg-muted"}`} />
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Current status detail */}
              <div className="flex items-center gap-3 mb-3">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                <div>
                  <p className="font-medium">
                    {(() => {
                      const s = order.current_stage || order.status;
                      const labels: Record<string, string> = {
                        registered: "분석을 시작하고 있습니다...",
                        queued: "분석 파이프라인을 준비하고 있습니다...",
                        preprocessing: "데이터를 전처리하고 있습니다",
                        rag_enrichment: "AI가 각 PTM 사이트를 심층 분석하고 있습니다",
                        report_generation: "AI가 종합 보고서를 작성하고 있습니다",
                      };
                      return labels[s] || "분석을 진행하고 있습니다...";
                    })()}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {(() => {
                      const s = order.current_stage || order.status;
                      const detail = order.stage_detail || "";
                      // Transform backend messages to user-friendly Korean
                      if (detail) {
                        return friendlyMessage(s, detail);
                      }
                      const hints: Record<string, string> = {
                        registered: "잠시만 기다려주세요. 자동으로 시작됩니다",
                        queued: "곧 시작됩니다. 잠시만 기다려주세요",
                        preprocessing: "PTM을 정량하고 통계 분석을 수행합니다 (약 5-15분)",
                        rag_enrichment: "각 PTM 사이트별 생물학적 기능, 관련 논문, 신호전달 경로를 분석합니다 (약 10-30분)",
                        report_generation: "모든 분석 결과를 종합하여 보고서를 생성합니다 (약 5-10분)",
                      };
                      return hints[s] || "";
                    })()}
                  </p>
                </div>
              </div>
              {/* Sub-progress for PTM enrichment */}
              {(() => {
                const detail = order.stage_detail || "";
                const sub = parseSubProgress(detail);
                if (sub) {
                  return (
                    <div className="mb-3">
                      <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
                        <span>{sub.label}</span>
                        <span className="font-mono tabular-nums">{sub.done} / {sub.total}</span>
                      </div>
                      <Progress value={sub.pct} className="h-1.5" />
                    </div>
                  );
                }
                return null;
              })()}
              <Progress value={order.progress_pct} className="h-2" />
              <div className="flex items-center justify-between mt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive hover:bg-destructive/10 gap-1.5 h-7 px-2"
                  onClick={async () => {
                    if (!confirm("분석을 중단하시겠습니까? 이 작업은 되돌릴 수 없습니다.")) return;
                    try {
                      await api.post(`/orders/${order.id}/cancel`);
                      setOrder({ ...order, status: "cancelled" });
                    } catch (err) {
                      console.error("Cancel failed:", err);
                    }
                  }}
                >
                  <StopCircle className="h-3.5 w-3.5" />
                  분석 중단
                </Button>
                <p className="text-xs text-muted-foreground">{order.progress_pct}%</p>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Completed: Visualization Tabs */}
        {isCompleted && (
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="mb-4">
              <TabsTrigger value="overview" className="gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                Overview
              </TabsTrigger>
              <TabsTrigger value="vector" className="gap-1.5">
                <ScatterChartIcon className="h-3.5 w-3.5" />
                Vector Plot
              </TabsTrigger>
              <TabsTrigger value="kinase" className="gap-1.5">
                <Activity className="h-3.5 w-3.5" />
                Kinase Activity
              </TabsTrigger>
              <TabsTrigger value="cascade" className="gap-1.5">
                <Network className="h-3.5 w-3.5" />
                Cascade
              </TabsTrigger>
              <TabsTrigger value="timeline" className="gap-1.5">
                <Timer className="h-3.5 w-3.5" />
                Timeline
              </TabsTrigger>
              <TabsTrigger value="modules" className="gap-1.5">
                <Boxes className="h-3.5 w-3.5" />
                Modules
              </TabsTrigger>
            </TabsList>

            <TabsContent value="overview">
              <OverviewTab order={order} />
            </TabsContent>
            <TabsContent value="vector">
              <VectorPlotTab orderId={order.id} />
            </TabsContent>
            <TabsContent value="kinase">
              <KinaseActivityTab orderId={order.id} />
            </TabsContent>
            <TabsContent value="cascade">
              <CascadeTab orderId={order.id} order={order} />
            </TabsContent>
            <TabsContent value="timeline">
              <TimelineTab orderId={order.id} order={order} />
            </TabsContent>
            <TabsContent value="modules">
              <ModulesTab orderId={order.id} />
            </TabsContent>
          </Tabs>
        )}

        {/* Failed State */}
        {order.status === "failed" && (
          <Card className="border-destructive/30">
            <CardContent className="py-8 flex flex-col items-center">
              <XCircle className="h-12 w-12 text-destructive mb-3" />
              <h3 className="font-semibold mb-1">Analysis Failed</h3>
              <p className="text-sm text-muted-foreground text-center max-w-md">
                {order.error_message || "An unexpected error occurred during analysis."}
              </p>
              <Button variant="outline" className="mt-4" onClick={() => navigate("/app/new")}>
                Try Again
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Cancelled State */}
        {isCancelled && (
          <Card className="border-orange-500/30">
            <CardContent className="py-8 flex flex-col items-center">
              <StopCircle className="h-12 w-12 text-orange-500 mb-3" />
              <h3 className="font-semibold mb-1">분석이 중단되었습니다</h3>
              <p className="text-sm text-muted-foreground text-center max-w-md">
                사용자에 의해 분석이 취소되었습니다.
              </p>
              <Button variant="outline" className="mt-4" onClick={() => navigate("/app/new")}>
                새 분석 시작
              </Button>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Right: Mekii AI Chat Panel */}
      {chatOpen && (
        <div className="w-[400px] border-l bg-card flex flex-col shrink-0">
          <MekiiChat orderId={Number(id)} order={order} activeTab={activeTab} />
        </div>
      )}
    </div>
  );
}

// ── Progress Helpers ──────────────────────────────────────────────────────────

interface SubProgress {
  label: string;
  done: number;
  total: number;
  pct: number;
}

/**
 * Parse backend progress messages like "MAPK3 S204: 12 articles, 5 pathways (45/169)"
 * or "All 169 PTMs queued — processing (0/169)" into structured sub-progress.
 */
function parseSubProgress(message: string): SubProgress | null {
  // Pattern: "... (done/total)"
  const m = message.match(/\((\d+)\s*\/\s*(\d+)\)\s*$/);
  if (m) {
    const done = parseInt(m[1]);
    const total = parseInt(m[2]);
    if (!isNaN(done) && !isNaN(total) && total > 0) {
      return {
        label: `PTM 분석 진행`,
        done,
        total,
        pct: Math.round((done / total) * 100),
      };
    }
  }
  // Pattern: "label: done/total"
  const m2 = message.match(/^(.+?):\s*([\d,]+)\s*\/\s*([\d,]+)$/);
  if (m2) {
    const done = parseInt(m2[2].replace(/,/g, ""));
    const total = parseInt(m2[3].replace(/,/g, ""));
    if (!isNaN(done) && !isNaN(total) && total > 0) {
      return { label: m2[1].trim(), done, total, pct: Math.round((done / total) * 100) };
    }
  }
  return null;
}

/**
 * Transform backend technical messages into user-friendly Korean descriptions.
 * Hides RAG/LLM/technical jargon from end users.
 */
function friendlyMessage(stage: string, detail: string): string {
  if (!detail) return "";
  
  // ── Preprocessing stage ──
  if (stage === "preprocessing") {
    if (detail.includes("Loading input")) return "입력 파일을 불러오는 중...";
    if (detail.includes("PTM quantification")) {
      if (detail.includes("complete")) return "PTM 정량 분석 완료";
      if (detail.includes("skipped")) return "PTM 정량 분석 완료 (캐시 사용)";
      return "PTM 정량 분석 중...";
    }
    if (detail.includes("vector")) {
      if (detail.includes("complete") || detail.includes("generated")) return "PTM 벡터 시각화 완료";
      return "PTM 벡터 시각화 생성 중...";
    }
    if (detail.includes("enrichment") || detail.includes("domain") || detail.includes("motif")) {
      if (detail.includes("complete")) return "도메인/모티프 분석 완료";
      return "도메인 및 모티프 분석 중...";
    }
    if (detail.includes("biological") || detail.includes("Biological")) {
      if (detail.includes("complete")) return "생물학적 기능 분석 완료";
      return "생물학적 기능 분석 중...";
    }
    if (detail.includes("Preprocessing pipeline started")) return "전처리 파이프라인 시작";
    return detail.replace(/RAG|LLM|ChromaDB/gi, "AI").substring(0, 80);
  }

  // ── RAG Enrichment stage (shown as "AI 분석" to users) ──
  if (stage === "rag_enrichment") {
    if (detail.includes("pipeline started")) return "AI 심층 분석을 시작합니다...";
    if (detail.includes("Loading PTM vector")) return "분석 데이터를 불러오는 중...";
    if (detail.includes("PTMs selected")) {
      const match = detail.match(/(\d+) PTMs selected/);
      return match ? `${match[1]}개 PTM 사이트 선정 완료 — 분석 시작` : "PTM 사이트 선정 완료";
    }
    if (detail.includes("Starting literature") || detail.includes("enrichment")) {
      if (detail.includes("complete")) return "문헌 기반 분석 완료";
      if (detail.includes("Starting")) return "각 PTM별 문헌 및 경로 분석 시작...";
    }
    if (detail.includes("All") && detail.includes("PTMs queued")) {
      const match = detail.match(/All (\d+) PTMs/);
      return match ? `${match[1]}개 PTM 분석 대기열 등록 — 순차 처리 중` : "PTM 분석 대기열 등록 완료";
    }
    // Per-PTM database-first progress
    const sourceMatch = detail.match(/\[sources:\s*([^\]]+)\]\s*$/i);
    const sourceSummary = sourceMatch ? ` · ${sourceMatch[1]}` : "";
    const dbOnlyMatch = detail.match(/^([\w.-]+)\s+\w+\d+:\s*\[db_only\]\s*structured DB,\s*(\d+)\s*pathways,\s*PubMed skipped\s*\((\d+)\/(\d+)\)/i);
    if (dbOnlyMatch) {
      return `${dbOnlyMatch[1]} 분석 중 — 구조화 DB 경로 ${dbOnlyMatch[2]}개 확인, 논문 검색 생략 (${dbOnlyMatch[3]}/${dbOnlyMatch[4]})${sourceSummary}`;
    }
    const targetedMatch = detail.match(/^([\w.-]+)\s+\w+\d+:\s*\[(abstract_targeted|fulltext_escalated)\]\s*(\d+)\s*selected articles,\s*(\d+)\s*pathways\s*\((\d+)\/(\d+)\)/i);
    if (targetedMatch) {
      const routeLabel = targetedMatch[2].toLowerCase() === "fulltext_escalated" ? "논문 본문 검토" : "필요 문헌 검토";
      return `${targetedMatch[1]} 분석 중 — ${routeLabel} ${targetedMatch[3]}편, 경로 ${targetedMatch[4]}개 (${targetedMatch[5]}/${targetedMatch[6]})${sourceSummary}`;
    }
    // Legacy per-PTM progress: "GENE POS: N articles, M pathways (done/total)"
    const ptmMatch = detail.match(/^(\w+)\s+\w+\d+:\s*(\d+)\s*articles?,\s*(\d+)\s*pathways?\s*\((\d+)\/(\d+)\)/);
    if (ptmMatch) {
      return `${ptmMatch[1]} 분석 중 — 논문 ${ptmMatch[2]}편, 경로 ${ptmMatch[3]}개 발견 (${ptmMatch[4]}/${ptmMatch[5]})`;
    }
    // Simpler per-PTM pattern
    const simpleMatch = detail.match(/(\d+)\/(\d+)/);
    if (simpleMatch && detail.includes("article")) {
      return detail.replace(/articles?/g, "편").replace(/pathways?/g, "경로").substring(0, 80);
    }
    if (detail.includes("Generating MD report")) return "분석 결과를 정리하고 있습니다...";
    if (detail.includes("MD report generated")) return "분석 결과 정리 완료";
    if (detail.includes("global_analysis") || detail.includes("Global")) return "전체 PTM 패턴 종합 분석 중...";
    if (detail.includes("receptor")) return "수용체 신호전달 분석 중...";
    if (detail.includes("3-Layer Summary")) return "신호전달 경로 종합 정리 중...";
    if (detail.includes("Enrichment complete")) {
      const match = detail.match(/(\d+) PTMs.*?(\d+) articles/);
      return match ? `분석 완료: ${match[1]}개 PTM, ${match[2]}편 논문 참조` : "AI 심층 분석 완료";
    }
    // Fallback: strip technical terms
    return detail
      .replace(/RAG enrichment/gi, "AI 분석")
      .replace(/RAG/gi, "")
      .replace(/LLM/gi, "AI")
      .replace(/ChromaDB/gi, "")
      .replace(/MCP/gi, "")
      .trim()
      .substring(0, 80);
  }

  // ── Report Generation stage ──
  if (stage === "report_generation") {
    if (detail.includes("pipeline started")) return "보고서 생성을 시작합니다...";
    if (detail.includes("LLM verified") || detail.includes("llm_preflight")) return "AI 모델 준비 완료";
    if (detail.includes("LangGraph") || detail.includes("Executing")) return "AI 보고서 작성 파이프라인 실행 중...";
    if (detail.includes("Loading enriched") || detail.includes("Context loaded")) return "분석 데이터 로딩 중...";
    if (detail.includes("research questions") || detail.includes("Generating AI")) return "연구 질문 생성 중...";
    if (detail.includes("Generated") && detail.includes("question")) return "연구 질문 생성 완료";
    if (detail.includes("Analyzing PTM data") || detail.includes("Researching")) return "PTM 데이터 심층 분석 중...";
    if (detail.includes("Research complete")) return "데이터 분석 완료";
    if (detail.includes("hypothes")) {
      if (detail.includes("Generating") || detail.includes("Validating")) return "가설 생성 및 검증 중...";
      if (detail.includes("Generated") || detail.includes("complete")) return "가설 검증 완료";
      const qMatch = detail.match(/Hypothesis for Q(\d+).*?\((\d+)\/(\d+)\)/);
      if (qMatch) return `가설 생성 중 — 질문 ${qMatch[1]} (${qMatch[2]}/${qMatch[3]})`;
      return "가설 생성 중...";
    }
    if (detail.includes("network") || detail.includes("signaling")) {
      if (detail.includes("complete")) return "신호전달 네트워크 분석 완료";
      return "신호전달 네트워크 분석 중...";
    }
    if (detail.includes("Writing") || detail.includes("sections")) {
      if (detail === "All sections written") return "모든 보고서 섹션 작성 완료";
      if (detail.startsWith("Writing ")) {
        const section = detail.replace("Writing ", "");
        return `보고서 작성 중: ${section}`;
      }
      return "보고서 섹션 작성 중...";
    }
    if (detail.includes("co-pilot") || detail.includes("reviewing")) return "AI 리뷰 및 품질 검수 중...";
    if (detail.includes("reviewed")) return "AI 품질 검수 완료";
    if (detail.includes("Q&A report")) {
      if (detail.includes("generated")) return "Q&A 보고서 생성 완료";
      return "Q&A 보고서 생성 중...";
    }
    if (detail.includes("Refining") || detail.includes("refined")) return "연구 질문 정제 중...";
    // Fallback
    return detail
      .replace(/RAG/gi, "")
      .replace(/LLM/gi, "AI")
      .replace(/LangGraph/gi, "")
      .trim()
      .substring(0, 80);
  }

  // Default: strip technical terms
  return detail
    .replace(/RAG/gi, "")
    .replace(/LLM/gi, "AI")
    .replace(/ChromaDB/gi, "")
    .trim()
    .substring(0, 80);
}

// ── Sub-components ─────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
    pending: { label: "Pending", color: "bg-yellow-100 text-yellow-800", icon: <Clock className="h-3 w-3" /> },
    running: { label: "Running", color: "bg-blue-100 text-blue-800", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    preprocessing: { label: "Processing", color: "bg-blue-100 text-blue-800", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    rag_enrichment: { label: "AI 분석 중", color: "bg-indigo-100 text-indigo-800", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    report_generation: { label: "보고서 작성 중", color: "bg-purple-100 text-purple-800", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    completed: { label: "Completed", color: "bg-green-100 text-green-800", icon: <CheckCircle2 className="h-3 w-3" /> },
    failed: { label: "Failed", color: "bg-red-100 text-red-800", icon: <XCircle className="h-3 w-3" /> },
    cancelled: { label: "Cancelled", color: "bg-orange-100 text-orange-800", icon: <StopCircle className="h-3 w-3" /> },
  };
  const c = config[status] || config.pending;
  return (
    <Badge className={`gap-1 text-[10px] ${c.color}`}>
      {c.icon} {c.label}
    </Badge>
  );
}

function OverviewTab({ order }: { order: Order }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Executive Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground leading-relaxed">
            Analysis completed successfully. Use the tabs above to explore detailed results,
            or ask Mekii AI questions about your data in the chat panel.
          </p>
        </CardContent>
      </Card>
      <AnalysisStatisticsTab orderId={order.id} />
    </div>
  );
}

type VectorRow = {
  gene: string;
  position: string;
  condition: string;
  protein_log2fc: number;
  ptm_relative_log2fc: number;
  ptm_absolute_log2fc: number;
  control_pseudocount_used?: boolean;
  p_value?: number | null;
  q_value?: number | null;
};

function parseTimeOrder(cond: string): number {
  const m = cond.match(/(\d+(?:\.\d+)?)\s*(h|hr|hour|min|m)?/i);
  if (!m) return 0;
  let v = parseFloat(m[1]);
  const unit = (m[2] || "h").toLowerCase();
  if (unit.startsWith("m") || unit === "min") v /= 60;
  return v;
}

function VectorPlotTab({ orderId }: { orderId: number }) {
  const [data, setData] = useState<{ vector_data: VectorRow[] } | null>(null);
  const [plotFiles, setPlotFiles] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState<"relative" | "absolute">("relative");
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    Promise.all([
      api.get<{ vector_data: VectorRow[] }>(`/orders/${orderId}/vector-plot-data`).catch(() => null),
      api.get<{ files: string[] }>(`/orders/${orderId}/vector-plots`).catch(() => ({ files: [] })),
    ]).then(([vd, pf]) => {
      if (vd) setData({ vector_data: vd.vector_data || [] });
      setPlotFiles((pf as any)?.files || []);
    }).finally(() => setLoading(false));
  }, [orderId]);
  if (loading) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">Loading vector plot data...</p>
        </CardContent>
      </Card>
    );
  }
  if (!data?.vector_data?.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 rounded-lg border bg-muted/20">
          <ScatterChartIcon className="h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground text-center">Scatter data will appear here after preprocessing completes.</p>
        </CardContent>
      </Card>
    );
  }
  const yKey = metric === "relative" ? "ptm_relative_log2fc" : "ptm_absolute_log2fc";
  const conditions = Array.from(
    new Set(data.vector_data.map((r) => r.condition).filter((c) => c && c !== "Control"))
  ).sort((a, b) => parseTimeOrder(a) - parseTimeOrder(b));
  const chartsByCond = conditions.map((cond) => {
    const rows = data.vector_data.filter((r) => r.condition === cond);
    const points = rows.map((r) => ({
      x: r.protein_log2fc ?? 0,
      y: (r[yKey as keyof VectorRow] as number) ?? 0,
      name: `${r.gene} ${r.position}`.trim() || `${r.gene}${r.position}`,
    }));
    return { condition: cond, points };
  });
  const allX = data.vector_data.map((r) => r.protein_log2fc ?? 0);
  const allY = data.vector_data.map((r) => (r[yKey as keyof VectorRow] as number) ?? 0);
  const xMin = Math.min(...allX);
  const xMax = Math.max(...allX);
  const yMin = Math.min(...allY);
  const yMax = Math.max(...allY);
  const domainPadding = Math.max(Math.abs(xMax - xMin), Math.abs(yMax - yMin)) * 0.1 / zoom;
  const xDomain = [xMin - domainPadding, xMax + domainPadding];
  const yDomain = [yMin - domainPadding, yMax + domainPadding];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          <Button
            variant={metric === "relative" ? "default" : "outline"}
            size="sm"
            onClick={() => setMetric("relative")}
          >
            PTM Relative
          </Button>
          <Button
            variant={metric === "absolute" ? "default" : "outline"}
            size="sm"
            onClick={() => setMetric("absolute")}
          >
            PTM Absolute
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="sm" onClick={() => setZoom((z) => Math.min(4, z + 0.5))}>
            <ZoomIn className="h-3.5 w-3.5" /> Zoom In
          </Button>
          <Button variant="outline" size="sm" onClick={() => setZoom((z) => Math.max(0.5, z - 0.5))}>
            <ZoomOut className="h-3.5 w-3.5" /> Zoom Out
          </Button>
          <span className="text-xs text-muted-foreground ml-1">{zoom.toFixed(1)}x</span>
        </div>
      </div>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {chartsByCond.map(({ condition, points }, idx) => (
          <Card key={condition} className="overflow-hidden">
            <CardHeader className="py-2 px-4">
              <CardTitle className="text-sm flex items-center gap-2">
                <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: SCATTER_PALETTE[idx % SCATTER_PALETTE.length] }} />
                {condition} ({metric === "relative" ? "PTM Relative" : "PTM Absolute"})
              </CardTitle>
            </CardHeader>
            <CardContent className="p-2">
              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart margin={{ top: 8, right: 8, bottom: 24, left: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis
                      type="number"
                      dataKey="x"
                      name="Protein Log2FC"
                      domain={xDomain}
                      tick={{ fontSize: 10 }}
                    />
                    <YAxis
                      type="number"
                      dataKey="y"
                      name={metric === "relative" ? "PTM Relative Log2FC" : "PTM Absolute Log2FC"}
                      domain={yDomain}
                      tick={{ fontSize: 10 }}
                    />
                    <RechartsTooltip
                      cursor={{ strokeDasharray: "3 3" }}
                      content={({ active, payload }) => {
                        if (!active || !payload?.[0]) return null;
                        const p = payload[0].payload;
                        return (
                          <div className="rounded-md border bg-background px-3 py-2 text-sm shadow-md">
                            <p className="font-medium">{p.name}</p>
                            <p className="text-muted-foreground">
                              Protein: {p.x.toFixed(3)} · {metric === "relative" ? "PTM Rel" : "PTM Abs"}: {p.y.toFixed(3)}
                            </p>
                          </div>
                        );
                      }}
                    />
                    {metric === "relative" && [-1, -0.5, 0, 0.5, 1].map((y) => (
                      <ReferenceLine key={y} y={y} stroke="#ef4444" strokeDasharray={y === 0 ? undefined : "3 3"} strokeOpacity={0.5} />
                    ))}
                    {metric === "relative" && <ReferenceLine x={0} stroke="#ef4444" strokeDasharray="3 3" strokeOpacity={0.5} />}
                    {metric === "absolute" && (
                      <>
                        <ReferenceLine x={0} stroke="#ef4444" strokeDasharray="3 3" strokeOpacity={0.5} />
                        <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="3 3" strokeOpacity={0.5} />
                        <ReferenceLine segment={[{ x: Math.min(xMin, yMin), y: Math.min(xMin, yMin) }, { x: Math.max(xMax, yMax), y: Math.max(xMax, yMax) }]} stroke="#000" strokeDasharray="3 3" strokeOpacity={0.6} />
                      </>
                    )}
                    <Scatter
                      name={condition}
                      data={points}
                      fill={SCATTER_PALETTE[idx % SCATTER_PALETTE.length]}
                      fillOpacity={0.7}
                    />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      {/* Static PNG plots */}
      {plotFiles.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Static Report Plots (PNG)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {plotFiles.map((f) => (
                <Button
                  key={f}
                  variant="outline"
                  size="sm"
                  className="gap-1 text-xs"
                  onClick={() => api.downloadFile(`/orders/${orderId}/files/${encodeURIComponent(f)}`, f)}
                >
                  <Download className="h-3 w-3" /> {f}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function KinaseActivityTab({ orderId }: { orderId: number }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<any>(`/orders/${orderId}/vector-plot-data`)
      .then((d) => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">Loading kinase activity data...</p>
        </CardContent>
      </Card>
    );
  }

  const receptors = data?.inferred_receptors || [];
  const cowave = data?.cowave_analysis;

  return (
    <div className="space-y-4">
      {/* Inferred Receptors */}
      {receptors.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Inferred Upstream Receptors
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {receptors.slice(0, 12).map((rec: any, i: number) => (
                <div key={i} className="border rounded-lg p-3 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">{rec.name}</span>
                    <Badge variant="outline" className="text-[10px]">{rec.receptor_class}</Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {rec.downstream_ptm_count} downstream PTMs
                  </p>
                  {rec.via_kinases?.length > 0 && (
                    <p className="text-[10px] text-muted-foreground">
                      via: {rec.via_kinases.slice(0, 4).join(", ")}
                    </p>
                  )}
                  {rec.signaling_pathway && (
                    <p className="text-[10px] text-primary/80">{rec.signaling_pathway}</p>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
      {/* Within-Cluster Concordance summary (internal field: cowave) */}
      {cowave && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Within-Cluster Concordance Analysis</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Within-cluster concordance analysis annotates observed sampled-interval trajectory patterns within fixed temporal phosphosite clusters.
              See the Modules tab for cluster and footprint diagnostics; this does not establish shared regulation or causal order.
            </p>
          </CardContent>
        </Card>
      )}
      {/* Fallback */}
      {receptors.length === 0 && !cowave && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Activity className="h-12 w-12 text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No kinase activity data available for this analysis.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function CascadeTab({ orderId, order }: { orderId: number; order: Order }) {
  const crossTalkData = order.cross_talk_data as any;

  if (!crossTalkData) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Network className="h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground">
            {order.report_options?.analysis_mode === "cross_talk"
              ? "Cross-Talk 분석 데이터를 불러올 수 없습니다."
              : "이 분석에는 Cross-Talk 데이터가 포함되어 있지 않습니다."}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Network className="h-4 w-4" />
            PTM Cross-Talk Analysis
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Phosphorylation과 Ubiquitylation 간의 Cross-Talk 패턴 분석 결과
          </p>
        </CardHeader>
      </Card>
      {crossTalkData?.primary_summary && crossTalkData?.secondary_summary && (
        <CrossTalkVennDiagram
          dualPTMProteins={crossTalkData.dual_ptm_proteins ?? []}
          primarySummary={crossTalkData.primary_summary}
          secondarySummary={crossTalkData.secondary_summary}
          sharedNonPTM={crossTalkData.shared_nonptm ?? []}
          primaryOnlyNonPTM={crossTalkData.primary_only_nonptm ?? []}
          secondaryOnlyNonPTM={crossTalkData.secondary_only_nonptm ?? []}
        />
      )}
      {crossTalkData?.dual_ptm_proteins?.length > 0 && (
        <CrossTalkHeatmap
          dualPTMProteins={crossTalkData.dual_ptm_proteins}
          primaryPtmType={crossTalkData.primary_ptm_type ?? "phosphorylation"}
          secondaryPtmType={crossTalkData.secondary_ptm_type ?? "ubiquitylation"}
        />
      )}
      {crossTalkData?.sequential_gating?.length > 0 && (
        <CrossTalkSequentialGating
          gatingEvents={crossTalkData.sequential_gating}
          primaryPtmType={crossTalkData.primary_ptm_type ?? "phosphorylation"}
          secondaryPtmType={crossTalkData.secondary_ptm_type ?? "ubiquitylation"}
        />
      )}
    </div>
  );
}

function TimelineTab({ orderId, order }: { orderId: number; order: Order }) {
  const spData = order.signal_propagation_data as any;

  if (!spData?.summary) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Timer className="h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground">
            Signal propagation timeline 데이터가 없습니다.
            Multi-time-point 데이터에서만 생성됩니다.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <SignalPropagationTimeline data={spData} />
    </div>
  );
}

function ModulesTab({ orderId }: { orderId: number }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<any>(`/orders/${orderId}/vector-plot-data`)
      .then((d) => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">Loading module data...</p>
        </CardContent>
      </Card>
    );
  }

  const topNPtms = data?.top_n_ptms || [];
  const vectorData = data?.vector_data || [];
  const receptors = data?.inferred_receptors || [];

  if (!topNPtms.length) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Boxes className="h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground">
            Kinase module data is not available for this analysis.
          </p>
        </CardContent>
      </Card>
    );
  }

  // Show a summary of top PTMs and their protein classes
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Boxes className="h-4 w-4" />
            Top N PTM Sites ({topNPtms.length})
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Most significant PTM sites identified by the analysis pipeline
          </p>
        </CardHeader>
        <CardContent>
          <div className="max-h-[400px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b">
                  <th className="text-left py-2 px-2 text-xs font-medium text-muted-foreground">Gene</th>
                  <th className="text-left py-2 px-2 text-xs font-medium text-muted-foreground">Position</th>
                  <th className="text-left py-2 px-2 text-xs font-medium text-muted-foreground">Protein Class</th>
                </tr>
              </thead>
              <tbody>
                {topNPtms.slice(0, 50).map((ptm: any, i: number) => (
                  <tr key={i} className="border-b border-muted/50">
                    <td className="py-1.5 px-2 font-mono text-xs">{ptm.gene}</td>
                    <td className="py-1.5 px-2 font-mono text-xs">{ptm.position}</td>
                    <td className="py-1.5 px-2">
                      {ptm.protein_class ? (
                        <Badge variant="outline" className="text-[10px]">
                          {ptm.protein_class.role}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {topNPtms.length > 50 && (
            <p className="text-xs text-muted-foreground mt-2 text-center">
              Showing 50 of {topNPtms.length} PTM sites
            </p>
          )}
        </CardContent>
      </Card>
      {/* Receptor summary */}
      {receptors.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Upstream Receptor Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {receptors.slice(0, 8).map((rec: any, i: number) => (
                <Badge key={i} variant="outline" className="text-xs gap-1">
                  {rec.name} ({rec.downstream_ptm_count} PTMs)
                </Badge>
              ))}
              {receptors.length > 8 && (
                <Badge variant="secondary" className="text-xs">
                  +{receptors.length - 8} more
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
