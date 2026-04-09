import { useEffect, useState, useCallback, useRef } from "react";
import { RefreshCw, AlertCircle, CheckCircle2, HelpCircle, Server, Database, Cpu, Network, Terminal, ChevronDown, ChevronUp, Circle, RotateCcw, Loader2, Eye } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

interface ArchNode {
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
  nodes: Record<string, ArchNode>;
  edges: Edge[];
}

const statusConfig = {
  ok: { color: "text-blue-600", bg: "bg-blue-500/20", icon: CheckCircle2 },
  error: { color: "text-red-600", bg: "bg-red-500/20", icon: AlertCircle },
  unavailable: { color: "text-amber-600", bg: "bg-amber-500/20", icon: HelpCircle },
  restarting: { color: "text-amber-600", bg: "bg-amber-500/20", icon: RefreshCw },
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

/** Maximum number of log lines to keep in memory */
const MAX_LOG_LINES = 5000;

export default function SystemMonitor() {
  const [data, setData] = useState<SystemArchitecture | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedContainer, setSelectedContainer] = useState<string>("");
  const [logLines, setLogLines] = useState<string[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [architectureExpanded, setArchitectureExpanded] = useState(false);
  const [connectionExpanded, setConnectionExpanded] = useState(false);
  const [containerStatusExpanded, setContainerStatusExpanded] = useState(true);
  const [containerStatus, setContainerStatus] = useState<{ id: string; label: string; category: string; status: string; detail: string; image?: string; started_at?: string }[]>([]);
  const logsContainerRef = useRef<HTMLDivElement>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const autoScrollRef = useRef(true);

  // Context menu
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; containerId: string; label: string } | null>(null);
  const [restarting, setRestarting] = useState<string | null>(null);
  const ctxRef = useRef<HTMLDivElement>(null);

  // ── Architecture & Container Status ──────────────────────────
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

  // ── SSE Log Streaming ────────────────────────────────────────
  const closeStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setStreaming(false);
  }, []);

  const startStream = useCallback((containerId: string) => {
    closeStream();
    if (!containerId) return;

    setLogsLoading(true);
    setLogsError(null);
    setLogLines([]);
    autoScrollRef.current = true;

    // Determine base URL for SSE (same origin, under /api/)
    const baseUrl = window.location.origin;
    const sseUrl = `${baseUrl}/api/health/container-logs/${containerId}/stream?tail=200`;

    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    es.addEventListener("log", (event: MessageEvent) => {
      const line = event.data;
      if (line !== undefined && line !== null) {
        setLogLines((prev) => {
          const next = [...prev, line];
          // Trim to MAX_LOG_LINES to prevent memory bloat
          return next.length > MAX_LOG_LINES ? next.slice(-MAX_LOG_LINES) : next;
        });
      }
      // First log event means loading is done
      setLogsLoading(false);
      setStreaming(true);
    });

    es.addEventListener("ping", () => {
      // Keep-alive, just mark as connected
      setLogsLoading(false);
      setStreaming(true);
    });

    es.onerror = () => {
      // EventSource auto-reconnects on error, but if it closes we mark it
      if (es.readyState === EventSource.CLOSED) {
        setStreaming(false);
        setLogsError("Log stream disconnected. Click Reconnect to retry.");
      }
      setLogsLoading(false);
    };

    es.onopen = () => {
      setLogsLoading(false);
      setStreaming(true);
    };
  }, [closeStream]);

  // Start/stop stream when selected container changes
  useEffect(() => {
    if (selectedContainer) {
      startStream(selectedContainer);
    } else {
      closeStream();
      setLogLines([]);
    }
    return () => closeStream();
  }, [selectedContainer, startStream, closeStream]);

  // ── Auto-scroll logic ────────────────────────────────────────
  const handleScroll = useCallback(() => {
    const el = logsContainerRef.current;
    if (!el) return;
    // If user scrolled up more than 80px from bottom, disable auto-scroll
    autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  useEffect(() => {
    if (autoScrollRef.current && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [logLines]);

  // ── Fallback: manual fetch (non-streaming) ───────────────────
  const fetchLogsFallback = useCallback(async () => {
    if (!selectedContainer) return;
    closeStream();
    setLogsLoading(true);
    setLogsError(null);
    try {
      const res = await api.get<{ logs: string; error?: string }>("/health/container-logs/" + selectedContainer + "?tail=500");
      if (res.error) {
        setLogsError(res.error);
        setLogLines([]);
      } else {
        setLogLines((res.logs || "").split("\n"));
      }
    } catch (e) {
      setLogsError(e instanceof Error ? e.message : "Failed to fetch logs");
      setLogLines([]);
    } finally {
      setLogsLoading(false);
    }
  }, [selectedContainer, closeStream]);

  // ── Context menu handlers ──────────────────────────────────────
  const handleContextMenu = useCallback((e: React.MouseEvent, containerId: string, label: string) => {
    e.preventDefault();
    e.stopPropagation();
    setCtxMenu({ x: e.clientX, y: e.clientY, containerId, label });
  }, []);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ctxRef.current && !ctxRef.current.contains(e.target as Node)) {
        setCtxMenu(null);
      }
    };
    if (ctxMenu) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [ctxMenu]);

  const handleRestart = useCallback(async (containerId: string) => {
    setCtxMenu(null);
    setRestarting(containerId);
    try {
      const res = await api.post<{ success: boolean; message?: string; error?: string }>(
        `/health/container-restart/${containerId}`
      );
      if (res.success) {
        setTimeout(() => {
          fetchContainerStatus();
          setRestarting(null);
        }, 3000);
      } else {
        alert(res.error || "Restart failed");
        setRestarting(null);
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "Restart failed");
      setRestarting(null);
    }
  }, [fetchContainerStatus]);

  const leftCol = ["client", "gateway", "api_server"];
  const rightCol = ["mysql", "redis", "chromadb", "mcp_server", "ollama", "cytoscape"];

  const archNodeToContainer: Record<string, { id: string; label: string }> = {
    api_server: { id: "ptm-api-server", label: "API Server" },
    gateway: { id: "ptm-gateway", label: "Gateway (nginx)" },
    mysql: { id: "ptm-mysql", label: "MySQL" },
    redis: { id: "ptm-redis", label: "Redis" },
    chromadb: { id: "ptm-chromadb", label: "ChromaDB" },
    mcp_server: { id: "ptm-mcp-server", label: "MCP Server" },
  };

  const containerLogs = logLines.join("\n");

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
                  const ctr = archNodeToContainer[id];
                  const isNodeRestarting = ctr && restarting === ctr.id;
                  return (
                    <div
                      key={id}
                      onContextMenu={ctr ? (e) => handleContextMenu(e, ctr.id, ctr.label) : undefined}
                      className={cn(
                        "rounded-lg border p-4 transition-colors",
                        config.bg,
                        "border-current/20",
                        ctr && "cursor-context-menu",
                        isNodeRestarting && "opacity-60 animate-pulse",
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Icon className="h-4 w-4" />
                          <span className="font-medium">{node.label}</span>
                        </div>
                        {isNodeRestarting
                          ? <StatusBadge status="restarting" />
                          : <StatusBadge status={node.status} />
                        }
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
                    const ctr = archNodeToContainer[id];
                    const isNodeRestarting = ctr && restarting === ctr.id;
                    return (
                      <div
                        key={id}
                        onContextMenu={ctr ? (e) => handleContextMenu(e, ctr.id, ctr.label) : undefined}
                        className={cn(
                          "rounded-lg border p-4 transition-colors",
                          config.bg,
                          "border-current/20",
                          ctr && "cursor-context-menu",
                          isNodeRestarting && "opacity-60 animate-pulse",
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            {id === "ollama" || id === "cytoscape" ? (
                              <Network className="h-4 w-4" />
                            ) : (
                              <Database className="h-4 w-4" />
                            )}
                            <span className="font-medium">{node.label}</span>
                          </div>
                          {isNodeRestarting
                            ? <StatusBadge status="restarting" />
                            : <StatusBadge status={node.status} />
                          }
                        </div>
                        <div className="mt-2 text-xs text-muted-foreground">
                          {node.port > 0 ? `${node.host}:${node.port}` : node.host}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground truncate" title={node.detail}>
                          {isNodeRestarting ? "Restarting..." : node.detail}
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
                Click a container card to view its live logs below.
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
                const isRestarting = restarting === c.id;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setSelectedContainer(c.id)}
                    onContextMenu={(e) => handleContextMenu(e, c.id, c.label)}
                    className={cn(
                      "rounded-lg border p-3 transition-colors text-left w-full cursor-pointer",
                      "hover:opacity-90 hover:ring-2 hover:ring-blue-400/50",
                      config.bg,
                      "border-current/20",
                      isSelected && "ring-2 ring-blue-500 ring-offset-2",
                      isRestarting && "opacity-60 animate-pulse"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-sm">{c.label}</span>
                      <div className="flex items-center gap-1.5">
                        {isRestarting && <Loader2 className="h-3 w-3 animate-spin text-amber-500" />}
                        <StatusBadge status={isRestarting ? "restarting" : c.status} />
                      </div>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground font-mono truncate" title={c.detail}>
                      {isRestarting ? "Restarting..." : c.detail}
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
                    <div className="mt-1 text-xs text-muted-foreground">
                      {isSelected ? "✓ Viewing logs" : "Click to view logs"}
                      <span className="text-muted-foreground/40 ml-1">• Right-click for options</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </CardContent>
        )}
      </Card>

      {/* Container Logs — SSE Streaming */}
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
                {streaming && (
                  <span className="inline-flex items-center gap-1 text-xs font-normal text-green-400">
                    <Circle className="h-2 w-2 fill-green-400 animate-pulse" />
                    Live
                  </span>
                )}
              </CardTitle>
              <CardDescription className="text-zinc-400 mt-1">
                Real-time log streaming (tail -f). Auto-scrolls when at bottom.
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
                onClick={() => startStream(selectedContainer)}
                disabled={!selectedContainer}
                className="border-zinc-600 text-zinc-300 hover:bg-zinc-700"
                title="Reconnect SSE stream"
              >
                <RefreshCw className="h-4 w-4 mr-2" />
                Reconnect
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={fetchLogsFallback}
                disabled={!selectedContainer}
                className="border-zinc-600 text-zinc-300 hover:bg-zinc-700"
                title="Fetch last 500 lines (non-streaming)"
              >
                Snapshot
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0 bg-[#1a1b26]">
          <div
            ref={logsContainerRef}
            onScroll={handleScroll}
            className="h-[560px] overflow-y-auto p-3 font-mono text-[11.5px] leading-[18px] text-zinc-300 scrollbar-thin whitespace-pre-wrap break-all"
            style={{ contain: "layout" }}
          >
            {logsLoading ? (
              <div className="flex items-center justify-center h-full gap-2 text-zinc-500">
                <RefreshCw className="h-4 w-4 animate-spin" />
                Connecting to log stream...
              </div>
            ) : logsError ? (
              <div className="flex flex-col items-center justify-center h-full gap-2 text-amber-500">
                <AlertCircle className="h-8 w-8" />
                <span>{logsError}</span>
                <span className="text-xs text-zinc-500">Ensure Docker socket is mounted: /var/run/docker.sock</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => startStream(selectedContainer)}
                  className="mt-2 border-zinc-600 text-zinc-300 hover:bg-zinc-700"
                >
                  Reconnect
                </Button>
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
                <span>Waiting for log data...</span>
                <span className="text-xs">Logs will appear here as they are generated.</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Context Menu */}
      {ctxMenu && (
        <div
          ref={ctxRef}
          className="fixed z-50 min-w-[180px] rounded-lg border bg-popover p-1 shadow-lg animate-in fade-in-0 zoom-in-95"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
        >
          <div className="px-2 py-1.5 text-xs font-semibold text-muted-foreground border-b mb-1">
            {ctxMenu.label}
          </div>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent transition-colors"
            onClick={() => {
              setSelectedContainer(ctxMenu.containerId);
              setCtxMenu(null);
            }}
          >
            <Eye className="h-4 w-4" />
            View Logs
          </button>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent transition-colors text-amber-600 dark:text-amber-400"
            onClick={() => {
              if (confirm(`'${ctxMenu.label}' 컨테이너를 재시작하시겠습니까?`)) {
                handleRestart(ctxMenu.containerId);
              } else {
                setCtxMenu(null);
              }
            }}
          >
            <RotateCcw className="h-4 w-4" />
            Restart Container
          </button>
        </div>
      )}
    </div>
  );
}
