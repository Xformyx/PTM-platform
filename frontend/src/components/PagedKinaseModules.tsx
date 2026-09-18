import {useEffect,useRef,useState} from 'react';
import {api} from '../lib/api';
import {LatestRequest} from '../lib/vectorView';

export function PagedKinaseModules({result}:{result:any}) {
 const [kinase,setKinase]=useState(''),[after,setAfter]=useState(''),[search,setSearch]=useState('');
 const [modulePage,setModulePage]=useState(0),[page,setPage]=useState<any>(null),[error,setError]=useState('');
 const latest=useRef(new LatestRequest());
 useEffect(()=>{setKinase('');setAfter('');setPage(null);return()=>latest.current.invalidate();},[result.analysis_job_id]);
 useEffect(()=>{const token=latest.current.begin();setPage(null);setError('');if(!kinase)return;
   const query=new URLSearchParams({kind:kinase==='__unassigned'?'features':'members',after,limit:'100',...(kinase==='__unassigned'?{status:'unassigned'}:{kinase})});
   api.get<any>(`${result.membership_page_url}?${query}`).then(p=>{if(latest.current.current(token))setPage(p);}).catch(e=>{if(latest.current.current(token))setError(String(e));});
   return()=>latest.current.invalidate();
 },[result.membership_page_url,kinase,after]);
 const modules=result.kinase_modules.filter((m:any)=>m.canonical.toLowerCase().includes(search.toLowerCase()));
 return <section className="space-y-2" data-testid="paged-kinase-modules">
   <p className="text-xs">전체 분석 feature {result.coverage.analysis_features} · 적격 {result.coverage.eligible_features} · 후보 연결 {result.coverage.mapped_features} · 미귀속 {result.summary.total_unassigned}. 후보는 직접 인과의 확정이 아닙니다.</p>
   <label>Kinase 검색 <input value={search} onChange={e=>{setSearch(e.target.value);setModulePage(0);}}/></label>
   <div className="grid grid-cols-3 gap-1">{modules.slice(modulePage*50,(modulePage+1)*50).map((m:any)=><button className="border rounded text-xs p-1" key={m.canonical} onClick={()=>{setKinase(m.canonical);setAfter('');}}>{m.canonical} · 후보 {m.total_count}</button>)}</div>
   <button disabled={!modulePage} onClick={()=>setModulePage(p=>p-1)}>이전 kinase</button> <button disabled={(modulePage+1)*50>=modules.length} onClick={()=>setModulePage(p=>p+1)}>다음 kinase</button>
   <button onClick={()=>{setKinase('__unassigned');setAfter('');}}>미귀속 원장 조회</button>
   {kinase&&<p className="text-xs">{kinase==='__unassigned'?'미귀속':kinase} · {page?`전체 ${page.count}, 현재 페이지 ${page.records.length}`:'조회 중…'}</p>}
   {error&&<p role="alert">{error}</p>}
   {page&&<><div className="max-h-72 overflow-auto">{page.records.map((r:any)=><details key={r.feature_id}><summary className="text-xs">{r.gene||r.feature_id} {r.position||''} · {r.evaluation_status||r.membership} · {(r.evidence_roles||[]).join(', ')}</summary><pre className="text-xs overflow-auto">{JSON.stringify(r,null,2)}</pre></details>)}</div><button disabled={!page.next_cursor} onClick={()=>setAfter(page.next_cursor)}>다음 100개</button></>}
   <button onClick={()=>api.downloadFile(result.membership_page_url.replace(/\/inventory$/,'/artifacts/candidates'),'full_analysis_inventory.json')}>고정 revision의 전체 근거 원장</button>
 </section>;
}
