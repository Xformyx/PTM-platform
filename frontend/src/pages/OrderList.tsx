import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { PlusCircle, ClipboardList, Play, ChevronDown, ChevronUp, ChevronsUpDown, AlertCircle, Trash2, Square, Share2, Loader2, GitCompareArrows, StretchHorizontal, UnfoldHorizontal } from "lucide-react";
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
import { ShareOrderModal } from "@/components/ShareOrderModal";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";

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

const statusBadgeVariant = (s: string): { variant: "success" | "destructive" | "info" | "warning" | "secondary" | "outline"; className?: string } => {
  switch (s) {
    case "completed": return { variant: "success" };
    case "failed": return { variant: "destructive" };
    case "cancelled": return { variant: "outline" };
    case "registered": return { variant: "secondary", className: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" };
    case "queued": return { variant: "warning" };
    case "preprocessing": return { variant: "info", className: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400" };
    case "rag_enrichment": return { variant: "info", className: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400" };
    case "report_generation": return { variant: "info", className: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400" };
    default: return { variant: "secondary" };
  }
};

type StatusFilter = "all" | "registered" | "running" | "completed" | "failed";
type SortField = "created_at" | "completed_at";
type SortDir = "asc" | "desc";
type TableLayoutMode = "fit" | "expand";

const ORDER_LIST_LAYOUT_KEY = "ptm-order-list-layout-mode";

function loadTableLayoutMode(): TableLayoutMode {
  try {
    const raw = localStorage.getItem(ORDER_LIST_LAYOUT_KEY);
    return raw === "expand" ? "expand" : "fit";
  } catch {
    return "fit";
  }
}

function saveTableLayoutMode(mode: TableLayoutMode) {
  try {
    localStorage.setItem(ORDER_LIST_LAYOUT_KEY, mode);
  } catch {
    /* ignore */
  }
}

function SortIcon({ field, sort }: { field: SortField; sort: { field: SortField; dir: SortDir } | null }) {
  if (!sort || sort.field !== field) return <ChevronsUpDown className="h-3 w-3 ml-1 opacity-40" />;
  return sort.dir === "asc"
    ? <ChevronUp className="h-3 w-3 ml-1 text-primary" />
    : <ChevronDown className="h-3 w-3 ml-1 text-primary" />;
}

const ORDER_LIST_COL_WIDTHS_KEY = "ptm-order-list-col-pct-v2";
/** Percent widths — must sum to 100 */
/** Last column (Action) kept ≥6% so Run/Delete aren’t flush to the table edge */
const DEFAULT_COL_PCT = [11, 13, 8, 8, 8, 11, 7, 10, 11, 13] as const;
const N_COLS = DEFAULT_COL_PCT.length;
const MIN_COL_PCT = 4;

function loadOrderListColWidths(): number[] {
  try {
    const raw = localStorage.getItem(ORDER_LIST_COL_WIDTHS_KEY);
    if (!raw) return [...DEFAULT_COL_PCT];
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr) || arr.length !== N_COLS) return [...DEFAULT_COL_PCT];
    let nums = arr.map((x) => Number(x));
    if (nums.some((n) => !Number.isFinite(n) || n <= 0)) return [...DEFAULT_COL_PCT];
    let sum = nums.reduce((a, b) => a + b, 0);
    if (sum <= 0) return [...DEFAULT_COL_PCT];
    if (Math.abs(sum - 100) > 2) {
      nums = nums.map((n) => (n / sum) * 100);
      sum = 100;
    }
    nums = nums.map((n) => Math.max(MIN_COL_PCT, n));
    sum = nums.reduce((a, b) => a + b, 0);
    nums = nums.map((n) => (n / sum) * 100);
    const drift = 100 - nums.reduce((a, b) => a + b, 0);
    nums[N_COLS - 1] = nums[N_COLS - 1] + drift;
    return nums.map((n) => Math.round(n * 1000) / 1000);
  } catch {
    return [...DEFAULT_COL_PCT];
  }
}

function saveOrderListColWidths(widths: number[]) {
  try {
    if (!Array.isArray(widths) || widths.length !== N_COLS) return;
    if (widths.some((w) => !Number.isFinite(w))) return;
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
  onStart: (colIndex: number, e: React.PointerEvent<HTMLSpanElement>) => void;
}) {
  return (
    <span
      role="separator"
      aria-hidden
      title="열 경계를 드래그해 너비 조정"
      tabIndex={-1}
      className="absolute right-0 top-0 z-20 h-full w-1.5 touch-none cursor-col-resize select-none hover:bg-primary/30 active:bg-primary/50"
      onClick={(e) => e.stopPropagation()}
      onPointerDown={(e) => {
        if (!e.isPrimary) return;
        e.preventDefault();
        e.stopPropagation();
        (e.currentTarget as HTMLSpanElement).setPointerCapture(e.pointerId);
        onStart(colIndex, e);
      }}
    />
  );
}

export default function OrderList() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<{ field: SortField; dir: SortDir } | null>({ field: "created_at", dir: "desc" });
  const [expandedError, setExpandedError] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; order_code: string } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [shareTarget, setShareTarget] = useState<{ id: number; order_code: string } | null>(null);
  const [stoppingOrderId, setStoppingOrderId] = useState<number | null>(null);
  const stopRequestRef = useRef(false);
  const [startingOrderId, setStartingOrderId] = useState<number | null>(null);
  const [compareSelection, setCompareSelection] = useState<number[]>([]);
  const [tableLayout, setTableLayout] = useState<TableLayoutMode>(() => loadTableLayoutMode());
  const isExpandLayout = tableLayout === "expand";

  const [colWidths, setColWidths] = useState<number[]>(() => loadOrderListColWidths());
  const colWidthsRef = useRef<number[]>(colWidths);
  const tableRef = useRef<HTMLTableElement>(null);
  const dragRef = useRef<{
    index: number;
    startX: number;
    startWidths: number[];
    pointerId: number;
    handle: HTMLElement;
  } | null>(null);
  const persistColsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** After React commits colWidths — ref + localStorage (avoids Firefox losing mouseup vs state). */
  useEffect(() => {
    colWidthsRef.current = colWidths;
    if (persistColsTimer.current) clearTimeout(persistColsTimer.current);
    persistColsTimer.current = setTimeout(() => {
      persistColsTimer.current = null;
      saveOrderListColWidths(colWidths);
    }, 120);
    return () => {
      if (persistColsTimer.current) clearTimeout(persistColsTimer.current);
    };
  }, [colWidths]);

  const onColResizeMove = useCallback((e: PointerEvent) => {
    const d = dragRef.current;
    const tableEl = tableRef.current;
    if (!d || !tableEl || e.pointerId !== d.pointerId) return;
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
    colWidthsRef.current = next;
    setColWidths(next);
  }, []);

  const onColResizeEnd = useCallback((e: PointerEvent) => {
    const d = dragRef.current;
    if (!d || e.pointerId !== d.pointerId) return;
    window.removeEventListener("pointermove", onColResizeMove);
    window.removeEventListener("pointerup", onColResizeEnd);
    window.removeEventListener("pointercancel", onColResizeEnd);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    try {
      d.handle.releasePointerCapture(d.pointerId);
    } catch {
      /* already released */
    }
    dragRef.current = null;
  }, [onColResizeMove]);

  const startColResize = (colIndex: number, e: React.PointerEvent<HTMLSpanElement>) => {
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const handle = e.currentTarget;
    dragRef.current = {
      index: colIndex,
      startX: e.clientX,
      startWidths: [...colWidthsRef.current],
      pointerId: e.pointerId,
      handle,
    };
    window.addEventListener("pointermove", onColResizeMove);
    window.addEventListener("pointerup", onColResizeEnd);
    window.addEventListener("pointercancel", onColResizeEnd);
  };

  useEffect(() => {
    return () => {
      const d = dragRef.current;
      if (d) {
        try {
          d.handle.releasePointerCapture(d.pointerId);
        } catch {
          /* ignore */
        }
        dragRef.current = null;
      }
      window.removeEventListener("pointermove", onColResizeMove);
      window.removeEventListener("pointerup", onColResizeEnd);
      window.removeEventListener("pointercancel", onColResizeEnd);
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

  const handleRun = async (e: React.MouseEvent, order: Order) => {
    e.stopPropagation();
    if (startingOrderId !== null || stoppingOrderId !== null) return;
    setStartingOrderId(order.id);
    try {
      await api.post(`/orders/${order.id}/start`);
      fetchOrders();
    } catch (err: unknown) {
      alert((err as { message?: string })?.message || "Failed to start");
    } finally {
      setStartingOrderId(null);
    }
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
    if (stopRequestRef.current) return;
    stopRequestRef.current = true;
    flushSync(() => {
      setStoppingOrderId(orderId);
    });
    try {
      await api.post(`/orders/${orderId}/cancel`);
      fetchOrders();
    } catch (err: any) {
      alert(err.message || "Failed to stop");
    } finally {
      stopRequestRef.current = false;
      setStoppingOrderId(null);
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

  const filters: StatusFilter[] = ["all", "registered", "running", "completed", "failed"];

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
        <div className="flex items-center gap-2">
          {compareSelection.length === 2 && (
            <Button
              variant="outline"
              className="border-primary text-primary hover:bg-primary/10"
              onClick={() => navigate(`/admin/compare?a=${compareSelection[0]}&b=${compareSelection[1]}`)}
            >
              <GitCompareArrows className="mr-2 h-4 w-4" />
              Compare ({compareSelection.length})
            </Button>
          )}
          {compareSelection.length === 1 && (
            <Badge variant="outline" className="text-muted-foreground py-1">
              Select 1 more to compare
            </Badge>
          )}
          <Button asChild>
            <Link to="/admin/orders/new">
              <PlusCircle className="mr-2 h-4 w-4" />
              New Order
            </Link>
          </Button>
        </div>
      </div>

      {/* Filter Badges + layout mode */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
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
        <div
          className="inline-flex items-center rounded-md border bg-background p-0.5"
          role="group"
          aria-label="Table column layout"
        >
          <Button
            type="button"
            size="sm"
            variant={tableLayout === "fit" ? "secondary" : "ghost"}
            className="h-7 px-2.5 text-xs gap-1.5"
            title="Fit columns to window (truncate long text)"
            onClick={() => {
              setTableLayout("fit");
              saveTableLayoutMode("fit");
            }}
          >
            <StretchHorizontal className="h-3.5 w-3.5" />
            Fit
          </Button>
          <Button
            type="button"
            size="sm"
            variant={tableLayout === "expand" ? "secondary" : "ghost"}
            className="h-7 px-2.5 text-xs gap-1.5"
            title="Show full column text with horizontal scroll"
            onClick={() => {
              setTableLayout("expand");
              saveTableLayoutMode("expand");
            }}
          >
            <UnfoldHorizontal className="h-3.5 w-3.5" />
            Full
          </Button>
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          {filtered.length > 0 ? (
            <Table
              ref={tableRef}
              className={cn(
                "w-full",
                isExpandLayout ? "table-auto min-w-max" : "table-fixed min-w-[1200px]"
              )}
            >
              {!isExpandLayout && (
                <colgroup>
                  <col style={{ width: "36px" }} />
                  {colWidths.map((pct, i) => (
                    <col key={i} style={{ width: `${pct}%` }} />
                  ))}
                </colgroup>
              )}
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8 px-2">
                    <span className="sr-only">Compare</span>
                  </TableHead>
                  <TableHead className={cn("relative", isExpandLayout && "whitespace-nowrap")}>
                    Order ID
                    {!isExpandLayout && <ColResizeHandle colIndex={0} onStart={startColResize} />}
                  </TableHead>
                  <TableHead className={cn("relative", isExpandLayout && "whitespace-nowrap")}>
                    Project
                    {!isExpandLayout && <ColResizeHandle colIndex={1} onStart={startColResize} />}
                  </TableHead>
                  <TableHead className={cn("relative", isExpandLayout && "whitespace-nowrap")}>
                    PTM Type
                    {!isExpandLayout && <ColResizeHandle colIndex={2} onStart={startColResize} />}
                  </TableHead>
                  <TableHead className={cn("relative", isExpandLayout && "whitespace-nowrap")}>
                    Species
                    {!isExpandLayout && <ColResizeHandle colIndex={3} onStart={startColResize} />}
                  </TableHead>
                  <TableHead className={cn("relative", isExpandLayout && "whitespace-nowrap")}>
                    Status
                    {!isExpandLayout && <ColResizeHandle colIndex={4} onStart={startColResize} />}
                  </TableHead>
                  <TableHead className={cn("relative", isExpandLayout && "whitespace-nowrap")}>
                    Progress
                    {!isExpandLayout && <ColResizeHandle colIndex={5} onStart={startColResize} />}
                  </TableHead>
                  <TableHead className={cn("relative", isExpandLayout && "whitespace-nowrap")}>
                    Elapsed
                    {!isExpandLayout && <ColResizeHandle colIndex={6} onStart={startColResize} />}
                  </TableHead>
                  <TableHead
                    className={cn(
                      "relative cursor-pointer select-none hover:bg-muted/50",
                      isExpandLayout && "whitespace-nowrap"
                    )}
                    onClick={() => handleSort("created_at")}
                  >
                    <div className="flex items-center pr-1">
                      Created <SortIcon field="created_at" sort={sort} />
                    </div>
                    {!isExpandLayout && <ColResizeHandle colIndex={7} onStart={startColResize} />}
                  </TableHead>
                  <TableHead
                    className={cn(
                      "relative cursor-pointer select-none hover:bg-muted/50",
                      isExpandLayout && "whitespace-nowrap"
                    )}
                    onClick={() => handleSort("completed_at")}
                  >
                    <div className="flex items-center pr-1">
                      Updated <SortIcon field="completed_at" sort={sort} />
                    </div>
                    {!isExpandLayout && <ColResizeHandle colIndex={8} onStart={startColResize} />}
                  </TableHead>
                  <TableHead className={cn("pr-5", isExpandLayout && "whitespace-nowrap")}>Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((order) => (
                  <TableRow
                    key={order.id}
                    className={cn("cursor-pointer", compareSelection.includes(order.id) && "bg-primary/5")}
                    onClick={() => navigate(`/admin/orders/${order.id}`)}
                  >
                    <TableCell className="px-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary cursor-pointer"
                        checked={compareSelection.includes(order.id)}
                        disabled={order.status !== "completed" || (!compareSelection.includes(order.id) && compareSelection.length >= 2)}
                        title={order.status !== "completed" ? "Only completed orders can be compared" : compareSelection.length >= 2 && !compareSelection.includes(order.id) ? "Max 2 orders" : "Select for comparison"}
                        onChange={() => {
                          setCompareSelection((prev) =>
                            prev.includes(order.id)
                              ? prev.filter((id) => id !== order.id)
                              : [...prev, order.id]
                          );
                        }}
                      />
                    </TableCell>
                    <TableCell
                      className={cn(isExpandLayout ? "whitespace-nowrap" : "truncate")}
                      title={isExpandLayout ? undefined : order.order_code}
                    >
                      <Link
                        to={`/admin/orders/${order.id}`}
                        className="font-mono text-primary hover:underline font-medium"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {order.order_code}
                      </Link>
                    </TableCell>
                    <TableCell
                      className={cn(isExpandLayout ? "whitespace-nowrap" : "truncate")}
                      title={isExpandLayout ? undefined : order.project_name}
                    >
                      <div className={cn("flex items-center gap-1.5", !isExpandLayout && "min-w-0")}>
                        <span className={cn(!isExpandLayout && "truncate")}>{order.project_name}</span>
                        {order.is_shared && (
                          <Badge
                            variant="outline"
                            className="shrink-0 text-[10px] h-4 px-1.5 border-amber-400 text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30"
                          >
                            Shared
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className={cn("capitalize", isExpandLayout ? "whitespace-nowrap" : "truncate")}>
                      {order.ptm_type}
                    </TableCell>
                    <TableCell className={cn("capitalize", isExpandLayout ? "whitespace-nowrap" : "truncate")}>
                      {order.species}
                    </TableCell>
                    <TableCell>
                      {(() => {
                        const isHalted = order.stage_detail?.startsWith("Halted:");
                        if (isHalted) {
                          return (
                            <Badge variant="destructive" className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                              Halted
                            </Badge>
                          );
                        }
                        const badge = statusBadgeVariant(order.status);
                        const label = order.status === "rag_enrichment" ? "RAG Enrichment"
                          : order.status === "report_generation" ? "Report Gen."
                          : order.status;
                        return (
                          <Badge variant={badge.variant} className={`capitalize ${badge.className ?? ""}`}>
                            {label}
                          </Badge>
                        );
                      })()}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        {(() => {
                          const stageWeights: Record<string, [number, number]> = { preprocessing: [0, 15], rag_enrichment: [15, 50], report_generation: [50, 100] };
                          const raw = order.status === "completed" ? 100 : order.progress_pct;
                          const range = stageWeights[order.status];
                          const displayPct = order.status === "completed" ? 100
                            : range ? Math.round(range[0] + (Math.min(Math.max(raw, 0), 100) / 100) * (range[1] - range[0]))
                            : raw;
                          return (
                            <>
                              <Progress
                                value={displayPct}
                                className="w-16"
                                indicatorClassName={
                                  order.status === "failed" ? "bg-destructive"
                                    : order.stage_detail?.startsWith("Halted:") ? "bg-red-400"
                                    : undefined
                                }
                              />
                              <span className="text-xs text-muted-foreground whitespace-nowrap">
                                {Math.round(displayPct)}%
                              </span>
                            </>
                          );
                        })()}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground whitespace-nowrap overflow-hidden">
                      {fmtElapsed(order)}
                    </TableCell>
                    <TableCell
                      className="text-muted-foreground whitespace-nowrap overflow-hidden"
                      title={order.created_by ? `Created by: ${order.created_by}` : undefined}
                    >
                      {fmtDate(order.created_at)}
                    </TableCell>
                    <TableCell
                      className="text-muted-foreground whitespace-nowrap overflow-hidden"
                      title={order.run_by ? `Run by: ${order.run_by}` : undefined}
                    >
                      {order.status === "completed" ? fmtDate(order.completed_at) : "—"}
                    </TableCell>
                    <TableCell className="pr-5" onClick={(e) => e.stopPropagation()}>
                      {(() => {
                        const isReadOnly = order.is_shared && order.share_access === "read_only";
                        const isOwn = !order.is_shared;
                        return (
                          <div className="flex items-center justify-end gap-1.5">
                            {/* Run/Stop — hidden for read-only shared */}
                            {!isReadOnly && (
                              isRunning(order.status) ? (
                                <Button
                                  size="sm"
                                  variant="destructive"
                                  className={cn(
                                    "h-7 gap-1 min-w-[60px]",
                                    stoppingOrderId !== null && "opacity-80 cursor-wait",
                                  )}
                                  disabled={stoppingOrderId !== null}
                                  onClick={(e) => handleStop(e, order.id)}
                                >
                                  {stoppingOrderId === order.id ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    <Square className="h-3 w-3" />
                                  )}
                                  {stoppingOrderId === order.id ? "Stopping…" : "Stop"}
                                </Button>
                              ) : (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className={cn(
                                    "h-7 gap-1 min-w-[60px]",
                                    startingOrderId !== null && "opacity-80 cursor-wait",
                                  )}
                                  disabled={startingOrderId !== null || stoppingOrderId !== null}
                                  onClick={(e) => void handleRun(e, order)}
                                >
                                  {startingOrderId === order.id ? (
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                  ) : (
                                    <Play className="h-3 w-3" />
                                  )}
                                  {startingOrderId === order.id
                                    ? "Starting…"
                                    : order.status === "completed"
                                      ? "Re-Run"
                                      : "Run"}
                                </Button>
                              )
                            )}
                            {/* Share button — only for own orders */}
                            {isOwn && (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 w-7 p-0 text-muted-foreground hover:text-primary"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setShareTarget({ id: order.id, order_code: order.order_code });
                                }}
                                title="Share order"
                              >
                                <Share2 className="h-3.5 w-3.5" />
                              </Button>
                            )}
                            {/* Delete — hidden for read-only shared */}
                            {!isReadOnly && (
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
                            )}
                            {/* Error expand */}
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
                        );
                      })()}
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

      {/* Stop-in-progress overlay (Order detail과 동일 — 즉시 피드백, 중복 클릭 방지) */}
      {stoppingOrderId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-background rounded-lg shadow-lg p-6 max-w-md w-full mx-4 flex flex-col gap-3">
            <div className="flex items-center gap-3 text-lg font-semibold">
              <Loader2 className="h-6 w-6 shrink-0 animate-spin text-primary" />
              분석을 멈추는 중
            </div>
            <p className="text-sm text-muted-foreground">
              서버에 중단 요청을 보내고 있습니다. 백그라운드 워커와 LLM이 처리 중일 수 있어 잠시 걸릴 수 있습니다.
            </p>
            {orders.find((o) => o.id === stoppingOrderId)?.order_code && (
              <p className="text-xs font-mono text-muted-foreground">
                Order: {orders.find((o) => o.id === stoppingOrderId)?.order_code}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Share modal */}
      {shareTarget && (
        <ShareOrderModal
          open={!!shareTarget}
          onOpenChange={(open) => !open && setShareTarget(null)}
          orderId={shareTarget.id}
          orderCode={shareTarget.order_code}
        />
      )}

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
