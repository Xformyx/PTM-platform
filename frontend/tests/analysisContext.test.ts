import test from 'node:test';
import assert from 'node:assert/strict';
import { BIOLOGICAL_DESIGN, studyFieldLabel, newExperimentContext, designSamples, designErrors, mergeAnalysisContext, withPersistedExportMode, persistedLiteratureSelection, resolveSubmission } from '../src/lib/analysisContext.ts';

test('rerun keeps empty, explicit and all-active literature selections distinct', () => {
  for (const ids of [[], [7], null, undefined]) {
    const state = persistedLiteratureSelection(ids);
    const payload = state.useAllCollections ? null : state.selectedCollectionIds;
    assert.deepEqual(payload, ids ?? null);
    if (Array.isArray(ids)) assert.notEqual(state.selectedCollectionIds, ids);
  }
});

test('new planned default is distinct from actual Rep IDs and never added on rerun', () => {
  const samples=[{sample_id:'a',condition:'Control',replicate:1},{sample_id:'b',condition:'Control',replicate:2}];
  assert.deepEqual(newExperimentContext().replication_plan,{default_replicates_per_condition:3,source:'new_experiment_default'});
  for(const count of [2,4]){
    const existing={replication_plan:{default_replicates_per_condition:count,source:'user_input'},legacy_samples:samples};
    assert.deepEqual(newExperimentContext(existing).replication_plan,existing.replication_plan);
    assert.deepEqual(withPersistedExportMode(existing).replication_plan,existing.replication_plan);
    assert.deepEqual(newExperimentContext(existing).legacy_samples,samples);
  }
  assert.equal(newExperimentContext({replication_plan:null}).replication_plan,null);
  assert.equal(withPersistedExportMode({legacy_samples:samples}).replication_plan,undefined);
  assert.deepEqual(designSamples(samples).map(row=>row.replicate),[1,2]);
});

test('Biological Design keeps the compatibility key and exact content', () => {
  const original='  모델 α\n반복 설계와 분석 목적  ';
  const saved=withPersistedExportMode(mergeAnalysisContext({}, {biological_question:original}));
  assert.equal(BIOLOGICAL_DESIGN.label,'Biological Design');
  assert.equal(studyFieldLabel('biological_question'),'Biological Design');
  assert.equal(studyFieldLabel('research_questions'),'research questions');
  assert.equal(saved.biological_question,original);
  assert.equal(saved.biological_design,undefined);
});

test('copy and rerun text edits retain complete structured context', () => {
  const context = { sample_manifest: { samples: [{ sample_id: 'c', condition: 'Control', biological_unit: 'material' }] },
    secondary_sample_manifest: { samples: [] }, normalization_policy: 'already_normalized.v1', custom: { a: 1 } };
  const saved = mergeAnalysisContext(context, { treatment: 'Insulin' });
  assert.deepEqual(saved.sample_manifest, context.sample_manifest);
  assert.deepEqual(saved.secondary_sample_manifest, context.secondary_sample_manifest);
  assert.equal(saved.normalization_policy, 'already_normalized.v1');
  assert.deepEqual(saved.custom, { a: 1 });
  assert.equal(mergeAnalysisContext(saved, { sample_manifest: null }).sample_manifest, null);
});

test('filenames establish condition matching but never biological replication', () => {
  const samples = designSamples([{ file_name: 'rep1.mzML', group: 'Control', condition: 'con', replicate: 1 },
    { file_name: 'rep2.mzML', group: 'Treatment', condition: '5min_2', replicate: 2 }]);
  assert.deepEqual(samples.map(({sample_id,condition,replicate})=>({sample_id,condition,replicate})), [{ sample_id: 'rep1.mzML', condition: 'Control',replicate:1 }, { sample_id: 'rep2.mzML', condition: '5min',replicate:2 }]);
  assert.equal(samples[1].source_condition,'5min_2');
  assert.deepEqual(designErrors({}, samples), []);
  assert.equal(designErrors({ sample_manifest: { samples: samples.map(s => ({ ...s, biological_unit: '' })) } }, samples).length, 1);
});

test('a missing analysis purpose is stored as Astra, and a saved purpose is kept', () => {
  const saved = withPersistedExportMode({ cell_type: 'hepatocyte', treatment: 'insulin' });
  assert.equal(saved.quantitation_export_mode, 'astra_analysis.v5');
  assert.equal(saved.normalization_policy, 'already_normalized.v1');
  assert.equal(saved.treatment, 'insulin');
  const legacy = withPersistedExportMode({ quantitation_export_mode: 'legacy_only.v1', normalization_policy: 'legacy_median.v1' });
  assert.equal(legacy.quantitation_export_mode, 'legacy_only.v1');
  assert.equal(legacy.normalization_policy, 'legacy_median.v1');
  const recorded = withPersistedExportMode({ quantitation_export_mode: 'enrichment_free_timecourse.v3', normalization_policy: 'already_normalized.v1' });
  assert.equal(recorded.quantitation_export_mode, 'enrichment_free_timecourse.v3');
});

test('v4 reruns select current Astra without dropping design or science inputs', () => {
  const old = { quantitation_export_mode: 'astra_analysis.v4', normalization_policy: 'legacy_median.v1',
    study_design: { injections: [{ injection_id: 'c' }] }, science: { diann_version: '2.7.0', experimental_enabled: false } };
  const next = withPersistedExportMode(old);
  assert.equal(next.quantitation_export_mode, 'astra_analysis.v5');
  assert.equal(old.quantitation_export_mode, 'astra_analysis.v4');
  assert.equal(next.normalization_policy, old.normalization_policy);
  assert.deepEqual(next.study_design, old.study_design);
  assert.deepEqual(next.science, old.science);
});

test('submission awaits the current source instead of a previous debounced preview', async () => {
  const context={quantitation_export_mode:'astra_analysis.v5',time_points:'0,45min',study_design:{conditions:[{label:'30min'}]}};
  const samples=[{sample_id:'f',condition:'45min'}];
  const updated={...context,study_design:{conditions:[{label:'45min'}]}};
  let finish:(response:{analysis_context:typeof updated})=>void=()=>{};
  const saved=resolveSubmission(context,samples,'human','phosphorylation',body=>{
    assert.deepEqual(body,{analysis_context:context,sample_config:samples,species:'human',ptm_type:'phosphorylation'});
    return new Promise(resolve=>{finish=resolve;});
  });
  finish({analysis_context:updated});
  assert.deepEqual(await saved,updated);
  const legacy={quantitation_export_mode:'legacy_only.v1'};
  assert.equal(await resolveSubmission(legacy,samples,'human','phosphorylation',()=>{throw new Error('Legacy must not resolve here');}),legacy);
});

test('rerun restores recorded-only metadata without replacing explicit source values', () => {
  const context={quantitation_export_mode:'astra_analysis.v5',cell_type:'current cells',study_design:{study:{original_context:{cell_type:'recorded cells',treatment:'recorded treatment'},design_axis:'cross_sectional',acquisition:{instrument:'recorded instrument'}}}};
  const restored=withPersistedExportMode(context);
  assert.equal(restored.cell_type,'current cells');
  assert.equal(restored.treatment,'recorded treatment');
  assert.equal(restored.design_axis,'cross_sectional');
  assert.deepEqual(restored.acquisition,{instrument:'recorded instrument'});
  assert.equal(withPersistedExportMode({...context,treatment:null}).treatment,null);
});
