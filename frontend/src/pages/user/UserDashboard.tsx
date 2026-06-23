/**
 * UserDashboard — Analysis history for general users.
 * Shows a clean list of past analyses with status and quick actions.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { Order } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Plus,
  FlaskConical,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  ArrowRight,
  FileText,
  MessageSquare,
} from "lucide-react";

const STATUS_CONFIG: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  pending: { label: "Pending", icon: <Clock className="h-3.5 w-3.5" />, color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300" },
  running: { label: "Running", icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, color: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300" },
  preprocessing: { label: "Processing", icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, color: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300" },
  rag_enrichment: { label: "Enriching", icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, color: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300" },
  report_generation: { label: "Generating Report", icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, color: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300" },
  completed: { label: "Completed", icon: <CheckCircle2 className="h-3.5 w-3.5" />, color: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300" },
  failed: { label: "Failed", icon: <XCircle className="h-3.5 w-3.5" />, color: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300" },
};

export default function UserDashboard() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<Order[]>("/orders")
      .then((data) => setOrders(data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const activeOrders = orders.filter((o) => !["completed", "failed"].includes(o.status));
  const completedOrders = orders.filter((o) => o.status === "completed");

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">My Analyses</h1>
          <p className="text-muted-foreground mt-1">
            Manage and view your PTM analysis results
          </p>
        </div>
        <Button onClick={() => navigate("/app/new")} className="gap-2">
          <Plus className="h-4 w-4" />
          New Analysis
        </Button>
      </div>

      {loading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      ) : orders.length === 0 ? (
        /* Empty State */
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <div className="h-16 w-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
              <FlaskConical className="h-8 w-8 text-primary" />
            </div>
            <h3 className="text-lg font-semibold mb-2">No analyses yet</h3>
            <p className="text-muted-foreground text-center max-w-md mb-6">
              Upload your DIA-NN output files and let Mekii AI analyze your PTM data.
              Get kinase activity profiles, signaling cascades, and AI-generated reports.
            </p>
            <Button onClick={() => navigate("/app/new")} className="gap-2">
              <Plus className="h-4 w-4" />
              Start Your First Analysis
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-8">
          {/* Active Analyses */}
          {activeOrders.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                In Progress ({activeOrders.length})
              </h2>
              <div className="space-y-3">
                {activeOrders.map((order) => (
                  <AnalysisCard key={order.id} order={order} onClick={() => navigate(`/app/${order.id}`)} />
                ))}
              </div>
            </section>
          )}

          {/* Completed Analyses */}
          {completedOrders.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                Completed ({completedOrders.length})
              </h2>
              <div className="space-y-3">
                {completedOrders.map((order) => (
                  <AnalysisCard key={order.id} order={order} onClick={() => navigate(`/app/${order.id}`)} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function AnalysisCard({ order, onClick }: { order: Order; onClick: () => void }) {
  const status = STATUS_CONFIG[order.status] || STATUS_CONFIG.pending;
  const createdDate = new Date(order.created_at).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  return (
    <Card
      className="cursor-pointer hover:shadow-md transition-all hover:border-primary/30 group"
      onClick={onClick}
    >
      <CardContent className="flex items-center gap-4 py-4 px-5">
        {/* Icon */}
        <div className="h-10 w-10 rounded-lg bg-primary/5 flex items-center justify-center shrink-0">
          <FlaskConical className="h-5 w-5 text-primary" />
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-medium truncate">{order.project_name}</h3>
            <Badge variant="outline" className="text-[10px] shrink-0">
              {order.ptm_type === "ubiquitylation" ? "Ubiquitylation" : "Phosphorylation"}
            </Badge>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{createdDate}</span>
            <span>{order.species || "Unknown organism"}</span>
            {order.progress_pct > 0 && order.status !== "completed" && (
              <span className="font-mono">{order.progress_pct}%</span>
            )}
          </div>
        </div>

        {/* Status Badge */}
        <Badge className={`shrink-0 gap-1 ${status.color}`}>
          {status.icon}
          {status.label}
        </Badge>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
          {order.status === "completed" && (
            <>
              <Button variant="ghost" size="icon" className="h-8 w-8" title="View Report">
                <FileText className="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" className="h-8 w-8" title="Ask Mekii AI">
                <MessageSquare className="h-4 w-4" />
              </Button>
            </>
          )}
          <ArrowRight className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}
