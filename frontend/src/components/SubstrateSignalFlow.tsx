import {useEffect, useState} from 'react';
import {CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {api} from '../lib/api';

type Row=Record<string,any>;
type Page={status:string;reason?:string;items:Row[];total_count:number;next_cursor:string|null;catalog_id?:string};
const parse=(value:string|null|undefined,fallback:any=[])=>value?JSON.parse(value):fallback;
const relationLabels:Record<string,string>={bundle_member:'형태 묶음의 구성원',candidate_association:'후보–기질 연관',method_contribution:'방법 결과의 계산 기여',method_input_excluded:'방법 입력에서 제외',same_parent_mathematical_dependence:'같은 부모단백질의 수학적 의존성',observed_before:'관측 구간의 선후',curated_enzyme_substrate_prior:'기록된 효소–기질 방향 관계 (prior)'};
function usePage(orderId:number,kind:string,filters:Row,cursor:string|null=null,limit=25) {
  const key=JSON.stringify([orderId,kind,filters,cursor,limit]);
  const [state,setState]=useState<{key:string;page?:Page;error?:string}>({key:''});
  useEffect(()=>{let active=true;setState({key});
    api.post<Page>(`/orders/${orderId}/substrate-signal/${kind}`,{filters,cursor,limit})
      .then(page=>{if(active)setState({key,page});}).catch(e=>{if(active)setState({key,error:String(e.message||e)});});
    return()=>{active=false;};
  },[key]);
  return state.key===key?state:{key};
}
function SourceDetails({row}:{row:Row}) {return <details><summary>원본 key · 저장 상태 · 해석 제한</summary><pre className="overflow-auto max-h-80 text-xs whitespace-pre-wrap">{JSON.stringify(row,null,2)}</pre></details>;}
function Candidate({orderId,bundle}:{orderId:number;bundle:Row}) {
  const [cursor,setCursor]=useState<string|null>(null);
  const [linkCursor,setLinkCursor]=useState<string|null>(null);
  const members=usePage(orderId,'kinase_substrate_membership',{bundle_id:bundle.bundle_id},cursor);
  const links=usePage(orderId,'temporal_evidence_links',{bundle_id:bundle.bundle_id},linkCursor,100);
  const hypotheses=usePage(orderId,'downstream_hypotheses',{bundle_id:bundle.bundle_id});
  return <section className="border rounded p-3 space-y-2" aria-label="Kinase substrate 근거">
    <h4>{bundle.candidate_id} · {bundle.track}</h4>
    <p>연결 form {bundle.association_form_count} · 기여 form {bundle.contributing_form_count} · site {bundle.site_count} · gene {bundle.gene_count??'미기록'} · 측정군 {bundle.measurement_group_count}</p>
    <p>구별 불가 후보: {parse(bundle.indistinguishable_candidates_json).join(', ')||'이 projection에서 확정하지 않음'} · 활성 확정이 아닌 탐색적 연관</p>
    <table className="w-full text-xs"><caption>{bundle.track.startsWith('method:')?'저장 native method 결과 — log2 footprint와 별도 단위':'저장 footprint / fixed-common — 새 합산 없음'}</caption><thead><tr><th>분</th><th>variable / native</th><th>fixed-common</th><th>기여 gene / 측정군</th><th>진입 / 이탈</th></tr></thead><tbody>{parse(bundle.points_json).map((p:Row)=>{
      const variable=p.saved_results?.['kinase/kinase_temporal_profiles']?.[0]?.values;
      const native=p.saved_results?.['kinase/method_scores']?.[0]?.values;
      const fixed=p.saved_results?.['temporal/kinase_fixed_membership']?.[0]?.values;
      return <tr key={p.contrast_id}><td>{p.time_min??'미기록'}</td><td>{variable?.activity_magnitude??native?.score??'NA'} · {variable?.activity_status??native?.status??'상태 미기록'}</td><td>{fixed?.fixed_common_score??'NA'}</td><td>{p.contributing_gene_count??'미기록'} / {p.contributing_measurement_group_count}</td><td>{fixed?.entered_sites??'미기록'} / {fixed?.departed_sites??'미기록'}</td></tr>;
    })}</tbody></table>
    <SourceDetails row={{points:parse(bundle.points_json),diagnostics:parse(bundle.diagnostics_json),fixed_membership_status:bundle.fixed_membership_status,source_availability:parse(bundle.source_availability_json)}}/>
    <p>전체 membership {members.page?.total_count??'…'}개 — 첫 집합 구성은 emergence가 아닙니다.</p>
    {members.page?.items.map(m=><SourceDetails key={m.membership_id} row={{membership_id:m.membership_id,forms:parse(m.form_ids_json),saved_values:parse(m.saved_values_json),source:parse(m.source_ref_json)}}/>)}
    {members.page?.next_cursor&&<button onClick={()=>setCursor(members.page!.next_cursor)}>다음 기질 근거</button>}
    <details><summary>관계와 화살표 의미 ({links.page?.total_count??0})</summary>{links.page?.items.map(l=><div key={l.link_id}><p>{relationLabels[l.edge_type]||l.edge_type} · {l.status}{l.reason?` · ${l.reason}`:''}</p><SourceDetails row={l}/></div>)}{links.page?.next_cursor&&<button onClick={()=>setLinkCursor(links.page!.next_cursor)}>다음 관계</button>}<p>화살표는 membership·계산 의존성·관측 순서·기록 prior를 구분합니다. 직접 인과 검증은 아닙니다.</p></details>
    {hypotheses.page?.items.map(h=><div key={h.hypothesis_id}><p>검토할 가설 · {h.prior_status==='missing_exact_prior'?'정확한 방향 관계 prior 미기록':h.prior_status} · 시간 일치: {h.temporal_consistency} · 인과 미확정</p><SourceDetails row={{...h,alternatives:parse(h.alternatives_json),prior_observation_checks:parse(h.prior_observation_checks_json)}}/></div>)}
    {members.error||links.error||hypotheses.error?<p role="alert">{members.error||links.error||hypotheses.error}</p>:null}
  </section>;
}
function FormDetail({orderId,row}:{orderId:number;row:Row}) {
  const detail=usePage(orderId,'substrate_trajectories',{form_id:row.form_id,effect_series_id:row.effect_series_id});
  const [cursor,setCursor]=useState<string|null>(null),[bundle,setBundle]=useState<Row|null>(null);
  const candidates=usePage(orderId,'kinase_substrate_bundles',{form_id:row.form_id,effect_series_id:row.effect_series_id},cursor);
  const tracks=(detail.page?.items||[]).filter(r=>['U_joint','P_joint','A'].includes(r.track));
  const base:Row[]=parse(row.points_json);
  const points=base.filter(p=>p.time_min!==null).map(p=>({...p,...Object.fromEntries(tracks.map(t=>[t.track,parse(t.points_json).find((q:Row)=>q.contrast_id===p.contrast_id)?.value??null]))}));
  return <section className="border rounded p-3 space-y-3" aria-label="Form 시간 반응 상세">
    <h4 className="font-semibold">{row.form_id} · U_joint / P_joint / A</h4>
    <p>기록된 실제 시간(분), log2 contrast. 결측·제외점은 연결하지 않습니다. 절대 occupancy나 kinase 농도가 아닙니다.</p>
    <ResponsiveContainer width="100%" height={280}><LineChart data={points}><CartesianGrid strokeDasharray="3 3"/><XAxis type="number" dataKey="time_min" domain={['dataMin','dataMax']} label={{value:'분',position:'insideBottomRight'}}/><YAxis/><Tooltip/><Legend/>{['U_joint','P_joint','A'].map((t,i)=><Line key={t} name={t} dataKey={t} stroke={['#2563eb','#a16207','#be123c'][i]} connectNulls={false} isAnimationActive={false}/>)}</LineChart></ResponsiveContainer>
    <table className="text-xs w-full"><thead><tr><th>시간</th><th>실제 Control</th><th>Control 시간</th><th>A / 상태</th></tr></thead><tbody>{base.map(p=><tr key={p.contrast_id}><td>{p.time_min??'미기록'}</td><td>{p.reference_condition_id}</td><td>{p.reference_time_min??'미기록'}</td><td>{p.value??'NA'} · {p.status}</td></tr>)}</tbody></table>
    <SourceDetails row={{identity:parse(row.identity_json),feature:parse(row.feature_json),feature_status:row.feature_status,scope:parse(row.scope_json),points:base}}/>
    <p>연결된 전체 kinase bundle {candidates.page?.total_count??'…'}개</p>
    {candidates.page?.items.map(b=><button className="border rounded px-2 mr-2" key={b.bundle_id} onClick={()=>setBundle(b)}>{b.candidate_id} · {b.track}</button>)}
    {candidates.page?.next_cursor&&<button onClick={()=>setCursor(candidates.page!.next_cursor)}>다음 후보</button>}
    {bundle&&<Candidate key={bundle.bundle_id} orderId={orderId} bundle={bundle}/>}
    {detail.error||candidates.error?<p role="alert">{detail.error||candidates.error}</p>:null}
  </section>;
}
export function SubstrateSignalFlow({orderId}:{orderId:number}) {
  const [cursor,setCursor]=useState<string|null>(null),[limit,setLimit]=useState(15),[selected,setSelected]=useState<Row|null>(null),[pins,setPins]=useState<string[]>([]);
  const {page,error}=usePage(orderId,'substrate_trajectories',{track:'A'},cursor,limit);
  return <section className="space-y-3 mb-6" aria-label="전체 기질 기반 신호 흐름">
    <h3 className="font-semibold">전체 기질 시간 반응 → kinase 근거 → 관계·가설</h3>
    <p>발행 snapshot의 전체 적격 관측과 계산 추적. 페이지와 pin은 분석 모집단·활성 판정을 바꾸지 않습니다.</p>
    {error&&<p role="alert">{error}</p>}
    {page?.status==='unavailable'?<p>{page.reason} — 저장 projection이 포함된 reader revision에서 제공됩니다.</p>:<>
      <label>페이지 크기 <select value={limit} onChange={e=>{setLimit(Number(e.target.value));setCursor(null);}}>{[5,15,50].map(n=><option key={n}>{n}</option>)}</select></label>
      <span> 전체 form/scope {page?.total_count??'…'} · 검토 pin {pins.length}</span>
      <ul>{page?.items.map(r=><li key={r.trajectory_id}><button className="text-primary underline" onClick={()=>setSelected(r)}>{parse(r.identity_json,{}).display_label||r.form_id}</button> · 유효점 {r.eligible_points}/{r.registered_points} · {r.pattern||'pattern 미기록'} <button aria-label={`검토 pin ${r.form_id}`} onClick={()=>setPins(p=>p.includes(r.trajectory_id)?p.filter(x=>x!==r.trajectory_id):[...p,r.trajectory_id])}>{pins.includes(r.trajectory_id)?'Unpin':'Pin'}</button></li>)}</ul>
      <button disabled={!cursor} onClick={()=>setCursor(null)}>처음</button> <button disabled={!page?.next_cursor} onClick={()=>setCursor(page!.next_cursor)}>다음 페이지</button>
      {selected&&<FormDetail key={selected.trajectory_id} orderId={orderId} row={selected}/>}
    </>}
  </section>;
}
