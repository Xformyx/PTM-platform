import { Navigate, Routes, Route } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import Layout from '@/components/layout/Layout';
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

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginGuard />} />
      <Route element={<ProtectedRoutes />}>
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
      </Route>
    </Routes>
  );
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
    return <Navigate to="/" replace />;
  }

  return <Login />;
}
