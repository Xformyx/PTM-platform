export type AnalysisContext = Record<string, unknown>;
export type DesignSample = { sample_id: string; condition: string };
export type ManifestSample = DesignSample & {
  biological_unit: string;
  technical_injection?: string | number;
  [key: string]: unknown;
};
export type SampleManifest = {
  schema_version: string;
  pairing: "paired" | "unpaired";
  samples: ManifestSample[];
  conditions?: Array<{ condition: string; time_minutes?: number | null; [key: string]: unknown }>;
  [key: string]: unknown;
};

export function mergeAnalysisContext(existing: AnalysisContext | null | undefined, fields: AnalysisContext): AnalysisContext {
  return { ...(existing ?? {}), ...fields };
}

/** Match the API's condition grouping; replicate suffixes never assign study units. */
export function designSamples(config: unknown): DesignSample[] {
  const rows = Array.isArray(config) ? config : (config as { samples?: unknown[] } | null)?.samples ?? [];
  return rows.flatMap((entry) => {
    const row = entry as Record<string, unknown>;
    const filename = String(row.file_name ?? row.File_Name ?? row.filename ?? "");
    if (!filename) return [];
    const group = String(row.group ?? row.Group ?? "").trim();
    let condition = String(row.condition ?? row.Condition ?? "").trim();
    const replicate = row.replicate ?? row.Replicate;
    if (group.toLowerCase() === "control") condition = "Control";
    else if (condition && replicate != null && condition.endsWith(`_${replicate}`)) condition = condition.slice(0, -String(replicate).length - 1);
    return [{ sample_id: filename, condition: condition || group || "Unknown" }];
  });
}

export function sampleManifest(value: unknown): SampleManifest | null {
  if (!value || typeof value !== "object" || !Array.isArray((value as SampleManifest).samples)) return null;
  return value as SampleManifest;
}

export function designErrors(context: AnalysisContext, samples: DesignSample[], secondary: DesignSample[] = []): string[] {
  const errors: string[] = [];
  for (const [key, rows, label] of [["sample_manifest", samples, "Primary"], ["secondary_sample_manifest", secondary, "Secondary"]] as const) {
    if (context[key] == null) continue;
    const manifest = sampleManifest(context[key]);
    if (!manifest) { errors.push(`${label} sample design is invalid.`); continue; }
    const assigned = new Map(manifest.samples.map((s) => [s.sample_id, s]));
    if (assigned.size !== manifest.samples.length || assigned.size !== rows.length || rows.some((s) => !assigned.has(s.sample_id) || assigned.get(s.sample_id)?.condition !== s.condition)) {
      errors.push(`${label} sample design must match the configured samples and conditions.`);
    }
    if (manifest.samples.some((s) => !String(s.biological_unit ?? "").trim())) errors.push(`${label} samples require a biological unit for every injection.`);
  }
  if (['legacy_plus_report_compatible.v1','enrichment_free_primary.v2'].includes(String(context.quantitation_export_mode))) {
    const manifest = sampleManifest(context.sample_manifest);
    const conditions = [...new Set(samples.map(s => s.condition))];
    const times = new Map(manifest?.conditions?.map(c => [c.condition, c.time_minutes]) ?? []);
    if (!manifest || conditions.some(c => times.get(c) == null || !Number.isFinite(times.get(c))) || times.get('Control') !== 0 || new Set(times.values()).size !== times.size) {
      errors.push('Additional form evidence requires a complete sample design and unique condition times, with Control at 0 minutes.');
    }
  }
  if (context.quantitation_export_mode === 'enrichment_free_primary.v2') {
    if (context.enrichment_status !== 'enrichment_free') errors.push('Declare enrichment-free acquisition for primary A analysis.');
    if (!/^[a-f0-9]{64}$/.test(String(context.annotation_snapshot_sha256 ?? ''))) errors.push('Select a registered frozen annotation snapshot.');
  }
  return errors;
}
