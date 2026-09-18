import {useState} from 'react';
import {api} from '../lib/api';

export function AnalysisJobStatus({job,onRetry}:{job:any;onRetry:()=>void}) {
 const [message,setMessage]=useState('');
 if(!job?.job_id)return null;
 const active=['queued','running'].includes(job.execution_status);
 const act=async(action:string)=>{try{const result=await api.post<any>(`${job.status_url}/${action}`,{});setMessage(action==='cancel'?'취소 요청됨. 실제 worker 종료 전에는 계산 자원을 재할당하지 않습니다.':result.recovery);if(action==='retry'&&result.recovery==='requeued')onRetry();}catch(e){setMessage(String(e));}};
 return <div role="status" className="text-xs border rounded p-2 space-y-1">
   <p>분석 작업 {job.execution_status} · 평가 {job.evaluation_status} · 복구 {job.recovery_count??0}/3</p>
   {Object.entries(job.stage_status||{}).map(([name,state])=><span className="mr-3" key={name}>{name}: {(state as any).execution_status}</span>)}
   {job.failure_reason&&<p>{job.failure_reason}</p>}
   {active&&<button onClick={()=>act('cancel')}>분석 취소 요청</button>}
   {['failed','timed_out'].includes(job.execution_status)&&<button onClick={()=>act('retry')}>같은 입력으로 완료 stage 재사용·재시도</button>}
   {message&&<p>{message}</p>}
 </div>;
}
