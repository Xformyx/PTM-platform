import { getAuthHeader } from "@/lib/api";

/** Open EventSource with a short-lived ticket instead of putting the JWT in the URL. */
export async function openEventSource(path: string): Promise<EventSource> {
  const res = await fetch("/api/events/ticket", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeader(),
    },
  });
  if (!res.ok) {
    throw new Error("Failed to issue SSE ticket");
  }
  const data = (await res.json()) as { ticket?: string };
  if (!data.ticket) {
    throw new Error("SSE ticket missing");
  }
  const sep = path.includes("?") ? "&" : "?";
  return new EventSource(`${path}${sep}ticket=${encodeURIComponent(data.ticket)}`);
}
