import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, RefreshCw, ScrollText } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { FadeIn } from "@/components/motion/fade-in";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface PipelineLog {
  id: number;
  order_id: number;
  order_code: string;
  project_name: string;
  stage: string;
  step: string;
  status: string;
  progress_pct: number | null;
  message: string | null;
  created_at: string | null;
}

const STAGES = [
  { value: "all", label: "All stages" },
  { value: "preprocessing", label: "Preprocessing" },
  { value: "rag_enrichment", label: "RAG Enrichment" },
  { value: "report_generation", label: "Report Generation" },
];

function formatKST(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function statusVariant(status: string) {
  switch (status) {
    case "completed":
      return "success" as const;
    case "failed":
      return "destructive" as const;
    case "started":
    case "running":
    case "progress":
      return "info" as const;
    default:
      return "secondary" as const;
  }
}

export default function Logs() {
  const navigate = useNavigate();
  const [logs, setLogs] = useState<PipelineLog[]>([]);
  const [stage, setStage] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async (nextStage = stage) => {
    setLoading(true);
    setError(null);
    try {
      const qs = nextStage !== "all" ? `?stage=${encodeURIComponent(nextStage)}&limit=200` : "?limit=200";
      const data = await api.get<{ logs: PipelineLog[] }>(`/orders/pipeline-logs${qs}`);
      setLogs(data.logs ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load logs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(stage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Pipeline Logs</h1>
          <p className="text-sm text-muted-foreground mt-1">
            주문 파이프라인 실행 로그입니다. 컨테이너 로그는 System Monitor에서 봅니다.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={stage} onValueChange={setStage}>
            <SelectTrigger className="w-[200px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STAGES.map((s) => (
                <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={() => load()} disabled={loading} className="gap-1.5">
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh
          </Button>
        </div>
      </div>

      <FadeIn>
        <Card>
          <CardContent className="p-0">
            {loading && logs.length === 0 ? (
              <div className="flex items-center justify-center py-20 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                Loading logs…
              </div>
            ) : error ? (
              <div className="py-16 text-center text-sm text-destructive">{error}</div>
            ) : logs.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20">
                <ScrollText className="h-16 w-16 text-muted-foreground/30 mb-4" />
                <p className="text-lg font-medium text-muted-foreground">No logs available</p>
                <p className="text-sm text-muted-foreground mt-1">
                  주문을 실행하면 단계별 로그가 여기에 쌓입니다.
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[130px]">Time</TableHead>
                    <TableHead>Order</TableHead>
                    <TableHead>Stage</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Message</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.map((log) => (
                    <TableRow key={log.id}>
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatKST(log.created_at)}
                      </TableCell>
                      <TableCell>
                        <button
                          type="button"
                          className="text-left hover:underline"
                          onClick={() => navigate(`/admin/orders/${log.order_id}`)}
                        >
                          <div className="text-sm font-medium truncate max-w-[180px]">
                            {log.project_name || log.order_code}
                          </div>
                          <div className="text-[11px] text-muted-foreground font-mono">{log.order_code}</div>
                        </button>
                      </TableCell>
                      <TableCell>
                        <div className="text-xs">{log.stage}</div>
                        <div className="text-[11px] text-muted-foreground">{log.step}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(log.status)} className="text-[10px]">
                          {log.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs max-w-[420px] truncate" title={log.message ?? ""}>
                        {log.message || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </FadeIn>
    </div>
  );
}
