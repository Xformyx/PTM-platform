import { useState, useEffect } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  LayoutDashboard,
  ClipboardList,
  Library,
  Brain,
  BookOpen,
  FlaskConical,
  Settings,
  Activity,
  LogOut,
  KeyRound,
  Sun,
  Moon,
  Monitor,
  Shield,
  Trash2,
  UserPlus,
  Users,
  RotateCcw,
  Loader2,
  ChevronLeft,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";
import ResourceMonitor from "@/components/layout/ResourceMonitor";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";

interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const mainNav: NavItem[] = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { path: "/orders", label: "Orders", icon: ClipboardList, end: true },
  { path: "/ptmquant", label: "PTMQuant", icon: FlaskConical },
  { path: "/rag", label: "RAG Collections", icon: Library },
  { path: "/llm", label: "LLM Models", icon: Brain },
  { path: "/articles", label: "Article Cache", icon: BookOpen },
];

function NavItemLink({ item, collapsed = false }: { item: NavItem; collapsed?: boolean }) {
  const location = useLocation();
  const Icon = item.icon;
  const isActive = item.end
    ? location.pathname === item.path
    : location.pathname.startsWith(item.path);

  return (
    <NavLink key={item.path} to={item.path} end={item.end} title={collapsed ? item.label : undefined}>
      <div
        className={cn(
          "group relative flex items-center rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
          collapsed ? "justify-center" : "gap-3",
          isActive
            ? "bg-primary/10 text-primary"
            : "text-muted-foreground hover:bg-accent hover:text-foreground"
        )}
      >
        {isActive && (
          <motion.div
            layoutId="activeIndicator"
            className="absolute left-0 inset-y-1 w-[3px] rounded-r-full bg-primary"
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
          />
        )}
        <Icon className="h-4 w-4 shrink-0" />
        {!collapsed && <span>{item.label}</span>}
      </div>
    </NavLink>
  );
}

function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const reset = () => {
    setCurrent(""); setNext(""); setConfirm(""); setError(""); setSuccess(false);
  };

  const handleClose = () => { reset(); onClose(); };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (next !== confirm) { setError("New passwords do not match"); return; }
    if (next.length < 6) { setError("Password must be at least 6 characters"); return; }
    setLoading(true);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      setSuccess(true);
      setTimeout(handleClose, 1500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to change password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" />
            Change Password
          </DialogTitle>
        </DialogHeader>
        {success ? (
          <p className="text-sm text-green-600 dark:text-green-400 py-4 text-center">
            Password changed successfully!
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3 pt-2">
            <div className="space-y-1.5">
              <Label htmlFor="cp-current">Current Password</Label>
              <Input
                id="cp-current"
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cp-new">New Password</Label>
              <Input
                id="cp-new"
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cp-confirm">Confirm New Password</Label>
              <Input
                id="cp-confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            {error && (
              <p className="text-xs text-destructive bg-destructive/10 rounded px-2 py-1.5">{error}</p>
            )}
            <div className="flex gap-2 pt-1">
              <Button type="button" variant="outline" className="flex-1" onClick={handleClose} disabled={loading}>
                Cancel
              </Button>
              <Button type="submit" className="flex-1" disabled={loading}>
                {loading ? "Saving…" : "Change Password"}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Format version: strip leading zeros (001.001.001.001 → 1.1.1.1) */
function formatVersionDisplay(raw: string): string {
  return raw
    .split(".")
    .map((s) => String(parseInt(s, 10) || 0))
    .join(".");
}

function VersionDisplay({ collapsed }: { collapsed?: boolean }) {
  const [version, setVersion] = useState<string>("—");
  const [gitHash, setGitHash] = useState<string>("");
  const [gitDate, setGitDate] = useState<string>("");
  useEffect(() => {
    fetch("/api/version")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        if (d?.version) setVersion(formatVersionDisplay(d.version));
        if (d?.git_hash) setGitHash(d.git_hash);
        if (d?.git_date) setGitDate(d.git_date);
      })
      .catch(() => {});
  }, []);

  const hashPart = gitHash ? gitHash.slice(0, 7) : "";
  const tooltip = [
    `Version: ${version}`,
    hashPart ? `Commit: ${hashPart}` : "",
    gitDate ? `Built: ${gitDate}` : "",
  ].filter(Boolean).join(" · ");

  return (
    <div
      className={cn(
        "shrink-0 px-3 py-2 border-t",
        collapsed ? "flex justify-center" : ""
      )}
      title={tooltip}
    >
      {collapsed ? (
        <span className="text-[9px] text-muted-foreground font-mono">{hashPart || "—"}</span>
      ) : (
        <div className="space-y-0.5">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground font-mono">v{version}</span>
            {hashPart && (
              <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-muted text-muted-foreground">{hashPart}</span>
            )}
          </div>
          {gitDate && (
            <div className="text-[9px] text-muted-foreground/60 font-mono">{gitDate}</div>
          )}
        </div>
      )}
    </div>
  );
}

function CreateUserModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"admin" | "analyst">("analyst");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const emailValid = email === "" || EMAIL_RE.test(email);

  const reset = () => {
    setEmail(""); setName(""); setRole("analyst"); setError(""); setSuccess(false);
  };
  const handleClose = () => { reset(); onClose(); };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!EMAIL_RE.test(email)) {
      setError("Please enter a valid email address");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/users", { email, name, role });
      setSuccess(true);
      setTimeout(handleClose, 1800);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="h-4 w-4" />
            Create User
          </DialogTitle>
          <DialogDescription>
            New user will receive the temporary password{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs font-semibold">
              ptm1234
            </code>{" "}
            and must change it on first login.
          </DialogDescription>
        </DialogHeader>
        {success ? (
          <p className="text-sm text-green-600 dark:text-green-400 py-4 text-center">
            User created successfully!
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3 pt-1">
            <div className="space-y-1.5">
              <Label htmlFor="cu-email">Email</Label>
              <Input
                id="cu-email"
                type="email"
                placeholder="user@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                disabled={loading}
                className={!emailValid ? "border-destructive focus-visible:ring-destructive" : ""}
              />
              {!emailValid && (
                <p className="text-[11px] text-destructive">Please enter a valid email address</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cu-name">Display Name</Label>
              <Input
                id="cu-name"
                type="text"
                placeholder="Full name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cu-role">Role</Label>
              <Select
                value={role}
                onValueChange={(v) => setRole(v as "admin" | "analyst")}
                disabled={loading}
              >
                <SelectTrigger id="cu-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="analyst">General User</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {error && (
              <p className="text-xs text-destructive bg-destructive/10 rounded px-2 py-1.5">{error}</p>
            )}
            <div className="flex gap-2 pt-1">
              <Button type="button" variant="outline" className="flex-1" onClick={handleClose} disabled={loading}>
                Cancel
              </Button>
              <Button type="submit" className="flex-1" disabled={loading}>
                {loading ? "Creating…" : "Create User"}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

interface ManagedUser {
  id: number;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  must_change_password: boolean;
}

interface LoginAttemptRow {
  id: number;
  email: string;
  user_name: string | null;
  user_id: number | null;
  status: string;
  reason: string;
  ip_address: string | null;
  location: string | null;
  user_agent: string | null;
  created_at: string | null;
}

function ManageUsersModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [resetting, setResetting] = useState<number | null>(null);
  const [toggling, setToggling] = useState<number | null>(null);
  const [message, setMessage] = useState<{ id: number; text: string; ok: boolean } | null>(null);
  const [expandedUserId, setExpandedUserId] = useState<number | null>(null);
  const [userAttempts, setUserAttempts] = useState<Record<number, LoginAttemptRow[]>>({});
  const [attemptsLoading, setAttemptsLoading] = useState<number | null>(null);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const data = await api.get<ManagedUser[]>("/auth/users");
      setUsers(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async (u: ManagedUser) => {
    setResetting(u.id);
    setMessage(null);
    try {
      await api.patch(`/auth/users/${u.id}`, { password: "ptm1234" });
      setMessage({ id: u.id, text: "Reset to ptm1234", ok: true });
    } catch (err: unknown) {
      setMessage({ id: u.id, text: err instanceof Error ? err.message : "Failed", ok: false });
    } finally {
      setResetting(null);
    }
  };

  const loadUserAttempts = async (uid: number) => {
    setAttemptsLoading(uid);
    try {
      const data = await api.get<LoginAttemptRow[]>(`/auth/login-attempts?user_id=${uid}&limit=20`);
      setUserAttempts((prev) => ({ ...prev, [uid]: data }));
    } catch { /* ignore */ }
    finally { setAttemptsLoading(null); }
  };

  const handleToggleActive = async (u: ManagedUser) => {
    setToggling(u.id);
    setMessage(null);
    try {
      const res = await api.patch<ManagedUser>(`/auth/users/${u.id}`, { is_active: !u.is_active });
      setUsers((prev) => prev.map((p) => (p.id === u.id ? { ...p, is_active: res.is_active } : p)));
    } catch (err: unknown) {
      setMessage({ id: u.id, text: err instanceof Error ? err.message : "Failed", ok: false });
    } finally {
      setToggling(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="max-w-lg" onOpenAutoFocus={() => { loadUsers(); setUserAttempts({}); setExpandedUserId(null); }}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Users className="h-4 w-4" />
            Manage Users
          </DialogTitle>
          <DialogDescription>
            Reset any user's password to the temporary password{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs font-semibold">ptm1234</code>.
            The user must change it on next login.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-2 max-h-[26rem] overflow-y-auto pr-1">
            {users.map((u) => {
              const isExpanded = expandedUserId === u.id;
              const logs = userAttempts[u.id] || [];

              return (
                <div key={u.id} className={`rounded-lg border ${!u.is_active ? "opacity-60" : ""}`}>
                  <div className="flex items-center gap-3 px-3 py-2.5">
                    <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${u.is_active ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground"}`}>
                      {u.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <p className="text-sm font-medium truncate">{u.name}</p>
                        <Badge variant={u.role === "admin" ? "default" : "secondary"} className="text-[10px] h-4 px-1">
                          {u.role === "admin" ? "Admin" : "User"}
                        </Badge>
                        {!u.is_active && (
                          <Badge variant="outline" className="text-[10px] h-4 px-1 text-red-500 border-red-300">
                            Disabled
                          </Badge>
                        )}
                        {u.must_change_password && (
                          <Badge variant="outline" className="text-[10px] h-4 px-1 text-amber-600 border-amber-400">
                            pw change required
                          </Badge>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground truncate">{u.email}</p>
                      {message?.id === u.id && (
                        <p className={`text-[11px] mt-0.5 ${message.ok ? "text-green-600 dark:text-green-400" : "text-destructive"}`}>
                          {message.text}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs px-2"
                        title="Login history"
                        onClick={() => {
                          if (isExpanded) { setExpandedUserId(null); }
                          else { setExpandedUserId(u.id); loadUserAttempts(u.id); }
                        }}
                      >
                        <Shield className="h-3 w-3" />
                      </Button>
                      {u.id !== currentUser?.id && (
                        <Button
                          variant={u.is_active ? "outline" : "default"}
                          size="sm"
                          className={`h-7 text-xs ${!u.is_active ? "bg-emerald-600 hover:bg-emerald-700" : ""}`}
                          onClick={() => handleToggleActive(u)}
                          disabled={toggling === u.id}
                        >
                          {toggling === u.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : u.is_active ? (
                            "Disable"
                          ) : (
                            "Enable"
                          )}
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => handleReset(u)}
                        disabled={resetting === u.id}
                      >
                        {resetting === u.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <><RotateCcw className="h-3 w-3 mr-1" />Reset PW</>
                        )}
                      </Button>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="border-t bg-muted/30 px-3 py-2 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Login History</p>
                        {logs.length > 0 && (
                          <Button
                            variant="ghost" size="sm"
                            className="h-5 text-[10px] px-1.5 text-muted-foreground hover:text-destructive"
                            title="Delete all login history"
                            onClick={async () => {
                              try {
                                await api.delete(`/auth/login-attempts/${u.id}`);
                                setUserAttempts((prev) => ({ ...prev, [u.id]: [] }));
                              } catch { /* ignore */ }
                            }}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                      {attemptsLoading === u.id ? (
                        <div className="flex justify-center py-3">
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                        </div>
                      ) : logs.length === 0 ? (
                        <p className="text-[11px] text-muted-foreground py-1">No login records</p>
                      ) : (
                        <div className="space-y-1 overflow-y-auto" style={{ maxHeight: "calc(5 * 34px)" }}>
                          {logs.map((a) => (
                            <div key={a.id} className="flex items-center gap-2 text-[11px] rounded bg-background px-2 py-1.5 border" title={a.ip_address || ""}>
                              <span className={`shrink-0 h-1.5 w-1.5 rounded-full ${a.status === "success" ? "bg-emerald-500" : "bg-red-500"}`} />
                              <span className="text-muted-foreground whitespace-nowrap">
                                {a.created_at ? new Date(a.created_at).toLocaleString("ko-KR") : ""}
                              </span>
                              <span className="font-medium">
                                {a.status === "success" ? "Login" : "Blocked"}
                              </span>
                              {a.location ? (
                                <span className="text-muted-foreground truncate ml-auto">{a.location}</span>
                              ) : a.ip_address ? (
                                <span className="text-muted-foreground/60 font-mono text-[10px] ml-auto truncate max-w-[120px]">{a.ip_address}</span>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="flex justify-end pt-1">
          <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function UserProfileSection({ collapsed = false }: { collapsed?: boolean }) {
  const { user, isAdmin, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [manageUsersOpen, setManageUsersOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const themeOptions: { value: "light" | "dark" | "system"; label: string; icon: LucideIcon }[] = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
  ];

  if (collapsed) {
    return (
      <>
        <Separator />
        <div className="flex flex-col items-center gap-1 py-3">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary cursor-default"
            title={`${user?.name} (${isAdmin ? "Admin" : "User"})`}
          >
            {user?.name?.charAt(0).toUpperCase() ?? "U"}
          </div>
          <button
            onClick={handleLogout}
            title="Sign Out"
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
          >
            <LogOut className="h-3.5 w-3.5" />
          </button>
        </div>
        <ChangePasswordModal open={passwordOpen} onClose={() => setPasswordOpen(false)} />
        <CreateUserModal open={createUserOpen} onClose={() => setCreateUserOpen(false)} />
        <ManageUsersModal open={manageUsersOpen} onClose={() => setManageUsersOpen(false)} />
      </>
    );
  }

  return (
    <>
      <Separator />
      <div className="px-3 py-3 space-y-1">
        {/* User info row */}
        <div className="flex items-center gap-2 px-2 py-1.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
            {user?.name?.charAt(0).toUpperCase() ?? "U"}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{user?.name}</p>
            <p className="text-[10px] text-muted-foreground truncate flex items-center gap-1">
              {isAdmin && <Shield className="h-2.5 w-2.5" />}
              {isAdmin ? "Admin" : "User"}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => setSettingsOpen((v) => !v)}
            title="User settings"
          >
            <Settings className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Inline settings panel */}
        {settingsOpen && (
          <div className="rounded-lg border bg-card p-3 space-y-3 mx-1">
            {/* Theme selector */}
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2">Theme</p>
              <div className="flex gap-1">
                {themeOptions.map(({ value, label, icon: Icon }) => (
                  <button
                    key={value}
                    onClick={() => setTheme(value)}
                    className={cn(
                      "flex-1 flex flex-col items-center gap-1 rounded-md py-1.5 text-[10px] font-medium transition-colors",
                      theme === value
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-accent text-muted-foreground"
                    )}
                  >
                    <Icon className="h-3 w-3" />
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <Separator />

            {/* Actions */}
            <div className="space-y-1">
              {isAdmin && (
                <>
                  <button
                    onClick={() => { setCreateUserOpen(true); setSettingsOpen(false); }}
                    className="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                  >
                    <UserPlus className="h-3 w-3" />
                    Create User
                  </button>
                  <button
                    onClick={() => { setManageUsersOpen(true); setSettingsOpen(false); }}
                    className="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                  >
                    <Users className="h-3 w-3" />
                    Manage Users
                  </button>
                </>
              )}
              <button
                onClick={() => { setPasswordOpen(true); setSettingsOpen(false); }}
                className="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <KeyRound className="h-3 w-3" />
                Change Password
              </button>
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium text-destructive/80 hover:bg-destructive/10 hover:text-destructive transition-colors"
              >
                <LogOut className="h-3 w-3" />
                Sign Out
              </button>
            </div>
          </div>
        )}
      </div>

      <ChangePasswordModal open={passwordOpen} onClose={() => setPasswordOpen(false)} />
      <CreateUserModal open={createUserOpen} onClose={() => setCreateUserOpen(false)} />
      <ManageUsersModal open={manageUsersOpen} onClose={() => setManageUsersOpen(false)} />
    </>
  );
}

interface SidebarProps {
  className?: string;
  collapsed?: boolean;
  onToggle?: () => void;
}

export default function Sidebar({ className, collapsed = false, onToggle }: SidebarProps) {
  const { isAdmin } = useAuth();

  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r transition-all duration-300 overflow-hidden",
        collapsed ? "w-[60px]" : "w-64",
        className
      )}
      style={{ background: "hsl(var(--sidebar))", color: "hsl(var(--sidebar-foreground))" }}
    >
      {/* Logo + toggle */}
      <div className={cn("flex items-center py-5 shrink-0", collapsed ? "justify-center px-0" : "gap-3 px-4")}>
        <img
          src="/mekii-logo.png"
          alt="Mekii"
          className={cn(
            "shrink-0 object-contain",
            collapsed ? "h-9 w-9" : "h-10 w-auto max-w-[120px]"
          )}
        />
        {!collapsed && (
          <div className="flex-1 min-w-0">
            <h1 className="text-sm font-semibold tracking-tight leading-tight">Meta-Kinetics<br/>Intelligence</h1>
          </div>
        )}
        <button
          onClick={onToggle}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground transition-colors",
            collapsed && "mt-1"
          )}
        >
          {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
        </button>
      </div>

      <Separator />

      {/* Navigation */}
      <nav className="flex-1 min-h-0 overflow-y-auto space-y-1 px-2 py-4">
        {mainNav.map((item) => (
          <NavItemLink key={item.path} item={item} collapsed={collapsed} />
        ))}
      </nav>

      {/* Resource Monitor — admin only, hidden when collapsed */}
      {isAdmin && !collapsed && <ResourceMonitor />}

      {/* System Monitor — admin only */}
      {isAdmin && (
        <div className="px-2 py-1">
          <NavLink to="/system-monitor" title={collapsed ? "System Monitor" : undefined}>
            {({ isActive }) => (
              <div
                className={cn(
                  "relative flex items-center rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                  collapsed ? "justify-center" : "gap-3",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="activeIndicator"
                    className="absolute left-0 inset-y-1 w-[3px] rounded-r-full bg-primary"
                    transition={{ type: "spring", stiffness: 400, damping: 30 }}
                  />
                )}
                <Activity className="h-4 w-4 shrink-0" />
                {!collapsed && <span>System Monitor</span>}
              </div>
            )}
          </NavLink>
        </div>
      )}

      {/* Settings — admin only */}
      {isAdmin && (
        <>
          <Separator />
          <div className="px-2 py-2">
            <NavLink to="/settings" title={collapsed ? "Settings" : undefined}>
              {({ isActive }) => (
                <div
                  className={cn(
                    "relative flex items-center rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                    collapsed ? "justify-center" : "gap-3",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  )}
                >
                  {isActive && (
                    <motion.div
                      layoutId="activeIndicator"
                      className="absolute left-0 inset-y-1 w-[3px] rounded-r-full bg-primary"
                      transition={{ type: "spring", stiffness: 400, damping: 30 }}
                    />
                  )}
                  <Settings className="h-4 w-4 shrink-0" />
                  {!collapsed && <span>Settings</span>}
                </div>
              )}
            </NavLink>
          </div>
        </>
      )}

      {/* User profile */}
      <UserProfileSection collapsed={collapsed} />

      {/* Version */}
      <VersionDisplay collapsed={collapsed} />
    </aside>
  );
}
