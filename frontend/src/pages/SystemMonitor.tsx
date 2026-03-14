import { useEffect, useState, useCallback, useRef } from "react";
import { RefreshCw, AlertCircle, CheckCircle2, HelpCircle, Server, Database, Cpu, Network, Terminal, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

interface Node {
  id: string;
  label: string;
  host: string;
  port: number;
  status: "ok" | "error" | "unavailable";
  detail: string;
}

interface Edge {
  from: string;
  to: string;
  label: string;
  status: string;
}

interface SystemArchitecture {
  nodes: Record<string, Node>;
  edges: Edge[];
}

const statusConfig = {
  ok: { color: "text-blue-600", bg: "bg-blue-500/20", icon: CheckCircle2 },
  error: { color: "text-red-600", bg: "bg-red-500/20", icon: AlertCircle },
  unavailable: { color: "text-amber-600", bg: "bg-amber-500/20", icon: HelpCircle },
  unknown: { color: "text-muted-foreground", bg: "bg-muted/50", icon: HelpCircle },
};

function StatusBadge({ status }: { status: string }) {
  const config = statusConfig[status as keyof typeof statusConfig] ?? statusConfig.unknown;
  const Icon = config.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium", config.bg, config.color)}>
      <Icon className="h-3 w-3" />
      {status}
    </span>
  );
}

export default function SystemMonitor() {
  const [data, setData] = useState<SystemArchitecture | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedContainer, setSelectedContainer] = useState<string>("");
  const [containerLogs, setContainerLogs] = useState<string>("");
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [architectureExpanded, setArchitectureExpanded] = useState(false);
  const [connectionExpanded, setConnectionExpanded] = useState(false);
  const [containerStatusExpanded, setContainerStatusExpanded] = useState(true);
  const [containerStatus, setContainerStatus] = useState<{ id: string; label: string; category: string; status: string; detail: string; image?: string; started_at?: string }[]>([]);
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const fetchArchitecture = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<SystemArchitecture>("/health/system-architecture");
      setData(res);
    } catch (e) {
      setError("API unreachable (Gateway or API Server may be down)");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchArchitecture();
    const id = setInterval(fetchArchitecture, 15000);
    return () => clearInterval(id);
  }, [fetchArchitecture]);

  const fetchContainerStatus = useCallback(async () => {
    try {
      const res = await api.get<{ containers: { id: string; label: string; category: string; status: string; detail: string; image?: string; started_at?: string }[] }>("/health/container-status");
      setContainerStatus(res.containers || []);
    } catch {
      setContainerStatus([]);
    }
  }, []);

  useEffect(() => {
    fetchContainerStatus();
    const id = setInterval(fetchContainerStatus, 15000);
    return () => clearInterval(id);
  }, [fetchContainerStatus]);

  useEffect(() => {
    if (containerStatus.length > 0 && !selectedContainer) {
      setSelectedContainer(containerStatus[0].id);
    } else if (containerStatus.length > 0 && selectedContainer && !containerStatus.some((c) => c.id === selectedContainer)) {
      setSelectedContainer(containerStatus[0].id);
    }
  }, [containerStatus, selectedContainer]);

  const fetchLogs = useCallback(async () => {
    if (!selectedContainer) return;
    try {
      const res = await api.get<{ logs: string; error?: string }>("/health/container-logs/" + selectedContainer + "?tail=500");
      if (res.error) {
        setLogsError(res.error);
        setContainerLogs("");
      } else {
        setContainerLogs(res.logs || "");
      }
    } catch (e) {
      setLogsError(e instanceof Error ? e.message : "Failed to fetch logs");
      setContainerLogs("");
    }
  }, [selectedContainer]);

  useEffect(() => {
    if (!selectedContainer) {
      setContainerLogs("");
      return;
    }
    setLogsError(null);
    setLogsLoading(true);
    fetchLogs().finally(() => setLogsLoading(false));
    const id = setInterval(() => fetchLogs(), 4000);
    return () => clearInterval(id);
  }, [selectedContainer, fetchLogs]);

  useEffect(() => {
    if (!containerLogs || !logsContainerRef.current) return;
    const el = logsContainerRef.current;
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (isNearBottom) {
      logsEndRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [containerLogs]);

  const leftCol = ["client", "gateway", "api_server"];
  const rightCol = ["mysql", "redis", "chromadb", "mcp_server", "ollama", "cytoscape"];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">System Monitor</h1>
          <p className="text-sm text-muted-foreground">
            Architecture diagram and connectivity status. Refreshes every 15s.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => { fetchArchitecture(); fetchContainerStatus(); }} disabled={loading}>
          <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {error && (
        <Card className="border-red-200 bg-red-50/50 dark:bg-red-950/20">
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
              <AlertCircle className="h-5 w-5" />
              <span>{error}</span>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              Check: <code className="rounded bg-muted px-1">docker compose ps</code> &{" "}
              <code className="rounded bg-muted px-1">docker compose restart gateway api-server</code>
            </p>
          </CardContent>
        </Card>
      )}

      <Card>
        <button
          type="button"
          onClick={() => setArchitectureExpanded((v) => !v)}
          className="w-full text-left"
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Server className="h-5 w-5" />
                System Architecture
              </CardTitle>
              <CardDescription>
                Nodes and connections. Green = OK, Red = Error, Amber = Unavailable.
              </CardDescription>
            </div>
            {architectureExpanded ? (
              <ChevronUp className="h-5 w-5 text-muted-foreground shrink-0" />
            ) : (
              <ChevronDown className="h-5 w-5 text-muted-foreground shrink-0" />
            )}
          </CardHeader>
        </button>
        {architectureExpanded && (
        <CardContent>
          {loading && !data ? (
            <div className="flex h-64 items-center justify-center text-muted-foreground">
              Loading...
            </div>
          ) : data ? (
            <div className="flex flex-col lg:flex-row gap-8">
              {/* Left column: Client → Gateway → API */}
              <div className="flex flex-col gap-4 min-w-[200px]">
                {leftCol.map((id) => {
                  const node = data.nodes[id];
                  if (!node) return null;
                  const config = statusConfig[node.status as keyof typeof statusConfig] ?? statusConfig.unknown;
                  const Icon = id === "client" ? Cpu : id === "gateway" ? Server : Database;
                  return (
                    <div
                      key={id}
                      className={cn(
                        "rounded-lg border p-4 transition-colors",
                        config.bg,
                        "border-current/20"
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Icon className="h-4 w-4" />
                          <span className="font-medium">{node.label}</span>
                        </div>
                        <StatusBadge status={node.status} />
                      </div>
                      <div className="mt-2 text-xs text-muted-foreground">
                        {node.port > 0 ? `${node.host}:${node.port}` : node.detail}
                      </div>
                      {node.detail && node.port > 0 && (
                        <div className="mt-1 text-xs text-muted-foreground">{node.detail}</div>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Arrow */}
              <div className="hidden lg:flex items-center justify-center text-muted-foreground">
                <span className="text-2xl">→</span>
              </div>

              {/* Right column: Backend services */}
              <div className="flex flex-col gap-4 flex-1">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {rightCol.map((id) => {
                    const node = data.nodes[id];
                    if (!node) return null;
                    const config = statusConfig[node.status as keyof typeof statusConfig] ?? statusConfig.unknown;
                    return (
                      <div
                        key={id}
                        className={cn(
                          "rounded-lg border p-4 transition-colors",
                          config.bg,
                          "border-current/20"
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {id === "cytoscape" ? (
                              <Network className="h-4 w-4" />
                            ) : (
                              <Database className="h-4 w-4" />
                            )}
                            <span className="font-medium">{node.label}</span>
                          </div>
                          <StatusBadge status={node.status} />
                        </div>
                        <div className="mt-2 text-xs text-muted-foreground">
                          {node.port > 0 ? `${node.host}:${node.port}` : node.host}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground truncate" title={node.detail}>
                          {node.detail}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : null}
        </CardContent>
        )}
      </Card>

      {/* Connection matrix */}
      {data && (
        <Card>
          <button
            type="button"
            onClick={() => setConnectionExpanded((v) => !v)}
            className="w-full text-left"
          >
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <div>
                <CardTitle>Connection Status</CardTitle>
                <CardDescription>API Server → Backend services</CardDescription>
              </div>
              {connectionExpanded ? (
                <ChevronUp className="h-5 w-5 text-muted-foreground shrink-0" />
              ) : (
                <ChevronDown className="h-5 w-5 text-muted-foreground shrink-0" />
              )}
            </CardHeader>
          </button>
          {connectionExpanded && (
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 font-medium">From</th>
                    <th className="text-left py-2 font-medium">To</th>
                    <th className="text-left py-2 font-medium">Port</th>
                    <th className="text-left py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.edges
                    .filter((e) => e.from !== "client")
                    .map((edge, i) => (
                      <tr key={i} className="border-b last:border-0">
                        <td className="py-2">{edge.from.replace("_", " ")}</td>
                        <td className="py-2">{edge.to.replace("_", " ")}</td>
                        <td className="py-2 font-mono">{edge.label}</td>
                        <td className="py-2">
                          <StatusBadge status={edge.status} />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </CardContent>
          )}
        </Card>
      )}

      {/* Container Status */}
      <Card>
        <button
          type="button"
          onClick={() => setContainerStatusExpanded((v) => !v)}
          className="w-full text-left"
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <div>
              <CardTitle>Container Status</CardTitle>
              <CardDescription>
                서비스에 필요한 컨테이너들의 실행 상태 (15초마다 갱신)
              </CardDescription>
            </div>
            {containerStatusExpanded ? (
              <ChevronUp className="h-5 w-5 text-muted-foreground shrink-0" />
            ) : (
              <ChevronDown className="h-5 w-5 text-muted-foreground shrink-0" />
            )}
          </CardHeader>
        </button>
        {containerStatusExpanded && (
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {containerStatus.map((c) => {
                const config = statusConfig[c.status as keyof typeof statusConfig] ?? statusConfig.unknown;
                const isSelected = selectedContainer === c.id;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setSelectedContainer(c.id)}
                    className={cn(
                      "rounded-lg border p-3 transition-colors text-left w-full cursor-pointer",
                      "hover:opacity-90 hover:ring-2 hover:ring-blue-400/50",
                      config.bg,
                      "border-current/20",
                      isSelected && "ring-2 ring-blue-500 ring-offset-2"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-sm">{c.label}</span>
                      <StatusBadge status={c.status} />
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground font-mono truncate" title={c.detail}>
                      {c.detail}
                    </div>
                    {c.image && (
                      <div className="mt-1.5 text-xs text-muted-foreground truncate" title={c.image}>
                        Image: {c.image}
                      </div>
                    )}
                    {c.started_at && (
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        Started: {new Date(c.started_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "short" })}
                      </div>
                    )}
                    <div className="mt-1 text-xs text-muted-foreground">{isSelected ? "✓ Viewing logs" : "Click to view logs"}</div>
                  </button>
                );
              })}
            </div>
          </CardContent>
        )}
      </Card>

      {/* Container Logs */}
      <Card className="overflow-hidden border-zinc-700 dark:border-zinc-700">
        <CardHeader className="border-b border-zinc-700/60 bg-[#24283b]">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-zinc-100">
                <Terminal className="h-5 w-5" />
                Container Logs
                {selectedContainer && (
                  <span className="text-sm font-normal text-zinc-400">
                    — {containerStatus.find((c) => c.id === selectedContainer)?.label ?? selectedContainer}
                  </span>
                )}
              </CardTitle>
              <CardDescription className="text-zinc-400 mt-1">
                Click a container above. Logs refresh every 4s. Scroll stays at bottom when viewing latest.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Select value={selectedContainer} onValueChange={setSelectedContainer}>
                <SelectTrigger className="w-[260px] bg-[#1a1b26] border-zinc-600 text-zinc-200">
                  <SelectValue placeholder={containerStatus.length ? "Select container" : "Loading containers..."} />
                </SelectTrigger>
                <SelectContent>
                  {containerStatus.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.label} ({c.status})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="sm"
                onClick={() => fetchLogs()}
                disabled={!selectedContainer}
                className="border-zinc-600 text-zinc-300 hover:bg-zinc-700"
              >
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0 bg-[#1a1b26]">
          <div
            ref={logsContainerRef}
            className="h-[560px] overflow-y-auto p-3 font-mono text-[11.5px] leading-[18px] text-zinc-300 scrollbar-thin whitespace-pre-wrap break-all"
            style={{ contain: "layout" }}
          >
            {logsLoading ? (
              <div className="flex items-center justify-center h-full gap-2 text-zinc-500">
                <RefreshCw className="h-4 w-4 animate-spin" />
                Loading logs...
              </div>
            ) : logsError ? (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-amber-500">
                <AlertCircle className="h-8 w-8" />
                <span>{logsError}</span>
                <span className="text-xs text-zinc-500">Ensure Docker socket is mounted: /var/run/docker.sock</span>
              </div>
            ) : !selectedContainer || containerStatus.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-zinc-500">
                <Terminal className="h-8 w-8" />
                <span>{containerStatus.length === 0 ? "Loading containers... (Docker socket required)" : "Select a container to view logs"}</span>
              </div>
            ) : containerLogs ? (
              <>
                <pre className="m-0">{containerLogs}</pre>
                <div ref={logsEndRef} aria-hidden="true" />
              </>
            ) : (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-zinc-500">
                <Terminal className="h-8 w-8" />
                <span>No logs available</span>
                <span className="text-xs">Try another container (e.g. API Server, Report Generation Worker)</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
