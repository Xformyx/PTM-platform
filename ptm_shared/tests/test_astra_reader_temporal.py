"""Saved-row joins/serialization only: these tests never run a scientific engine."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from ptm_shared.tests.test_astra_card_inputs import small
from ptm_shared.astra_card_inputs import project_card_inputs, encode
from ptm_shared.astra_reader import build_reader_tables, write_reader
from ptm_shared import astra_reader_temporal as temporal


@pytest.fixture
def saved(small):
    tables, inputs, design = small
    comp = tables['quant/comparisons']
    design['contrasts'] = comp[['contrast_id', 'target_condition_id', 'reference_condition_id', 'pairing']].drop_duplicates().to_dict('records')
    tables['quant/summary']['parent_pg'] = tables['quant/summary'].form_id
    tables.update(project_card_inputs(tables, inputs, design, {}))
    tables.update(build_reader_tables(tables, design))
    series, features, intervals = [], [], []
    for ref in ['base', 'other_base']:
        sid = 'series_' + ref
        series.append({'series_id': sid, 'arm_id': 'arm', 'reference_condition_id': ref,
                       'pairing': 'unpaired', 'contrast_ids': ';'.join(t + '_' + ref for t in ['one', 'gap', 'last'])})
        for form in tables['quant/summary'].form_id:
            features.append({'feature_id': 'feature_' + form + ref, 'entity_id': form, 'series_id': sid,
                'arm_id': 'arm', 'reference_condition_id': ref, 'track': 'A',
                'times_minutes': '[30,60,120]', 'values': '[1,null,1]', 'observed_mask': '[true,false,true]',
                'observed_points': 2, 'observed_peak_time_min': 30, 'signed_peak': 1,
                'onset_lower_min': None, 'onset_upper_min': 30, 'onset_left_censored': True,
                'recovery_lower_min': None, 'recovery_upper_min': None, 'right_censored': True,
                'pattern': 'saved_pattern', 'threshold': .5, 'threshold_sensitive': False,
                'loto_pattern_stability': .5, 'adjacent_trapezoid_auc': None,
                'auc_supported_duration_min': 0, 'gap_intervals': 2})
            intervals.append({'interval_id': 'interval_' + form + ref, 'form_id': form, 'series_id': sid,
                'arm_id': 'arm', 'reference_condition_id': 'one', 'target_condition_id': 'gap',
                'from_min': 30, 'to_min': 60, 'U_joint': None, 'P_joint': None, 'A': None,
                'reference_run_ids': 'one-0;one-1', 'target_run_ids': '', 'reference_joint_n': 2, 'target_joint_n': 0,
                'status': 'parent_or_joint_observations_unavailable'})
    tables[temporal.SERIES] = pd.DataFrame(series)
    tables[temporal.PTM] = pd.DataFrame(features)
    tables[temporal.INTERVAL] = pd.DataFrame(intervals)
    members, profiles, fixed, anchors, cowave = [], [], [], [], []
    for track in ['curated_A', 'motif_A']:
        for t, tm in [('one', 30), ('gap', 60), ('last', 120)]:
            cid = t + '_base'
            if t != 'gap':
                members.append({'contribution_id': track + cid, 'candidate_id': 'kinase', 'contrast_id': cid,
                                'track': track, 'form_ids': 'single', 'site_key': 'site', 'measurement_group_id': 'group_single', 'value': 1.})
            profiles.append({'candidate_id': 'kinase', 'contrast_id': cid, 'track': track,
                             'arm_id': 'arm', 'reference_condition_id': 'base', 'time_min': tm,
                             'activity_magnitude': None if t == 'gap' else -1. if track == 'motif_A' else 1., 'coverage_adequate': False})
            fixed.append({'candidate_id': 'kinase', 'series_id': 'series_base', 'contrast_id': cid, 'track': track,
                          'fixed_common_score': None, 'fixed_common_sites': 0, 'available_sites': 0 if t == 'gap' else 1,
                          'entered_sites': 0 if t == 'gap' else 1, 'departed_sites': 1 if t == 'gap' else 0, 'membership_turnover': 1.})
        shared = {'candidate_id': 'kinase', 'series_id': 'series_base', 'track': track, 'site_key': 'site',
                  'signed_correlation': -.3, 'interval_concordance': .25, 'support_status': 'computed',
                  'independent_validation': False, 'details': '{"metrics":{"interval_direction_support":[]}}'}
        anchors.append({**shared, 'target_excluded': True})
        for kind in ['gene', 'measurement_group']:
            cowave.append({**shared, 'cowave_id': 'cowave_' + kind + track, 'excluded_kind': kind,
                           'excluded_ids': 'recorded_' + kind, 'remaining_site_keys': 'remaining1;remaining2'})
    for name, values in [(temporal.CONTRIBUTION, members), (temporal.PROFILE, profiles), (temporal.FIXED, fixed),
                         (temporal.ANCHOR, anchors), (temporal.COWAVE, cowave)]: tables[name] = pd.DataFrame(values)
    return tables


def packet(tables):
    return json.loads(tables['reader/packet'].iloc[0].packet_json)


def test_saved_values_na_scope_links_questions_and_writer(saved, tmp_path):
    before = {k: v.copy(deep=True) for k, v in saved.items()}
    original = packet(saved)
    (tmp_path/'reader').mkdir()
    # Hard guards: nothing in this boundary may calculate or retrieve.
    with patch('ptm_shared.astra_package.compute_science', side_effect=AssertionError('calculation')), \
         patch('ptm_shared.astra_literature.collect', side_effect=AssertionError('retrieval')):
        temporal.attach_temporal(saved)
        temporal.validate_temporal(saved)
        write_reader(tmp_path, saved)
    p = packet(saved); data = p['temporal_evidence']
    assert data['coverage'] == {'linked': 6}
    assert p['reader_cards'] == original['reader_cards']
    assert p['original_questions'] == original['original_questions']
    for k in before:
        if k != 'reader/packet': pd.testing.assert_frame_equal(before[k], saved[k])
    for f in data['findings']:
        assert f['ordered_contrast_ids'] == [t + '_' + f['scope']['reference_condition_id'] for t in ['one', 'gap', 'last']]
        assert f['features'][0]['row']['values'] == '[1,null,1]'
        assert f['features'][0]['row']['observed_mask'] == '[true,false,true]'
        assert f['intervals'][0]['row']['A'] is None
        assert f['intervals'][0]['row']['reference_run_ids'] == 'one-0;one-1'
        if f['form_id'] == 'single' and f['scope']['reference_condition_id'] == 'base':
            assert {c['track'] for c in f['candidates']} == {'curated_A', 'motif_A'}
            for c in f['candidates']:
                assert c['profiles'][1]['row']['activity_magnitude'] is None
                assert c['profiles'][0]['row']['activity_magnitude'] == (-1. if c['track'] == 'motif_A' else 1.)
                assert all(e['row']['fixed_common_score'] is None and e['unavailable_reason'] == 'no_common_sites' for e in c['fixed_membership'])
                assert len(c['exclusions']) == 3
        else: assert not f['candidates']  # Same label in mouse and another reference is not a join key.
    for q in p['research_question_evidence_map']['questions']:
        assert q['temporal_evidence']['evidence']
    assert 'feature_id' in p['authoring_rules']['temporal_evidence']['required_evidence_anchor']
    assert 'TEMPORAL_EVIDENCE.md' in (tmp_path/'reader/READ_ME.md').read_text()
    assert '\n\n| ---' not in (tmp_path/'reader/TEMPORAL_EVIDENCE.md').read_text()
    links = pd.read_csv(tmp_path/'reader/temporal_links.csv')
    assert not links.duplicated(['finding_id','source_table','source_key_json']).any()
    # Input order is immaterial; IDs and scopes, rather than first row, drive joins.
    shuffled = {k: (v if k.startswith('reader/') else v.sample(frac=1, random_state=7).reset_index(drop=True)) for k, v in before.items()}
    temporal.attach_temporal(shuffled)
    assert packet(shuffled)['temporal_evidence'] == data


def test_missing_ambiguous_duplicate_scope_and_tampering(saved):
    original = {k: v.copy(deep=True) for k, v in saved.items()}
    extra = saved[temporal.SERIES].iloc[0].copy();extra['series_id'] = 'ambiguous'
    saved[temporal.SERIES] = pd.concat([saved[temporal.SERIES], extra.to_frame().T], ignore_index=True)
    temporal.attach_temporal(saved)
    assert packet(saved)['temporal_evidence']['coverage'] == {'ambiguous': 3, 'linked': 3}
    assert all(not f['features'] for f in packet(saved)['temporal_evidence']['findings'] if f['status'] == 'ambiguous')
    saved.update(original)
    saved[temporal.PTM] = pd.concat([saved[temporal.PTM], saved[temporal.PTM].iloc[:1]])
    with pytest.raises(ValueError, match='Duplicate temporal reader source key'): temporal.attach_temporal(saved)
    saved.update(original)
    duplicate = saved[temporal.PTM].iloc[0].copy();duplicate['feature_id'] = 'another_id_same_scope'
    saved[temporal.PTM] = pd.concat([saved[temporal.PTM], duplicate.to_frame().T], ignore_index=True)
    temporal.attach_temporal(saved)
    assert packet(saved)['temporal_evidence']['coverage'] == {'ambiguous': 1, 'linked': 5}
    saved.update(original)
    saved[temporal.PTM] = saved[temporal.PTM].iloc[:0]
    temporal.attach_temporal(saved)
    assert packet(saved)['temporal_evidence']['coverage'] == {'unlinked': 6}
    saved.update(original)
    saved[temporal.PTM] = saved[temporal.PTM].copy()
    saved[temporal.PTM].loc[0, 'arm_id'] = 'wrong_arm'
    with pytest.raises(ValueError, match='scope conflict'): temporal.attach_temporal(saved)
    saved.update(original);temporal.attach_temporal(saved)
    p = packet(saved);p['temporal_evidence']['findings'][0]['features'][0]['row']['values'] = '[1,0,1]'
    saved['reader/packet'].loc[0,'packet_json'] = encode(p)
    with pytest.raises(ValueError, match='differs from saved'): temporal.validate_temporal(saved)


def test_existing_v6_reader_builder_consumes_saved_tables_without_analysis(saved):
    p = packet(saved)
    result = build_reader_tables(saved, p['canonical_study_design'])
    assert packet(result)['temporal_evidence']['coverage'] == {'linked': 6}
    assert result['reader/findings'].finding_id.tolist() == saved['reader/findings'].finding_id.tolist()


def test_nullable_boolean_csv_semantics(saved):
    saved[temporal.PTM]['parent_pattern_agreement'] = ['True', 'False', None] * 4
    saved[temporal.PTM]['normalization_pattern_agreement'] = ['False', None, 'True'] * 4
    temporal.attach_temporal(saved)
    for name in ('parent_pattern_agreement','normalization_pattern_agreement'):
        saved[temporal.PTM][name] = saved[temporal.PTM][name].map({'True':True,'False':False})
    temporal.validate_temporal(saved)


def test_immutable_revision_failure_keeps_pointer_and_source(saved, tmp_path):
    from ptm_shared.astra_reader_revision import revise_temporal
    from ptm_shared.generic_workflow import json_write
    from ptm_shared.annotation_registry import digest
    from ptm_shared.astra_package import write_tables
    source = tmp_path/'source';source.mkdir()
    (source/'reproducibility/code/ptm_shared').mkdir(parents=True)
    (source/'study').mkdir()
    dictionary = write_tables(saved, source)
    json_write(source/'reproducibility/data_dictionary.json', dictionary)
    json_write(source/'reproducibility/replay_config.json', {'engine_profile':'astra_analysis.v6'})
    json_write(source/'provenance.json', {'run_id':'old','code_sha256':{},'stage_fingerprints':{}})
    json_write(source/'study/analysis_plan.json', {'code_dependencies':{'evidence':{}}})
    (source/'START_HERE_ASTRA.md').write_text('old')
    (source/'evidence_report.html').write_text('old')
    manifest = {str(p.relative_to(source)):{'sha256':digest(p),'bytes':p.stat().st_size} for p in source.rglob('*') if p.is_file()}
    json_write(source/'manifest.json', {'files':manifest})
    output=tmp_path/'out';output.mkdir();pointer=output/'enrichment_free_current.json';pointer.write_text('previous_success')
    with patch('ptm_shared.astra_package.validate_package'), patch('ptm_shared.astra_reader_revision.read_tables',return_value=saved), \
         patch('ptm_shared.astra_reader.validate_reader'), patch('ptm_shared.astra_package.seal_archive',side_effect=RuntimeError('write failure')):
        with pytest.raises(RuntimeError,match='write failure'): revise_temporal(source,output)
    assert pointer.read_text() == 'previous_success'
    assert all(digest(source/name)==entry['sha256'] for name,entry in manifest.items())
