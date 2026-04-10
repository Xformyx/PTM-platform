const API_BASE = '/api';
const TOKEN_KEY = 'ptm-token';

function getAuthHeader(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeader(),
      ...options?.headers,
    },
    ...options,
  });

  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  if (!res.ok) {
    const raw = await res.json().catch(() => null);
    const msg = formatApiDetail(raw, res.status, res.statusText);
    throw new Error(msg);
  }

  return res.json();
}

/** Normalize FastAPI / gateway error bodies for user-visible messages */
function formatApiDetail(
  raw: unknown,
  status: number,
  statusText: string,
): string {
  if (!raw || typeof raw !== 'object') return `Request failed: ${status} ${statusText}`;
  const r = raw as Record<string, unknown>;
  const d = r.detail ?? r.message ?? r.error;
  if (typeof d === 'string' && d.trim()) return d;
  if (Array.isArray(d)) {
    const parts = d.map((item: unknown) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        const o = item as { msg?: string; loc?: unknown };
        const loc = Array.isArray(o.loc) ? o.loc.join('.') : '';
        return loc ? `${loc}: ${o.msg ?? ''}` : (o.msg ?? JSON.stringify(item));
      }
      return String(item);
    });
    return parts.filter(Boolean).join('; ') || `Request failed: ${status}`;
  }
  if (d && typeof d === 'object') return JSON.stringify(d);
  return `Request failed: ${status} ${statusText}`;
}

export const api = {
  get: <T>(path: string) => request<T>(path),

  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),

  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    }),

  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),

  upload: async <T>(path: string, formData: FormData): Promise<T> => {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { ...getAuthHeader() },
      body: formData,
    });
    if (!res.ok) {
      const raw = await res.json().catch(() => null);
      throw new Error(formatApiDetail(raw, res.status, res.statusText));
    }
    return res.json();
  },

  /** Fetch a binary resource with auth header and return an object URL for display */
  fetchBlobUrl: async (path: string): Promise<string> => {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { ...getAuthHeader() },
    });
    if (res.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (!res.ok) {
      const raw = await res.json().catch(() => null);
      throw new Error(formatApiDetail(raw, res.status, res.statusText));
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },

  /** Fetch a file with auth header and trigger browser download */
  downloadFile: async (path: string, filename: string): Promise<void> => {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { ...getAuthHeader() },
    });
    if (res.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (!res.ok) {
      const raw = await res.json().catch(() => null);
      throw new Error(formatApiDetail(raw, res.status, res.statusText));
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
};
