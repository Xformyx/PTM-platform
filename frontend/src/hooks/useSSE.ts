import { useEffect, useRef, useState, useCallback } from 'react';
import type { ProgressEvent } from '@/lib/types';

export function useOrderProgress(orderId: number | null) {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!orderId) return;

    // EventSource cannot send custom headers, so pass the JWT as a query param.
    // The server's get_sse_user dependency accepts both Bearer header and ?token=.
    const token = localStorage.getItem('ptm-token');
    const url = `/api/events/orders/${orderId}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);

    es.addEventListener('progress', (event) => {
      try {
        const data: ProgressEvent = {
          ...JSON.parse(event.data),
          _ts: Date.now(),
        };
        setProgress(data);
        setEvents((prev) => {
          const next = [...prev, data];
          return next.length > 500 ? next.slice(-500) : next;
        });
      } catch {
        // ignore parse errors
      }
    });

    es.onerror = () => {
      setConnected(false);
      es.close();
      // Store the timer so it can be cleared if the component unmounts before
      // the reconnect fires, preventing zombie EventSource connections.
      reconnectTimerRef.current = setTimeout(connect, 3000);
    };
  }, [orderId]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      eventSourceRef.current?.close();
    };
  }, [connect]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    eventSourceRef.current?.close();
    setConnected(false);
  }, []);

  return { progress, events, connected, disconnect };
}
