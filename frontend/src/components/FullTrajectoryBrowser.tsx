import {useEffect,useMemo,useRef,useState} from 'react';
import {api} from '../lib/api';
import {type QuantAxis} from '../lib/quantitation';
import {LatestRequest,representationValue,sharedViewRequest} from '../lib/vectorView';

type Manifest={measurement_revision:string;identified_features:number;source_rows:number;conditions:string[]};
/** Exact paginated curves over an all-feature distribution. A page is not an analysis subset. */
export function FullTrajectoryBrowser({orderId,axis}:{orderId:number;axis:QuantAxis}) {
 const [manifest,setManifest]=useState<Manifest|null>(null),[distribution,setDistribution]=useState<any>(null);
 const [page,setPage]=useState<{feature_ids:string[];next_cursor:string|null}|null>(null),[rows,setRows]=useState<any[]>([]);
 const [after,setAfter]=useState(''),[search,setSearch]=useState(''),[error,setError]=useState('');
 const [checked,setChecked]=useState<Record<string,boolean>>({}),[pinned,setPinned]=useState<string[]>([]);
 const [hover,setHover]=useState('');const canvas=useRef<HTMLCanvasElement>(null),distributionCanvas=useRef<HTMLCanvasElement>(null);
 const latest=useRef(new LatestRequest()),detailRequests=useRef(new LatestRequest());
 const [detail,setDetail]=useState<any>(null);
 const labels=useMemo(()=>new Map(rows.map(r=>[r.feature_id,r.source_gene_label])),[rows]);
 const numericIndex=useMemo(()=>{const index=new Map<string,Map<string,number>>();for(const r of rows){const value=representationValue(r,axis,'conventional_log2_contrast');if(value===null)continue;if(!index.has(r.feature_id))index.set(r.feature_id,new Map());index.get(r.feature_id)!.set(r.condition,value);}return index;},[rows,axis]);
 const inspect=async(id:string)=>{const token=detailRequests.current.begin();try{const packet=await api.post<any>(`/orders/${orderId}/vector-view/annotations`,{measurement_revision:manifest?.measurement_revision,options:{axis:axis==='relative'?'adjusted':axis,search:id,limit:1}});if(detailRequests.current.current(token))setDetail(packet);}catch(e){if(detailRequests.current.current(token))setDetail({error:String(e)});}};
 useEffect(()=>{setDetail(null);detailRequests.current.invalidate();return()=>detailRequests.current.invalidate();},[orderId,axis,manifest?.measurement_revision]);
 useEffect(()=>{setAfter('');setPinned([]);setManifest(null);setRows([]);setPage(null);},[orderId,axis]);
 useEffect(()=>{const token=latest.current.begin();setError('');
  const call=(operation:string,options={},revision?:string)=>sharedViewRequest(JSON.stringify([orderId,operation,options,revision]),()=>api.post<any>(`/orders/${orderId}/vector-view/${operation}`,{measurement_revision:revision,options}));
  (async()=>{const m=await call('manifest');const [d,p]=await Promise.all([call('distribution',{axis:axis==='relative'?'adjusted':axis},m.measurement_revision),call('features',{axis:axis==='relative'?'adjusted':axis,after,search,limit:100},m.measurement_revision)]);
   const ids=[...new Set([...pinned,...p.feature_ids])];const r=await call('trajectories',{feature_ids:ids},m.measurement_revision);
   if(!latest.current.current(token))return;setManifest(m);setDistribution(d);setPage(p);setRows(r);setChecked(previous=>Object.fromEntries(ids.map(id=>[id,previous[id]??true])));
  })().catch(e=>{if(latest.current.current(token))setError(String(e.message||e));});
  return ()=>latest.current.invalidate();
 },[orderId,axis,after,search,pinned]);
 useEffect(()=>{const ctx=distributionCanvas.current?.getContext('2d');if(!ctx||!manifest||!distribution)return;ctx.clearRect(0,0,760,200);
  const max=distribution.bins.reduce((m:number,b:any)=>Math.max(m,b.count),1),w=760/Math.max(1,manifest.conditions.length);
  for(const b of distribution.bins){const x=manifest.conditions.indexOf(b.condition)*w,y=200-(b.bin+1)*200/distribution.resolution;
   ctx.fillStyle=`rgba(37,99,235,${0.15+0.85*Math.log1p(b.count)/Math.log1p(max)})`;ctx.fillRect(x,y,w,200/distribution.resolution+0.2);}
 },[manifest,distribution]);
 useEffect(()=>{const ctx=canvas.current?.getContext('2d');if(!ctx||!manifest||!distribution?.bounds)return;ctx.clearRect(0,0,760,320);
  const [low,high]=distribution.bounds;let i=0;for(const [id,values]of numericIndex){if(!checked[id])continue;ctx.strokeStyle=ctx.fillStyle=`hsl(${(i++*137.5)%360} 65% 42%)`;ctx.beginPath();let previous=false;
   manifest.conditions.forEach((condition,j)=>{const v=values.get(condition);if(v===undefined){previous=false;return;}const x=12+j*736/Math.max(1,manifest.conditions.length-1),y=308-(v-low)*296/Math.max(high-low,1e-9);if(previous)ctx.lineTo(x,y);else ctx.moveTo(x,y);previous=true;});ctx.stroke();
   manifest.conditions.forEach((condition,j)=>{const v=values.get(condition);if(v===undefined)return;const x=12+j*736/Math.max(1,manifest.conditions.length-1),y=308-(v-low)*296/Math.max(high-low,1e-9);ctx.beginPath();ctx.arc(x,y,2.5,0,Math.PI*2);ctx.fill();});}
 },[numericIndex,manifest,distribution,checked]);
 if(error)return <p role="alert">{error} · Scatter의 표시 인덱스 준비 버튼으로 과거 주문을 준비할 수 있습니다.</p>;
 if(!manifest||!page||!distribution)return <p>전체 분포와 trajectory 페이지를 조회 중입니다.</p>;
 return <div className="space-y-3" data-testid="full-trajectory-browser"><p>전체 관측 feature {distribution.eligible_features} · 원본 행 {manifest.source_rows} · 현재 페이지 {page.feature_ids.length} · 체크 {Object.values(checked).filter(Boolean).length}</p>
 <p>측정값: 전처리 vector · {axis} log2 contrast · 전체 관측 분포는 집계이며 개별 precursor가 아닙니다.</p>
 <canvas ref={distributionCanvas} width={760} height={200} className="max-w-full" aria-label="전체 시점별 관측 분포"/>
 <p>{manifest.conditions.join(' → ')} · 범위 {distribution.bounds?.join(' … ')} · 유효 관측 {distribution.count}</p>
 <canvas ref={canvas} width={760} height={320} className="max-w-full" aria-label="현재 페이지의 정확한 trajectory" onMouseMove={e=>{const x=(e.clientX-e.currentTarget.getBoundingClientRect().left)/e.currentTarget.getBoundingClientRect().width;const index=Math.min(manifest.conditions.length-1,Math.max(0,Math.round(x*(manifest.conditions.length-1))));setHover(manifest.conditions[index]||'');}}/>
 <p>시점: {hover||'—'} · 없는 시점은 연결하지 않습니다. 페이지·체크·pin은 분석 입력을 바꾸지 않습니다.</p>
 <label>Feature ID 검색 <input aria-label="Feature ID 검색" value={search} onChange={e=>{setSearch(e.target.value);setAfter('');}}/></label>
 <div className="max-h-64 overflow-auto">{[...new Set([...pinned,...page.feature_ids])].map(id=><div key={id}><label><input type="checkbox" checked={checked[id]||false} onChange={e=>setChecked({...checked,[id]:e.target.checked})}/>{labels.get(id)||id} · {id}</label> <button onClick={()=>setPinned(p=>p.includes(id)?p.filter(x=>x!==id):[...p,id])}>{pinned.includes(id)?'Unpin':'Pin'}</button> <button onClick={()=>inspect(id)}>근거 상세</button></div>)}</div>
 {detail&&<details open><summary>주석과 원본 scope · 측정값의 평가와 별도</summary><pre className="max-h-64 overflow-auto text-xs">{JSON.stringify(detail,null,2)}</pre></details>}
 <button onClick={()=>setAfter('')}>처음</button> <button disabled={!page.next_cursor} onClick={()=>setAfter(page.next_cursor!)}>다음 100개</button>
 <button onClick={()=>api.downloadFile(`/orders/${orderId}/vector-view/export?measurement_revision=${encodeURIComponent(manifest?.measurement_revision || "")}`,"full_vector_inventory.jsonl")}>전체 원본 관측 export</button></div>;
}
