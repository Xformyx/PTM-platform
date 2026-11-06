import React,{useState,useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import StudyInputFields from '../src/components/StudyInputFields';
import SampleDesignFields from '../src/components/SampleDesignFields';
import RerunOptionsModal from '../src/components/RerunOptionsModal';
import {designSamples,resolveSubmission,type AnalysisContext} from '../src/lib/analysisContext';
import {api} from '../src/lib/api';
import '../src/index.css';

const initialRows=designSamples(['Control 0min','Control 30min','Control 60min','Drug 0.5h','Drug 60min'].flatMap((condition,i)=>[1,2,3].map(replicate=>({sample_id:`f${i}_${replicate}`,condition,group:i<3?'Control':'Treatment',replicate,control_family:'vehicle'}))));
const models:[]=[];
function Fixture(){
  const [context,setContext]=useState<AnalysisContext>({quantitation_export_mode:'astra_analysis.v6',biological_question:'원본 설계 설명',replication_declaration:'independent_biological_units',pairing_policy:'unpaired'});
  const [rows,setRows]=useState(initialRows);const [initial,setInitial]=useState<AnalysisContext>();
  const [payload,setPayload]=useState<unknown>(null);const [rerun,setRerun]=useState(false);
  const [order,setOrder]=useState({id:1,order_code:'synthetic_control',status:'completed',species:'human',ptm_type:'phosphorylation',analysis_context:context,sample_config:rows,rag_collections:[],report_options:{research_questions:['별도 연구 질문']}});
  useEffect(()=>{if(!initial&&context.study_design)setInitial(context);},[context,initial]);
  return <main className="mx-auto max-w-5xl space-y-4 p-6">
    <StudyInputFields {...{context,rows}} onChange={setContext} samples={rows} onSamplesChange={setRows} species="human" ptmType="phosphorylation" publishedContext={initial}/>
    <SampleDesignFields context={context} onChange={setContext} samples={rows} species="human" ptmType="phosphorylation"/>
    <button onClick={async()=>{const saved=await resolveSubmission(context,rows,'human','phosphorylation',body=>api.post('/orders/resolve-design',body));setContext(saved);setPayload(saved);}}>Save draft</button>
    <button onClick={()=>{setOrder({...order,analysis_context:context,sample_config:rows});setRerun(true);}}>Open rerun</button>
    <button onClick={()=>setRows(rows.filter(r=>r.source_condition!=='Control 30min'))}>Remove 30min Control</button>
    <button onClick={()=>setRows(initialRows)}>Restore samples</button>
    <RerunOptionsModal open={rerun} onOpenChange={setRerun} order={order} llmModels={models} defaultLlmModel="" onConfirm={value=>{setPayload(value);setRerun(false);}}/>
    <pre aria-label="Source context">{JSON.stringify(context)}</pre><pre aria-label="Original context">{JSON.stringify(initial)}</pre><pre aria-label="Saved payload">{JSON.stringify(payload)}</pre>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
