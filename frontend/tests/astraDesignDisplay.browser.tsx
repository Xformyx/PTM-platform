import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import RerunOptionsModal from '../src/components/RerunOptionsModal';
import '../src/index.css';

const labels=['Control','0.5h','1h','3h','6h','24h'];
const samples=labels.flatMap((condition,i)=>[1,2,3].map(replicate=>({sample_id:`f${i}_${replicate}`,condition,replicate,group:i===0?'Control':'Treatment'})));
const context={quantitation_export_mode:'astra_analysis.v5',cell_type:'recorded cells',treatment:'compound',
  time_points:'0,0.5,1,3,6,24h',biological_question:'  모델 α · 처리 및 시간 계획\n반복 설계와 분석 목적 원문  '};
const models:[]=[];
function Fixture(){
  const [open,setOpen]=useState(true);
  const [payload,setPayload]=useState<unknown>(null);
  const [order]=useState({id:1,order_code:'synthetic_design_display',species:'human',ptm_type:'phosphorylation',sample_config:samples,analysis_context:context,
    rag_collections:[],report_options:{research_questions:['별도 연구 질문 그대로']}});
  return <><RerunOptionsModal open={open} onOpenChange={setOpen} order={order} llmModels={models} defaultLlmModel="" onConfirm={value=>{setPayload(value);setOpen(false);}}/>
    <pre aria-label="Saved payload">{JSON.stringify(payload)}</pre></>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
