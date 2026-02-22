import { useState, useEffect } from "react";
import { Settings as SettingsIcon, Monitor, Save } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

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
  const [settings, setSettings] = useState<PtmSettings>(loadSettings);
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    const interval = Math.max(5, settings.resourceMonitorInterval);
    const updated = { ...settings, resourceMonitorInterval: interval };
    setSettings(updated);
    saveSettings(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
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
    </div>
  );
}
