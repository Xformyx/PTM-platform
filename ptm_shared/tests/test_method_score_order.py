"""method_scores export order follows stored minutes. It does not rescore."""
import pandas as pd
import pytest

from ptm_shared.astra_package import order_method_scores, write_tables
from ptm_shared.contrast_quantification import KEY_COLUMNS
from ptm_shared.study_design import time_value


def _comparison(contrast_id, minutes, reference='control', arm='arm', pairing='unpaired', reference_minutes=0):
    row = dict.fromkeys(KEY_COLUMNS)
    row.update(contrast_id=contrast_id, arm_id=arm, condition_id=contrast_id, target_condition_id=contrast_id,
               reference_condition_id=reference, time_min=minutes, reference_time_min=reference_minutes,
               target_label='not-a-time-key', reference_label=reference, pairing=pairing,
               comparison_interpretation='target_vs_declared_reference_condition_not_necessarily_time_zero')
    return row


def _score(contrast_id, candidate='candidate', method='PhosX_native_functions', score=1.0, version='0.23.1'):
    return {'method_result_id': f'{method}:{candidate}:{contrast_id}', 'method_id': method, 'method_version': version,
            'candidate_id': candidate, 'contrast_id': contrast_id, 'score_name': 'Activity Score', 'score': score,
            'method_p': None, 'method_q': None, 'membership_ids': contrast_id + '-member', 'status': 'stored'}


def _design(rows):
    conditions = [{'condition_id': 'control', 'arm_id': 'arm', 'label': 'Control label', 'time': {'minutes': 0}}]
    contrasts = []
    for contrast_id, minutes, reference, arm, pairing in rows:
        conditions.append({'condition_id': contrast_id, 'arm_id': arm, 'label': '180min',
                           'time': None if minutes is None else {'minutes': minutes}})
        contrasts.append({'contrast_id': contrast_id, 'target_condition_id': contrast_id,
                          'reference_condition_id': reference, 'pairing': pairing})
    return {'conditions': conditions, 'contrasts': contrasts,
            'injections': [{'injection_id': 'i', 'condition_id': 'control', 'material_id': 'm', 'input_column': 'c'}],
            'materials': [{'material_id': 'm'}]}


def test_label_and_contrast_id_do_not_set_time_order():
    comparisons = pd.DataFrame([
        _comparison('id_90', 90), _comparison('id_0', 0), _comparison('id_half', 0.5),
        _comparison('id_10', 10), _comparison('id_2', 2),
    ])
    frame = pd.DataFrame([_score(cid, score=index) for index, cid in enumerate(['id_90', 'id_0', 'id_half', 'id_10', 'id_2'])])
    original = frame.copy()
    ordered, audit = order_method_scores(frame, comparisons=comparisons)
    assert ordered.contrast_id.tolist() == ['id_0', 'id_half', 'id_2', 'id_10', 'id_90']
    assert ordered.score.tolist() == [1, 2, 4, 3, 0]
    assert 'time_min' not in ordered.columns
    assert list(ordered.columns) == list(frame.columns)
    pd.testing.assert_frame_equal(frame, original)
    assert audit['time_order_complete'] is True
    again, _ = order_method_scores(ordered, comparisons=comparisons)
    assert again.method_result_id.tolist() == ordered.method_result_id.tolist()


def test_canonical_minutes_from_existing_time_value_not_raw_unit_numbers():
    converted = [time_value(30, 's'), time_value(2, 'h'), time_value(1, 'd')]
    assert [item['minutes'] for item in converted] == [0.5, 120, 1440]
    rows = [('late', 1440, 'control', 'arm', 'unpaired'), ('early', 0.5, 'control', 'arm', 'unpaired'),
            ('middle', 120, 'control', 'arm', 'unpaired')]
    frame = pd.DataFrame([_score(cid) for cid, *_ in rows])
    ordered, _ = order_method_scores(frame.sample(frac=1, random_state=1), design=_design(rows))
    assert ordered.contrast_id.tolist() == ['early', 'middle', 'late']


def test_same_time_scopes_stay_separate_and_ties_use_ids():
    comparisons = pd.DataFrame([
        _comparison('contrast_b', 10, reference='ref_b', arm='arm_b', pairing='paired'),
        _comparison('contrast_a', 10, reference='ref_a', arm='arm_a', pairing='unpaired'),
        _comparison('contrast_c', 10, reference='ref_a', arm='arm_a', pairing='unpaired'),
    ])
    frame = pd.DataFrame([
        _score('contrast_b', score=2), _score('contrast_c', score=3), _score('contrast_a', score=1),
    ])
    ordered, _ = order_method_scores(frame, comparisons=comparisons)
    assert ordered.contrast_id.tolist() == ['contrast_a', 'contrast_c', 'contrast_b']
    assert ordered.score.tolist() == [1, 3, 2]
    assert len(ordered) == 3


def test_unresolved_time_stays_last_and_is_not_called_complete():
    comparisons = pd.DataFrame([_comparison('known', 5), _comparison('missing', None), _comparison('earlier', 1)])
    frame = pd.DataFrame([_score('missing', score=9), _score('known', score=8), _score('earlier', score=7)])
    ordered, audit = order_method_scores(frame, comparisons=comparisons)
    assert ordered.contrast_id.tolist() == ['earlier', 'known', 'missing']
    assert ordered.score.tolist() == [7, 8, 9]
    assert audit['time_order_complete'] is False
    assert audit['status'] == 'ordered_with_unresolved_time'
    assert audit['unresolved_time_contrasts'] == [{'contrast_id': 'missing', 'rows': 1}]


def test_conflicts_unknown_contrast_and_invalid_time_stop_export():
    with pytest.raises(ValueError, match='Conflicting contrast metadata'):
        order_method_scores(pd.DataFrame([_score('same')]), comparisons=pd.DataFrame([
            _comparison('same', 1), _comparison('same', 2)]))
    with pytest.raises(ValueError, match='no canonical metadata'):
        order_method_scores(pd.DataFrame([_score('absent')]), comparisons=pd.DataFrame([_comparison('known', 1)]))
    with pytest.raises(ValueError, match='Invalid time_min'):
        order_method_scores(pd.DataFrame([_score('bad')]), comparisons=pd.DataFrame([_comparison('bad', '15min')]))
    with pytest.raises(ValueError, match='Invalid time_min'):
        order_method_scores(pd.DataFrame([_score('bad')]), comparisons=pd.DataFrame([_comparison('bad', float('inf'))]))
    with pytest.raises(ValueError, match='requires design or quant/comparisons'):
        order_method_scores(pd.DataFrame([_score('known')]))


def test_design_and_comparisons_must_agree_and_empty_schema_is_kept():
    rows = [('known', 1, 'control', 'arm', 'unpaired')]
    comparisons = pd.DataFrame([_comparison('known', 1)])
    ordered, _ = order_method_scores(pd.DataFrame([_score('known')]), design=_design(rows), comparisons=comparisons)
    assert ordered.contrast_id.tolist() == ['known']
    disagreed = comparisons.copy()
    disagreed.loc[0, 'time_min'] = 5
    with pytest.raises(ValueError, match='Conflicting time_min'):
        order_method_scores(pd.DataFrame([_score('known')]), design=_design(rows), comparisons=disagreed)
    empty = pd.DataFrame(columns=['method_result_id', 'method_id', 'contrast_id', 'score'])
    kept, audit = order_method_scores(empty)
    assert list(kept.columns) == list(empty.columns) and kept.empty
    assert audit['status'] == 'empty' and audit['time_order_complete'] is False


def test_write_tables_orders_only_method_scores_and_records_the_policy(tmp_path):
    comparisons = pd.DataFrame([_comparison('id_5', 5), _comparison('id_1', 1)])
    scores = pd.DataFrame([_score('id_5', score=5), _score('id_1', score=1)])
    other = pd.DataFrame([{'form_id': 'form_b', 'A': 1.5}, {'form_id': 'form_a', 'A': None}])
    before = tmp_path / 'before'
    after = tmp_path / 'after'
    write_tables({'quant/comparisons': comparisons, 'quant/summary': other}, before)
    dictionary = write_tables({'quant/comparisons': comparisons, 'quant/summary': other, 'kinase/method_scores': scores}, after)
    assert pd.read_csv(after / 'kinase/method_scores.csv').contrast_id.tolist() == ['id_1', 'id_5']
    assert (before / 'quant/summary.csv').read_bytes() == (after / 'quant/summary.csv').read_bytes()
    assert (before / 'quant/comparisons.csv').read_bytes() == (after / 'quant/comparisons.csv').read_bytes()
    entry = dictionary['kinase/method_scores.csv']
    assert entry['row_order_policy'] == 'canonical_minutes_within_method_scope'
    assert entry['row_order_metadata_source'] == 'quant/comparisons'
    assert entry['time_order_complete'] is True
    assert 'time_min' not in entry['columns']
    shuffled = scores.sample(frac=1, random_state=3)
    cached = tmp_path / 'cached'
    write_tables({'quant/comparisons': comparisons, 'kinase/method_scores': shuffled}, cached)
    assert pd.read_csv(cached / 'kinase/method_scores.csv').contrast_id.tolist() == ['id_1', 'id_5']
