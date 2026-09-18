import {api} from "./api";

export async function requestAnalysis<T>(path: string, body: unknown, onStatus?:(status:any)=>void, isCurrent:()=>boolean=()=>true): Promise<T> {
  let response = await api.post<any>(path, body);
  if (!response.job_id) return response as T;
  onStatus?.(response);
  while (response.execution_status === "queued" || response.execution_status === "running") {
    await new Promise(resolve => setTimeout(resolve, 1500));
    if(!isCurrent())throw new Error('View detached; durable analysis continues');
    response = await api.get<any>(response.status_url);
    onStatus?.(response);
  }
  if (response.execution_status !== "completed") throw new Error(`Analysis ${response.execution_status}: ${response.failure_reason || "see job status"}`);
  return api.get<T>(response.result_url);
}
