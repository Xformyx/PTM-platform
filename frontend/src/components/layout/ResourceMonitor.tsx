import { useEffect, useState, useCallback } from "react";
import { Cpu, HardDrive, MemoryStick, MonitorSpeaker } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { loadSettings } from "@/pages/Settings";

interface SystemMetrics {
  cpu: { usage_pct: number; cores: number; freq_mhz: number | null };
  memory: { used_gb: number; total_gb: number; usage_pct: number };
  disk: { used_gb: number; total_gb: number; usage_pct: number };
  gpu: Array<{
    index: number;
    name: string;
    gpu_util_pct: number;
    mem_used_gb: number;
    mem_total_gb: number;
    mem_util_pct: number;
  }>;
}

function UsageBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-muted/50 overflow-hidden">
      <div
        className={cn("h-full rounded-full transition-all duration-700 ease-out", color)}
        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </div>
  );
}

function barColor(pct: number): string {
  if (pct >= 90) return "bg-red-500";
  if (pct >= 70) return "bg-amber-500";
  return "bg-emerald-500";
}

export default function ResourceMonitor() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [intervalSec, setIntervalSec] = useState(loadSettings().resourceMonitorInterval);

  const fetchMetrics = useCallback(async () => {
    try {
      const data = await api.get<SystemMetrics>("/system/metrics");
      setMetrics(data);
    } catch {
      /* ignore fetch errors */
    }
  }, []);

  useEffect(() => {
    fetchMetrics();

    const id = setInterval(fetchMetrics, intervalSec * 1000);
    return () => clearInterval(id);
  }, [fetchMetrics, intervalSec]);

  // Listen for settings changes
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.resourceMonitorInterval) {
        setIntervalSec(detail.resourceMonitorInterval);
      }
    };
    window.addEventListener("ptm-settings-changed", handler);
    return () => window.removeEventListener("ptm-settings-changed", handler);
  }, []);

  if (!metrics) return null;

  const { cpu, memory, disk, gpu } = metrics;

  return (
    <div className="px-4 pb-2">
      <div className="rounded-lg border bg-muted/30 px-3 py-2.5 space-y-2.5">
        {/* CPU */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Cpu className="h-3 w-3 text-muted-foreground" />
              <span className="text-[10px] font-medium text-muted-foreground">CPU</span>
            </div>
            <span className="text-[10px] font-mono tabular-nums text-foreground">
              {cpu.usage_pct.toFixed(0)}%
              <span className="text-muted-foreground ml-1">({cpu.cores}c)</span>
            </span>
          </div>
          <UsageBar pct={cpu.usage_pct} color={barColor(cpu.usage_pct)} />
        </div>

        {/* Memory */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <MemoryStick className="h-3 w-3 text-muted-foreground" />
              <span className="text-[10px] font-medium text-muted-foreground">MEM</span>
            </div>
            <span className="text-[10px] font-mono tabular-nums text-foreground">
              {memory.used_gb}
              <span className="text-muted-foreground">/{memory.total_gb}GB</span>
            </span>
          </div>
          <UsageBar pct={memory.usage_pct} color={barColor(memory.usage_pct)} />
        </div>

        {/* Disk */}
        {disk && (
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <HardDrive className="h-3 w-3 text-muted-foreground" />
                <span className="text-[10px] font-medium text-muted-foreground">DISK</span>
              </div>
              <span className="text-[10px] font-mono tabular-nums text-foreground">
                {disk.used_gb}
                <span className="text-muted-foreground">/{disk.total_gb}GB</span>
              </span>
            </div>
            <UsageBar pct={disk.usage_pct} color={barColor(disk.usage_pct)} />
          </div>
        )}

        {/* GPU */}
        {gpu.length > 0 ? (
          gpu.map((g) => (
            <div key={g.index} className="space-y-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <MonitorSpeaker className="h-3 w-3 text-muted-foreground" />
                  <span className="text-[10px] font-medium text-muted-foreground">GPU</span>
                </div>
                <span className="text-[10px] font-mono tabular-nums text-foreground">
                  {g.gpu_util_pct}%
                  <span className="text-muted-foreground ml-1">
                    {g.mem_used_gb}/{g.mem_total_gb}GB
                  </span>
                </span>
              </div>
              <UsageBar pct={g.gpu_util_pct} color={barColor(g.gpu_util_pct)} />
            </div>
          ))
        ) : (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <MonitorSpeaker className="h-3 w-3 text-muted-foreground" />
              <span className="text-[10px] font-medium text-muted-foreground">GPU</span>
            </div>
            <span className="text-[10px] text-muted-foreground">N/A</span>
          </div>
        )}
      </div>
    </div>
  );
}
