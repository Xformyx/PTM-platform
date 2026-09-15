const DOC_EXT_ORDER: Record<string, number> = {
  ".docx": 0,
  ".html": 1,
  ".md": 2,
};

const FIGURE_EXT = new Set([".png", ".svg", ".jpg", ".jpeg", ".webp"]);
const STAMPED_REPORT = /_report_(\d{6}_\d{4})\.(md|html|docx)$/i;

export interface ReportRevision {
  key: string;
  label: string;
  files: string[];
  latest: boolean;
}

export function isStampedReportDocument(filename: string): boolean {
  return STAMPED_REPORT.test(filename);
}

export function isReportFigure(filename: string): boolean {
  const ext = filename.slice(filename.lastIndexOf(".")).toLowerCase();
  return FIGURE_EXT.has(ext);
}

export function reportRevisionKey(filename: string): string | null {
  const stamped = filename.match(STAMPED_REPORT);
  return stamped ? stamped[1] : null;
}

export function formatRevisionLabel(key: string): string {
  const match = key.match(/^(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})$/);
  if (!match) return key;
  return `20${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}`;
}

export function sortReportBundle(files: string[]): string[] {
  return [...files].sort((a, b) => {
    const extA = a.slice(a.lastIndexOf(".")).toLowerCase();
    const extB = b.slice(b.lastIndexOf(".")).toLowerCase();
    const figureA = FIGURE_EXT.has(extA);
    const figureB = FIGURE_EXT.has(extB);
    if (figureA !== figureB) return figureA ? 1 : -1;
    const rank = (DOC_EXT_ORDER[extA] ?? 9) - (DOC_EXT_ORDER[extB] ?? 9);
    return rank || a.localeCompare(b);
  });
}

export function groupReportRevisions(files: string[]): ReportRevision[] {
  const groups = new Map<string, string[]>();
  for (const name of files) {
    const key = reportRevisionKey(name);
    if (!key) continue;
    const current = groups.get(key) || [];
    current.push(name);
    groups.set(key, current);
  }

  const keys = [...groups.keys()].sort((a, b) => b.localeCompare(a));
  return keys.map((key, index) => ({
    key,
    label: formatRevisionLabel(key),
    files: sortReportBundle(groups.get(key) || []),
    latest: index === 0,
  }));
}

export function bundledReportNames(revisions: ReportRevision[]): Set<string> {
  return new Set(revisions.flatMap((rev) => rev.files));
}
