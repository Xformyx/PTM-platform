import { Navigate, Routes, Route } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import Layout from '@/components/layout/Layout';
import UserLayout from '@/components/user/UserLayout';
import Login from '@/pages/Login';
import ForcePasswordChange from '@/components/ForcePasswordChange';
import Dashboard from '@/pages/Dashboard';
import OrderList from '@/pages/OrderList';
import OrderCreate from '@/pages/OrderCreate';
import OrderDetail from '@/pages/OrderDetail';
import RagManagement from '@/pages/RagManagement';
import RagCollectionDetail from '@/pages/RagCollectionDetail';
import LlmConfig from '@/pages/LlmConfig';
import Articles from '@/pages/Articles';
import Reports from '@/pages/Reports';
import Logs from '@/pages/Logs';
import Settings from '@/pages/Settings';
import SystemMonitor from '@/pages/SystemMonitor';
import PTMQuant from '@/pages/PTMQuant';
import Landing from '@/pages/user/Landing';
import UserDashboard from '@/pages/user/UserDashboard';
import NewAnalysis from '@/pages/user/NewAnalysis';
import AnalysisReport from '@/pages/user/AnalysisReport';
import { Loader2 } from 'lucide-react';

function ProtectedRoutes() {
  const { user, isLoading, mustChangePassword } = useAuth();
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (mustChangePassword) {
    return <ForcePasswordChange />;
  }
  return <Layout />;
}

function UserProtectedRoutes() {
  const { user, isLoading, mustChangePassword } = useAuth();
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (mustChangePassword) {
    return <ForcePasswordChange />;
  }
  return <UserLayout />;
}

export default function App() {
  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/" element={<LandingGuard />} />
      <Route path="/login" element={<LoginGuard />} />

      {/* General User Routes (simplified UI) */}
      <Route path="/app" element={<UserProtectedRoutes />}>
        <Route index element={<UserDashboard />} />
        <Route path="new" element={<NewAnalysis />} />
        <Route path=":id" element={<AnalysisReport />} />
      </Route>

      {/* Admin Routes (full admin UI) */}
      <Route path="/admin" element={<ProtectedRoutes />}>
        <Route index element={<Dashboard />} />
        <Route path="system-monitor" element={<SystemMonitor />} />
        <Route path="orders" element={<OrderList />} />
        <Route path="orders/new" element={<OrderCreate />} />
        <Route path="orders/:id" element={<OrderDetail />} />
        <Route path="rag" element={<RagManagement />} />
        <Route path="rag/:id" element={<RagCollectionDetail />} />
        <Route path="llm" element={<LlmConfig />} />
        <Route path="articles" element={<Articles />} />
        <Route path="reports" element={<Reports />} />
        <Route path="logs" element={<Logs />} />
        <Route path="settings" element={<Settings />} />
        <Route path="ptmquant" element={<PTMQuant />} />
      </Route>

      {/* Legacy routes: redirect old paths to /admin */}
      <Route path="/orders" element={<Navigate to="/admin/orders" replace />} />
      <Route path="/orders/new" element={<Navigate to="/admin/orders/new" replace />} />
      <Route path="/orders/:id" element={<Navigate to="/admin/orders/:id" replace />} />
    </Routes>
  );
}

/** Landing page for unauthenticated users, redirect authenticated users based on role */
function LandingGuard() {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }
  if (user) {
    if (user.role === "admin" || user.role === "analyst") {
      return <Navigate to="/admin" replace />;
    }
    return <Navigate to="/app" replace />;
  }
  return <Landing />;
}

/** Redirect already-logged-in users away from /login */
function LoginGuard() {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }
  if (user) {
    if (user.role === "admin" || user.role === "analyst") {
      return <Navigate to="/admin" replace />;
    }
    return <Navigate to="/app" replace />;
  }
  return <Login />;
}
