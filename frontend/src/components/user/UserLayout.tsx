/**
 * UserLayout — Simplified layout for general users.
 * Clean top navigation with minimal options.
 * No sidebar, no admin tools.
 */
import { Outlet, useLocation, useNavigate, Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Plus,
  History,
  LogOut,
  User,
  Settings,
  ChevronDown,
} from "lucide-react";

export default function UserLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      {/* Top Navigation */}
      <header className="flex h-16 items-center justify-between border-b bg-card px-6 shrink-0">
        {/* Left: Logo + Nav */}
        <div className="flex items-center gap-8">
          <Link to="/app" className="flex items-center gap-2 group">
            <img
              src="/mekii-logo.png"
              alt="Mekii"
              className="h-9 w-auto object-contain"
            />
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            <Link to="/app">
              <Button
                variant={location.pathname === "/app" ? "secondary" : "ghost"}
                size="sm"
                className="gap-2"
              >
                <History className="h-4 w-4" />
                My Analyses
              </Button>
            </Link>
            <Link to="/app/new">
              <Button
                variant={location.pathname === "/app/new" ? "secondary" : "ghost"}
                size="sm"
                className="gap-2"
              >
                <Plus className="h-4 w-4" />
                New Analysis
              </Button>
            </Link>
          </nav>
        </div>

        {/* Right: User Menu */}
        <div className="flex items-center gap-3">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="gap-2">
                <div className="h-7 w-7 rounded-full bg-primary/10 flex items-center justify-center text-xs font-semibold text-primary">
                  {user?.name?.charAt(0).toUpperCase() ?? "U"}
                </div>
                <span className="hidden sm:block text-sm font-medium max-w-[120px] truncate">
                  {user?.name}
                </span>
                <ChevronDown className="h-3 w-3 text-muted-foreground" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuItem className="gap-2">
                <User className="h-4 w-4" />
                Profile
              </DropdownMenuItem>
              <DropdownMenuItem className="gap-2">
                <Settings className="h-4 w-4" />
                Settings
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem className="gap-2 text-destructive" onClick={handleLogout}>
                <LogOut className="h-4 w-4" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* Page Content */}
      <main className="flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="h-full"
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
