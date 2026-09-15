const STORAGE_KEY = "ptm-runtime-banner-seen";
const HIGHLIGHT_MS = 20 * 60 * 1000;

export interface RuntimeCluster {
  at?: string;
  at_kst: string;
  ids: string[];
  labels: string[];
}

export interface RuntimeDeployEvent {
  at?: string;
  at_kst: string;
  kind: string;
  commit: string;
  version: string;
  built: string[];
  built_labels: string[];
  restarted: string[];
  restarted_labels: string[];
}

export interface RuntimeContainer {
  id: string;
  short: string;
  status: string;
  started_at: string;
  started_at_kst: string;
  image_id: string;
  image_created: string;
  image_created_kst: string;
}

export interface RuntimeBannerData {
  version: string;
  git_hash: string;
  git_date: string;
  applied_at_kst?: string;
  last_deploy: RuntimeDeployEvent | null;
  latest_restart: RuntimeCluster | null;
  latest_image: RuntimeCluster | null;
  containers: RuntimeContainer[];
}

interface SeenSnapshot {
  git_hash: string;
  git_date: string;
  deploy_at: string;
  containers: Record<string, { started_at: string; image_id: string }>;
  changes: string[];
  highlighted_until: number;
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

export function formatVersionDisplay(raw: string): string {
  const parts = raw.split(".").map((s) => String(parseInt(s, 10) || 0));
  if (parts.length >= 3) return parts.slice(0, 3).join(".");
  while (parts.length < 3) parts.push("0");
  return parts.join(".");
}

export function parseKst(kst: string): Date | null {
  const text = (kst || "").trim();
  if (!text) return null;
  const d = new Date(text.includes("T") ? text : text.replace(" ", "T") + "+09:00");
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatStampShort(kst: string): string {
  const d = parseKst(kst);
  if (!d) return kst;
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi}`;
}

export function relativeFromKst(kst: string, now = Date.now()): string {
  const d = parseKst(kst);
  if (!d) return "";
  const mins = Math.max(0, Math.floor((now - d.getTime()) / 60000));
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  return `${days}일 전`;
}

function snapshotFromBanner(data: RuntimeBannerData): Omit<SeenSnapshot, "changes" | "highlighted_until"> {
  const containers: SeenSnapshot["containers"] = {};
  for (const c of data.containers || []) {
    containers[c.id] = { started_at: c.started_at || "", image_id: c.image_id || "" };
  }
  return {
    git_hash: data.git_hash || "",
    git_date: data.git_date || "",
    deploy_at: data.last_deploy?.at || data.last_deploy?.at_kst || "",
    containers,
  };
}

export function describeRuntimeChanges(
  previous: SeenSnapshot | null,
  data: RuntimeBannerData,
): string[] {
  if (!previous) return [];
  const changes: string[] = [];
  if ((data.git_hash || "") !== previous.git_hash || (data.git_date || "") !== previous.git_date) {
    changes.push("커밋 표시");
  }

  const deployAt = data.last_deploy?.at || data.last_deploy?.at_kst || "";
  if (data.last_deploy && deployAt && deployAt !== previous.deploy_at) {
    for (const label of data.last_deploy.built_labels || []) {
      changes.push(`${label} 빌드`);
    }
    const built = new Set(data.last_deploy.built_labels || []);
    for (const label of data.last_deploy.restarted_labels || []) {
      if (!built.has(label)) changes.push(`${label} 재시작`);
    }
    return unique(changes);
  }

  for (const c of data.containers || []) {
    const before = previous.containers[c.id];
    if (!before) continue;
    const imageChanged = Boolean(c.image_id) && c.image_id !== before.image_id;
    const startedChanged = Boolean(c.started_at) && c.started_at !== before.started_at;
    if (imageChanged) changes.push(`${c.short} 빌드`);
    else if (startedChanged) changes.push(`${c.short} 재시작`);
  }
  return unique(changes);
}

export function rememberRuntimeBanner(data: RuntimeBannerData): string[] {
  let previous: SeenSnapshot | null = null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    previous = raw ? (JSON.parse(raw) as SeenSnapshot) : null;
  } catch {
    previous = null;
  }

  const now = Date.now();
  const nextSnap = snapshotFromBanner(data);
  const freshChanges = describeRuntimeChanges(previous, data);
  const keepHighlight = previous && previous.highlighted_until > now ? previous.changes : [];
  const changes = freshChanges.length ? freshChanges : keepHighlight;

  const stored: SeenSnapshot = {
    ...nextSnap,
    changes,
    highlighted_until: freshChanges.length ? now + HIGHLIGHT_MS : previous?.highlighted_until || 0,
  };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
  } catch {
    /* ignore quota */
  }
  if (!stored.highlighted_until || stored.highlighted_until <= now) return [];
  return stored.changes;
}

export function restartSummary(data: RuntimeBannerData): string {
  const cluster = data.latest_restart;
  if (!cluster?.at_kst) return "";
  const labels = (cluster.labels || []).slice(0, 3).join(", ");
  const more = (cluster.labels || []).length > 3 ? "…" : "";
  return `${labels}${more} · ${relativeFromKst(cluster.at_kst)}`;
}
