import { useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { ArrowLeft, GitCompareArrows, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import type { Order } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/contexts/AuthContext";

/* ─── Types ─── */
interface CompareMetadata {
  order_a: { id: number; order_code: string; project_name: string; species: string; ptm_type: string; conditions: string[] };
  order_b: { id: number; order_code: string; project_name: string; species: string; ptm_type: string; conditions: string[] };
  shared_genes: number;
  unique_a_genes: number;
  unique_b_genes: number;
  shared_sites: number;
  unique_a_sites: number;
  unique_b_sites: number;
}

/* ─── Helpers ─── */
function SummaryCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="flex flex-col items-center justify-center p-4 rounded-lg bg-muted/50 border min-w-[120px]">
      <span className="text-2xl font-bold text-primary">{value}</span>
      <span className="text-xs text-muted-foreground mt-1 text-center">{label}</span>
      {sub && <span className="text-[10px] text-muted-foreground/70 mt-0.5">{sub}</span>}
    </div>
  );
}

function OrderInfoCard({ order }: { order: CompareMetadata["order_a"] }) {
  return (
    <Card className="flex-1">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Link to={`/admin/orders/${order.id}`} className="font-mono text-primary hover:underline">
            {order.order_code}
          </Link>
          <Badge variant="outline" className="text-[10px]">{order.ptm_type}</Badge>
          <Badge variant="secondary" className="text-[10px]">{order.species}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <p className="text-sm text-muted-foreground">{order.project_name}</p>
        <p className="text-xs text-muted-foreground/70 mt-1">
          Conditions: {order.conditions.join(", ")}
        </p>
      </CardContent>
    </Card>
  );
}

/* ─── Main Component ─── */
export default function OrderCompare() {
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const orderAId = searchParams.get("a");
  const orderBId = searchParams.get("b");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<CompareMetadata | null>(null);
  const [report, setReport] = useState("");
  const [streaming, setStreaming] = useState(false);
  const reportRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  /* Fetch metadata (quick) */
  const fetchMetadata = useCallback(async () => {
    if (!orderAId || !orderBId) {
      setError("Two order IDs are required (query params: a, b)");
      setLoading(false);
      return;
    }
    try {
      const data = await api.get<CompareMetadata>(`/compare/metadata?order_a_id=${orderAId}&order_b_id=${orderBId}`);
      setMetadata(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load comparison metadata");
    } finally {
      setLoading(false);
    }
  }, [orderAId, orderBId]);

  /* Stream comparative report */
  const streamReport = useCallback(async () => {
    if (!orderAId || !orderBId) return;
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);
    setReport("");

    try {
      const token = localStorage.getItem("token");
      const res = await fetch(`/api/compare/report?order_a_id=${orderAId}&order_b_id=${orderBId}`, {
        method: "GET",
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        signal: controller.signal,
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const payload = line.slice(6);
            if (payload === "[DONE]") break;
            try {
              const parsed = JSON.parse(payload);
              if (parsed.content) {
                setReport((prev) => prev + parsed.content);
              }
            } catch {
              // non-JSON line, treat as raw text
              setReport((prev) => prev + payload);
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setReport((prev) => prev + `\n\n---\n**Error:** ${err.message}`);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [orderAId, orderBId]);

  useEffect(() => {
    fetchMetadata();
  }, [fetchMetadata]);

  /* Auto-start streaming after metadata loads */
  useEffect(() => {
    if (metadata && !report && !streaming) {
      streamReport();
    }
  }, [metadata]);

  /* Cleanup on unmount */
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  if (!orderAId || !orderBId) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <AlertCircle className="h-12 w-12 text-muted-foreground/40" />
        <p className="text-muted-foreground">Select two completed orders from the Order List to compare.</p>
        <Button variant="outline" asChild>
          <Link to="/admin/orders"><ArrowLeft className="mr-2 h-4 w-4" />Back to Orders</Link>
        </Button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-[400px]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <AlertCircle className="h-12 w-12 text-destructive/60" />
        <p className="text-destructive font-medium">{error}</p>
        <Button variant="outline" asChild>
          <Link to="/admin/orders"><ArrowLeft className="mr-2 h-4 w-4" />Back to Orders</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/admin/orders"><ArrowLeft className="h-4 w-4" /></Link>
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
              <GitCompareArrows className="h-6 w-6 text-primary" />
              Comparative Analysis
            </h1>
            <p className="text-sm text-muted-foreground">Cross-order PTM comparison</p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={streamReport}
          disabled={streaming}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${streaming ? "animate-spin" : ""}`} />
          {streaming ? "Generating..." : "Regenerate"}
        </Button>
      </div>

      {/* Order Info Cards */}
      {metadata && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <OrderInfoCard order={metadata.order_a} />
          <OrderInfoCard order={metadata.order_b} />
        </div>
      )}

      {/* Summary Statistics */}
      {metadata && (
        <div className="flex flex-wrap gap-3 justify-center">
          <SummaryCard label="Shared Genes" value={metadata.shared_genes} />
          <SummaryCard label={`Unique to A`} value={metadata.unique_a_genes} sub={metadata.order_a.order_code} />
          <SummaryCard label={`Unique to B`} value={metadata.unique_b_genes} sub={metadata.order_b.order_code} />
          <SummaryCard label="Shared Sites" value={metadata.shared_sites} />
          <SummaryCard label={`Unique Sites A`} value={metadata.unique_a_sites} sub={metadata.order_a.order_code} />
          <SummaryCard label={`Unique Sites B`} value={metadata.unique_b_sites} sub={metadata.order_b.order_code} />
        </div>
      )}

      {/* Comparative Report (Streaming Markdown) */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            Comparative Report
            {streaming && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div ref={reportRef} className="prose prose-sm dark:prose-invert max-w-none">
            {report ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
            ) : streaming ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Analyzing and comparing two orders...</span>
              </div>
            ) : (
              <p className="text-muted-foreground">Report will appear here.</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
