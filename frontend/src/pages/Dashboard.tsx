import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ClipboardList,
  Loader2,
  CheckCircle2,
  AlertCircle,
  XCircle,
  Activity,
} from "lucide-react";
import {
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  ResponsiveContainer,
} from "recharts";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { StaggerContainer, StaggerItem } from "@/components/motion/stagger-children";
import { FadeIn } from "@/components/motion/fade-in";

interface HealthStatus {
  status: string;
  checks: Record<string, { status: string; detail?: string; models_count?: number }>;
}

interface Order {
  id: number;
  order_code: string;
  project_name: string;
  status: string;
  progress_pct: number;
  created_at: string;
}

interface OrderSummary {
  total: number;
  orders: Order[];
}

const STATUS_COLORS: Record<string, string> = {
  completed: "#22c55e",
  running: "#3b82f6",
  pending: "#a3a3a3",
  failed: "#ef4444",
};

const statusBadgeVariant = (s: string) => {
  switch (s) {
    case "completed": return "success" as const;
    case "failed": return "destructive" as const;
    case "running": return "info" as const;
    default: return "secondary" as const;
  }
};

function CountUp({ target }: { target: number }) {
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (target === 0) return;
    let start = 0;
    const step = Math.max(1, Math.ceil(target / 20));
    const interval = setInterval(() => {
      start += step;
      if (start >= target) {
        setVal(target);
        clearInterval(interval);
      } else {
        setVal(start);
      }
    }, 30);
    return () => clearInterval(interval);
  }, [target]);
  return <>{val}</>;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [orders, setOrders] = useState<OrderSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<HealthStatus>("/health/detailed").catch(() => null),
      api.get<OrderSummary>("/orders?page_size=5").catch(() => null),
    ]).then(([h, o]) => {
      setHealth(h);
      setOrders(o);
      setLoading(false);
    });
  }, []);

  const allOrders = orders?.orders ?? [];
  const counts = {
    total: orders?.total ?? 0,
    running: allOrders.filter((o) => o.status === "running" || o.status === "preprocessing" || o.status === "rag_enrichment" || o.status === "report_generation").length,
    completed: allOrders.filter((o) => o.status === "completed").length,
    failed: allOrders.filter((o) => o.status === "failed").length,
  };

  const pieData = Object.entries(
    allOrders.reduce<Record<string, number>>((acc, o) => {
      acc[o.status] = (acc[o.status] || 0) + 1;
      return acc;
    }, {})
  ).map(([name, value]) => ({ name, value }));

  const kpiCards = [
    { label: "Total Orders", value: counts.total, icon: ClipboardList, color: "text-foreground" },
    { label: "Running", value: counts.running, icon: Loader2, color: "text-blue-500" },
    { label: "Completed", value: counts.completed, icon: CheckCircle2, color: "text-emerald-500" },
    { label: "Failed", value: counts.failed, icon: AlertCircle, color: "text-red-500" },
  ];

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-40" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <div className="grid lg:grid-cols-2 gap-6">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>

      {/* KPI Cards */}
      <StaggerContainer className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {kpiCards.map((kpi) => {
          const Icon = kpi.icon;
          return (
            <StaggerItem key={kpi.label}>
              <Card>
                <CardContent className="flex items-center gap-4 p-5">
                  <div className={`rounded-lg bg-muted p-2.5 ${kpi.color}`}>
                    <Icon className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">{kpi.label}</p>
                    <p className="text-2xl font-bold">
                      <CountUp target={kpi.value} />
                    </p>
                  </div>
                </CardContent>
              </Card>
            </StaggerItem>
          );
        })}
      </StaggerContainer>

      {/* Middle Section: Chart + Service Health */}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* Pie Chart */}
        <FadeIn delay={0.1}>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Order Status Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={85}
                      paddingAngle={3}
                      dataKey="value"
                      animationBegin={0}
                      animationDuration={800}
                      animationEasing="ease-out"
                    >
                      {pieData.map((entry) => (
                        <Cell key={entry.name} fill={STATUS_COLORS[entry.name] || "#94a3b8"} />
                      ))}
                    </Pie>
                    <RTooltip />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
                  No order data yet
                </div>
              )}
              <div className="mt-2 flex flex-wrap justify-center gap-4">
                {pieData.map((d) => (
                  <div key={d.name} className="flex items-center gap-1.5 text-xs">
                    <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: STATUS_COLORS[d.name] || "#94a3b8" }} />
                    <span className="capitalize text-muted-foreground">{d.name}</span>
                    <span className="font-medium">{d.value}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </FadeIn>

        {/* Service Health */}
        <FadeIn delay={0.15}>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Service Health</CardTitle>
            </CardHeader>
            <CardContent>
              {health?.checks ? (
                <div className="space-y-3">
                  {Object.entries(health.checks).map(([name, check]) => (
                    <div key={name} className="flex items-center justify-between rounded-lg border px-4 py-3">
                      <div className="flex items-center gap-3">
                        <Activity className="h-4 w-4 text-muted-foreground" />
                        <span className="text-sm font-medium capitalize">{name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {check.models_count !== undefined && (
                          <span className="text-xs text-muted-foreground">{check.models_count} models</span>
                        )}
                        {check.status === "ok" ? (
                          <Badge variant="success" className="gap-1">
                            <CheckCircle2 className="h-3 w-3" /> Online
                          </Badge>
                        ) : check.status === "unavailable" ? (
                          <Badge variant="warning" className="gap-1">N/A</Badge>
                        ) : (
                          <Badge variant="destructive" className="gap-1">
                            <XCircle className="h-3 w-3" /> Error
                          </Badge>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">
                  Unable to fetch health status
                </div>
              )}
            </CardContent>
          </Card>
        </FadeIn>
      </div>

      {/* Recent Orders Table */}
      <FadeIn delay={0.2}>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Recent Orders</CardTitle>
          </CardHeader>
          <CardContent>
            {allOrders.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Order ID</TableHead>
                    <TableHead>Project</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Progress</TableHead>
                    <TableHead>Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {allOrders.map((order) => (
                    <TableRow
                      key={order.id}
                      className="cursor-pointer"
                      onClick={() => navigate(`/orders/${order.id}`)}
                    >
                      <TableCell className="font-mono text-primary">{order.order_code}</TableCell>
                      <TableCell>{order.project_name}</TableCell>
                      <TableCell>
                        <Badge variant={statusBadgeVariant(order.status)} className="capitalize">
                          {order.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Progress value={order.progress_pct} className="w-20" />
                          <span className="text-xs text-muted-foreground">{order.progress_pct}%</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {new Date(order.created_at).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" })}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <ClipboardList className="h-12 w-12 text-muted-foreground/40 mb-3" />
                <p className="text-sm text-muted-foreground">No orders yet</p>
                <p className="text-xs text-muted-foreground mt-1">Create your first order to get started</p>
              </div>
            )}
          </CardContent>
        </Card>
      </FadeIn>
    </div>
  );
}
