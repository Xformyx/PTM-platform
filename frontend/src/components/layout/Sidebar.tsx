import { useState } from "react";
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
  UserPlus,
  type LucideIcon,
} from "lucide-react";
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
  { path: "/rag", label: "RAG Collections", icon: Library },
  { path: "/llm", label: "LLM Models", icon: Brain },
  { path: "/articles", label: "Article Cache", icon: BookOpen },
];

function NavItemLink({ item }: { item: NavItem }) {
  const location = useLocation();
  const Icon = item.icon;
  const isActive = item.end
    ? location.pathname === item.path
    : location.pathname.startsWith(item.path);

  return (
    <NavLink key={item.path} to={item.path} end={item.end}>
      <div
        className={cn(
          "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
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
        <span>{item.label}</span>
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

function UserProfileSection() {
  const { user, isAdmin, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [createUserOpen, setCreateUserOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  const themeOptions: { value: "light" | "dark" | "system"; label: string; icon: LucideIcon }[] = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
  ];

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
                <button
                  onClick={() => { setCreateUserOpen(true); setSettingsOpen(false); }}
                  className="w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                >
                  <UserPlus className="h-3 w-3" />
                  Create User
                </button>
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
    </>
  );
}

export default function Sidebar({ className }: { className?: string }) {
  const { isAdmin } = useAuth();

  return (
    <aside className={cn("flex h-screen w-64 flex-col border-r", className)} style={{ background: "hsl(var(--sidebar))", color: "hsl(var(--sidebar-foreground))" }}>
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
          <FlaskConical className="h-5 w-5 text-primary-foreground" />
        </div>
        <div>
          <h1 className="text-base font-semibold tracking-tight">PTM Platform</h1>
          <p className="text-[11px] text-muted-foreground">Analysis & Report System</p>
        </div>
      </div>

      <Separator />

      {/* Navigation */}
      <nav className="flex-1 min-h-0 overflow-y-auto space-y-1 px-3 py-4">
        {mainNav.map((item) => (
          <NavItemLink key={item.path} item={item} />
        ))}
      </nav>

      {/* Resource Monitor — admin only */}
      {isAdmin && <ResourceMonitor />}

      {/* System Monitor — admin only */}
      {isAdmin && (
        <div className="px-3 py-2">
          <NavLink to="/system-monitor">
            {({ isActive }) => (
              <div
                className={cn(
                  "relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
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
                <Activity className="h-4 w-4" />
                <span>System Monitor</span>
              </div>
            )}
          </NavLink>
        </div>
      )}

      {/* Settings — admin only */}
      {isAdmin && (
        <>
          <Separator />
          <div className="px-3 py-2">
            <NavLink to="/settings">
              {({ isActive }) => (
                <div
                  className={cn(
                    "relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
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
                  <Settings className="h-4 w-4" />
                  <span>Settings</span>
                </div>
              )}
            </NavLink>
          </div>
        </>
      )}

      {/* User profile */}
      <UserProfileSection />
    </aside>
  );
}
