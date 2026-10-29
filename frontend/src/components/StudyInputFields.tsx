import { useState } from 'react';
import { Input } from '@/components/ui/input';
import CanonicalStudyFields from './CanonicalStudyFields';
import type { AnalysisContext, DesignSample } from '@/lib/analysisContext';

/** The original data-information state, shared by create and rerun. */
export default function StudyInputFields({context,onChange,samples,species,ptmType,onSamplesChange}:{context:AnalysisContext;onChange:(value:AnalysisContext)=>void;samples:DesignSample[];species:string;ptmType:string;onSamplesChange?:(value:DesignSample[])=>void}) {
  const [error,setError]=useState('');
  const science=(context.science??{}) as Record<string,unknown>;
  const processing=(context.processing??{}) as Record<string,unknown>;
  const legacy=(context.acquisition_metadata??{}) as Record<string,unknown>;
  const put=(key:string,value:unknown)=>onChange({...context,[key]:value});
  const setVersion=(value:string)=>{
    const software=String(processing.software??processing.software_name??'').toLowerCase().replace('-','');
    onChange({...context,science:{...science,diann_version:value||null},
      ...(!software||software==='diann'?{processing:{...processing,software:'DIA-NN',software_version:{value:value||null,software:'DIA-NN',source:'user_input',status:value?'provided':'unknown'}}}:{}),
      ...('diann_version' in legacy?{acquisition_metadata:{...legacy,diann_version:value||null}}:{})});
  };
  return <div className="space-y-3" aria-label="원본 데이터 정보">
    {onSamplesChange&&<div className="overflow-auto"><p>Sample Config</p><table className="w-full text-xs"><thead><tr><th>File</th><th>Condition</th><th>Group</th><th>Rep.</th></tr></thead><tbody>{samples.map((row,index)=>{
      const update=(key:string,value:string)=>onSamplesChange(samples.map((v,i)=>i===index?{...v,[key]:value,...(key==='condition'?{source_condition:value}:{})}:v));
      return <tr key={row.sample_id}><td>{row.sample_id}</td><td><Input aria-label={`Condition ${row.sample_id}`} value={String(row.source_condition??row.condition)} onChange={e=>update('condition',e.target.value)}/></td><td><select aria-label={`Group ${row.sample_id}`} value={row.group??''} onChange={e=>update('group',e.target.value)}><option value="">미기록</option><option>Control</option><option>Treatment</option>{row.group&&!['Control','Treatment'].includes(row.group)&&<option>{row.group}</option>}</select></td><td><Input aria-label={`Rep ${row.sample_id}`} value={row.replicate??''} onChange={e=>update('replicate',e.target.value)}/></td></tr>;
    })}</tbody></table></div>}
    <label className="block text-sm">Design axis<select aria-label="Design axis" value={String(context.design_axis??'time_course')} onChange={e=>put('design_axis',e.target.value)}><option value="time_course">Time course</option><option value="cross_sectional">Condition contrasts without time</option></select></label>
    <label className="block text-sm">DIA-NN version (알려진 경우에만)<Input aria-label="DIA-NN version" value={String(science.diann_version??'')} onChange={e=>setVersion(e.target.value)}/></label>
    <label className="block text-sm">등록 Reference ID<Input aria-label="Registered reference ID" value={String((science.reference as Record<string,unknown>|undefined)?.reference_id??'')} onChange={e=>put('science',{...science,reference:{...((science.reference??{}) as Record<string,unknown>),reference_id:e.target.value}})}/></label>
    <details><summary className="cursor-pointer text-sm">추가 데이터 정보 / 해당 항목 수정 (선택)</summary>
      <p className="text-xs">이미 선언한 값만 기록하세요. 반복 유형과 biological mapping이 없으면 descriptive 분석을 유지합니다. 파일·조건·Control 분류는 Sample Config에서 수정합니다.</p>
      <label className="block text-sm">예정 반복 수 (조건별, 실제 Rep. 번호와 별도)<Input aria-label="예정 반복 수" type="number" min="1" step="1"
        value={String((context.replication_plan as {default_replicates_per_condition?:number}|undefined)?.default_replicates_per_condition??'')}
        onChange={e=>put('replication_plan',{...((context.replication_plan??{}) as Record<string,unknown>),default_replicates_per_condition:e.target.value===''?null:Number(e.target.value),source:'user_input'})}/></label>
      <CanonicalStudyFields {...{context,onChange,samples,species,ptmType}} sourceEditor/>
      <details><summary>기존 sample manifest 가져오기 / 수정</summary>
        <p className="text-xs">선언된 condition, biological_unit, technical_injection, pairing을 가져옵니다. Rep. 번호로 관계를 추정하지 않습니다.</p>
        <textarea aria-label="Sample manifest JSON" className="w-full rounded border bg-background p-2 text-xs" key={JSON.stringify(context.sample_manifest)} defaultValue={JSON.stringify(context.sample_manifest??null,null,2)} onBlur={e=>{try{const value=JSON.parse(e.target.value);if(value!==null&&(!Array.isArray(value.samples)||!Array.isArray(value.conditions)))throw new Error();put('sample_manifest',value);setError('');}catch{setError('sample manifest에는 samples와 conditions 배열이 필요합니다.');}}}/>
        {error&&<p role="alert">{error}</p>}
      </details>
    </details>
  </div>;
}
