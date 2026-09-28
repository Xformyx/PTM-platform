import { useEffect, useState } from 'react';
import { getAuthHeader } from '@/lib/api';
import { Button } from '@/components/ui/button';
import type { AnalysisContext } from '@/lib/analysisContext';

type Snapshot={sha256:string|null;status:string;database?:string;source?:string;version?:string;retrieved_utc?:string;taxonomy_ids?:string[];ptm_types?:string[];orthology_translation?:boolean;reasons?:string[]};
export default function FrozenAnnotationFields({context,onChange,species,ptmType}:{context:AnalysisContext;onChange:(v:AnalysisContext)=>void;species:string;ptmType:string}) {
  const [state,setState]=useState('loading');const [snapshots,setSnapshots]=useState<Snapshot[]>([]);const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    const abort=new AbortController();setState('loading');
    const tax=({human:'9606',mouse:'10090',rat:'10116',rat_hir:'10116'} as Record<string,string>)[species];
    fetch(`/api/orders/frozen-annotations?${new URLSearchParams({...tax?{taxonomy_id:tax}:{},ptm_type:ptmType})}`,{headers:getAuthHeader(),signal:abort.signal})
      .then(async response=>{
        if(response.status===401 || response.status===403){setState('unauthorized');return;}
        if(!response.ok){setState('server_error');return;}
        const data=await response.json();
        if(!Array.isArray(data.snapshots)){setState('metadata_invalid');return;}
        setSnapshots(data.snapshots);setState(data.status);
      }).catch(error=>{if(error.name!=='AbortError')setState('network_error');});
    return()=>abort.abort();
  },[species,ptmType,attempt]);
  const messages:Record<string,string>={loading:'Loading annotation registry…',empty_registry:'No annotation is registered. An administrator can register a checked snapshot; generic quantification-only analysis is available.',
    no_compatible_snapshot:'No compatible annotation is available for this organism/PTM. Review metadata or ask an administrator to register a compatible snapshot.',
    unauthorized:'Annotation lookup requires an authorized session. Sign in again or contact an administrator.',
    server_error:'Annotation service could not read the registry. Retry or contact an administrator.',network_error:'Annotation lookup failed because the server could not be reached. Retry the request.',metadata_invalid:'Registry metadata could not be validated. Contact an administrator.'};
  return <div className="space-y-2">
    <label className="block text-sm">Frozen annotation snapshot<select aria-label="Frozen annotation snapshot" className="mt-1 block w-full rounded border bg-background p-2"
      value={String(context.annotation_snapshot_sha256??'')} onChange={e=>onChange({...context,annotation_snapshot_sha256:e.target.value})}>
      <option value="">Select a compatible registered snapshot</option>
      {snapshots.filter(s=>s.sha256).map(s=><option key={s.sha256} value={s.sha256!} disabled={s.status!=='ready'}>
        {s.database??'Annotation'} · {s.version??s.retrieved_utc??'version unknown'} · {s.sha256!.slice(0,12)} · {s.status}
      </option>)}
    </select></label>
    {messages[state]&&<p role={state==='loading'?'status':'alert'} className="text-xs">{messages[state]}</p>}
    {snapshots.filter(s=>s.status!=='ready').map((s,i)=><p key={s.sha256??i} className="text-xs">{s.sha256?.slice(0,12)??'Registration'}: {s.status} · {s.reasons?.join(', ')}</p>)}
    {Boolean(context.annotation_snapshot_sha256) && state!=='loading' && !snapshots.some(s=>s.sha256===context.annotation_snapshot_sha256)&&<p role="alert" className="text-xs">The order's pinned snapshot is not present in this registry. It has not been replaced automatically.</p>}
    {snapshots.filter(s=>s.sha256===context.annotation_snapshot_sha256).map(s=><p key={s.sha256} className="text-xs">Source: {s.source??s.database??'unknown'} · Taxonomy: {s.taxonomy_ids?.join(', ')??'unknown'} · PTM: {s.ptm_types?.join(', ')??'unknown'} · Orthology translation: {s.orthology_translation==null?'unknown':String(s.orthology_translation)} · Retrieved: {s.retrieved_utc??'unknown'}</p>)}
    {['network_error','server_error','metadata_invalid','unauthorized','no_compatible_snapshot','empty_registry'].includes(state)&&<Button type="button" variant="outline" size="sm" onClick={()=>setAttempt(v=>v+1)}>Retry registry lookup</Button>}
  </div>;
}
