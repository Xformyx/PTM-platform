import {useEffect, useRef, useState} from "react";
import {api} from "../lib/api";
import {LatestRequest, sharedViewRequest} from "../lib/vectorView";

type Density = {bins:{x:number;y:number;count:number}[]; count:number; full_eligible_count:number;
  bounds:[number,number,number,number] | null; resolution:number; measurement_revision:string};
type Exact = {observations:{feature_id:string;condition:string;x:number;y:number}[];next_cursor:string|null};

export function VectorDensityPlot({orderId}:{orderId:number}) {
  const canvas=useRef<HTMLCanvasElement>(null), latest=useRef(new LatestRequest()), exactLatest=useRef(new LatestRequest());
  const [manifest,setManifest]=useState<any>(null),[density,setDensity]=useState<Density|null>(null);
  const [axis,setAxis]=useState("adjusted"),[condition,setCondition]=useState("");
  const [bounds,setBounds]=useState<Density["bounds"]>(null),[exact,setExact]=useState<Exact|null>(null);
  const [error,setError]=useState(""),[hover,setHover]=useState("");
  const [preparing,setPreparing]=useState(false),[reload,setReload]=useState(0);
  const start=useRef<[number,number]|null>(null);
  const lasso=useRef<[number,number][]|null>(null);
  const [polygon,setPolygon]=useState<[number,number][]|null>(null);
  useEffect(()=>{
    let active=true;setManifest(null);setDensity(null);setExact(null);setBounds(null);
    sharedViewRequest(`vector-manifest:${orderId}`,()=>api.post<any>(`/orders/${orderId}/vector-view/manifest`,{}))
      .then(m=>{if(active){setManifest(m);setCondition(m.conditions[0]||"");}}).catch(e=>{if(active)setError(String(e));});
    return()=>{active=false;};
  },[orderId,reload]);
  const prepare=async()=>{
    setPreparing(true);setError("");
    try {
      let status=await api.post<any>(`/orders/${orderId}/vector-view/prepare`,{});
      while(["queued","running"].includes(status.execution_status)){
        await new Promise(resolve=>setTimeout(resolve,1500));
        status=await api.post<any>(`/orders/${orderId}/vector-view/preparation_status`,{});
      }
      if(status.execution_status!=="completed")throw new Error(status.failure_reason||status.execution_status);
      setReload(x=>x+1);
    }catch(e){setError(String(e));}finally{setPreparing(false);}
  };
  useEffect(()=>{
    if(!manifest)return;
    const token=latest.current.begin();exactLatest.current.invalidate();setError("");setExact(null);setPolygon(null);
    api.post<Density>(`/orders/${orderId}/vector-view/density`,{measurement_revision:manifest.measurement_revision,
      options:{axis,condition:condition||null,bins:96,bounds}}).then(d=>{if(latest.current.current(token))setDensity(d);})
      .catch(e=>{if(latest.current.current(token))setError(String(e));});
    return()=>latest.current.invalidate();
  },[manifest,orderId,axis,condition,bounds]);
  useEffect(()=>{
    const context=canvas.current?.getContext("2d");if(!context||!density)return;
    context.clearRect(0,0,768,576);
    let maximum=1;for(const bin of density.bins)maximum=Math.max(maximum,bin.count);
    for(const bin of density.bins){
      context.fillStyle=`rgba(30,100,200,${.3+.7*Math.log1p(bin.count)/Math.log1p(maximum)})`;
      context.fillRect(bin.x*768/density.resolution,(density.resolution-1-bin.y)*576/density.resolution,768/density.resolution,576/density.resolution);
    }
    if(polygon&&density.bounds){
      const b=density.bounds;context.beginPath();
      polygon.forEach(([x,y],i)=>{const px=(x-b[0])/Math.max(b[1]-b[0],1e-12)*768,py=(b[3]-y)/Math.max(b[3]-b[2],1e-12)*576;i?context.lineTo(px,py):context.moveTo(px,py);});
      context.closePath();context.strokeStyle='#d02020';context.lineWidth=2;context.stroke();
    }
  },[density,polygon]);
  const coordinate=(e:React.PointerEvent<HTMLCanvasElement>):[number,number]=>{
    const rect=e.currentTarget.getBoundingClientRect(),b=density!.bounds!;
    return [b[0]+(e.clientX-rect.left)/rect.width*(b[1]-b[0]),b[3]-(e.clientY-rect.top)/rect.height*(b[3]-b[2])];
  };
  const drill=async(after="")=>{
    if(!density?.bounds)return;
    const token=exactLatest.current.begin();
    try { const d=await api.post<Exact>(`/orders/${orderId}/vector-view/coordinates`,{measurement_revision:density.measurement_revision,
      options:{axis,condition:condition||null,bounds:density.bounds,after,limit:200,polygon}});
    if(exactLatest.current.current(token))setExact(d);
    } catch(e) {if(exactLatest.current.current(token))setError(String(e));}
  };
  return <section className="space-y-3" data-testid="vector-density">
    <h3>전체 관측 분포</h3>
    <p>측정값: 전처리 vector · 전체 bin 합계 {density?.count ?? "…"} / 축 적격 {density?.full_eligible_count ?? "…"} 관측.
      색은 같은 영역의 관측 수입니다. 드래그로 확대하거나 Shift+드래그로 원좌표 lasso를 선택한 뒤 정확한 precursor 좌표를 조회할 수 있습니다.</p>
    {polygon&&<p>Lasso 선택 {polygon.length}개 꼭짓점 · 조회는 원래 float64 좌표로 판정합니다. <button onClick={()=>{setPolygon(null);setExact(null);}}>선택 해제</button></p>}
    <label>축 <select value={axis} onChange={e=>{setAxis(e.target.value);setBounds(null);}}>
      <option value="adjusted">Protein-adjusted PTM (A)</option><option value="unadjusted">PTM (U)</option><option value="protein">Protein (P)</option></select></label>
    <select aria-label="조건" value={condition} onChange={e=>{setCondition(e.target.value);setBounds(null);}}>
      {(manifest?.conditions||[]).map((c:string)=><option key={c}>{c}</option>)}</select>
    <button onClick={()=>setBounds(null)}>전체 범위</button><button onClick={()=>drill()}>정확한 좌표 조회</button>
    <button onClick={()=>api.downloadFile(`/orders/${orderId}/vector-view/export?measurement_revision=${encodeURIComponent(manifest?.measurement_revision || "")}`,"full_vector_inventory.jsonl")}>전체 원장 export</button>
    {error&&<p role="alert">{error}</p>}
    {!manifest&&<button disabled={preparing} onClick={prepare}>{preparing?"전체 관측 보기 준비 중…":"기존 측정값으로 전체 관측 보기 준비"}</button>}
    <canvas ref={canvas} width={768} height={576} style={{width:"100%",maxWidth:768,height:576,border:"1px solid #aaa"}}
      aria-label="전체 관측 density" onPointerDown={e=>{if(density?.bounds){start.current=coordinate(e);lasso.current=e.shiftKey?[start.current]:null;e.currentTarget.setPointerCapture(e.pointerId);}}}
      onPointerUp={e=>{if(start.current&&density?.bounds){const end=coordinate(e),a=start.current;start.current=null;
        if(lasso.current){const points=[...lasso.current,end];lasso.current=null;if(points.length>=3){setPolygon(points);setExact(null);}return;}
        if(a[0]!==end[0]&&a[1]!==end[1])setBounds([Math.min(a[0],end[0]),Math.max(a[0],end[0]),Math.min(a[1],end[1]),Math.max(a[1],end[1])]);}}}
      onPointerMove={e=>{if(density?.bounds){const [x,y]=coordinate(e);if(lasso.current)lasso.current.push([x,y]);setHover(`Protein log2FC ${x.toFixed(3)}, ${axis} log2FC ${y.toFixed(3)}`);}}}/>
    <p>{hover}</p>
    {density?.bounds&&<p>Protein log2FC [{density.bounds[0]}, {density.bounds[1]}] · {axis} log2FC [{density.bounds[2]}, {density.bounds[3]}]</p>}
    {exact&&<><p>정확한 관측 {exact.observations.length}개 (현재 페이지)</p><table><tbody>{exact.observations.map(r=><tr key={r.feature_id+":"+r.condition}>
      <td>{r.feature_id}</td><td>{r.condition}</td><td>{r.x}</td><td>{r.y}</td></tr>)}</tbody></table>
      {exact.next_cursor&&<button onClick={()=>drill(exact.next_cursor!)}>다음 관측</button>}</>}
  </section>;
}
