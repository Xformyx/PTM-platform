import {useEffect, useMemo, useState} from 'react';
import {Line, LineChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {api} from '../lib/api';
import {conditionMinutes, SCATTER_PALETTE} from '../lib/scatterOverview';
import {Button} from './ui/button';
import {Card, CardContent, CardHeader, CardTitle} from './ui/card';

type Row = Record<string, any>;
type Page = {records: Row[]; total_count: number; next_cursor: string|null; bundle_id?: string};

// Each request owns its cleanup token. A different bundle/pathway never accepts
// the previous request's response, even if the server cannot cancel the read.
function useRead<T>(url: string|null, retry=0) {
  const [state,setState] = useState<{url: string|null; data?:T; error?:string}>({url:null});
  useEffect(()=>{
    if (!url) {setState({url}); return;}
    const controller = new AbortController(); let active=true;
    setState({url});
    api.get<T>(url,{signal:controller.signal}).then(data=>{if(active)setState({url,data});})
      .catch(error=>{if(active)setState({url,error:String(error.message||error)});});
    return ()=>{active=false;controller.abort();};
  },[url,retry]);
  return state.url===url ? state : {url};
}

function usePage(url: string|null, retry=0) {
  const [localRetry,setLocalRetry]=useState(0);
  const [position,setPosition] = useState<{url:string|null;cursor:string}>({url:null,cursor:''});
  const cursor=position.url===url?position.cursor:'';
  const query=url&&cursor?`${url}${url.includes('?')?'&':'?'}cursor=${encodeURIComponent(cursor)}`:url;
  const read=useRead<Page>(query,retry+localRetry);
  return {...read, hasCursor:!!cursor, first:()=>setPosition({url,cursor:''}),
    next:()=>{if(read.data?.next_cursor)setPosition({url,cursor:read.data.next_cursor});},
    reload:()=>setLocalRetry(r=>r+1)};
}

function PageStatus({page,title}:{page:ReturnType<typeof usePage>;title:string}) {
  if(page.error)return <div><p role="alert">{title} 조회 실패: {page.error}</p><Button size="sm" variant="outline" onClick={page.reload}>{title} 다시 조회</Button></div>;
  if(!page.data)return <p role="status">{title} 조회 중…</p>;
  return <div className="text-xs py-2" data-testid={`page-${title}`}>
    {title}: 전체 {page.data.total_count}건 · 현재 페이지 {page.data.records.length}건
    {(page.hasCursor||page.data.next_cursor)&&<span className="inline-flex gap-2 ml-2">
      <Button size="sm" variant="outline" disabled={!page.hasCursor} onClick={page.first}>{title} 처음</Button>
      <Button size="sm" variant="outline" disabled={!page.data.next_cursor} onClick={page.next}>{title} 다음</Button>
    </span>}
  </div>;
}

function label(row:Row) {
  const observations = Object.values(row.observations||{}) as Row[];
  const raw = observations.find(r=>r.source)?.source;
  return `${raw?.source_gene_label || row.source_gene_label || row.gene || 'Unmapped'} ${row.position||''} · ${row.precursor_id||row.feature_id} · z${row.precursor_charge||'?'}`;
}

function Curves({features, conditions, track}: {features:Row[];conditions:string[];track:string}) {
  const [checked,setChecked] = useState<string[]>([]), [zoom,setZoom] = useState(false);
  const identity = features.map(r=>r.feature_id).join('|');
  useEffect(()=>{setChecked(features.slice(0,3).map(r=>r.feature_id));setZoom(false);},[identity]);
  const ordered = useMemo(()=>[...conditions].sort((a,b)=>conditionMinutes(a)-conditionMinutes(b)||a.localeCompare(b)),[conditions]);
  const rows = useMemo(()=>ordered.map(condition=>({condition, minute:conditionMinutes(condition),
    ...Object.fromEntries(features.map(f=>[f.feature_id, f.trajectories?.[track]?.[condition] ?? null]))})),[features,ordered,track]);
  const timed = rows.every(r=>Number.isFinite(r.minute));
  return <div className="space-y-3" data-testid="explorer-curves">
    <p className="text-sm">페이지 {features.length} precursor · 표시 {checked.length} · {track==='relative'?'A: protein-adjusted log2 contrast':track==='unadjusted'?'U: unadjusted log2 contrast (모델 입력과 다른 표현)':'paired occupancy logit delta'}.</p>
    <p className="text-xs text-muted-foreground">없는 시점은 gap이며 실제 0은 관측입니다. precursor 수는 biological n이 아닙니다. 체크와 확대는 계산 결과를 변경하지 않습니다.</p>
    <div className="h-72 w-full min-w-0" role="img" aria-label="선택 precursor의 실제 시간 곡선">
      <ResponsiveContainer width="100%" height="100%"><LineChart data={rows} margin={{left:8,right:24,top:10,bottom:20}}>
        <CartesianGrid strokeDasharray="3 3"/><XAxis dataKey={timed?'minute':'condition'} type={timed?'number':'category'} domain={['dataMin','dataMax']} label={{value:timed?'Time (min)':'Declared condition',position:'bottom'}}/>
        <YAxis domain={zoom?[-2,2]:['auto','auto']} allowDataOverflow={zoom} tickFormatter={v=>Number(v).toFixed(1)}/>
        <Tooltip labelFormatter={v=>timed?`${v} min`:String(v)} formatter={(v:any,name:any)=>[v, label(features.find(f=>f.feature_id===name)||{feature_id:name})]}/>
        {features.filter(f=>checked.includes(f.feature_id)).map((f,i)=><Line key={f.feature_id} name={f.feature_id} dataKey={f.feature_id} stroke={SCATTER_PALETTE[i%SCATTER_PALETTE.length]} dot={{r:3}} type="linear" connectNulls={false} isAnimationActive={false}/>)}
      </LineChart></ResponsiveContainer>
    </div>
    <Button size="sm" variant="outline" onClick={()=>setZoom(z=>!z)}>{zoom?'전체 범위 복원':'±2 범위 확대'}</Button>
    {zoom&&<p role="status">±2 밖의 점은 잘립니다. 전체 범위 복원으로 확인할 수 있습니다.</p>}
    <div className="max-h-44 overflow-auto border rounded p-2">{features.map(f=><label key={f.feature_id} className="block text-xs py-1 break-all"><input type="checkbox" checked={checked.includes(f.feature_id)} onChange={e=>setChecked(c=>e.target.checked?[...c,f.feature_id]:c.filter(id=>id!==f.feature_id))}/> {label(f)}</label>)}</div>
  </div>;
}

function LegacyObservationView({orderId,initialN}:{orderId:number;initialN:number}) {
  const [n,setN] = useState(initialN),[track,setTrack] = useState('adjusted');
  const curveTrack=track==='adjusted'?'relative':'unadjusted';
  const read = useRead<Row>(`/orders/${orderId}/vector-plot-data?mode=per_condition_top_n&n=${n}&axis=${track}`);
  const features = useMemo(()=>{
    const index = new Map<string,Row>();
    for(const row of read.data?.vector_data||[]) {
      if(!row.feature_id)continue;
      const f=index.get(row.feature_id)||{...row,trajectories:{[curveTrack]:{}}};
      const value=track==='adjusted'?row.ptm_protein_adjusted_log2fc:row.ptm_unadjusted_log2fc;
      if(typeof value==='number'&&Number.isFinite(value))f.trajectories[curveTrack][row.condition]=value;
      index.set(row.feature_id,f);
    }
    return [...index.values()];
  },[read.data,track,curveTrack]);
  return <div className="space-y-3"><p>이 주문에는 연결된 run bundle이 없습니다. 기존 TSV의 관측을 조회합니다. 과거 분석을 full 결과로 재분류하지 않습니다.</p>
    <label>조건별 Top N <select aria-label="Legacy Top N" value={n} onChange={e=>setN(Number(e.target.value))}>{[...new Set([20,50,100,initialN])].sort((a,b)=>a-b).map(v=><option key={v}>{v}</option>)}</select></label>
    <label> 표현 <select aria-label="Legacy axis" value={track} onChange={e=>setTrack(e.target.value)}><option value="adjusted">A</option><option value="unadjusted">U</option></select></label>
    {read.error?<p role="alert">{read.error}</p>:!read.data?<p role="status">원관측 조회 중…</p>:<Curves features={features} conditions={read.data.conditions||[...new Set((read.data.vector_data||[]).map((r:Row)=>r.condition))]} track={curveTrack}/>}
  </div>;
}

/** Shared admin/user completed-result reader. No analysis admission or RAG calls. */
export function SignalingEvidenceExplorer({orderId,initialN:savedN=50}:{orderId:number;initialN?:unknown}) {
  const initialN=typeof savedN==='number'&&Number.isInteger(savedN)&&savedN>0?savedN:50;
  const [retry,setRetry]=useState(0),[bundleId,setBundleId]=useState(''),[pathway,setPathway]=useState('');
  const [mode,setMode]=useState('inventory'),[n,setN]=useState(initialN),[pathwayCursor,setPathwayCursor]=useState('');
  const [kinase,setKinase]=useState(''),[moduleId,setModuleId]=useState('');
  const [modelId,setModelId]=useState('');
  const [cursor,setCursor]=useState(''),[featureId,setFeatureId]=useState(''),[track,setTrack]=useState('relative');
  const runs=useRead<{records:Row[]}>(`/orders/${orderId}/evidence-runs`,retry);
  useEffect(()=>{setBundleId('');setPathway('');setCursor('');setFeatureId('');setPathwayCursor('');setKinase('');setModuleId('');setN(initialN);},[orderId,initialN]);
  const chosen = bundleId || runs.data?.records.find(r=>r.bundle_id)?.bundle_id || '';
  const base=chosen?`/orders/${orderId}/evidence-runs/${encodeURIComponent(chosen)}`:null;
  const bundle=useRead<Row>(base,retry), pathways=useRead<Page>(base?`${base}/pathways?limit=100${pathwayCursor?`&cursor=${encodeURIComponent(pathwayCursor)}`:''}`:null,retry);
  const members=useRead<Page>(base?`${base}/features?limit=50&track=${track}&mode=${mode}${mode.endsWith('top_n')?`&n=${n}`:''}${pathway?`&pathway_key=${encodeURIComponent(pathway)}`:''}${kinase?`&kinase=${encodeURIComponent(kinase)}`:''}${moduleId?`&module_id=${encodeURIComponent(moduleId)}`:''}${cursor?`&cursor=${encodeURIComponent(cursor)}`:''}`:null,retry);
  const kinases=usePage(base?`${base}/kinases?limit=100`:null,retry);
  const details=usePage(base&&featureId?`${base}/contributions?feature_id=${encodeURIComponent(featureId)}&track=${track}`:null,retry);
  const evidence=usePage(base&&featureId?`${base}/evidence?feature_id=${encodeURIComponent(featureId)}`:null,retry);
  const claims=usePage(base&&featureId?`${base}/report-claims?feature_id=${encodeURIComponent(featureId)}`:null,retry);
  const sources=usePage(base?`${base}/source-runs`:null,retry), validations=usePage(base?`${base}/validations`:null,retry);
  const comparison=usePage(base?`${base}/model-comparisons`:null,retry);
  const modelResults=usePage(base&&modelId?`${base}/model-results?model_id=${encodeURIComponent(modelId)}`:null,retry);
  const unmapped=usePage(base?`${base}/unmapped-modules`:null,retry);
  const hypotheses=usePage(base?`${base}/mechanism-hypotheses`:null,retry);
  const suggestions=usePage(base?`${base}/experiment-suggestions`:null,retry);
  useEffect(()=>{setCursor('');setFeatureId('');},[track,mode,n,chosen,kinase,moduleId]);
  useEffect(()=>{setPathwayCursor('');setKinase('');setModuleId('');setModelId('');},[chosen]);
  const error = runs.error||bundle.error||pathways.error||members.error;
  if(error)return <Card><CardContent className="py-5"><p role="alert">결과 조회 실패: {error}</p><Button onClick={()=>setRetry(r=>r+1)}>다시 시도</Button></CardContent></Card>;
  return <div className="space-y-4 min-w-0" data-testid="signaling-explorer">
    <Card><CardHeader><CardTitle>Signaling Evidence Explorer</CardTitle><p className="text-sm text-muted-foreground">완료된 분석의 경로·PTM·kinase·근거를 함께 탐색합니다.</p></CardHeader><CardContent className="space-y-3">
      {!runs.data?<p role="status">분석 run 조회 중…</p>:!chosen?<><p>상태: legacy_unbound · {runs.data.records.map(r=>r.execution_status).join(', ')||'연결된 분석 없음'}</p><LegacyObservationView key={orderId} orderId={orderId} initialN={initialN}/></>:<>
        <label>분석 run <select aria-label="분석 run" className="max-w-full border rounded p-1" value={chosen} onChange={e=>{setBundleId(e.target.value);setPathway('');setCursor('');setFeatureId('');}}>{runs.data.records.filter(r=>r.bundle_id).map(r=><option value={r.bundle_id} key={r.bundle_id}>{r.created_at||r.run_id} · {r.explorer_status}</option>)}</select></label>
        {runs.data.records.some(r=>['queued','running'].includes(r.execution_status))&&<p>새 분석이 진행 중입니다. 현재 표시한 완료 run은 바뀌지 않습니다.</p>}
        {bundle.data?<><p>상태: {bundle.data.explorer_status} · 입력 범위: {bundle.data.analysis_scope}</p>
          <p className="text-sm">원본 행 {bundle.data.coverage.source_rows??'미집계'} · precursor {bundle.data.coverage.identified_features??'미집계'} · 모델 적격 {bundle.data.coverage.eligible_features??'미집계'} · 경로 매핑 {bundle.data.coverage.pathway_mapped_features??'미평가'}</p>
          <p className="text-xs break-all">Bundle {chosen}</p><p className="text-xs">수는 겹치는 집합입니다. pathway/kinase membership 수를 더해 전체 feature 수로 사용하지 않습니다.</p>
        </>:<p role="status">고정된 component 조회 중…</p>}
      </>}
    </CardContent></Card>
    {base&&bundle.data&&<>
      <Card><CardHeader><CardTitle>경로 × 시간</CardTitle></CardHeader><CardContent>
        <p className="text-xs mb-3">구성원 contrast의 기술적 요약 · precursor 중앙값을 단백질별로 요약한 후 평균 · 활성/억제 검정이 아닙니다. 회색은 미평가, 흰색은 0입니다. 시간 열은 범주로 배치됩니다.</p>
        {!pathways.data?<p role="status">경로 조회 중…</p>:pathways.data.records.length===0?<p>경로 결과 없음 · reference 상태: {bundle.data.pathway_source?.status}. 유효한 PTM과 kinase 결과는 아래에서 조회할 수 있습니다.</p>:<div className="overflow-x-auto max-h-96"><table className="text-xs w-full"><thead><tr><th>경로 / provider</th>{bundle.data!.conditions.map((c:string)=><th key={c}>{c}</th>)}</tr></thead><tbody>{pathways.data.records.map(p=><tr key={p.pathway_key}><td><button className="text-left underline p-2" aria-pressed={pathway===p.pathway_key} onClick={()=>{setPathway(p.pathway_key);setCursor('');setFeatureId('');}}>{p.name} · {p.provider} · {p.member_feature_count} features</button></td>{p.scores.map((s:Row)=><td key={s.condition} title={`${s.condition}: ${s.value??'미평가'}; hit/background ${s.hit_proteins}/${s.background_proteins}; ${s.evaluation_status}`} style={{background:s.value===null?'#ddd':s.value===0?'white':s.value>0?'#fecaca':'#bfdbfe'}} className="p-2">{s.value===null?'—':Number(s.value).toFixed(2)}</td>)}</tr>)}</tbody></table></div>}
        <Button variant="outline" size="sm" disabled={!pathways.data?.next_cursor} onClick={()=>setPathwayCursor(pathways.data!.next_cursor!)}>다음 경로</Button> <Button variant="outline" size="sm" onClick={()=>setPathwayCursor('')}>처음 경로</Button> <Button variant="outline" size="sm" onClick={()=>{setPathway('');setCursor('');setFeatureId('');}}>전체 feature</Button>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>PTM 관측과 곡선</CardTitle></CardHeader><CardContent className="space-y-3">
        <p>조회 범위 {pathway?'선택 경로 전체':'전체 inventory'} · {members.data?.total_count??'…'} precursor · 페이지 {members.data?.records.length??0}</p>
        {(kinase||moduleId)&&<p>추가 표시 조건: {kinase||moduleId} <Button size="sm" variant="outline" onClick={()=>{setKinase('');setModuleId('');}}>표시 조건 해제</Button></p>}
        <label>PTM 곡선 표시 <select aria-label="PTM display selection" value={mode} onChange={e=>setMode(e.target.value)}><option value="inventory">범위 내 전체 inventory</option><option value="all_observed">유효 관측 전체</option><option value="global_top_n">전체 Top N</option><option value="per_condition_top_n">조건별 Top N 합집합</option></select></label>
        {mode.endsWith('top_n')&&<label>N <input aria-label="Display N" type="number" min="1" value={n} onChange={e=>{const value=Number(e.target.value);if(Number.isInteger(value)&&value>0)setN(value);}}/></label>}
        <label>정량 표현 <select aria-label="Explorer track" value={track} onChange={e=>setTrack(e.target.value)}><option value="relative">A · 분석 track</option><option value="unadjusted">U · 관측 보기</option><option value="occupancy">유효 paired occupancy</option></select></label>
        {members.data?<><Curves features={members.data.records} conditions={bundle.data.conditions} track={track}/>
          <div className="max-h-60 overflow-auto"><table className="text-xs w-full"><tbody>{members.data.records.map(f=><tr key={f.feature_id}><td><button data-feature-id={f.feature_id} className="underline text-left p-1" onClick={()=>setFeatureId(f.feature_id)}>{label(f)}</button></td>{bundle.data!.conditions.map((c:string)=><td className="p-2" key={c} title={`${c} ${track}`} style={{background:f.trajectories?.[track]?.[c]==null?'#ddd':f.trajectories[track][c]>0?'#fecaca':f.trajectories[track][c]<0?'#bfdbfe':'white'}}>{f.trajectories?.[track]?.[c]==null?'—':Number(f.trajectories[track][c]).toFixed(2)}</td>)}</tr>)}</tbody></table></div>
          <Button size="sm" variant="outline" onClick={()=>setCursor('')}>처음</Button> <Button size="sm" disabled={!members.data.next_cursor} onClick={()=>setCursor(members.data!.next_cursor!)}>다음 50개</Button>
        </>:<p role="status">회원 조회 중…</p>}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Kinase 근거와 전역 footprint</CardTitle></CardHeader><CardContent>
        <p className="text-xs">기질 footprint이며 catalytic activity 확정이나 정답 확률이 아닙니다. 경로 선택으로 전역 score를 재계산하지 않습니다.</p>
        <div className="max-h-64 overflow-auto">{kinases.data?.records.map(k=><details key={k.canonical}><summary>{k.canonical} · {k.tmm_profile_type} · footprint peak {k.peak_condition??'보류'}</summary><p className="text-xs">{bundle.data!.conditions.map((c:string)=>`${c}: ↑${k.up_sums?.[c]??'—'} / ↓${k.down_sums?.[c]??'—'}`).join(' · ')}</p><Button size="sm" variant="outline" onClick={()=>setKinase(k.canonical)}>이 후보에 연결된 관측 보기</Button></details>)}</div>
        <PageStatus page={kinases} title="Kinase"/>
        {featureId&&<div className="mt-3"><p>선택 precursor: {label(members.data?.records.find(f=>f.feature_id===featureId)||{feature_id:featureId})}</p>
          {details.data?.records.map(d=><details key={d.kinase}><summary>{d.kinase}: {d.resolution} · 개별 ratio {d.contribution_ratio??'보류'} · whole-trajectory ratio · {d.unsupported_reason||d.score_status||''}</summary>
            <p className="text-xs">Profile: {d.profile_provenance?.profile_type||'미기록'} · prior peak {d.profile_peak_condition??'보류'}</p>
            <div className="overflow-auto"><table className="text-xs"><thead><tr><th>조건</th><th>귀속 평가</th><th>합산 포함</th><th>기여</th></tr></thead><tbody>{Object.entries(d.condition_evaluations||{}).map(([c,v])=><tr key={c}><td>{c}</td><td>{String((v as Row).allocation_evaluable)}</td><td>{String((v as Row).included_in_score)}</td><td>{(v as Row).score_contribution??'보류'}</td></tr>)}</tbody></table></div></details>)}
          <PageStatus page={details} title="기여"/>
          {evidence.data?.records.map((e,i)=><details key={i} className="text-xs py-1"><summary>{e.source_type} · {e.kinase||e.title||e.evidence_id} · {(e.evidence_roles||[]).join(', ')}</summary>
            <p>범위 {e.binding_scope||e.evidence_scope||'candidate'} · claim support {e.claim_support_status||'별도 평가 필요'} · {e.relationship||''}</p>
            {e.quote&&<blockquote className="border-l pl-2 my-2">{e.quote}</blockquote>}
            <p>출처 {(e.source_ids||[]).join(', ')} {e.pmid&&<a className="underline" href={`https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(e.pmid)}/`} target="_blank" rel="noreferrer">PMID {e.pmid}</a>} · {e.doi&&<a className="underline ml-2" href={`https://doi.org/${encodeURIComponent(e.doi)}`} target="_blank" rel="noreferrer">DOI {e.doi}</a>} · {e.access_scope||''}</p>
            <p className="break-all">{e.source_sha256} · span {e.source_offset??'미기록'} · {e.source_faithfulness_status||''}</p>
            {(e.condition_differences||[]).map((s:string,j:number)=><p key={j}>{s}</p>)}</details>)}
          <PageStatus page={evidence} title="근거"/>
          {claims.data?.records.map((c,i)=><p className="text-xs py-1" key={i}>보고서 {c.section} 문단 {c.paragraph_index??c.paragraph_id??'미기록'} · {c.retained?'사용':'미사용/보류'} · {c.release_status} · 근거 {(c.evidence_ids||[]).join(', ')} · {(c.reason_codes||[]).join(', ')}</p>)}
          <PageStatus page={claims} title="보고서 주장"/>
        </div>}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>근거 수집·검증·미매핑 반응</CardTitle></CardHeader><CardContent className="text-sm space-y-2">
        {sources.data?.records.map(s=><p key={s.source_run_id||s.source}>{s.source}: {s.status} {s.reason||''}</p>)}
        <PageStatus page={sources} title="근거 수집"/>
        {validations.data?.records.map(v=><p key={v.name}>{v.name}: {v.evaluation_status} · {v.method} · {v.unit} · {v.reason||''}</p>)}
        <PageStatus page={validations} title="검증"/>
        <p>Wave 군집: 평가 {bundle.data.wave_scope?.all_evaluated??'미집계'} · retained {bundle.data.wave_scope?.retained??'미집계'} · 후속 계산 {bundle.data.wave_scope?.downstream_wave_ids?.length??'미집계'}. 입력 단위는 precursor이며 complete-case fitting 범위입니다.</p>
        <p>Cross-layer 쌍: 평가 {bundle.data.wave_scope?.cross_layer?.evaluated_pair_count??'미집계'} · retained {bundle.data.wave_scope?.cross_layer?.retained_edge_count??'미집계'}. 후속 후보 정책을 전체 관측 수로 해석하지 않습니다.</p>
        {unmapped.data?.records.map(m=><details key={m.module_id}><summary>미매핑 시간 모듈 · {m.members.length} precursor · {m.membership_scope}</summary><p>새 pathway 발견을 뜻하지 않습니다.</p><Button size="sm" variant="outline" onClick={()=>{setModuleId(m.module_id);setPathway('');setKinase('');setMode('inventory');}}>모든 회원 관측 보기</Button></details>)}
        <PageStatus page={unmapped} title="미매핑 모듈"/>
        <p>보고서: {bundle.data.components.report.status} · 문헌: {bundle.data.components.annotation.status}</p>
        {comparison.data?.records.map(m=><div key={m.model_id}><p>{m.model_id}: {m.status} · {m.reason||''} · 비교 결과 {m.result_record_count}건 · 기본 모델 승격 없음</p><p className="text-xs">입력: {m.input_unit||m.track||'해당 모델 원장 참조'} · 통계 단위: {m.statistical_unit||'개별 결과 참조'}</p><Button size="sm" variant="outline" onClick={()=>setModelId(m.model_id)}>{m.model_id} 결과 보기</Button> <Button size="sm" variant="outline" onClick={()=>api.downloadFile(`${base}/artifacts/model_comparisons`,'model-comparisons.json')}>비교 원장</Button></div>)}
        <PageStatus page={comparison} title="비교 모델"/>
        {modelId&&<div data-testid="comparison-results"><p>선택 비교: {modelId}</p><p className="text-xs">방법마다 값의 의미가 다릅니다. score는 정답 확률이 아니며, 미평가는 0이 아닙니다.</p>
          {modelResults.data?.records.map((r,i)=><details key={`${r.kinase||r.feature_id}:${r.condition||i}`}><summary>{r.kinase||r.feature_id} · {r.condition||'전체 시간'} · {r.evaluation_status||'조건별 결과'} · {r.reason||''}</summary>
            <p>Score {r.score??'—'} · 효과 {r.effect??r.model_conditional_effect??'—'} · 시간 기울기 {r.slope_per_minute??'—'}</p>
            <p>p {r.p_value??'—'} · q {r.q_value??'—'} · 기질/배경 group {r.substrate_groups??'—'}/{r.background_groups??'—'}</p>
            <p>사용 시간 {(r.used_conditions||[]).join(', ')||'모델 원장 참조'} · 결측 {(r.missing_conditions||[]).join(', ')||'없음 또는 미기록'}</p>
          </details>)}<PageStatus page={modelResults} title="모델 결과"/>
        </div>}
        {hypotheses.data?.records.map(h=><details key={h.packet_id}><summary>기전 후보: {h.observation?.kinase||'미분해'} → {h.observation?.wave_id} → {h.observation?.target_gene}</summary><p>관측 가설 · 인과 검증 {h.causality_status} · signed network 검증 {h.signed_network_validation}</p><p>반증/부족 근거: {(h.counterevidence||[]).join(', ')}</p><p>{h.computation_scope}</p></details>)}
        <PageStatus page={hypotheses} title="기전 가설"/>
        {suggestions.data?.records.map(s=><details key={s.suggestion_id}><summary>후속 실험 제안: {s.candidate} · 경쟁 가설 쌍 {s.pair_count}</summary><p>선택적 개입과 target engagement 확인 · 실제 수행되지 않은 조건부 제안입니다.</p><p>readout: {s.readout}</p><p>가정: {(s.assumptions||[]).join('; ')}</p><p>한계: {(s.limitations||[]).join('; ')} · 비용/실행 가능성 미평가</p></details>)}
        <PageStatus page={suggestions} title="실험 제안"/>
        <p>추가 모델·기전 가설·독립 연구 검증은 이 run에서 수행되지 않았으면 미수행입니다.</p>
        <Button variant="outline" onClick={()=>api.downloadFile(`${base}/inventory-export`,'evidence-inventory.jsonl')}>전체 evidence inventory 내보내기</Button>
      </CardContent></Card>
    </>}
  </div>;
}
