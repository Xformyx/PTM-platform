"""Small source-update regressions; no provider, scientific run or archive replay."""
from copy import deepcopy
import pytest

from ptm_shared.study_design import resolve_study_design, require_resolved, DesignError
from ptm_shared.study_execution import resolve_context


def inputs():
    labels = ['Control', '0.5h', '1h', '3h', '6h', '24h']
    rows = [{'sample_id': f'f{i}_{r}', 'condition': label,
             'group': 'Control' if i == 0 else 'Treatment', 'replicate': r}
            for i, label in enumerate(labels) for r in [1, 2]]
    context = {'quantitation_export_mode': 'astra_analysis.v5', 'time_points': '0,0.5,1,3,6,24h',
               'cell_type': '세포 α', 'treatment': 'compound', 'biological_question': 'response?',
               'special_conditions': 'recorded condition'}
    manifest = {'schema_version': 'sample_manifest.v1', 'pairing': 'paired',
                'conditions': [{'condition': label, 'time_minutes': minutes}
                               for label, minutes in zip(labels, [0, 30, 60, 180, 360, 1440])],
                'samples': [{**r, 'biological_unit': f'donor_{r["replicate"]}', 'technical_injection': '1'} for r in rows]}
    return context, rows, manifest


def test_manifest_added_after_unknown_preview_matches_direct_input():
    context, rows, manifest = inputs()
    preview = resolve_study_design(context, rows)
    assert preview['status'] == 'resolved' and not preview['materials']
    final = resolve_study_design({**context, 'study_design': preview, 'sample_manifest': manifest}, rows)
    direct = resolve_study_design({**context, 'sample_manifest': manifest}, rows)
    require_resolved(final)
    assert len(final['materials']) == 12
    assert {c['pairing'] for c in final['contrasts']} == {'paired'}
    for key in ['conditions', 'materials', 'injections', 'contrasts', 'arms']:
        assert final[key] == direct[key]
    assert resolve_study_design({**context, 'study_design': final, 'sample_manifest': manifest}, rows) == final


def test_condition_rename_and_removal_prune_only_automatic_design():
    context, rows, _ = inputs()
    preview = resolve_study_design(context, rows)
    changed = deepcopy(rows)
    for row in changed:
        if row['condition'] == '0.5h': row['condition'] = '0.75h'
    context['time_points'] = '0,0.75,1,3,6,24h'
    result = resolve_study_design({**context, 'study_design': preview}, changed)
    require_resolved(result)
    assert '0.5h' not in {c['label'] for c in result['conditions']}
    assert len(result['contrasts']) == 5
    retained = {i['input_column']: i['injection_id'] for i in preview['injections']}
    assert all(i['injection_id'] == retained[i['input_column']] for i in result['injections'])
    result = resolve_study_design({**context, 'study_design': result}, [r for r in changed if r['condition'] != '24h'])
    require_resolved(result)
    assert len(result['conditions']) == 5 and len(result['contrasts']) == 4


@pytest.mark.parametrize('context', [
    {'science': {'diann_version': '2.7.0'}},
    {'processing': {'software': 'DIA-NN', 'software_version': {'value': '2.7.0'}}},
    {'acquisition_metadata': {'diann_version': '2.7.0'}},
    {'science': {'diann_version': '2.7.0'}, 'processing': {'software_version': {'value': '2.7.0'}}},
])
def test_diann_single_known_value_feeds_parser_and_display(context, tmp_path):
    import pandas as pd
    from ptm_shared.diann_evidence import observations
    base, rows, _ = inputs()
    resolved = resolve_context({**base, **context}, rows)
    assert resolved['science']['diann_version'] == '2.7.0'
    assert resolved['study_design']['study']['processing']['software_version']['value'] == '2.7.0'
    assert resolve_context(resolved, rows) == resolved
    pr = pd.DataFrame([{'Precursor.Id': 'ASK2', 'Modified.Sequence': 'AS(UniMod:21)K',
                        'Protein.Group': 'P1', 'Precursor.Charge': 2, rows[0]['sample_id']: 10.0}])
    report = tmp_path/'report.tsv'
    pd.DataFrame([{**pr.iloc[0].to_dict(), 'Protein.Ids': 'P1', 'Run': rows[0]['sample_id']}]).to_csv(report, sep='\t', index=False)
    parsed, _ = observations(report, resolved['science']['diann_version'], pr, resolved['study_design'])
    assert parsed.diann_version.tolist() == [resolved['study_design']['study']['processing']['software_version']['value']]


def test_diann_conflict_and_unidentified_other_software_are_not_guessed():
    base, rows, _ = inputs()
    conflict = resolve_context({**base, 'science': {'diann_version': '2.7.0'},
        'processing': {'software': 'DIA-NN', 'software_version': {'value': '1.8.1'}}}, rows)
    with pytest.raises(DesignError, match='diann_version_conflict'):
        require_resolved(conflict['study_design'])
    for software in [None, 'Other software']:
        other = resolve_context({**base, 'processing': {'software': software, 'software_version': {'value': '2.7.0'}}}, rows)
        assert not other.get('science', {}).get('diann_version')


def test_manifest_updates_pairs_and_technical_injections_without_changing_ids():
    context, rows, manifest = inputs()
    context['sample_manifest'] = manifest
    previous = resolve_study_design(context, rows)
    manifest['pairing'] = 'unpaired'
    for row in manifest['samples']: row['technical_injection'] = 'recorded injection'
    final = resolve_study_design({**context, 'study_design': previous}, rows)
    require_resolved(final)
    assert [m['material_id'] for m in final['materials']] == [m['material_id'] for m in previous['materials']]
    assert all(m['pair_id'] is None for m in final['materials'])
    assert {c['pairing'] for c in final['contrasts']} == {'unpaired'}
    assert {i['technical_injection_id'] for i in final['injections']} == {'recorded injection'}


def test_confirmed_material_pair_time_and_custom_ids_survive_source_updates():
    context, rows, manifest = inputs()
    previous = resolve_study_design({**context, 'sample_manifest': manifest}, rows)
    protected = previous['materials'][0]
    protected.update(biological_unit_id='confirmed donor', pair_id='confirmed pair', source='user_confirmed_mapping')
    c = next(c for c in previous['conditions'] if c['label'] == '1h')
    c['time'] = {'value': 60, 'unit': 'min', 'minutes': 60, 'original': 'user value'}
    previous['injections'][0]['injection_id'] = 'confirmed-injection-id'
    for row in rows:
        if row['condition'] == '0.5h': row['condition'] = '0.75h'
    final = resolve_study_design({**context, 'time_points': '0,0.75,1,3,6,24h', 'study_design': previous}, rows)
    require_resolved(final)
    assert final['injections'][0]['injection_id'] == 'confirmed-injection-id'
    assert protected in final['materials']
    assert next(v for v in final['conditions'] if v['condition_id'] == c['condition_id'])['time'] == c['time']


def test_ambiguous_older_overrides_are_not_treated_as_generated():
    context, rows, _ = inputs()
    older = resolve_study_design(context, rows)
    for provenance in older['field_provenance'].values(): provenance.pop('resolved_value', None)
    older['injections'][0]['injection_id'] = 'old stable id'
    before = deepcopy(older)
    final = resolve_study_design({**context, 'study_design': older}, rows)
    assert older == before
    for key in ['conditions', 'injections', 'materials', 'contrasts']:
        assert final[key] == older[key]


def test_existing_time_confirmation_is_preserved_when_manifest_changes():
    context, rows, manifest = inputs()
    previous = resolve_study_design({**context, 'sample_manifest': manifest}, rows)
    condition = next(c for c in previous['conditions'] if c['label'] == '1h')
    condition['time_conflict_resolution'] = 'use_confirmed_structured'
    manifest['conditions'][2]['time_minutes'] = 75
    final = resolve_study_design({**context, 'sample_manifest': manifest, 'study_design': previous}, rows)
    assert next(c for c in final['conditions'] if c['label'] == '1h')['time']['minutes'] == 60


def test_paired_missing_mapping_stays_error_and_unknown_is_descriptive():
    context, rows, _ = inputs()
    unknown = resolve_study_design(context, rows)
    require_resolved(unknown)
    assert not unknown['materials']
    assert {c['pairing'] for c in unknown['contrasts']} == {'unknown'}
    paired = resolve_study_design({**context, 'study_design': unknown, 'pairing_policy': 'paired'}, rows)
    with pytest.raises(DesignError, match='pair_mapping_required'): require_resolved(paired)
    assert len(paired['injections']) == 12


def test_linked_version_edit_and_explicit_null_do_not_resurrect_preview():
    from ptm_shared.analysis_context import merge_analysis_context
    context, rows, manifest = inputs()
    saved = resolve_context({**context, 'science': {'diann_version': '2.7.0'}, 'sample_manifest': manifest}, rows)
    changed = resolve_context(merge_analysis_context(saved, {'science': {'diann_version': '2.6.0'}}), rows)
    assert changed['study_design']['study']['processing']['software_version']['value'] == '2.6.0'
    cleared = resolve_context(merge_analysis_context(changed, {'science': None, 'sample_manifest': None, 'cell_type': None}), rows)
    assert 'science' not in cleared
    assert not cleared['study_design']['materials']
    assert cleared['study_design']['study']['cell_type'] is None
    assert not cleared['study_design']['study']['processing'].get('software_version')
    assert merge_analysis_context(saved, {}) == saved


def test_unchanged_design_preserves_quantitative_outputs_and_cache_dependencies():
    import pandas as pd
    from test_generic_study import generic_fixture
    from ptm_shared.contrast_quantification import quantify_contrasts
    from ptm_shared.astra_plan import resolve_plan
    pr, pg, fasta, design, context, rows = generic_fixture()
    refreshed = resolve_study_design({**context, 'study_design': design}, rows, taxonomy_id=9606, species='human')
    assert refreshed == design
    before = quantify_contrasts(pr, pg, fasta, design)
    after = quantify_contrasts(pr, pg, fasta, refreshed)
    for key, table in before.items():
        if isinstance(table, pd.DataFrame): pd.testing.assert_frame_equal(table, after[key], check_exact=True)
    plan = resolve_plan({**context, 'study_design': design})
    assert plan['fingerprints'] == resolve_plan({**context, 'study_design': refreshed})['fingerprints']
    changed = resolve_study_design({**context, 'study_design': design, 'replication_declaration': 'unknown'}, rows, taxonomy_id=9606, species='human')
    assert plan['fingerprints']['quant'] != resolve_plan({**context, 'study_design': changed})['fingerprints']['quant']


def test_reference_ambiguity_and_missing_units_only_block_relevant_fields():
    rows = [{'sample_id':'c1','condition':'vehicle 0min','group':'Control'},
            {'sample_id':'c2','condition':'other 0min','group':'Control'},
            {'sample_id':'t','condition':'90min','group':'Treatment'}]
    draft = resolve_study_design({}, rows)
    assert any(i['code'] == 'reference_unresolved' for i in draft['issues'])
    reference, _, target = draft['conditions']
    draft['contrasts'] = [{'contrast_id':'explicit-contrast', 'target_condition_id':target['condition_id'],
                          'reference_condition_id':reference['condition_id'], 'pairing':'unknown','source':'user_confirmed'}]
    require_resolved(resolve_study_design({'study_design':draft}, rows))
    missing = resolve_study_design({}, [{'sample_id':'c','condition':'Control','group':'Control'},
                                       {'sample_id':'t','condition':'90','group':'Treatment'}])
    assert {i['code'] for i in missing['issues']} >= {'time_unresolved'}


def test_recorded_replay_passes_archived_design_without_live_resolution(tmp_path, monkeypatch):
    import json
    from ptm_shared import astra_package, study_design
    context, rows, _ = inputs()
    archived = resolve_study_design(context, rows)
    archived['field_provenance'] = {}  # Older archive without update tracking.
    (tmp_path/'reproducibility').mkdir(); (tmp_path/'references').mkdir()
    (tmp_path/'reproducibility/replay_config.json').write_text(json.dumps({'inputs':{},'design':archived,'context':context,'snapshot':{}}))
    (tmp_path/'references/source_pin.json').write_text('{}')
    monkeypatch.setattr(astra_package, 'validate_package', lambda directory: None)
    monkeypatch.setattr(study_design, 'resolve_study_design', lambda *a, **k: pytest.fail('Replay must not resolve a live draft'))
    class ReachedRecordedCompute(Exception): pass
    def recorded_compute(inputs, design, ctx, sources, **kwargs):
        assert design == archived and ctx == context
        raise ReachedRecordedCompute()
    monkeypatch.setattr(astra_package, 'compute_science', recorded_compute)
    with pytest.raises(ReachedRecordedCompute): astra_package.replay_package(tmp_path, tmp_path.parent/'unused-replay')
