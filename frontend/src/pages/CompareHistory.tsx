import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  GitCompareArrows,
  ExternalLink,
  Trash2,
  Loader2,
  RefreshCw,
  MessageSquare,
  Bot,
  Clock,
} from "lucide-react";
import { getAuthHeader } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

interface OrderMeta {
  id: number;
  order_code: string;
  project_name: string;
}

interface CompareHistoryItem {
  id: number;
  order_id_a: number;
  order_id_b: number;
  order_a: OrderMeta;
  order_b: OrderMeta;
  llm_model: string | null;
  chat_count: number;
  created_at: string;
  updated_at: string;
}

function formatKST(iso: string) {
  try {
    return new Date(iso + "Z").toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
  } catch {
    return iso;
  }
}

function relativeTime(iso: string) {
  const ms = Date.now() - new Date(iso + "Z").getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "방금 전";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  return `${days}일 전`;
}

export default function CompareHistory() {
  const navigate = useNavigate();
  const [items, setItems] = useState<CompareHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<CompareHistoryItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/compare/list", { headers: { ...getAuthHeader() } });
      if (res.ok) {
        const data = await res.json();
        setItems(data);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await fetch(`/api/compare/saved/${deleteTarget.id}`, {
        method: "DELETE",
        headers: { ...getAuthHeader() },
      });
      setItems((prev) => prev.filter((i) => i.id !== deleteTarget.id));
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
            <GitCompareArrows className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">Comparative Analysis History</h1>
            <p className="text-sm text-muted-foreground">저장된 오더 비교 분석 목록</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
          새로고침
        </Button>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-20 gap-4 text-muted-foreground">
            <GitCompareArrows className="h-12 w-12 opacity-30" />
            <div className="text-center">
              <p className="font-medium">저장된 비교 분석이 없습니다</p>
              <p className="text-sm mt-1">Orders 목록에서 완료된 오더 2개를 선택한 후 Compare를 실행하세요.</p>
            </div>
            <Button variant="outline" onClick={() => navigate("/admin/orders")}>
              Orders로 이동
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <Card
              key={item.id}
              className="cursor-pointer hover:border-primary/50 hover:shadow-sm transition-all group"
              onClick={() => navigate(`/admin/compare?a=${item.order_id_a}&b=${item.order_id_b}`)}
            >
              <CardContent className="p-4">
                <div className="flex items-start gap-4">
                  {/* Order pair */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      {/* Order A */}
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-medium text-primary/70 bg-primary/10 rounded px-1.5 py-0.5">A</span>
                        <span className="font-mono text-sm font-semibold">{item.order_a.order_code}</span>
                        <span className="text-sm text-muted-foreground truncate max-w-[160px]">{item.order_a.project_name}</span>
                      </div>

                      <GitCompareArrows className="h-4 w-4 text-muted-foreground shrink-0" />

                      {/* Order B */}
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-medium text-blue-600/70 bg-blue-500/10 rounded px-1.5 py-0.5">B</span>
                        <span className="font-mono text-sm font-semibold">{item.order_b.order_code}</span>
                        <span className="text-sm text-muted-foreground truncate max-w-[160px]">{item.order_b.project_name}</span>
                      </div>
                    </div>

                    {/* Meta */}
                    <div className="flex items-center gap-3 mt-2 flex-wrap">
                      {item.llm_model && (
                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Bot className="h-3 w-3" />
                          {item.llm_model}
                        </span>
                      )}
                      {item.chat_count > 0 && (
                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                          <MessageSquare className="h-3 w-3" />
                          Q&A {item.chat_count}개
                        </span>
                      )}
                      <span className="flex items-center gap-1 text-xs text-muted-foreground" title={formatKST(item.updated_at)}>
                        <Clock className="h-3 w-3" />
                        {relativeTime(item.updated_at)}
                      </span>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 text-xs group-hover:border-primary/50"
                      onClick={() => navigate(`/admin/compare?a=${item.order_id_a}&b=${item.order_id_b}`)}
                    >
                      <ExternalLink className="h-3.5 w-3.5 mr-1" />
                      열기
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                      title="삭제"
                      onClick={() => setDeleteTarget(item)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Delete confirmation */}
      <Dialog open={!!deleteTarget} onOpenChange={(v: boolean) => !v && setDeleteTarget(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>비교 분석 삭제</DialogTitle>
            <DialogDescription>
              {deleteTarget && (
                <>
                  <span className="font-mono font-semibold">{deleteTarget.order_a.order_code}</span>
                  {" vs "}
                  <span className="font-mono font-semibold">{deleteTarget.order_b.order_code}</span>
                  {" 비교 분석 리포트와 Q&A 히스토리를 삭제합니다. 이 작업은 되돌릴 수 없습니다."}
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : null}
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
