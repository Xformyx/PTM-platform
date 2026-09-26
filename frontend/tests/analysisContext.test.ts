import test from 'node:test';
import assert from 'node:assert/strict';
import { designSamples, designErrors, mergeAnalysisContext } from '../src/lib/analysisContext.ts';

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
  assert.deepEqual(samples, [{ sample_id: 'rep1.mzML', condition: 'Control' }, { sample_id: 'rep2.mzML', condition: '5min' }]);
  assert.deepEqual(designErrors({}, samples), []);
  assert.equal(designErrors({ sample_manifest: { samples: samples.map(s => ({ ...s, biological_unit: '' })) } }, samples).length, 1);
});
