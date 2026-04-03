/**
 * ShareOrderModal — share an order with other users and manage existing shares.
 *
 * Features:
 *  - Shows current shares (who has access, what level)
 *  - Add new share (pick user + access level)
 *  - Revoke any existing share
 */
import { useEffect, useState } from "react";
import { Share2, X, UserPlus, Shield, Eye, Trash2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { OrderShareEntry, ShareableUser } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orderId: number;
  orderCode: string;
}

const ACCESS_LABELS: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  full_access: {
    label: "Full Access",
    icon: <Shield className="h-3 w-3" />,
    color: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  },
  read_only: {
    label: "Read Only",
    icon: <Eye className="h-3 w-3" />,
    color: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  },
};

export function ShareOrderModal({ open, onOpenChange, orderId, orderCode }: Props) {
  const [shares, setShares] = useState<OrderShareEntry[]>([]);
  const [users, setUsers] = useState<ShareableUser[]>([]);
  const [loadingShares, setLoadingShares] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [selectedAccess, setSelectedAccess] = useState<"full_access" | "read_only">("read_only");
  const [submitting, setSubmitting] = useState(false);
  const [revoking, setRevoking] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoadingShares(true);
    setError(null);
    try {
      const [sharesData, usersData] = await Promise.all([
        api.get<OrderShareEntry[]>(`/orders/${orderId}/shares`),
        api.get<ShareableUser[]>("/orders/shareable-users"),
      ]);
      setShares(sharesData);
      setUsers(usersData);
    } catch (e: any) {
      setError(e.message || "Failed to load share data");
    } finally {
      setLoadingShares(false);
    }
  };

  useEffect(() => {
    if (open) {
      fetchData();
      setSelectedUserId("");
      setSelectedAccess("read_only");
    }
  }, [open, orderId]);

  const handleShare = async () => {
    if (!selectedUserId) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/orders/${orderId}/share`, {
        user_id: Number(selectedUserId),
        access_level: selectedAccess,
      });
      setSelectedUserId("");
      await fetchData();
    } catch (e: any) {
      setError(e.message || "Failed to share order");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (userId: number) => {
    setRevoking(userId);
    setError(null);
    try {
      await api.delete(`/orders/${orderId}/share/${userId}`);
      setShares((prev) => prev.filter((s) => s.user_id !== userId));
    } catch (e: any) {
      setError(e.message || "Failed to revoke share");
    } finally {
      setRevoking(null);
    }
  };

  // Users already shared with (exclude from picker)
  const sharedUserIds = new Set(shares.map((s) => s.user_id));
  const availableUsers = users.filter((u) => !sharedUserIds.has(u.id));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Share2 className="h-4 w-4 text-primary" />
            Share Order
          </DialogTitle>
          <DialogDescription>
            <span className="font-mono text-xs">{orderCode}</span>
            {" — "}공유 사용자를 관리합니다.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 pt-1">
          {/* ── Current shares ── */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              현재 공유 중 ({shares.length})
            </p>
            {loadingShares ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-3">
                <Loader2 className="h-4 w-4 animate-spin" /> 로딩 중...
              </div>
            ) : shares.length === 0 ? (
              <p className="text-sm text-muted-foreground py-3 text-center border border-dashed rounded-lg">
                공유된 사용자가 없습니다.
              </p>
            ) : (
              <ul className="space-y-2">
                {shares.map((share) => {
                  const meta = ACCESS_LABELS[share.access_level];
                  return (
                    <li
                      key={share.user_id}
                      className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="h-7 w-7 rounded-full bg-primary/10 flex items-center justify-center text-xs font-bold text-primary shrink-0">
                          {share.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">{share.name}</p>
                          <p className="text-xs text-muted-foreground truncate">{share.email}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${meta.color}`}
                        >
                          {meta.icon}
                          {meta.label}
                        </span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 text-destructive hover:text-destructive hover:bg-destructive/10"
                          disabled={revoking === share.user_id}
                          onClick={() => handleRevoke(share.user_id)}
                          title="공유 해지"
                        >
                          {revoking === share.user_id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <X className="h-3.5 w-3.5" />
                          )}
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* ── Add new share ── */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
              사용자 추가
            </p>
            <div className="flex items-center gap-2">
              <Select
                value={selectedUserId}
                onValueChange={setSelectedUserId}
                disabled={availableUsers.length === 0}
              >
                <SelectTrigger className="flex-1 h-9 text-sm">
                  <SelectValue
                    placeholder={
                      availableUsers.length === 0 ? "공유 가능한 사용자 없음" : "사용자 선택..."
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {availableUsers.map((u) => (
                    <SelectItem key={u.id} value={String(u.id)}>
                      <span className="font-medium">{u.name}</span>
                      <span className="ml-2 text-muted-foreground text-xs">{u.email}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select
                value={selectedAccess}
                onValueChange={(v) => setSelectedAccess(v as "full_access" | "read_only")}
              >
                <SelectTrigger className="w-[130px] h-9 text-sm shrink-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read_only">
                    <span className="flex items-center gap-1.5">
                      <Eye className="h-3.5 w-3.5" /> Read Only
                    </span>
                  </SelectItem>
                  <SelectItem value="full_access">
                    <span className="flex items-center gap-1.5">
                      <Shield className="h-3.5 w-3.5" /> Full Access
                    </span>
                  </SelectItem>
                </SelectContent>
              </Select>

              <Button
                size="sm"
                className="h-9 gap-1.5 shrink-0"
                disabled={!selectedUserId || submitting}
                onClick={handleShare}
              >
                {submitting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <UserPlus className="h-3.5 w-3.5" />
                )}
                공유
              </Button>
            </div>
          </div>

          {/* Access level legend */}
          <div className="rounded-lg bg-muted/50 px-3 py-2.5 space-y-1 text-xs text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Eye className="h-3.5 w-3.5 shrink-0" />
              <span><strong>Read Only</strong> — 결과 조회만 가능. Re-run·삭제 불가.</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Shield className="h-3.5 w-3.5 shrink-0" />
              <span><strong>Full Access</strong> — Re-run·설정 변경·파일 다운로드 모두 가능.</span>
            </div>
          </div>

          {error && (
            <p className="text-sm text-destructive bg-destructive/10 rounded px-3 py-2">{error}</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
