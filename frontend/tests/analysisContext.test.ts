import test from 'node:test';
import assert from 'node:assert/strict';
import { designSamples, designErrors, mergeAnalysisContext, withPersistedExportMode } from '../src/lib/analysisContext.ts';

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
  assert.equal(saved.quantitation_export_mode, 'astra_analysis.v4');
  assert.equal(saved.normalization_policy, 'already_normalized.v1');
  assert.equal(saved.treatment, 'insulin');
  const legacy = withPersistedExportMode({ quantitation_export_mode: 'legacy_only.v1', normalization_policy: 'legacy_median.v1' });
  assert.equal(legacy.quantitation_export_mode, 'legacy_only.v1');
  assert.equal(legacy.normalization_policy, 'legacy_median.v1');
  const recorded = withPersistedExportMode({ quantitation_export_mode: 'enrichment_free_timecourse.v3', normalization_policy: 'already_normalized.v1' });
  assert.equal(recorded.quantitation_export_mode, 'enrichment_free_timecourse.v3');
});
