import {useEffect,useState} from 'react';
import {CartesianGrid,Line,LineChart,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts';
import {api} from '../lib/api';
import {axisLabel,type QuantAxis,type QuantRow} from '../lib/quantitation';
import {indexedTrajectory,indexObservations} from '../lib/vectorView';
import {Button} from './ui/button';

export type PrecursorSelection={feature_id:string;revision:string;label:string;source_row:number};
type Detail={feature:{gene:string;position:string;protein_group:string;fasta_taxonomy_id:string;annotation_match:{status:string;assertions:{annotation_id:string;match_scope:string;source:Record<string,unknown>}[]}};
  measurement_revision:string;condition_grid:{condition:string;time_minutes:number|null;source:string}[];observations:QuantRow[]};
const axes:QuantAxis[]=['unadjusted','protein','relative'];
export function SelectedPrecursor({orderId,selection,onEvidence}:{orderId:number;selection:PrecursorSelection;onEvidence:()=>void}){
  const [data,setData]=useState<Detail>(),[error,setError]=useState('');
  useEffect(()=>{let active=true;
    api.post<Detail>(`/orders/${orderId}/vector-view/feature-detail`,{measurement_revision:selection.revision,options:{feature_id:selection.feature_id}})
      .then(d=>{if(active)setData(d)}).catch(e=>{if(active)setError(String(e.message))});
    return()=>{active=false};
  },[orderId,selection]);
  if(error)return <p role="alert">{selection.label} · {error}</p>;
  if(!data)return <p role="status">{selection.label} 조회 중…</p>;
  const index=indexObservations(data.observations),conditions=data.condition_grid.map(c=>c.condition);
  const values=axes.map(a=>indexedTrajectory(index,selection.feature_id,conditions,a,'conventional_log2_contrast'));
  const points=data.condition_grid.map((c,i)=>({...c,...Object.fromEntries(axes.map((a,j)=>[a,values[j][i]]))}));
  return <section aria-label="선택 기질" className="min-w-0 space-y-2 rounded border p-3">
    <h3>{selection.label} · {data.feature.protein_group} · taxon {data.feature.fasta_taxonomy_id||'미기록'}</h3>
    <p>전처리 TSV · 동일 precursor의 U/P/A · log₂ contrast</p>
    <ResponsiveContainer width="100%" height={210}><LineChart data={points.filter(c=>c.time_minutes!==null)}><CartesianGrid/><XAxis dataKey="time_minutes" type="number" domain={['dataMin','dataMax']} unit=" min"/><YAxis/><Tooltip/>{axes.map((a,i)=><Line key={a} dataKey={a} name={axisLabel[a]} stroke={['#2563eb','#a16207','#be123c'][i]} isAnimationActive={false} connectNulls={false}/>)}</LineChart></ResponsiveContainer>
    <div className="overflow-x-auto"><table><thead><tr><th>조건 · 시간 (분)</th>{axes.map(a=><th key={a}>{axisLabel[a]}</th>)}<th>원본 관측</th></tr></thead><tbody>{points.map((p,i)=><tr key={p.condition}><td>{p.condition} · {p.time_minutes??'미기록'}</td>{values.map((v,j)=><td key={j}>{v[i]??'NA'}</td>)}<td>{index.get(selection.feature_id)?.has(p.condition)?'등록':'행 없음'}</td></tr>)}</tbody></table></div>
    <details><summary>저장 주석 · {data.feature.annotation_match.status}</summary>{data.feature.annotation_match.assertions.map(a=><p key={a.annotation_id}>{a.match_scope} · {a.annotation_id} · {JSON.stringify(a.source)}</p>)}</details>
    <details><summary>원본 출처와 계산 범위</summary><pre className="overflow-auto">{JSON.stringify({selection,observations:data.observations},null,2)}</pre></details>
    <Button onClick={onEvidence}>이 precursor의 Kinase·경로 근거</Button>
  </section>
}
