import { useEffect, useRef, useState, useMemo } from "react";
import { flushSync } from "react-dom";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Cog, BookOpen, FileText, CheckCircle2, AlertCircle, Brain,
  Play, RotateCcw, ArrowLeft, Terminal, Circle, RefreshCw,
  ChevronDown, ChevronUp, Download, FileSpreadsheet, FileJson, File, FolderOpen,
  Copy, Check, Eye, ArrowRightCircle, Sparkles, Plus, X, Trash2,
  MessageSquare, Loader2, ToggleLeft, ToggleRight, Square, StopCircle,
  ChartScatter, TrendingUp, ZoomIn, ZoomOut, GitMerge, BarChart3,
  LayoutDashboard, FileOutput, Share2, CopyPlus, ChevronLeft, ChevronRight,
  Presentation, FlaskConical,
} from "lucide-react";
import { ShareOrderModal } from "@/components/ShareOrderModal";
import { Input } from "@/components/ui/input";
import { AutoResizeTextarea } from "@/components/ui/auto-resize-textarea";
import { api } from "@/lib/api";
import { useOrderProgress } from "@/hooks/useSSE";
import type { Order, OrderLog, ProgressEvent } from "@/lib/types";
import { AnalysisStatisticsTab } from "@/components/AnalysisStatisticsTab";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import FilePreviewModal from "@/components/FilePreviewModal";
import RerunOptionsModal from "@/components/RerunOptionsModal";
import CrossTalkVennDiagram from "@/components/CrossTalkVennDiagram";
import CrossTalkHeatmap from "@/components/CrossTalkHeatmap";
import CrossTalkSequentialGating from "@/components/CrossTalkSequentialGating";
import SignalPropagationTimeline from "@/components/SignalPropagationTimeline";
import { OrderArticlesTab } from "@/components/OrderArticlesTab";
import { CoScientistTab } from "@/components/CoScientistTab";
import KinaseModuleAnalysis from "@/components/KinaseModuleAnalysis";
import ChatPanel from "@/components/ChatPanel";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  ReferenceLine,
} from "recharts";

const STAGES = [
  { key: "preprocessing", label: "Preprocessing", icon: Cog, range: [0, 33] },
  { key: "rag_enrichment", label: "RAG Enrichment", icon: BookOpen, range: [33, 66] },
  { key: "report_generation", label: "Report Generation", icon: FileText, range: [66, 100] },
];

const statusBadgeVariant = (s: string): { variant: "success" | "destructive" | "info" | "warning" | "secondary" | "outline"; className?: string } => {
  switch (s) {
    case "completed": return { variant: "success" };
    case "failed": return { variant: "destructive" };
    case "cancelled": return { variant: "outline" };
    case "registered": return { variant: "secondary", className: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" };
    case "queued": return { variant: "warning" };
    case "preprocessing": return { variant: "info", className: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400" };
    case "rag_enrichment": return { variant: "info", className: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400" };
    case "report_generation": return { variant: "info", className: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400" };
    default: return { variant: "secondary" };
  }
};

function formatTime(ts: string | number): string {
  const d = typeof ts === "number" ? new Date(ts) : new Date(ts);
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  };
  const parts = new Intl.DateTimeFormat("en-CA", opts).formatToParts(d);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  const pad = (s: string) => s.padStart(2, "0");
  return `${get("year")}-${pad(get("month"))}-${pad(get("day"))} ${pad(get("hour"))}:${pad(get("minute"))}:${pad(get("second"))}`;
}

function stageLabel(stage: string): string {
  switch (stage) {
    case "preprocessing": return "Preprocessing";
    case "rag_enrichment": return "RAG Enrichment";
    case "report_generation": return "Report Generation";
    case "completed": return "Completed";
    default: return stage;
  }
}

const STAGE_WEIGHTS = { preprocessing: [0, 15], rag_enrichment: [15, 50], report_generation: [50, 100] } as const;
type StageKey = keyof typeof STAGE_WEIGHTS;

function computeOverallPct(stage: string | undefined, stagePct: number): number {
  if (stage === "completed") return 100;
  const range = STAGE_WEIGHTS[stage as StageKey];
  if (!range) return stagePct;
  const [lo, hi] = range;
  return Math.round(lo + (Math.min(Math.max(stagePct, 0), 100) / 100) * (hi - lo));
}

function stageStepLabel(_stage: string | undefined): string {
  return "";
}

function stageColor(stage: string): string {
  switch (stage) {
    case "preprocessing": return "text-blue-400";
    case "rag_enrichment": return "text-amber-400";
    case "report_generation": return "text-emerald-400";
    default: return "text-gray-400";
  }
}

function statusIcon(status: string): string {
  switch (status) {
    case "completed": return "✓";
    case "failed": return "✗";
    case "started": return "▶";
    case "running": return "●";
    case "progress": return "›";
    default: return "·";
  }
}

function statusColor(status: string): string {
  switch (status) {
    case "completed": return "text-emerald-400";
    case "failed": return "text-red-400";
    case "started": return "text-cyan-400";
    case "running": return "text-blue-400";
    case "progress": return "text-amber-400/90";
    default: return "text-zinc-500";
  }
}

function OverviewField({
  label,
  value,
  capitalize,
  mono,
  longText,
  truncate,
}: {
  label: string;
  value: string;
  capitalize?: boolean;
  mono?: boolean;
  longText?: boolean;
  truncate?: boolean;
}) {
  return (
    <div className="space-y-1 min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "text-sm font-medium",
          !truncate && "break-words",
          capitalize && "capitalize",
          mono && "font-mono text-xs",
          longText && "whitespace-pre-wrap",
          truncate && "truncate"
        )}
        title={truncate ? value : undefined}
      >
        {value}
      </p>
    </div>
  );
}

// ── Sub-progress parser ──────────────────────────────────────────────────────

interface SubProgress {
  label: string;
  done: number;
  total: number;
  pct: number;
}

function parseSubProgress(message: string): SubProgress | null {
  // Pattern 1: "InterPro domains: 1,200/6,071"
  const m1 = message.match(/^(.+?):\s*([\d,]+)\s*\/\s*([\d,]+)$/);
  if (m1) {
    const done = parseInt(m1[2].replace(/,/g, ""));
    const total = parseInt(m1[3].replace(/,/g, ""));
    if (!isNaN(done) && !isNaN(total) && total > 0)
      return { label: m1[1].trim(), done, total, pct: Math.round((done / total) * 100) };
  }
  // Pattern 2: "Hypothesis for Q4 done (3/10)"
  const m2 = message.match(/^(.+?)\s*\((\d+)\s*\/\s*(\d+)\)\s*$/);
  if (m2) {
    const done = parseInt(m2[2]);
    const total = parseInt(m2[3]);
    if (!isNaN(done) && !isNaN(total) && total > 0)
      return { label: `[${done}/${total}] ${m2[1].trim()}`, done, total, pct: Math.round((done / total) * 100) };
  }
  return null;
}

// ── Activity Progress Card ──────────────────────────────────────────────────

function ActivityProgress({
  progress,
  stage,
  pct,
  message,
  isRunning,
}: {
  progress: ProgressEvent | null;
  stage?: string;
  pct: number;
  message?: string;
  isRunning: boolean;
}) {
  const latestMessage = progress?.message || message || "";
  const latestStage = progress?.stage || stage || "";
  const stagePct = progress?.progress_pct ?? pct;
  const overallPct = computeOverallPct(latestStage, stagePct);
  const sub = parseSubProgress(latestMessage);

  if (!isRunning && !sub) return null;

  return (
    <Card>
      <CardContent className="py-4 space-y-3">
        {/* Overall pipeline progress */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              {isRunning && (
                <Circle className="h-2 w-2 fill-primary text-primary animate-pulse" />
              )}
              <span className="font-medium">Overall Progress</span>
            </div>
            <span className="text-muted-foreground tabular-nums">
              {overallPct >= 0 ? `${overallPct}%` : ""}
            </span>
          </div>
          <Progress value={Math.max(0, overallPct)} className="h-2" />
        </div>

        {/* Current stage progress */}
        <div className="space-y-1.5 pl-4 border-l-2 border-primary/20">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">
              {stageLabel(latestStage)}
            </span>
            <span className="font-mono tabular-nums text-muted-foreground">
              {stagePct >= 0 ? `${Math.round(stagePct)}%` : ""}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-primary/60 transition-all duration-500 ease-out"
              style={{ width: `${Math.max(0, stagePct)}%` }}
            />
          </div>
        </div>

        {/* Sub-task progress (e.g., InterPro 3,200/6,071) */}
        {sub && (
          <div className="space-y-1.5 pl-8 border-l-2 border-primary/10">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{sub.label}</span>
              <span className="font-mono tabular-nums text-muted-foreground">
                {sub.done.toLocaleString()} / {sub.total.toLocaleString()}
                <span className="ml-1.5 text-foreground font-medium">{sub.pct}%</span>
              </span>
            </div>
            <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary/40 transition-all duration-500 ease-out"
                style={{ width: `${sub.pct}%` }}
              />
            </div>
          </div>
        )}

        {/* Current activity text */}
        {!sub && latestMessage && (
          <p className="text-xs text-muted-foreground pl-4 border-l-2 border-primary/20 truncate" title={latestMessage}>
            {latestMessage}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Terminal Log Panel (Collapsible) ─────────────────────────────────────────

interface LogEntry {
  key: string;
  ts: string | number;
  stage: string;
  step: string;
  status: string;
  pct?: number;
  message: string;
}

function toLogEntry(log: OrderLog): LogEntry {
  return {
    key: `db-${log.id}`,
    ts: log.created_at,
    stage: log.stage,
    step: log.step,
    status: log.status,
    pct: log.progress_pct,
    message: log.message || "",
  };
}

function sseToLogEntry(e: ProgressEvent, idx: number): LogEntry {
  const pct = e.progress_pct;
  return {
    key: `sse-${idx}`,
    ts: e._ts || Date.now(),
    stage: e.stage,
    step: e.step,
    status: e.status,
    pct: pct != null && !Number.isNaN(Number(pct)) ? Number(pct) : undefined,
    message: e.message || "",
  };
}

function isProgressUpdate(entry: LogEntry): boolean {
  return !!parseSubProgress(entry.message);
}

function TerminalPanel({
  logs,
  sseEvents,
  isRunning,
}: {
  logs: OrderLog[];
  sseEvents: ProgressEvent[];
  isRunning: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);

  const allEntries = useMemo(() => {
    const dbEntries = logs.map(toLogEntry);
    const lastDbTime = logs.length > 0
      ? new Date(logs[logs.length - 1].created_at).getTime()
      : 0;
    const sseEntries = sseEvents
      .map((e, i) => sseToLogEntry(e, i))
      .filter((e) => {
        const eTime = typeof e.ts === "number" ? e.ts : new Date(e.ts).getTime();
        return eTime > lastDbTime;
      });
    return [...dbEntries, ...sseEntries];
  }, [logs, sseEvents]);

  // Filter: collapse consecutive progress updates, keep only last per step
  const filteredEntries = useMemo(() => {
    const result: LogEntry[] = [];
    for (let i = 0; i < allEntries.length; i++) {
      const entry = allEntries[i];
      if (isProgressUpdate(entry)) {
        const next = allEntries[i + 1];
        if (next && next.step === entry.step && isProgressUpdate(next)) {
          continue;
        }
      }
      result.push(entry);
    }
    return result;
  }, [allEntries]);

  useEffect(() => {
    if (expanded && autoScroll) {
      const el = containerRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }
  }, [filteredEntries.length, autoScroll, expanded]);

  const userScrolledRef = useRef(false);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (!isAtBottom) {
      userScrolledRef.current = true;
      setAutoScroll(false);
    } else if (userScrolledRef.current) {
      userScrolledRef.current = false;
      setAutoScroll(true);
    }
  };

  const totalEntries = allEntries.length;

  return (
    <Card className="overflow-hidden border-zinc-700 dark:border-zinc-700 bg-[#1a1b26]">
      {/* Clickable header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 bg-[#24283b] border-b border-zinc-700/60 hover:bg-[#292e42] transition-colors cursor-pointer"
      >
        <div className="flex gap-1.5 mr-2">
          <div className="h-2.5 w-2.5 rounded-full bg-[#f7768e]/80" />
          <div className="h-2.5 w-2.5 rounded-full bg-[#e0af68]/80" />
          <div className="h-2.5 w-2.5 rounded-full bg-[#9ece6a]/80" />
        </div>
        <Terminal className="h-3.5 w-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">Analysis Log</span>
        <div className="flex-1" />
        {isRunning && (
          <div className="flex items-center gap-1.5">
            <Circle className="h-2 w-2 fill-emerald-400 text-emerald-400 animate-pulse" />
            <span className="text-[10px] text-emerald-400 font-mono tracking-wide">LIVE</span>
          </div>
        )}
        <span className="text-[10px] text-zinc-600 font-mono">{totalEntries}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 text-zinc-500 transition-transform duration-200",
            expanded && "rotate-180",
          )}
        />
      </button>

      {/* Expandable body */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 300 }}
            exit={{ height: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div
              ref={containerRef}
              onScroll={handleScroll}
              className="h-[300px] overflow-y-auto p-2 font-mono text-[11.5px] leading-[20px] scrollbar-thin"
            >
              {filteredEntries.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full gap-2">
                  <Terminal className="h-8 w-8 text-zinc-700" />
                  <span className="text-zinc-600 text-xs">No log entries yet</span>
                </div>
              ) : (
                filteredEntries.map((e) => {
                  const pctStr = e.pct != null && e.pct >= 0
                    ? `${String(Math.round(e.pct)).padStart(3, " ")}%`
                    : "    ";
                  return (
                    <div
                      key={e.key}
                      className="flex gap-0 hover:bg-white/[0.03] px-2 rounded-sm"
                    >
                      <span className="text-zinc-600 shrink-0 w-[165px]">{formatTime(e.ts)}</span>
                      <span className={cn("shrink-0 w-4 text-center", statusColor(e.status))}>
                        {statusIcon(e.status)}
                      </span>
                      <span className="text-zinc-500 shrink-0 w-[40px] text-right tabular-nums">{pctStr}</span>
                      <span className="text-zinc-700 shrink-0 px-1">│</span>
                      <span className={cn("shrink-0 w-[120px] truncate", stageColor(e.stage))}>
                        {stageLabel(e.stage)}
                      </span>
                      <span className="text-zinc-400 truncate">
                        {e.step !== e.stage && (
                          <span className="text-zinc-500">[{e.step}] </span>
                        )}
                        {e.message}
                      </span>
                    </div>
                  );
                })
              )}
              <div />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────

// ── Result Files ──────────────────────────────────────────────────────────────

function fileIcon(name: string) {
  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "md") return <FileText className="h-4 w-4 text-blue-500" />;
  if (ext === "docx") return <BookOpen className="h-4 w-4 text-indigo-500" />;
  if (ext === "tsv" || ext === "csv") return <FileSpreadsheet className="h-4 w-4 text-emerald-500" />;
  if (ext === "json") return <FileJson className="h-4 w-4 text-amber-500" />;
  if (ext === "txt") return <FileText className="h-4 w-4 text-zinc-500" />;
  if (ext === "png" || ext === "jpg") return <File className="h-4 w-4 text-pink-500" />;
  return <File className="h-4 w-4 text-muted-foreground" />;
}

function fileBadge(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "docx") return "Word";
  if (ext === "md") return "Markdown";
  if (ext === "tsv") return "TSV";
  if (ext === "json") return "JSON";
  if (ext === "txt") return "Text";
  if (ext === "png") return "Image";
  return ext?.toUpperCase() || "";
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatFileTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false,
  });
}

interface FileDetail {
  name: string;
  size_bytes: number;
  modified_at: string | null;
}

type SortKey = "name" | "size" | "modified";

function ResultFiles({
  orderId,
  resultFiles,
  onDeleted,
}: {
  orderId: number;
  resultFiles: { report_files?: string[]; all_files?: string[] };
  onDeleted?: () => void;
}) {
  const reports = resultFiles.report_files || [];
  const allFiles = resultFiles.all_files || [];
  const dataFiles = allFiles.filter((f) => !reports.includes(f));

  const [fileDetails, setFileDetails] = useState<Record<string, FileDetail>>({});
  const [hostDir, setHostDir] = useState("");
  const [copied, setCopied] = useState(false);
  const [previewFile, setPreviewFile] = useState("");
  const [reportSort, setReportSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "name", dir: "asc" });
  const [dataSort, setDataSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "name", dir: "asc" });
  const [deleting, setDeleting] = useState<string | null>(null);

  const handleDeleteReport = async (filename: string) => {
    if (!confirm(`Delete "${filename}"? This cannot be undone.`)) return;
    setDeleting(filename);
    try {
      await api.delete(`/orders/${orderId}/files/${encodeURIComponent(filename)}`);
      onDeleted?.();
    } catch (err: any) {
      alert(err.message || "Failed to delete file");
    } finally {
      setDeleting(null);
    }
  };

  useEffect(() => {
    api.get<{ files: FileDetail[]; host_output_dir: string }>(`/orders/${orderId}/file-details`).then((d) => {
      const map: Record<string, FileDetail> = {};
      d.files.forEach((f) => { map[f.name] = f; });
      setFileDetails(map);
      setHostDir(d.host_output_dir);
    }).catch(() => {});
  }, [orderId]);

  const handleFileClick = (filename: string) => {
    setPreviewFile(filename);
  };

  const handleCopyPath = async () => {
    if (!hostDir) return;
    try {
      await navigator.clipboard.writeText(hostDir);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  };

  const isReportInput = (f: string) => /^enriched_ptm_data.*\.json$/.test(f);

  const sortFiles = (files: string[], sort: { key: SortKey; dir: "asc" | "desc" }) => {
    const mult = sort.dir === "asc" ? 1 : -1;
    return [...files].sort((a, b) => {
      const da = fileDetails[a];
      const db = fileDetails[b];
      if (sort.key === "name") {
        return mult * a.localeCompare(b);
      }
      if (sort.key === "size") {
        const sa = da?.size_bytes ?? 0;
        const sb = db?.size_bytes ?? 0;
        return mult * (sa - sb);
      }
      if (sort.key === "modified") {
        const ma = da?.modified_at ?? "";
        const mb = db?.modified_at ?? "";
        return mult * ma.localeCompare(mb);
      }
      return 0;
    });
  };

  const handleDownload = (filename: string) =>
    api.downloadFile(`/orders/${orderId}/files/${encodeURIComponent(filename)}`, filename);

  const FolderPathBadge = () =>
    hostDir ? (
      <button
        onClick={handleCopyPath}
        className="text-[10px] font-mono text-muted-foreground bg-muted hover:bg-muted/80 px-2 py-1 rounded flex items-center gap-1.5 transition-colors cursor-pointer"
        title="Click to copy path"
      >
        <FolderOpen className="h-3 w-3 shrink-0" />
        <span className="truncate max-w-[280px]">{hostDir}</span>
        {copied ? (
          <Check className="h-3 w-3 text-emerald-500 shrink-0" />
        ) : (
          <Copy className="h-3 w-3 shrink-0 opacity-50" />
        )}
      </button>
    ) : null;

  const SortableHeader = ({
    label,
    sortKey,
    currentSort,
    onSort,
  }: {
    label: string;
    sortKey: SortKey;
    currentSort: { key: SortKey; dir: "asc" | "desc" };
    onSort: (key: SortKey) => void;
  }) => (
    <TableHead className="cursor-pointer select-none hover:bg-muted/50 whitespace-nowrap" onClick={() => onSort(sortKey)}>
      <div className="flex items-center gap-1">
        {label}
        {currentSort.key === sortKey ? (
          currentSort.dir === "asc" ? (
            <ChevronUp className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronDown className="h-3 w-3 shrink-0" />
          )
        ) : (
          <ChevronDown className="h-3 w-3 shrink-0 opacity-30" />
        )}
      </div>
    </TableHead>
  );

  const FileTable = ({
    files,
    sort,
    onSort,
    mono,
    showDelete,
  }: {
    files: string[];
    sort: { key: SortKey; dir: "asc" | "desc" };
    onSort: (key: SortKey) => void;
    mono?: boolean;
    showDelete?: boolean;
  }) => {
    const sorted = sortFiles(files, sort);
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <SortableHeader label="File name" sortKey="name" currentSort={sort} onSort={onSort} />
            <SortableHeader label="Size" sortKey="size" currentSort={sort} onSort={onSort} />
            <SortableHeader label="Update time" sortKey="modified" currentSort={sort} onSort={onSort} />
            <TableHead className="whitespace-nowrap">File type</TableHead>
            <TableHead className="w-[100px] text-center">Preview</TableHead>
            <TableHead className="w-[90px] text-center">Download</TableHead>
            {showDelete && <TableHead className="w-[70px] text-center">Delete</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((f) => {
            const detail = fileDetails[f];
            const reportInput = isReportInput(f);
            return (
              <TableRow
                key={f}
                className={cn(
                  reportInput && "bg-primary/5",
                  "hover:bg-muted/50",
                )}
              >
                <TableCell>
                  <div className="flex items-center gap-2 min-w-0">
                    {fileIcon(f)}
                    <div className="min-w-0 flex-1">
                      <span className={cn("text-sm truncate block", mono ? "font-mono text-xs" : "font-medium")}>
                        {f}
                      </span>
                      {reportInput && (
                        <span className="inline-flex items-center gap-0.5 text-[9px] text-primary font-medium px-1 py-0.5 rounded bg-primary/10 shrink-0 mt-0.5">
                          <ArrowRightCircle className="h-2.5 w-2.5" /> Report Input
                        </span>
                      )}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {detail ? formatBytes(detail.size_bytes) : "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {detail?.modified_at ? formatFileTime(detail.modified_at) : "—"}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-[10px]">{fileBadge(f)}</Badge>
                </TableCell>
                <TableCell className="text-center">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2"
                    onClick={() => handleFileClick(f)}
                    title="Preview"
                  >
                    <Eye className="h-3.5 w-3.5" />
                  </Button>
                </TableCell>
                <TableCell className="text-center">
                  <button
                    onClick={() => handleDownload(f)}
                    className="inline-flex items-center justify-center h-7 px-2 rounded-md hover:bg-muted transition-colors"
                    title="Download"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </button>
                </TableCell>
                {showDelete && (
                  <TableCell className="text-center">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-destructive hover:text-destructive hover:bg-destructive/10"
                      onClick={() => handleDeleteReport(f)}
                      disabled={deleting === f}
                      title="Delete"
                    >
                      {deleting === f ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    );
  };

  return (
    <div className="space-y-4">
      {reports.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <BookOpen className="h-4 w-4" /> Reports
              </CardTitle>
              <FolderPathBadge />
            </div>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border overflow-x-auto">
              <FileTable
                files={reports}
                sort={reportSort}
                onSort={(k) => setReportSort((s) => (s.key === k && s.dir === "asc" ? { key: k, dir: "desc" } : { key: k, dir: "asc" }))}
                showDelete
              />
            </div>
          </CardContent>
        </Card>
      )}

      {dataFiles.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <FileSpreadsheet className="h-4 w-4" /> Data Files ({dataFiles.length})
              </CardTitle>
              <FolderPathBadge />
            </div>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border overflow-x-auto">
              <FileTable
                files={dataFiles}
                sort={dataSort}
                onSort={(k) => setDataSort((s) => (s.key === k && s.dir === "asc" ? { key: k, dir: "desc" } : { key: k, dir: "asc" }))}
                mono
              />
            </div>
          </CardContent>
        </Card>
      )}

      <FilePreviewModal
        open={!!previewFile}
        onClose={() => setPreviewFile("")}
        orderId={orderId}
        filename={previewFile}
      />
    </div>
  );
}

// ── Vector Plot Tab ────────────────────────────────────────────────────────────

function VectorPlotImage({ orderId, filename }: { orderId: number; filename: string }) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    setObjectUrl(null);

    const url = `/api/orders/${orderId}/files/${encodeURIComponent(filename)}`;
    fetch(url, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        const u = URL.createObjectURL(blob);
        urlRef.current = u;
        setObjectUrl(u);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });

    return () => {
      cancelled = true;
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, [orderId, filename, retryKey]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-2 bg-muted/20 rounded-lg">
        <AlertCircle className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Failed to load image</p>
        <button
          onClick={() => setRetryKey((k) => k + 1)}
          className="text-xs text-primary hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!objectUrl) {
    return (
      <div className="flex items-center justify-center py-12 bg-muted/20 rounded-lg">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return (
    <img
      src={objectUrl}
      alt={filename}
      className="w-full h-auto object-contain"
    />
  );
}

// ── Interactive Scatter Plots (Recharts) ──────────────────────────────────────

const SCATTER_PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];

type VectorRow = {
  gene: string;
  position: string;
  condition: string;
  protein_log2fc: number;
  ptm_relative_log2fc: number;
  ptm_absolute_log2fc: number;
  quantification_track?: string;
  occupancy_fraction?: number | null;
  occupancy_percent?: number | null;
  occupancy_delta_pp?: number | null;
  occupancy_logit_delta?: number | null;
  occupancy_calibration_type?: string;
  pair_quality_tier?: string;
  pair_missingness?: number | null;
  control_pseudocount_used?: boolean;
  p_value?: number | null;
  q_value?: number | null;
};

function ScatterPlotsInteractive({ orderId }: { orderId: number }) {
  const [data, setData] = useState<{ vector_data: VectorRow[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState<"relative" | "absolute" | "occupancy">("relative");
  const [zoom, setZoom] = useState(1); // 1 = auto, zoom in = narrower range

  useEffect(() => {
    api
      .get<{ vector_data: VectorRow[] }>(`/orders/${orderId}/vector-plot-data`)
      .then((d) => setData({ vector_data: d.vector_data || [] }))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground mb-3" />
        <p className="text-sm text-muted-foreground">Loading scatter data...</p>
      </div>
    );
  }

  if (!data?.vector_data?.length) {
    return (
      <div className="flex flex-col items-center justify-center py-12 rounded-lg border bg-muted/20">
        <ChartScatter className="h-12 w-12 text-muted-foreground/40 mb-3" />
        <p className="text-sm text-muted-foreground text-center">
          Scatter data will appear here after preprocessing completes.
        </p>
      </div>
    );
  }

  const conditions = Array.from(
    new Set(data.vector_data.map((r) => r.condition).filter((c) => c && c !== "Control"))
  ).sort((a, b) => parseTimeOrder(a) - parseTimeOrder(b));

  const yKey = metric === "relative"
    ? "ptm_relative_log2fc"
    : metric === "absolute"
      ? "ptm_absolute_log2fc"
      : "occupancy_logit_delta";
  const occupancyAvailable = data.vector_data.some((row) => (
    row.pair_quality_tier === "O1" || row.pair_quality_tier === "O2"
  ) && row.occupancy_logit_delta != null);
  const metricLabel = metric === "relative"
    ? "PTM Relative"
    : metric === "absolute"
      ? "PTM Absolute"
      : "Paired Occupancy (apparent)";

  const chartsByCond = conditions.map((cond) => {
    const rows = data.vector_data.filter((r) => (
      r.condition === cond
      && (metric !== "occupancy" || (
        (r.pair_quality_tier === "O1" || r.pair_quality_tier === "O2")
        && r.occupancy_logit_delta != null
      ))
    ));
    const points = rows.map((r) => ({
      x: r.protein_log2fc ?? 0,
      y: (r[yKey as keyof VectorRow] as number) ?? 0,
      name: `${r.gene} ${r.position}`.trim() || `${r.gene}${r.position}`,
      pairTier: r.pair_quality_tier || "O0",
      calibration: r.occupancy_calibration_type || "none",
      occupancyPercent: r.occupancy_percent,
    }));
    return { condition: cond, points };
  });

  const metricRows = metric === "occupancy"
    ? data.vector_data.filter((row) => (
      (row.pair_quality_tier === "O1" || row.pair_quality_tier === "O2")
      && row.occupancy_logit_delta != null
    ))
    : data.vector_data;
  const allX = metricRows.map((r) => r.protein_log2fc ?? 0);
  const allY = metricRows.map((r) => (r[yKey as keyof VectorRow] as number) ?? 0);
  const xMin = Math.min(...allX);
  const xMax = Math.max(...allX);
  const yMin = Math.min(...allY);
  const yMax = Math.max(...allY);
  const pad = Math.max(0.3, (Math.max(xMax - xMin, yMax - yMin) || 2) * 0.1);
  const domainPadding = pad / zoom;
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
          <Button
            variant={metric === "occupancy" ? "default" : "outline"}
            size="sm"
            disabled={!occupancyAvailable}
            onClick={() => setMetric("occupancy")}
          >
            Paired Occupancy
          </Button>
        </div>
        {metric === "occupancy" && (
          <p className="w-full text-xs text-muted-foreground">
            Observed-only paired modified/unmodified peptide signal. O2 values are apparent occupancy fractions and are not calibrated physical occupancy.
          </p>
        )}
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
                {condition} ({metricLabel})
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
                      name={metric === "occupancy" ? "Occupancy logit delta" : metric === "relative" ? "PTM Relative Log2FC" : "PTM Absolute Log2FC"}
                      domain={yDomain}
                      tick={{ fontSize: 10 }}
                    />
                    <Tooltip
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
    </div>
  );
}

function parseTimeOrder(cond: string): number {
  // Normalize to minutes for correct time-series ordering.
  // Handles mixed units: '30min' and '0.5hr' both → 30.0 minutes.
  const m = cond.match(/^(\d+(?:\.\d+)?)\s*(sec|s|min|m|hr|h|hour|d|day)s?$/i);
  if (m) {
    const val = parseFloat(m[1]);
    const unit = m[2].toLowerCase();
    if (unit === "sec" || unit === "s") return val / 60;
    if (unit === "min" || unit === "m") return val;
    if (unit === "hr" || unit === "h" || unit === "hour") return val * 60;
    if (unit === "d" || unit === "day") return val * 1440;
  }
  // Bare number (assume minutes)
  const m2 = cond.match(/^(\d+(?:\.\d+)?)$/);
  if (m2) return parseFloat(m2[1]);
  // Non-time string → sort last
  return Infinity;
}

// ── PTM Trend Classification ─────────────────────────────────────────────────
// Aligned with backend temporal_comovement_node.py pattern classification
type TrendCategory =
  | "sustained_activation"
  | "sustained_inhibition"
  | "transient_burst"
  | "increasing"
  | "decreasing"
  | "biphasic"
  | "volatile"
  | "other";

const TREND_META: Record<TrendCategory, { label: string; color: string; description: string }> = {
  sustained_activation: { label: "Sustained Activation", color: "#ef4444", description: "지속적 활성화 (대부분 시간대에서 높은 양의 Log2FC)" },
  sustained_inhibition: { label: "Sustained Inhibition", color: "#8b5cf6", description: "지속적 억제 (대부분 시간대에서 음의 Log2FC)" },
  transient_burst:      { label: "Transient Burst",      color: "#f59e0b", description: "일시적 급등 후 복귀 (스파이크 패턴)" },
  increasing:           { label: "Increasing",           color: "#22c55e", description: "시간에 따른 증가 추세" },
  decreasing:           { label: "Decreasing",           color: "#3b82f6", description: "시간에 따른 감소 추세" },
  biphasic:             { label: "Biphasic",             color: "#ec4899", description: "양↔음 전환이 있는 이중 위상 패턴" },
  volatile:             { label: "Volatile",             color: "#f97316", description: "다수의 방향 전환 (불규칙 변동)" },
  other:                { label: "Other",                color: "#6b7280", description: "낮은 변동 또는 미분류 패턴" },
};

function classifyTrend(values: number[]): TrendCategory {
  if (values.length < 2) return "other";

  const n = values.length;
  const absMax = Math.max(...values.map(Math.abs));
  const range = Math.max(...values) - Math.min(...values);

  // Low-change PTMs: if max absolute value is very small, classify as other
  if (absMax < 0.8) return "other";

  // ── Metrics ──
  const posCount = values.filter((v) => v > 0.5).length;
  const negCount = values.filter((v) => v < -0.5).length;

  // Count significant direction changes (peaks/valleys)
  let dirChanges = 0;
  for (let i = 1; i < n - 1; i++) {
    const d1 = values[i] - values[i - 1];
    const d2 = values[i + 1] - values[i];
    if ((d1 > 0.3 && d2 < -0.3) || (d1 < -0.3 && d2 > 0.3)) dirChanges++;
  }

  // Count sign changes between significant values (biphasic detection)
  let signChanges = 0;
  for (let i = 1; i < n; i++) {
    if (values[i] * values[i - 1] < 0 && Math.abs(values[i]) > 0.5 && Math.abs(values[i - 1]) > 0.5) {
      signChanges++;
    }
  }

  // Spike ratio: fraction of timepoints above half-max (transient detection)
  const aboveHalf = values.filter((v) => Math.abs(v) > absMax * 0.5).length;
  const spikeRatio = aboveHalf / n;

  // Sustained ratio: fraction of timepoints with |value| > 1.0
  const sustainedCount = values.filter((v) => Math.abs(v) > 1.0).length;
  const sustainedRatio = sustainedCount / n;

  // First-half vs second-half means for trend detection
  const half = Math.floor(n / 2);
  const firstHalfMean = values.slice(0, half).reduce((a, b) => a + b, 0) / half;
  const secondHalfMean = values.slice(half).reduce((a, b) => a + b, 0) / (n - half);
  const trendDiff = secondHalfMean - firstHalfMean;

  // Step-wise direction counts
  let ups = 0;
  let downs = 0;
  for (let i = 1; i < n; i++) {
    if (values[i] > values[i - 1] + 0.2) ups++;
    else if (values[i] < values[i - 1] - 0.2) downs++;
  }

  // ── Classification (ordered by specificity) ──

  // 1. Biphasic: clear sign change between significant values
  if (signChanges >= 1 && range > 1.5) {
    return "biphasic";
  }

  // 2. Transient burst: sharp spike then return to baseline
  if (spikeRatio <= 0.4 && absMax > 2.0) {
    return "transient_burst";
  }

  // 3. Sustained activation: most timepoints significantly positive
  if (sustainedRatio >= 0.5 && posCount > negCount) {
    return "sustained_activation";
  }

  // 4. Sustained inhibition: most timepoints significantly negative
  if (sustainedRatio >= 0.5 && negCount > posCount) {
    return "sustained_inhibition";
  }

  // 5. Increasing: clear upward trend
  if (trendDiff > 0.8 && ups > downs && dirChanges <= 2) {
    return "increasing";
  }

  // 6. Decreasing: clear downward trend
  if (trendDiff < -0.8 && downs > ups && dirChanges <= 2) {
    return "decreasing";
  }

  // 7. Volatile: many direction changes with significant range
  if (dirChanges >= 3 && range > 1.5) {
    return "volatile";
  }

  // 8. Fallback for moderate signals: use weaker criteria
  if (absMax >= 1.0) {
    if (sustainedRatio >= 0.35 && posCount > negCount) return "sustained_activation";
    if (sustainedRatio >= 0.35 && negCount > posCount) return "sustained_inhibition";
    if (trendDiff > 0.5 && ups >= downs) return "increasing";
    if (trendDiff < -0.5 && downs >= ups) return "decreasing";
    if (spikeRatio <= 0.45) return "transient_burst";
  }

  // 9. Low range = other
  if (range < 1.0) return "other";

  // 10. Default: if there's some activity but no clear pattern
  if (dirChanges >= 2) return "volatile";

  return "other";
}

// ── v9.17: RoleBadge — protein class badge for Top N legend ─────────────────
const ROLE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  RTK:                { bg: "bg-rose-500/15",    text: "text-rose-400",    border: "border-rose-500/30" },
  Receptor:           { bg: "bg-rose-500/10",    text: "text-rose-300",    border: "border-rose-400/25" },
  Kinase:             { bg: "bg-blue-500/15",    text: "text-blue-400",    border: "border-blue-500/30" },
  TF:                 { bg: "bg-violet-500/15",  text: "text-violet-400",  border: "border-violet-500/30" },
  Phosphatase:        { bg: "bg-amber-500/15",   text: "text-amber-400",   border: "border-amber-500/30" },
  Adaptor:            { bg: "bg-cyan-500/15",    text: "text-cyan-400",    border: "border-cyan-500/30" },
  Chaperone:          { bg: "bg-teal-500/15",    text: "text-teal-400",    border: "border-teal-500/30" },
  Cytoskeletal:       { bg: "bg-stone-500/15",   text: "text-stone-400",   border: "border-stone-500/30" },
  "E3 ligase":        { bg: "bg-orange-500/15",  text: "text-orange-400",  border: "border-orange-500/30" },
  DUB:                { bg: "bg-lime-500/15",    text: "text-lime-400",    border: "border-lime-500/30" },
  "Autophagy receptor": { bg: "bg-pink-500/15", text: "text-pink-400",    border: "border-pink-500/30" },
  "Membrane protein": { bg: "bg-slate-500/15",   text: "text-slate-400",   border: "border-slate-500/30" },
  Nuclear:            { bg: "bg-indigo-500/15",  text: "text-indigo-400",  border: "border-indigo-500/30" },
};

const ROLE_SHORT: Record<string, string> = {
  RTK: "RTK", Receptor: "Rec", Kinase: "Kin", TF: "TF",
  Phosphatase: "PPase", Adaptor: "Adpt", Chaperone: "Chap",
  Cytoskeletal: "Cyto", "E3 ligase": "E3", DUB: "DUB",
  "Autophagy receptor": "Atg-R", "Membrane protein": "Mem",
  Nuclear: "Nuc",
};

function RoleBadge({ role, ubiContext, confidence, isUbi }: { role: string; ubiContext?: string; confidence: string; isUbi: boolean }) {
  const style = ROLE_COLORS[role] || { bg: "bg-zinc-500/15", text: "text-zinc-400", border: "border-zinc-500/30" };
  const short = ROLE_SHORT[role] || role;
  const tooltipParts = [role];
  if (ubiContext && isUbi) tooltipParts.push(ubiContext);
  tooltipParts.push(`[${confidence}]`);
  return (
    <span
      className={`inline-flex items-center gap-0.5 px-1.5 py-0 rounded text-[10px] font-semibold leading-4 border flex-shrink-0 ${style.bg} ${style.text} ${style.border}`}
      title={tooltipParts.join(" — ")}
    >
      {short}
      {ubiContext && isUbi && (
        <span className="opacity-70 text-[9px]"> {ubiContext.split(" ")[0]}</span>
      )}
    </span>
  );
}

/** API vector-plot row (numeric columns + optional stats from preprocessing v9.25+) */
type TopNVectorPlotRow = {
  gene: string;
  position: string;
  condition: string;
  ptm_relative_log2fc: number;
  ptm_absolute_log2fc: number;
  control_pseudocount_used?: boolean;
  q_value?: number | null;
};

// ── MultiSiteDivergencePanel ────────────────────────────────────────────────
// Finds same-protein multi-site pairs across different wave modules and classifies
// them into 3 biological patterns.
type DivergencePattern =
  | "signal_attenuation"
  | "sequential_regulation"
  | "multisite_coordination"
  | "same_peak_coordination"
  | "temporally_separated_same_direction"
  | "temporally_separated_opposite_direction";

interface SitePairEntry {
  gene: string;
  siteA: { position: string; label: string; waveLabel: string; peakCondition: string; peakFC: number; isDeNovo: boolean; activityClass: "de_novo" | "regulated" | "minor" };
  siteB: { position: string; label: string; waveLabel: string; peakCondition: string; peakFC: number; isDeNovo: boolean; activityClass: "de_novo" | "regulated" | "minor" };
  pattern: DivergencePattern;
  description: string;
  // v12.1 enhancements
  confidenceTier: "High" | "Medium" | "Low";
  pValue: number | null;
  isSignificant: boolean | null;
  lagMinutes: number | null;
  lagFraction: number;
  isMeaningfulLag: boolean;
  effectSize: number;
  resolutionWarning: string | null;
}

const DIVERGENCE_META: Record<DivergencePattern, { label: string; color: string; bgColor: string; borderColor: string; description: string }> = {
  signal_attenuation: {
    label: "Signal Attenuation",
    color: "text-orange-700 dark:text-orange-400",
    bgColor: "bg-orange-50 dark:bg-orange-950/30",
    borderColor: "border-orange-300 dark:border-orange-700",
          description: "초기·후기 반대 방향 site response 관찰; 신호 감쇠 메커니즘을 증명하지 않음",
  },
  sequential_regulation: {
    label: "Sequential Regulation",
    color: "text-blue-700 dark:text-blue-400",
    bgColor: "bg-blue-50 dark:bg-blue-950/30",
    borderColor: "border-blue-300 dark:border-blue-700",
          description: "두 site가 서로 다른 wave에서 반응; 독립 kinase의 순차 조절을 증명하지 않음",
  },
  multisite_coordination: {
    label: "Multisite Coordination",
    color: "text-emerald-700 dark:text-emerald-400",
    bgColor: "bg-emerald-50 dark:bg-emerald-950/30",
    borderColor: "border-emerald-300 dark:border-emerald-700",
          description: "같은 wave의 여러 site peak 관찰; 단일 kinase의 multisite phosphorylation을 증명하지 않음",
  },
  same_peak_coordination: {
    label: "Same-peak Site Coordination",
    color: "text-emerald-700 dark:text-emerald-400",
    bgColor: "bg-emerald-50 dark:bg-emerald-950/30",
    borderColor: "border-emerald-300 dark:border-emerald-700",
    description: "동일 timepoint의 site peak 관찰; 단일 kinase 또는 processivity를 증명하지 않음",
  },
  temporally_separated_same_direction: {
    label: "Temporally Separated Same-direction Response",
    color: "text-blue-700 dark:text-blue-400",
    bgColor: "bg-blue-50 dark:bg-blue-950/30",
    borderColor: "border-blue-300 dark:border-blue-700",
    description: "서로 다른 timepoint의 같은 방향 site response 관찰; 독립 kinase를 증명하지 않음",
  },
  temporally_separated_opposite_direction: {
    label: "Temporally Separated Opposite-direction Response",
    color: "text-orange-700 dark:text-orange-400",
    bgColor: "bg-orange-50 dark:bg-orange-950/30",
    borderColor: "border-orange-300 dark:border-orange-700",
    description: "서로 다른 timepoint의 반대 방향 site response 관찰; feedback 또는 activation/inhibition을 증명하지 않음",
  },
};

function canonicalDivergenceToEntry(pair: any): SitePairEntry | null {
  const parseSite = (value: unknown) => {
    const raw = String(value || "");
    const [gene, ...rest] = raw.split(" ");
    const position = rest.join(" ");
    return { gene, position, label: raw };
  };
  const a = parseSite(pair?.siteA);
  const b = parseSite(pair?.siteB);
  if (!pair?.protein || !a.position || !b.position) return null;
  const directionality = pair.directionality || {};
  const peakLag = directionality.peak_lag_minutes;
  return {
    gene: String(pair.protein),
    siteA: {
      position: a.position,
      label: a.label,
      waveLabel: String(pair.directionality_tier || "D0_unresolved"),
      peakCondition: String(pair.peak_condA || ""),
      peakFC: Number(pair.fcA || 0),
      isDeNovo: Boolean(pair.is_denovoA),
      activityClass: pair.is_denovoA ? "de_novo" : "regulated",
    },
    siteB: {
      position: b.position,
      label: b.label,
      waveLabel: String(pair.directionality_tier || "D0_unresolved"),
      peakCondition: String(pair.peak_condB || ""),
      peakFC: Number(pair.fcB || 0),
      isDeNovo: Boolean(pair.is_denovoB),
      activityClass: pair.is_denovoB ? "de_novo" : "regulated",
    },
    pattern: pair.pattern as DivergencePattern,
    description: String(pair.interpretation_boundary || "Observed site-specific temporal pattern; no causal mechanism is established."),
    confidenceTier: (pair.confidence_tier === "High" || pair.confidence_tier === "Medium") ? pair.confidence_tier : "Low",
    pValue: typeof pair.fdr_q_value === "number" ? pair.fdr_q_value : null,
    isSignificant: typeof pair.evidence_eligible_for_ai === "boolean" ? pair.evidence_eligible_for_ai : null,
    lagMinutes: typeof peakLag === "number" ? peakLag : null,
    lagFraction: Number(pair.temporal_lag || 0),
    isMeaningfulLag: pair.directionality_tier !== "D0_unresolved",
    effectSize: Number(pair.effect_size || 0),
    resolutionWarning: pair.resolution_warning || null,
  };
}

function computeMultiSiteDivergence(
  uniquePtms: Array<{ gene: string; position: string; label: string }>,
  vectorByPtm: Map<string, Array<{ condition: string; value: number }>>,
  conditions: string[],
  ptmActivityClass: Map<string, "de_novo" | "regulated" | "minor">,
  ptmPseudocountUsed: Map<string, boolean>,
): SitePairEntry[] {
  if (conditions.length < 3 || uniquePtms.length < 2) return [];

  // Assign each PTM to a wave module (peak condition index)
  const ptmPeak = new Map<string, { condIdx: number; peakCondition: string; peakFC: number }>();
  uniquePtms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    const arr = vectorByPtm.get(key);
    if (!arr) return;
    let bestIdx = 0;
    let bestAbs = 0;
    conditions.forEach((cond, idx) => {
      const row = arr.find((r) => r.condition === cond);
      const v = row?.value ?? 0;
      if (Math.abs(v) > bestAbs) { bestAbs = Math.abs(v); bestIdx = idx; }
    });
    const peakRow = arr.find((r) => r.condition === conditions[bestIdx]);
    ptmPeak.set(key, { condIdx: bestIdx, peakCondition: conditions[bestIdx], peakFC: peakRow?.value ?? 0 });
  });

  // Group PTMs by gene
  const byGene = new Map<string, typeof uniquePtms>();
  uniquePtms.forEach((p) => {
    if (!byGene.has(p.gene)) byGene.set(p.gene, []);
    byGene.get(p.gene)!.push(p);
  });

  const results: SitePairEntry[] = [];
  const seenPairs = new Set<string>();

  byGene.forEach((sites, gene) => {
    if (sites.length < 2) return;
    for (let i = 0; i < sites.length; i++) {
      for (let j = i + 1; j < sites.length; j++) {
        const pA = sites[i];
        const pB = sites[j];
        const keyA = `${pA.gene}_${pA.position}`;
        const keyB = `${pB.gene}_${pB.position}`;
        const pairKey = [keyA, keyB].sort().join("|");
        if (seenPairs.has(pairKey)) continue;
        seenPairs.add(pairKey);

        const peakA = ptmPeak.get(keyA);
        const peakB = ptmPeak.get(keyB);
        if (!peakA || !peakB) continue;

        const acA = ptmActivityClass.get(keyA) ?? "minor";
        const acB = ptmActivityClass.get(keyB) ?? "minor";
        // Only include pairs where at least one site is regulated or de_novo
        if (acA === "minor" && acB === "minor") continue;

        const isDeNovoA = ptmPseudocountUsed.get(keyA) ?? false;
        const isDeNovoB = ptmPseudocountUsed.get(keyB) ?? false;

        // Order by peak time (early → late)
        const [early, late] = peakA.condIdx <= peakB.condIdx ? [pA, pB] : [pB, pA];
        const [earlyPeak, latePeak] = peakA.condIdx <= peakB.condIdx ? [peakA, peakB] : [peakB, peakA];
        const [earlyAC, lateAC] = peakA.condIdx <= peakB.condIdx ? [acA, acB] : [acB, acA];
        const [earlyDeNovo, lateDeNovo] = peakA.condIdx <= peakB.condIdx ? [isDeNovoA, isDeNovoB] : [isDeNovoB, isDeNovoA];

        let pattern: DivergencePattern;
        let description: string;

        if (peakA.condIdx === peakB.condIdx) {
          pattern = "multisite_coordination";
          description = `${gene} ${early.position} + ${late.position}이 동일 timepoint (peak: ${earlyPeak.peakCondition})에서 peak를 보임 → same-peak site coordination 관찰`;
        } else if (earlyPeak.peakFC > 0 && latePeak.peakFC < 0) {
          pattern = "signal_attenuation";
          description = `${gene} ${early.position}과 ${late.position}에서 시간적으로 분리된 반대 방향 response 관찰; feedback 또는 attenuation을 증명하지 않음`;
        } else if (earlyPeak.peakFC < 0 && latePeak.peakFC > 0) {
          pattern = "signal_attenuation";
          description = `${gene} ${early.position}과 ${late.position}에서 시간적으로 분리된 반대 방향 response 관찰; inhibition-to-activation mechanism을 증명하지 않음`;
        } else {
          pattern = "sequential_regulation";
          const dir = earlyPeak.peakFC > 0 && latePeak.peakFC > 0 ? "두 Activating site" : "두 Inhibitory site";
          description = `${gene} ${early.position} (wave: ${earlyPeak.peakCondition})와 ${late.position} (wave: ${latePeak.peakCondition})의 시간적으로 분리된 ${dir} site response 관찰`;
        }

        // v12.1 #3: Lag computation
        const lagIdx = Math.abs(latePeak.condIdx - earlyPeak.condIdx);
        const lagFraction = lagIdx / Math.max(conditions.length - 1, 1);
        // Try to parse real time from condition names
        let lagMinutes: number | null = null;
        let isMeaningfulLag = lagIdx >= 1;
        const parseTimeMin = (cond: string): number | null => {
          const m = cond.match(/(\d+(?:\.\d+)?)\s*min/i);
          if (m) return parseFloat(m[1]);
          const h = cond.match(/(\d+(?:\.\d+)?)\s*(?:hr|hour|h)$/i);
          if (h) return parseFloat(h[1]) * 60;
          const s = cond.match(/(\d+(?:\.\d+)?)\s*sec/i);
          if (s) return parseFloat(s[1]) / 60;
          return null;
        };
        if (lagIdx > 0) {
          const tEarly = parseTimeMin(earlyPeak.peakCondition);
          const tLate = parseTimeMin(latePeak.peakCondition);
          if (tEarly !== null && tLate !== null) {
            lagMinutes = Math.round(Math.abs(tLate - tEarly) * 10) / 10;
            isMeaningfulLag = lagMinutes >= 5.0;
          }
        }

        // v12.1 #4: Confidence tier (MAD-based effect_size)
        const allFCsForMAD = Array.from(ptmPeak.values()).map((p) => Math.abs(p.peakFC)).filter((v) => v > 0.01);
        let madFC = 1.0;
        if (allFCsForMAD.length > 0) {
          const sorted = [...allFCsForMAD].sort((a, b) => a - b);
          const medFC = sorted[Math.floor(sorted.length / 2)];
          const deviations = allFCsForMAD.map((v) => Math.abs(v - medFC)).sort((a, b) => a - b);
          madFC = Math.max(deviations[Math.floor(deviations.length / 2)], 0.1);
        }
        const effectSize = Math.abs(earlyPeak.peakFC - latePeak.peakFC) / madFC;
        let confidenceTier: "High" | "Medium" | "Low" = "Low";
        if (effectSize >= 2.0) confidenceTier = "High";
        else if (effectSize >= 1.0) confidenceTier = "Medium";

        // v12.1 #5: Resolution warning
        const resolutionWarning = conditions.length <= 3 ? `LOW RESOLUTION: Only ${conditions.length} timepoints` : null;

        // v12.1 #6: Permutation p-value
        let pValue: number | null = null;
        let isSignificant: boolean | null = null;
        const keyEarly = `${gene}_${early.position}`;
        const keyLate = `${gene}_${late.position}`;
        const arrEarly = vectorByPtm.get(keyEarly);
        const arrLate = vectorByPtm.get(keyLate);
        if (arrEarly && arrLate && conditions.length >= 3) {
          const valsE = conditions.map((c) => arrEarly.find((r) => r.condition === c)?.value ?? 0);
          const valsL = conditions.map((c) => arrLate.find((r) => r.condition === c)?.value ?? 0);
          const obsDivergence = valsE.reduce((sum, v, i) => sum + (v - valsL[i]) ** 2, 0);
          const combined = [...valsE, ...valsL];
          const half = valsE.length;
          let countGE = 0;
          const nPerm = 500; // reduced for frontend performance
          // Simple seeded PRNG (xorshift32)
          let seed = 42;
          const xorshift = () => { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; return (seed >>> 0) / 4294967296; };
          for (let p = 0; p < nPerm; p++) {
            // Fisher-Yates shuffle
            const perm = [...combined];
            for (let i = perm.length - 1; i > 0; i--) {
              const j = Math.floor(xorshift() * (i + 1));
              [perm[i], perm[j]] = [perm[j], perm[i]];
            }
            const permDiv = perm.slice(0, half).reduce((sum, v, i) => sum + (v - perm[half + i]) ** 2, 0);
            if (permDiv >= obsDivergence) countGE++;
          }
          pValue = Math.round(((countGE + 1) / (nPerm + 1)) * 10000) / 10000;
          isSignificant = pValue < 0.05;
        }

        results.push({
          gene,
          siteA: { position: early.position, label: early.label, waveLabel: `Wave (peak: ${earlyPeak.peakCondition})`, peakCondition: earlyPeak.peakCondition, peakFC: earlyPeak.peakFC, isDeNovo: earlyDeNovo, activityClass: earlyAC },
          siteB: { position: late.position, label: late.label, waveLabel: `Wave (peak: ${latePeak.peakCondition})`, peakCondition: latePeak.peakCondition, peakFC: latePeak.peakFC, isDeNovo: lateDeNovo, activityClass: lateAC },
          pattern,
          description,
          confidenceTier,
          pValue,
          isSignificant,
          lagMinutes,
          lagFraction,
          isMeaningfulLag,
          effectSize: Math.round(effectSize * 1000) / 1000,
          resolutionWarning,
        });
      }
    }
  });

  const ORDER: Record<DivergencePattern, number> = {
    signal_attenuation: 0,
    sequential_regulation: 1,
    multisite_coordination: 2,
    temporally_separated_opposite_direction: 0,
    temporally_separated_same_direction: 1,
    same_peak_coordination: 2,
  };
  const TIER_ORDER: Record<string, number> = { High: 0, Medium: 1, Low: 2 };
  results.sort((a, b) => {
    const patDiff = ORDER[a.pattern] - ORDER[b.pattern];
    if (patDiff !== 0) return patDiff;
    // Within same pattern: High > Medium > Low confidence
    const tierDiff = (TIER_ORDER[a.confidenceTier] ?? 3) - (TIER_ORDER[b.confidenceTier] ?? 3);
    if (tierDiff !== 0) return tierDiff;
    // Then by effect size descending
    return b.effectSize - a.effectSize;
  });
  return results;
}

// ── Sparkline SVG (mini time-series for each site) ───────────────────────
function SiteSpark({
  values,
  width = 72,
  height = 28,
  isActivating,
}: {
  values: number[];
  width?: number;
  height?: number;
  isActivating: boolean;
}) {
  if (values.length < 2) return null;
  const maxAbs = Math.max(...values.map(Math.abs), 0.1);
  const pad = 3;
  const w = width - pad * 2;
  const h = height - pad * 2;
  const mid = pad + h / 2;
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * w;
    const y = mid - (v / maxAbs) * (h / 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = isActivating ? "#ef4444" : "#3b82f6";
  const fill = isActivating ? "rgba(239,68,68,0.08)" : "rgba(59,130,246,0.08)";
  // Area fill path
  const areaD = `M${pts[0]} ` + pts.slice(1).map((p) => `L${p}`).join(" ") + ` L${(pad + w).toFixed(1)},${mid.toFixed(1)} L${pad},${mid.toFixed(1)} Z`;
  return (
    <svg width={width} height={height} className="overflow-visible shrink-0">
      <line x1={pad} y1={mid} x2={pad + w} y2={mid} stroke="currentColor" strokeOpacity="0.15" strokeWidth="0.5" />
      <path d={areaD} fill={fill} />
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      {values.map((v, i) => {
        const x = pad + (i / (values.length - 1)) * w;
        const y = mid - (v / maxAbs) * (h / 2);
        const isPeak = Math.abs(v) === Math.max(...values.map(Math.abs));
        return isPeak ? (
          <circle key={i} cx={x.toFixed(1)} cy={y.toFixed(1)} r="2.5" fill={color} />
        ) : null;
      })}
    </svg>
  );
}

function MultiSiteDivergencePanel({
  uniquePtms,
  vectorByPtm,
  conditions,
  ptmActivityClass,
  ptmPseudocountUsed,
  canonicalPairs,
  onHighlightPtms,
}: {
  uniquePtms: Array<{ gene: string; position: string; label: string }>;
  vectorByPtm: Map<string, Array<{ condition: string; value: number }>>;
  conditions: string[];
  ptmActivityClass: Map<string, "de_novo" | "regulated" | "minor">;
  ptmPseudocountUsed: Map<string, boolean>;
  canonicalPairs?: any[];
  onHighlightPtms: (labels: string[]) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [patternFilter, setPatternFilter] = useState<DivergencePattern | "all">("all");
  const [hoveredGene, setHoveredGene] = useState<string | null>(null);

  const entries = useMemo(
    () => {
      const serverEntries = (canonicalPairs || []).map(canonicalDivergenceToEntry).filter((entry): entry is SitePairEntry => entry !== null);
      return serverEntries.length > 0
        ? serverEntries
        : computeMultiSiteDivergence(uniquePtms, vectorByPtm, conditions, ptmActivityClass, ptmPseudocountUsed);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [uniquePtms.length, conditions.join(","), vectorByPtm.size, ptmActivityClass.size, ptmPseudocountUsed.size, canonicalPairs?.length]
  );

  if (entries.length === 0) return null;

  // Group entries by gene for swimlane display
  const byGene = new Map<string, SitePairEntry[]>();
  entries.forEach((e) => {
    if (!byGene.has(e.gene)) byGene.set(e.gene, []);
    byGene.get(e.gene)!.push(e);
  });

  // Collect all unique sites per gene (across all pairs)
  const geneSites = new Map<string, Array<{ position: string; label: string; peakFC: number; peakCondition: string; peakCondIdx: number; isDeNovo: boolean; activityClass: "de_novo" | "regulated" | "minor"; values: number[] }>>();
  byGene.forEach((geneEntries, gene) => {
    const siteMap = new Map<string, (typeof geneSites extends Map<string, Array<infer T>> ? T : never)>();
    geneEntries.forEach((e) => {
      [e.siteA, e.siteB].forEach((s) => {
        if (!siteMap.has(s.position)) {
          const key = `${gene}_${s.position}`;
          const arr = vectorByPtm.get(key) ?? [];
          const values = conditions.map((c) => arr.find((r) => r.condition === c)?.value ?? 0);
          const peakCondIdx = conditions.indexOf(s.peakCondition);
          siteMap.set(s.position, {
            position: s.position,
            label: s.label,
            peakFC: s.peakFC,
            peakCondition: s.peakCondition,
            peakCondIdx: peakCondIdx >= 0 ? peakCondIdx : 0,
            isDeNovo: s.isDeNovo,
            activityClass: s.activityClass,
            values,
          });
        }
      });
    });
    // Sort sites by peak condition index (time order)
    geneSites.set(gene, Array.from(siteMap.values()).sort((a, b) => a.peakCondIdx - b.peakCondIdx));
  });

  const counts: Record<DivergencePattern, number> = {
    signal_attenuation: 0,
    sequential_regulation: 0,
    multisite_coordination: 0,
    temporally_separated_opposite_direction: 0,
    temporally_separated_same_direction: 0,
    same_peak_coordination: 0,
  };
  entries.forEach((e) => { counts[e.pattern]++; });

  const filteredGenes = patternFilter === "all"
    ? Array.from(byGene.keys())
    : Array.from(byGene.entries()).filter(([, gEntries]) => gEntries.some((e) => e.pattern === patternFilter)).map(([g]) => g);

  // Max bubble radius in px
  const BUBBLE_R_MAX = 18;
  const BUBBLE_R_MIN = 6;
  const allFCs = Array.from(geneSites.values()).flatMap((sites) => sites.map((s) => Math.abs(s.peakFC)));
  const globalMaxFC = Math.max(...allFCs, 1);
  function bubbleR(fc: number) {
    return BUBBLE_R_MIN + ((Math.abs(fc) / globalMaxFC) * (BUBBLE_R_MAX - BUBBLE_R_MIN));
  }

  // Pattern color for connector line between sites
  function connectorColor(pattern: DivergencePattern) {
    if (pattern === "signal_attenuation") return "#f97316"; // orange
    if (pattern === "sequential_regulation") return "#3b82f6"; // blue
    return "#10b981"; // emerald
  }

  // Condition column width
  const COL_W = 90;
  const GENE_LABEL_W = 80;
  const SPARK_W = 68;
  const SPARK_H = 26;

  // Compute per-gene row height based on max sites sharing the same condition
  // Activating sites go above center, inhibitory sites go below center
  // Each site needs ~38px vertical space
  const SITE_SLOT_H = 38;
  const CENTER_GAP = 10; // gap between activation zone and inhibition zone
  function geneRowLayout(sites: typeof geneSites extends Map<string, Array<infer T>> ? Array<T> : never[]) {
    // Count max activating and inhibitory sites at same condition
    const actByCondIdx = new Map<number, number>();
    const inhByCondIdx = new Map<number, number>();
    sites.forEach((s) => {
      const idx = s.peakCondIdx;
      if (s.peakFC >= 0) actByCondIdx.set(idx, (actByCondIdx.get(idx) ?? 0) + 1);
      else inhByCondIdx.set(idx, (inhByCondIdx.get(idx) ?? 0) + 1);
    });
    const maxAct = Math.max(0, ...Array.from(actByCondIdx.values()));
    const maxInh = Math.max(0, ...Array.from(inhByCondIdx.values()));
    const actZoneH = maxAct * SITE_SLOT_H;
    const inhZoneH = maxInh * SITE_SLOT_H;
    const totalH = Math.max(72, actZoneH + CENTER_GAP + inhZoneH + 16);
    const centerY = actZoneH + CENTER_GAP / 2 + 8; // y of the horizontal center line
    return { totalH, centerY, actZoneH, inhZoneH };
  }

  return (
    <div className="rounded-lg border bg-card">
      {/* Header */}
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-muted/30 transition-colors rounded-t-lg"
        onClick={() => setCollapsed((v) => !v)}
      >
        <div className="flex items-center gap-2">
          <GitMerge className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-semibold">Multi-site Temporal Divergence</span>
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">{entries.length} pairs</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground hidden sm:inline">같은 단백질 내 site 간 시간적 분기 패턴</span>
          {collapsed ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronUp className="h-4 w-4 text-muted-foreground" />}
        </div>
      </button>

      {!collapsed && (
        <div className="px-4 pb-4 space-y-3">
          {/* Pattern filter */}
          <div className="flex flex-wrap gap-1.5 pt-1">
            <button
              onClick={() => setPatternFilter("all")}
              className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${
                patternFilter === "all"
                  ? "bg-foreground text-background border-foreground"
                  : "bg-background text-muted-foreground border-border hover:border-foreground/50"
              }`}
            >
              All ({entries.length})
            </button>
            {(Object.keys(DIVERGENCE_META) as DivergencePattern[]).map((pat) => {
              const meta = DIVERGENCE_META[pat];
              if (counts[pat] === 0) return null;
              return (
                <button
                  key={pat}
                  onClick={() => setPatternFilter(pat)}
                  className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${
                    patternFilter === pat
                      ? `${meta.bgColor} ${meta.color} ${meta.borderColor}`
                      : "bg-background text-muted-foreground border-border hover:border-foreground/50"
                  }`}
                >
                  {meta.label} ({counts[pat]})
                </button>
              );
            })}
          </div>

          {/* ── Bubble Swimlane ── */}
          <div className="overflow-x-auto">
            {/* Condition header row */}
            <div
              className="flex items-center text-[10px] text-muted-foreground font-medium border-b border-border/40 pb-1 mb-1"
              style={{ minWidth: GENE_LABEL_W + COL_W * conditions.length }}
            >
              <div style={{ width: GENE_LABEL_W }} className="shrink-0 pr-2 text-right">Protein</div>
              {conditions.map((c) => (
                <div key={c} style={{ width: COL_W }} className="shrink-0 text-center truncate px-1">{c}</div>
              ))}
            </div>

            {/* Gene swimlane rows */}
            {filteredGenes.map((gene) => {
              const sites = geneSites.get(gene) ?? [];
              const geneEntries = byGene.get(gene) ?? [];
              const isHovered = hoveredGene === gene;
              const { totalH, centerY } = geneRowLayout(sites);

              // Assign Y positions: activating sites above center, inhibitory below
              // Track slot index per condIdx per direction
              const actSlotCounter = new Map<number, number>();
              const inhSlotCounter = new Map<number, number>();
              const sitePositions = sites.map((site) => {
                const isAct = site.peakFC >= 0;
                const condIdx = site.peakCondIdx;
                const cx = condIdx * COL_W + COL_W / 2;
                const r = bubbleR(site.peakFC);
                let cy: number;
                if (isAct) {
                  const slot = actSlotCounter.get(condIdx) ?? 0;
                  actSlotCounter.set(condIdx, slot + 1);
                  // Stack upward from centerY: slot 0 is closest to center
                  cy = centerY - r - 4 - slot * SITE_SLOT_H;
                } else {
                  const slot = inhSlotCounter.get(condIdx) ?? 0;
                  inhSlotCounter.set(condIdx, slot + 1);
                  // Stack downward from centerY
                  cy = centerY + r + 4 + slot * SITE_SLOT_H;
                }
                return { ...site, cx, cy, r };
              });

              // Build a map for connector endpoint lookup
              const siteYMap = new Map<string, { cx: number; cy: number; r: number }>();
              sitePositions.forEach((s) => siteYMap.set(s.position, { cx: s.cx, cy: s.cy, r: s.r }));

              return (
                <div
                  key={gene}
                  className={`flex items-start border-b border-border/20 last:border-0 transition-colors ${
                    isHovered ? "bg-muted/20" : ""
                  }`}
                  style={{ minWidth: GENE_LABEL_W + COL_W * conditions.length, minHeight: totalH }}
                  onMouseEnter={() => setHoveredGene(gene)}
                  onMouseLeave={() => setHoveredGene(null)}
                >
                  {/* Gene label */}
                  <div
                    style={{ width: GENE_LABEL_W, paddingTop: centerY - 7 }}
                    className="shrink-0 pr-3 text-right text-[11px] font-bold text-foreground/80"
                  >
                    {gene}
                  </div>

                  {/* Swimlane SVG canvas */}
                  <svg
                    width={COL_W * conditions.length}
                    height={totalH}
                    className="overflow-visible"
                    style={{ minWidth: COL_W * conditions.length }}
                  >
                    {/* Horizontal center line */}
                    <line
                      x1={0} y1={centerY}
                      x2={COL_W * conditions.length} y2={centerY}
                      stroke="currentColor" strokeOpacity="0.12" strokeWidth="1"
                    />
                    {/* Activation zone label */}
                    <text x={4} y={Math.max(12, centerY - 6)} fontSize="8" fill="#ef4444" opacity="0.5" fontWeight="600">ACT</text>
                    {/* Inhibition zone label */}
                    <text x={4} y={Math.min(totalH - 4, centerY + 14)} fontSize="8" fill="#3b82f6" opacity="0.5" fontWeight="600">INH</text>

                    {/* Connector lines between paired sites */}
                    {geneEntries
                      .filter((e) => patternFilter === "all" || e.pattern === patternFilter)
                      .map((e, ei) => {
                        const posA = siteYMap.get(e.siteA.position);
                        const posB = siteYMap.get(e.siteB.position);
                        if (!posA || !posB) return null;
                        const color = connectorColor(e.pattern);
                        const markerId = `arrow-${gene}-${ei}`;
                        // Draw curved connector between the two bubbles
                        const dx = posB.cx - posA.cx;
                        const dy = posB.cy - posA.cy;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < 1) return null;
                        // Endpoint on bubble edge
                        const ex1 = posA.cx + (dx / dist) * (posA.r + 2);
                        const ey1 = posA.cy + (dy / dist) * (posA.r + 2);
                        const ex2 = posB.cx - (dx / dist) * (posB.r + 4);
                        const ey2 = posB.cy - (dy / dist) * (posB.r + 4);
                        // Bezier control point (arc above/below)
                        const midX = (ex1 + ex2) / 2;
                        const midY = (ey1 + ey2) / 2 - Math.abs(dx) * 0.15;
                        // v12.1: confidence tier badge color
                        const tierColor = e.confidenceTier === "High" ? "#16a34a" : e.confidenceTier === "Medium" ? "#ca8a04" : "#9ca3af";
                        const tierLabel = e.confidenceTier === "High" ? "H" : e.confidenceTier === "Medium" ? "M" : "L";
                        const tooltipParts = [`Tier: ${e.confidenceTier}`, `Effect: ${e.effectSize.toFixed(2)}`];
                        if (e.pValue !== null) tooltipParts.push(`p=${e.pValue.toFixed(3)}${e.isSignificant ? " *" : " (ns)"}`);
                        if (e.lagMinutes !== null) tooltipParts.push(`Lag: ${e.lagMinutes}min`);
                        else if (e.lagFraction > 0) tooltipParts.push(`LagFrac: ${(e.lagFraction * 100).toFixed(0)}%`);
                        if (e.resolutionWarning) tooltipParts.push(e.resolutionWarning);
                        const connTooltip = tooltipParts.join(" | ");
                        return (
                          <g key={ei}>
                            <title>{connTooltip}</title>
                            <defs>
                              <marker id={markerId} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                                <path d="M0,0 L0,6 L6,3 z" fill={color} opacity="0.8" />
                              </marker>
                            </defs>
                            <path
                              d={`M${ex1.toFixed(1)},${ey1.toFixed(1)} Q${midX.toFixed(1)},${midY.toFixed(1)} ${ex2.toFixed(1)},${ey2.toFixed(1)}`}
                              fill="none"
                              stroke={color}
                              strokeWidth={e.confidenceTier === "Low" ? "1" : "1.5"}
                              strokeOpacity={e.confidenceTier === "Low" ? "0.35" : e.isSignificant === false ? "0.5" : "0.65"}
                              strokeDasharray={e.pattern === "multisite_coordination" ? "3,2" : e.confidenceTier === "Low" ? "2,3" : undefined}
                              markerEnd={`url(#${markerId})`}
                            />
                            {/* Confidence tier badge at midpoint */}
                            <circle cx={midX} cy={midY - 2} r="5" fill={tierColor} opacity="0.85" />
                            <text x={midX} y={midY + 1} textAnchor="middle" fontSize="6" fill="white" fontWeight="700">{tierLabel}</text>
                          </g>
                        );
                      })}

                    {/* Bubble nodes per site */}
                    {sitePositions.map((site) => {
                      const { cx, cy, r } = site;
                      const isAct = site.peakFC > 0;
                      const fill = isAct ? "#ef4444" : "#3b82f6";
                      const fillLight = isAct ? "rgba(239,68,68,0.15)" : "rgba(59,130,246,0.15)";
                      const strokeStyle = site.isDeNovo ? "4,2" : undefined;
                      // Label goes above bubble for activating, below for inhibitory
                      const labelY = isAct ? cy - r - 5 : cy + r + 12;

                      return (
                        <g
                          key={site.position}
                          className="cursor-pointer"
                          onClick={() => onHighlightPtms([site.label])}
                        >
                          <title>{`${site.label}: ${site.peakFC > 0 ? "+" : ""}${site.peakFC.toFixed(2)} @ ${site.peakCondition}${site.isDeNovo ? " ⚡de novo" : ""}`}</title>
                          {/* Outer glow for de_novo */}
                          {site.isDeNovo && (
                            <circle cx={cx} cy={cy} r={r + 4} fill="none" stroke="#f97316" strokeWidth="1.2" strokeOpacity="0.5" strokeDasharray="2,2" />
                          )}
                          {/* Main bubble */}
                          <circle cx={cx} cy={cy} r={r} fill={fillLight} stroke={fill} strokeWidth={site.activityClass === "minor" ? 1 : 2} strokeDasharray={strokeStyle} />
                          {/* Site label — colored by direction */}
                          <text
                            x={cx}
                            y={labelY}
                            textAnchor="middle"
                            fontSize="9"
                            fill={fill}
                            fontWeight="700"
                          >
                            {site.position}{site.isDeNovo ? " ⚡" : ""}
                          </text>
                          {/* FC value inside bubble */}
                          {r >= 11 && (
                            <text
                              x={cx}
                              y={cy + 3.5}
                              textAnchor="middle"
                              fontSize="8"
                              fill={fill}
                              fontWeight="700"
                            >
                              {site.peakFC > 0 ? "+" : ""}{site.peakFC.toFixed(1)}
                            </text>
                          )}
                        </g>
                      );
                    })}
                  </svg>

                  {/* Sparklines column (one per site, stacked) */}
                  <div className="flex flex-col gap-0.5 pl-2 self-center">
                    {sites.map((site) => {
                      const isAct = site.peakFC > 0;
                      return (
                        <div
                          key={site.position}
                          className="flex items-center gap-1 cursor-pointer"
                          onClick={() => onHighlightPtms([site.label])}
                          title={`${site.label} time-series`}
                        >
                          <span
                            className="text-[8px] font-mono w-10 text-right shrink-0"
                            style={{ color: isAct ? "#ef4444" : "#3b82f6" }}
                          >
                            {site.position}
                          </span>
                          <SiteSpark
                            values={site.values}
                            width={SPARK_W}
                            height={SPARK_H}
                            isActivating={isAct}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Pattern legend */}
          <div className="pt-2 border-t border-border/50 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <svg width="20" height="8"><line x1="0" y1="4" x2="20" y2="4" stroke="#f97316" strokeWidth="1.5" /><path d="M16,1 L16,7 L20,4 z" fill="#f97316" /></svg>
              Signal Attenuation
            </span>
            <span className="flex items-center gap-1">
              <svg width="20" height="8"><line x1="0" y1="4" x2="20" y2="4" stroke="#3b82f6" strokeWidth="1.5" /><path d="M16,1 L16,7 L20,4 z" fill="#3b82f6" /></svg>
              Sequential Regulation
            </span>
            <span className="flex items-center gap-1">
              <svg width="20" height="8"><line x1="0" y1="4" x2="20" y2="4" stroke="#10b981" strokeWidth="1.5" strokeDasharray="3,2" /><path d="M16,1 L16,7 L20,4 z" fill="#10b981" /></svg>
              Multisite Coordination
            </span>
            <span className="flex items-center gap-1">
              <svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="rgba(239,68,68,0.15)" stroke="#ef4444" strokeWidth="2" /></svg>
              Activating (FC &gt; 0)
            </span>
            <span className="flex items-center gap-1">
              <svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="rgba(59,130,246,0.15)" stroke="#3b82f6" strokeWidth="2" /></svg>
              Inhibitory (FC &lt; 0)
            </span>
            <span className="flex items-center gap-1">
              <svg width="12" height="12"><circle cx="6" cy="6" r="4" fill="none" stroke="#f97316" strokeWidth="1" strokeDasharray="2,2" /></svg>
              ⚡ De novo
            </span>
            <span className="flex items-center gap-1">
              <svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="#16a34a" opacity="0.85" /><text x="6" y="9" textAnchor="middle" fontSize="6" fill="white" fontWeight="700">H</text></svg>
              High Confidence
            </span>
            <span className="flex items-center gap-1">
              <svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="#ca8a04" opacity="0.85" /><text x="6" y="9" textAnchor="middle" fontSize="6" fill="white" fontWeight="700">M</text></svg>
              Medium
            </span>
            <span className="flex items-center gap-1">
              <svg width="12" height="12"><circle cx="6" cy="6" r="5" fill="#9ca3af" opacity="0.85" /><text x="6" y="9" textAnchor="middle" fontSize="6" fill="white" fontWeight="700">L</text></svg>
              Low (tentative)
            </span>
            <span className="col-span-2 sm:col-span-3 text-[9px] opacity-60">
              버블 크기 = |FC| 크기. 클릭 시 라인 차트에서 하이라이트. 커넥터 hover 시 p-value/lag/effect size 확인.
            </span>
            {entries[0]?.resolutionWarning && (
              <span className="col-span-2 sm:col-span-3 text-[9px] text-amber-600 dark:text-amber-400 font-medium">
                ⚠️ {entries[0].resolutionWarning}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── TopNTimeSeriesPlot ───────────────────────────────────────────────────────
function TopNTimeSeriesPlot({ orderId, ptmType = "phosphorylation" }: { orderId: number; ptmType?: string }) {
  const isUbi = ptmType.toLowerCase().includes("ubiquityl") || ptmType.toLowerCase().includes("ubiquitin");
  const [data, setData] = useState<{ vector_data: TopNVectorPlotRow[]; top_n_ptms: Array<{ gene: string; position: string; label: string; protein_class?: { role: string; confidence: string; tags: string[]; ubi_context?: string } }>; suggested_n?: number | null; top_n_setting?: number; source?: string; inferred_receptors?: Array<{ name: string; receptor_class: string; downstream_ptm_count: number; downstream_ptms: string[]; via_kinases?: string[]; pathway?: string; signaling_pathway?: string; source?: string }>; divergence_pairs?: any[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [metric, setMetric] = useState<"relative" | "absolute">("relative");
  const [trendFilter, setTrendFilter] = useState<TrendCategory | "all">("all");
  const [yZoom, setYZoom] = useState(1); // 1 = default, <1 = zoom in (narrower range), >1 = zoom out (wider range)
  const [hoveredPtm, setHoveredPtm] = useState<string | null>(null);
  const [yManualMin, setYManualMin] = useState<string>("");
  const [yManualMax, setYManualMax] = useState<string>("");
  // v9.21: receptor → kinase highlight linkage
  const [selectedHighlightKinase, setSelectedHighlightKinase] = useState<string | null>(null);
  // v9.23: Bimodal activity filter (de_novo / regulated / minor)
  const [activityFilter, setActivityFilter] = useState<"all" | "de_novo" | "regulated" | "minor">("all");
  // Module highlight: PTM labels of the highlighted module (empty = none)
  const [highlightedModulePtmLabels, setHighlightedModulePtmLabels] = useState<Set<string>>(new Set());
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [refreshingReceptors, setRefreshingReceptors] = useState(false);
  // v11.9: fetch ip_overlay_data from order (previously referenced non-existent 'order' variable)
  const [ipOverlayData, setIpOverlayData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    api.get<{ ip_overlay_data?: Record<string, unknown> | null }>(`/orders/${orderId}`)
      .then((o) => setIpOverlayData(o.ip_overlay_data ?? null))
      .catch(() => setIpOverlayData(null));
  }, [orderId]);

  const fetchVectorPlotData = (forceRefresh = false) => {
    const params = forceRefresh ? "?force_refresh=true" : "";
    return api
      .get<{ vector_data: unknown[]; top_n_ptms: Array<{ gene: string; position: string; label: string; protein_class?: { role: string; confidence: string; tags: string[]; ubi_context?: string } }>; suggested_n?: number | null; top_n_setting?: number; source?: string; inferred_receptors?: Array<{ name: string; receptor_class: string; downstream_ptm_count: number; downstream_ptms: string[]; via_kinases?: string[]; pathway?: string; signaling_pathway?: string; source?: string }> }>(`/orders/${orderId}/vector-plot-data${params}`);
  };

  const refreshReceptorInference = async () => {
    setRefreshingReceptors(true);
    try {
      const d = await fetchVectorPlotData(true);
      setData((prev) => prev ? { ...prev, inferred_receptors: d.inferred_receptors || [] } : prev);
    } catch (err) {
      console.error("Failed to refresh receptor inference:", err);
    } finally {
      setRefreshingReceptors(false);
    }
  };

  useEffect(() => {
    fetchVectorPlotData()
      .then((d) => {
        setData({
          vector_data: (d.vector_data || []) as TopNVectorPlotRow[],
          top_n_ptms: d.top_n_ptms || [],
          suggested_n: d.suggested_n,
          top_n_setting: d.top_n_setting,
          source: d.source,
          inferred_receptors: d.inferred_receptors || [],
        });
        // Deduplicate by gene_position key — keep first occurrence
        const seen = new Set<string>();
        const init: Record<string, boolean> = {};
        (d.top_n_ptms || []).forEach((p) => {
          const key = `${p.gene}_${p.position}`;
          if (!seen.has(key)) {
            seen.add(key);
            init[key] = true;
          }
        });
        setChecked(init);
      })
      .catch(() => setData({ vector_data: [], top_n_ptms: [] }))
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-3" />
        <p className="text-sm text-muted-foreground">Loading time-series data...</p>
      </div>
    );
  }

  if (!data || data.top_n_ptms.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 rounded-lg border bg-muted/20">
        <TrendingUp className="h-12 w-12 text-muted-foreground/40 mb-3" />
        <p className="text-sm text-muted-foreground text-center">
          {isUbi
            ? "Top N Ubiquitylation site time-series data will appear here after preprocessing completes."
            : "Top N PTM time-series data will appear here after preprocessing completes."}
        </p>
      </div>
    );
  }

  const valueKey = metric === "relative" ? "ptm_relative_log2fc" : "ptm_absolute_log2fc";

  // Deduplicate top_n_ptms by gene_position
  const seenKeys = new Set<string>();
  const uniquePtms = data.top_n_ptms.filter((p) => {
    const key = `${p.gene}_${p.position}`;
    if (seenKeys.has(key)) return false;
    seenKeys.add(key);
    return true;
  });

  const topNSet = new Set(uniquePtms.map((p) => `${p.gene}_${p.position}`));
  const vectorByPtm = new Map<string, Array<{ condition: string; value: number }>>();
  // Track which PTMs had control pseudocount imputation (de novo flag from preprocessing)
  const ptmPseudocountUsed = new Map<string, boolean>();
  // v9.25: Track minimum q_value per PTM across conditions
  const ptmMinQValue = new Map<string, number | null>();

  data.vector_data.forEach((row) => {
    const key = `${row.gene}_${row.position}`;
    if (!topNSet.has(key)) return;
    if (!vectorByPtm.has(key)) vectorByPtm.set(key, []);
    vectorByPtm.get(key)!.push({ condition: row.condition, value: row[valueKey as keyof typeof row] as number });
    // If any condition row for this PTM has control_pseudocount_used=true, mark it
    if (row.control_pseudocount_used) ptmPseudocountUsed.set(key, true);
    // Track minimum q_value across conditions for this PTM
    if (row.q_value != null && !isNaN(row.q_value)) {
      const prev = ptmMinQValue.get(key);
      if (prev == null || row.q_value < prev) ptmMinQValue.set(key, row.q_value);
    }
  });

  const conditions = Array.from(
    new Set(data.vector_data.map((r) => r.condition).filter(Boolean))
  ).sort((a, b) => parseTimeOrder(a) - parseTimeOrder(b));

  // Classify each PTM trend
  const ptmTrends = new Map<string, TrendCategory>();
  uniquePtms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    const arr = vectorByPtm.get(key);
    if (!arr) { ptmTrends.set(key, "other"); return; }
    const sorted = conditions.map((c) => arr.find((r) => r.condition === c)?.value ?? 0);
    ptmTrends.set(key, classifyTrend(sorted));
  });

  // v9.25: Bimodal activity classification per PTM (updated with q_value support)
  // ── 2-pass activity classification (matches RAG worker logic) ──────────────
  // Pass 1: Strict (q_value < 0.05 AND |FC| >= 1.0)
  // Pass 2: If Pass 1 yields 0 regulated, relax to |FC| >= 0.8
  const ptmActivityClass = new Map<string, "de_novo" | "regulated" | "minor">();
  const _hasAnyQValue = Array.from(ptmMinQValue.values()).some((v) => v != null);

  // Pass 1: classify all PTMs
  uniquePtms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    const arr = vectorByPtm.get(key);
    if (!arr || !conditions.length) { ptmActivityClass.set(key, "minor"); return; }
    const maxVal = Math.max(...arr.map((r) => r.value));
    const minVal = Math.min(...arr.map((r) => r.value));
    const baselineVal = arr.find((r) => r.condition === conditions[0])?.value ?? 0;
    const maxAbsLog2FC = Math.max(Math.abs(maxVal), Math.abs(minVal));
    const minQVal = ptmMinQValue.get(key);
    const hasQValue = minQVal != null;

    // Primary: use preprocessing imputation flag (most accurate for de novo)
    if (ptmPseudocountUsed.get(key)) {
      ptmActivityClass.set(key, "de_novo");
    } else if (hasQValue) {
      // q_value available: Regulated = |Log2FC| >= 1.0 AND q_value < 0.05
      if (maxAbsLog2FC >= 1.0 && minQVal < 0.05) {
        ptmActivityClass.set(key, "regulated");
      } else {
        ptmActivityClass.set(key, "minor");
      }
    } else {
      // Fallback (old data without q_value): use maxAbsChange > 0.8
      const maxAbsChange = Math.max(Math.abs(maxVal - baselineVal), Math.abs(minVal - baselineVal));
      if (maxAbsChange > 0.8) {
        ptmActivityClass.set(key, "regulated");
      } else {
        ptmActivityClass.set(key, "minor");
      }
    }
  });

  // Pass 2: if q_value data exists but yielded 0 regulated, re-classify with |FC| >= 0.8
  const _regulatedCount = Array.from(ptmActivityClass.values()).filter((v) => v === "regulated").length;
  if (_hasAnyQValue && _regulatedCount === 0) {
    uniquePtms.forEach((p) => {
      const key = `${p.gene}_${p.position}`;
      if (ptmActivityClass.get(key) === "de_novo") return; // keep de_novo
      const arr = vectorByPtm.get(key);
      if (!arr || !conditions.length) return;
      const maxAbsLog2FC = Math.max(...arr.map((r) => Math.abs(r.value)));
      if (maxAbsLog2FC >= 0.8) {
        ptmActivityClass.set(key, "regulated");
      } else {
        ptmActivityClass.set(key, "minor");
      }
    });
  }

  // Convert highlighted label set → gene_position key set (for KinaseModuleAnalysis button state)
  const highlightedPtmKeySet = (() => {
    if (highlightedModulePtmLabels.size === 0) return new Set<string>();
    const labelToKey = new Map(uniquePtms.map((p) => [p.label, `${p.gene}_${p.position}`]));
    const keys = new Set<string>();
    highlightedModulePtmLabels.forEach((lbl) => {
      const k = labelToKey.get(lbl);
      if (k) keys.add(k);
    });
    return keys;
  })();

  // Filter PTMs by trend category AND activity filter
  const filteredPtms = uniquePtms.filter((p) => {
    const key = `${p.gene}_${p.position}`;
    const trendOk = trendFilter === "all" || ptmTrends.get(key) === trendFilter;
    const actOk = activityFilter === "all" || ptmActivityClass.get(key) === activityFilter;
    return trendOk && actOk;
  });

  const chartData = conditions.map((cond) => {
    const point: Record<string, string | number> = { condition: cond };
    filteredPtms.forEach((p) => {
      const key = `${p.gene}_${p.position}`;
      if (!checked[key]) return;
      const arr = vectorByPtm.get(key);
      const row = arr?.find((r) => r.condition === cond);
      point[p.label] = row ? row.value : 0;
    });
    return point;
  });

  const visibleLabels = filteredPtms.filter((p) => checked[`${p.gene}_${p.position}`]).map((p) => p.label);

  // v9.28: Activity class-based color palettes
  const AC_PALETTES: Record<string, string[]> = {
    de_novo: ["#E65100", "#F57C00", "#FF9800", "#FFB74D", "#D84315", "#BF360C", "#EF6C00", "#FFA726", "#FB8C00", "#E55100"],
    regulated: ["#1565C0", "#1E88E5", "#42A5F5", "#64B5F6", "#0D47A1", "#1976D2", "#2196F3", "#90CAF9", "#0277BD", "#039BE5"],
    minor: ["#4CAF50", "#66BB6A", "#81C784", "#A5D6A7", "#2E7D32", "#388E3C", "#43A047", "#56985A", "#6DAF71", "#7BC67F"],
  };
  const AC_LINE_STYLE: Record<string, { strokeWidth: number; strokeDasharray?: string; opacity: number }> = {
    de_novo: { strokeWidth: 2.5, opacity: 1 },
    regulated: { strokeWidth: 2.2, opacity: 0.95 },
    minor: { strokeWidth: 1.8, opacity: 0.75 },
  };

  // Fixed color map: each PTM gets color based on its activity class
  const colorMap = new Map<string, string>();
  const _acIdx: Record<string, number> = { de_novo: 0, regulated: 0, minor: 0 };
  uniquePtms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    const ac = ptmActivityClass.get(key) || "minor";
    const palette = AC_PALETTES[ac] || AC_PALETTES.minor;
    colorMap.set(p.label, palette[_acIdx[ac] % palette.length]);
    _acIdx[ac]++;
  });

  // Map label to activity class for line style lookup
  const labelToAC = new Map<string, string>();
  uniquePtms.forEach((p) => {
    const key = `${p.gene}_${p.position}`;
    labelToAC.set(p.label, ptmActivityClass.get(key) || "minor");
  });

  const toggle = (key: string) => setChecked((c) => ({ ...c, [key]: !c[key] }));

  const allChecked = filteredPtms.every((p) => checked[`${p.gene}_${p.position}`]);
  const noneChecked = filteredPtms.every((p) => !checked[`${p.gene}_${p.position}`]);

  const toggleAll = () => {
    const newVal = !allChecked;
    setChecked((c) => {
      const next = { ...c };
      filteredPtms.forEach((p) => { next[`${p.gene}_${p.position}`] = newVal; });
      return next;
    });
  };

  // Compute Y-axis domain with padding and zoom
  const allValues = visibleLabels.flatMap((label) =>
    chartData.map((d) => (typeof d[label] === "number" ? (d[label] as number) : 0))
  );
  const yMin = allValues.length > 0 ? Math.min(...allValues) : -1;
  const yMax = allValues.length > 0 ? Math.max(...allValues) : 1;
  const yCenter = (yMin + yMax) / 2;
  const yHalfRange = Math.max((yMax - yMin) / 2, 0.5) * yZoom;
  const autoYMin = Math.floor(yCenter - yHalfRange - 1);
  const autoYMax = Math.ceil(yCenter + yHalfRange + 1);

  // Manual override takes priority if valid numbers are entered
  const parsedManualMin = yManualMin !== "" ? parseFloat(yManualMin) : NaN;
  const parsedManualMax = yManualMax !== "" ? parseFloat(yManualMax) : NaN;
  const yDomainMin = !isNaN(parsedManualMin) ? parsedManualMin : autoYMin;
  const yDomainMax = !isNaN(parsedManualMax) ? parsedManualMax : autoYMax;

  // Count per trend category
  const trendCounts: Record<string, number> = { all: uniquePtms.length };
  uniquePtms.forEach((p) => {
    const t = ptmTrends.get(`${p.gene}_${p.position}`) || "other";
    trendCounts[t] = (trendCounts[t] || 0) + 1;
  });

  // v9.23: Count per activity class
  const activityCounts: Record<string, number> = { all: uniquePtms.length, de_novo: 0, regulated: 0, minor: 0 };
  uniquePtms.forEach((p) => {
    const a = ptmActivityClass.get(`${p.gene}_${p.position}`) || "minor";
    activityCounts[a] = (activityCounts[a] || 0) + 1;
  });

  // Chart height scales with visible lines for better separation (30% taller than before)
  const chartHeight = Math.max(650, Math.min(1040, 520 + visibleLabels.length * 10));

  return (
    <div className="space-y-4">
      {/* Info badges: source, suggested N */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={`px-2 py-0.5 rounded-full font-medium ${data.source === "enriched" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
          {data.source === "enriched" ? "Source: Enriched (RAG)" : "Source: Preprocessing (TSV)"}
        </span>
        <span className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
          Top N setting: {data.top_n_setting ?? "?"} / condition
        </span>
        <span className="px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 font-medium">
          {isUbi ? "Unique Sites" : "Unique PTMs"}: {uniquePtms.length}
        </span>
        {data.suggested_n != null && (
          <span className="px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 font-medium">
            Suggested N: {data.suggested_n} (|Log2FC| &gt; mean+2σ)
          </span>
        )}
      </div>

      {/* Metric toggle + Trend filter */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-2">
          <Button
            variant={metric === "relative" ? "default" : "outline"}
            size="sm"
            onClick={() => setMetric("relative")}
          >
            {isUbi ? "Ubi Site Relative Log2FC" : "PTM Relative Log2FC"}
          </Button>
          <Button
            variant={metric === "absolute" ? "default" : "outline"}
            size="sm"
            onClick={() => setMetric("absolute")}
          >
            {isUbi ? "Ubi Site Absolute Log2FC" : "PTM Absolute Log2FC"}
          </Button>
        </div>
        <Separator orientation="vertical" className="h-6" />
        <div className="flex flex-wrap gap-1.5">
          <Button
            variant={trendFilter === "all" ? "default" : "outline"}
            size="sm"
            className="text-xs h-7 px-2"
            onClick={() => setTrendFilter("all")}
          >
            All ({trendCounts["all"] || 0})
          </Button>
          {(Object.keys(TREND_META) as TrendCategory[]).map((cat) => (
            <Button
              key={cat}
              variant={trendFilter === cat ? "default" : "outline"}
              size="sm"
              className="text-xs h-7 px-2"
              style={trendFilter === cat ? { backgroundColor: TREND_META[cat].color, borderColor: TREND_META[cat].color } : {}}
              onClick={() => setTrendFilter(cat)}
              title={TREND_META[cat].description}
            >
              {TREND_META[cat].label} ({trendCounts[cat] || 0})
            </Button>
          ))}
        </div>
        <Separator orientation="vertical" className="h-6" />
        {/* v9.23: Activity filter (De novo / Regulated / Minor) */}
        <div className="flex flex-wrap gap-1.5 items-center">
          <span className="text-[10px] text-muted-foreground font-medium mr-0.5">Activity:</span>
          <Button
            variant={activityFilter === "all" ? "default" : "outline"}
            size="sm"
            className="text-xs h-7 px-2"
            onClick={() => setActivityFilter("all")}
          >
            All ({activityCounts.all})
          </Button>
          <Button
            variant={activityFilter === "de_novo" ? "default" : "outline"}
            size="sm"
            className="text-xs h-7 px-2"
            style={activityFilter === "de_novo" ? { backgroundColor: "#E65100", borderColor: "#E65100" } : {}}
            onClick={() => setActivityFilter("de_novo")}
            title="Not detected in control (imputed with pseudocount) — may inflate Log2FC"
          >
            ★ De novo ({activityCounts.de_novo})
          </Button>
          <Button
            variant={activityFilter === "regulated" ? "default" : "outline"}
            size="sm"
            className="text-xs h-7 px-2"
            style={activityFilter === "regulated" ? { backgroundColor: "#1565C0", borderColor: "#1565C0" } : {}}
            onClick={() => setActivityFilter("regulated")}
            title="Detected in control, |Log2FC| \u2265 1.0 AND q-value < 0.05 (Welch's t-test + BH correction)"
          >
            ● Regulated ({activityCounts.regulated})
          </Button>
          <Button
            variant={activityFilter === "minor" ? "default" : "outline"}
            size="sm"
            className="text-xs h-7 px-2"
            style={activityFilter === "minor" ? { backgroundColor: "#2E7D32", borderColor: "#2E7D32" } : {}}
            onClick={() => setActivityFilter("minor")}
            title="Small change — low significance"
          >
            Minor ({activityCounts.minor})
          </Button>
        </div>
        <div className="ml-auto">
          <Button
            variant="outline"
            size="sm"
            className="text-xs h-7 px-2 gap-1.5"
            onClick={() => setSidebarOpen((v) => !v)}
          >
            {sidebarOpen ? <><ChevronRight className="h-3 w-3" /> Hide PTM List</> : <><ChevronLeft className="h-3 w-3" /> Show PTM List</>}
          </Button>
        </div>
      </div>

      <div className={`grid gap-4 ${sidebarOpen ? "lg:grid-cols-[1fr_240px]" : ""}`}>
        {/* Chart area — taller Y axis with zoom controls */}
        <div className="rounded-lg border bg-background p-4 relative" style={{ minHeight: `${chartHeight + 40}px` }}>
          {/* Y-axis zoom controls + manual min/max */}
          <div className="absolute top-2 right-2 flex flex-col gap-1.5 z-10">
            <Button
              variant="outline"
              size="sm"
              className="h-7 w-7 p-0"
              title="Y축 확대 (좁히기)"
              onClick={() => { setYManualMin(""); setYManualMax(""); setYZoom((z) => Math.max(0.2, z * 0.7)); }}
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 w-7 p-0"
              title="Y축 축소 (넓히기)"
              onClick={() => { setYManualMin(""); setYManualMax(""); setYZoom((z) => Math.min(5, z * 1.4)); }}
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </Button>
            <div className="flex flex-col gap-1 mt-1 bg-background/90 rounded border p-1.5" style={{ width: "72px" }}>
              <label className="text-[10px] text-muted-foreground leading-none">Y Max</label>
              <Input
                type="number"
                placeholder={String(Math.round(autoYMax))}
                value={yManualMax}
                onChange={(e) => setYManualMax(e.target.value)}
                className="h-6 text-xs px-1.5 w-full"
              />
              <label className="text-[10px] text-muted-foreground leading-none mt-0.5">Y Min</label>
              <Input
                type="number"
                placeholder={String(Math.round(autoYMin))}
                value={yManualMin}
                onChange={(e) => setYManualMin(e.target.value)}
                className="h-6 text-xs px-1.5 w-full"
              />
            </div>
          </div>
          <ResponsiveContainer width="100%" height={chartHeight}>
            <LineChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="condition" stroke="hsl(var(--muted-foreground))" fontSize={12} />
              <YAxis
                stroke="hsl(var(--muted-foreground))"
                fontSize={12}
                domain={[yDomainMin, yDomainMax]}
                tickCount={Math.max(8, Math.round((yDomainMax - yDomainMin) / 2))}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload || payload.length === 0) return null;
                  // Show only the hovered PTM, or if no specific hover, show the one closest to cursor
                  const target = hoveredPtm
                    ? payload.find((p) => p.name === hoveredPtm) || payload[0]
                    : payload[0];
                  if (!target) return null;
                  const ptmColor = colorMap.get(target.name as string) || target.color;
                  return (
                    <div style={{
                      backgroundColor: "hsl(var(--card))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "6px",
                      padding: "8px 12px",
                      fontSize: "13px",
                      boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
                    }}>
                      <p style={{ margin: 0, fontWeight: 600, marginBottom: 4 }}>Time: {label}</p>
                      <p style={{ margin: 0, color: typeof ptmColor === "string" ? ptmColor : undefined }}>
                        {target.name}: {typeof target.value === "number" ? target.value.toFixed(3) : target.value}
                      </p>
                    </div>
                  );
                }}
              />
              {/* No <Legend /> — labels shown only on hover */}
              {/* v9.28: Render lines in draw order: minor first (background), then regulated, then de_novo (foreground) */}
              {/* Also supports module highlight from Co-wave */}
              {["minor", "regulated", "de_novo"].flatMap((drawClass) =>
                visibleLabels
                  .filter((label) => (labelToAC.get(label) || "minor") === drawClass)
                  .map((label) => {
                    const lineColor = colorMap.get(label) || "#4CAF50";
                    const ac = labelToAC.get(label) || "minor";
                    const style = AC_LINE_STYLE[ac] || AC_LINE_STYLE.minor;
                    const isHovered = hoveredPtm === label;
                    const isModuleHighlighted = highlightedModulePtmLabels.size > 0;
                    const inModule = highlightedModulePtmLabels.has(label);
                    // Priority: hover > module highlight > activity class default
                    const baseWidth = isHovered
                      ? style.strokeWidth + 2
                      : inModule && isModuleHighlighted
                        ? 3.5
                        : style.strokeWidth;
                    const baseOpacity = hoveredPtm
                      ? isHovered ? 1 : 0.15
                      : isModuleHighlighted
                        ? inModule ? 1 : 0.12
                        : style.opacity;
                    const dotR = inModule && isModuleHighlighted ? 4 : 3;
                    return (
                      <Line
                        key={label}
                        type="monotone"
                        dataKey={label}
                        stroke={lineColor}
                        strokeWidth={baseWidth}
                        strokeDasharray={style.strokeDasharray}
                        dot={{ r: dotR, fill: lineColor }}
                        activeDot={{
                          r: 7,
                          fill: lineColor,
                          onMouseEnter: () => setHoveredPtm(label),
                          onMouseLeave: () => setHoveredPtm(null),
                        }}
                        name={label}
                        opacity={baseOpacity}
                        onMouseEnter={() => setHoveredPtm(label)}
                        onMouseLeave={() => setHoveredPtm(null)}
                      />
                    );
                  })
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Right sidebar — PTM checklist with Select All / Deselect All */}
        {sidebarOpen && <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            {isUbi ? "Top N Ubi Sites" : "Top N PTMs"} ({filteredPtms.length})
          </p>
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              className="text-xs h-6 px-2 flex-1"
              onClick={toggleAll}
            >
              {allChecked ? "Deselect All" : "Select All"}
            </Button>
          </div>
          {/* ── Badge Legend ── */}
          <details className="rounded border border-border/50 text-xs">
            <summary className="cursor-pointer px-2 py-1.5 text-muted-foreground hover:text-foreground select-none flex items-center gap-1.5 font-medium">
              <span className="text-[9px] transition-transform">&#9654;</span> Badge Legend
            </summary>
            <div className="px-2 pb-2 pt-1 grid grid-cols-1 gap-y-1">
              {(isUbi ? [
                { role: "E3 ligase",          short: "E3",     desc: "E3 Ubiquitin Ligase" },
                { role: "DUB",               short: "DUB",    desc: "Deubiquitinase" },
                { role: "RTK",               short: "RTK",    desc: "Receptor Tyrosine Kinase" },
                { role: "Receptor",          short: "Rec",    desc: "Cell-surface Receptor" },
                { role: "Kinase",            short: "Kin",    desc: "Protein Kinase" },
                { role: "TF",                short: "TF",     desc: "Transcription Factor" },
                { role: "Autophagy receptor",short: "Atg-R",  desc: "Autophagy Receptor" },
                { role: "Chaperone",         short: "Chap",   desc: "Chaperone / HSP" },
                { role: "Cytoskeletal",      short: "Cyto",   desc: "Cytoskeletal Protein" },
                { role: "Nuclear",           short: "Nuc",    desc: "Nuclear / Nucleolar Protein" },
                { role: "Membrane protein",  short: "Mem",    desc: "Membrane Protein" },
              ] : [
                { role: "RTK",               short: "RTK",    desc: "Receptor Tyrosine Kinase" },
                { role: "Receptor",          short: "Rec",    desc: "Cell-surface Receptor" },
                { role: "Kinase",            short: "Kin",    desc: "Protein Kinase" },
                { role: "TF",                short: "TF",     desc: "Transcription Factor" },
                { role: "Phosphatase",       short: "PPase",  desc: "Protein Phosphatase" },
                { role: "Adaptor",           short: "Adpt",   desc: "Adaptor / Scaffold" },
                { role: "Chaperone",         short: "Chap",   desc: "Chaperone / HSP" },
                { role: "Cytoskeletal",      short: "Cyto",   desc: "Cytoskeletal Protein" },
                { role: "Nuclear",           short: "Nuc",    desc: "Nuclear / Nucleolar Protein" },
                { role: "Membrane protein",  short: "Mem",    desc: "Membrane Protein" },
              ]).map(({ role, short, desc }) => {
                const style = ROLE_COLORS[role] || { bg: "bg-zinc-500/15", text: "text-zinc-400", border: "border-zinc-500/30" };
                return (
                  <div key={role} className="flex items-center gap-2">
                    <span className={`inline-flex items-center px-1.5 py-0 rounded text-[10px] font-semibold leading-4 border flex-shrink-0 w-10 justify-center ${style.bg} ${style.text} ${style.border}`}>
                      {short}
                    </span>
                    <span className="text-muted-foreground">{desc}</span>
                  </div>
                );
              })}
            </div>
          </details>
          <div className="max-h-[calc(100vh-400px)] min-h-[300px] overflow-y-auto space-y-0.5 rounded border p-2">
            {filteredPtms.map((p) => {
              const key = `${p.gene}_${p.position}`;
              const trend = ptmTrends.get(key) || "other";
              const actCls = ptmActivityClass.get(key) || "minor";
              const pc = p.protein_class;
              return (
                <label
                  key={key}
                  className="flex items-center gap-1.5 cursor-pointer hover:bg-muted/50 rounded px-2 py-1 text-sm"
                >
                  <input
                    type="checkbox"
                    checked={!!checked[key]}
                    onChange={() => toggle(key)}
                    className="rounded flex-shrink-0"
                  />
                  <span
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0 border"
                    style={{ backgroundColor: colorMap.get(p.label) || "#6b7280", borderColor: TREND_META[trend].color }}
                    title={`${TREND_META[trend].label}: ${TREND_META[trend].description}`}
                  />
                  {/* v9.23: activity class indicator */}
                  {actCls === "de_novo" && <span className="text-[8px] flex-shrink-0" style={{ color: "#E65100" }} title="De novo (not detected in control, imputed)">★</span>}
                  {actCls === "regulated" && <span className="text-[8px] flex-shrink-0" style={{ color: "#1565C0" }} title="Regulated (q<0.05, |Log2FC|≥1.0)">●</span>}
                  <span className="truncate flex-1 min-w-0" title={pc ? `${p.label} \u2014 ${pc.role}${pc.ubi_context ? ` (${pc.ubi_context})` : ''} [${pc.confidence}] | ${actCls}` : `${p.label} (${TREND_META[trend].label}) | ${actCls}`}>
                    {p.label}
                  </span>
                  {pc && pc.role !== "Other" && (
                    <RoleBadge role={pc.role} ubiContext={pc.ubi_context} confidence={pc.confidence} isUbi={isUbi} />
                  )}
                </label>
              );
            })}
            {filteredPtms.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">
                {isUbi ? "No Ubi sites match the current filters." : "No PTMs match the current filters."}
              </p>
            )}
          </div>
        </div>}
      </div>

      {/* ── v9.18: Inferred Upstream Receptors Panel ── */}
      {(data.inferred_receptors ?? []).length > 0 && (() => {
        const receptors = data.inferred_receptors!;
        // color map per receptor class
        const classColor: Record<string, { bg: string; text: string; border: string }> = {
          RTK:             { bg: "bg-rose-500/15",    text: "text-rose-400",    border: "border-rose-500/30" },
          GPCR:            { bg: "bg-violet-500/15",  text: "text-violet-400",  border: "border-violet-500/30" },
          Integrin:        { bg: "bg-cyan-500/15",    text: "text-cyan-300",    border: "border-cyan-500/30" },
          Developmental:   { bg: "bg-emerald-500/15", text: "text-emerald-400", border: "border-emerald-500/30" },
          "Cytokine/Immune": { bg: "bg-amber-500/15", text: "text-amber-400",   border: "border-amber-500/30" },
          Immune:          { bg: "bg-amber-500/15",   text: "text-amber-400",   border: "border-amber-500/30" },
          Cytokine:        { bg: "bg-yellow-500/15",  text: "text-yellow-400",  border: "border-yellow-500/30" },
          "TGFβ":          { bg: "bg-orange-500/15",  text: "text-orange-400",  border: "border-orange-500/30" },
          "Nuclear Receptor": { bg: "bg-fuchsia-500/15", text: "text-fuchsia-400", border: "border-fuchsia-500/30" },
          "Ion Channel":   { bg: "bg-teal-500/15",    text: "text-teal-400",    border: "border-teal-500/30" },
          Receptor:        { bg: "bg-slate-500/15",   text: "text-slate-400",   border: "border-slate-500/30" },
        };
        // Unified scaling: all receptors normalized against the global max PTM count
        const globalMax = Math.max(...receptors.map(r => r.downstream_ptm_count), 1);
        const getBarPct = (rec: typeof receptors[0]) => {
          return Math.max(Math.round((rec.downstream_ptm_count / globalMax) * 100), 5);
        };
        return (
          <div className="mt-4 rounded-lg border border-border/60 bg-card/50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-sm font-semibold">Inferred Upstream Receptors</span>
              <span className="text-xs text-muted-foreground">(from Reactome pathway mapping + literature)</span>
              <button
                onClick={refreshReceptorInference}
                disabled={refreshingReceptors}
                className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-sky-600 hover:bg-sky-500 text-white transition-colors disabled:opacity-50 shadow-sm"
                title="Re-calculate receptor inference with latest data (ignores cache)"
              >
                <svg className={`h-4 w-4 ${refreshingReceptors ? 'animate-spin' : ''}`} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg>
                {refreshingReceptors ? 'Refreshing...' : 'Refresh Inference'}
              </button>
            </div>
            <div className="space-y-2.5">
              {receptors.map((rec) => {
                const style = classColor[rec.receptor_class] || classColor["Receptor"];
                const barPct = getBarPct(rec);
                const viaKinases = (rec as any).via_kinases as string[] | undefined;
                const pathway = (rec as any).pathway as string | undefined;
                const sigPathway = (rec as any).signaling_pathway as string | undefined;
                const source = (rec as any).source as string | undefined;
                const tooltipParts: string[] = [];
                if (viaKinases?.length) tooltipParts.push(`via: ${viaKinases.join(", ")}`);
                if (sigPathway) tooltipParts.push(`pathway: ${sigPathway}`);
                if (rec.downstream_ptms?.length) tooltipParts.push(`PTMs: ${rec.downstream_ptms.join(", ")}`);
                const tooltip = tooltipParts.join("\n");
                return (
                  <div key={rec.name} className="group">
                    <div className="flex items-center gap-3">
                      {/* Class badge */}
                      <span className={`inline-flex items-center px-1.5 py-0 rounded text-[10px] font-semibold leading-4 border flex-shrink-0 w-16 justify-center ${style.bg} ${style.text} ${style.border}`}>
                        {rec.receptor_class}
                      </span>
                      {/* Receptor name */}
                      <span
                        className="text-sm font-medium min-w-[180px] max-w-[260px] flex-shrink-0 cursor-help"
                        style={{ wordBreak: "break-word", lineHeight: "1.3" }}
                        title={tooltip}
                      >
                        {rec.name}
                      </span>
                      {/* Bar */}
                      <div className="flex-1 h-2 rounded-full bg-muted/30 overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{
                            width: `${barPct}%`,
                            backgroundColor:
                              source === "treatment_context" || source === "treatment_context_uniprot"
                                ? "#38bdf8"   /* sky-400 — bright & unmistakable */
                                : source === "reactome"
                                  ? "#fb7185" /* rose-400 */
                                  : "#a78bfa", /* violet-400 */
                          }}
                        />
                      </div>
                      {/* Count */}
                      <span className="text-xs text-muted-foreground w-16 text-right flex-shrink-0">
                        {rec.downstream_ptm_count} PTM{rec.downstream_ptm_count !== 1 ? "s" : ""}
                      </span>
                      {/* Confidence score */}
                      {(rec as any).confidence_score != null && (
                        <span
                          className={`text-[10px] font-mono flex-shrink-0 w-10 text-right ${
                            (rec as any).confidence_score >= 0.6
                              ? "text-emerald-400"
                              : (rec as any).confidence_score >= 0.4
                                ? "text-yellow-400"
                                : "text-muted-foreground"
                          }`}
                          title={`Confidence: ${((rec as any).confidence_score * 100).toFixed(0)}% (cowave=${((rec as any).cowave_score || 0).toFixed(1)}, convergence=${((rec as any).via_kinases || []).length} kinases, source=${source})`}
                        >
                          {((rec as any).confidence_score * 100).toFixed(0)}%
                        </span>
                      )}
                      {/* Source indicator */}
                      {source === "reactome" && (
                        <span className="text-[9px] text-emerald-500/70 flex-shrink-0" title="Mapped via Reactome pathway database">
                          R
                        </span>
                      )}
                      {source === "treatment_context" && (
                        <span className="text-[9px] text-sky-400/70 flex-shrink-0" title="Known receptor for treatment ligand (from experimental context)">
                          T
                        </span>
                      )}
                      {source === "treatment_context_uniprot" && (
                        <span className="text-[9px] text-sky-300/70 flex-shrink-0" title="UniProt receptor for treatment ligand">
                          Tu
                        </span>
                      )}
                      {source === "curated_kinase_receptor_db" && (
                        <span className="text-[9px] text-purple-400/70 flex-shrink-0" title="Curated kinase-receptor database">
                          C
                        </span>
                      )}
                      {source === "e3_ligase_db" && (
                        <span className="text-[9px] text-orange-400/70 flex-shrink-0" title="E3 ligase receptor database">
                          E3
                        </span>
                      )}
                      {source === "literature" && (
                        <span className="text-[9px] text-amber-400/70 flex-shrink-0" title="Extracted from literature annotations">
                          L
                        </span>
                      )}
                    </div>
                    {/* Expanded detail on hover — via kinases + pathway */}
                    {(viaKinases?.length || pathway || (rec as any).matched_ligand || (rec as any).evidence) && (
                      <div className="hidden group-hover:flex items-center gap-1.5 ml-[76px] mt-0.5">
                        {viaKinases?.length ? (
                          <span className="text-[10px] text-muted-foreground flex items-center gap-1 flex-wrap">
                            via{" "}
                            {viaKinases.map((k, ki) => (
                              <button
                                key={k}
                                onClick={() => setSelectedHighlightKinase(prev => prev === k ? null : k)}
                                className={`px-1 py-0 rounded text-[10px] border transition-colors ${
                                  selectedHighlightKinase === k
                                    ? "bg-yellow-200 dark:bg-yellow-700/60 text-yellow-900 dark:text-yellow-100 border-yellow-400"
                                    : "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 border-amber-400 hover:bg-amber-100 dark:hover:bg-amber-800/30"
                                }`}
                                title={`Click to highlight ${k} in Cascade View timeline`}
                              >
                                {ki > 0 && <span className="mr-0.5 opacity-50">→</span>}{k}
                              </button>
                            ))}
                          </span>
                        ) : null}
                        {sigPathway ? (
                          <span className="text-[10px] text-blue-400/60 ml-1">
                            ({sigPathway})
                          </span>
                        ) : null}
                        {(rec as any).matched_ligand ? (
                          <span className="text-[10px] text-sky-400/60">
                            ligand: {(rec as any).matched_ligand}
                          </span>
                        ) : null}
                        {(rec as any).pathway && !sigPathway ? (
                          <span className="text-[10px] text-blue-400/60 ml-1">
                            ({(rec as any).pathway})
                          </span>
                        ) : null}
                        {(rec as any).evidence ? (
                          <span className="text-[10px] text-muted-foreground/50 ml-1">
                            [{(rec as any).evidence}]
                          </span>
                        ) : null}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <p className="text-[10px] text-muted-foreground mt-2">
              Filtered by confidence score (convergence + temporal consistency + source reliability).
              <span className="text-emerald-400 ml-1">Green %</span> = high confidence
              <span className="text-yellow-400 ml-1">Yellow %</span> = moderate
              <span className="text-muted-foreground ml-1">Gray %</span> = lower.
              <span className="text-sky-400/70 ml-1">T</span> = Treatment
              <span className="text-emerald-500/70 ml-1">R</span> = Reactome
              <span className="text-purple-400/70 ml-1">C</span> = Curated DB
              <span className="text-orange-400/70 ml-1">E3</span> = E3 ligase
              <span className="text-amber-400/70 ml-1">L</span> = Literature.
            </p>
          </div>
        );
      })()}

      {/* ── Multi-site Temporal Divergence Panel ── */}
      {conditions.length >= 3 && (
        <MultiSiteDivergencePanel
          uniquePtms={uniquePtms}
          vectorByPtm={vectorByPtm}
          conditions={conditions}
          ptmActivityClass={ptmActivityClass}
          ptmPseudocountUsed={ptmPseudocountUsed}
          canonicalPairs={data.divergence_pairs || []}
          onHighlightPtms={(labels) => {
            setHighlightedModulePtmLabels((prev) => {
              const same = prev.size === labels.length && labels.every((l) => prev.has(l));
              return same ? new Set() : new Set(labels);
            });
          }}
        />
      )}

      {/* ── Kinase / E3 Ligase Module Analysis Panel ── */}
      {conditions.length >= 3 && (
        <KinaseModuleAnalysis
          orderId={orderId}
          ptmType={ptmType}
          highlightedKinase={selectedHighlightKinase}
          inferredReceptors={data.inferred_receptors || []}
          ipOverlayData={ipOverlayData}
          vectorData={data.vector_data.map((row) => ({
            gene: row.gene,
            position: row.position,
            condition: row.condition,
            value: row[valueKey as keyof typeof row] as number,
            control_pseudocount_used: row.control_pseudocount_used,
            q_value: row.q_value,
          }))}
          topNPtms={uniquePtms}
          checkedPtms={checked}
          conditions={conditions}
          highlightedPtmKeys={highlightedPtmKeySet}
          onSelectPtms={(keys) => {
            // Convert PTM keys (gene_position) → labels for chart highlight
            const keySet = new Set(keys);
            const labels = uniquePtms
              .filter((p) => keySet.has(`${p.gene}_${p.position}`))
              .map((p) => p.label);
            setHighlightedModulePtmLabels((prev) => {
              // Toggle: if same set already highlighted, clear
              const same = prev.size === labels.length && labels.every((l) => prev.has(l));
              return same ? new Set() : new Set(labels);
            });
          }}
        />
      )}
    </div>
  );
}

function VectorPlotTab({ orderId, singleTimePoint, ptmType = "phosphorylation" }: { orderId: number; singleTimePoint?: boolean; ptmType?: string }) {
  const isUbi = ptmType.toLowerCase().includes("ubiquityl") || ptmType.toLowerCase().includes("ubiquitin");
  const [files, setFiles] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<{ files: string[] }>(`/orders/${orderId}/vector-plots`)
      .then((d) => setFiles(d.files || []))
      .catch(() => setFiles([]))
      .finally(() => setLoading(false));
  }, [orderId]);

  if (loading) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">Loading vector plots...</p>
        </CardContent>
      </Card>
    );
  }

  const handleDownload = (filename: string) =>
    api.downloadFile(`/orders/${orderId}/files/${encodeURIComponent(filename)}`, filename);

  return (
    <div className="space-y-6">
      <Tabs defaultValue="scatter">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="scatter" className="gap-2">
            <ChartScatter className="h-3.5 w-3.5" /> Scatter Plots
          </TabsTrigger>
          <TabsTrigger
            value="timeseries"
            className="gap-2"
            disabled={singleTimePoint}
            title={singleTimePoint ? "Single time point — time-series not available" : undefined}
          >
            <TrendingUp className="h-3.5 w-3.5" /> {isUbi ? "Top N Ubi Site Time-series" : "Top N PTM Time-series"}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="scatter" className="mt-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <ChartScatter className="h-4 w-4" /> PTM Vector 2D Plots
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                Protein Log2FC vs PTM Relative/Absolute Log2FC. Hover over dots to see sample names. Use Zoom In/Out to adjust view.
              </p>
            </CardHeader>
            <CardContent>
              <ScatterPlotsInteractive orderId={orderId} />
              {files.length > 0 && (
                <div className="mt-6 pt-4 border-t">
                  <p className="text-xs text-muted-foreground mb-2">Download static report (PNG)</p>
                  <div className="flex flex-wrap gap-2">
                    {files.map((f) => (
                      <button
                        key={f}
                        onClick={() => handleDownload(f)}
                        className="text-xs text-primary hover:underline flex items-center gap-1"
                      >
                        <Download className="h-3 w-3" /> {f}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="timeseries" className="mt-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <TrendingUp className="h-4 w-4" /> {isUbi ? "Top N Ubiquitylation Site Time-series" : "Top N PTM Time-series"}
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                {isUbi
                  ? "시간별 Ubiquitylation site 변화 추이. 마우스를 올리면 site명과 값을 확인할 수 있습니다."
                  : "시간별 PTM 변화 추이. 마우스를 올리면 PTM명과 값을 확인할 수 있습니다."}
              </p>
            </CardHeader>
            <CardContent>
              <TopNTimeSeriesPlot orderId={orderId} ptmType={ptmType} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── Research Questions Panel ─────────────────────────────────────────────────

interface AiQuestion {
  question: string;
  category: string;
  confidence: number;
  rationale: string;
  included: boolean;
  source: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  temporal_pathway: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  pathway_crosstalk: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300",
  kinase_phosphatase: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  adaptation_mechanism: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  network: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300",
  novelty: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300",
  ecm_context: "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300",
};

function ResearchQuestionsPanel({
  orderId,
  orderStatus,
  reportOptions,
  isRunning,
  onRunReport,
}: {
  orderId: number;
  orderStatus: string;
  reportOptions: any;
  isRunning: boolean;
  onRunReport: () => void;
}) {
  const [aiQuestions, setAiQuestions] = useState<AiQuestion[]>([]);
  const [manualQuestions, setManualQuestions] = useState<string[]>([]);
  const [newQuestion, setNewQuestion] = useState("");
  const [generating, setGenerating] = useState(false);
  const [polling, setPolling] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.get<{ research_questions: string[]; ai_questions: AiQuestion[] }>(
      `/orders/${orderId}/questions`,
    ).then((d) => {
      if (d.ai_questions?.length) setAiQuestions(d.ai_questions);
      const manual = (d.research_questions || []).filter(
        (q: string) => !d.ai_questions?.some((aq: AiQuestion) => aq.question === q),
      );
      if (manual.length) setManualQuestions(manual);
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, [orderId]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const res = await api.post<{ task_id: string }>(`/orders/${orderId}/generate-questions`, {});
      setPolling(true);
      const pollInterval = setInterval(async () => {
        try {
          const data = await api.get<{ research_questions: string[]; ai_questions: AiQuestion[] }>(
            `/orders/${orderId}/questions`,
          );
          if (data.ai_questions?.length) {
            setAiQuestions(data.ai_questions);
            setPolling(false);
            setGenerating(false);
            clearInterval(pollInterval);
          }
        } catch { /* keep polling */ }
      }, 3000);
      setTimeout(() => { clearInterval(pollInterval); setGenerating(false); setPolling(false); }, 120000);
    } catch {
      setGenerating(false);
    }
  };

  const toggleQuestion = (idx: number) => {
    setAiQuestions((prev) =>
      prev.map((q, i) => (i === idx ? { ...q, included: !q.included } : q)),
    );
  };

  const handleSaveAndRun = async () => {
    const included = aiQuestions.filter((q) => q.included).map((q) => q.question);
    const allQuestions = [...included, ...manualQuestions];
    try {
      await api.put(`/orders/${orderId}/questions`, {
        research_questions: allQuestions,
        ai_questions: aiQuestions,
      });
      onRunReport();
    } catch (err: any) {
      alert(err.message || "Failed to save questions");
    }
  };

  const canGenerate = ["completed", "failed"].includes(orderStatus) && !isRunning;
  const canRerun = canGenerate;
  const totalIncluded = aiQuestions.filter((q) => q.included).length + manualQuestions.length;

  if (!loaded) return null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <MessageSquare className="h-4 w-4" /> Research Questions
            {totalIncluded > 0 && (
              <Badge variant="secondary" className="text-[10px]">{totalIncluded} active</Badge>
            )}
          </CardTitle>
          <div className="flex gap-2">
            {canGenerate && (
              <Button
                variant="outline" size="sm" className="h-7 text-xs gap-1.5"
                onClick={handleGenerate}
                disabled={generating}
              >
                {generating ? (
                  <><Loader2 className="h-3 w-3 animate-spin" /> Generating...</>
                ) : (
                  <><Sparkles className="h-3 w-3" /> AI Generate</>
                )}
              </Button>
            )}
            {canRerun && totalIncluded > 0 && (
              <Button
                size="sm" className="h-7 text-xs gap-1.5"
                onClick={handleSaveAndRun}
              >
                <Play className="h-3 w-3" /> Re-run with Questions
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* AI Generated Questions */}
        {aiQuestions.length > 0 && (
          <div className="space-y-2">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              AI-Generated Questions
            </p>
            {aiQuestions.map((q, i) => (
              <div
                key={i}
                className={cn(
                  "flex items-start gap-2 rounded-lg border px-3 py-2 transition-all",
                  q.included ? "bg-background" : "bg-muted/30 opacity-60",
                )}
              >
                <button
                  onClick={() => toggleQuestion(i)}
                  className="mt-0.5 shrink-0"
                  title={q.included ? "Exclude" : "Include"}
                >
                  {q.included ? (
                    <ToggleRight className="h-4 w-4 text-primary" />
                  ) : (
                    <ToggleLeft className="h-4 w-4 text-muted-foreground" />
                  )}
                </button>
                <div className="flex-1 min-w-0 space-y-1">
                  <p className="text-sm leading-snug">{q.question}</p>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge className={cn("text-[9px] px-1.5 py-0", CATEGORY_COLORS[q.category] || "bg-muted text-muted-foreground")}>
                      {q.category.replace(/_/g, " ")}
                    </Badge>
                    <span className="text-[10px] text-muted-foreground">
                      confidence: {(q.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  {q.rationale && (
                    <p className="text-[10px] text-muted-foreground italic">{q.rationale}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Manual Questions */}
        <div className="space-y-2">
          {(manualQuestions.length > 0 || canGenerate) && (
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Custom Questions
            </p>
          )}
          {manualQuestions.map((q, i) => (
            <div key={i} className="flex items-start gap-2 group">
              <span className="text-xs text-muted-foreground mt-1.5 w-5 shrink-0">Q{i + 1}</span>
              <div className="flex-1 rounded-lg border px-3 py-2 text-sm bg-background">{q}</div>
              <Button
                variant="ghost" size="icon" className="h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={() => setManualQuestions(manualQuestions.filter((_, j) => j !== i))}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
          {canGenerate && (
            <div className="flex gap-2 items-start">
              <AutoResizeTextarea
                value={newQuestion}
                onChange={(e) => setNewQuestion(e.target.value)}
                placeholder="Add a research question..."
                className="flex-1 min-w-0 text-sm"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && newQuestion.trim()) {
                    e.preventDefault();
                    setManualQuestions([...manualQuestions, newQuestion.trim()]);
                    setNewQuestion("");
                  }
                }}
              />
              <Button
                variant="outline" size="icon" className="h-8 w-8 shrink-0 mt-1"
                disabled={!newQuestion.trim()}
                onClick={() => {
                  if (newQuestion.trim()) {
                    setManualQuestions([...manualQuestions, newQuestion.trim()]);
                    setNewQuestion("");
                  }
                }}
              >
                <Plus className="h-3 w-3" />
              </Button>
            </div>
          )}
        </div>

        {aiQuestions.length === 0 && manualQuestions.length === 0 && !generating && (
          <div className="flex flex-col items-center py-4 gap-2">
            <Sparkles className="h-8 w-8 text-muted-foreground/30" />
            <p className="text-xs text-muted-foreground text-center">
              {canGenerate
                ? "RAG Enrichment 완료 후 AI로 질문을 자동 생성하거나 직접 입력할 수 있습니다."
                : "보고서 생성 시 AI가 자동으로 질문을 생성합니다."}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface LlmConfig {
  default_provider: string;
  default_model: string;
  ollama_url: string;
}

export default function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const orderId = parseInt(id || "0");
  const [order, setOrder] = useState<Order | null>(null);

  // read-only shared: hide all write actions
  const isReadOnlyShared = !!(order?.is_shared && order?.share_access === "read_only");
  const [logs, setLogs] = useState<OrderLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [llmModels, setLlmModels] = useState<{ provider: string; model_id: string; name: string }[]>([]);
  const [ragCollections, setRagCollections] = useState<{ id: number; name: string }[]>([]);
  const [rerunModalOpen, setRerunModalOpen] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("overview");
  const [duplicateModalOpen, setDuplicateModalOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<{ type: "start" } | { type: "run-stage"; stage: string } | null>(null);
  const runHandledRef = useRef(false);
  const [phaseModalOpen, setPhaseModalOpen] = useState(false);
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [prepModalOpen, setPrepModalOpen] = useState(false);
  const [stopInProgress, setStopInProgress] = useState(false);
  const [pptxGenerating, setPptxGenerating] = useState(false);
  /** PPTX Celery 진행 (폴링 + sessionStorage로 탭 이동 후에도 복원) */
  const [pptxProgressMeta, setPptxProgressMeta] = useState<{
    message: string;
    progress: number | null;
    stage?: string;
  } | null>(null);
  const [pptxLlm, setPptxLlm] = useState("");
  const stopRequestRef = useRef(false);
  const lastLogIdRef = useRef(0);

  const isRunning = !!order && !["completed", "failed", "registered", "cancelled"].includes(order.status);

  const { progress, events } = useOrderProgress(isRunning ? orderId : null);

  // Build per-PTM phase status from SSE events + DB logs (for stopped/completed orders)
  type PhaseStatus = "pending" | "running" | "done" | "skip" | "error";
  type StructuredSourceSummary = {
    key: string; label: string; status: string; count: number; unit: string;
  };
  type PtmPhaseRow = {
    gene: string; position: string;
    A: PhaseStatus; B: PhaseStatus; C: PhaseStatus; D: PhaseStatus;
    articleProgress: string; // "done/total" e.g. "5/15", or "" if unknown
    cachedCount: number;
    errorDetail: string;
    sourceSummary: StructuredSourceSummary[];
  };
  const { ptmPhaseMap, ptmTotal } = useMemo(() => {
    const map = new Map<string, PtmPhaseRow>();
    let total: number | null = null;

    const blank = (gene: string, position: string): PtmPhaseRow =>
      ({ gene, position, A: "pending", B: "pending", C: "pending", D: "pending", articleProgress: "", cachedCount: 0, errorDetail: "", sourceSummary: [] });

    const applyMeta = (meta: Record<string, unknown>) => {
      if (meta?.type === "ptm_list") {
        total = Number(meta.total ?? 0) || null;
        return;
      }
      if (meta?.type !== "ptm_phase") return;
      const gene = String(meta.gene ?? "");
      const position = String(meta.position ?? "");
      const phase = String(meta.phase ?? "") as "A" | "B" | "C" | "D";
      const status = String(meta.status ?? "pending") as PhaseStatus;
      const detail = String(meta.detail ?? "");
      const key = `${gene}__${position}`;

      // Phase A pending = 새 run 시작 신호 → 이전 run 데이터 완전 리셋
      if (phase === "A" && status === "pending") {
        map.set(key, blank(gene, position));
        return;
      }

      const existing = map.get(key) ?? blank(gene, position);
      const sourceSummary = phase === "A" && Array.isArray(meta.source_summary)
        ? meta.source_summary
            .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
            .map(item => ({
              key: String(item.key ?? ""),
              label: String(item.label ?? item.key ?? "DB"),
              status: String(item.status ?? "done"),
              count: Number(item.count ?? 0) || 0,
              unit: String(item.unit ?? "records"),
            }))
        : existing.sourceSummary;

      // Article progress:
      // - "3/15 articles" from per-article LLM callbacks
      // - "15 articles" from Phase B start (backend) — parse as total only
      // - "5/5 articles, 5 cached" from Phase B done with cache hits
      const artMatch = detail.match(/^(\d+)\/(\d+)\s*articles?(?:,\s*(\d+)\s*cached)?$/i);
      const totalOnlyMatch = detail.match(/^(\d+)\s*articles?$/i);
      let newArticleProgress = existing.articleProgress;
      let newCachedCount = existing.cachedCount;
      if (artMatch) {
        newArticleProgress = `${artMatch[1]}/${artMatch[2]}`;
        if (artMatch[3]) newCachedCount = Number(artMatch[3]);
      } else if (phase === "B" && totalOnlyMatch) {
        const t = totalOnlyMatch[1];
        if (status === "running") {
          newArticleProgress = `0/${t}`;
        } else if (status === "done" || status === "skip") {
          newArticleProgress = `${t}/${t}`;
        }
      } else if (phase === "B" && status === "done" && detail === "") {
        const partial = existing.articleProgress.match(/^0\/(\d+)$/);
        if (partial) newArticleProgress = `${partial[1]}/${partial[1]}`;
      }

      map.set(key, {
        ...existing,
        [phase]: status,
        articleProgress: newArticleProgress,
            cachedCount: newCachedCount,
            errorDetail: phase === "B" && status === "error" && detail ? detail : existing.errorDetail,
            sourceSummary,
      });
    };
    // DB logs first (historical), then SSE events override (real-time)
    for (const log of logs) {
      if (log.metadata?.type) applyMeta(log.metadata);
    }
    for (const ev of events) {
      if (ev.metadata?.type) applyMeta(ev.metadata as Record<string, unknown>);
    }
    return { ptmPhaseMap: map, ptmTotal: total };
  }, [logs, events]);

  type StepRow = { step: string; label: string; status: PhaseStatus; detail: string };

  const PREP_STEPS: { key: string; label: string }[] = [
    { key: "ptm_quantification", label: "PTM Quantification" },
    { key: "vector_report", label: "Vector Report" },
    { key: "unified_enrichment", label: "Domain/Motif Enrichment" },
    { key: "biological_enrichment", label: "Biological Enrichment" },
    { key: "finalization", label: "Finalization" },
  ];

  const REPORT_STEPS: { key: string; label: string }[] = [
    { key: "kinase_annotation", label: "Kinase Annotation" },
    { key: "context_loading", label: "Context Loading" },
    { key: "question_generation", label: "Question Generation" },
    { key: "research", label: "Research Analysis" },
    { key: "hypothesis", label: "Hypothesis Generation" },
    { key: "validation", label: "Hypothesis Validation" },
    { key: "network", label: "Network Analysis" },
    { key: "rq_refinement", label: "RQ Refinement" },
    { key: "writing", label: "Report Writing" },
    { key: "report_copilot", label: "Report Co-pilot" },
    { key: "qa_report", label: "Q&A Report" },
    { key: "compilation", label: "Final Compilation" },
  ];

  const prepStepRows = useMemo((): StepRow[] => {
    const resetAll = () => {
      for (const s of PREP_STEPS) map.set(s.key, { step: s.key, label: s.label, status: "pending", detail: "" });
    };
    const map = new Map<string, StepRow>();
    resetAll();

    const apply = (meta: Record<string, unknown>) => {
      if (meta?.type !== "preprocessing_phase") return;
      const step = String(meta.step ?? "");
      const status = String(meta.status ?? "");
      const detail = String(meta.detail ?? "");

      if (step === PREP_STEPS[0].key && status === "running") {
        resetAll();
      }

      const row = map.get(step);
      if (!row) return;
      if (status === "done") row.status = "done";
      else if (status === "running") row.status = "running";
      else if (status === "error") row.status = "error";
      row.detail = detail;
    };

    for (const log of logs) { if (log.metadata?.type) apply(log.metadata); }
    for (const ev of events) { if (ev.metadata?.type) apply(ev.metadata as Record<string, unknown>); }

    // Completed order past preprocessing: force all prep steps to "done"
    if (order && ["completed", "rag_enrichment", "report_generation"].includes(order.status)) {
      for (const row of map.values()) {
        if (row.status !== "done") row.status = "done";
      }
    }

    return Array.from(map.values());
  }, [logs, events, order?.status]);

  const reportStepRows = useMemo((): StepRow[] => {
    const resetAll = () => {
      for (const s of REPORT_STEPS) map.set(s.key, { step: s.key, label: s.label, status: "pending", detail: "" });
    };
    const map = new Map<string, StepRow>();
    resetAll();

    const apply = (meta: Record<string, unknown>) => {
      if (meta?.type !== "report_phase") return;
      const step = String(meta.step ?? "");
      const status = String(meta.status ?? "");
      const detail = String(meta.detail ?? "");

      // New run detected: first step starts running → reset all steps
      if ((step === "kinase_annotation" || step === "context_loading") && status === "running") {
        resetAll();
      }

      const row = map.get(step);
      if (!row) return;
      if (status === "done" || status === "skipped") row.status = "done";
      else if (status === "running") row.status = "running";
      else if (status === "error") row.status = "error";
      row.detail = detail;
    };

    for (const log of logs) { if (log.metadata?.type) apply(log.metadata); }
    for (const ev of events) { if (ev.metadata?.type) apply(ev.metadata as Record<string, unknown>); }

    // Completed order: force all steps to "done" (logs may be from an interrupted duplicate run)
    if (order?.status === "completed") {
      for (const row of map.values()) {
        if (row.status !== "done") row.status = "done";
      }
    }

    return Array.from(map.values());
  }, [logs, events, order?.status]);

  useEffect(() => {
    Promise.all([
      api.get<Order>(`/orders/${orderId}`),
      api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`),
      api.get<LlmConfig>("/system/llm-config"),
    ]).then(([o, l, lc]) => {
      setOrder(o);
      setLogs(l.logs);
      if (l.logs.length > 0) {
        lastLogIdRef.current = Math.max(...l.logs.map((x) => x.id));
      }
      setLlmConfig(lc);
      setLoading(false);
    }).catch(() => {
      setLoading(false);
    });
  }, [orderId]);
  useEffect(() => {
    api.get<{ models: { provider: string; model_id: string; name: string; is_active: boolean }[] }>("/llm/models").then((d) => {
      const fromApi = d.models.filter((m) => m.is_active).map((m) => ({ provider: m.provider, model_id: m.model_id, name: m.name }));
      const cloudProviders: { provider: string; model_id: string; name: string }[] = [
        { provider: "gemini", model_id: "__provider__", name: "Gemini" },
        { provider: "openai", model_id: "__provider__", name: "OpenAI" },
        { provider: "anthropic", model_id: "__provider__", name: "Anthropic" },
      ];
      const hasProvider = (p: string) => fromApi.some((m) => m.provider === p && m.model_id === "__provider__");
      const merged = [...fromApi];
      for (const cp of cloudProviders) {
        if (!hasProvider(cp.provider)) merged.push(cp);
      }
      setLlmModels(merged);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    if (llmModels.length === 0 || pptxLlm) return;
    const ro = order?.report_options as { llm_provider?: string; llm_model?: string } | undefined;
    const fromOrder =
      ro?.llm_provider && ro?.llm_model
        ? `${ro.llm_provider}:${ro.llm_model}`
        : "";
    if (fromOrder && llmModels.some((m) => `${m.provider}:${m.model_id}` === fromOrder)) {
      setPptxLlm(fromOrder);
      return;
    }
    const m0 = llmModels[0];
    setPptxLlm(`${m0.provider}:${m0.model_id}`);
  }, [llmModels, order?.report_options, pptxLlm]);
  useEffect(() => {
    api.get<{ collections: { id: number; name: string }[] }>("/rag/collections").then((d) => {
      setRagCollections(d.collections.map((c) => ({ id: c.id, name: c.name })));
    }).catch(() => setRagCollections([]));
  }, []);
  useEffect(() => {
    if (runHandledRef.current) return;
    if (searchParams.get("run") !== "1" || !order || !["registered", "failed", "completed"].includes(order.status)) return;

    runHandledRef.current = true;

    const url = new URL(window.location.href);
    url.searchParams.delete("run");
    window.history.replaceState({}, "", url.pathname + url.search);

    if (order.status === "registered") {
      api.post(`/orders/${orderId}/start`)
        .then(() => Promise.all([api.get<Order>(`/orders/${orderId}`), api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`)]))
        .then(([o, l]) => {
          setOrder(o);
          setLogs(l.logs);
        })
        .catch((err: any) => alert(err.message || "Failed to start"));
      return;
    }
    setPendingAction({ type: "start" });
    setRerunModalOpen(true);
  }, [searchParams, order, orderId]);

  const wasRunningRef = useRef(false);

  useEffect(() => {
    if (!isRunning) return;
    const interval = setInterval(async () => {
      try {
        const sinceId = lastLogIdRef.current;
        const [s, l] = await Promise.all([
          api.get<Pick<Order, "id" | "status" | "current_stage" | "progress_pct" | "stage_detail" | "error_message">>(`/orders/${orderId}/status`),
          api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs?since_id=${sinceId}`),
        ]);
        setOrder((prev) => prev ? { ...prev, ...s } : prev);
        if (l.logs.length > 0) {
          setLogs((prev) => {
            const merged = [...prev, ...l.logs];
            lastLogIdRef.current = Math.max(lastLogIdRef.current, ...l.logs.map((x) => x.id));
            return merged;
          });
        }
      } catch { /* ignore */ }
    }, 5000);
    return () => clearInterval(interval);
  }, [isRunning, orderId]);

  // When order transitions from running → completed/failed, do one final re-fetch
  useEffect(() => {
    if (wasRunningRef.current && !isRunning && order && ["completed", "failed"].includes(order.status)) {
      setTimeout(async () => {
        try {
          const [o, l] = await Promise.all([
            api.get<Order>(`/orders/${orderId}`),
            api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`),
          ]);
          setOrder(o);
          setLogs(l.logs);
        } catch { /* ignore */ }
      }, 1500);
    }
    wasRunningRef.current = isRunning;
  }, [isRunning]);

  useEffect(() => {
    if (progress && order) {
      setOrder((prev) =>
        prev
          ? {
              ...prev,
              progress_pct:
                progress.progress_pct != null &&
                !Number.isNaN(Number(progress.progress_pct))
                  ? Number(progress.progress_pct)
                  : prev.progress_pct,
              current_stage: progress.stage,
              stage_detail: progress.message,
              status: progress.status === "failed" ? "failed" : prev.status,
            }
          : prev,
      );
    }
  }, [progress]);

  const handleRefresh = async () => {
    const [o, l] = await Promise.all([
      api.get<Order>(`/orders/${orderId}`),
      api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`),
    ]);
    setOrder(o);
    setLogs(l.logs);
  };

  /** PPTX: poll Celery job (524 방지 — 작업은 워커에서 실행; 복귀 시 sessionStorage로 폴링 재개) */
  const pptxPollAbortRef = useRef<AbortController | null>(null);
  const runPptxPollRef = useRef<((taskId: string, signal?: AbortSignal) => Promise<void>) | null>(null);
  runPptxPollRef.current = async (taskId: string, signal?: AbortSignal) => {
    const key = `pptx-task-${orderId}`;
    const metaKey = `pptx-meta-${orderId}`;
    const deadline = Date.now() + 45 * 60 * 1000;
    const sleepAbortable = (ms: number) =>
      new Promise<void>((resolve) => {
        const id = window.setTimeout(resolve, ms);
        signal?.addEventListener(
          "abort",
          () => {
            window.clearTimeout(id);
            resolve();
          },
          { once: true },
        );
      });
    while (Date.now() < deadline) {
      if (signal?.aborted) return;
      const s = await api.get<{
        job_status: string;
        ready: boolean;
        filename?: string | null;
        error?: string;
        raw?: unknown;
        message?: string | null;
        progress?: number | null;
        stage?: string | null;
        celery_state?: string;
      }>(`/orders/${orderId}/generate-pptx/status/${taskId}`);
      if (s.job_status === "success" && s.ready) {
        sessionStorage.removeItem(key);
        sessionStorage.removeItem(metaKey);
        setPptxProgressMeta(null);
        if (s.filename) {
          await api.downloadFile(
            `/orders/${orderId}/files/${encodeURIComponent(s.filename)}`,
            s.filename,
          );
          await handleRefresh();
        } else {
          alert(
            s.raw != null
              ? `PPTX 결과가 비정상입니다: ${JSON.stringify(s.raw)}`
              : "PPTX 파일을 찾을 수 없습니다.",
          );
        }
        return;
      }
      if (s.job_status === "failure" && s.ready) {
        sessionStorage.removeItem(key);
        sessionStorage.removeItem(metaKey);
        setPptxProgressMeta(null);
        alert(s.error || "PPTX 생성에 실패했습니다.");
        return;
      }
      const msg =
        (typeof s.message === "string" && s.message.trim()
          ? s.message
          : s.celery_state === "PENDING"
            ? "Waiting for worker…"
            : "Generating PPTX…") ?? "Generating PPTX…";
      const pct = typeof s.progress === "number" ? s.progress : null;
      const next = {
        message: msg,
        progress: pct,
        stage: s.stage ?? undefined,
      };
      setPptxProgressMeta(next);
      try {
        sessionStorage.setItem(metaKey, JSON.stringify(next));
      } catch {
        /* ignore quota */
      }
      await sleepAbortable(2000);
    }
    if (signal?.aborted) return;
    sessionStorage.removeItem(key);
    sessionStorage.removeItem(metaKey);
    setPptxProgressMeta(null);
    alert("PPTX 생성 대기 시간이 초과되었습니다.");
  };

  useEffect(() => {
    const tid = sessionStorage.getItem(`pptx-task-${orderId}`);
    if (!tid || !runPptxPollRef.current) return;
    pptxPollAbortRef.current?.abort();
    const ac = new AbortController();
    pptxPollAbortRef.current = ac;
    setPptxGenerating(true);
    void runPptxPollRef.current(tid, ac.signal).finally(() => {
      if (!ac.signal.aborted) setPptxGenerating(false);
    });
    return () => {
      ac.abort();
    };
  }, [orderId]);

  /** 주문 진입 시 진행 중 PPTX 메타 복원 (다른 탭 갔다 와도 배너 즉시 표시) */
  useEffect(() => {
    const tid = sessionStorage.getItem(`pptx-task-${orderId}`);
    const raw = sessionStorage.getItem(`pptx-meta-${orderId}`);
    if (!tid) {
      setPptxProgressMeta(null);
      return;
    }
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as { message?: string; progress?: number | null; stage?: string };
        setPptxProgressMeta({
          message: parsed.message || "Generating PPTX…",
          progress: typeof parsed.progress === "number" ? parsed.progress : null,
          stage: parsed.stage,
        });
      } catch {
        setPptxProgressMeta({ message: "Generating PPTX…", progress: null });
      }
    } else {
      setPptxProgressMeta({ message: "Generating PPTX…", progress: null });
    }
  }, [orderId]);

  const openRerunModal = async (action: { type: "start" } | { type: "run-stage"; stage: string }) => {
    setPendingAction(action);
    try {
      const fresh = await api.get<Order>(`/orders/${orderId}`);
      setOrder(fresh);
    } catch { /* keep existing order */ }
    setRerunModalOpen(true);
  };

  const handleRerunConfirm = async (opts: {
    analysis_context: Record<string, unknown>;
    analysis_options: Record<string, unknown>;
    report_options: Record<string, unknown>;
    rag_collections?: number[] | null;
  }) => {
    if (!pendingAction) return;
    try {
      await api.patch(`/orders/${orderId}`, opts);
      const runningStatuses = ["queued", "preprocessing", "rag_enrichment", "report_generation"];
      if (order && runningStatuses.includes(order.status)) {
        await api.post(`/orders/${orderId}/cancel`);
        await new Promise((r) => setTimeout(r, 1500));
      }
      if (pendingAction.type === "run-stage") {
        await api.post(`/orders/${orderId}/run-stage`, { stage: pendingAction.stage });
      } else {
        await api.post(`/orders/${orderId}/start`);
      }
      const [o, l] = await Promise.all([
        api.get<Order>(`/orders/${orderId}`),
        api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`),
      ]);
      setOrder(o);
      setLogs(l.logs);
      setPendingAction(null);
    } catch (err: any) {
      alert(err.message || "Failed to run");
      throw err;
    }
  };

  const handleStart = async () => {
    if (order?.status === "registered") {
      try {
        await api.post(`/orders/${orderId}/start`);
        const [o, l] = await Promise.all([
          api.get<Order>(`/orders/${orderId}`),
          api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`),
        ]);
        setOrder(o);
        setLogs(l.logs);
      } catch (err: any) {
        alert(err.message || "Failed to start");
      }
    } else {
      openRerunModal({ type: "start" });
    }
  };

  const handleRunStage = (stage: string) => openRerunModal({ type: "run-stage", stage });

  const rerunConfirmLabel = (() => {
    if (pendingAction?.type === "run-stage") {
      const labels: Record<string, string> = {
        preprocessing: "Confirm & Re-run Preprocessing",
        rag_enrichment: "Confirm & Re-run RAG Enrichment (+ Report)",
        report_generation: "Confirm & Re-run Report Generation",
      };
      return labels[pendingAction.stage] || "Confirm & Re-run Stage";
    }
    return "Confirm & Re-run from Beginning";
  })();

  const handleStop = async () => {
    if (stopRequestRef.current) return;
    stopRequestRef.current = true;
    // Force one paint before network so spinner + dialog show (React 18 batches across await otherwise).
    flushSync(() => {
      setStopInProgress(true);
    });
    try {
      await api.post(`/orders/${orderId}/cancel`);
      const [o, l] = await Promise.all([
        api.get<Order>(`/orders/${orderId}`),
        api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`),
      ]);
      setOrder(o);
      setLogs(l.logs);
    } catch (err: any) {
      alert(err.message || "Failed to stop");
    } finally {
      stopRequestRef.current = false;
      setStopInProgress(false);
    }
  };

  // ── Duplicate Order (via RerunOptionsModal in duplicate mode) ──────
  const [dupName, setDupName] = useState("");

  useEffect(() => {
    if (duplicateModalOpen && order) {
      setDupName(`${order.order_code}_copy`);
    }
  }, [duplicateModalOpen, order]);

  const handleDuplicateConfirm = async (opts: {
    analysis_context: Record<string, unknown>;
    analysis_options: Record<string, unknown>;
    report_options: Record<string, unknown>;
    rag_collections?: number[] | null;
  }) => {
    if (!order || !dupName.trim()) return;
    try {
      const result = await api.post<{ id: number; order_code: string }>(`/orders/${order.id}/duplicate`, {
        new_order_name: dupName.trim(),
        report_options: opts.report_options,
        analysis_options: opts.analysis_options,
        analysis_context: opts.analysis_context,
      });
      setDuplicateModalOpen(false);
      navigate(`/admin/orders/${result.id}`);
    } catch (err: any) {
      alert(err?.message || "Duplication failed");
      throw err;
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (!order) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <AlertCircle className="h-12 w-12 text-muted-foreground/40 mb-3" />
        <p className="text-muted-foreground">Order not found</p>
      </div>
    );
  }

  const currentStageIdx = STAGES.findIndex((s) => s.key === order.current_stage);
  const showProgress = isRunning || ["completed", "failed"].includes(order.status);
  const showTerminal = logs.length > 0 || events.length > 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate("/admin/orders")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight">{order.order_code}</h1>
              {(() => {
                const isHalted = order.stage_detail?.startsWith("Halted:");
                if (isHalted) {
                  return (
                    <>
                      <Badge variant="destructive" className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                        Halted
                      </Badge>
                      <span className="text-xs text-red-500 ml-1" title={order.stage_detail ?? ""}>
                        {(order.stage_detail ?? "").replace("Halted: ", "")}
                      </span>
                    </>
                  );
                }
                const badge = statusBadgeVariant(order.status);
                return (
                  <Badge variant={badge.variant} className={`capitalize ${badge.className ?? ""}`}>
                    {order.status === "rag_enrichment" ? "RAG Enrichment"
                      : order.status === "report_generation" ? "Report Generation"
                      : order.status}
                  </Badge>
                );
              })()}
            </div>
            <p className="text-sm text-muted-foreground mt-0.5">{order.project_name}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={handleRefresh} title="Refresh">
            <RefreshCw className="h-4 w-4" />
          </Button>
          {/* Share button — only for own orders */}
          {!order.is_shared && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setShareModalOpen(true)}
              title="Share order"
            >
              <Share2 className="h-4 w-4" /> Share
            </Button>
          )}
          {isRunning && !isReadOnlyShared && (
            <Button
              variant="destructive"
              onClick={handleStop}
              disabled={stopInProgress}
              className={cn("gap-2 min-w-[7.5rem]", stopInProgress && "opacity-80 cursor-wait")}
            >
              {stopInProgress ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Square className="h-4 w-4" />
              )}
              {stopInProgress ? "Stopping…" : "Stop"}
            </Button>
          )}
          {order.status === "registered" && !isReadOnlyShared && (
            <Button onClick={handleStart} className="gap-2">
              <Play className="h-4 w-4" /> Start Analysis
            </Button>
          )}
          {order.status === "failed" && !isReadOnlyShared && (
            <Button variant="outline" onClick={handleStart} className="gap-2">
              <RotateCcw className="h-4 w-4" /> Retry Analysis
            </Button>
          )}
          {["completed", "cancelled"].includes(order.status) && !isReadOnlyShared && (
            <Button variant="outline" onClick={handleStart} className="gap-2">
              <RotateCcw className="h-4 w-4" /> Re-run from Beginning
            </Button>
          )}
        </div>
      </div>

      {/* Stage Stepper */}
      <Card>
        <CardContent className="py-6">
          <div className="flex items-center justify-between">
            {STAGES.map((stage, i) => {
              const Icon = stage.icon;
              const isActive = order.current_stage === stage.key;
              const isCompleted = currentStageIdx > i || order.status === "completed";
              const isFailed = isActive && order.status === "failed";
              const canRerun =
                !isRunning &&
                order.status !== "registered" &&
                !isReadOnlyShared;

              return (
                <div key={stage.key} className="flex flex-1 items-center">
                  <div className="flex flex-col items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        if (stage.key === "preprocessing") setPrepModalOpen(true);
                        else if (stage.key === "rag_enrichment") setPhaseModalOpen(true);
                        else if (stage.key === "report_generation") setReportModalOpen(true);
                      }}
                      title="진행 상태 보기"
                      className={cn(
                        "relative flex h-11 w-11 items-center justify-center rounded-full border-2 transition-all",
                        isCompleted ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950"
                          : isFailed ? "border-destructive bg-destructive/10"
                          : isActive ? "border-primary bg-primary/10"
                          : "border-muted bg-muted",
                        "cursor-pointer hover:ring-2 hover:ring-primary/50 hover:scale-105",
                      )}
                    >
                      {isCompleted ? (
                        <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 300 }}>
                          <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
                        </motion.div>
                      ) : (
                        <Icon className={cn("h-5 w-5", isActive ? (isFailed ? "text-destructive" : "text-primary") : "text-muted-foreground")} />
                      )}
                      {isActive && !isCompleted && !isFailed && (
                        <motion.div
                          className="absolute inset-0 rounded-full border-2 border-primary pointer-events-none"
                          animate={{ scale: [1, 1.15, 1], opacity: [1, 0.4, 1] }}
                          transition={{ duration: 2, repeat: Infinity }}
                        />
                      )}
                    </button>
                    <span className={cn("text-xs font-medium", isActive ? "text-foreground" : "text-muted-foreground")}>
                      {stage.label}
                    </span>
                    {stage.key === "rag_enrichment" && llmConfig && (
                      <button
                        type="button"
                        onClick={() => setPhaseModalOpen(true)}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-[10px] text-muted-foreground font-mono hover:bg-muted/70 hover:text-foreground transition-colors cursor-pointer"
                        title="Phase 진행 상태 보기"
                      >
                        <Brain className="h-3 w-3" />
                        {(order.report_options as any)?.rag_enrichment_llm_model ||
                          (order.report_options as any)?.rag_llm_model ||
                          llmConfig.default_model}
                      </button>
                    )}
                    {stage.key === "report_generation" && llmConfig && (
                      <button
                        type="button"
                        onClick={() => setReportModalOpen(true)}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-[10px] text-muted-foreground font-mono hover:bg-muted/70 hover:text-foreground transition-colors cursor-pointer"
                        title="진행 상태 보기"
                      >
                        <Brain className="h-3 w-3" />
                        {(order.report_options as any)?.llm_model || llmConfig.default_model}
                      </button>
                    )}
                    {canRerun && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-[10px] gap-1 text-muted-foreground hover:text-primary"
                        onClick={() => handleRunStage(stage.key)}
                      >
                        <RotateCcw className="h-3 w-3" /> Re-run
                      </Button>
                    )}
                  </div>
                  {i < STAGES.length - 1 && (
                    <div className={cn("mx-3 h-0.5 flex-1 rounded-full", isCompleted ? "bg-emerald-400" : "bg-border")} />
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* ── RAG Enrichment Phase Status Modal ── */}
      {phaseModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setPhaseModalOpen(false)}>
          <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-4xl max-h-[80vh] flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-primary" />
                <span className="font-semibold text-sm">RAG Enrichment — Phase 진행 상태</span>
                <Badge variant="outline" className="text-[10px] font-mono">
                  {(() => {
                    const done = Array.from(ptmPhaseMap.values()).filter(r => r.D === "done").length;
                    const total = ptmTotal || ptmPhaseMap.size;
                    return `${done} / ${total} PTMs`;
                  })()}
                </Badge>
              </div>
              <button type="button" onClick={() => setPhaseModalOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="overflow-auto flex-1">
              {ptmPhaseMap.size === 0 ? (
                <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground text-sm">
                  <Loader2 className="h-6 w-6 animate-spin" />
                  <span>아직 Phase 이벤트가 없습니다. 분석이 시작되면 실시간으로 업데이트됩니다.</span>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-28">Gene</TableHead>
                      <TableHead className="w-20">Position</TableHead>
                      {(["A", "B", "C", "D"] as const).map(ph => (
                        <TableHead key={ph} className="text-center w-20">
                          Phase {ph}
                          <div className="text-[9px] font-normal text-muted-foreground">
                            {ph === "A" ? "MCP" : ph === "B" ? "LLM" : ph === "C" ? "STRING" : "Assembly"}
                          </div>
                        </TableHead>
                      ))}
                      <TableHead>Detail</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Array.from(ptmPhaseMap.values()).map(row => {
                      const isCancelledOrder = order?.status === "cancelled" || order?.status === "failed";
                      const phaseIcon = (s: string) => {
                        if (s === "done") return <CheckCircle2 className="h-4 w-4 text-emerald-500 mx-auto" />;
                        if (s === "running") {
                          if (isCancelledOrder)
                            return <StopCircle className="h-4 w-4 text-amber-500 mx-auto" aria-label="중단됨" />;
                          return <Loader2 className="h-4 w-4 text-primary animate-spin mx-auto" />;
                        }
                        if (s === "error") return <AlertCircle className="h-4 w-4 text-destructive mx-auto" />;
                        if (s === "skip") return <span className="text-[10px] text-muted-foreground block text-center">skip</span>;
                        return <Circle className="h-3 w-3 text-muted-foreground/40 mx-auto" />;
                      };
                      const hasError = [row.A, row.B, row.C, row.D].some(s => s === "error");
                      return (
                        <TableRow key={`${row.gene}__${row.position}`} className={hasError ? "bg-destructive/5" : undefined}>
                          <TableCell className="font-mono text-xs font-medium">{row.gene}</TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">{row.position}</TableCell>
                          {(["A", "B", "C", "D"] as const).map(ph => (
                            <TableCell key={ph} className="text-center">{phaseIcon(row[ph])}</TableCell>
                          ))}
                          <TableCell className="text-[10px] text-muted-foreground max-w-[280px]">
                            <div className="space-y-1">
                              {row.errorDetail && <span className="block text-destructive" title={row.errorDetail}>⚠ {row.errorDetail}</span>}
                              {row.articleProgress && (() => {
                                const [d, t] = row.articleProgress.split("/").map(Number);
                                const isDone = row.B === "done";
                                const cached = row.cachedCount > 0 ? `, ${row.cachedCount} cached` : "";
                                return (
                                  <span className={isDone ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"}>
                                    {isDone ? "✓ " : ""}{d}/{t} articles{cached}
                                  </span>
                                );
                              })()}
                              {row.sourceSummary.length > 0 && <div className="flex flex-wrap gap-1">
                                {row.sourceSummary.map(source => {
                                  const tone = source.status === "error"
                                    ? "text-destructive border-destructive/40"
                                    : source.status === "skip"
                                    ? "text-muted-foreground/60 border-border"
                                    : source.status === "cache_hit"
                                    ? "text-sky-600 dark:text-sky-400 border-sky-500/40"
                                    : source.status === "empty"
                                    ? "text-muted-foreground border-border"
                                    : "text-emerald-600 dark:text-emerald-400 border-emerald-500/40";
                                  const value = source.status === "skip" ? "skip"
                                    : source.status === "cache_hit" ? `${source.count} cached`
                                    : source.status === "error" ? "error"
                                    : `${source.count} ${source.unit}`;
                                  return <span key={source.key} className={`border rounded px-1 py-0.5 ${tone}`} title={`${source.label}: ${source.status}`}>{source.label} {value}</span>;
                                })}
                              </div>}
                              {!row.errorDetail && !row.articleProgress && row.sourceSummary.length === 0 && <span className="text-muted-foreground/40">—</span>}
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </div>
            <div className="px-5 py-2 border-t border-border text-[10px] text-muted-foreground flex gap-4">
              <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3 text-emerald-500" /> done</span>
              <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 text-primary" /> running</span>
              <span className="flex items-center gap-1"><StopCircle className="h-3 w-3 text-amber-500" /> stopped</span>
              <span className="flex items-center gap-1"><AlertCircle className="h-3 w-3 text-destructive" /> error</span>
              <span className="flex items-center gap-1"><Circle className="h-3 w-3 text-muted-foreground/40" /> pending</span>
              <span className="text-muted-foreground/60">skip = 조건 미충족(정상)</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Preprocessing Phase Status Modal ── */}
      {prepModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setPrepModalOpen(false)}>
          <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <Cog className="h-4 w-4 text-primary" />
                <span className="font-semibold text-sm">Preprocessing — 단계별 진행 상태</span>
                <Badge variant="outline" className="text-[10px] font-mono">
                  {prepStepRows.filter(r => r.status === "done").length} / {prepStepRows.length} steps
                </Badge>
              </div>
              <button type="button" onClick={() => setPrepModalOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="overflow-auto flex-1">
              {prepStepRows.every(r => r.status === "pending") ? (
                <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground text-sm">
                  <Loader2 className="h-6 w-6 animate-spin" />
                  <span>아직 이벤트가 없습니다. 분석이 시작되면 실시간으로 업데이트됩니다.</span>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12 text-center">#</TableHead>
                      <TableHead>Step</TableHead>
                      <TableHead className="text-center w-20">Status</TableHead>
                      <TableHead>Detail</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {prepStepRows.map((row, i) => {
                      const isCancelledOrder = order?.status === "cancelled" || order?.status === "failed";
                      const icon = row.status === "done" ? <CheckCircle2 className="h-4 w-4 text-emerald-500 mx-auto" />
                        : row.status === "running" ? (isCancelledOrder ? <StopCircle className="h-4 w-4 text-amber-500 mx-auto" /> : <Loader2 className="h-4 w-4 text-primary animate-spin mx-auto" />)
                        : row.status === "error" ? <AlertCircle className="h-4 w-4 text-destructive mx-auto" />
                        : <Circle className="h-3 w-3 text-muted-foreground/40 mx-auto" />;
                      return (
                        <TableRow key={row.step}>
                          <TableCell className="text-center text-xs text-muted-foreground">{i + 1}</TableCell>
                          <TableCell className="text-xs font-medium">{row.label}</TableCell>
                          <TableCell className="text-center">{icon}</TableCell>
                          <TableCell className="text-[10px] text-muted-foreground max-w-[250px] truncate">
                            {row.detail ? (
                              <span className={row.status === "done" ? "text-emerald-600 dark:text-emerald-400" : ""}>{row.detail}</span>
                            ) : (
                              <span className="text-muted-foreground/40">—</span>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </div>
            <div className="px-5 py-2 border-t border-border text-[10px] text-muted-foreground flex gap-4">
              <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3 text-emerald-500" /> done</span>
              <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 text-primary" /> running</span>
              <span className="flex items-center gap-1"><Circle className="h-3 w-3 text-muted-foreground/40" /> pending</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Report Generation Phase Status Modal ── */}
      {reportModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setReportModalOpen(false)}>
          <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-border">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-primary" />
                <span className="font-semibold text-sm">Report Generation — 단계별 진행 상태</span>
                <Badge variant="outline" className="text-[10px] font-mono">
                  {reportStepRows.filter(r => r.status === "done").length} / {reportStepRows.length} steps
                </Badge>
              </div>
              <button type="button" onClick={() => setReportModalOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="overflow-auto flex-1">
              {reportStepRows.every(r => r.status === "pending") ? (
                <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground text-sm">
                  <Loader2 className="h-6 w-6 animate-spin" />
                  <span>아직 이벤트가 없습니다. 분석이 시작되면 실시간으로 업데이트됩니다.</span>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-12 text-center">#</TableHead>
                      <TableHead>Step</TableHead>
                      <TableHead className="text-center w-20">Status</TableHead>
                      <TableHead>Detail</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {reportStepRows.map((row, i) => {
                      const isCancelledOrder = order?.status === "cancelled" || order?.status === "failed";
                      const icon = row.status === "done" ? <CheckCircle2 className="h-4 w-4 text-emerald-500 mx-auto" />
                        : row.status === "running" ? (isCancelledOrder ? <StopCircle className="h-4 w-4 text-amber-500 mx-auto" /> : <Loader2 className="h-4 w-4 text-primary animate-spin mx-auto" />)
                        : row.status === "error" ? <AlertCircle className="h-4 w-4 text-destructive mx-auto" />
                        : <Circle className="h-3 w-3 text-muted-foreground/40 mx-auto" />;
                      return (
                        <TableRow key={row.step}>
                          <TableCell className="text-center text-xs text-muted-foreground">{i + 1}</TableCell>
                          <TableCell className="text-xs font-medium">{row.label}</TableCell>
                          <TableCell className="text-center">{icon}</TableCell>
                          <TableCell className="text-[10px] text-muted-foreground max-w-[250px] truncate">
                            {row.detail ? (
                              <span className={row.status === "done" ? "text-emerald-600 dark:text-emerald-400" : ""}>{row.detail}</span>
                            ) : (
                              <span className="text-muted-foreground/40">—</span>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </div>
            <div className="px-5 py-2 border-t border-border text-[10px] text-muted-foreground flex gap-4">
              <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3 text-emerald-500" /> done</span>
              <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 text-primary" /> running</span>
              <span className="flex items-center gap-1"><Circle className="h-3 w-3 text-muted-foreground/40" /> pending</span>
            </div>
          </div>
        </div>
      )}

      {/* Activity Progress Bar */}
      {showProgress && (
        <ActivityProgress
          progress={progress}
          stage={order.current_stage}
          pct={Number(order.progress_pct) || 0}
          message={order.stage_detail}
          isRunning={isRunning}
        />
      )}

      {/* Collapsible Terminal Log */}
      {showTerminal && (
        <TerminalPanel logs={logs} sseEvents={events} isRunning={isRunning} />
      )}

      {/* Error */}
      {order.status === "failed" && order.error_message && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Analysis Failed</AlertTitle>
          <AlertDescription>{order.error_message}</AlertDescription>
        </Alert>
      )}

      {/* PPTX generation (Celery) — 모든 탭에서 보임; 진행률은 워커 PROGRESS 메타 + sessionStorage 복원 */}
      {pptxGenerating && (
        <div className="rounded-lg border border-primary/35 bg-primary/5 px-4 py-3 space-y-2 shadow-sm">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
            <span className="text-sm font-medium">Generating PPTX…</span>
          </div>
          <p className="text-xs text-muted-foreground pl-6">
            {pptxProgressMeta?.message ?? "Preparing presentation. You can switch tabs; progress is saved for this order."}
          </p>
          <div className="pl-6 pr-1 pt-1">
            {typeof pptxProgressMeta?.progress === "number" ? (
              <Progress value={Math.min(100, Math.max(0, pptxProgressMeta.progress))} className="h-2" />
            ) : (
              <div className="relative h-2 w-full overflow-hidden rounded-full bg-primary/20">
                <motion.div
                  className="absolute top-0 bottom-0 w-[38%] rounded-full bg-primary"
                  initial={false}
                  animate={{ left: ["-38%", "100%"] }}
                  transition={{ repeat: Infinity, duration: 1.55, ease: "linear" }}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tabs: Overview / Analysis Statistics / Vector Plot / Results */}
      <Tabs defaultValue="overview" onValueChange={(v) => setActiveTab(v)}>
        <div className="flex items-center justify-between gap-2">
          <TabsList className="flex-wrap h-auto gap-1">
            <TabsTrigger value="overview">
              <LayoutDashboard className="h-3.5 w-3.5 mr-1.5" />
              Overview
            </TabsTrigger>
            <TabsTrigger value="analysis-statistics">
              <BarChart3 className="h-3.5 w-3.5 mr-1.5" />
              Analysis Statistics
            </TabsTrigger>
            <TabsTrigger value="vector-plot">
              <ChartScatter className="h-3.5 w-3.5 mr-1.5" />
              Vector Plot
            </TabsTrigger>
            {(order.report_options as any)?.analysis_mode === "cross_talk" && (
              <TabsTrigger value="cross-talk">
                <GitMerge className="h-3.5 w-3.5 mr-1.5" />
                Cross-Talk
              </TabsTrigger>
            )}
            <TabsTrigger value="articles">
              <BookOpen className="h-3.5 w-3.5 mr-1.5" />
              Articles
            </TabsTrigger>
            <TabsTrigger value="results">
              <FileOutput className="h-3.5 w-3.5 mr-1.5" />
              Results
            </TabsTrigger>
            <TabsTrigger value="coscientist">
              <FlaskConical className="h-3.5 w-3.5 mr-1.5" />
              Co-Scientist
            </TabsTrigger>
          </TabsList>
          <Button variant="outline" size="sm" className="shrink-0" onClick={() => setDuplicateModalOpen(true)}>
            <CopyPlus className="h-3.5 w-3.5 mr-1.5" />
            Order Duplicate
          </Button>
        </div>

        <TabsContent value="overview" className="space-y-4 mt-4">
          {/* Project & Sample Info */}
          <div className="grid md:grid-cols-2 gap-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Project & Sample</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <OverviewField label="Order Name" value={order.order_code} />
                <OverviewField label="Project Name" value={order.project_name} />
                <OverviewField label="PTM Type" value={order.ptm_type} capitalize />
                <OverviewField label="Species" value={order.species} capitalize />
                <OverviewField
                  label="Analysis Mode"
                  value={
                    (order.report_options as any)?.analysis_mode === "cross_talk"
                      ? "Cross-Talk (Phos x Ub)"
                      : (order.report_options as any)?.analysis_mode === "ptm_nonptm_network"
                        ? "PTM + Network"
                        : "PTM-Only"
                  }
                />
                <OverviewField
                  label="Report Type"
                  value={
                    (order.report_options as any)?.report_type === "extended"
                      ? "Extended (+ Drug Repositioning)"
                      : (order.report_options as any)?.report_type === "co_scientist"
                        ? "Data-Grounded Analysis"
                        : "Standard"
                  }
                />
                <OverviewField
                  label="RAG Literature Collections"
                  value={
                    (() => {
                      const ids = order.rag_collections;
                      if (!ids || !Array.isArray(ids) || ids.length === 0) return "All active collections";
                      const toNum = (x: unknown) => (typeof x === "string" ? parseInt(x, 10) : Number(x));
                      const names = ids
                        .map((id) => ragCollections.find((c) => c.id === toNum(id))?.name ?? `#${id}`)
                        .filter(Boolean);
                      return names.length > 0 ? names.join(", ") : `${ids.length} collections`;
                    })()
                  }
                />
                <OverviewField
                  label="Created"
                  value={new Date(order.created_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Sample Configuration</CardTitle>
              </CardHeader>
              <CardContent>
                {order.sample_config && (order.sample_config as any).samples?.length > 0 ? (
                  <div className="space-y-3">
                    {(order.sample_config as any).single_time_point && (
                      <div className="rounded-md bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs font-medium text-amber-700 dark:text-amber-400">
                        Single time point (no temporal grouping)
                      </div>
                    )}
                    <OverviewField
                      label="Source"
                      value={(order.sample_config as any).source === "xlsx" ? "config.xlsx" : "Auto Parse"}
                    />
                    {(order.sample_config as any).regex_pattern && (
                      <OverviewField label="Regex Pattern" value={(order.sample_config as any).regex_pattern} mono />
                    )}
                    <div>
                      <p className="text-xs text-muted-foreground mb-2">Samples ({(order.sample_config as any).samples.length})</p>
                      <div className="max-h-[200px] overflow-y-auto rounded border bg-muted/20">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="text-[10px] py-1.5">File</TableHead>
                              <TableHead className="text-[10px] py-1.5">Condition</TableHead>
                              <TableHead className="text-[10px] py-1.5">Group</TableHead>
                              <TableHead className="text-[10px] py-1.5 w-12">Rep</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {((order.sample_config as any).samples as any[]).map((s: any, i: number) => (
                              <TableRow key={i}>
                                <TableCell className="text-xs py-1.5 font-mono truncate max-w-[140px]" title={s.file_name}>
                                  {s.file_name?.split(/[/\\]/).pop() || s.file_name}
                                </TableCell>
                                <TableCell className="text-xs py-1.5">{s.condition ?? "-"}</TableCell>
                                <TableCell className="text-xs py-1.5">{s.group ?? "-"}</TableCell>
                                <TableCell className="text-xs py-1.5">{s.replicate ?? 1}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No sample configuration</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Analysis Context — full text, no truncation */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Analysis Context</CardTitle>
              <p className="text-xs text-muted-foreground mt-1">Cell type, treatment, time points, biological question</p>
            </CardHeader>
            <CardContent>
              {order.analysis_context && Object.keys(order.analysis_context).some((k) => (order.analysis_context as any)[k]) ? (
                <div className="grid sm:grid-cols-2 gap-4">
                  {(["cell_type", "treatment", "time_points", "biological_question", "special_conditions"] as const).map((key) => {
                    const val = (order.analysis_context as any)?.[key];
                    if (val == null || val === "") return null;
                    const label = key.replace(/_/g, " ");
                    const isLong = key === "biological_question";
                    return (
                      <div key={key} className={isLong ? "sm:col-span-2" : ""}>
                        <OverviewField
                          label={label}
                          value={String(val)}
                          longText={isLong}
                        />
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No analysis context provided</p>
              )}
            </CardContent>
          </Card>

          {/* Analysis Options & Report Options */}
          <div className="grid md:grid-cols-2 gap-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Analysis Options (Protein Selection)</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <OverviewField
                  label="Mode"
                  value={
                    (() => {
                      const mode = (order.analysis_options as Record<string, string> | undefined)?.mode;
                      const labels: Record<string, string> = {
                        full: "Full Analysis",
                        ptm_topn: "PTM Sites + Top N",
                        log2fc_threshold: "Log2FC Threshold",
                        custom_count: "Custom Protein Count",
                        protein_list: "Custom Protein List",
                      };
                      return (mode && labels[mode]) ?? mode ?? "Full Analysis";
                    })()
                  }
                />
                {(order.analysis_options as any)?.mode === "ptm_topn" && (
                  <OverviewField label="Top N (proteins)" value={`${(order.analysis_options as any)?.topN ?? 500}개`} />
                )}
                {(order.analysis_options as any)?.mode === "log2fc_threshold" && (
                  <OverviewField label="Log2FC Threshold" value={String((order.analysis_options as any)?.log2fcThreshold ?? 0.5)} />
                )}
                {(order.analysis_options as any)?.mode === "custom_count" && (
                  <OverviewField label="Protein Count" value={String((order.analysis_options as any)?.proteinCount ?? 1000)} />
                )}
                {(order.analysis_options as any)?.protein_list_path && (
                  <OverviewField
                    label="Protein List"
                    value={(order.analysis_options as any).protein_list_path?.split(/[/\\]/).pop() ?? (order.analysis_options as any).protein_list_path}
                    mono
                  />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Report Options</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <OverviewField
                  label="PTM Selection Mode"
                  value={(() => {
                    const mode = (order.report_options as any)?.ptm_selection_mode;
                    const labels: Record<string, string> = {
                      de_novo_regulated: "De novo + Regulated",
                      de_novo: "De novo only",
                      regulated: "Regulated only",
                      minor: "Minor only",
                      all: "All PTMs",
                      top_n: `Top ${(order.report_options as any)?.top_n_ptms ?? 50} by |FC|`,
                    };
                    return labels[mode] ?? (mode ? mode : "De novo + Regulated");
                  })()}
                />
                <OverviewField
                  label="LLM Model (RAG Enrichment)"
                  value={(order.report_options as any)?.rag_enrichment_llm_model || "Default (Report model)"}
                />
                <OverviewField
                  label="LLM Model (Report)"
                  value={(order.report_options as any)?.llm_model || "Default"}
                />
                <OverviewField
                  label="External Co-Scientist Discussion"
                  value={(() => {
                    const integration = (order.report_options as any)?.co_scientist_integration;
                    const result = (order.result_files as any)?.co_scientist_integration_result;
                    if (!integration?.enabled || !integration?.session_id) {
                      if (result?.status && result.status !== "disabled") {
                        return `Last run: ${result.status}${result.warning ? ` — ${result.warning}` : ""}`;
                      }
                      return "Not included";
                    }
                    const label = integration.mode === "enhanced_discussion"
                      ? "Enhanced Discussion"
                      : "Hypothesis & Validation Addendum";
                    const selected = `${label} · session ${String(integration.session_id).slice(0, 12)}`;
                    if (!result?.status) return selected;
                    const detail = result.status === "ready"
                      ? `ready (${result.eligible_hypotheses ?? 0} candidates)`
                      : result.warning
                        ? `${result.status} — ${result.warning}`
                        : result.status;
                    return `${selected} · ${detail}`;
                  })()}
                />
                <OverviewField
                  label="RAG Literature Collections"
                  value={
                    (() => {
                      const ids = order.rag_collections;
                      if (!ids || !Array.isArray(ids) || ids.length === 0) return "All active collections";
                      const toNum = (x: unknown) => (typeof x === "string" ? parseInt(x, 10) : Number(x));
                      const names = ids
                        .map((id) => ragCollections.find((c) => c.id === toNum(id))?.name ?? `#${id}`)
                        .filter(Boolean);
                      return names.length > 0 ? names.join(", ") : `${ids.length} collections`;
                    })()
                  }
                />
              </CardContent>
            </Card>
          </div>

          {/* Research Questions are omitted for Co-Scientist reports, which generate questions autonomously. */}
          {(order.report_options as any)?.report_type !== "co_scientist" && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <MessageSquare className="h-4 w-4" /> Research Questions
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(() => {
                const qs = (order.report_options as any)?.research_questions;
                const list = Array.isArray(qs) ? qs.filter((q: unknown) => typeof q === "string" && q.trim()) : [];
                if (list.length === 0) {
                  return <p className="text-sm text-muted-foreground">설정된 연구 질문이 없습니다.</p>;
                }
                return (
                  <div className="space-y-2">
                    {list.map((q: string, i: number) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="text-xs text-muted-foreground mt-1.5 w-5 shrink-0">Q{i + 1}</span>
                        <div className="flex-1 rounded-lg border px-3 py-2 text-sm bg-muted/30 break-words">{q}</div>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </CardContent>
          </Card>
          )}

          {/* Research Question Evolution (from rq_refinement pipeline node) */}
          {(() => {
            const rqLog = logs.find(l => l.metadata?.type === "rq_refinement");
            if (!rqLog?.metadata) return null;
            const meta = rqLog.metadata as Record<string, unknown>;
            const origQs = (meta.original_questions as string[]) || [];
            const refinedQs = (meta.refined_questions as string[]) || [];
            const refinedItems = (meta.refined_items as Array<{question: string; category?: string; signaling_chain?: string; priority?: string}>) || [];
            const keyDiscovery = meta.key_discovery as string || "";
            if (origQs.length === 0 && refinedQs.length === 0) return null;
            return (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <GitMerge className="h-4 w-4" /> Research Question Evolution
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {origQs.length > 0 && (
                    <div>
                      <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
                        RQ₀ — Original (User)
                      </p>
                      <div className="space-y-1.5">
                        {origQs.map((q: string, i: number) => (
                          <div key={i} className="rounded border px-3 py-1.5 text-xs bg-muted/20 text-muted-foreground break-words">
                            {q}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {refinedItems.length > 0 && (
                    <>
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <ArrowRightCircle className="h-3.5 w-3.5 rotate-90" />
                        <span className="text-[10px] uppercase tracking-wider">Refined by Signaling Analysis</span>
                      </div>
                      <div>
                        <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
                          RQ₂ — Data-grounded
                        </p>
                        <div className="space-y-2">
                          {refinedItems.map((item, i: number) => (
                            <div key={i} className="rounded-lg border px-3 py-2 text-sm bg-background break-words">
                              <div className="flex items-start gap-2">
                                <span className="text-xs text-primary font-mono mt-0.5 shrink-0">Q{i + 1}</span>
                                <div className="flex-1">
                                  <p>{item.question}</p>
                                  <div className="flex flex-wrap gap-1.5 mt-1.5">
                                    {item.category && (
                                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">{item.category}</span>
                                    )}
                                    {item.priority && (
                                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${item.priority === "high" ? "bg-orange-500/10 text-orange-600" : "bg-muted text-muted-foreground"}`}>
                                        {item.priority}
                                      </span>
                                    )}
                                    {item.signaling_chain && (
                                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-600 font-mono">{item.signaling_chain}</span>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                  {keyDiscovery && (
                    <div className="rounded border-l-2 border-primary/40 bg-primary/5 px-3 py-2">
                      <p className="text-[10px] font-medium text-primary uppercase tracking-wider mb-1">Key Discovery</p>
                      <p className="text-xs">{keyDiscovery}</p>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })()}
        </TabsContent>

        <TabsContent value="results" className="mt-4">
          {order.result_files && (order.result_files as any)?.all_files?.length > 0 ? (
            <div className="space-y-4">
              {!isRunning && order.status !== "registered" && !isReadOnlyShared && (
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Select value={pptxLlm} onValueChange={setPptxLlm}>
                      <SelectTrigger className="h-8 text-xs w-[200px]">
                        <SelectValue placeholder="LLM for PPTX" />
                      </SelectTrigger>
                      <SelectContent>
                        {llmModels.map((m) => (
                          <SelectItem key={`pptx-${m.provider}:${m.model_id}`} value={`${m.provider}:${m.model_id}`} className="text-xs">
                            {m.name} ({m.provider})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      size="sm"
                      className="gap-2"
                      disabled={pptxGenerating || !pptxLlm}
                      onClick={async () => {
                        setPptxGenerating(true);
                        setPptxProgressMeta({ message: "Queueing PPTX job…", progress: null });
                        try {
                          const [provider, ...modelParts] = pptxLlm.split(":");
                          const model = modelParts.join(":");
                          const res = await api.post<{ task_id: string }>(`/orders/${order.id}/generate-pptx`, {
                            llm_provider: provider,
                            llm_model: model === "__provider__" ? "" : model,
                          });
                          const tid = res.task_id;
                          sessionStorage.setItem(`pptx-task-${order.id}`, tid);
                          pptxPollAbortRef.current?.abort();
                          const ac = new AbortController();
                          pptxPollAbortRef.current = ac;
                          await runPptxPollRef.current?.(tid, ac.signal);
                        } catch (e: unknown) {
                          setPptxProgressMeta(null);
                          sessionStorage.removeItem(`pptx-meta-${order.id}`);
                          const msg =
                            e instanceof Error && e.message
                              ? e.message
                              : typeof e === "string"
                                ? e
                                : "PPTX 생성에 실패했습니다.";
                          alert(msg);
                        } finally {
                          setPptxGenerating(false);
                        }
                      }}
                    >
                      {pptxGenerating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Presentation className="h-3.5 w-3.5" />}
                      {pptxGenerating ? "Generating PPTX…" : "Generate PPTX"}
                    </Button>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={() => handleRunStage("report_generation")}
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Re-run Report Generation
                  </Button>
                </div>
              )}
              <ResultFiles orderId={order.id} resultFiles={order.result_files as any} onDeleted={handleRefresh} />
            </div>
          ) : (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12 gap-4">
                <FileText className="h-12 w-12 text-muted-foreground/40 mb-3" />
                <p className="text-sm text-muted-foreground">
                  {order.status === "completed"
                    ? "Report files available for download"
                    : "Results will appear here after analysis completes"}
                </p>
                {!isRunning && order.status !== "registered" && !isReadOnlyShared && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={() => handleRunStage("report_generation")}
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                    Re-run Report Generation
                  </Button>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="analysis-statistics" className="mt-4">
          <AnalysisStatisticsTab orderId={order.id} />
        </TabsContent>

        <TabsContent value="vector-plot" className="mt-4">
          <div className="flex gap-4">
            <div className={chatOpen ? "flex-1 min-w-0" : "w-full"}>
              <VectorPlotTab orderId={order.id} singleTimePoint={(order.sample_config as any)?.single_time_point} ptmType={order.ptm_type} />
            </div>

            <div className={`${chatOpen ? "w-[420px]" : "w-10"} flex-shrink-0 h-[calc(100vh-200px)] sticky top-4 rounded-xl border border-border shadow-lg overflow-hidden`}>
              <ChatPanel
                orderId={order.id}
                viewContext={{
                  active_tab: activeTab,
                }}
                isOpen={chatOpen}
                onToggle={() => setChatOpen((v) => !v)}
              />
            </div>
          </div>
        </TabsContent>

        {(order.report_options as any)?.analysis_mode === "cross_talk" && (
          <TabsContent value="cross-talk" className="mt-4">
            <div className="space-y-6">
              {/* Cross-Talk Header */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <GitMerge className="h-4 w-4 text-amber-600" />
                    Cross-Talk Analysis (Phos x Ub)
                  </CardTitle>
                  <p className="text-xs text-muted-foreground mt-1">
                    Phosphorylation과 Ubiquitylation 간의 Cross-Talk 패턴 분석 결과
                  </p>
                </CardHeader>
              </Card>

              {order.cross_talk_data ? (
                <>
                  {/* Venn Diagram - cross_talk_data is flat: dual_ptm_proteins, primary_summary, etc. */}
                  {(order.cross_talk_data as any)?.primary_summary && (order.cross_talk_data as any)?.secondary_summary && (
                    <CrossTalkVennDiagram
                      dualPTMProteins={(order.cross_talk_data as any).dual_ptm_proteins ?? []}
                      primarySummary={(order.cross_talk_data as any).primary_summary}
                      secondarySummary={(order.cross_talk_data as any).secondary_summary}
                      sharedNonPTM={(order.cross_talk_data as any).shared_nonptm ?? []}
                      primaryOnlyNonPTM={(order.cross_talk_data as any).primary_only_nonptm ?? []}
                      secondaryOnlyNonPTM={(order.cross_talk_data as any).secondary_only_nonptm ?? []}
                    />
                  )}

                  {/* Heatmap */}
                  {(order.cross_talk_data as any)?.dual_ptm_proteins?.length > 0 && (
                    <CrossTalkHeatmap
                      dualPTMProteins={(order.cross_talk_data as any).dual_ptm_proteins}
                      primaryPtmType={(order.cross_talk_data as any).primary_ptm_type ?? "phosphorylation"}
                      secondaryPtmType={(order.cross_talk_data as any).secondary_ptm_type ?? "ubiquitylation"}
                    />
                  )}

                  {/* Sequential Gating */}
                  {(order.cross_talk_data as any)?.sequential_gating?.length > 0 && (
                    <CrossTalkSequentialGating
                      gatingEvents={(order.cross_talk_data as any).sequential_gating}
                      primaryPtmType={(order.cross_talk_data as any).primary_ptm_type ?? "phosphorylation"}
                      secondaryPtmType={(order.cross_talk_data as any).secondary_ptm_type ?? "ubiquitylation"}
                    />
                  )}

                  {/* Signal Propagation Timeline */}
                  {order.signal_propagation_data?.summary && (
                    <SignalPropagationTimeline data={order.signal_propagation_data as any} orderId={order.id} />
                  )}
                </>
              ) : (
                <Card>
                  <CardContent className="flex flex-col items-center justify-center py-12 gap-4">
                    <GitMerge className="h-12 w-12 text-muted-foreground/40" />
                    <p className="text-sm text-muted-foreground">
                      {order.status === "completed"
                        ? "Cross-Talk 분석 데이터가 없습니다."
                        : "분석 완료 후 Cross-Talk 결과가 여기에 표시됩니다."}
                    </p>
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>
        )}

        {/* Articles Tab */}
        <TabsContent value="articles" className="mt-4">
          <OrderArticlesTab orderCode={order.order_code} orderStatus={order.status} />
        </TabsContent>

        {/* Co-Scientist Tab */}
        <TabsContent value="coscientist" className="mt-4">
          <CoScientistTab
            orderId={order.id}
            orderCode={order.order_code}
            orderStatus={order.status}
          />
        </TabsContent>
      </Tabs>

      {/* Stop-in-progress overlay — renders immediately (no portal/animation delay) */}
      {stopInProgress && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-background rounded-lg shadow-lg p-6 max-w-md w-full mx-4 flex flex-col gap-3">
            <div className="flex items-center gap-3 text-lg font-semibold">
              <Loader2 className="h-6 w-6 shrink-0 animate-spin text-primary" />
              분석을 멈추는 중
            </div>
            <p className="text-sm text-muted-foreground">
              서버에 중단 요청을 보내고 있습니다. 백그라운드 워커와 LLM이 처리 중일 수 있어 잠시 걸릴 수 있습니다.
            </p>
          </div>
        </div>
      )}

      <RerunOptionsModal
        open={rerunModalOpen}
        onOpenChange={(open) => {
          setRerunModalOpen(open);
          if (!open) setPendingAction(null);
        }}
        order={order}
        llmModels={llmModels}
        defaultLlmModel={llmConfig?.default_model || ""}
        onConfirm={handleRerunConfirm}
        confirmLabel={rerunConfirmLabel}
      />
      <ShareOrderModal
        open={shareModalOpen}
        onOpenChange={setShareModalOpen}
        orderId={order.id}
        orderCode={order.order_code}
      />
      <RerunOptionsModal
        open={duplicateModalOpen}
        onOpenChange={setDuplicateModalOpen}
        order={order}
        llmModels={llmModels}
        defaultLlmModel={llmConfig?.default_model || ""}
        onConfirm={handleDuplicateConfirm}
        confirmLabel="Create Duplicate"
        duplicateMode
        duplicateName={dupName}
        onDuplicateNameChange={setDupName}
      />
    </div>
  );
}
