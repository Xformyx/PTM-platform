import { useEffect, useRef, useState, useCallback } from 'react';
import type { ProgressEvent } from '@/lib/types';

export function useOrderProgress(orderId: number | null) {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!orderId) return;

    const es = new EventSource(`/api/events/orders/${orderId}`);
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);

    es.addEventListener('progress', (event) => {
      try {
        const data: ProgressEvent = {
          ...JSON.parse(event.data),
          _ts: Date.now(),
        };
        setProgress(data);
        setEvents((prev) => [...prev, data]);
      } catch {
        // ignore parse errors
      }
    });

    es.onerror = () => {
      setConnected(false);
      es.close();
      setTimeout(connect, 3000);
    };
  }, [orderId]);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [connect]);

  const disconnect = useCallback(() => {
    eventSourceRef.current?.close();
    setConnected(false);
  }, []);

  return { progress, events, connected, disconnect };
}
