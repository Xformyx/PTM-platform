import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { designErrors, sampleManifest } from "@/lib/analysisContext";
import type { AnalysisContext, DesignSample, SampleManifest } from "@/lib/analysisContext";

export default function SampleDesignFields({ context, onChange, samples, secondarySamples = [] }: {
  context: AnalysisContext;
  onChange: (context: AnalysisContext) => void;
  samples: DesignSample[];
  secondarySamples?: DesignSample[];
}) {
  const put = (key: string, value: unknown) => onChange({ ...context, [key]: value });
  const errors = designErrors(context, samples, secondarySamples);
  return <div className="space-y-4 rounded-lg border p-4">
    <div className="space-y-2">
      <Label>Additional global normalization</Label>
      <select className="block w-full rounded border bg-background p-2 text-sm"
        aria-label="Additional global normalization"
        value={String(context.normalization_policy ?? "legacy_median.v1")}
        onChange={(e) => put("normalization_policy", e.target.value)}>
        <option value="legacy_median.v1">Scale PR and PG separately by sample median</option>
        <option value="already_normalized.v1">Use supplied intensities without additional scaling</option>
      </select>
      <p className="text-xs text-muted-foreground">This choice does not establish how DIA-NN normalized the input.</p>
      <Label>Additional form evidence export (phosphorylation)</Label>
      <select aria-label="Additional form evidence export" className="block w-full rounded border bg-background p-2 text-sm"
        value={String(context.quantitation_export_mode ?? "legacy_only.v1")}
        onChange={(e) => put("quantitation_export_mode", e.target.value)}>
        <option value="legacy_only.v1">Standard analysis outputs</option>
        <option value="legacy_plus_report_compatible.v1">Also export charge-collapsed mean-log form evidence</option>
      </select>
      <p className="text-xs text-muted-foreground">The additional export requires a complete sample design and condition times, with Control at 0 minutes. It includes joint observation masks and parent sensitivity. Existing precursor vectors keep their estimator.</p>
    </div>
    {[["sample_manifest", samples, "Primary"], ["secondary_sample_manifest", secondarySamples, "Secondary"]].map(([keyValue, rowValues, label]) => {
      const key = String(keyValue);
      const rows = rowValues as DesignSample[];
      const manifest = sampleManifest(context[key]);
      if (!rows.length && !manifest) return null;
      const configure = () => {
        const old = new Map(manifest?.samples.map((s) => [s.sample_id, s]) ?? []);
        put(key, { ...manifest, schema_version: "sample_manifest.v1", pairing: manifest?.pairing ?? "unpaired",
          samples: rows.map((s) => ({ biological_unit: "", ...old.get(s.sample_id), ...s })),
          conditions: [...new Set(rows.map((s) => s.condition))].map((condition) => manifest?.conditions?.find((c) => c.condition === condition) ?? { condition }) });
      };
      const update = (patch: Partial<SampleManifest>) => put(key, { ...manifest, ...patch });
      return <div className="space-y-3" key={key}>
        <p className="text-sm font-medium">{String(label)} sample design</p>
        <p className="text-xs text-muted-foreground">Use the same biological unit for repeated injections of the same material. Filename suffixes do not establish biological replication. Without a complete design, effects and detection remain available and biological p/q values are withheld.</p>
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" onClick={configure} disabled={!rows.length}>
            {manifest ? "Match configured samples" : "Enter sample design"}
          </Button>
          {manifest && <Button type="button" variant="ghost" size="sm" onClick={() => put(key, null)}>Clear declared design</Button>}
        </div>
        {manifest && <>
          <Label>Comparison design</Label>
          <select aria-label={`${label} comparison design`} className="block w-full rounded border bg-background p-2 text-sm"
            value={manifest.pairing ?? "unpaired"} onChange={(e) => update({ pairing: e.target.value as "paired" | "unpaired" })}>
            <option value="unpaired">Independent biological units across conditions</option>
            <option value="paired">Same biological units measured across conditions</option>
          </select>
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-xs"><thead><tr className="text-left"><th>Injection</th><th>Condition</th><th>Biological unit</th><th>Technical injection</th></tr></thead>
              <tbody>{manifest.samples.map((s, i) => <tr key={s.sample_id}>
                <td className="max-w-40 break-all pr-2" title={s.sample_id}>{s.sample_id.split(/[\\/]/).pop()}</td><td className="pr-2">{s.condition}</td>
                <td><Input aria-label={`Biological unit ${s.sample_id}`} className="min-w-28" value={s.biological_unit ?? ""}
                  onChange={(e) => update({ samples: manifest.samples.map((v, j) => j === i ? { ...v, biological_unit: e.target.value } : v) })} /></td>
                <td><Input aria-label={`Technical injection ${s.sample_id}`} className="min-w-20" value={s.technical_injection ?? ""}
                  onChange={(e) => update({ samples: manifest.samples.map((v, j) => j === i ? { ...v, technical_injection: e.target.value } : v) })} /></td>
              </tr>)}</tbody></table>
          </div>
          <div className="grid grid-cols-2 gap-2">{[...new Set(manifest.samples.map((s) => s.condition))].map((condition) => {
            const time = manifest.conditions?.find((c) => c.condition === condition)?.time_minutes;
            return <label key={condition} className="text-xs">{condition}{condition === "Control" ? " (baseline)" : ""} — time in minutes
              <Input type="number" step="any" aria-label={`${label} ${condition} time in minutes`} value={time ?? ""}
                onChange={(e) => update({ conditions: [...(manifest.conditions ?? []).filter((c) => c.condition !== condition),
                  { ...manifest.conditions?.find((c) => c.condition === condition), condition, time_minutes: e.target.value === "" ? null : Number(e.target.value) }] })} />
            </label>;
          })}</div>
        </>}
      </div>;
    })}
    {errors.map((error) => <p role="alert" key={error} className="text-xs text-destructive">{error}</p>)}
  </div>;
}
