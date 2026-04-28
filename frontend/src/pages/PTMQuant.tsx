import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  FlaskConical, PlusCircle, RefreshCw, Trash2, Download, Eye,
  ChevronDown, ChevronRight, Loader2, FileText, CheckCircle2,
  Clock, XCircle, StopCircle, Folder, FolderOpen, ChevronRight as BreadcrumbSep,
  Home,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

interface MzmlFile  { name: string; path: string; size: number; }
interface DirEntry  { name: string; path: string; }
interface FastaFile { name: string; species: string; label: string; path: string; size: number; }
interface PassDef   { id: string; label: string; description: string; }

interface FilesResponse {
  current_path: string;
  dirs: DirEntry[];
  mzml: MzmlFile[];
  fasta: FastaFile[];
}

interface Job {
  job_id: string;
  name: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  reference_file: string | null;
  input_files: string[] | null;
  passes: string[] | null;
  output_subdir: string | null;
  progress: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

interface OutputFile {
  name: string; path: string; size: number; modified_at?: number; is_tsv: boolean; is_json: boolean; is_matrix: boolean;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatBytes(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

function fmtDate(iso: string) {
  try {
    return new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(new Date(iso)).replace(/\.\s*/g, ".").replace(/\.$/, "");
  } catch { return iso; }
}

function fmtElapsed(start: string, end: string | null, status: Job["status"]) {
  try {
    const s = new Date(start).getTime();
    const e = (status === "done" || status === "failed" || status === "cancelled") && end
      ? new Date(end).getTime() : Date.now();
    const ms = Math.max(0, e - s);
    const sec = Math.floor(ms / 1000);
    const min = Math.floor(sec / 60);
    const hr = Math.floor(min / 60);
    return hr > 0
      ? `${hr}:${String(min % 60).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`
      : `${String(min).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
  } catch { return "—"; }
}

function StatusBadge({ status }: { status: Job["status"] }) {
  const cfg: Record<string, { label: string; icon: React.ReactNode; cls: string }> = {
    pending:   { label: "대기 중",  icon: <Clock className="h-3 w-3" />, cls: "bg-yellow-500/15 text-yellow-600 border-yellow-300" },
    running:   { label: "실행 중",  icon: <Loader2 className="h-3 w-3 animate-spin" />, cls: "bg-blue-500/15 text-blue-600 border-blue-300" },
    done:      { label: "완료",     icon: <CheckCircle2 className="h-3 w-3" />, cls: "bg-green-500/15 text-green-600 border-green-300" },
    failed:    { label: "실패",     icon: <XCircle className="h-3 w-3" />, cls: "bg-red-500/15 text-red-600 border-red-300" },
    cancelled: { label: "취소",     icon: <XCircle className="h-3 w-3" />, cls: "bg-muted text-muted-foreground border-border" },
  };
  const c = cfg[status] ?? cfg.pending;
  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border whitespace-nowrap", c.cls)}>
      {c.icon}{c.label}
    </span>
  );
}

// ── Preview Modal ─────────────────────────────────────────────────────────

function PreviewModal({ jobId, file, open, onClose }: {
  jobId: string; file: OutputFile | null; open: boolean; onClose: () => void;
}) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!open || !file) return;
    setLoading(true);
    fetch(`/api/ptmquant/jobs/${jobId}/preview/${encodeURIComponent(file.path)}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("ptm-token") || ""}` },
    }).then(r => r.text()).then(t => { setContent(t); setLoading(false); })
      .catch(() => { setContent("파일을 불러올 수 없습니다."); setLoading(false); });
  }, [open, file, jobId]);
  const rows = content.split("\n").map(r => r.split("\t"));
  const headers = rows[0] ?? [];
  const bodyRows = rows.slice(1);

  const prettyJson = (() => {
    if (!file?.is_json || !content) return null;
    try { return JSON.stringify(JSON.parse(content), null, 2); } catch { return content; }
  })();

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-5xl max-h-[85vh] flex flex-col">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><FileText className="h-4 w-4" />{file?.name}</DialogTitle></DialogHeader>
        <div className="flex-1 overflow-auto">
          {loading ? <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
            : file?.is_tsv && headers.length > 0 ? (
              <div className="overflow-auto rounded border text-xs">
                <table className="w-full border-collapse">
                  <thead className="sticky top-0 bg-muted"><tr>{headers.map((h, i) => <th key={i} className="px-2 py-1 text-left font-medium border-b whitespace-nowrap">{h}</th>)}</tr></thead>
                  <tbody>{bodyRows.filter(r => r.join("").trim()).map((row, ri) => (
                    <tr key={ri} className={ri % 2 === 0 ? "" : "bg-muted/30"}>
                      {row.map((cell, ci) => <td key={ci} className="px-2 py-0.5 border-b border-border/30 max-w-[200px] truncate">{cell}</td>)}
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : prettyJson !== null ? (
              <pre className="text-xs font-mono bg-zinc-950 text-green-300 rounded p-3 overflow-auto whitespace-pre-wrap">{prettyJson}</pre>
            ) : <pre className="text-xs font-mono bg-muted/40 rounded p-3 overflow-auto whitespace-pre-wrap">{content}</pre>}
        </div>
        <div className="flex justify-end gap-2 pt-2 border-t">
          <a href={`/api/ptmquant/jobs/${jobId}/files/${encodeURIComponent(file?.path ?? "")}`} download={file?.name}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90">
            <Download className="h-3.5 w-3.5" /> 다운로드
          </a>
          <Button variant="outline" size="sm" onClick={onClose}>닫기</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── mzML Directory Browser ─────────────────────────────────────────────────

function MzmlBrowser({ selected, onChange, onDirectoryEnter }: {
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  onDirectoryEnter?: (dirName: string) => void;
}) {
  const [currentPath, setCurrentPath] = useState("");
  const [dirs, setDirs] = useState<DirEntry[]>([]);
  const [mzmls, setMzmls] = useState<MzmlFile[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (path: string) => {
    setLoading(true);
    try {
      const res = await api.get<FilesResponse>(`/ptmquant/files?path=${encodeURIComponent(path)}`);
      setCurrentPath(res.current_path);
      setDirs(res.dirs);
      setMzmls(res.mzml);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(""); }, [load]);

  const breadcrumbs = currentPath ? currentPath.split("/") : [];
  const allSelected = mzmls.length > 0 && mzmls.every(f => selected.has(f.path));

  const toggleFile = (path: string) => {
    const next = new Set(selected);
    next.has(path) ? next.delete(path) : next.add(path);
    onChange(next);
  };

  const toggleAll = () => {
    const next = new Set(selected);
    if (allSelected) mzmls.forEach(f => next.delete(f.path));
    else mzmls.forEach(f => next.add(f.path));
    onChange(next);
  };

  const navigate = (path: string, dirName?: string) => {
    load(path);
    if (dirName && onDirectoryEnter) onDirectoryEnter(dirName);
  };

  // Count selected files in current dir
  const selectedHere = mzmls.filter(f => selected.has(f.path)).length;

  return (
    <div className="border rounded-lg overflow-hidden">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 px-3 py-2 bg-muted/30 border-b text-xs">
        <button onClick={() => navigate("", "")} className="flex items-center gap-1 hover:text-primary transition-colors">
          <Home className="h-3 w-3" /> file_share
        </button>
        {breadcrumbs.map((part, i) => {
          const partPath = breadcrumbs.slice(0, i + 1).join("/");
          return (
            <span key={i} className="flex items-center gap-1">
              <BreadcrumbSep className="h-3 w-3 text-muted-foreground" />
              <button onClick={() => navigate(partPath, part)} className="hover:text-primary transition-colors">{part}</button>
            </span>
          );
        })}
        {loading && <Loader2 className="h-3 w-3 animate-spin ml-auto text-muted-foreground" />}
        {selectedHere > 0 && (
          <span className="ml-auto text-primary font-medium">{selectedHere}/{mzmls.length} 선택</span>
        )}
      </div>

      {/* Contents */}
      <div className="max-h-52 overflow-y-auto">
        {/* Select all header */}
        {mzmls.length > 0 && (
          <div
            className="flex items-center gap-2 px-3 py-1.5 border-b bg-muted/10 cursor-pointer hover:bg-muted/30 text-xs"
            onClick={toggleAll}
          >
            <input type="checkbox" checked={allSelected} readOnly className="rounded" />
            <span className="font-medium">전체 선택 ({mzmls.length}개)</span>
          </div>
        )}

        {/* Directories */}
        {dirs.map(d => (
          <div key={d.path}
            className="flex items-center gap-2 px-3 py-2 border-b last:border-0 hover:bg-muted/30 cursor-pointer text-sm"
            onClick={() => navigate(d.path, d.name)}
          >
            <Folder className="h-4 w-4 text-amber-500 shrink-0" />
            <span className="flex-1">{d.name}</span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          </div>
        ))}

        {/* mzML files */}
        {mzmls.map(f => (
          <div key={f.path}
            className={cn(
              "flex items-center gap-2 px-3 py-2 border-b last:border-0 cursor-pointer text-sm",
              selected.has(f.path) ? "bg-primary/5" : "hover:bg-muted/30"
            )}
            onClick={() => toggleFile(f.path)}
          >
            <input type="checkbox" checked={selected.has(f.path)} readOnly className="rounded shrink-0" />
            <FileText className="h-4 w-4 text-blue-500 shrink-0" />
            <span className="flex-1 truncate font-mono text-xs">{f.name}</span>
            <span className="text-muted-foreground text-xs shrink-0">{formatBytes(f.size)}</span>
          </div>
        ))}

        {!loading && dirs.length === 0 && mzmls.length === 0 && (
          <div className="py-6 text-center text-sm text-muted-foreground">이 폴더에 파일이 없습니다</div>
        )}
      </div>
    </div>
  );
}

// ── Create Job Dialog ──────────────────────────────────────────────────────

function CreateJobDialog({ open, onClose, onCreated, passes: passDefs, fastaFiles, defaultMemory, defaultThreads }: {
  open: boolean;
  onClose: () => void;
  onCreated: (job: Job) => void;
  passes: PassDef[];
  fastaFiles: FastaFile[];
  defaultMemory: number;
  defaultThreads: number;
}) {
  const [selectedMzml,   setSelectedMzml]   = useState<Set<string>>(new Set());
  const [selectedFasta,  setSelectedFasta]  = useState("");
  const [selectedPasses, setSelectedPasses] = useState<Set<string>>(new Set(["phospho"]));
  const [outputSubdir,   setOutputSubdir]   = useState("");
  const [jobName,        setJobName]        = useState("");
  const [threads,        setThreads]        = useState(defaultThreads);
  const [maxMemoryGb,    setMaxMemoryGb]    = useState(defaultMemory);
  const [resume,         setResume]         = useState(false);
  const [error,          setError]          = useState("");
  const [submitting,     setSubmitting]     = useState(false);
  // Track last auto-filled values to detect user edits
  const autoFilledRef = useRef<{ name: string; subdir: string }>({ name: "", subdir: "" });

  // Reset on open
  useEffect(() => {
    if (open) {
      setSelectedMzml(new Set());
      setSelectedFasta("");
      setSelectedPasses(new Set(["phospho"]));
      setOutputSubdir("");
      setJobName("");
      setThreads(defaultThreads);
      setMaxMemoryGb(defaultMemory);
      setResume(false);
      setError("");
      autoFilledRef.current = { name: "", subdir: "" };
    }
  }, [open, defaultMemory, defaultThreads]);

  const togglePass = (id: string) => {
    setSelectedPasses(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleSubmit = async () => {
    if (selectedMzml.size === 0)   return setError("mzML 파일을 하나 이상 선택하세요.");
    if (!selectedFasta)            return setError("Reference FASTA를 선택하세요.");
    if (selectedPasses.size === 0) return setError("PTM 분석 타입을 선택하세요.");
    if (!outputSubdir.trim())      return setError("출력 폴더 이름을 입력하세요.");
    if (!jobName.trim())           return setError("작업 이름을 입력하세요.");
    if (!/^[a-zA-Z0-9_\-]+$/.test(outputSubdir.trim()))
      return setError("출력 폴더 이름은 영문, 숫자, _, -만 사용 가능합니다.");
    setError(""); setSubmitting(true);
    try {
      const job = await api.post<Job>("/ptmquant/jobs", {
        name: jobName.trim(),
        reference_file: selectedFasta,
        input_files: Array.from(selectedMzml),
        passes: Array.from(selectedPasses),
        output_subdir: outputSubdir.trim(),
        threads, max_memory_gb: maxMemoryGb, resume,
      });
      onCreated(job);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "작업 생성 실패");
    } finally { setSubmitting(false); }
  };

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-primary" /> 새 PTMQuant 작업 만들기
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-5 pr-1">
          {/* Job Name */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">작업 이름</Label>
            <Input value={jobName} onChange={e => setJobName(e.target.value)} placeholder="예: Mouse_phospho_run1" />
          </div>

          {/* mzML File Browser */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-xs font-medium">mzML 파일 선택</Label>
              {selectedMzml.size > 0 && (
                <span className="text-xs text-primary font-medium">{selectedMzml.size}개 선택됨</span>
              )}
            </div>
            <MzmlBrowser
              selected={selectedMzml}
              onChange={setSelectedMzml}
              onDirectoryEnter={(dirName) => {
                if (!dirName) return;
                const autoName   = dirName;
                const autoSubdir = `${dirName}_result`;
                // Update only if field is empty OR was previously auto-filled (not manually edited)
                setJobName(prev => {
                  if (!prev || prev === autoFilledRef.current.name) { autoFilledRef.current.name = autoName; return autoName; }
                  return prev;
                });
                setOutputSubdir(prev => {
                  if (!prev || prev === autoFilledRef.current.subdir) { autoFilledRef.current.subdir = autoSubdir; return autoSubdir; }
                  return prev;
                });
              }}
            />
          </div>

          {/* Reference FASTA */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">Reference FASTA</Label>
            <div className="grid grid-cols-1 gap-2">
              {fastaFiles.length === 0 ? (
                <p className="text-xs text-muted-foreground">참조 FASTA 파일 없음 (/data/reference/ 확인)</p>
              ) : (
                Object.entries(
                  fastaFiles.reduce<Record<string, FastaFile[]>>((acc, f) => {
                    (acc[f.species] = acc[f.species] || []).push(f);
                    return acc;
                  }, {})
                ).map(([, files]) => files.map(f => (
                  <label key={f.path} className={cn(
                    "flex items-center gap-3 rounded-lg border px-3 py-2 cursor-pointer transition-colors",
                    selectedFasta === f.path ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                  )}>
                    <input type="radio" name="fasta" value={f.path} checked={selectedFasta === f.path}
                      onChange={() => setSelectedFasta(f.path)} className="shrink-0" />
                    <div>
                      <p className="text-sm font-medium">{f.label}</p>
                      <p className="text-xs text-muted-foreground font-mono">{f.name} · {formatBytes(f.size)}</p>
                    </div>
                  </label>
                )))
              )}
            </div>
          </div>

          {/* PTM Passes */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">PTM 분석 타입</Label>
            <div className="grid grid-cols-1 gap-1.5">
              {passDefs.map(p => (
                <label key={p.id} className={cn(
                  "flex items-center gap-3 rounded-lg border px-3 py-2 cursor-pointer transition-colors text-sm",
                  selectedPasses.has(p.id) ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                )}>
                  <input type="checkbox" checked={selectedPasses.has(p.id)} onChange={() => togglePass(p.id)} className="rounded shrink-0" />
                  <div>
                    <span className="font-medium">{p.label}</span>
                    <span className="ml-2 text-xs text-muted-foreground">{p.description}</span>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Output folder */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium">출력 폴더 이름 <span className="text-muted-foreground font-normal">(file_share 내)</span></Label>
            <Input value={outputSubdir} onChange={e => setOutputSubdir(e.target.value)} placeholder="예: mouse_phospho_results" />
          </div>

          <Separator />

          {/* Advanced */}
          <div className="grid grid-cols-2 gap-4">
            {/* CPU Threads */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-medium">CPU 스레드</Label>
                <span className="text-xs font-mono font-semibold">{threads === 0 ? "전체 코어" : `${threads} 스레드`}</span>
              </div>
              <input type="range" min={0} max={16} step={1} value={threads}
                onChange={e => setThreads(Number(e.target.value))}
                className="w-full h-1.5 accent-primary cursor-pointer" />
            </div>
            {/* Max Memory */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-medium">최대 메모리</Label>
                <span className={cn("text-xs font-mono font-semibold px-1.5 py-0.5 rounded",
                  maxMemoryGb < 24 ? "bg-red-500/15 text-red-600" : maxMemoryGb < 32 ? "bg-yellow-500/15 text-yellow-600" : "bg-green-500/15 text-green-600"
                )}>{maxMemoryGb} GB</span>
              </div>
              <input type="range" min={8} max={96} step={4} value={maxMemoryGb}
                onChange={e => setMaxMemoryGb(Number(e.target.value))}
                className="w-full h-1.5 accent-primary cursor-pointer" />
              <p className="text-[10px] text-muted-foreground">Phospho 패스는 32 GB 이상 권장</p>
            </div>
          </div>

          {/* Resume */}
          <label className={cn(
            "flex items-center gap-3 rounded-lg border px-3 py-2 cursor-pointer transition-colors",
            resume ? "border-amber-400 bg-amber-500/5" : "hover:bg-muted/40"
          )}>
            <input type="checkbox" checked={resume} onChange={e => setResume(e.target.checked)} className="rounded shrink-0" />
            <div>
              <p className="text-sm font-medium">이어서 실행 (Resume)</p>
              <p className="text-xs text-muted-foreground">이미 완료된 패스의 Sage 결과를 재사용합니다</p>
            </div>
          </label>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter className="pt-3 border-t">
          <Button variant="outline" onClick={onClose} disabled={submitting}>취소</Button>
          <Button onClick={handleSubmit} disabled={submitting} className="gap-1.5">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
            {submitting ? "생성 중..." : "작업 시작"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Expanded Job Detail Row ────────────────────────────────────────────────

function JobDetail({ job, onRefresh }: { job: Job; onRefresh: (id: string) => void }) {
  const [log, setLog] = useState<string[]>([]);
  const [fileStatus, setFileStatus] = useState("");
  const [outputFiles, setOutputFiles] = useState<OutputFile[]>([]);
  const [outputLoading, setOutputLoading] = useState(false);
  const [previewFile, setPreviewFile] = useState<OutputFile | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const isActive = job.status === "pending" || job.status === "running";

  // SSE for active jobs
  useEffect(() => {
    if (!isActive) return;
    const token = localStorage.getItem("ptm-token") || "";
    const es = new EventSource(`/api/events/ptmquant/${job.job_id}?token=${token}`);
    es.addEventListener("progress", (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.message) setLog(prev => [...prev, d.message]);
        if (d.file_status) setFileStatus(d.file_status);
        if (d.type === "done" || d.type === "error") { onRefresh(job.job_id); es.close(); }
      } catch { /* ignore */ }
    });
    return () => { es.close(); };
  }, [isActive, job.job_id, onRefresh]);

  // Load output files (done or failed — might have partial results)
  useEffect(() => {
    if (isActive) return;
    setOutputLoading(true);
    api.get<OutputFile[]>(`/ptmquant/jobs/${job.job_id}/files`)
      .then(r => setOutputFiles(Array.isArray(r) ? r : []))
      .catch(() => {})
      .finally(() => setOutputLoading(false));
  }, [isActive, job.job_id]);

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  return (
    <div className="px-4 py-3 space-y-3 border-t border-border/40">
      {/* Job meta summary */}
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <span><span className="font-medium text-foreground">출력 폴더:</span> {job.output_subdir ?? "—"}</span>
        <span><span className="font-medium text-foreground">파일 수:</span> {job.input_files?.length ?? 0}개</span>
        <span><span className="font-medium text-foreground">패스:</span> {job.passes?.join(", ") ?? "—"}</span>
        <span><span className="font-medium text-foreground">Reference:</span> {job.reference_file ?? "—"}</span>
      </div>

      {/* Progress bar (active) */}
      {isActive && (
        <div className="space-y-1">
          {job.status === "pending" ? (
            <div className="relative h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="absolute inset-y-0 w-1/3 rounded-full bg-yellow-400 animate-slide" />
            </div>
          ) : (
            <Progress value={job.progress} className="h-1.5" />
          )}
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{job.status === "pending" ? "대기 중..." : fileStatus || `${job.progress.toFixed(0)}% 처리 중`}</span>
            <span>{job.progress.toFixed(0)}%</span>
          </div>
        </div>
      )}

      {/* Error message */}
      {job.status === "failed" && job.error_message && (
        <div className="text-xs text-red-600 bg-red-50 dark:bg-red-950/20 rounded border border-red-200 px-3 py-2 font-mono whitespace-pre-wrap">
          {job.error_message}
        </div>
      )}

      {/* Live log (SSE) */}
      {log.length > 0 && (
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-1">실시간 로그</p>
          <div ref={logRef} className="h-40 overflow-y-auto bg-zinc-950 rounded px-3 py-2 text-xs text-green-400 font-mono space-y-0.5">
            {log.map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </div>
      )}

      {/* Output files */}
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-1">출력 파일</p>
        {outputLoading ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> 파일 목록 로딩 중...
          </div>
        ) : outputFiles.length === 0 ? (
          <p className="text-xs text-muted-foreground py-1">
            {isActive ? "작업 완료 후 파일이 여기 표시됩니다." : "출력 파일이 없습니다."}
          </p>
        ) : (
              <div className="grid grid-cols-1 gap-1">
            {outputFiles.map(f => (
              <div key={f.path} className={cn(
                "flex items-center justify-between gap-2 rounded px-2 py-1.5 text-xs",
                f.is_matrix ? "bg-primary/5 border border-primary/20" : "bg-muted/40"
              )}>
                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                  <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                  <span className="truncate font-mono">{f.name}</span>
                  {f.is_matrix && <Badge variant="outline" className="text-[10px] py-0 px-1">matrix</Badge>}
                  <span className="text-muted-foreground shrink-0">{formatBytes(f.size)}</span>
                </div>
                {f.modified_at && (
                  <span className="text-muted-foreground shrink-0 tabular-nums">
                    {new Intl.DateTimeFormat("ko-KR", {
                      timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit",
                      hour: "2-digit", minute: "2-digit", hour12: false,
                    }).format(new Date(f.modified_at * 1000))}
                  </span>
                )}
                <div className="flex gap-1 shrink-0">
                  {(f.is_tsv || f.is_json) && (
                    <Button variant="ghost" size="icon" className="h-6 w-6" title="미리보기"
                      onClick={() => { setPreviewFile(f); setPreviewOpen(true); }}>
                      <Eye className="h-3 w-3" />
                    </Button>
                  )}
                  <a href={`/api/ptmquant/jobs/${job.job_id}/files/${encodeURIComponent(f.path)}`} download={f.name}
                    className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-accent" title="다운로드">
                    <Download className="h-3 w-3" />
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <PreviewModal jobId={job.job_id} file={previewFile} open={previewOpen} onClose={() => setPreviewOpen(false)} />
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function PTMQuant() {
  const [passes,     setPasses]     = useState<PassDef[]>([]);
  const [fastaFiles, setFastaFiles] = useState<FastaFile[]>([]);
  const [jobs,       setJobs]       = useState<Job[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [defaultMemory,  setDefaultMemory]  = useState(32);
  const [defaultThreads, setDefaultThreads] = useState(4);

  // Live elapsed ticker — updates every second for active jobs
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === "pending" || j.status === "running");
    if (!hasActive) return;
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, [jobs]);

  // Load system settings defaults
  useEffect(() => {
    api.get<{ settings: { key: string; value: string }[] }>("/settings/system")
      .then(res => {
        const map = Object.fromEntries(res.settings.map(s => [s.key, s.value]));
        if (map["PTMQUANT_DEFAULT_MEMORY_GB"]) { const v = parseInt(map["PTMQUANT_DEFAULT_MEMORY_GB"], 10); if (!isNaN(v)) setDefaultMemory(v); }
        if (map["PTMQUANT_DEFAULT_THREADS"])   { const v = parseInt(map["PTMQUANT_DEFAULT_THREADS"], 10);   if (!isNaN(v)) setDefaultThreads(v); }
      }).catch(() => {});
  }, []);

  const fetchAll = useCallback(async () => {
    try {
      const [filesData, passesData, jobsData] = await Promise.all([
        api.get<FilesResponse>("/ptmquant/files"),
        api.get<PassDef[]>("/ptmquant/passes"),
        api.get<Job[]>("/ptmquant/jobs"),
      ]);
      setFastaFiles(filesData.fasta);
      setPasses(passesData);
      setJobs(jobsData);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Poll active jobs every 5s
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === "pending" || j.status === "running");
    if (!hasActive) return;
    const id = setInterval(() => {
      api.get<Job[]>("/ptmquant/jobs").then(setJobs).catch(() => {});
    }, 5000);
    return () => clearInterval(id);
  }, [jobs]);

  const refreshJob = useCallback(async (jobId: string) => {
    try {
      const updated = await api.get<Job>(`/ptmquant/jobs/${jobId}`);
      setJobs(prev => prev.map(j => j.job_id === jobId ? updated : j));
    } catch { /* ignore */ }
  }, []);

  const deleteJob = useCallback(async (jobId: string) => {
    if (!confirm("이 작업을 삭제하시겠습니까?")) return;
    try {
      await api.delete(`/ptmquant/jobs/${jobId}`);
      setJobs(prev => prev.filter(j => j.job_id !== jobId));
      if (expandedId === jobId) setExpandedId(null);
    } catch (e: unknown) { alert(e instanceof Error ? e.message : "삭제 실패"); }
  }, [expandedId]);

  const cancelJob = useCallback(async (jobId: string) => {
    if (!confirm("실행 중인 작업을 중단하시겠습니까?")) return;
    try {
      await api.post(`/ptmquant/jobs/${jobId}/cancel`, {});
      await refreshJob(jobId);
    } catch (e: unknown) { alert(e instanceof Error ? e.message : "중단 실패"); }
  }, [refreshJob]);

  const handleCreated = (job: Job) => {
    setJobs(prev => [job, ...prev]);
    setExpandedId(job.job_id);
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FlaskConical className="h-6 w-6 text-primary" /> PTMQuant 변환 작업
          </h1>
          <p className="text-muted-foreground text-sm mt-1">MzML → PTM 정량 행렬 (pg/pr matrix) 변환 파이프라인</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchAll} className="gap-1.5">
            <RefreshCw className="h-3.5 w-3.5" /> 새로고침
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)} className="gap-1.5">
            <PlusCircle className="h-4 w-4" /> 새 작업 만들기
          </Button>
        </div>
      </div>

      {/* Job Table */}
      {jobs.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <FlaskConical className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-muted-foreground">아직 작업이 없습니다.</p>
            <Button className="mt-4 gap-1.5" onClick={() => setShowCreate(true)}>
              <PlusCircle className="h-4 w-4" /> 첫 번째 작업 만들기
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 hover:bg-muted/40">
                <TableHead className="w-8"></TableHead>
                <TableHead>작업 이름</TableHead>
                <TableHead>Reference</TableHead>
                <TableHead>패스</TableHead>
                <TableHead className="text-center">파일</TableHead>
                <TableHead className="w-36">진행률</TableHead>
                <TableHead>상태</TableHead>
                <TableHead className="text-right font-mono">소요시간</TableHead>
                <TableHead>생성일</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.map(job => {
                const isExpanded = expandedId === job.job_id;
                const isActive = job.status === "pending" || job.status === "running";
                const species = job.reference_file?.split("/")?.[0] ?? "—";
                return (
                  <Fragment key={job.job_id}>
                    <TableRow
                      className={cn("cursor-pointer", isExpanded && "bg-muted/20", isActive && "bg-blue-50/30 dark:bg-blue-950/10")}
                      onClick={() => setExpandedId(isExpanded ? null : job.job_id)}
                    >
                      <TableCell className="py-2">
                        {isExpanded
                          ? <ChevronDown className="h-4 w-4 text-muted-foreground" />
                          : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                      </TableCell>
                      <TableCell className="py-2 font-medium max-w-[160px] truncate">{job.name}</TableCell>
                      <TableCell className="py-2 text-sm capitalize text-muted-foreground">{species}</TableCell>
                      <TableCell className="py-2">
                        <div className="flex flex-wrap gap-1">
                          {job.passes?.map(p => (
                            <Badge key={p} variant="secondary" className="text-[10px] py-0 px-1.5">{p}</Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="py-2 text-center text-sm">{job.input_files?.length ?? 0}</TableCell>
                      <TableCell className="py-2">
                        {isActive ? (
                          job.status === "pending" ? (
                            <div className="relative h-1.5 overflow-hidden rounded-full bg-muted w-full">
                              <div className="absolute inset-y-0 w-1/3 rounded-full bg-yellow-400 animate-slide" />
                            </div>
                          ) : (
                            <div className="space-y-0.5">
                              <Progress value={job.progress} className="h-1.5" />
                              <p className="text-[10px] text-muted-foreground text-right">{job.progress.toFixed(0)}%</p>
                            </div>
                          )
                        ) : job.status === "done" ? (
                          <Progress value={100} className="h-1.5" />
                        ) : null}
                      </TableCell>
                      <TableCell className="py-2"><StatusBadge status={job.status} /></TableCell>
                      <TableCell className="py-2 text-right font-mono text-sm tabular-nums text-muted-foreground" onClick={e => e.stopPropagation()}>
                        {/* tick dependency forces re-render every second for live timer */}
                        {tick >= 0 && fmtElapsed(job.created_at, job.updated_at, job.status)}
                      </TableCell>
                      <TableCell className="py-2 text-xs text-muted-foreground whitespace-nowrap">{fmtDate(job.created_at)}</TableCell>
                      <TableCell className="py-2" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center gap-1 justify-end">
                          {isActive && (
                            <Button variant="ghost" size="icon" className="h-7 w-7 text-orange-500 hover:text-orange-600"
                              onClick={() => cancelJob(job.job_id)} title="중단">
                              <StopCircle className="h-3.5 w-3.5" />
                            </Button>
                          )}
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                            onClick={() => deleteJob(job.job_id)} disabled={isActive} title="삭제">
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>

                    {/* Expanded Detail */}
                    {isExpanded && (
                      <TableRow className="bg-muted/5 hover:bg-muted/5">
                        <TableCell colSpan={10} className="p-0">
                          <JobDetail job={job} onRefresh={refreshJob} />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}

      {/* Create Dialog */}
      <CreateJobDialog
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={handleCreated}
        passes={passes}
        fastaFiles={fastaFiles}
        defaultMemory={defaultMemory}
        defaultThreads={defaultThreads}
      />
    </div>
  );
}
