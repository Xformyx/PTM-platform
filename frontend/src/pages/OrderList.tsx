import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { PlusCircle, ClipboardList, Play, ChevronDown, AlertCircle, Trash2, Square } from "lucide-react";
import { api } from "@/lib/api";
import type { Order } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const statusBadgeVariant = (s: string) => {
  switch (s) {
    case "completed": return "success" as const;
    case "failed": return "destructive" as const;
    case "running": case "preprocessing": case "rag_enrichment": case "report_generation": return "info" as const;
    default: return "secondary" as const;
  }
};

type StatusFilter = "all" | "pending" | "running" | "completed" | "failed";

export default function OrderList() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [expandedError, setExpandedError] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; order_code: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchOrders = () => {
    api
      .get<{ orders: Order[]; total: number }>("/orders")
      .then((data) => {
        setOrders(data.orders);
        setTotal(data.total);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchOrders(); }, []);

  const handleRun = (e: React.MouseEvent, orderId: number) => {
    e.stopPropagation();
    navigate(`/orders/${orderId}?run=1`);
  };

  const handleDeleteClick = (e: React.MouseEvent, order: Order) => {
    e.stopPropagation();
    setDeleteTarget({ id: order.id, order_code: order.order_code });
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/orders/${deleteTarget.id}`);
      setDeleteTarget(null);
      fetchOrders();
    } catch (err: unknown) {
      alert((err as { message?: string })?.message || "Failed to delete order");
    } finally {
      setDeleting(false);
    }
  };

  const handleStop = async (e: React.MouseEvent, orderId: number) => {
    e.stopPropagation();
    try {
      await api.post(`/orders/${orderId}/cancel`);
      fetchOrders();
    } catch (err: any) {
      alert(err.message || "Failed to stop");
    }
  };

  const isRunning = (s: string) => ["running", "preprocessing", "rag_enrichment", "report_generation", "queued"].includes(s);
  const filtered = filter === "all" ? orders : orders.filter((o) => (filter === "running" ? isRunning(o.status) : o.status === filter));
  const filters: StatusFilter[] = ["all", "pending", "running", "completed", "failed"];

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-[400px]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Orders</h1>
          <p className="text-sm text-muted-foreground">{total} total orders</p>
        </div>
        <Button asChild>
          <Link to="/orders/new">
            <PlusCircle className="mr-2 h-4 w-4" />
            New Order
          </Link>
        </Button>
      </div>

      {/* Filter Badges */}
      <div className="flex gap-2">
        {filters.map((f) => (
          <Badge
            key={f}
            variant={filter === f ? "default" : "outline"}
            className="cursor-pointer capitalize"
            onClick={() => setFilter(f)}
          >
            {f}
          </Badge>
        ))}
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {filtered.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Order ID</TableHead>
                  <TableHead>Project</TableHead>
                  <TableHead>PTM Type</TableHead>
                  <TableHead>Species</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-32">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((order) => (
                  <TableRow
                    key={order.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/orders/${order.id}`)}
                  >
                    <TableCell>
                      <Link
                        to={`/orders/${order.id}`}
                        className="font-mono text-primary hover:underline font-medium"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {order.order_code}
                      </Link>
                    </TableCell>
                    <TableCell>{order.project_name}</TableCell>
                    <TableCell className="capitalize">{order.ptm_type}</TableCell>
                    <TableCell className="capitalize">{order.species}</TableCell>
                    <TableCell>
                      <Badge variant={statusBadgeVariant(order.status)} className="capitalize">
                        {order.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 min-w-[120px]">
                        <Progress
                          value={order.progress_pct}
                          className="w-20"
                          indicatorClassName={order.status === "failed" ? "bg-destructive" : undefined}
                        />
                        <span className="text-xs text-muted-foreground whitespace-nowrap">
                          {Math.round(order.progress_pct)}%
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(order.created_at).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" })}
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1">
                        {isRunning(order.status) ? (
                          <Button
                            size="sm"
                            variant="destructive"
                            className="h-7 gap-1 min-w-[60px]"
                            onClick={(e) => handleStop(e, order.id)}
                          >
                            <Square className="h-3 w-3" /> Stop
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 gap-1 min-w-[60px]"
                            onClick={(e) => handleRun(e, order.id)}
                          >
                            <Play className="h-3 w-3" /> {order.status === "completed" ? "Re-Run" : "Run"}
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 w-7 p-0 text-destructive hover:text-destructive hover:bg-destructive/10"
                          onClick={(e) => handleDeleteClick(e, order)}
                          disabled={isRunning(order.status)}
                          title="Delete order"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                        {order.status === "failed" && order.error_message && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedError(expandedError === order.id ? null : order.id);
                            }}
                            title="Show error"
                          >
                            <ChevronDown className={`h-3 w-3 transition-transform ${expandedError === order.id ? "rotate-180" : ""}`} />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="flex flex-col items-center justify-center py-16">
              <ClipboardList className="h-12 w-12 text-muted-foreground/40 mb-3" />
              <p className="text-sm font-medium text-muted-foreground">No orders found</p>
              <p className="text-xs text-muted-foreground mt-1">
                {filter !== "all" ? "Try changing the filter" : 'Click "New Order" to create one'}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Delete confirmation dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-md" onPointerDownOutside={(e) => e.preventDefault()}>
          <DialogHeader>
            <DialogTitle>Order 삭제 확인</DialogTitle>
            <DialogDescription>
              <strong>{deleteTarget?.order_code}</strong> Order를 정말 삭제하시겠습니까?
              <br />
              <span className="text-destructive font-medium">
                data/inputs, data/outputs 의 해당 디렉토리도 함께 삭제됩니다.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteConfirm} disabled={deleting}>
              {deleting ? "삭제 중..." : "삭제"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Expanded error messages */}
      <AnimatePresence>
        {expandedError && orders.find((o) => o.id === expandedError && o.error_message) && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <Card className="border-destructive/50">
              <CardContent className="flex items-start gap-3 p-4">
                <AlertCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-destructive">
                    {orders.find((o) => o.id === expandedError)?.order_code}
                  </p>
                  <p className="text-sm text-destructive/80 mt-1">
                    {orders.find((o) => o.id === expandedError)?.error_message}
                  </p>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
