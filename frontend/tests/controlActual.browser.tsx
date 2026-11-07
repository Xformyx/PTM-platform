import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import StudyInputFields from '../src/components/StudyInputFields';
import SampleDesignFields from '../src/components/SampleDesignFields';
import RerunOptionsModal from '../src/components/RerunOptionsModal';
import {designSamples, resolveSubmission, type AnalysisContext} from '../src/lib/analysisContext';
import {api} from '../src/lib/api';
import '../src/index.css';

// Local validation shell around unchanged production components and real HTTP
// save/resolve routes. No scientific matching, fake API, or automatic execution.
function ActualInput() {
  const [order, setOrder] = useState<any>();
  const [context, setContext] = useState<AnalysisContext>({});
  const [rerun, setRerun] = useState(false);
  const [state, setState] = useState('loading');
  const id = new URLSearchParams(location.search).get('order') || '1';
  const load = async () => {
    const row = await api.get<any>(`/orders/${id}`);
    if (row.order_code !== 'C05A_ACTUAL') throw new Error('Only the dedicated C05A validation Order is allowed');
    setOrder(row); setContext(row.analysis_context); setState('restored');
  };
  useEffect(() => { load().catch(e => setState(String(e))); }, []);
  if (!order) return <p role="status">{state}</p>;
  const rows = designSamples(order.sample_config);
  const save = async (value: AnalysisContext) => {
    const resolved = await resolveSubmission(value, rows, order.species, order.ptm_type, body => api.post('/orders/resolve-design', body));
    await api.patch(`/orders/${id}`, {analysis_context: resolved});
    await load(); setState('saved');
  };
  return <main className="mx-auto max-w-5xl space-y-4 p-6">
    <h1>C05-A 실제 저장 입력 · 격리 로컬 검증</h1>
    <p role="status" aria-label="Validation state">{state}</p>
    <StudyInputFields context={context} onChange={setContext} samples={rows} species={order.species} ptmType={order.ptm_type}/>
    <SampleDesignFields context={context} onChange={setContext} samples={rows} species={order.species} ptmType={order.ptm_type}/>
    <button onClick={() => save(context).catch(e => setState(String(e)))}>Save actual draft</button>
    <button onClick={() => load().catch(e => setState(String(e)))}>Reload persisted order</button>
    <button onClick={() => setRerun(true)}>Open saved Astra summary</button>
    <RerunOptionsModal open={rerun} onOpenChange={setRerun} order={order} llmModels={[]} defaultLlmModel=""
      onConfirm={async value => {await save(value.analysis_context);setRerun(false);}}/>
    <pre aria-label="Persisted order">{JSON.stringify(order)}</pre>
    <pre aria-label="Source context">{JSON.stringify(context)}</pre>
  </main>;
}
if (location.hostname !== '127.0.0.1') throw new Error('C05A validation is localhost only');
createRoot(document.getElementById('root')!).render(<ActualInput/>);
