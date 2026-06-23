/**
 * AnalysisReport — Result visualization + Mekii AI chat for general users.
 * 
 * Left panel: Visualization tabs (Vector Plot, Kinase Heatmap, Cascade, Timeline, Modules)
 * Right panel: Mekii AI Chat (context-aware, always visible)
 */
import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { Order } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import MekiiChat from "@/components/user/MekiiChat";
import {
  ArrowLeft,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  ScatterChart,
  Activity,
  Network,
  Timer,
  Boxes,
  FileText,
  Download,
  MessageSquare,
  PanelRightOpen,
  PanelRightClose,
} from "lucide-react";

export default function AnalysisReport() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

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
        if (data.status === "completed" || data.status === "failed") {
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

  const isRunning = !["completed", "failed"].includes(order.status);
  const isCompleted = order.status === "completed";

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
            {isCompleted && (
              <Button variant="outline" size="sm" className="gap-1">
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
                        rag_enrichment: "AI가 문헌을 검색하고 분석하고 있습니다",
                        report_generation: "종합 보고서를 작성하고 있습니다",
                      };
                      return labels[s] || "분석을 진행하고 있습니다...";
                    })()}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {order.stage_detail || (() => {
                      const s = order.current_stage || order.status;
                      const hints: Record<string, string> = {
                        registered: "잠시만 기다려주세요. 자동으로 시작됩니다",
                        queued: "곧 시작됩니다. 잠시만 기다려주세요",
                        preprocessing: "mzML 파일에서 PTM을 정량하고 통계 분석을 수행합니다 (약 5-15분)",
                        rag_enrichment: "PubMed, UniProt, KEGG 등에서 관련 정보를 수집하고 LLM이 해석합니다 (약 10-30분)",
                        report_generation: "모든 분석 결과를 종합하여 보고서를 생성합니다 (약 5-10분)",
                      };
                      return hints[s] || "";
                    })()}
                  </p>
                </div>
              </div>
              <Progress value={order.progress_pct} className="h-2" />
              <p className="text-xs text-muted-foreground mt-2 text-right">{order.progress_pct}%</p>
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
                <ScatterChart className="h-3.5 w-3.5" />
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
              <CascadeTab orderId={order.id} />
            </TabsContent>
            <TabsContent value="timeline">
              <TimelineTab orderId={order.id} />
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

// ── Sub-components ─────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
    pending: { label: "Pending", color: "bg-yellow-100 text-yellow-800", icon: <Clock className="h-3 w-3" /> },
    running: { label: "Running", color: "bg-blue-100 text-blue-800", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    preprocessing: { label: "Processing", color: "bg-blue-100 text-blue-800", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    rag_enrichment: { label: "Enriching", color: "bg-indigo-100 text-indigo-800", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    report_generation: { label: "Reporting", color: "bg-purple-100 text-purple-800", icon: <Loader2 className="h-3 w-3 animate-spin" /> },
    completed: { label: "Completed", color: "bg-green-100 text-green-800", icon: <CheckCircle2 className="h-3 w-3" /> },
    failed: { label: "Failed", color: "bg-red-100 text-red-800", icon: <XCircle className="h-3 w-3" /> },
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
          <Separator className="my-4" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-xs text-muted-foreground">PTM Sites</p>
              <p className="text-lg font-bold">-</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Active Kinases</p>
              <p className="text-lg font-bold">-</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Cascades</p>
              <p className="text-lg font-bold">-</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Modules</p>
              <p className="text-lg font-bold">-</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function VectorPlotTab({ orderId }: { orderId: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <ScatterChart className="h-4 w-4" />
          4-Quadrant Vector Plot
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="aspect-square max-h-[500px] bg-muted/30 rounded-lg flex items-center justify-center border">
          <p className="text-sm text-muted-foreground">
            Vector Plot visualization (Protein Log2FC × PTM Relative Log2FC)
          </p>
        </div>
        <p className="text-xs text-muted-foreground mt-2">
          X-axis: Protein abundance change (Log2FC) | Y-axis: PTM occupancy change (Relative Log2FC)
        </p>
      </CardContent>
    </Card>
  );
}

function KinaseActivityTab({ orderId }: { orderId: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Activity className="h-4 w-4" />
          Kinase Activity Heatmap
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[400px] bg-muted/30 rounded-lg flex items-center justify-center border">
          <p className="text-sm text-muted-foreground">
            Kinase activity heatmap (Co-Wave analysis results)
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function CascadeTab({ orderId }: { orderId: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Network className="h-4 w-4" />
          Signaling Cascade
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[400px] bg-muted/30 rounded-lg flex items-center justify-center border">
          <p className="text-sm text-muted-foreground">
            Receptor → Kinase → Substrate cascade visualization
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function TimelineTab({ orderId }: { orderId: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Timer className="h-4 w-4" />
          Temporal Timeline
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[400px] bg-muted/30 rounded-lg flex items-center justify-center border">
          <p className="text-sm text-muted-foreground">
            Signal propagation timeline (temporal kinase activation order)
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function ModulesTab({ orderId }: { orderId: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Boxes className="h-4 w-4" />
          Kinase Modules
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[400px] bg-muted/30 rounded-lg flex items-center justify-center border">
          <p className="text-sm text-muted-foreground">
            Co-Wave kinase modules (anchor → inferred → novel substrates)
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
