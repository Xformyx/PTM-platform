import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download, Eye, FileText, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { FadeIn } from "@/components/motion/fade-in";
import FilePreviewModal from "@/components/FilePreviewModal";

interface ReportRow {
  order_id: number;
  order_code: string;
  project_name: string;
  ptm_type: string;
  status: string;
  filename: string;
  kind: "markdown" | "pptx" | "pdf" | string;
  size_bytes: number;
  modified_at: string;
  completed_at: string | null;
}

function formatKST(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return d.toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Reports() {
  const navigate = useNavigate();
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<{ orderId: number; filename: string } | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<{ reports: ReportRow[] }>("/orders/reports");
      setReports(data.reports ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load reports");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return reports;
    return reports.filter((r) =>
      [r.project_name, r.order_code, r.filename, r.ptm_type].some((v) =>
        (v || "").toLowerCase().includes(q),
      ),
    );
  }, [reports, query]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Reports</h1>
          <p className="text-sm text-muted-foreground mt-1">
            생성된 분석 리포트(MD / PPTX / PDF)를 주문 단위로 모았습니다.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} className="gap-1.5">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </Button>
      </div>

      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search project, order, or filename"
        className="max-w-md"
      />

      <FadeIn>
        <Card>
          <CardContent className="p-0">
            {loading && reports.length === 0 ? (
              <div className="flex items-center justify-center py-20 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                Loading reports…
              </div>
            ) : error ? (
              <div className="py-16 text-center text-sm text-destructive">{error}</div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20">
                <FileText className="h-16 w-16 text-muted-foreground/30 mb-4" />
                <p className="text-lg font-medium text-muted-foreground">No reports yet</p>
                <p className="text-sm text-muted-foreground mt-1">
                  Report Generation이 끝난 주문의 파일이 여기에 나타납니다.
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Project</TableHead>
                    <TableHead>File</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Updated</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((r) => (
                    <TableRow key={`${r.order_id}-${r.filename}`}>
                      <TableCell>
                        <button
                          type="button"
                          className="text-left hover:underline"
                          onClick={() => navigate(`/admin/orders/${r.order_id}`)}
                        >
                          <div className="font-medium">{r.project_name || r.order_code}</div>
                          <div className="text-xs text-muted-foreground font-mono">{r.order_code}</div>
                        </button>
                      </TableCell>
                      <TableCell className="font-mono text-xs max-w-[280px] truncate" title={r.filename}>
                        {r.filename}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-[10px] uppercase">{r.kind}</Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{formatSize(r.size_bytes)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatKST(r.modified_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          {r.kind === "markdown" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              title="Preview"
                              onClick={() => setPreview({ orderId: r.order_id, filename: r.filename })}
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            title="Download"
                            onClick={() =>
                              api.downloadFile(
                                `/orders/${r.order_id}/files/${encodeURIComponent(r.filename)}`,
                                r.filename,
                              )
                            }
                          >
                            <Download className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </FadeIn>

      {preview && (
        <FilePreviewModal
          open
          onClose={() => setPreview(null)}
          orderId={preview.orderId}
          filename={preview.filename}
        />
      )}
    </div>
  );
}
