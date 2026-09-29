import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { AnalysisContext, DesignSample } from '@/lib/analysisContext';

type Condition={condition_id:string;arm_id:string;label:string;role:string;time:{value:number;unit:string;minutes:number;original:string}|null;reference_condition_id?:string;time_conflict_resolution?:string};
type Material={material_id:string;biological_unit_id:string|null;pair_id:string|null;source?:string};
type Injection={injection_id:string;input_column:string;condition_id:string;material_id:string|null;technical_injection_id:string|null};
type Treatment={name:string;dose:number|null;unit:string|null;dose_status:string;source?:string};
type Arm={arm_id:string;name:string;treatments:Treatment[]};
type Contrast={contrast_id:string;target_condition_id:string;reference_condition_id:string;pairing:string;purpose?:string};
type Design={schema_version:string;status:string;replication_declaration:string;conditions:Condition[];arms:Arm[];materials:Material[];injections:Injection[];contrasts:Contrast[];issues:Array<{code:string;path:string;message:string;severity:string}>;[key:string]:unknown};

export default function CanonicalStudyFields({context,onChange,samples,species,ptmType}:{context:AnalysisContext;onChange:(v:AnalysisContext)=>void;samples:DesignSample[];species:string;ptmType:string}) {
  const astra=context.quantitation_export_mode==='astra_analysis.v4';
  const [plan,setPlan]=useState<Record<string,unknown>|null>(null);
  const [error,setError]=useState('');const [pending,setPending]=useState(false);const [revision,setRevision]=useState(0);
  const current=useRef({context,onChange});current.current={context,onChange};
  const input=JSON.stringify({analysis_context:context,sample_config:samples,species,ptm_type:ptmType});
  useEffect(()=>{
    let active=true;
    const timer=setTimeout(()=>{setPending(true);api.post<{study_design:Design;analysis_plan?:Record<string,unknown>}>('/orders/resolve-design',JSON.parse(input))
      .then(response=>{if(!active)return;setError('');setPlan(response.analysis_plan??null);const state=current.current;
        if(JSON.stringify(state.context.study_design)!==JSON.stringify(response.study_design))state.onChange({...state.context,study_design:response.study_design});})
      .catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setPending(false);});},350);
    return()=>{active=false;clearTimeout(timer);};
  },[input,revision]);
  const design=context.study_design as Design|undefined;
  const put=(key:string,value:unknown)=>onChange({...context,[key]:value});
  const change=(patch:Partial<Design>)=>put('study_design',{...design,...patch});
  const selectClass='block w-full rounded border bg-background p-2 text-sm';
  const condition=(id:string)=>design?.conditions.find(c=>c.condition_id===id)?.label??id;
  const importedStudy=(design?.study??{}) as Record<string,unknown>;
  const metadataSection=(section:string)=>(context[section]??importedStudy[section]??{}) as Record<string,unknown>;
  const setMetadata=(section:string,key:string,value:unknown)=>put(section,{...metadataSection(section),[key]:value});
  return <div className="space-y-4">
    <p className="text-sm font-medium">Review imported study design</p>
    <p className="text-xs text-muted-foreground">Files and conditions come from the configured samples. Rep numbers alone do not establish biological or technical replication. Drafts can be saved; only unresolved execution requirements block Start.</p>
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={context.enrichment_status==='enrichment_free'} onChange={e=>put('enrichment_status',e.target.checked?'enrichment_free':'unknown')}/>These PR/PG inputs were acquired without PTM enrichment</label>
    {astra?<div className="rounded border bg-muted/30 p-3 text-sm" aria-label="Automatic analysis plan">
      <p>정량: 공급 intensity · 동일 주입 parent 보정 · 대체 parent/정규화 민감도</p>
      <p>탐색: {ptmType==='phosphorylation'?'kinase DB + 관측 잔기 중심 motif + 기질 footprint':'지원 PTM 정량·등장·단백질 통합; kinase 해당 없음'}</p>
      <p>통합: PTM/kinase 시간 패턴 + 전체 단백질 변화 + 등장 PTM</p>
      <p>참조 자료는 자동 준비 후 이번 실행에 고정됩니다. 일부 DB 실패는 제한 사항과 함께 전달됩니다.</p>
      <details><summary>참조 자료 갱신</summary><label className="flex gap-2"><input type="checkbox" checked={context.refresh_references===true} onChange={e=>put('refresh_references',e.target.checked)}/>다음 새 실행에서 참조 자료 갱신 요청 (완료된 패키지는 보존)</label></details>
      {plan&&<details><summary>Recorded plan details</summary><pre className="whitespace-pre-wrap text-xs">{JSON.stringify(plan,null,2)}</pre></details>}
    </div>:<p className="text-xs">Recorded legacy estimator and annotation settings are preserved. Use a new Astra package run to adopt the automatic plan.</p>}
    {!context.sample_manifest&&(!design?.materials.length||design.replication_declaration==='unknown')&&<label className="block text-sm">Confirm replication once<select aria-label="Replication declaration" className={selectClass} value={String(context.replication_declaration??design?.replication_declaration??'unknown')}
      onChange={e=>put('replication_declaration',e.target.value)}>
      <option value="unknown">Unconfirmed — descriptive observations; no biological inference</option><option value="technical_per_condition">One material per condition, with repeated technical injections</option>
      <option value="independent_biological_units">Each injection measures a different biological unit</option><option value="mixed">Mixed design — edit material/unit/pair mapping below</option>
    </select></label>}
    {pending&&<p role="status" className="text-xs">Resolving imported design…</p>}
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {design&&<>
      <p className="text-xs">{design.injections.length} injections · {design.materials.length} declared materials · {design.conditions.length} conditions · {design.contrasts.length} contrasts · {design.status}</p>
      <div className="overflow-auto"><table className="w-full text-xs"><thead><tr><th>Condition</th><th>Arm</th><th>Time</th><th>Unit</th><th>Role</th></tr></thead><tbody>
        {design.conditions.map(c=><tr key={c.condition_id}><td>{c.label}</td><td><select aria-label={`Arm ${c.label}`} className={selectClass} value={c.arm_id} onChange={e=>change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,arm_id:e.target.value}:v)})}>
          {design.arms.map(a=><option key={a.arm_id} value={a.arm_id}>{a.name}</option>)}</select></td>
          <td><Input aria-label={`Time ${c.label}`} type="number" step="any" value={c.time?.value??''} onChange={e=>change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,time:e.target.value===''?null:{...(v.time??{unit:'min',minutes:0,original:''}),value:Number(e.target.value)}}:v)})}/></td>
          <td><select aria-label={`Time unit ${c.label}`} className={selectClass} value={c.time?.unit??'min'} onChange={e=>change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,time:{value:v.time?.value??0,minutes:v.time?.minutes??0,original:v.time?.original??'',unit:e.target.value}}:v)})}>
            {[...new Set(['s','min','h','d',c.time?.unit??'min'])].map(u=><option key={u}>{u}</option>)}</select></td>
          <td><select aria-label={`Role ${c.label}`} className={selectClass} value={c.role} onChange={e=>change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,role:e.target.value}:v),contrasts:[]})}>
            <option value="target">Target</option><option value="reference">Reference</option><option value="unknown">Unconfirmed</option></select></td></tr>)}
      </tbody></table></div>
      <div className="space-y-2">{design.conditions.filter(c=>c.role!=='reference').map(c=>{
        const contrast=design.contrasts.find(v=>v.target_condition_id===c.condition_id);
        return <div key={c.condition_id} className="grid grid-cols-3 items-center gap-2 text-xs"><span>{c.label} compared with</span>
          <select aria-label={`Reference ${c.label}`} className={selectClass} value={contrast?.reference_condition_id??c.reference_condition_id??''} onChange={e=>{
            const ref=e.target.value;const updated={contrast_id:contrast?.contrast_id??`contrast_${c.condition_id}_${ref}`,target_condition_id:c.condition_id,reference_condition_id:ref,pairing:contrast?.pairing??'unknown'};
            change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,reference_condition_id:ref}:v),contrasts:[...design.contrasts.filter(v=>v.target_condition_id!==c.condition_id),updated]});}}>
            <option value="">Confirm reference</option>{design.conditions.filter(v=>v.condition_id!==c.condition_id).map(v=><option key={v.condition_id} value={v.condition_id}>{v.label}</option>)}</select>
          <select aria-label={`Pairing ${c.label}`} className={selectClass} value={contrast?.pairing??'unknown'} onChange={e=>change({contrasts:design.contrasts.map(v=>v.target_condition_id===c.condition_id?{...v,pairing:e.target.value}:v)})}>
            <option value="unknown">Pairing unconfirmed</option><option value="unpaired">Unpaired units</option><option value="paired">Declared paired units</option></select></div>;
      })}</div>
      {design.issues.map((i,index)=><div key={index} className="text-xs" role={i.severity==='error'?'alert':'status'}><span>{i.code} · {i.path}: {i.message}</span>
        {i.code==='treatment_context_conflict'&&<Button type="button" size="sm" variant="outline" onClick={()=>put('treatment_conflict_resolution','reviewed_structured_arms')}>Confirm reviewed treatment and dose assignments</Button>}
        {['time_conflict','time_points_conflict'].includes(i.code)&&<Button type="button" size="sm" variant="outline" onClick={()=>change({conditions:design.conditions.map(c=>i.path===`conditions.${c.condition_id}.time`?{...c,time_conflict_resolution:'use_confirmed_structured'}:c)})}>Confirm structured time for this condition</Button>}</div>)}
      <details open={context.replication_declaration==='mixed'}><summary className="cursor-pointer text-sm">Material, biological unit and pairing mapping</summary>
        <p className="text-xs">Different well/lysate samples need different material IDs. A donor/unit or pair ID can connect materials; technical injection numbers do not establish pairs.</p>
        <div className="max-h-80 overflow-auto"><table className="w-full text-xs"><thead><tr><th>Injection / condition</th><th>Material ID</th><th>Biological unit</th><th>Pair ID</th></tr></thead><tbody>{design.injections.map(s=>{
          const m=design.materials.find(v=>v.material_id===s.material_id);
          const setMaterial=(patch:Partial<Material>)=>{const id=s.material_id??`material_${s.injection_id}`;change({injections:design.injections.map(v=>v.injection_id===s.injection_id?{...v,material_id:id}:v),materials:[...design.materials.filter(v=>v.material_id!==id),{material_id:id,biological_unit_id:null,pair_id:null,...m,...patch,source:'user_confirmed_mapping'}]});};
          return <tr key={s.injection_id}><td className="max-w-48 break-all">{s.input_column.split(/[\\/]/).pop()} · {condition(s.condition_id)}</td><td><Input aria-label={`Material ${s.input_column}`} value={s.material_id??''} onChange={e=>{
            const id=e.target.value;change({injections:design.injections.map(v=>v.injection_id===s.injection_id?{...v,material_id:id||null}:v),materials:design.materials.some(v=>v.material_id===id)?design.materials:[...design.materials,{material_id:id,biological_unit_id:null,pair_id:null,source:'user_confirmed_mapping'}].filter(v=>v.material_id)});}}/></td>
            <td><Input aria-label={`Biological unit ${s.input_column}`} value={m?.biological_unit_id??''} onChange={e=>setMaterial({biological_unit_id:e.target.value||null})}/></td>
            <td><Input aria-label={`Pair ${s.input_column}`} value={m?.pair_id??''} onChange={e=>setMaterial({pair_id:e.target.value||null})}/></td></tr>;
        })}</tbody></table></div>
      </details>
      <details><summary className="cursor-pointer text-sm">Treatments and doses</summary>{design.arms.map(a=><div key={a.arm_id} className="my-2 space-y-1"><p className="text-xs">Arm: {a.name}</p>
        {a.treatments.map((t,index)=><div key={index} className="grid grid-cols-4 gap-2">{['name','dose','unit','dose_status'].map(key=>{
          const update=(value:unknown)=>change({arms:design.arms.map(v=>v.arm_id===a.arm_id?{...v,treatments:v.treatments.map((x,j)=>j===index?{...x,[key]:value,source:'user_confirmed'}:x)}:v)});
          return key==='dose_status'?<select key={key} aria-label={`Dose status ${a.name} ${index}`} className={selectClass} value={t.dose_status} onChange={e=>update(e.target.value)}>{['unknown','provided','not_applicable','none'].map(v=><option key={v}>{v}</option>)}</select>:
            <Input key={key} aria-label={`${key} ${a.name} ${index}`} placeholder={key} type={key==='dose'?'number':'text'} step="any" value={t[key as keyof Treatment]??''} onChange={e=>update(key==='dose'?(e.target.value===''?null:Number(e.target.value)):e.target.value||null)}/>;
        })}</div>)}
        <Button type="button" size="sm" variant="outline" onClick={()=>change({arms:design.arms.map(v=>v.arm_id===a.arm_id?{...v,treatments:[...v.treatments,{name:'',dose:null,unit:null,dose_status:'unknown'}]}:v)})}>Add treatment or nonchemical condition</Button>
      </div>)}</details>
    </>}
    <details><summary className="cursor-pointer text-sm">Optional acquisition and processing information</summary>
      <p className="text-xs">Leave unknown values unknown. Volume and peptide mass are separate quantities and are never converted into each other.</p>
      {(['acquisition','processing'] as const).map(section=><div key={section} className="my-2 grid grid-cols-2 gap-2">{(section==='acquisition'?['instrument','mode','injection_volume','injected_peptide_mass','description']:['software_version','settings','upstream_normalization']).map(key=>{
        const row=(metadataSection(section)[key]??{}) as {value?:string;unit?:string;status?:string};
        return <label key={key} className="text-xs">{key.replace(/_/g,' ')}<div className="flex gap-1"><Input aria-label={key} value={row.value??''} onChange={e=>setMetadata(section,key,{...row,value:e.target.value||null,status:e.target.value?'provided':'unknown',source:'user_input'})}/>
          {['injection_volume','injected_peptide_mass'].includes(key)&&<Input aria-label={`${key} unit`} placeholder="unit" value={row.unit??''} onChange={e=>setMetadata(section,key,{...row,unit:e.target.value||null,source:'user_input'})}/>}</div>
          <select aria-label={`${key} status`} className={selectClass} value={row.status??'unknown'} onChange={e=>setMetadata(section,key,{...row,status:e.target.value,source:'user_input'})}>{['unknown','provided','not_applicable','none'].map(v=><option key={v}>{v}</option>)}</select></label>;
      })}</div>)}
      <label className="text-xs">Pre-treatment / starvation (value and unit)<Input aria-label="Pre-treatment" value={typeof context.pre_treatment==='string'?context.pre_treatment:''} onChange={e=>put('pre_treatment',e.target.value||null)}/></label>
    </details>
    <details><summary className="cursor-pointer text-sm">Optional validation panel and temporal windows</summary><p className="text-xs">Panel genes are not excluded from primary discovery. Selection timing is preserved. Windows use minutes and do not imply causal timing.</p>
      <label className="text-xs">Panel genes (comma separated)<Input aria-label="Validation panel genes" value={((context.validation_panel as {genes?:string[]})?.genes??[]).join(', ')} onChange={e=>put('validation_panel',{...(context.validation_panel as object??{}),genes:e.target.value.split(',').map(v=>v.trim()).filter(Boolean),selection_timing:(context.validation_panel as {selection_timing?:string})?.selection_timing??'retrospective_exploratory'})}/></label>
      <label className="text-xs">Selection timing<Input aria-label="Panel selection timing" value={(context.validation_panel as {selection_timing?:string})?.selection_timing??''} onChange={e=>put('validation_panel',{...(context.validation_panel as object??{}),selection_timing:e.target.value||'unknown'})}/></label>
      <label className="text-xs">Temporal windows JSON<textarea aria-label="Temporal windows JSON" className="block w-full rounded border bg-background p-2" defaultValue={JSON.stringify(context.temporal_windows??{},null,2)} onBlur={e=>{try{put('temporal_windows',JSON.parse(e.target.value));setError('');}catch{setError('Temporal windows must be JSON, e.g. {"early":{"maximum_minutes":30}}.');}}}/></label>
    </details>
    <Button type="button" variant="outline" size="sm" onClick={()=>setRevision(v=>v+1)}>Recheck imported design</Button>
  </div>;
}
