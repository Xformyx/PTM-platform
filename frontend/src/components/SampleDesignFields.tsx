import { Button } from "@/components/ui/button";
import CanonicalStudyFields from './CanonicalStudyFields';
import FrozenAnnotationFields from './FrozenAnnotationFields';
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { designErrors, sampleManifest } from "@/lib/analysisContext";
import type { AnalysisContext, DesignSample, SampleManifest } from "@/lib/analysisContext";

export default function SampleDesignFields({ context, onChange, samples, secondarySamples = [], species='human', ptmType='phosphorylation' }: {
  context: AnalysisContext;
  onChange: (context: AnalysisContext) => void;
  samples: DesignSample[];
  secondarySamples?: DesignSample[];
  species?:string;
  ptmType?:string;
}) {
  const put = (key: string, value: unknown) => onChange({ ...context, [key]: value });
  const errors = designErrors(context, samples, secondarySamples);
  const mode = typeof context.quantitation_export_mode === "string" ? context.quantitation_export_mode : "";
  const astra=['astra_analysis.v4','astra_analysis.v5'].includes(mode);
  const science=(context.science??{}) as Record<string,unknown>;
  const generic=astra||mode==='enrichment_free_timecourse.v3';
  return <div className="space-y-4 rounded-lg border p-4">
    <div className="space-y-2">
      <Label>Analysis purpose</Label>
      <select aria-label="Analysis purpose" className="block w-full rounded border bg-background p-2 text-sm"
        value={mode}
        onChange={e=>onChange({...context,quantitation_export_mode:e.target.value,normalization_policy:context.normalization_policy??'already_normalized.v1'})}>
        {mode === "" && <option value="">분석 목적을 선택하세요</option>}
        <option value={astra?mode:'astra_analysis.v4'}>Astra 분석 패키지 생성</option>
        <option value="legacy_only.v1">Legacy platform reports</option>
        {mode !== "" && !['astra_analysis.v4','astra_analysis.v5','legacy_only.v1'].includes(mode)&&<option value={mode}>Recorded legacy analysis — preserved</option>}
      </select>
      {astra && <details><summary className="cursor-pointer text-sm">Experimental science validation</summary>
        <p className="text-xs">종은 현재 주문의 {species} 값을 사용합니다. v5는 실험적 분석이며 독립 benchmark 정확도와 실제 atlas parity는 미검증입니다.</p>
        <label className="text-sm"><input type="checkbox" checked={mode==='astra_analysis.v5'} onChange={e=>onChange({...context,quantitation_export_mode:e.target.checked?'astra_analysis.v5':'astra_analysis.v4',science:{...science,experimental_enabled:e.target.checked}})}/> v5 scientific evidence (experimental)</label>
        {mode==='astra_analysis.v5'&&<>
          <label className="block text-sm">Design axis<select aria-label="Design axis" value={String(context.design_axis??'time_course')} onChange={e=>put('design_axis',e.target.value)}><option value="time_course">Time course</option><option value="cross_sectional">Condition contrasts without time</option></select></label>
          <label className="block text-sm">DIA-NN version (only when a report is provided)<Input value={String(science.diann_version??'')} onChange={e=>put('science',{...science,diann_version:e.target.value})}/></label>
          <p className="text-xs">기존 matrix 정량은 유지됩니다. 새 원본 보고서는 관측 audit에 사용하며 run confidence를 개별 site posterior로 바꾸지 않습니다.</p>
        </>}
      </details>}
      <details><summary className="cursor-pointer text-sm">Advanced normalization override</summary>
        <p className="text-xs">New Astra studies preserve supplied intensities. This does not establish upstream DIA-NN normalization. The alternative scaling track is calculated automatically.</p>
        <select aria-label="Additional global normalization" className="block w-full rounded border bg-background p-2 text-sm"
          value={String(context.normalization_policy??'already_normalized.v1')} onChange={e=>put('normalization_policy',e.target.value)}>
          <option value="already_normalized.v1">Use supplied intensities</option><option value="legacy_median.v1">Explicit override: separate PR/PG median scaling</option>
        </select>
      </details>
      {context.quantitation_export_mode === 'enrichment_free_primary.v2' && <div className="space-y-3">
        <p className="text-sm">Rat/Rat_hir full-matrix analysis. Parent-adjusted A is the primary input; U/P explain correction. Produces an evidence report and Astra bundle with frozen kinase, paired parent and late protein layers.</p>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={context.enrichment_status === 'enrichment_free'}
          onChange={e => put('enrichment_status',e.target.checked ? 'enrichment_free' : 'unknown')} />These inputs were acquired without phosphopeptide enrichment</label>
        <FrozenAnnotationFields {...{context,onChange,species,ptmType}}/>
        <p className="text-xs text-muted-foreground">Acquisition information: leave unavailable values blank; exported as unknown.</p>
        <div className="grid grid-cols-2 gap-2">{['injection_amount','starvation_duration','acquisition_conditions','diann_version','diann_processing','diann_normalization'].map(key => {
          const metadata = (context.acquisition_metadata ?? {}) as Record<string,string>;
          return <label key={key} className="text-xs">{key.replace(/_/g,' ')}<Input value={metadata[key] ?? ''}
            onChange={e => put('acquisition_metadata',{...metadata,[key]:e.target.value})} /></label>;
        })}</div>
      </div>}
      {!generic && mode !== "" && <p className="text-xs text-muted-foreground">The legacy additional export requires a complete sample design and unique condition times, with Control at 0 minutes. It includes joint observation masks and parent sensitivity. Existing precursor vectors keep their estimator.</p>}
    </div>
    {generic&&<CanonicalStudyFields {...{context,onChange,samples,species,ptmType}}/>}
    {!generic&&[["sample_manifest", samples, "Primary"], ["secondary_sample_manifest", secondarySamples, "Secondary"]].map(([keyValue, rowValues, label]) => {
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
