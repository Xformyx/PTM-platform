export type QuantAxis = "relative" | "unadjusted" | "protein";
export type FeatureRef = { feature_id?: string | null; temporal_feature_key?: string; key?: string; gene: string; position: string };
export type QuantRow = FeatureRef & { condition: string; [key: string]: unknown };
export const axisPrefix = { relative: "ptm_protein_adjusted", unadjusted: "ptm_unadjusted", protein: "protein" } as const;
export const axisLabel = { relative: "Protein-adjusted PTM (A)", unadjusted: "Independent PTM (U)", protein: "Total protein (P)" } as const;
export function featureKey(row: FeatureRef): string {
  return row.feature_id || row.temporal_feature_key || (row.key?.startsWith("FEATURE-") ? row.key : null) || `unresolved-site:${row.gene}_${row.position}`;
}
export function finite(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
export function axisValue(row: QuantRow, axis: QuantAxis): number | null {
  const eligibility = row.axis_eligibility as Record<string, { eligible: boolean }> | undefined;
  const name = axis === "relative" ? "adjusted" : axis;
  if (eligibility?.[name]?.eligible === false) return null;
  const value = row[`${axisPrefix[axis]}_log2fc`];
  return finite(value) ? value : null;
}
export function axisQ(row: QuantRow, axis: QuantAxis): number | null {
  const value = row[`${axisPrefix[axis]}_q_value`];
  return finite(value) ? value : null;
}
export function supportedChange(rows: QuantRow[], axis: QuantAxis): boolean {
  return rows.some(row => {
    const effect = axisValue(row, axis), q = axisQ(row, axis);
    return effect !== null && q !== null && q >= 0 && q < .05 && Math.abs(effect) >= 1;
  });
}
export function observedGrid(rows: QuantRow[], feature: FeatureRef, conditions: string[], axis: QuantAxis): (number | null)[] {
  return conditions.map(condition => {
    const matches = rows.filter(row => featureKey(row) === featureKey(feature) && row.condition === condition);
    // Conflicting rows require upstream resolution, never first-row selection.
    const values = [...new Set(matches.map(row => axisValue(row, axis)))];
    return values.length === 1 ? values[0] : null;
  });
}

// A unique sampled extremum requires a complete observed grid. This is not a
// biological peak estimate or a statistical test of a temporal pattern.
export function sampledExtremumIndex(values: (number | null)[]): number | null {
  if (values.length < 2 || !values.every(finite)) return null;
  const magnitudes = values.map(Math.abs);
  const maximum = Math.max(...magnitudes);
  const matches = magnitudes.flatMap((v, i) => v === maximum ? [i] : []);
  return matches.length === 1 ? matches[0] : null;
}

// Legacy site-level kinase annotations may highlight all corresponding forms;
// this is contextual selection, never a quantitative aggregation.
export function expandContextSelection(keys: string[], features: FeatureRef[]): string[] {
  return features.filter(p => keys.includes(featureKey(p)) || keys.includes(`${p.gene}_${p.position}`) || keys.includes(`unresolved-site:${p.gene}_${p.position}`)).map(featureKey);
}
