import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';

type Evidence = {
  run_id:string;
  schema_version?:string;
  study_preview?:{brief:string;transfer_validation:{unexpected_missing:number}};
  counts:Record<string,number>;
  provenance:{provenance_id:string; normalization:{normalization_policy:string}; estimator_versions:Record<string,string>};
  analysis_readiness?:{strict_attribution?:string|{status:string;reason?:string};kinase?:{status:string;reason?:string};source_caution?:string[]};
  primary_profiles:Array<{entity:string;track?:string;time_min:number;contrast_id?:string;target_label?:string;reference_label?:string;gene_balanced_mean:number|null;descriptive_pattern:string;n_sites_or_units:number;n_substrate_genes:number}>;
};
const countLabels:Record<string,string> = {mapped_forms:'Mapped forms',parent_eligible:'Forms with eligible parent',repeated_comparisons:'Comparisons with repeated joint observations',candidate_entities:'Candidate entities (kinases / families / motif classes)',candidate_edges:'Candidate relation rows',kinase_profile_rows:'Profile rows (candidate × contrast × track)',protein_groups:'Protein groups',forms:'PTM forms',primary_comparisons:'Eligible form comparisons',kinase_profiles_v1:'Profile rows (entity × mode × time)',kinase_profiles:'Profile rows (entity × mode × contrast)'};

export default function PrimaryAEvidence({orderId,status}:{orderId:number;status:string}) {
  const [data,setData] = useState<Evidence|null>(null);
  const [error,setError] = useState('');
  const [entity,setEntity] = useState('');
  const [track,setTrack] = useState('curated_A');
  const profiles=data?.primary_profiles.filter(p=>!p.track||p.track===track)??[];
  useEffect(() => {
    let active = true;
    setData(null); setError(''); setEntity('');
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
  const proteinOnly=data?.analysis_readiness?.kinase?.reason==='protein_only_analysis';
  return <section className="space-y-4 rounded-lg border p-5" aria-label="Primary A evidence">
    <h2 className="text-xl font-semibold">Astra 분석 패키지</h2>
    <p className="text-sm">Parent-adjusted form responses, U/P comparison modes, paired parent sensitivity, emergence and protein time courses. The Astra bundle includes kinase footprints when compatible annotation analysis was performed.</p>
    {error && <p role="alert" className="text-sm text-muted-foreground">{error}</p>}
    {data && <>
      {data.schema_version==='astra_analysis_package.v5.experimental'&&<p className="rounded border p-3 text-sm">Experimental v5: 후보 근거와 확정 판단을 구분합니다. 독립 calibration 전 확정 call은 보류되며, 실제 자원 검증과 생물학적 정확도 향상은 별도 검증 대상입니다.</p>}
      <div className="grid gap-3 sm:grid-cols-3">{Object.entries(data.counts).map(([key,n]) => <div key={key} className="rounded border p-3"><div className="text-2xl font-semibold">{n.toLocaleString()}</div><div className="text-sm">{countLabels[key] ?? key}</div></div>)}</div>
      <p className="break-all text-xs">Recorded run: {data.run_id}<br/>Provenance: {data.provenance.provenance_id}<br/>Normalization: {data.provenance.normalization.normalization_policy}</p>
      <p className="text-sm">Strict attribution: {typeof data.analysis_readiness?.strict_attribution==='object'?data.analysis_readiness.strict_attribution.status:data.analysis_readiness?.strict_attribution??'See recorded readiness'}. {data.analysis_readiness?.kinase&&`Kinase analysis: ${data.analysis_readiness.kinase.status}.`} Low confidence does not establish absence of a biological response. Technical injections do not establish biological replication; no biological p/q is generated.</p>
      <div className="flex flex-wrap gap-2">
        <Button onClick={()=>download('astra',`astra_analysis_package_${data.run_id}.zip`)}>패키지 다운로드</Button>
        <Button variant="outline" onClick={()=>download('report',`evidence_${data.run_id}.html`)}>근거 보기</Button>
        {!proteinOnly&&<Button variant="outline" onClick={()=>download('primary_input','primary_A_input.csv')}>Download primary A</Button>}
        {data.schema_version==='astra_analysis_package.v5.experimental'&&<><Button variant="outline" onClick={()=>download('kinase_calls','kinase_calls.csv')}>판단·보류 근거</Button><Button variant="outline" onClick={()=>download('protein_input','protein_contrasts.csv')}>단백질 비교</Button><Button variant="outline" onClick={()=>download('measurement_audit','measurement_observations.csv')}>측정 audit</Button></>}
      </div>
      {['astra_analysis_package.v4','astra_analysis_package.v5.experimental'].includes(data.schema_version??'')&&<>
        <Button variant="outline" onClick={()=>download('start_here','START_HERE_ASTRA.md')}>Astra 전달 지침</Button>
        <details><summary className="cursor-pointer">전달되는 실험 정보 · 누락 {data.study_preview?.transfer_validation.unexpected_missing??'unknown'}개</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap text-sm">{data.study_preview?.brief}</pre></details>
        <details><summary className="cursor-pointer">근거와 제한 사항</summary><pre className="whitespace-pre-wrap text-xs">{JSON.stringify(data.analysis_readiness,null,2)}</pre></details>
      </>}
      {['astra_analysis_package.v4','astra_analysis_package.v5.experimental'].includes(data.schema_version??'')&&!proteinOnly&&<label className="block text-sm">Footprint evidence<select aria-label="Footprint evidence" className="ml-3 rounded border bg-background p-2" value={track} onChange={e=>setTrack(e.target.value)}><option value="curated_A">Curated substrate A</option><option value="motif_A">Motif candidate A (exploratory)</option>{data.schema_version==='astra_analysis_package.v5.experimental'&&<option value="specificity_A">Experimental specificity A (unvalidated)</option>}</select></label>}
      {!proteinOnly&&<><label className="block text-sm">Candidate kinase / family<select aria-label="Candidate kinase / family" value={entity} onChange={e=>setEntity(e.target.value)} className="ml-3 rounded border bg-background p-2">
        {[...new Set(profiles.map(p=>p.entity))].sort().map(e=><option key={e}>{e}</option>)}
      </select></label>
      <div className="overflow-auto"><table className="w-full text-sm"><thead><tr className="text-left"><th>Target / reference · observed time when available</th><th>Footprint</th><th>Sites / genes</th><th>Descriptive pattern</th></tr></thead>
        <tbody>{profiles.filter(p=>p.entity===entity).map(p=><tr key={p.contrast_id??p.time_min} className="border-t"><td className="py-2">{p.target_label?`${p.target_label} / ${p.reference_label} ${p.time_min==null?'':`(${p.time_min} min)`}`:p.time_min}</td><td>{p.gene_balanced_mean?.toFixed(4) ?? 'Unavailable'}</td><td>{p.n_sites_or_units} / {p.n_substrate_genes}</td><td>{p.descriptive_pattern}</td></tr>)}</tbody></table></div></>}
      <p className="text-xs text-muted-foreground">Consult the recorded annotation/source sensitivities. Alternative parent default: {data.provenance.estimator_versions.strict_parent_default}. Displayed provenance belongs to this completed run, even if order settings were subsequently edited.</p>
    </>}
  </section>;
}
