import { useEffect, useState, useCallback } from "react";
import { RefreshCw, AlertCircle, CheckCircle2, HelpCircle, Server, Database, Cpu } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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
  ok: { color: "text-emerald-600", bg: "bg-emerald-500/20", icon: CheckCircle2 },
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

  const leftCol = ["client", "gateway", "api_server"];
  const rightCol = ["mysql", "redis", "chromadb", "mcp_server", "ollama"];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">System Monitor</h1>
          <p className="text-sm text-muted-foreground">
            Architecture diagram and connectivity status. Refreshes every 15s.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchArchitecture} disabled={loading}>
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
              Check: <code className="rounded bg-muted px-1">docker compose ps</code> and{" "}
              <code className="rounded bg-muted px-1">docker compose restart gateway api-server</code>
            </p>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-5 w-5" />
            System Architecture
          </CardTitle>
          <CardDescription>
            Nodes and connections. Green = OK, Red = Error, Amber = Unavailable.
          </CardDescription>
        </CardHeader>
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
                            <Database className="h-4 w-4" />
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
      </Card>

      {/* Connection matrix */}
      {data && (
        <Card>
          <CardHeader>
            <CardTitle>Connection Status</CardTitle>
            <CardDescription>API Server → Backend services</CardDescription>
          </CardHeader>
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
        </Card>
      )}
    </div>
  );
}
