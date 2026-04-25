import { useState, useEffect, useCallback, useRef } from "react";
import {
  Settings as SettingsIcon, Monitor, Save, Mail, Shield, Zap,
  Webhook, Server, Loader2, CheckCircle2, AlertTriangle,
  FolderOpen, Upload, Download, Trash2, FileIcon, X, CheckSquare, Square, CheckCircle2 as CheckCircleIcon,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "ptm-settings";

export interface PtmSettings {
  resourceMonitorInterval: number;
}

export function loadSettings(): PtmSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...defaultSettings(), ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return defaultSettings();
}

function defaultSettings(): PtmSettings {
  return { resourceMonitorInterval: 30 };
}

function saveSettings(s: PtmSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  window.dispatchEvent(new CustomEvent("ptm-settings-changed", { detail: s }));
}

interface SystemSetting {
  key: string;
  value: string;
  description: string | null;
  category: string | null;
  value_type: string | null;
  updated_at: string | null;
}

const CATEGORY_CONFIG: Record<string, { label: string; icon: typeof Shield; description: string }> = {
  watchdog: {
    label: "Watchdog (분석 멈춤 감지)",
    icon: Shield,
    description: "분석이 멈추거나 중단되었을 때 자동으로 감지하고 알림을 보냅니다.",
  },
  performance: {
    label: "Performance (LLM 성능)",
    icon: Zap,
    description: "LLM 호출의 동시성과 타임아웃을 조절합니다.",
  },
  integration: {
    label: "Integration (외부 연동)",
    icon: Webhook,
    description: "Webhook 등 외부 서비스와의 연동을 설정합니다.",
  },
  worker: {
    label: "Worker Concurrency (워커 동시성)",
    icon: Server,
    description: "각 파이프라인 워커의 동시 처리 수입니다. 변경 후 서비스 재시작이 필요합니다.",
  },
};

const SETTING_LABELS: Record<string, string> = {
  WATCHDOG_CHECK_INTERVAL_SECONDS: "점검 주기 (초)",
  WATCHDOG_NO_TASK_STALL_MINUTES: "Task 없음 감지 (분)",
  WATCHDOG_NO_PROGRESS_STALL_MINUTES: "진행 없음 감지 (분)",
  WATCHDOG_ALERT_COOLDOWN_MINUTES: "알림 쿨다운 (분)",
  WATCHDOG_MAX_RESTARTS: "최대 자동 재시작 횟수",
  WATCHDOG_AUTO_RESTART: "자동 재시작 활성화",
  REPORT_LLM_WORKERS: "동시 LLM 호출 수",
  OLLAMA_TIMEOUT: "Ollama 타임아웃 (초)",
  WEBHOOK_URL: "Webhook URL",
  PREPROCESSING_CONCURRENCY: "Preprocessing 워커",
  RAG_ENRICHMENT_CONCURRENCY: "RAG Enrichment 워커",
  REPORT_GENERATION_CONCURRENCY: "Report Generation 워커",
};

const SETTING_DESCRIPTIONS: Record<string, string> = {
  WATCHDOG_CHECK_INTERVAL_SECONDS: "분석 상태를 자동 점검하는 주기 (초)",
  WATCHDOG_NO_TASK_STALL_MINUTES: "Celery 작업이 없을 때 멈춤으로 판단하는 시간 (분)",
  WATCHDOG_NO_PROGRESS_STALL_MINUTES: "진행 없음 감지 임계값 (분, LLM 호출 시간 고려)",
  WATCHDOG_ALERT_COOLDOWN_MINUTES: "동일 오더에 대한 반복 알림 쿨다운 (분)",
  WATCHDOG_MAX_RESTARTS: "멈춤 감지 시 자동 재시작의 최대 횟수",
  WATCHDOG_AUTO_RESTART: "멈춤 감지 시 자동으로 재시작할지 여부",
  REPORT_LLM_WORKERS: "Report 생성 시 동시에 수행하는 LLM 호출 수",
  OLLAMA_TIMEOUT: "Ollama LLM 요청 타임아웃 (초)",
  WEBHOOK_URL: "분석 이벤트를 전송할 Webhook URL",
  PREPROCESSING_CONCURRENCY: "Preprocessing 워커의 동시 처리 수 (재시작 필요)",
  RAG_ENRICHMENT_CONCURRENCY: "RAG Enrichment 워커의 동시 처리 수 (재시작 필요)",
  REPORT_GENERATION_CONCURRENCY: "Report Generation 워커의 동시 처리 수 (재시작 필요)",
  ENABLE_RQ_REFINEMENT: "리포트 생성 시 분석 결과를 기반으로 Research Question을 자동 구체화",
  ENABLE_REPORT_COPILOT: "리포트 초안을 AI가 검토하여 누락/보완점을 자동 식별",
};

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full",
        "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-primary" : "bg-muted",
      )}
    >
      <span
        className={cn(
          "pointer-events-none block h-5 w-5 rounded-full bg-background shadow-lg ring-0 transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}

interface SharedFile {
  name: string;
  size: number;
  modified_at: number;
  mime_type: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

const CHUNK_SIZE = 10 * 1024 * 1024; // 10 MB per chunk
const UPLOADS_LS_KEY = "ptm-file-uploads";

interface SavedUpload {
  uploadId: string;
  fileName: string;
  totalSize: number;
  totalChunks: number;
  uploadedChunks: number;
  startedAt: number;
}

interface UploadEntry {
  name: string;
  pct: number;
  finalizing: boolean;
  uploadId: string;
  uploadedChunks: number;
  totalChunks: number;
}

function lsGetUploads(): Record<string, SavedUpload> {
  try { return JSON.parse(localStorage.getItem(UPLOADS_LS_KEY) || "{}"); } catch { return {}; }
}
function lsSaveUpload(u: SavedUpload) {
  const all = lsGetUploads();
  all[u.uploadId] = u;
  localStorage.setItem(UPLOADS_LS_KEY, JSON.stringify(all));
}
function lsRemoveUpload(uploadId: string) {
  const all = lsGetUploads();
  delete all[uploadId];
  localStorage.setItem(UPLOADS_LS_KEY, JSON.stringify(all));
}

export default function Settings() {
  const { user, updateUser } = useAuth();
  const [localSettings, setLocalSettings] = useState<PtmSettings>(loadSettings);
  const [localSaved, setLocalSaved] = useState(false);
  const [emailEnabled, setEmailEnabled] = useState(user?.email_notifications_enabled ?? true);
  const [emailSaving, setEmailSaving] = useState(false);

  // System settings
  const [sysSettings, setSysSettings] = useState<SystemSetting[]>([]);
  const [sysEdits, setSysEdits] = useState<Record<string, string>>({});
  const [sysLoading, setSysLoading] = useState(true);
  const [sysSaving, setSysSaving] = useState(false);
  const [sysSaved, setSysSaved] = useState(false);
  const [sysError, setSysError] = useState<string | null>(null);

  // File share
  const [sharedFiles, setSharedFiles] = useState<SharedFile[]>([]);
  const [fileShareLoading, setFileShareLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<Record<string, UploadEntry>>({});
  const [pendingResumes, setPendingResumes] = useState<SavedUpload[]>([]);
  const [fileShareError, setFileShareError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const resumeFileInputRef = useRef<HTMLInputElement>(null);
  const resumeTargetRef = useRef<string | null>(null);
  // key → current chunk XHR (취소용)
  const xhrMapRef = useRef<Record<string, XMLHttpRequest>>({});
  // keys that have been cancelled — upload loop checks this
  const cancelledRef = useRef<Set<string>>(new Set());

  // ── Download state ─────────────────────────────────────────────
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [downloadProgress, setDownloadProgress] = useState<Record<string, {
    name: string; pct: number; received: number; total: number; done: boolean; error: string | null;
  }>>({});
  const downloadAbortMapRef = useRef<Record<string, AbortController>>({});

  useEffect(() => {
    setEmailEnabled(user?.email_notifications_enabled ?? true);
  }, [user?.email_notifications_enabled]);

  const fetchSystemSettings = useCallback(async () => {
    setSysLoading(true);
    setSysError(null);
    try {
      const res = await api.get<{ settings: SystemSetting[] }>("/settings/system");
      setSysSettings(res.settings);
      const edits: Record<string, string> = {};
      for (const s of res.settings) edits[s.key] = s.value;
      setSysEdits(edits);
    } catch (e) {
      setSysError("시스템 설정을 불러올 수 없습니다.");
    } finally {
      setSysLoading(false);
    }
  }, []);

  useEffect(() => { fetchSystemSettings(); }, [fetchSystemSettings]);

  const handleLocalSave = () => {
    const interval = Math.max(5, localSettings.resourceMonitorInterval);
    const updated = { ...localSettings, resourceMonitorInterval: interval };
    setLocalSettings(updated);
    saveSettings(updated);
    setLocalSaved(true);
    setTimeout(() => setLocalSaved(false), 2000);
  };

  const handleEmailToggle = async (enabled: boolean) => {
    setEmailSaving(true);
    try {
      const data = await api.patch<{ email_notifications_enabled: boolean }>(
        "/settings/email-notifications",
        { email_notifications_enabled: enabled }
      );
      setEmailEnabled(data.email_notifications_enabled);
      updateUser({ ...user!, email_notifications_enabled: data.email_notifications_enabled });
    } catch {
      setEmailEnabled(!enabled);
    } finally {
      setEmailSaving(false);
    }
  };

  const handleSysEdit = (key: string, value: string) => {
    setSysEdits((prev) => ({ ...prev, [key]: value }));
    setSysSaved(false);
  };

  const hasSysChanges = sysSettings.some((s) => sysEdits[s.key] !== s.value);

  const handleSysSave = async () => {
    const changed: Record<string, string> = {};
    for (const s of sysSettings) {
      if (sysEdits[s.key] !== s.value) changed[s.key] = sysEdits[s.key];
    }
    if (Object.keys(changed).length === 0) return;

    setSysSaving(true);
    try {
      const res = await api.patch<{ settings: SystemSetting[]; updated: string[] }>(
        "/settings/system",
        { settings: changed }
      );
      setSysSettings(res.settings);
      const edits: Record<string, string> = {};
      for (const s of res.settings) edits[s.key] = s.value;
      setSysEdits(edits);
      setSysSaved(true);
      setTimeout(() => setSysSaved(false), 3000);
    } catch {
      setSysError("설정 저장에 실패했습니다.");
    } finally {
      setSysSaving(false);
    }
  };

  const grouped = sysSettings.reduce<Record<string, SystemSetting[]>>((acc, s) => {
    const cat = s.category || "general";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(s);
    return acc;
  }, {});

  const categoryOrder = ["watchdog", "performance", "integration", "worker"];

  const isAdmin = user?.role === "admin";

  // ── File Share handlers ──────────────────────────────────────────────
  const fetchSharedFiles = useCallback(async () => {
    if (!isAdmin) return;
    setFileShareLoading(true);
    setFileShareError(null);
    try {
      const res = await api.get<{ files: SharedFile[] }>("/settings/files");
      setSharedFiles(res.files);
    } catch {
      setFileShareError("파일 목록을 불러올 수 없습니다.");
    } finally {
      setFileShareLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => { fetchSharedFiles(); }, [fetchSharedFiles]);

  // On mount: restore pending upload sessions from localStorage
  useEffect(() => {
    if (!isAdmin) return;
    const saved = lsGetUploads();
    const ids = Object.keys(saved);
    if (ids.length === 0) return;

    const token = localStorage.getItem("ptm-token");
    Promise.all(
      ids.map(async (uploadId) => {
        try {
          const res = await fetch(`/api/settings/files/chunks/${uploadId}/status`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          });
          if (!res.ok) { lsRemoveUpload(uploadId); return null; }
          const data = await res.json();
          if (data.status === "done" || data.status === "finalizing") {
            lsRemoveUpload(uploadId); return null;
          }
          // Still uploading on server — offer resume
          return { ...saved[uploadId], uploadedChunks: data.received_chunks } as SavedUpload;
        } catch {
          return null;
        }
      })
    ).then((results) => {
      setPendingResumes(results.filter(Boolean) as SavedUpload[]);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  const uploadFileChunked = useCallback(async (
    file: File,
    key: string,
    uploadId: string,
    startChunk: number,
    totalChunks: number,
  ) => {
    const token = localStorage.getItem("ptm-token");

    try {
      for (let i = startChunk; i < totalChunks; i++) {
        if (cancelledRef.current.has(key)) return;

        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, file.size);
        const blob = file.slice(start, end);
        const formData = new FormData();
        formData.append("chunk", blob, file.name);

        await new Promise<void>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", `/api/settings/files/chunks/${uploadId}/${i}`);
          if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
          xhrMapRef.current[key] = xhr;
          xhr.onload = () => {
            delete xhrMapRef.current[key];
            xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`${xhr.status}`));
          };
          xhr.onerror = () => { delete xhrMapRef.current[key]; reject(new Error("network")); };
          xhr.onabort = () => { delete xhrMapRef.current[key]; reject(new Error("aborted")); };
          xhr.send(formData);
        });

        const uploaded = i + 1;
        const pct = Math.round((uploaded / totalChunks) * 100);
        setUploadProgress((prev) =>
          prev[key] ? { ...prev, [key]: { ...prev[key], pct, uploadedChunks: uploaded } } : prev
        );
        lsSaveUpload({ uploadId, fileName: file.name, totalSize: file.size, totalChunks, uploadedChunks: uploaded, startedAt: Date.now() });
      }

      if (cancelledRef.current.has(key)) return;

      // All chunks uploaded — finalize
      setUploadProgress((prev) =>
        prev[key] ? { ...prev, [key]: { ...prev[key], finalizing: true } } : prev
      );
      const resp = await fetch(`/api/settings/files/chunks/${uploadId}/finalize`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const detail = err.detail;
        const msg = typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => d?.msg || JSON.stringify(d)).join("; ")
            : `HTTP ${resp.status}`;
        throw new Error(msg);
      }
      lsRemoveUpload(uploadId);
      fetchSharedFiles().finally(() => {
        setUploadProgress((prev) => { const n = { ...prev }; delete n[key]; return n; });
        cancelledRef.current.delete(key);
      });
    } catch (err: unknown) {
      if (cancelledRef.current.has(key)) return; // expected abort
      setFileShareError(`'${file.name}' 업로드 실패: ${err instanceof Error ? err.message : err}`);
      setUploadProgress((prev) => { const n = { ...prev }; delete n[key]; return n; });
      cancelledRef.current.delete(key);
    }
  }, [fetchSharedFiles]);

  const uploadFiles = useCallback(async (files: FileList | File[], resumeId?: string, resumeStartChunk?: number) => {
    const arr = Array.from(files);
    const token = localStorage.getItem("ptm-token");

    for (const file of arr) {
      const key = resumeId ?? `${file.name}-${Date.now()}`;
      let uploadId = resumeId ?? "";
      let startChunk = resumeStartChunk ?? 0;
      const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

      if (!resumeId) {
        // Init a new session
        try {
          const res = await fetch("/api/settings/files/chunks/init", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({ filename: file.name, total_size: file.size, total_chunks: totalChunks, chunk_size: CHUNK_SIZE }),
          });
          if (!res.ok) throw new Error(await res.text());
          const data = await res.json();
          uploadId = data.upload_id;
          lsSaveUpload({ uploadId, fileName: file.name, totalSize: file.size, totalChunks, uploadedChunks: 0, startedAt: Date.now() });
        } catch (e) {
          setFileShareError(`'${file.name}' 업로드 초기화 실패`);
          continue;
        }
      }

      const pct = Math.round((startChunk / totalChunks) * 100);
      setUploadProgress((prev) => ({
        ...prev,
        [key]: { name: file.name, pct, finalizing: false, uploadId, uploadedChunks: startChunk, totalChunks },
      }));

      // Remove from pending resumes if resuming
      if (resumeId) {
        setPendingResumes((prev) => prev.filter((r) => r.uploadId !== resumeId));
      }

      await uploadFileChunked(file, key, uploadId, startChunk, totalChunks);
    }
  }, [uploadFileChunked]);

  const handleCancelUpload = useCallback((key: string, uploadId: string) => {
    cancelledRef.current.add(key);
    xhrMapRef.current[key]?.abort();
    lsRemoveUpload(uploadId);
    // Clean up server-side chunks
    const token = localStorage.getItem("ptm-token");
    fetch(`/api/settings/files/chunks/${uploadId}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).catch(() => {});
    setUploadProgress((prev) => { const n = { ...prev }; delete n[key]; return n; });
  }, []);

  const handleCancelPendingResume = useCallback((uploadId: string) => {
    lsRemoveUpload(uploadId);
    setPendingResumes((prev) => prev.filter((r) => r.uploadId !== uploadId));
    const token = localStorage.getItem("ptm-token");
    fetch(`/api/settings/files/chunks/${uploadId}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).catch(() => {});
  }, []);

  const handleResumeClick = useCallback((saved: SavedUpload) => {
    resumeTargetRef.current = saved.uploadId;
    resumeFileInputRef.current?.click();
  }, []);

  const handleResumeFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadId = resumeTargetRef.current;
    if (!uploadId || !e.target.files?.length) return;
    const file = e.target.files[0];
    const saved = lsGetUploads()[uploadId];
    if (!saved) return;
    e.target.value = "";
    resumeTargetRef.current = null;
    uploadFiles([file], uploadId, saved.uploadedChunks);
  }, [uploadFiles]);

  const handleDropZoneDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) uploadFiles(e.dataTransfer.files);
  }, [uploadFiles]);

  const downloadFile = useCallback(async (filename: string) => {
    const authToken = localStorage.getItem("ptm-token");
    const controller = new AbortController();
    downloadAbortMapRef.current[filename] = controller;

    setDownloadProgress((prev) => ({
      ...prev,
      [filename]: { name: filename, pct: 0, received: 0, total: 0, done: false, error: null },
    }));

    try {
      // ── Path A: showSaveFilePicker — stream directly to disk (no memory limit) ──
      if ("showSaveFilePicker" in window) {
        // Must be called synchronously within the user-gesture tick
        let writable: FileSystemWritableFileStream;
        try {
          const handle = await (window as typeof window & {
            showSaveFilePicker: (opts?: { suggestedName?: string }) => Promise<FileSystemFileHandle>;
          }).showSaveFilePicker({ suggestedName: filename });
          writable = await handle.createWritable();
        } catch {
          // User dismissed the Save dialog
          setDownloadProgress((prev) => { const n = { ...prev }; delete n[filename]; return n; });
          delete downloadAbortMapRef.current[filename];
          return;
        }

        let resp: Response;
        try {
          resp = await fetch(`/api/settings/files/${encodeURIComponent(filename)}`, {
            headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
            signal: controller.signal,
          });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        } catch (e) {
          await writable.abort();
          throw e;
        }

        const total = parseInt(resp.headers.get("Content-Length") || "0", 10);
        const reader = resp.body!.getReader();
        let received = 0;

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            await writable.write(value);
            received += value.length;
            const pct = total > 0 ? Math.round((received / total) * 100) : -1;
            setDownloadProgress((prev) =>
              prev[filename] ? { ...prev, [filename]: { ...prev[filename], pct, received, total } } : prev
            );
          }
          await writable.close();
        } catch (e) {
          await writable.abort();
          throw e;
        }

      } else {
        // ── Path B: fallback — temp signed URL → browser native download ──
        setDownloadProgress((prev) =>
          prev[filename] ? { ...prev, [filename]: { ...prev[filename], pct: -1 } } : prev
        );

        const tokenResp = await fetch(
          `/api/settings/files/${encodeURIComponent(filename)}/dl-token`,
          { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} }
        );
        if (!tokenResp.ok) throw new Error(`토큰 발급 실패 (${tokenResp.status})`);
        const { token: dlToken } = await tokenResp.json();

        const dlUrl = `/api/settings/files/${encodeURIComponent(filename)}/dl?token=${encodeURIComponent(dlToken)}`;
        const a = document.createElement("a");
        a.href = dlUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        // Show a brief "started" state — browser download bar takes over
        setDownloadProgress((prev) =>
          prev[filename] ? { ...prev, [filename]: { ...prev[filename], pct: 100, done: true } } : prev
        );
        setTimeout(() => {
          setDownloadProgress((prev) => { const n = { ...prev }; delete n[filename]; return n; });
        }, 3000);
        return;
      }

      // Path A completion
      setDownloadProgress((prev) =>
        prev[filename] ? { ...prev, [filename]: { ...prev[filename], pct: 100, done: true } } : prev
      );
      setTimeout(() => {
        setDownloadProgress((prev) => { const n = { ...prev }; delete n[filename]; return n; });
      }, 4000);
    } catch (err: unknown) {
      if ((err as Error).name === "AbortError") {
        setDownloadProgress((prev) => { const n = { ...prev }; delete n[filename]; return n; });
      } else {
        setDownloadProgress((prev) =>
          prev[filename]
            ? { ...prev, [filename]: { ...prev[filename], error: (err as Error).message } }
            : prev
        );
      }
    } finally {
      delete downloadAbortMapRef.current[filename];
    }
  }, []);

  const handleDownloadSelected = useCallback(() => {
    selectedFiles.forEach((filename) => downloadFile(filename));
    setSelectedFiles(new Set());
  }, [selectedFiles, downloadFile]);

  const handleCancelDownload = useCallback((filename: string) => {
    downloadAbortMapRef.current[filename]?.abort();
  }, []);

  const toggleSelectFile = useCallback((name: string) => {
    setSelectedFiles((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedFiles((prev) =>
      prev.size === sharedFiles.length
        ? new Set()
        : new Set(sharedFiles.map((f) => f.name))
    );
  }, [sharedFiles]);

  const handleDeleteFile = async (filename: string) => {
    if (!confirm(`'${filename}' 파일을 삭제할까요?`)) return;
    try {
      await api.delete(`/settings/files/${encodeURIComponent(filename)}`);
      setSharedFiles((prev) => prev.filter((f) => f.name !== filename));
    } catch {
      setFileShareError(`'${filename}' 삭제 실패`);
    }
  };

  // Warn before leaving when uploads are in progress
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (Object.keys(uploadProgress).length > 0) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [uploadProgress]);

  return (
    <div className="space-y-6">
      {/* ── Floating Download Progress Panel ─────────────────────────────── */}
      {Object.keys(downloadProgress).length > 0 && (
        <div
          className="fixed left-1/2 top-1/2 z-50 w-80 max-w-[min(20rem,90vw)] -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-background shadow-2xl ring-1 ring-border/50 overflow-hidden"
          role="dialog"
          aria-label="다운로드 진행"
        >
          <div className="flex items-center justify-between px-4 py-2.5 bg-muted/50 border-b">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Download className="h-4 w-4 text-primary" />
              다운로드
              <span className="text-xs text-muted-foreground tabular-nums">
                ({Object.keys(downloadProgress).length}개)
              </span>
            </div>
            <button
              onClick={() => {
                Object.keys(downloadProgress).forEach((fn) => downloadAbortMapRef.current[fn]?.abort());
                setDownloadProgress({});
              }}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              title="모두 닫기"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="divide-y max-h-72 overflow-y-auto">
            {Object.entries(downloadProgress).map(([filename, entry]) => (
              <div key={filename} className="px-4 py-3 space-y-1.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium truncate" title={filename}>{filename}</p>
                    <p className="text-[10px] text-muted-foreground tabular-nums mt-0.5">
                      {entry.done && entry.total === 0
                        ? "브라우저 다운로드로 시작됨"
                        : entry.total > 0
                          ? `${formatBytes(entry.received)} / ${formatBytes(entry.total)}`
                          : entry.received > 0
                            ? formatBytes(entry.received)
                            : "연결 중..."}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
                    {entry.done ? (
                      <CheckCircleIcon className="h-4 w-4 text-green-500" />
                    ) : entry.error ? (
                      <AlertTriangle className="h-4 w-4 text-destructive" />
                    ) : (
                      <>
                        <span className="text-[11px] tabular-nums text-muted-foreground">
                          {entry.pct >= 0 ? `${entry.pct}%` : ""}
                        </span>
                        <button
                          onClick={() => handleCancelDownload(filename)}
                          className="rounded p-0.5 hover:bg-destructive/10 hover:text-destructive transition-colors text-muted-foreground"
                          title="취소"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {/* Progress bar */}
                {!entry.error && (
                  <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                    {entry.done ? (
                      <div className="h-full w-full rounded-full bg-green-500" />
                    ) : entry.pct < 0 || entry.total === 0 ? (
                      <div className="h-full w-full rounded-full bg-muted relative overflow-hidden">
                        <div
                          className="absolute inset-y-0 w-2/5 rounded-full bg-primary"
                          style={{ animation: "slide 1.4s ease-in-out infinite" }}
                        />
                      </div>
                    ) : (
                      <div
                        className="h-full rounded-full bg-primary transition-all duration-200"
                        style={{ width: `${entry.pct}%` }}
                      />
                    )}
                  </div>
                )}
                {entry.error && (
                  <p className="text-[10px] text-destructive">{entry.error}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <SettingsIcon className="h-6 w-6" /> Settings
        </h1>
        <p className="text-sm text-muted-foreground mt-1">플랫폼 및 시스템 설정을 관리합니다</p>
      </div>

      {/* Resource Monitoring (local) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Monitor className="h-4 w-4" /> Resource Monitoring
          </CardTitle>
          <CardDescription>
            사이드바에 표시되는 시스템 리소스 모니터링 주기를 설정합니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 max-w-xs">
            <Label htmlFor="interval">Monitoring Interval (seconds)</Label>
            <div className="flex items-center gap-2">
              <Input
                id="interval"
                type="number"
                min={5}
                max={300}
                value={localSettings.resourceMonitorInterval}
                onChange={(e) =>
                  setLocalSettings((s) => ({
                    ...s,
                    resourceMonitorInterval: parseInt(e.target.value) || 30,
                  }))
                }
                className="w-24"
              />
              <span className="text-sm text-muted-foreground">sec</span>
            </div>
            <p className="text-xs text-muted-foreground">
              최소 5초. CPU, Memory, GPU 사용률이 이 주기로 갱신됩니다.
            </p>
          </div>
          <Separator />
          <Button onClick={handleLocalSave} className="gap-2">
            <Save className="h-4 w-4" />
            {localSaved ? "Saved!" : "Save"}
          </Button>
        </CardContent>
      </Card>

      {/* Email Notifications */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Mail className="h-4 w-4" /> Email 알림
          </CardTitle>
          <CardDescription>
            분석 완료 또는 실패 시 이메일로 알림을 받습니다. 시스템 알림(웹)은 이 설정과 무관하게 항상 표시됩니다.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between rounded-lg border px-4 py-3">
            <div>
              <p className="text-sm font-medium">이메일 알림 받기</p>
              <p className="text-xs text-muted-foreground">
                {user?.email ?? ""} 로 발송
              </p>
            </div>
            <Toggle checked={emailEnabled} onChange={handleEmailToggle} disabled={emailSaving} />
          </div>
        </CardContent>
      </Card>

      {/* System Settings Header */}
      <Separator />
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">System Configuration</h2>
          <p className="text-sm text-muted-foreground">
            서버 측 설정 — 변경 시 즉시 적용됩니다 (Worker Concurrency 제외)
          </p>
        </div>
        <div className="flex items-center gap-2">
          {sysSaved && (
            <span className="flex items-center gap-1 text-sm text-emerald-600">
              <CheckCircle2 className="h-4 w-4" /> 저장 완료
            </span>
          )}
          {sysError && (
            <span className="flex items-center gap-1 text-sm text-destructive">
              <AlertTriangle className="h-4 w-4" /> {sysError}
            </span>
          )}
          <Button
            onClick={handleSysSave}
            disabled={sysSaving || !hasSysChanges}
            className="gap-2"
          >
            {sysSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {sysSaving ? "저장 중..." : "Save System Settings"}
          </Button>
        </div>
      </div>

      {sysLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        categoryOrder.map((cat) => {
          const items = grouped[cat];
          if (!items || items.length === 0) return null;
          const config = CATEGORY_CONFIG[cat];
          if (!config) return null;
          const Icon = config.icon;

          return (
            <Card key={cat}>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Icon className="h-4 w-4" /> {config.label}
                  {cat === "worker" && (
                    <Badge variant="outline" className="text-[10px] h-5 px-1.5 border-amber-400 text-amber-600">
                      재시작 필요
                    </Badge>
                  )}
                </CardTitle>
                <CardDescription>{config.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {items.map((s) => {
                    const label = SETTING_LABELS[s.key] || s.key;
                    const isBoolean = s.value_type === "boolean";
                    const isChanged = sysEdits[s.key] !== s.value;

                    return (
                      <div key={s.key} className="flex items-center justify-between gap-4 rounded-lg border px-4 py-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium">{label}</p>
                            {isChanged && (
                              <Badge variant="outline" className="text-[10px] h-4 px-1 border-blue-400 text-blue-600">
                                변경됨
                              </Badge>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {SETTING_DESCRIPTIONS[s.key] || s.description || ""}
                          </p>
                          <p className="text-[10px] text-muted-foreground/60 font-mono mt-0.5">
                            {s.key}
                          </p>
                        </div>
                        <div className="shrink-0">
                          {isBoolean ? (
                            <Toggle
                              checked={sysEdits[s.key]?.toLowerCase() === "true"}
                              onChange={(v) => handleSysEdit(s.key, v ? "true" : "false")}
                            />
                          ) : s.value_type === "integer" ? (
                            <Input
                              type="number"
                              min={0}
                              value={sysEdits[s.key] ?? ""}
                              onChange={(e) => handleSysEdit(s.key, e.target.value)}
                              className="w-28 text-right"
                            />
                          ) : (
                            <Input
                              type="text"
                              value={sysEdits[s.key] ?? ""}
                              onChange={(e) => handleSysEdit(s.key, e.target.value)}
                              className="w-72"
                            />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          );
        })
      )}

      {/* ── Admin File Share ── */}
      {isAdmin && (
        <>
          <Separator />
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-base flex items-center gap-2">
                    <FolderOpen className="h-4 w-4" /> File Share
                    <Badge variant="outline" className="text-[10px] h-5 px-1.5 border-violet-400 text-violet-600">
                      Admin
                    </Badge>
                  </CardTitle>
                  <CardDescription className="mt-1">
                    관리자 전용 파일 공유 공간입니다. Drag &amp; Drop 또는 파일 선택으로 업로드하고, 클릭으로 다운로드합니다.
                  </CardDescription>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={fetchSharedFiles}
                  disabled={fileShareLoading}
                  className="gap-1.5 shrink-0"
                >
                  {fileShareLoading
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : <FolderOpen className="h-3.5 w-3.5" />}
                  새로고침
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Error */}
              {fileShareError && (
                <div className="flex items-center justify-between rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    {fileShareError}
                  </div>
                  <button onClick={() => setFileShareError(null)}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}

              {/* Drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDropZoneDrop}
                onClick={() => fileInputRef.current?.click()}
                className={cn(
                  "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
                  dragOver
                    ? "border-primary bg-primary/5"
                    : "border-muted-foreground/25 hover:border-muted-foreground/50 hover:bg-muted/30",
                )}
              >
                <Upload className={cn("h-8 w-8", dragOver ? "text-primary" : "text-muted-foreground/50")} />
                <div>
                  <p className="text-sm font-medium">파일을 드래그하거나 클릭해서 업로드</p>
                  <p className="text-xs text-muted-foreground mt-0.5">모든 파일 형식 지원 · 여러 파일 동시 업로드 가능</p>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files) uploadFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
                {/* Hidden input for resume file selection */}
                <input
                  ref={resumeFileInputRef}
                  type="file"
                  className="hidden"
                  onChange={handleResumeFileSelect}
                />
              </div>

              {/* Pending resume sessions */}
              {pendingResumes.length > 0 && (
                <div className="rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 p-3 space-y-2">
                  <p className="text-xs font-medium text-amber-700 dark:text-amber-400">
                    이전 업로드 세션이 중단되었습니다. 파일을 다시 선택하면 이어서 업로드합니다.
                  </p>
                  {pendingResumes.map((saved) => (
                    <div key={saved.uploadId} className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-xs font-medium truncate">{saved.fileName}</p>
                        <p className="text-[10px] text-muted-foreground">
                          {formatBytes(saved.totalSize)} · {saved.uploadedChunks}/{saved.totalChunks} 청크 완료
                          ({Math.round(saved.uploadedChunks / saved.totalChunks * 100)}%)
                        </p>
                      </div>
                      <div className="flex gap-1.5 shrink-0">
                        <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={() => handleResumeClick(saved)}>
                          <Upload className="h-3 w-3" /> 이어 올리기
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive" onClick={() => handleCancelPendingResume(saved.uploadId)} title="삭제">
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Uploading progress bars */}
              {Object.keys(uploadProgress).length > 0 && (
                <div className="space-y-2">
                  {Object.entries(uploadProgress).map(([key, { name, pct, finalizing, uploadId, uploadedChunks, totalChunks }]) => (
                    <div key={key} className="space-y-1">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <Loader2 className="h-3 w-3 animate-spin shrink-0" />
                          <span className="truncate">{name}</span>
                          {!finalizing && (
                            <span className="text-[10px] opacity-60 shrink-0">({uploadedChunks}/{totalChunks} 청크)</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0 ml-2">
                          <span className="tabular-nums text-[11px]">
                            {finalizing ? "병합 중..." : `${pct}%`}
                          </span>
                          {!finalizing && (
                            <button
                              onClick={() => handleCancelUpload(key, uploadId)}
                              className="rounded p-0.5 hover:bg-destructive/10 hover:text-destructive transition-colors"
                              title="업로드 취소"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                        {finalizing ? (
                          <div className="h-full w-full rounded-full bg-muted relative overflow-hidden">
                            <div
                              className="absolute inset-y-0 w-2/5 rounded-full bg-primary"
                              style={{ animation: "slide 1.4s ease-in-out infinite" }}
                            />
                          </div>
                        ) : (
                          <div
                            className="h-full rounded-full bg-primary transition-all duration-200"
                            style={{ width: `${pct}%` }}
                          />
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* File list */}
              {fileShareLoading && sharedFiles.length === 0 ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : sharedFiles.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-1 py-8 text-muted-foreground">
                  <FolderOpen className="h-8 w-8 opacity-30" />
                  <p className="text-sm">업로드된 파일이 없습니다</p>
                </div>
              ) : (
                <>
                  {/* Selected-files action bar */}
                  {selectedFiles.size > 0 && (
                    <div className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 px-3 py-2">
                      <span className="text-sm font-medium">{selectedFiles.size}개 선택됨</span>
                      <div className="flex gap-2">
                        <Button size="sm" variant="outline" className="h-7 gap-1.5 text-xs" onClick={handleDownloadSelected}>
                          <Download className="h-3.5 w-3.5" />
                          {selectedFiles.size}개 다운로드
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setSelectedFiles(new Set())}>
                          선택 해제
                        </Button>
                      </div>
                    </div>
                  )}

                  <div className="rounded-md border overflow-hidden">
                    {/* Header row */}
                    <div className="grid grid-cols-[32px_1fr_110px_180px_88px] items-center gap-3 px-3 py-2 bg-muted/40 border-b text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      <button
                        onClick={toggleSelectAll}
                        className="flex items-center justify-center text-muted-foreground hover:text-foreground"
                        title={selectedFiles.size === sharedFiles.length ? "전체 해제" : "전체 선택"}
                      >
                        {selectedFiles.size === sharedFiles.length
                          ? <CheckSquare className="h-4 w-4 text-primary" />
                          : selectedFiles.size > 0
                            ? <CheckSquare className="h-4 w-4 opacity-50" />
                            : <Square className="h-4 w-4" />}
                      </button>
                      <div>파일명</div>
                      <div className="text-right">크기</div>
                      <div>업로드 시각</div>
                      <div className="text-right">동작</div>
                    </div>
                    <div className="divide-y">
                      {sharedFiles.map((file) => {
                        const uploadedAt = new Date(file.modified_at * 1000);
                        const isSelected = selectedFiles.has(file.name);
                        return (
                          <div
                            key={file.name}
                            className={cn(
                              "grid grid-cols-[32px_1fr_110px_180px_88px] items-center gap-3 px-3 py-2.5 transition-colors",
                              isSelected ? "bg-primary/5" : "hover:bg-muted/30",
                            )}
                          >
                            <button
                              onClick={() => toggleSelectFile(file.name)}
                              className="flex items-center justify-center text-muted-foreground hover:text-foreground"
                            >
                              {isSelected
                                ? <CheckSquare className="h-4 w-4 text-primary" />
                                : <Square className="h-4 w-4" />}
                            </button>
                            <div className="flex items-center gap-2 min-w-0">
                              <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                              <span className="truncate text-sm font-medium" title={file.name}>{file.name}</span>
                            </div>
                            <div className="text-sm text-right tabular-nums text-muted-foreground" title={`${file.size.toLocaleString()} bytes`}>
                              {formatBytes(file.size)}
                            </div>
                            <div className="text-xs text-muted-foreground tabular-nums" title={uploadedAt.toISOString()}>
                              {uploadedAt.toLocaleString("ko-KR", {
                                year: "numeric", month: "2-digit", day: "2-digit",
                                hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
                              })}
                            </div>
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-foreground"
                                onClick={() => downloadFile(file.name)}
                                title="다운로드"
                              >
                                <Download className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                onClick={() => handleDeleteFile(file.name)}
                                title="삭제"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    {/* Footer row */}
                    <div className="px-3 py-2 bg-muted/20 border-t text-[11px] text-muted-foreground flex items-center justify-between">
                      <span>총 {sharedFiles.length}개 파일</span>
                      <span className="tabular-nums">
                        합계 {formatBytes(sharedFiles.reduce((sum, f) => sum + f.size, 0))}
                      </span>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
