import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, CheckCheck, Loader2 } from "lucide-react";
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

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    const now = new Date();
    const diff = (now.getTime() - d.getTime()) / 1000;
    if (diff < 60) return "방금 전";
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
    return d.toLocaleDateString("ko-KR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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
      <DropdownMenuContent align="end" className="w-80 p-0">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-sm font-medium">알림</span>
          {notifications.some((n) => !n.read_at) && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs"
              onClick={handleMarkAllRead}
            >
              <CheckCheck className="mr-1 h-3 w-3" />
              모두 읽음
            </Button>
          )}
        </div>
        <ScrollArea className="h-[320px]">
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
                  className="w-full px-3 py-2.5 text-left hover:bg-accent transition-colors"
                  onClick={() => handleMarkRead(n)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span
                      className={`text-sm ${!n.read_at ? "font-medium" : "text-muted-foreground"}`}
                    >
                      {n.title}
                    </span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {formatTime(n.created_at)}
                    </span>
                  </div>
                  {n.message && (
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                      {n.message}
                    </p>
                  )}
                </button>
              ))}
            </div>
          )}
        </ScrollArea>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
