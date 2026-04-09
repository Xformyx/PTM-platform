import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck, Loader2, Trash2, CheckCircle2, XCircle, AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Notification {
  id: number;
  order_id: number | null;
  notification_type: string;
  title: string;
  message: string | null;
  read_at: string | null;
  created_at: string;
}

interface NotificationBellProps {
  compact?: boolean;
}

export default function NotificationBell({ compact }: NotificationBellProps) {
  const navigate = useNavigate();
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  const fetchUnreadCount = useCallback(async () => {
    try {
      const data = await api.get<{ count: number }>("/notifications/unread-count");
      setUnreadCount(data.count);
    } catch {
      // ignore
    }
  }, []);

  const fetchNotifications = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<Notification[]>("/notifications?limit=30");
      setNotifications(data);
    } catch {
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUnreadCount();
    const interval = setInterval(fetchUnreadCount, 30000);
    return () => clearInterval(interval);
  }, [fetchUnreadCount]);

  useEffect(() => {
    if (open) fetchNotifications();
  }, [open, fetchNotifications]);

  const handleMarkRead = async (n: Notification) => {
    try {
      await api.patch(`/notifications/${n.id}/read`);
      setNotifications((prev) =>
        prev.map((x) =>
          x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x
        )
      );
      setUnreadCount((c) => Math.max(0, c - 1));
      if (n.order_id) {
        setOpen(false);
        navigate(`/orders/${n.order_id}`);
      }
    } catch {
      // ignore
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await api.post("/notifications/mark-all-read");
      setNotifications((prev) =>
        prev.map((x) => ({ ...x, read_at: x.read_at ?? new Date().toISOString() }))
      );
      setUnreadCount(0);
    } catch {
      // ignore
    }
  };

  const handleDeleteAll = async () => {
    if (notifications.length === 0) return;
    if (
      !window.confirm(
        "모든 알림을 삭제할까요? 이 작업은 되돌릴 수 없습니다."
      )
    ) {
      return;
    }
    try {
      await api.delete<{ ok: boolean }>("/notifications");
      setNotifications([]);
      setUnreadCount(0);
    } catch {
      // ignore
    }
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    const now = new Date();
    const diff = (now.getTime() - d.getTime()) / 1000;
    if (diff < 60) return "방금 전";
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
    return d.toLocaleDateString("ko-KR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

  const getNotifIcon = (n: Notification) => {
    switch (n.notification_type) {
      case "order_completed":
        return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
      case "watchdog_restart":
        return <RefreshCw className="h-4 w-4 text-amber-500" />;
      case "watchdog_halted":
        return <AlertTriangle className="h-4 w-4 text-red-500" />;
      case "watchdog_warning":
        return <AlertTriangle className="h-4 w-4 text-amber-500" />;
      default:
        return <XCircle className="h-4 w-4 text-destructive" />;
    }
  };

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className={compact ? "relative h-7 w-7" : "relative h-9 w-9"}>
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && (
            <span className={cn(
              "absolute flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-medium text-destructive-foreground",
              compact ? "-right-0.5 -top-0.5 h-3.5" : "-right-0.5 -top-0.5 h-4"
            )}>
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-96 p-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
          <span className="text-sm font-medium">알림</span>
          <div className="flex shrink-0 items-center gap-1">
            {notifications.some((n) => !n.read_at) && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  handleMarkAllRead();
                }}
              >
                <CheckCheck className="mr-1 h-3 w-3" />
                모두 읽음
              </Button>
            )}
            {!loading && notifications.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  handleDeleteAll();
                }}
              >
                <Trash2 className="mr-1 h-3 w-3" />
                모두 삭제
              </Button>
            )}
          </div>
        </div>
        <ScrollArea className="max-h-[420px]">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : notifications.length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              알림이 없습니다
            </div>
          ) : (
            <div className="divide-y">
              {notifications.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  className={cn(
                    "w-full px-3 py-2.5 text-left hover:bg-accent transition-colors",
                    !n.read_at && "bg-accent/30",
                  )}
                  onClick={() => handleMarkRead(n)}
                >
                  <div className="flex items-start gap-2.5">
                    <div className="mt-0.5 shrink-0">
                      {getNotifIcon(n)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span
                          className={cn(
                            "text-sm leading-snug break-words",
                            !n.read_at ? "font-medium" : "text-muted-foreground",
                          )}
                        >
                          {n.title}
                        </span>
                        <span className="shrink-0 text-[11px] text-muted-foreground whitespace-nowrap">
                          {formatTime(n.created_at)}
                        </span>
                      </div>
                      {n.message && (
                        <p className="mt-1 text-xs text-muted-foreground leading-relaxed break-words whitespace-pre-wrap">
                          {n.message}
                        </p>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </ScrollArea>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
