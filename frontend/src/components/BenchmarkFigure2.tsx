/**
 * Figure 2 display for a completed locked score. It rearranges existing
 * metrics and anchor rows; it does not compute a new primary score.
 */
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type Figure2Source = {
  schema_version?: string;
  primary_score_unchanged?: boolean;
  ci_available?: boolean;
  partial_window_available?: boolean;
  panel_2a_metrics?: Array<{
    key: string;
    label: string;
    estimate: number | null;
    numerator?: number | null;
    denominator?: number | null;
  }>;
  panel_2b_branches?: Array<{
    branch: string;
    n_evaluable: number;
    detectable_anchor_recall: number | null;
    regulated_anchor_recall: number | null;
    direction_accuracy: number | null;
    peak_window_accuracy: number | null;
  }>;
  panel_2c_anchors?: Array<{
    anchor_id: string;
    tier?: string;
    branch?: string;
    window_status: string;
    regulation_status: string;
    is_measurable: boolean;
    detected: boolean;
    regulated: boolean;
  }>;
  panel_2d_status?: Record<string, number>;
};

const BRANCH_METRICS = [
  { key: "detectable_anchor_recall", label: "Detect" },
  { key: "regulated_anchor_recall", label: "Regulate" },
  { key: "direction_accuracy", label: "Direction" },
  { key: "peak_window_accuracy", label: "Peak" },
] as const;

const STATUS_LABELS: Record<string, string> = {
  not_measurable: "Not measurable",
  measurable_not_detected: "Measurable, not detected",
  detected_not_regulated: "Detected, not regulated",
  correct_regulation: "Correct regulation",
};

const WINDOW_TONE: Record<string, string> = {
  match: "bg-emerald-100 text-emerald-800 border-emerald-200",
  miss: "bg-red-100 text-red-800 border-red-200",
  not_evaluable: "bg-muted text-muted-foreground border-transparent",
};

function pct(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(0)}%`;
}

function heat(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "bg-muted text-muted-foreground";
  if (value >= 0.75) return "bg-emerald-200 text-emerald-950";
  if (value >= 0.4) return "bg-amber-100 text-amber-950";
  return "bg-red-100 text-red-900";
}

export function BenchmarkFigure2({ figure2 }: { figure2: Figure2Source }) {
  const bars = (figure2.panel_2a_metrics || []).map((row) => ({
    name: row.label,
    value: typeof row.estimate === "number" ? Number((row.estimate * 100).toFixed(1)) : 0,
    raw: row.estimate,
    n: row.numerator,
    d: row.denominator,
  }));
  const status = figure2.panel_2d_status || {};
  const statusBars = Object.entries(STATUS_LABELS).map(([key, label]) => ({
    name: label,
    count: status[key] || 0,
  }));

  return (
    <div className="space-y-4 rounded-lg border bg-background p-4">
      <div>
        <p className="text-sm font-medium">Figure 2 · Blind anchor recovery</p>
        <p className="text-xs text-muted-foreground">
          Locked score display only. Bootstrap CI and partial peak-window matches are not in this bundle.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">2A Component scores</p>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bars}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-18} textAnchor="end" height={56} />
                <YAxis tick={{ fontSize: 10 }} domain={[0, 100]} unit="%" />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const row = payload[0].payload as { name: string; value: number; n?: number; d?: number };
                    const denom = row.n != null && row.d != null ? ` (${row.n}/${row.d})` : "";
                    return (
                      <div className="rounded-md border bg-popover px-2 py-1 text-xs shadow-md">
                        <p className="font-medium">{row.name}</p>
                        <p>{row.value.toFixed(1)}%{denom}</p>
                      </div>
                    );
                  }}
                />
                <Bar dataKey="value" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">2D Detection vs regulation</p>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusBars} layout="vertical" margin={{ left: 8, right: 8 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#64748b" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">2B Branch rates (unweighted display)</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1 pr-2 font-medium">Branch</th>
                <th className="py-1 pr-2 font-medium">n</th>
                {BRANCH_METRICS.map((metric) => (
                  <th key={metric.key} className="py-1 pr-2 font-medium">{metric.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(figure2.panel_2b_branches || []).map((row) => (
                <tr key={row.branch}>
                  <td className="py-1 pr-2">{row.branch}</td>
                  <td className="py-1 pr-2 font-mono">{row.n_evaluable}</td>
                  {BRANCH_METRICS.map((metric) => {
                    const value = row[metric.key];
                    return (
                      <td key={metric.key} className="py-1 pr-2">
                        <span className={`inline-block min-w-[3rem] rounded px-1.5 py-0.5 text-center font-mono ${heat(value)}`}>{pct(value)}</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">2C Anchor window match</p>
        <div className="flex flex-wrap gap-1.5">
          {(figure2.panel_2c_anchors || []).map((row) => (
            <span
              key={row.anchor_id}
              title={`${row.anchor_id} · ${row.tier || ""} · ${row.branch || ""} · ${row.regulation_status}`}
              className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${WINDOW_TONE[row.window_status] || WINDOW_TONE.not_evaluable}`}
            >
              {row.anchor_id} {row.window_status}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
