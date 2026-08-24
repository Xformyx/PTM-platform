import { useEffect, useRef, useState, useCallback } from 'react';
import type { ProgressEvent } from '@/lib/types';
import { openEventSource } from '@/lib/sse';

export function useOrderProgress(orderId: number | null) {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelledRef = useRef(false);

  const connect = useCallback(() => {
    if (!orderId) return;
    cancelledRef.current = false;

    openEventSource(`/api/events/orders/${orderId}`)
      .then((es) => {
        if (cancelledRef.current) {
          es.close();
          return;
        }
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
          reconnectTimerRef.current = setTimeout(connect, 3000);
        };
      })
      .catch(() => {
        if (!cancelledRef.current) {
          reconnectTimerRef.current = setTimeout(connect, 3000);
        }
      });
  }, [orderId]);

  useEffect(() => {
    connect();
    return () => {
      cancelledRef.current = true;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      eventSourceRef.current?.close();
    };
  }, [connect]);

  const disconnect = useCallback(() => {
    cancelledRef.current = true;
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    eventSourceRef.current?.close();
    setConnected(false);
  }, []);

  return { progress, events, connected, disconnect };
}
