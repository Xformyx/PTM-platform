import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import SampleDesignFields from '../src/components/SampleDesignFields';
import StudyInputFields from '../src/components/StudyInputFields';
import RerunOptionsModal from '../src/components/RerunOptionsModal';
import type {AnalysisContext} from '../src/lib/analysisContext';
import {designSamples, resolveSubmission} from '../src/lib/analysisContext';
import {api} from '../src/lib/api';
import '../src/index.css';

const samples=designSamples([{sample_id:'c1',condition:'Control',group:'Control',replicate:1},{sample_id:'c2',condition:'Control',group:'Control',replicate:2},
  {sample_id:'t1',condition:'90min',group:'Treatment',replicate:1},{sample_id:'t2',condition:'90min',group:'Treatment',replicate:2}]);
const initial={quantitation_export_mode:'astra_analysis.v5',cell_type:'recorded cells',treatment:'compound',biological_question:'recorded question',special_conditions:'recorded conditions',time_points:'0,90min',science:{diann_version:'2.7.0',reference:{reference_id:'recorded-reference'}}};
function Fixture(){
  const [context,setContext]=useState<AnalysisContext>(initial);
  const [rows,setRows]=useState(samples);
  const [source,setSource]=useState(false);
  const [rerun,setRerun]=useState(false);
  const [payload,setPayload]=useState<unknown>(null);
  const [order,setOrder]=useState({id:1,order_code:'fixture',species:'human',ptm_type:'phosphorylation',analysis_context:context,sample_config:rows,rag_collections:[],report_options:{research_questions:['saved writing intent']}});
  return <main className="mx-auto max-w-4xl space-y-4 p-6">
    <SampleDesignFields context={context} onChange={setContext} samples={rows} species="human" ptmType="phosphorylation" onEdit={()=>setSource(true)}/>
    {source&&<section><label>Cell Type<input aria-label="Original Cell Type" value={String(context.cell_type??'')} onChange={e=>setContext({...context,cell_type:e.target.value})}/></label>
      <label>Time Points<input aria-label="Original Time Points" value={String(context.time_points??'')} onChange={e=>setContext({...context,time_points:e.target.value})}/></label>
      <StudyInputFields context={context} onChange={setContext} samples={rows} onSamplesChange={setRows} species="human" ptmType="phosphorylation"/>
    </section>}
    <button onClick={async()=>{const next=await resolveSubmission(context,rows,'human','phosphorylation',body=>api.post('/orders/resolve-design',body));setContext(next);setPayload(next);}}>Save draft</button>
    <button onClick={()=>{setOrder({...order,analysis_context:context,sample_config:rows});setRerun(true);}}>Open rerun</button>
    <button onClick={()=>setContext({...context,quantitation_export_mode:'legacy_only.v1'})}>Legacy fixture</button>
    <RerunOptionsModal open={rerun} onOpenChange={setRerun} order={order} llmModels={[]} defaultLlmModel="" onConfirm={value=>{setPayload(value);setRerun(false);}}/>
    <pre aria-label="Saved payload">{JSON.stringify(payload)}</pre>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
