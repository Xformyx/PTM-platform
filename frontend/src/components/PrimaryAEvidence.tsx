import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';

type Evidence = {
  run_id:string;
  counts:Record<string,number>;
  provenance:{provenance_id:string; normalization:{normalization_policy:string}; estimator_versions:Record<string,string>};
  analysis_readiness?:{strict_attribution?:string|{status:string;reason?:string};kinase?:{status:string;reason?:string};source_caution?:string[]};
  primary_profiles:Array<{entity:string;time_min:number;contrast_id?:string;target_label?:string;reference_label?:string;gene_balanced_mean:number|null;descriptive_pattern:string;n_sites_or_units:number;n_substrate_genes:number}>;
};
const countLabels:Record<string,string> = {forms:'PTM forms',primary_comparisons:'Eligible form comparisons',kinase_profiles_v1:'Profile rows (entity × mode × time)',kinase_profiles:'Profile rows (entity × mode × contrast)'};

export default function PrimaryAEvidence({orderId,status}:{orderId:number;status:string}) {
  const [data,setData] = useState<Evidence|null>(null);
  const [error,setError] = useState('');
  const [entity,setEntity] = useState('');
  useEffect(() => {
    let active = true;
    api.get<Evidence>(`/orders/${orderId}/enrichment-free-evidence`).then(r => {if(active){setData(r);setEntity(r.primary_profiles[0]?.entity??'');setError('');}})
      .catch(e => {if(active) setError(e.message);});
    return () => {active=false;};
  },[orderId,status]);
  const download = async (artifact:string,name:string) => {
    try {
      const url = await api.fetchBlobUrl(`/orders/${orderId}/enrichment-free-evidence?artifact=${artifact}`);
      const anchor=document.createElement('a'); anchor.href=url; anchor.download=name; anchor.click();
      setTimeout(()=>URL.revokeObjectURL(url),10000);
    } catch(e) {setError(String(e));}
  };
  return <section className="space-y-4 rounded-lg border p-5" aria-label="Primary A evidence">
    <h2 className="text-xl font-semibold">Primary A evidence</h2>
    <p className="text-sm">Parent-adjusted form responses, U/P comparison modes, paired parent sensitivity, emergence and protein time courses. The Astra bundle includes kinase footprints when compatible annotation analysis was performed.</p>
    {error && <p role="alert" className="text-sm text-muted-foreground">{error}</p>}
    {data && <>
      <div className="grid gap-3 sm:grid-cols-3">{Object.entries(data.counts).map(([key,n]) => <div key={key} className="rounded border p-3"><div className="text-2xl font-semibold">{n.toLocaleString()}</div><div className="text-sm">{countLabels[key] ?? key}</div></div>)}</div>
      <p className="break-all text-xs">Recorded run: {data.run_id}<br/>Provenance: {data.provenance.provenance_id}<br/>Normalization: {data.provenance.normalization.normalization_policy}</p>
      <p className="text-sm">Strict attribution: {typeof data.analysis_readiness?.strict_attribution==='object'?data.analysis_readiness.strict_attribution.status:data.analysis_readiness?.strict_attribution??'See recorded readiness'}. {data.analysis_readiness?.kinase&&`Kinase analysis: ${data.analysis_readiness.kinase.status}.`} Low confidence does not establish absence of a biological response. Technical injections do not establish biological replication; no biological p/q is generated.</p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={()=>download('astra',`astra_${data.run_id}.zip`)}>Download Astra bundle</Button>
        <Button variant="outline" onClick={()=>download('report',`evidence_${data.run_id}.html`)}>Download evidence report</Button>
        <Button variant="outline" onClick={()=>download('primary_input','primary_A_input.csv')}>Download primary A</Button>
      </div>
      <label className="block text-sm">Candidate kinase / family<select aria-label="Candidate kinase / family" value={entity} onChange={e=>setEntity(e.target.value)} className="ml-3 rounded border bg-background p-2">
        {[...new Set(data.primary_profiles.map(p=>p.entity))].sort().map(e=><option key={e}>{e}</option>)}
      </select></label>
      <div className="overflow-auto"><table className="w-full text-sm"><thead><tr className="text-left"><th>Target / reference (minutes)</th><th>Footprint</th><th>Sites / genes</th><th>Descriptive pattern</th></tr></thead>
        <tbody>{data.primary_profiles.filter(p=>p.entity===entity).map(p=><tr key={p.contrast_id??p.time_min} className="border-t"><td className="py-2">{p.target_label?`${p.target_label} / ${p.reference_label} (${p.time_min})`:p.time_min}</td><td>{p.gene_balanced_mean?.toFixed(4) ?? 'Unavailable'}</td><td>{p.n_sites_or_units} / {p.n_substrate_genes}</td><td>{p.descriptive_pattern}</td></tr>)}</tbody></table></div>
      <p className="text-xs text-muted-foreground">Consult the recorded annotation/source sensitivities. Alternative parent default: {data.provenance.estimator_versions.strict_parent_default}. Displayed provenance belongs to this completed run, even if order settings were subsequently edited.</p>
    </>}
  </section>;
}
