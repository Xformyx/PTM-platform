import numpy as np
from scipy.spatial.distance import squareform
from ptm_shared.condensed_wave_distance import condensed_distance, CorrelationView
from ptm_shared.kinase_trajectory_evidence import AnchorDeltaIndex, scheduled_intervals, _anchor_deltas


def test_condensed_distances_and_coherence_match_full_matrix_with_ties():
    rng=np.random.default_rng(128)
    values=rng.normal(size=(73,5)); values[1]=values[0];values[2]=-values[0]
    standardized=(values-values.mean(axis=1,keepdims=True))/values.std(axis=1,keepdims=True)
    corr=np.clip(standardized@standardized.T/5,-1,1);np.fill_diagonal(corr,1)
    expected=squareform(np.maximum((1-corr+(1-corr).T)/2,0),checks=False)
    with condensed_distance(standardized,memory_threshold_bytes=1,block_size=9) as actual:
        np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-14)
    assert abs(CorrelationView(standardized).mean_pairs(list(range(73)),block_size=9)-np.mean(corr[np.triu_indices(73,1)]))<1e-14


def test_indexed_medians_match_original_for_ties_multiforms_and_missing():
    times={f"f{i}":{"1min":i%3,"5min":(i%3)+(-1)**i,"10min":i%4} for i in range(12)}
    times["f3"].pop("5min")
    identities={f"f{i}":{"protein_group":"G","modified_sequence":f"form{i//2}"} for i in range(12)}
    intervals=scheduled_intervals(["1min","5min","10min"])
    index=AnchorDeltaIndex(intervals,times,list(times),identities)
    for a in range(6):
        for b in range(6):
            excluded={f"G|seq:form{a}",f"G|seq:form{b}"}
            for interval in intervals:
                expected=_anchor_deltas(interval,times,list(times),identities,excluded)
                assert index.query(interval,excluded)==expected


def test_streamed_events_and_loto_match_full_event_algorithm(tmp_path):
    import json
    from ptm_shared.dynamic_cowave_transition import analyze_dynamic_co_wave_transitions
    from ptm_shared.temporal_event_spool import TemporalEventSpool
    times=['1min','5min','15min','30min','60min']
    rng=np.random.default_rng(91)
    values=rng.choice([0.,None,-1.,1.,2.],size=(18,5))
    contract={'timepoints':times,'waves':[{'wave_id':f'w{g}', 'members':[{'key':f'f{i}','temporal_values':dict(zip(times,values[i]))} for i in range(g*6,(g+1)*6)]} for g in range(3)]}
    ordinary=analyze_dynamic_co_wave_transitions(contract)
    events=[]
    with TemporalEventSpool(tmp_path) as store:
        streamed=analyze_dynamic_co_wave_transitions(contract,event_store=store,event_sink=events.append)
    assert json.loads(json.dumps(streamed))==json.loads(json.dumps(ordinary))
    assert sum(e['record_type']=='pair_transition' for e in events)==ordinary['summary']['pair_transition_count']
    assert not list(tmp_path.iterdir())


def test_absolute_pearson_blocks_preserve_constant_missing_and_anticorrelation_rules():
    from ptm_shared.footprint_coherence import footprint_coherence
    rng=np.random.default_rng(129)
    x=rng.normal(size=(39,5));x[1]=-x[0];x[2]=1;x[3]=0
    labels=['1min','5min','10min','30min','60min']
    values={f'f{i}':dict(zip(labels,row)) for i,row in enumerate(x)}
    values['f4'].pop('10min')
    result=footprint_coherence(list(values),values,labels,block_size=7)
    filtered=np.delete(x,[3,4],axis=0)
    with np.errstate(invalid='ignore',divide='ignore'):corr=np.corrcoef(filtered)
    pairs=np.abs(corr[np.triu_indices(len(filtered),1)]);finite=pairs[np.isfinite(pairs)]
    assert result['mean_abs_pearson']==round(float(finite.mean()),3)
    assert result['valid_pair_count']==len(finite)


def test_geometry_cache_changes_with_profile_mask_and_dtype():
    from ptm_shared.tmm_identifiability import _singular_values,_cached_singular_values
    _cached_singular_values.cache_clear()
    base=np.array([[1.,2.],[3.,4.],[4.,2.]])
    for matrix in (base,base.copy(),base[:2],base*2,base.astype('float32')):
        np.testing.assert_array_equal(_singular_values(matrix),np.linalg.svd(matrix,compute_uv=False))
    assert _cached_singular_values.cache_info().hits==1
    assert _cached_singular_values.cache_info().misses==4
