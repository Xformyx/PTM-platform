import { useEffect, useRef, useState, useMemo } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Cog, BookOpen, FileText, CheckCircle2, AlertCircle, Brain,
  Play, RotateCcw, ArrowLeft, Terminal, Circle, RefreshCw,
  ChevronDown, ChevronUp, Download, FileSpreadsheet, FileJson, File, FolderOpen,
  Copy, Check, Eye, ArrowRightCircle, Sparkles, Plus, X,
  MessageSquare, Loader2, ToggleLeft, ToggleRight, Square,
  ChartScatter,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useOrderProgress } from "@/hooks/useSSE";
import type { Order, OrderLog, ProgressEvent } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import FilePreviewModal from "@/components/FilePreviewModal";
import RerunOptionsModal from "@/components/RerunOptionsModal";

const STAGES = [
  { key: "preprocessing", label: "Preprocessing", icon: Cog, range: [0, 33] },
  { key: "rag_enrichment", label: "RAG Enrichment", icon: BookOpen, range: [33, 66] },
  { key: "report_generation", label: "Report Generation", icon: FileText, range: [66, 100] },
];

const statusBadgeVariant = (s: string) => {
  switch (s) {
    case "completed": return "success" as const;
    case "failed": return "destructive" as const;
    case "running": case "preprocessing": case "rag_enrichment": case "report_generation": return "info" as const;
    default: return "secondary" as const;
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
    case "report_generation": return "Report Gen";
    default: return stage;
  }
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
    default: return "·";
  }
}

function statusColor(status: string): string {
  switch (status) {
    case "completed": return "text-emerald-400";
    case "failed": return "text-red-400";
    case "started": return "text-cyan-400";
    case "running": return "text-blue-400";
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
  // Matches patterns like "InterPro domains: 1,200/6,071" or "UniProt: 500/6,095"
  const m = message.match(/^(.+?):\s*([\d,]+)\s*\/\s*([\d,]+)$/);
  if (!m) return null;
  const done = parseInt(m[2].replace(/,/g, ""));
  const total = parseInt(m[3].replace(/,/g, ""));
  if (isNaN(done) || isNaN(total) || total === 0) return null;
  return { label: m[1].trim(), done, total, pct: Math.round((done / total) * 100) };
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
  const overallPct = progress?.progress_pct ?? pct;
  const sub = parseSubProgress(latestMessage);

  if (!isRunning && !sub) return null;

  return (
    <Card>
      <CardContent className="py-4 space-y-3">
        {/* Overall progress */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              {isRunning && (
                <Circle className="h-2 w-2 fill-primary text-primary animate-pulse" />
              )}
              <span className="font-medium">{stageLabel(latestStage)}</span>
            </div>
            <span className="text-muted-foreground tabular-nums">
              {overallPct >= 0 ? `${Math.round(overallPct)}%` : ""}
            </span>
          </div>
          <Progress value={Math.max(0, overallPct)} className="h-2" />
        </div>

        {/* Sub-task progress (e.g., InterPro 3,200/6,071) */}
        {sub && (
          <div className="space-y-1.5 pl-4 border-l-2 border-primary/20">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{sub.label}</span>
              <span className="font-mono tabular-nums text-muted-foreground">
                {sub.done.toLocaleString()} / {sub.total.toLocaleString()}
                <span className="ml-1.5 text-foreground font-medium">{sub.pct}%</span>
              </span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-primary/60 transition-all duration-500 ease-out"
                style={{ width: `${sub.pct}%` }}
              />
            </div>
          </div>
        )}

        {/* Current activity text (non-progress messages) */}
        {!sub && latestMessage && (
          <p className="text-xs text-muted-foreground pl-4 border-l-2 border-primary/20">
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
  return {
    key: `sse-${idx}`,
    ts: e._ts || Date.now(),
    stage: e.stage,
    step: e.step,
    status: e.status,
    pct: e.progress_pct,
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

function ResultFiles({ orderId, resultFiles }: { orderId: number; resultFiles: { report_files?: string[]; all_files?: string[] } }) {
  const reports = resultFiles.report_files || [];
  const allFiles = resultFiles.all_files || [];
  const dataFiles = allFiles.filter((f) => !reports.includes(f));

  const [fileDetails, setFileDetails] = useState<Record<string, FileDetail>>({});
  const [hostDir, setHostDir] = useState("");
  const [copied, setCopied] = useState(false);
  const [previewFile, setPreviewFile] = useState("");
  const [reportSort, setReportSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "name", dir: "asc" });
  const [dataSort, setDataSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "name", dir: "asc" });

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

  const downloadUrl = (filename: string) => `/api/orders/${orderId}/files/${encodeURIComponent(filename)}`;

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
  }: {
    files: string[];
    sort: { key: SortKey; dir: "asc" | "desc" };
    onSort: (key: SortKey) => void;
    mono?: boolean;
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
                  <a
                    href={downloadUrl(f)}
                    download={f}
                    className="inline-flex items-center justify-center h-7 px-2 rounded-md hover:bg-muted transition-colors"
                    title="Download"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </a>
                </TableCell>
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

function VectorPlotTab({ orderId }: { orderId: number }) {
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

  if (files.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <ChartScatter className="h-12 w-12 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground text-center">
            Vector plots will appear here after preprocessing completes.
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            PTM vector scatter plots (Protein Log2FC vs PTM Relative/Absolute Log2FC) are generated from the vector TSV.
          </p>
        </CardContent>
      </Card>
    );
  }

  const downloadUrl = (filename: string) => `/api/orders/${orderId}/files/${encodeURIComponent(filename)}`;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <ChartScatter className="h-4 w-4" /> PTM Vector 2D Plots
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Protein Log2FC vs PTM Relative/Absolute Log2FC scatter plots by condition. Generated after preprocessing.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6">
            {files.map((f) => (
              <div key={f} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{f}</span>
                  <a
                    href={downloadUrl(f)}
                    download={f}
                    className="text-xs text-primary hover:underline flex items-center gap-1"
                  >
                    <Download className="h-3 w-3" /> Download
                  </a>
                </div>
                <div className="rounded-lg border overflow-hidden bg-muted/20">
                  <VectorPlotImage orderId={orderId} filename={f} />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
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
            <div className="flex gap-2">
              <Input
                value={newQuestion}
                onChange={(e) => setNewQuestion(e.target.value)}
                placeholder="Add a research question..."
                className="text-sm h-8"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newQuestion.trim()) {
                    setManualQuestions([...manualQuestions, newQuestion.trim()]);
                    setNewQuestion("");
                  }
                }}
              />
              <Button
                variant="outline" size="icon" className="h-8 w-8 shrink-0"
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
  const [logs, setLogs] = useState<OrderLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null);
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [rerunModalOpen, setRerunModalOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<{ type: "start" } | { type: "run-stage"; stage: string } | null>(null);
  const runHandledRef = useRef(false);

  const isRunning = !!order && !["completed", "failed", "pending", "cancelled"].includes(order.status);

  const { progress, events } = useOrderProgress(isRunning ? orderId : null);

  useEffect(() => {
    Promise.all([
      api.get<Order>(`/orders/${orderId}`),
      api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`),
      api.get<LlmConfig>("/system/llm-config"),
    ]).then(([o, l, lc]) => {
      setOrder(o);
      setLogs(l.logs);
      setLlmConfig(lc);
      setLoading(false);
    });
  }, [orderId]);
  useEffect(() => {
    api.get<{ models: { name: string; is_active: boolean }[] }>("/llm/models").then((d) => {
      setOllamaModels(d.models.filter((m) => m.is_active).map((m) => m.name));
    }).catch(() => {});
  }, []);
  useEffect(() => {
    if (runHandledRef.current) return;
    if (searchParams.get("run") !== "1" || !order || !["pending", "failed", "completed"].includes(order.status)) return;

    runHandledRef.current = true;

    const url = new URL(window.location.href);
    url.searchParams.delete("run");
    window.history.replaceState({}, "", url.pathname + url.search);

    if (order.status === "pending") {
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

  useEffect(() => {
    if (!isRunning) return;
    const interval = setInterval(async () => {
      try {
        const [o, l] = await Promise.all([
          api.get<Order>(`/orders/${orderId}`),
          api.get<{ logs: OrderLog[] }>(`/orders/${orderId}/logs`),
        ]);
        setOrder(o);
        setLogs(l.logs);
      } catch { /* ignore */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [isRunning, orderId]);

  useEffect(() => {
    if (progress && order) {
      setOrder((prev) =>
        prev
          ? {
              ...prev,
              progress_pct: progress.progress_pct,
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
  }) => {
    if (!pendingAction) return;
    try {
      await api.patch(`/orders/${orderId}`, opts);
      if (pendingAction.type === "start") {
        await api.post(`/orders/${orderId}/start`);
      } else {
        await api.post(`/orders/${orderId}/run-stage`, { stage: pendingAction.stage });
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
    if (order?.status === "pending") {
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

  const handleStop = async () => {
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
          <Button variant="ghost" size="icon" onClick={() => navigate("/orders")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight">{order.order_code}</h1>
              <Badge variant={statusBadgeVariant(order.status)} className="capitalize">
                {order.status}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground mt-0.5">{order.project_name}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={handleRefresh} title="Refresh">
            <RefreshCw className="h-4 w-4" />
          </Button>
          {isRunning && (
            <Button variant="destructive" onClick={handleStop} className="gap-2">
              <Square className="h-4 w-4" /> Stop
            </Button>
          )}
          {order.status === "pending" && (
            <Button onClick={handleStart} className="gap-2">
              <Play className="h-4 w-4" /> Start Analysis
            </Button>
          )}
          {order.status === "failed" && (
            <Button variant="outline" onClick={handleStart} className="gap-2">
              <RotateCcw className="h-4 w-4" /> Retry Analysis
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
                ["completed", "failed"].includes(order.status);

              return (
                <div key={stage.key} className="flex flex-1 items-center">
                  <div className="flex flex-col items-center gap-2">
                    <div
                      className={cn(
                        "relative flex h-11 w-11 items-center justify-center rounded-full border-2 transition-colors",
                        isCompleted ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950"
                          : isFailed ? "border-destructive bg-destructive/10"
                          : isActive ? "border-primary bg-primary/10"
                          : "border-muted bg-muted",
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
                          className="absolute inset-0 rounded-full border-2 border-primary"
                          animate={{ scale: [1, 1.15, 1], opacity: [1, 0.4, 1] }}
                          transition={{ duration: 2, repeat: Infinity }}
                        />
                      )}
                    </div>
                    <span className={cn("text-xs font-medium", isActive ? "text-foreground" : "text-muted-foreground")}>
                      {stage.label}
                    </span>
                    {stage.key === "report_generation" && llmConfig && (
                      <div className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-[10px] text-muted-foreground font-mono">
                        <Brain className="h-3 w-3" />
                        {(order.report_options as any)?.llm_model || llmConfig.default_model}
                      </div>
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

      {/* Tabs: Overview / Results / Vector Plot */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="vector-plot">
            <ChartScatter className="h-3.5 w-3.5 mr-1.5" />
            Vector Plot
          </TabsTrigger>
          <TabsTrigger value="results">Results</TabsTrigger>
        </TabsList>

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
                  value={(order.report_options as any)?.analysis_mode === "ptm_nonptm_network" ? "PTM + Network" : "PTM-Only"}
                />
                <OverviewField
                  label="Report Type"
                  value={(order.report_options as any)?.report_type === "extended" ? "Extended (+ Drug Repositioning)" : "Standard"}
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
                  label="Top N PTMs"
                  value={`${(order.report_options as any)?.top_n_ptms ?? 20}개`}
                />
                <OverviewField
                  label="LLM Model (Report)"
                  value={(order.report_options as any)?.llm_model || "Default"}
                />
                <OverviewField
                  label="LLM Model (Paper Read)"
                  value={(order.report_options as any)?.rag_llm_model || "Default"}
                />
                {Array.isArray((order.report_options as any)?.research_questions) &&
                 (order.report_options as any).research_questions.length > 0 && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-2">Research Questions</p>
                    <ul className="space-y-1.5 text-sm">
                      {((order.report_options as any).research_questions as string[]).map((q, i) => (
                        <li key={i} className="rounded border bg-muted/20 px-2 py-1.5 break-words">
                          Q{i + 1}. {q}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Research Questions */}
          <ResearchQuestionsPanel
            orderId={order.id}
            orderStatus={order.status}
            reportOptions={order.report_options}
            isRunning={isRunning}
            onRunReport={() => handleRunStage("report_generation")}
          />
        </TabsContent>

        <TabsContent value="results" className="mt-4">
          {order.result_files && (order.result_files as any)?.all_files?.length > 0 ? (
            <div className="space-y-4">
              {!isRunning && ["completed", "failed"].includes(order.status) && (
                <div className="flex justify-end">
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
              <ResultFiles orderId={order.id} resultFiles={order.result_files as any} />
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
                {!isRunning && ["completed", "failed"].includes(order.status) && (
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

        <TabsContent value="vector-plot" className="mt-4">
          <VectorPlotTab orderId={order.id} />
        </TabsContent>
      </Tabs>

      <RerunOptionsModal
        open={rerunModalOpen}
        onOpenChange={(open) => {
          setRerunModalOpen(open);
          if (!open) setPendingAction(null);
        }}
        order={order}
        ollamaModels={ollamaModels}
        defaultLlmModel={llmConfig?.default_model || ""}
        onConfirm={handleRerunConfirm}
        confirmLabel={
          pendingAction?.type === "run-stage"
            ? `Confirm & Re-run ${stageLabel(pendingAction.stage)}`
            : "Confirm & Run"
        }
      />
    </div>
  );
}
