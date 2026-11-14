import json
from copy import deepcopy
import pandas as pd
import pytest
from test_ai_catalog import saved_points
from ptm_shared.substrate_signal_flow import trajectory_projection, TRAJECTORIES, MEMBERS, legacy_crosswalk
from ptm_shared.astra_evidence_catalog import EvidenceCatalog
from ptm_shared.substrate_signal_flow import kinase_projection, KINASES, KINASE_MEMBERS
from ptm_shared.effect_series import resolve_series
from ptm_shared.substrate_signal_flow import observed_order, evidence_map, LINKS, HYPOTHESES, ASSOCIATIONS


def kinase_fixture(tables,design,registry):
    sid=next(iter(resolve_series(design)[0]))
    edges=[];contributions=[];profiles=[];fixed=[];anchors=[]
    for k in ['K1','K2']:
        edges.append({'edge_id':'edge_'+k,'candidate_id':k,'form_id':'f','edge_type':'curated','site_id':'s','measurement_group_id':'g','substrate_gene':'G'})
        for i,c in enumerate(design['contrasts']):
            cid=c['contrast_id']
            contributions.append({'contribution_id':k+cid,'candidate_id':k,'contrast_id':cid,'track':'curated_A',
                'form_ids':'f','site_ids':'s','measurement_group_id':'g','substrate_gene':'G','edge_ids':'edge_'+k,'value':i,'gene_weight':1})
            profiles.append({'candidate_id':k,'contrast_id':cid,'track':'curated_A','activity_magnitude':i,'coverage_adequate':False})
            fixed.append({'candidate_id':k,'series_id':sid,'contrast_id':cid,'track':'curated_A','fixed_common_score':None,'fixed_common_sites':0,'entered_sites':1 if i==0 else 0})
        anchors.append({'candidate_id':k,'series_id':sid,'track':'curated_A','site_key':'s','support_status':'no_remaining_anchor','independent_validation':False})
    for name,rows,keys in [
        ('kinase/kinase_candidate_edges',edges,['edge_id']),
        ('kinase/substrate_contributions',contributions,['contribution_id']),
        ('kinase/kinase_temporal_profiles',profiles,['candidate_id','contrast_id','track']),
        ('temporal/kinase_fixed_membership',fixed,['candidate_id','series_id','contrast_id','track']),
        ('temporal/target_excluded_anchors',anchors,['candidate_id','series_id','track','site_key'])]:
        tables[name]=pd.DataFrame(rows);registry[name+'.csv']={'unique_key':keys,'sha256':'synthetic-hash'}
    return tables,design,registry


def test_exact_kinase_counts_scores_exclusion_and_identical_support(tmp_path):
    _,tables,design,registry=fixture(tmp_path)
    kinase_fixture(tables,design,registry)
    trajectories=trajectory_projection(tables,design,registry)[TRAJECTORIES]
    result=kinase_projection(tables,design,registry,trajectories)
    bundles=result[KINASES].query('track == "curated_A"')
    assert len(bundles)==2 and bundles.family_label.isna().all()
    assert bundles.gene_count.eq(1).all() and bundles.measurement_group_count.eq(1).all()
    for b in bundles.to_dict('records'):
        assert json.loads(b['indistinguishable_candidates_json'])==['K1','K2']
        points=json.loads(b['points_json'])
        assert points[0]['membership_event_meaning']=='initial_membership_not_emergence'
        assert [p['saved_results']['kinase/kinase_temporal_profiles'][0]['values']['activity_magnitude'] for p in points]==[0,1,2]
        assert all(p['saved_results']['temporal/kinase_fixed_membership'][0]['values']['fixed_common_score'] is None for p in points)
        assert json.loads(b['diagnostics_json'])['temporal/target_excluded_anchors'][0]['values']['support_status']=='no_remaining_anchor'
    assert len(result[KINASE_MEMBERS])==6
    tables['kinase/substrate_contributions'].loc[0,'edge_ids']='missing'
    with pytest.raises(ValueError,match='edge FK'):kinase_projection(tables,design,registry,trajectories)


def fixture(tmp_path, times=(7.5,45,240), mixed=True):
    root,tables,design=saved_points(tmp_path/'source',times,mixed,shared=None in times)
    registry=EvidenceCatalog(root).catalog['sources']
    return root,tables,design,registry


def test_full_population_scope_values_and_trace(tmp_path):
    root,tables,design,registry=fixture(tmp_path)
    original=tables['quant/comparisons'].copy(deep=True)
    result=trajectory_projection(tables,design,registry)
    a=result[TRAJECTORIES].query('track == "A"').iloc[0]
    points=json.loads(a.points_json)
    assert [p['time_min'] for p in points]==[7.5,45,240]
    assert len({p['reference_condition_id'] for p in points})==3
    assert len({p['pairing'] for p in points})==2
    for n in [0,5,15,50]:
        tables['reader/cards']['selected']=n>0
        pd.testing.assert_frame_equal(result[TRAJECTORIES],trajectory_projection(tables,design,registry)[TRAJECTORIES])
    pd.testing.assert_frame_equal(original,tables['quant/comparisons'])
    tables['quant/comparisons'].loc[1,'included']=False
    a=trajectory_projection(tables,design,registry)[TRAJECTORIES].query('track == "A"').iloc[0]
    p=json.loads(a.points_json)[1]
    assert p['value'] is None and p['calculation_trace_value']==1 and p['status']=='excluded'
    assert p['source_ref']['source_key']=={'form_id':'f','contrast_id':'c_1'}


def test_duplicate_key_identity_and_unknown_time(tmp_path):
    _,tables,design,registry=fixture(tmp_path,(7.5,7.5,None),False)
    extra=tables['quant/comparisons'].copy();extra['form_id']='distinct_taxon_form'
    tables['quant/comparisons']=pd.concat([tables['quant/comparisons'],extra],ignore_index=True)
    result=trajectory_projection(tables,design,registry)
    assert result[TRAJECTORIES].form_id.nunique()==2
    assert [p['time_min'] for p in json.loads(result[TRAJECTORIES].iloc[0].points_json)]==[7.5,7.5,None]
    tables['quant/comparisons']=pd.concat([tables['quant/comparisons'],extra])
    with pytest.raises(ValueError,match='Duplicate'):trajectory_projection(tables,design,registry)


def test_legacy_identity_never_symbol_only():
    assert legacy_crosswalk({'gene':'G','site':'S1'},[],{})['status']=='unavailable'
    f={'source_file_sha256':'hash','source_row':1,'precursor_id':'p','modified_sequence':'seq','taxon':'9606'}
    m={**f,'form_id':'f'}
    assert legacy_crosswalk(f,[m],{'f':{'taxa':['9606']}})['form_ids']==['f']
    assert legacy_crosswalk(f,[m],{'f':{'taxa':['10116']}})['status']=='unavailable'


def test_brackets_and_no_invented_biological_edge(tmp_path):
    a={'onset_lower_min':1,'onset_upper_min':5,'onset_left_censored':False}
    b={'onset_lower_min':15,'onset_upper_min':30,'onset_left_censored':False}
    assert observed_order(a,b)[0]=='observed_before'
    assert observed_order(b,a)[0]=='observed_after'
    assert observed_order(a,{**b,'onset_lower_min':5})[0]=='unresolved'
    assert observed_order({**a,'onset_left_censored':True},b)[0]=='unresolved'
    assert observed_order(a,None)[0]=='not_evaluable'
    _,tables,design,registry=fixture(tmp_path)
    kinase_fixture(tables,design,registry)
    outputs=trajectory_projection(tables,design,registry)
    outputs.update(kinase_projection(tables,design,registry,outputs[TRAJECTORIES]))
    result=evidence_map(outputs)
    assert not result[LINKS].edge_type.str.contains('prior').any()
    assert result[HYPOTHESES].prior_status.eq('missing_exact_prior').all()
    assert result[LINKS].causality_status.eq('not_established').all()
    assert result[HYPOTHESES].semantic_review_status.eq('not_performed').all()


def test_exact_prior_preserves_opposite_observed_order(tmp_path):
    _,tables,design,registry=fixture(tmp_path)
    kinase_fixture(tables,design,registry)
    outputs=trajectory_projection(tables,design,registry)
    outputs.update(kinase_projection(tables,design,registry,outputs[TRAJECTORIES]))
    t=outputs[TRAJECTORIES].query('track == "A"').iloc[0].to_dict()
    target={**t,'feature_json':json.dumps({'onset_lower_min':1,'onset_upper_min':5}),'feature_refs_json':json.dumps([{'evidence_id':'target_feature'}])}
    upstream={**t,'trajectory_id':'upstream','form_id':'kinase_form','identity_json':json.dumps({'protein_group':'P123','taxa':['9606']}),
              'feature_json':json.dumps({'onset_lower_min':15,'onset_upper_min':30}),'feature_refs_json':json.dumps([{'evidence_id':'upstream_feature'}])}
    outputs[TRAJECTORIES]=pd.DataFrame([target,upstream])
    for i,b in outputs[ASSOCIATIONS].iterrows():
        edges=json.loads(b.edges_json)
        for e in edges:e.update(edge_type='curated_exact_site_native',site_mapping_status='unique',directness='site_relation_recorded',candidate_accession='P123',input_accession='P456',substrate_taxon=9606,kinase_taxon=9606,evidence_record_ids='prior1')
        outputs[ASSOCIATIONS].loc[i,'edges_json']=json.dumps(edges)
    outputs[MEMBERS]=outputs[MEMBERS].query('track == "A"')
    result=evidence_map(outputs)
    checks=[c for j in result[HYPOTHESES].prior_observation_checks_json for c in json.loads(j)]
    assert checks and all(c['consistency']=='inconsistent' and not c['prior_falsified'] for c in checks)


def test_projection_pages_bind_catalog_and_filters(tmp_path):
    from ptm_shared.substrate_signal_flow import project_signal_flow, TABLE_KEYS
    from ptm_shared.substrate_signal_view import signal_page
    from ptm_shared.astra_package import write_tables
    from ptm_shared.annotation_registry import digest
    from ptm_shared.generic_workflow import json_write,object_hash
    root,tables,design,registry=fixture(tmp_path)
    outputs=project_signal_flow(tables,design,registry)
    entries=write_tables(outputs,root)
    path=root/'reader/evidence_catalog.json';catalog=json.loads(path.read_text())
    for name,meta in entries.items():
        meta.update(unique_key=TABLE_KEYS[name[:-4]],sha256=digest(root/name),indexed=False)
        catalog['sources'][name]=meta
    catalog['catalog_id']=object_hash({k:v for k,v in catalog.items() if k!='catalog_id'});json_write(path,catalog)
    c=EvidenceCatalog(root)
    ids=[];cursor=None
    while True:
        page=signal_page(c,'substrate_trajectories',{},cursor,1)
        ids.extend(r['trajectory_id'] for r in page['items']);cursor=page['next_cursor']
        if cursor is None:break
    assert ids==[r['trajectory_id'] for r in signal_page(c,'substrate_trajectories',limit=50)['items']]
    cursor=signal_page(c,'substrate_trajectories',limit=1)['next_cursor']
    with pytest.raises(ValueError,match='Cursor'):signal_page(c,'substrate_trajectories',{'track':'A'},cursor)
    assert signal_page(c,'substrate_trajectories',{'track':'A'})['total_count']==1


def test_native_unselected_membership_is_accessible_but_not_contributing(tmp_path):
    _,tables,design,registry=fixture(tmp_path)
    tables['kinase/method_membership']=pd.DataFrame([{'method_membership_id':'excluded','candidate_id':'k','contrast_id':'c_0',
        'method_id':'native','form_ids':'f','site_ids':'s','measurement_group_id':'g','selected':False,'ranking_statistic':4.2}])
    registry['kinase/method_membership.csv']={'unique_key':['method_membership_id'],'sha256':'fixture'}
    projections=trajectory_projection(tables,design,registry)
    result=kinase_projection(tables,design,registry,projections[TRAJECTORIES])
    b=result[KINASES].loc[result[KINASES].track.str.startswith('method:')].iloc[0]
    assert b.contributing_form_count==0 and b.measurement_group_count==0
    assert json.loads(result[KINASE_MEMBERS].iloc[0].saved_values_json)['selected'] is False
    projections.update(result)
    links=evidence_map(projections)[LINKS]
    assert 'method_input_excluded' in set(links.edge_type)
    assert 'method_contribution' not in set(links.edge_type)


def test_membership_turnover_keeps_variable_fixed_and_count_units_separate(tmp_path):
    _,tables,design,registry=fixture(tmp_path)
    kinase_fixture(tables,design,registry)
    extra=tables['quant/comparisons'].copy();extra['form_id']='second_form'
    tables['quant/comparisons']=pd.concat([tables['quant/comparisons'],extra],ignore_index=True)
    edges=tables['kinase/kinase_candidate_edges'].copy()
    edges['edge_id']+='second';edges['form_id']='second_form';edges['substrate_gene']='OTHER'
    tables['kinase/kinase_candidate_edges']=pd.concat([tables['kinase/kinase_candidate_edges'],edges],ignore_index=True)
    rows=tables['kinase/substrate_contributions']
    at_later=rows.contrast_id.eq('c_1')
    rows.loc[at_later,'form_ids']='second_form';rows.loc[at_later,'edge_ids']+='second'
    rows.loc[at_later,'substrate_gene']='OTHER'
    fixed=tables['temporal/kinase_fixed_membership']
    fixed['entered_sites']=[1,1,1]*2;fixed['departed_sites']=[0,1,1]*2
    projections=trajectory_projection(tables,design,registry)
    result=kinase_projection(tables,design,registry,projections[TRAJECTORIES])
    b=result[KINASES].query('candidate_id == "K1" and track == "curated_A"').iloc[0]
    assert b.contributing_form_count==2 and b.gene_count==2 and b.measurement_group_count==1
    points=json.loads(b.points_json)
    assert [p['contributing_form_count'] for p in points]==[1,1,1]
    assert [p['saved_results']['kinase/kinase_temporal_profiles'][0]['values']['activity_magnitude'] for p in points]==[0,1,2]
    assert all(p['saved_results']['temporal/kinase_fixed_membership'][0]['values']['fixed_common_score'] is None for p in points)
    assert [p['saved_results']['temporal/kinase_fixed_membership'][0]['values']['departed_sites'] for p in points]==[0,1,1]
    assert points[0]['membership_event_meaning']=='initial_membership_not_emergence'
