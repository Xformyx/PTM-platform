export type ScatterAxis = "adjusted" | "unadjusted" | "occupancy";
export type Bounds = [number, number, number, number];
export type ScatterPoint = {
  x: number; y: number; source_row: number; feature_id: string | null;
  precursor_id: string; charge: string; gene: string; site: string;
  protein_group: string; taxon: string; pair_quality_tier: string;
  accession: string; isoform: string; modified_sequence: string;
};
export type ScatterCondition = {
  condition: string; source_rows: number; represented_rows: number; excluded_rows: number;
  identity_unresolved_rows: number; exclusion_reasons: Record<string, number>;
  mode: "points" | "density"; points: ScatterPoint[];
  bins: { ix: number; iy: number; count: number }[];
};
export type ScatterOverview = {
  contract_version: "source_vector_scatter.v1"; measurement_revision: string; axis: ScatterAxis;
  unit: "source_vector_row"; status: "ready" | "empty_source" | "no_eligible_observations";
  source: { kind: string; filename: string; sha256: string };
  bounds: Bounds | null; bin_resolution: number; point_limit_per_condition: number;
  coverage: { source_rows: number; represented_rows: number; excluded_rows: number;
    identity_unresolved_represented_rows: number; sampled_out_rows: number; exclusion_reasons: Record<string, number> };
  conditions: ScatterCondition[];
};
export const SCATTER_PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];
export const scatterAxes: Record<ScatterAxis, { label: string; short: string }> = {
  adjusted: { label: "Protein-adjusted PTM (A)", short: "A log₂FC" },
  unadjusted: { label: "Independent PTM (U)", short: "U log₂FC" },
  occupancy: { label: "Paired occupancy", short: "Occupancy Δlogit" },
};
export const exclusionLabels: Record<string, string> = {
  malformed_source_row: "열 개수 불일치", condition_missing: "조건 없음", control_reference_row: "Control 기준행",
  protein_axis_unavailable: "Protein 축 없음", ptm_axis_ineligible: "PTM 축 부적격", occupancy_ineligible: "Occupancy 부적격",
};
export function conditionMinutes(label: string): number {
  const match = label.match(/(\d+(?:\.\d+)?)\s*(milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\b/i);
  if (!match) return Infinity;
  const unit = match[2].toLowerCase(), value = Number(match[1]);
  if (unit === "ms" || unit.startsWith("msec") || unit.startsWith("millisecond")) return value / 60000;
  if (unit.startsWith("s")) return value / 60;
  if (unit.startsWith("h")) return value * 60;
  if (unit.startsWith("d")) return value * 1440;
  return value;
}
export function orderedConditions(conditions: ScatterCondition[]): ScatterCondition[] {
  return [...conditions].sort((a, b) => conditionMinutes(a.condition) - conditionMinutes(b.condition)
    || a.condition.localeCompare(b.condition));
}
export function viewportBounds(bounds: Bounds, zoom: number): Bounds {
  const scale = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
  const width = Math.max(bounds[1] - bounds[0], 1), height = Math.max(bounds[3] - bounds[2], 1);
  const cx = bounds[0] / 2 + bounds[1] / 2, cy = bounds[2] / 2 + bounds[3] / 2;
  return [cx - width * .6 / scale, cx + width * .6 / scale, cy - height * .6 / scale, cy + height * .6 / scale];
}
export function binBounds(bin: { ix: number; iy: number }, bounds: Bounds, resolution: number): Bounds {
  const dx = (bounds[1] - bounds[0]) / resolution, dy = (bounds[3] - bounds[2]) / resolution;
  return [bounds[0] + bin.ix * dx, bounds[0] + (bin.ix + 1) * dx,
    bounds[2] + bin.iy * dy, bounds[2] + (bin.iy + 1) * dy];
}
export function scatterCount(condition: ScatterCondition): number {
  return condition.mode === "points" ? condition.points.length : condition.bins.reduce((sum, bin) => sum + bin.count, 0);
}
