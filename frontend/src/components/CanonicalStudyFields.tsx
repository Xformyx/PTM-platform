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

export default function CanonicalStudyFields({context,onChange,samples,species,ptmType,sourceEditor=false,onEdit}:{context:AnalysisContext;onChange:(v:AnalysisContext)=>void;samples:DesignSample[];species:string;ptmType:string;sourceEditor?:boolean;onEdit?:()=>void}) {
  const astra=['astra_analysis.v4','astra_analysis.v5','astra_analysis.v6'].includes(String(context.quantitation_export_mode));
  const [plan,setPlan]=useState<Record<string,unknown>|null>(null);
  const [error,setError]=useState('');const [pending,setPending]=useState(false);const [revision,setRevision]=useState(0);
  const current=useRef({context,onChange});current.current={context,onChange};
  const accepted=useRef('');
  const [resolvedInput,setResolvedInput]=useState('');
  const input=JSON.stringify({analysis_context:context,sample_config:samples,species,ptm_type:ptmType});
  useEffect(()=>{
    if(sourceEditor||accepted.current===input)return;
    let active=true;
    setPending(true);setPlan(null);setError('');
    const timer=setTimeout(()=>{api.post<{study_design:Design;analysis_context?:AnalysisContext;analysis_plan?:Record<string,unknown>}>('/orders/resolve-design',JSON.parse(input))
      .then(response=>{if(!active)return;setError('');setPlan(response.analysis_plan??null);const state=current.current;
        const next=response.analysis_context??{...state.context,study_design:response.study_design};
        accepted.current=JSON.stringify({...JSON.parse(input),analysis_context:next});setResolvedInput(accepted.current);
        if(JSON.stringify(state.context)!==JSON.stringify(next))state.onChange(next);})
      .catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setPending(false);});},350);
    return()=>{active=false;clearTimeout(timer);};
  },[input,revision,sourceEditor]);
  const design=context.study_design as Design|undefined;
  const put=(key:string,value:unknown)=>onChange({...context,[key]:value});
  const refreshReferences=(checked:boolean)=>onChange({...context,refresh_references:checked,
    ...(checked?{acquisition_policy:{...((context.acquisition_policy??{}) as Record<string,unknown>),mode:'research_full'}}:{})});
  const change=(patch:Partial<Design>)=>{
    const provenance={...((design?.field_provenance??{}) as Record<string,Record<string,unknown>>)};
    for(const [collection,rows] of Object.entries(patch))if(Array.isArray(rows))for(const row of rows){
      const id=row[({conditions:'condition_id',materials:'material_id',injections:'injection_id',contrasts:'contrast_id',arms:'arm_id'} as Record<string,string>)[collection]];
      const old=(design?.[collection] as Record<string,unknown>[]|undefined)?.find(v=>v[`${collection.slice(0,-1)}_id`]===id);
      if(JSON.stringify(old)!==JSON.stringify(row)){
        provenance[`${collection}.${id}`]={source:'user_input',confirmation_status:'user_confirmed'};
        if(collection==='conditions'&&JSON.stringify(old?.time)!==JSON.stringify(row.time))provenance[`conditions.${id}.time`]={source:'user_input',confirmation_status:'user_confirmed'};
      }
    }
    put('study_design',{...design,...patch,field_provenance:provenance});
  };
  const selectClass='block w-full rounded border bg-background p-2 text-sm';
  const condition=(id:string)=>design?.conditions.find(c=>c.condition_id===id)?.label??id;
  const importedStudy=(design?.study??{}) as Record<string,unknown>;
  const metadataSection=(section:string)=>(context[section]??importedStudy[section]??{}) as Record<string,unknown>;
  const setMetadata=(section:string,key:string,value:unknown)=>put(section,{...metadataSection(section),[key]:value});
  if(astra&&!sourceEditor){
    const waiting=pending||resolvedInput!==input;
    const ordered=[...(design?.conditions??[])].sort((a,b)=>(a.time?.minutes??Infinity)-(b.time?.minutes??Infinity));
    return <div className="space-y-3" aria-label="입력 정보 요약">
      <p className="font-medium">입력 정보 자동 반영</p>
      <Button type="button" size="sm" variant="outline" onClick={onEdit}>입력 정보 수정</Button>
      {waiting&&!error?<p role="status">최신 입력 정보를 반영하고 있습니다…</p>:error?<p role="alert">{error}</p>:design&&<>
        <p>종: {species} · 분석 대상: {ptmType}</p>
        <p>기준 조건: {ordered.filter(c=>c.role==='reference').map(c=>c.label).join(', ')||'미기록'}</p>
        <p>처리 조건: {ordered.filter(c=>c.role!=='reference').map(c=>`${c.label}${c.time?` (${c.time.value} ${c.time.unit})`:''}`).join(', ')}</p>
        <p>비교: {design.contrasts.map(c=>`${condition(c.target_condition_id)} vs ${condition(c.reference_condition_id)}`).join(' · ')}</p>
        <p>반복 정보: {design.materials.length?`${design.materials.length} material · ${new Set(design.materials.flatMap(m=>m.biological_unit_id?[m.biological_unit_id]:[])).size} biological unit`:'미기록 — descriptive 분석'} · {design.injections.length} injection</p>
        <p>Pairing: {[...new Set(design.contrasts.map(c=>c.pairing))].join(', ')||'unknown'}</p>
        <dl className="grid grid-cols-2 gap-1 text-sm">{[['cell_type','Cell Type'],['treatment','Treatment'],['time_points','Time Points'],['biological_question','Biological Question'],['special_conditions','Special Conditions'],['enrichment_status','Enrichment']].map(([key,label])=><div key={key}><dt className="text-muted-foreground">{label}</dt><dd>{String(context[key]??'unknown')||'unknown'}</dd></div>)}</dl>
        <p>DIA-NN version: {String((context.science as Record<string,unknown>|undefined)?.diann_version??'unknown')||'unknown'}</p>
        <p>등록 Reference: {String(((context.science as {reference?:{reference_id?:string}}|undefined)?.reference?.reference_id)||'업로드 FASTA 또는 등록된 종 reference')}</p>
        {design.issues.map((i,index)=><p key={index} role={i.severity==='error'?'alert':'status'} className="text-xs">{i.path}: {i.message}{i.severity==='error'?' — 입력 정보의 해당 항목을 수정하세요.':''}</p>)}
        <details><summary>기록된 매핑·용량·acquisition/processing</summary><pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify({arms:design.arms,materials:design.materials,injections:design.injections,acquisition:importedStudy.acquisition,processing:importedStudy.processing},null,2)}</pre></details>
        <p className="text-xs" aria-label="Reference acquisition policy">{String((plan?.source_execution as {message?:string}|undefined)?.message??'')}</p>
        <details><summary>참조 자료 갱신</summary><label className="flex gap-2 text-xs"><input type="checkbox" checked={context.refresh_references===true} onChange={e=>refreshReferences(e.target.checked)}/>다음 새 실행에서 참조 자료 갱신 요청</label></details>
      </>}
    </div>;
  }
  return <div className="space-y-4">
    <p className="text-sm font-medium">{sourceEditor?'원본 데이터의 추가 정보 (선택)':'Review imported study design'}</p>
    <p className="text-xs text-muted-foreground">Files and conditions come from the configured samples. Rep numbers alone do not establish biological or technical replication. Drafts can be saved; only unresolved execution requirements block Start.</p>
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={context.enrichment_status==='enrichment_free'} onChange={e=>put('enrichment_status',e.target.checked?'enrichment_free':'unknown')}/>These PR/PG inputs were acquired without PTM enrichment</label>
    {!astra&&<p className="text-xs">Recorded legacy estimator and annotation settings are preserved. Use a new Astra package run to adopt the automatic plan.</p>}
    {!context.sample_manifest&&(!design?.materials.length||design.replication_declaration==='unknown')&&<label className="block text-sm">{sourceEditor?'기록된 반복 유형 (선택)':'Confirm replication once'}<select aria-label="Replication declaration" className={selectClass} value={String(context.replication_declaration??design?.replication_declaration??'unknown')}
      onChange={e=>put('replication_declaration',e.target.value)}>
      <option value="unknown">Unconfirmed — descriptive observations; no biological inference</option><option value="technical_per_condition">One material per condition, with repeated technical injections</option>
      <option value="independent_biological_units">Each injection measures a different biological unit</option><option value="mixed">Mixed design — edit material/unit/pair mapping below</option>
    </select></label>}
    {pending&&<p role="status" className="text-xs">Resolving imported design…</p>}
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {design&&<>
      <p className="text-xs">{design.injections.length} injections · {design.materials.length} declared materials · {design.conditions.length} conditions · {design.contrasts.length} contrasts · {design.status}</p>
      {astra&&sourceEditor&&design.conditions.filter(c=>!design.injections.some(i=>i.condition_id===c.condition_id)).map(c=><div key={c.condition_id} className="text-xs">
        <p>{c.label}: 현재 파일에 연결되지 않은 기록입니다. 과거 출처가 불명확한 값은 자동 삭제하지 않습니다.</p>
        <Button type="button" size="sm" variant="outline" onClick={()=>change({conditions:design.conditions.filter(v=>v.condition_id!==c.condition_id),contrasts:design.contrasts.filter(v=>v.target_condition_id!==c.condition_id&&v.reference_condition_id!==c.condition_id)})}>{c.label} 기록 제거</Button>
      </div>)}
      <div className="overflow-auto"><table className="w-full text-xs"><thead><tr><th>Condition</th><th>Arm</th><th>Time</th><th>Unit</th><th>Role</th></tr></thead><tbody>
        {design.conditions.map(c=><tr key={c.condition_id}><td>{c.label}</td><td><select aria-label={`Arm ${c.label}`} className={selectClass} value={c.arm_id} onChange={e=>change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,arm_id:e.target.value}:v)})}>
          {design.arms.map(a=><option key={a.arm_id} value={a.arm_id}>{a.name}</option>)}</select></td>
          <td><Input disabled={context.design_axis==='cross_sectional'} aria-label={`Time ${c.label}`} type="number" step="any" value={c.time?.value??''} onChange={e=>change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,time:e.target.value===''?null:{...(v.time??{unit:'min',minutes:0,original:''}),value:Number(e.target.value)}}:v)})}/></td>
          <td><select disabled={context.design_axis==='cross_sectional'} aria-label={`Time unit ${c.label}`} className={selectClass} value={c.time?.unit??'min'} onChange={e=>change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,time:{value:v.time?.value??0,minutes:v.time?.minutes??0,original:v.time?.original??'',unit:e.target.value}}:v)})}>
            {[...new Set(['s','min','h','d',c.time?.unit??'min'])].map(u=><option key={u}>{u}</option>)}</select></td>
          <td><select aria-label={`Role ${c.label}`} className={selectClass} value={c.role} onChange={e=>change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,role:e.target.value}:v),contrasts:[]})}>
            <option value="target">Target</option><option value="reference">Reference</option><option value="unknown">Unconfirmed</option></select></td></tr>)}
      </tbody></table></div>
      {!astra&&<div className="space-y-2">{design.conditions.filter(c=>c.role!=='reference').map(c=>{
        const contrast=design.contrasts.find(v=>v.target_condition_id===c.condition_id);
        return <div key={c.condition_id} className="grid grid-cols-3 items-center gap-2 text-xs"><span>{c.label} compared with</span>
          <select aria-label={`Reference ${c.label}`} className={selectClass} value={contrast?.reference_condition_id??c.reference_condition_id??''} onChange={e=>{
            const ref=e.target.value;const updated={contrast_id:contrast?.contrast_id??`contrast_${c.condition_id}_${ref}`,target_condition_id:c.condition_id,reference_condition_id:ref,pairing:contrast?.pairing??'unknown'};
            change({conditions:design.conditions.map(v=>v.condition_id===c.condition_id?{...v,reference_condition_id:ref}:v),contrasts:[...design.contrasts.filter(v=>v.target_condition_id!==c.condition_id),updated]});}}>
            <option value="">Confirm reference</option>{design.conditions.filter(v=>v.condition_id!==c.condition_id).map(v=><option key={v.condition_id} value={v.condition_id}>{v.label}</option>)}</select>
          <select aria-label={`Pairing ${c.label}`} className={selectClass} value={contrast?.pairing??'unknown'} onChange={e=>change({contrasts:design.contrasts.map(v=>v.target_condition_id===c.condition_id?{...v,pairing:e.target.value}:v)})}>
            <option value="unknown">Pairing unconfirmed</option><option value="unpaired">Unpaired units</option><option value="paired">Declared paired units</option></select></div>;
      })}</div>}
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
      {(['acquisition','processing'] as const).map(section=><div key={section} className="my-2 grid grid-cols-2 gap-2">{(section==='acquisition'?['instrument','mode','injection_volume','injected_peptide_mass','description']:astra?['settings','upstream_normalization']:['software_version','settings','upstream_normalization']).map(key=>{
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
    {!sourceEditor&&<Button type="button" variant="outline" size="sm" onClick={()=>{accepted.current='';setRevision(v=>v+1);}}>Recheck imported design</Button>}
  </div>;
}
