import {useEffect,useMemo,useRef,useState} from 'react';

type ScoreRow={kinase:string;scores:Record<string,number|null>};
/** Exact cells, windowed in both dimensions. View limits never alter the rows. */
export function VirtualScoreHeatmap({rows,conditions,onSelect}:{rows:ScoreRow[];conditions:string[];onSelect:(name:string)=>void}) {
  const host=useRef<HTMLDivElement>(null);
  const [viewport,setViewport]=useState({top:0,left:0,width:800,height:420});
  const [detail,setDetail]=useState<ScoreRow|null>(null);
  const rowHeight=28,colWidth=86,labelWidth=160;
  const first=Math.max(0,Math.floor(viewport.top/rowHeight)-2);
  const last=Math.min(rows.length,first+Math.ceil(viewport.height/rowHeight)+5);
  const cFirst=Math.max(0,Math.floor(viewport.left/colWidth)-2);
  const cLast=Math.min(conditions.length,cFirst+Math.ceil(viewport.width/colWidth)+5);
  const max=useMemo(()=>{let n=0;for(const r of rows)for(const v of Object.values(r.scores))if(v!==null&&Number.isFinite(v))n=Math.max(n,Math.abs(v));return n||1;},[rows]);
  return <div className="space-y-2" data-testid="virtual-score-heatmap">
    <p className="text-xs">전체 표시 대상 {rows.length} · 현재 viewport {last-first} · 조건 {conditions.length}. 셀은 계산된 substrate footprint이며 catalytic activity 판정이 아닙니다.</p>
    <div ref={host} className="border overflow-auto" style={{height:420,position:'relative'}} onScroll={()=>{const e=host.current!;setViewport({top:e.scrollTop,left:e.scrollLeft,width:e.clientWidth,height:e.clientHeight});}}>
      <div style={{height:(rows.length+1)*rowHeight,width:labelWidth+conditions.length*colWidth,position:'relative'}}>
        {rows.slice(first,last).map((row,offset)=><div key={row.kinase} style={{position:'absolute',top:(first+offset+1)*rowHeight,height:rowHeight,width:'100%'}}>
          <button className="text-xs truncate bg-background text-left" style={{position:'sticky',left:0,width:labelWidth,height:rowHeight,zIndex:1}} onClick={()=>{setDetail(row);onSelect(row.kinase);}} title={row.kinase}>{row.kinase}</button>
          {conditions.slice(cFirst,cLast).map((c,index)=>{const value=row.scores[c];const valid=value!==null&&value!==undefined&&Number.isFinite(value);return <button key={c} title={`${row.kinase} · ${c}: ${valid?value:'NA'}`} onClick={()=>{setDetail(row);onSelect(row.kinase);}} style={{position:'absolute',left:labelWidth+(cFirst+index)*colWidth,width:colWidth,height:rowHeight,background:valid?`rgba(${value>=0?'220,60,60':'50,100,220'},${Math.abs(value)/max})`:'#ddd'}} className="text-xs border">{valid?value.toFixed(3):'NA'}</button>;})}
        </div>)}
        <div style={{position:'sticky',top:0,height:rowHeight,zIndex:2}} className="bg-background">
          {conditions.slice(cFirst,cLast).map((c,index)=><span key={c} className="text-xs truncate text-center" title={c} style={{position:'absolute',left:labelWidth+(cFirst+index)*colWidth,width:colWidth}}>{c}</span>)}
        </div>
      </div>
    </div>
    {detail&&<details open><summary>{detail.kinase} · 모든 시점의 정확한 값</summary><div className="overflow-auto max-h-48"><pre className="text-xs">{JSON.stringify(detail.scores,null,2)}</pre></div></details>}
  </div>;
}

/** All exact score trajectories on Canvas, with one separately inspected curve. */
export function CanvasScoreTrajectories({rows,conditions}:{rows:ScoreRow[];conditions:string[]}) {
  const canvas=useRef<HTMLCanvasElement>(null),overlay=useRef<HTMLCanvasElement>(null);
  const [detail,setDetail]=useState<{row:ScoreRow;condition:string;value:number}|null>(null);
  const index=useMemo(()=>conditions.map(c=>rows.filter(r=>r.scores[c]!=null&&Number.isFinite(r.scores[c])).map(row=>({row,value:row.scores[c]!})).sort((a,b)=>a.value-b.value)),[rows,conditions]);
  const extent=useMemo(()=>{let min=Infinity,max=-Infinity;for(const series of index)for(const p of series){min=Math.min(min,p.value);max=Math.max(max,p.value);}return Number.isFinite(min)?[min,max]:[0,0];},[index]);
  const y=(value:number)=>380-(value-extent[0])/Math.max(extent[1]-extent[0],1e-12)*360;
  const x=(i:number)=>20+i/Math.max(conditions.length-1,1)*1160;
  const draw=(context:CanvasRenderingContext2D,row:ScoreRow)=>{context.beginPath();let previous=false;conditions.forEach((c,i)=>{const value=row.scores[c];if(value==null||!Number.isFinite(value)){previous=false;return;}previous?context.lineTo(x(i),y(value)):context.moveTo(x(i),y(value));previous=true;});context.stroke();for(let i=0;i<conditions.length;i++){const value=row.scores[conditions[i]];if(value!=null&&Number.isFinite(value)){context.beginPath();context.arc(x(i),y(value),1.5,0,2*Math.PI);context.fill();}}};
  useEffect(()=>{const context=canvas.current?.getContext('2d');if(!context)return;context.clearRect(0,0,1200,400);context.strokeStyle='rgba(80,100,130,.18)';context.fillStyle='rgba(80,100,130,.18)';for(const row of rows)draw(context,row);},[rows,conditions,extent]);
  useEffect(()=>{const context=overlay.current?.getContext('2d');if(!context)return;context.clearRect(0,0,1200,400);if(detail){context.strokeStyle='#dd4040';context.fillStyle='#dd4040';context.lineWidth=2;draw(context,detail.row);}},[detail,conditions,extent]);
  return <div className="space-y-2"><p className="text-xs">전체 {rows.length}개 계산 궤적 · 모든 실제 시점 · null 구간은 연결하지 않습니다. 포인터로 정확한 궤적을 확인합니다.</p>
    <div style={{position:'relative',width:'100%',aspectRatio:'3/1'}} onPointerMove={e=>{const box=e.currentTarget.getBoundingClientRect();const ci=Math.min(conditions.length-1,Math.max(0,Math.round(((e.clientX-box.left)/box.width*1200-20)/1160*(conditions.length-1))));const pool=index[ci];if(!pool?.length){setDetail(null);return;}const target=extent[0]+(380-(e.clientY-box.top)/box.height*400)/360*(extent[1]-extent[0]);let lo=0,hi=pool.length;while(lo<hi){const m=(lo+hi)>>1;pool[m].value<target?lo=m+1:hi=m;}const a=pool[Math.min(lo,pool.length-1)],b=pool[Math.max(0,lo-1)],near=Math.abs(a.value-target)<Math.abs(b.value-target)?a:b;setDetail({...near,condition:conditions[ci]});}}>
      <canvas ref={canvas} width={1200} height={400} style={{position:'absolute',inset:0,width:'100%',height:'100%'}} aria-label="전체 kinase substrate footprint 궤적"/>
      <canvas ref={overlay} width={1200} height={400} style={{position:'absolute',inset:0,width:'100%',height:'100%'}}/>
    </div><p className="text-xs">Y: substrate footprint [{extent[0]}, {extent[1]}] · X: {conditions.join(' → ')}</p>
    {detail&&<details open><summary>{detail.row.kinase} · {detail.condition}: {detail.value}</summary><pre className="text-xs max-h-48 overflow-auto">{JSON.stringify(detail.row.scores,null,2)}</pre></details>}
  </div>;
}
