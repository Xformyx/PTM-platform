import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { PlusCircle, ClipboardList, Play, ChevronDown, ChevronUp, ChevronsUpDown, AlertCircle, Trash2, Square } from "lucide-react";
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

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const fmt = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
  // "2026. 03. 19. 23:45" → "2026.03.19 23:45"
  return fmt.format(d).replace(/\.\s*/g, ".").replace(/\.$/, "").replace(/(\d{4}\.\d{2}\.\d{2})\.(\d{2}:\d{2})/, "$1 $2");
}

/** Elapsed time from started_at to completed_at (or now if still running). Format: HH:MM */
function fmtElapsed(order: Order): string {
  const start = order.started_at ? new Date(order.started_at).getTime() : null;
  if (!start) return "—";
  const end = (order.status === "completed" || order.status === "failed" || order.status === "cancelled") && order.completed_at
    ? new Date(order.completed_at).getTime()
    : Date.now();
  const ms = Math.max(0, end - start);
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

const statusBadgeVariant = (s: string) => {
  switch (s) {
    case "completed": return "success" as const;
    case "failed": return "destructive" as const;
    case "running": case "preprocessing": case "rag_enrichment": case "report_generation": return "info" as const;
    default: return "secondary" as const;
  }
};

type StatusFilter = "all" | "pending" | "running" | "completed" | "failed";
type SortField = "created_at" | "completed_at";
type SortDir = "asc" | "desc";

function SortIcon({ field, sort }: { field: SortField; sort: { field: SortField; dir: SortDir } | null }) {
  if (!sort || sort.field !== field) return <ChevronsUpDown className="h-3 w-3 ml-1 opacity-40" />;
  return sort.dir === "asc"
    ? <ChevronUp className="h-3 w-3 ml-1 text-primary" />
    : <ChevronDown className="h-3 w-3 ml-1 text-primary" />;
}

const ORDER_LIST_COL_WIDTHS_KEY = "ptm-order-list-col-pct-v1";
/** Percent widths — must sum to 100 */
const DEFAULT_COL_PCT = [12, 16, 9, 9, 9, 12, 8, 11, 11, 5] as const;
const N_COLS = DEFAULT_COL_PCT.length;
const MIN_COL_PCT = 4;

function loadOrderListColWidths(): number[] {
  try {
    const raw = localStorage.getItem(ORDER_LIST_COL_WIDTHS_KEY);
    if (!raw) return [...DEFAULT_COL_PCT];
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr) || arr.length !== N_COLS) return [...DEFAULT_COL_PCT];
    const nums = arr.map((x) => Number(x));
    if (nums.some((n) => !Number.isFinite(n) || n < MIN_COL_PCT)) return [...DEFAULT_COL_PCT];
    const sum = nums.reduce((a, b) => a + b, 0);
    if (Math.abs(sum - 100) > 0.5) return [...DEFAULT_COL_PCT];
    return nums;
  } catch {
    return [...DEFAULT_COL_PCT];
  }
}

function saveOrderListColWidths(widths: number[]) {
  try {
    localStorage.setItem(ORDER_LIST_COL_WIDTHS_KEY, JSON.stringify(widths));
  } catch {
    /* ignore quota / private mode */
  }
}

function ColResizeHandle({
  colIndex,
  onStart,
}: {
  colIndex: number;
  onStart: (colIndex: number, e: React.MouseEvent) => void;
}) {
  return (
    <span
      role="separator"
      aria-hidden
      title="열 경계를 드래그해 너비 조정"
      className="absolute right-0 top-0 z-20 h-full w-1.5 cursor-col-resize select-none hover:bg-primary/30 active:bg-primary/50"
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => onStart(colIndex, e)}
    />
  );
}

export default function OrderList() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir } | null>({ field: "created_at", dir: "desc" });
  const [expandedError, setExpandedError] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; order_code: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [colWidths, setColWidths] = useState<number[]>(() => loadOrderListColWidths());
  const colWidthsRef = useRef(colWidths);
  colWidthsRef.current = colWidths;
  const tableRef = useRef<HTMLTableElement>(null);
  const dragRef = useRef<{ index: number; startX: number; startWidths: number[] } | null>(null);

  const onColResizeMove = useCallback((e: MouseEvent) => {
    const d = dragRef.current;
    const tableEl = tableRef.current;
    if (!d || !tableEl) return;
    const tw = tableEl.offsetWidth || 1;
    const deltaPct = ((e.clientX - d.startX) / tw) * 100;
    const i = d.index;
    const a0 = d.startWidths[i];
    const b0 = d.startWidths[i + 1];
    let newA = a0 + deltaPct;
    let newB = b0 - deltaPct;
    if (newA < MIN_COL_PCT) {
      newB -= MIN_COL_PCT - newA;
      newA = MIN_COL_PCT;
    }
    if (newB < MIN_COL_PCT) {
      newA -= MIN_COL_PCT - newB;
      newB = MIN_COL_PCT;
    }
    newA = Math.max(MIN_COL_PCT, newA);
    newB = Math.max(MIN_COL_PCT, newB);
    const pairSum = a0 + b0;
    const scale = pairSum / (newA + newB);
    newA *= scale;
    newB = pairSum - newA;
    const next = [...d.startWidths];
    next[i] = Math.round(newA * 1000) / 1000;
    next[i + 1] = Math.round(newB * 1000) / 1000;
    setColWidths(next);
  }, []);

  const onColResizeEnd = useCallback(() => {
    window.removeEventListener("mousemove", onColResizeMove);
    window.removeEventListener("mouseup", onColResizeEnd);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    dragRef.current = null;
    saveOrderListColWidths(colWidthsRef.current);
  }, [onColResizeMove]);

  const startColResize = (colIndex: number, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = {
      index: colIndex,
      startX: e.clientX,
      startWidths: [...colWidthsRef.current],
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onColResizeMove);
    window.addEventListener("mouseup", onColResizeEnd);
  };

  useEffect(() => {
    return () => {
      window.removeEventListener("mousemove", onColResizeMove);
      window.removeEventListener("mouseup", onColResizeEnd);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [onColResizeMove, onColResizeEnd]);

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

  // Auto-poll every 5s while any order is running
  const hasRunning = orders.some((o) => isRunning(o.status));
  useEffect(() => {
    if (!hasRunning) return;
    const interval = setInterval(fetchOrders, 5000);
    return () => clearInterval(interval);
  }, [hasRunning]);

  const handleSort = (field: SortField) => {
    setSort((prev) =>
      prev?.field === field
        ? { field, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { field, dir: "desc" }
    );
  };

  const filtered = (() => {
    let list = filter === "all" ? orders : orders.filter((o) =>
      filter === "running" ? isRunning(o.status) : o.status === filter
    );
    if (sort) {
      list = [...list].sort((a, b) => {
        const va = a[sort.field] ? new Date(a[sort.field]!).getTime() : 0;
        const vb = b[sort.field] ? new Date(b[sort.field]!).getTime() : 0;
        return sort.dir === "asc" ? va - vb : vb - va;
      });
    }
    return list;
  })();

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
        <CardContent className="p-0 overflow-x-auto">
          {filtered.length > 0 ? (
            <Table ref={tableRef} className="w-full table-fixed min-w-[920px]">
              <colgroup>
                {colWidths.map((pct, i) => (
                  <col key={i} style={{ width: `${pct}%` }} />
                ))}
              </colgroup>
              <TableHeader>
                <TableRow>
                  <TableHead className="relative">
                    Order ID
                    <ColResizeHandle colIndex={0} onStart={startColResize} />
                  </TableHead>
                  <TableHead className="relative">
                    Project
                    <ColResizeHandle colIndex={1} onStart={startColResize} />
                  </TableHead>
                  <TableHead className="relative">
                    PTM Type
                    <ColResizeHandle colIndex={2} onStart={startColResize} />
                  </TableHead>
                  <TableHead className="relative">
                    Species
                    <ColResizeHandle colIndex={3} onStart={startColResize} />
                  </TableHead>
                  <TableHead className="relative">
                    Status
                    <ColResizeHandle colIndex={4} onStart={startColResize} />
                  </TableHead>
                  <TableHead className="relative">
                    Progress
                    <ColResizeHandle colIndex={5} onStart={startColResize} />
                  </TableHead>
                  <TableHead className="relative">
                    Elapsed
                    <ColResizeHandle colIndex={6} onStart={startColResize} />
                  </TableHead>
                  <TableHead
                    className="relative cursor-pointer select-none hover:bg-muted/50"
                    onClick={() => handleSort("created_at")}
                  >
                    <div className="flex items-center pr-1">
                      Created <SortIcon field="created_at" sort={sort} />
                    </div>
                    <ColResizeHandle colIndex={7} onStart={startColResize} />
                  </TableHead>
                  <TableHead
                    className="relative cursor-pointer select-none hover:bg-muted/50"
                    onClick={() => handleSort("completed_at")}
                  >
                    <div className="flex items-center pr-1">
                      Updated <SortIcon field="completed_at" sort={sort} />
                    </div>
                    <ColResizeHandle colIndex={8} onStart={startColResize} />
                  </TableHead>
                  <TableHead>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((order) => (
                  <TableRow
                    key={order.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/orders/${order.id}`)}
                  >
                    <TableCell className="truncate">
                      <Link
                        to={`/orders/${order.id}`}
                        className="font-mono text-primary hover:underline font-medium"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {order.order_code}
                      </Link>
                    </TableCell>
                    <TableCell className="truncate" title={order.project_name}>{order.project_name}</TableCell>
                    <TableCell className="capitalize truncate">{order.ptm_type}</TableCell>
                    <TableCell className="capitalize truncate">{order.species}</TableCell>
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
                    <TableCell className="font-mono text-muted-foreground whitespace-nowrap">
                      {fmtElapsed(order)}
                    </TableCell>
                    <TableCell
                      className="text-muted-foreground whitespace-nowrap"
                      title={order.created_by ? `Created by: ${order.created_by}` : undefined}
                    >
                      {fmtDate(order.created_at)}
                    </TableCell>
                    <TableCell
                      className="text-muted-foreground whitespace-nowrap"
                      title={order.run_by ? `Run by: ${order.run_by}` : undefined}
                    >
                      {order.status === "completed" ? fmtDate(order.completed_at) : "—"}
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
