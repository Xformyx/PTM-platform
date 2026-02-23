import { Routes, Route } from 'react-router-dom';
import Layout from '@/components/layout/Layout';
import Dashboard from '@/pages/Dashboard';
import OrderList from '@/pages/OrderList';
import OrderCreate from '@/pages/OrderCreate';
import OrderDetail from '@/pages/OrderDetail';
import RagManagement from '@/pages/RagManagement';
import LlmConfig from '@/pages/LlmConfig';
import Articles from '@/pages/Articles';
import Reports from '@/pages/Reports';
import Logs from '@/pages/Logs';
import Settings from '@/pages/Settings';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="orders" element={<OrderList />} />
        <Route path="orders/new" element={<OrderCreate />} />
        <Route path="orders/:id" element={<OrderDetail />} />
        <Route path="rag" element={<RagManagement />} />
        <Route path="llm" element={<LlmConfig />} />
        <Route path="articles" element={<Articles />} />
        <Route path="reports" element={<Reports />} />
        <Route path="logs" element={<Logs />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
