import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import {
  LayoutDashboard,
  ClipboardList,
  Library,
  Brain,
  FlaskConical,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";
import ResourceMonitor from "@/components/layout/ResourceMonitor";

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
];

export default function Sidebar({ className }: { className?: string }) {
  const location = useLocation();

  return (
    <aside className={cn("flex h-screen w-64 flex-col border-r bg-card", className)}>
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
      <nav className="flex-1 space-y-1 px-3 py-4">
        {mainNav.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.end
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
        })}
      </nav>

      {/* Resource Monitor */}
      <ResourceMonitor />

      <Separator />

      {/* Settings */}
      <div className="px-3 py-3">
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
    </aside>
  );
}
