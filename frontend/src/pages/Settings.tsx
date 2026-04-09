import { useState, useEffect, useCallback } from "react";
import {
  Settings as SettingsIcon, Monitor, Save, Mail, Shield, Zap,
  Webhook, Server, Loader2, CheckCircle2, AlertTriangle,
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

  return (
    <div className="space-y-6">
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
    </div>
  );
}
