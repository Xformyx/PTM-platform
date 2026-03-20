import { useState, useEffect } from "react";
import { Settings as SettingsIcon, Monitor, Save, Mail } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

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

export default function Settings() {
  const { user, refreshUser, updateUser } = useAuth();
  const [settings, setSettings] = useState<PtmSettings>(loadSettings);
  const [saved, setSaved] = useState(false);
  const [emailEnabled, setEmailEnabled] = useState(user?.email_notifications_enabled ?? true);
  const [emailSaving, setEmailSaving] = useState(false);

  useEffect(() => {
    setEmailEnabled(user?.email_notifications_enabled ?? true);
  }, [user?.email_notifications_enabled]);

  const handleSave = () => {
    const interval = Math.max(5, settings.resourceMonitorInterval);
    const updated = { ...settings, resourceMonitorInterval: interval };
    setSettings(updated);
    saveSettings(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
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
      // revert on error
      setEmailEnabled(!enabled);
    } finally {
      setEmailSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <SettingsIcon className="h-6 w-6" /> Settings
        </h1>
        <p className="text-sm text-muted-foreground mt-1">Configure platform preferences</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Monitor className="h-4 w-4" /> Resource Monitoring
          </CardTitle>
          <CardDescription>
            Configure the system resource monitoring displayed in the sidebar.
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
                value={settings.resourceMonitorInterval}
                onChange={(e) =>
                  setSettings((s) => ({
                    ...s,
                    resourceMonitorInterval: parseInt(e.target.value) || 30,
                  }))
                }
                className="w-24"
              />
              <span className="text-sm text-muted-foreground">sec</span>
            </div>
            <p className="text-xs text-muted-foreground">
              Minimum 5 seconds. CPU, Memory, GPU usage will be refreshed at this interval.
            </p>
          </div>

          <Separator />

          <Button onClick={handleSave} className="gap-2">
            <Save className="h-4 w-4" />
            {saved ? "Saved!" : "Save Settings"}
          </Button>
        </CardContent>
      </Card>

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
            <button
              type="button"
              role="switch"
              aria-checked={emailEnabled}
              disabled={emailSaving}
              onClick={() => handleEmailToggle(!emailEnabled)}
              className={`
                relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full
                transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
                disabled:cursor-not-allowed disabled:opacity-50
                ${emailEnabled ? "bg-primary" : "bg-muted"}
              `}
            >
              <span
                className={`
                  pointer-events-none block h-5 w-5 rounded-full bg-background shadow-lg ring-0
                  transition-transform
                  ${emailEnabled ? "translate-x-6" : "translate-x-1"}
                `}
              />
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
