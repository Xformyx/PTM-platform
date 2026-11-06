import {useEffect, useId, useState} from 'react';
import {Button} from '@/components/ui/button';
import {CONTROL_COMPARISON as labels, type AnalysisContext, type ControlPolicy, type ControlResolution, type ControlStrategy, type ControlTime} from '@/lib/analysisContext';

type Condition={condition_id:string;label:string;arm_id:string;role:string;time:ControlTime;control_family?:string};
type Design={conditions:Condition[];arms?:Array<{arm_id:string;name:string}>;contrasts:Array<{target_condition_id:string;reference_condition_id:string}>;control_comparison?:ControlResolution};
const timeText=(time:ControlTime)=>time?`${time.value} ${time.unit}`:'시간 미기록';

/** This view consumes the server assignment; it never matches controls itself. */
export function ControlComparisonPreview({resolution}:{resolution?:ControlResolution}){
  if(!resolution)return <p role="status">Control 비교 정보를 해석하고 있습니다…</p>;
  const policy=resolution.effective_policy;
  return <section aria-label="생성될 비교" className="space-y-2">
    <p>Control 비교 방식: {policy.strategy?labels[policy.strategy].label:'미지정'}</p>
    {policy.source==='automatic_selection'&&<p className="text-xs">자동 판정된 제안입니다. 아래 실제 비교를 확인하거나 원본 정보에서 변경할 수 있습니다.</p>}
    <p className="font-medium">생성될 비교</p>
    <div className="overflow-auto"><table className="w-full text-left text-xs"><thead><tr><th>처리 조건</th><th>처리 시간</th><th>Control 조건</th><th>Control 시간</th><th>연결 상태</th></tr></thead>
      <tbody>{resolution.assignments.map(point=><tr key={point.contrast_id??point.target_condition_id}>
        <td>{point.target_label}</td><td>{timeText(point.target_time)}</td><td>{point.reference_label??'미지정'}</td><td>{timeText(point.reference_time)}</td>
        <td>{point.status==='resolved'?'연결됨':point.issues.map(i=>i.message).join(' ')||'미해결'}</td>
      </tr>)}</tbody></table></div>
    {policy.strategy==='time_matched'&&resolution.readiness.matched_temporal==='not_yet_supported'&&<p role="status">비교 연결과 비교별 정량을 지원합니다. 시간대별 Control 효과의 통합 시계열은 아직 지원하지 않습니다.</p>}
  </section>;
}

export default function ControlComparisonFields({context,onChange,publishedContext}:{context:AnalysisContext;onChange:(value:AnalysisContext)=>void;publishedContext?:AnalysisContext}){
  const uid=useId();const design=context.study_design as Design|undefined;
  const resolution=design?.control_comparison;
  const requested=context.control_comparison as ControlPolicy|undefined;
  const policy=requested??resolution?.effective_policy;
  const strategy=policy?.strategy;
  const ready=JSON.stringify(requested??null)===JSON.stringify(resolution?.requested_policy??null);
  const references=(design?.conditions??[]).filter(c=>c.role==='reference');
  const targets=(design?.conditions??[]).filter(c=>c.role!=='reference');
  const [custom,setCustom]=useState<Record<string,string>>({});const [dirty,setDirty]=useState(false);
  const mapping=JSON.stringify(Object.fromEntries((design?.contrasts??[]).map(c=>[c.target_condition_id,c.reference_condition_id])));
  useEffect(()=>{if(!dirty)setCustom(JSON.parse(mapping));},[mapping,dirty]);
  const setPolicy=(next:ControlPolicy)=>{setDirty(false);onChange({...context,control_comparison:{schema_version:'control_comparison.v1',source:'user_input',...next}});};
  const choose=(next:ControlStrategy)=>setPolicy({strategy:next,...(policy?.arm_control_families?{arm_control_families:policy.arm_control_families}:{}),
    ...(next==='shared_reference'&&strategy==='shared_reference'&&policy?.reference_condition_id?{reference_condition_id:policy.reference_condition_id}:{})});
  const errors=ready?resolution?.assignments.flatMap(p=>p.issues)??[]:[];
  const families=[...new Set(references.map(c=>c.control_family||c.arm_id))];
  const arms=[...new Set(targets.map(c=>c.arm_id))];
  const original=(publishedContext?.study_design as Design|undefined)?.contrasts;
  const signature=(rows:Design['contrasts'])=>JSON.stringify(rows.map(c=>[c.target_condition_id,c.reference_condition_id]).sort());
  const changed=original&&ready&&design&&signature(original)!==signature(design.contrasts);
  const common=references.find(c=>c.condition_id===(policy?.reference_condition_id??resolution?.effective_policy.reference_condition_id));
  return <section className="space-y-3" aria-label="Biological Design 설정">
    <fieldset aria-describedby={`${uid}-note ${uid}-errors`} className="space-y-2">
      <legend className="font-medium">{labels.label}</legend>
      <p className="text-xs text-muted-foreground">{labels.english_label}</p>
      {(['shared_reference','time_matched'] as const).map(value=><div key={value}>
        <label className="flex items-center gap-2"><input type="radio" name={`${uid}-strategy`} value={value} checked={strategy===value}
          aria-describedby={`${uid}-${value}-description ${uid}-errors`} onChange={()=>choose(value)}/>{labels[value].label} <span className="text-xs">({labels[value].english_label})</span></label>
        <p id={`${uid}-${value}-description`} className="text-xs">{labels[value].description}</p>
      </div>)}
      <p id={`${uid}-note`} className="text-xs">{labels.sample_note}</p>
      {strategy==='explicit_custom'&&<p>현재 방식: {labels.explicit_custom.label}</p>}
      {strategy==='shared_reference'&&<div>
        {references.length>1&&<label className="block text-sm">공통 Control<select aria-label="공통 Control" value={policy?.reference_condition_id??resolution?.effective_policy.reference_condition_id??''} className="block w-full rounded border bg-background p-2"
          onChange={e=>setPolicy({strategy:'shared_reference',reference_condition_id:e.target.value})}><option value="">지정하세요</option>{references.map(c=><option key={c.condition_id} value={c.condition_id}>{c.label} · {timeText(c.time)}</option>)}</select></label>}
        <p>공통 Control: {common?`${common.label} · ${timeText(common.time)}`:'미지정'}</p>
        {common&&<p className="text-xs">{common.time?.minutes===0?'시작 시점 대비 변화':'지정 Control 대비 변화'}</p>}
      </div>}
      {strategy==='time_matched'&&families.length>1&&arms.map(arm=><label key={arm} className="block text-sm">{design?.arms?.find(a=>a.arm_id===arm)?.name??arm}의 대응 Control family
        <select aria-label={`Control family ${arm}`} className="block w-full rounded border bg-background p-2" value={policy?.arm_control_families?.[arm]??targets.find(c=>c.arm_id===arm)?.control_family??''}
          onChange={e=>setPolicy({...policy,strategy:'time_matched',arm_control_families:{...policy?.arm_control_families,[arm]:e.target.value}})}><option value="">지정하세요</option>{families.map(f=><option key={f} value={f}>{references.filter(c=>(c.control_family||c.arm_id)===f).map(c=>c.label).join(', ')}</option>)}</select>
      </label>)}
      <div id={`${uid}-errors`} aria-live="polite">{errors.map((error,i)=><p role="alert" className="text-sm" key={i}>{error.message}</p>)}</div>
    </fieldset>
    <details><summary className="cursor-pointer">{labels.explicit_custom.label}</summary>
      <p className="text-xs">{labels.explicit_custom.description}</p>
      {targets.map(c=><label key={c.condition_id} className="block text-sm">{c.label} · {timeText(c.time)}
        <select aria-label={`직접 연결 ${c.condition_id}`} className="block w-full rounded border bg-background p-2" value={custom[c.condition_id]??''}
          onChange={e=>{setDirty(true);setCustom({...custom,[c.condition_id]:e.target.value});}}><option value="">지정하세요</option>{references.map(r=><option key={r.condition_id} value={r.condition_id}>{r.label} · {timeText(r.time)}</option>)}</select>
      </label>)}
      <Button type="button" variant="outline" onClick={()=>setPolicy({strategy:'explicit_custom',mappings:Object.fromEntries(Object.entries(custom).filter(([target,ref])=>Boolean(ref)&&targets.some(c=>c.condition_id===target)))})}>직접 연결 적용</Button>
    </details>
    {changed&&<p role="status">{labels.changed_result_note}</p>}
  </section>;
}
