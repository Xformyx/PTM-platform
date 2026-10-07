"""Projection failures: no invented precursor/site, no cross-reference pooling."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from ptm_shared.astra_card_inputs import project_card_inputs, consumer_states, validate_card_inputs, metadata_packet
from scripts.validate_astra_card_inputs import card_builders, verify_consumers
from ptm_shared.tests.test_astra_science import config


@pytest.fixture
def small(tmp_path):
    conditions=[{'condition_id':name,'arm_id':'arm','label':name,'time':{'minutes':t,'unit':'h','value':t/60}}
                for name,t in [('base',0),('one',30),('gap',60),('last',120),('other_base',15)]]
    injections=[{'injection_id':f'{c["condition_id"]}-{n}','input_column':f'{c["condition_id"]}-{n}',
                 'condition_id':c['condition_id'],'material_id':c['condition_id']} for c in conditions for n in range(3)]
    design={'conditions':conditions,'injections':injections,'materials':[{'material_id':c['condition_id'],
             'biological_unit_id':c['condition_id'],'pair_id':None} for c in conditions],
            'study':{'species':'mixed_species'},'replication_declaration':'technical_per_condition'}
    summaries=[];mappings=[];pr=[];contrasts=[];runs=[];localization=[]
    for fid,taxa,multiprecursor,sequence in [('single',[9606],False,'AS(UniMod:21)AA'),
            ('multisite',[9606],False,'AS(UniMod:21)T(UniMod:21)A'),
            ('collapsed',[9606],True,'AS(UniMod:21)AA'),('parent_missing',[9606],False,'AS(UniMod:21)AA'),
            ('mouse',[10090],False,'AS(UniMod:21)AA'),('mixed',[9606,10090],False,'AS(UniMod:21)AA')]:
        summaries.append({'form_id':fid,'Protein.Group':fid,'Modified.Sequence':sequence,'Genes':'SameLabel',
                          'representative_sites':'S2;T3' if fid=='multisite' else 'S2','mapping_status':'mapped',
                          'precursor_count':2 if multiprecursor else 1})
        for i,taxon in enumerate(taxa):
            mappings.append({'form_id':fid,'identity_id':fid+str(i),'site_id':fid+'_site'+str(i),
                'measurement_group_id':'group_'+fid,'substrate_taxon':taxon,'mapping_status':'multiple_mappings' if len(taxa)>1 else 'unique'})
        for charge in ([2,3] if multiprecursor else [2]):
            pr.append({'Protein.Group':fid,'Modified.Sequence':sequence,'Precursor.Id':f'{fid}-{charge}',
                       'Precursor.Charge':charge,**{s['input_column']:100 for s in injections}})
        for s in injections:
            runs.append({'form_id':fid,**s,'joint_observed':fid!='parent_missing' and s['condition_id']!='gap'})
        for target,t in [('one',30),('gap',60),('last',120)]:
            for ref in ['base','other_base']:
                missing=fid=='parent_missing' or target=='gap'
                cid=target+'_'+ref
                c={'form_id':fid,'contrast_id':cid,'arm_id':'arm','condition_id':target,'target_condition_id':target,
                    'reference_condition_id':ref,'target_label':target,'reference_label':ref,'time_min':t,
                    'reference_time_min':0 if ref=='base' else 15,'pairing':'unpaired','included':not missing,
                    'A':None if missing else 1.,'U_joint':None if missing else 2.,'P_joint':None if missing else 1.,
                    'U_all':3.,'P_all':None if fid=='parent_missing' else 1.5,'estimator_version':'fixture_original',
                    'statistical_unit':'biological_unit','inference_status':'descriptive_only',
                    'exclusion_reasons':'joint_missing' if missing else '',
                    'reference_joint_n':0 if missing else 3,'target_joint_n':0 if missing else 3,
                    'reference_joint_run_ids':'' if missing else ';'.join(f'{ref}-{i}' for i in range(3)),
                    'target_joint_run_ids':'' if missing else ';'.join(f'{target}-{i}' for i in range(3))}
                contrasts.append(c)
                localization.append({'form_id':fid,'contrast_id':cid,'localization_id':fid+cid,'measurement_status':'missing_input'})
    path=tmp_path/'PR.tsv';pd.DataFrame(pr).to_csv(path,sep='\t',index=False)
    tables={'quant/summary':pd.DataFrame(summaries),'quant/comparisons':pd.DataFrame(contrasts),
            'quant/runlevel':pd.DataFrame(runs),'science/site_identity_audit':pd.DataFrame(mappings),
            'science/localization_by_contrast':pd.DataFrame(localization)}
    return tables,{'PR':path},design


def test_identity_grain_na_masks_and_existing_consumers(small):
    tables,inputs,design=small
    before={k:v.copy(deep=True) for k,v in tables.items()}
    result=project_card_inputs(tables,inputs,design,{})
    validate_card_inputs({**tables,**result},design)
    for k,v in before.items():pd.testing.assert_frame_equal(v,tables[k])
    rows=result['reader_adapter/form_contrasts']
    assert len(rows)==36 and rows.form_id.nunique()==6
    assert not rows.loc[rows.form_id.isin(['mixed','collapsed','parent_missing']),'card_input_eligible'].any()
    collapsed=json.loads(result['reader_adapter/form_identity'].set_index('form_id').loc['collapsed'].identity_json)
    assert collapsed['precursor_id'] is None and len(collapsed['membership_ids'])==2
    assert set(result['reader_adapter/precursor_membership'].precursor_id)=={'single-2','multisite-2','collapsed-2','collapsed-3','parent_missing-2','mouse-2','mixed-2'}
    states=list(consumer_states(result));assert len(states)==6
    assert all(len(s['vector_plot_raw_data'])==3 for s in states)
    assert all(len({r['reference_id'] for r in s['vector_plot_raw_data']})==1 for s in states)
    # Each taxon/form has its own state despite an identical display name.
    assert {s['vector_plot_raw_data'][0]['form_id'] for s in states}=={'single','multisite','mouse'}
    examples=verify_consumers({**tables,**result},maximum_states=10);assert len(examples)==6
    for example in examples:
        points=example['observation_cards'][0]['trajectory']
        assert [p['time_minutes'] for p in points]==[30,60,120]
        assert points[1]['ptm_unadjusted_log2fc'] is None
        assert points[0]['ptm_unadjusted_log2fc']==2  # NOT U_all=3
        assert points[0]['axes']['adjusted']['treatment_biological_n']==1
        assert points[0]['axes']['adjusted']['p'] is None
        assert example['source_rows'][0]['localization_probability'] is None


def test_duplicate_precursor_metadata_and_tampered_projection(small):
    tables,inputs,design=small
    raw=pd.read_csv(inputs['PR'],sep='\t');pd.concat([raw,raw.iloc[:1]]).to_csv(inputs['PR'],sep='\t',index=False)
    result=project_card_inputs(tables,inputs,design,{})
    r=result['reader_adapter/form_contrasts'];assert not r.loc[r.form_id.eq('single'),'card_input_eligible'].any()
    assert 'precursor_membership_count_mismatch' in r.iloc[0].restriction_reasons
    row=json.loads(r.iloc[0].row_json);row['ptm_unadjusted_log2fc']=row['U_all']
    r.loc[0,'row_json']=json.dumps(row)
    with pytest.raises(ValueError,match='Card axis changed'):validate_card_inputs({**tables,**result},design)


def test_excluded_finite_stays_raw_and_is_not_promoted(small):
    tables,inputs,design=small
    tables['quant/comparisons'].loc[0,['included','exclusion_reasons']]=[False,'mapping_ineligible']
    result=project_card_inputs(tables,inputs,design,{})
    first=result['reader_adapter/form_contrasts'].iloc[0]
    assert json.loads(first.row_json)['A']==1
    assert first.consumer_state_status=='raw_only_excluded_finite_contrast'
    assert first.consumer_state_id not in {s['consumer_state_id'] for s in consumer_states(result)}


def test_recorded_metadata_and_shared_function(small):
    _,_,design=small
    raw={'cell_type':'cell-A','cell_model':'cell-B','dose':0,'enrichment':False,'panel':[],
         'biological_question':'한글\nLong question '+('abc'*1000)}
    snapshot={'original':{'analysis_context':raw}}
    p=metadata_packet(design,{},snapshot)
    assert p['recorded_context']==raw and p['contract']['metadata_status']=='conflict_unresolved'
    assert 'starvation' not in p['recorded_context']
    card_builders()  # Import pure consumers without loading the report graph.
    from report_generation.core.study_metadata import build_study_metadata_contract as old
    from ptm_shared.study_metadata import build_study_metadata_contract as shared
    assert old is shared


def test_adapter_called_by_v6_and_portable_replay(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    from ptm_shared.astra_package import validate_package
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    with patch.object(engine,'project_card_inputs',wraps=engine.project_card_inputs) as spy:
        result=engine.run('round06-synthetic',config,tmp_path/'out')
    assert spy.call_count==1
    root=tmp_path/'out/enrichment_free_runs'/result['run_id']
    validate_package(root)
    assert result['analysis_readiness']['card_input_adapter']['status']=='projected'
    provenance=json.loads((root/'provenance.json').read_text())
    for name in ['astra_card_inputs.py','study_metadata.py','annotation_species.py','evidence_contracts.py']:
        assert name in provenance['code_sha256']
        assert (root/'reproducibility/code/ptm_shared'/name).is_file()
    # Fresh interpreter: only the packaged source tree, no repository on sys.path.
    replay=tmp_path/'offline'
    code="import socket,runpy,sys; socket.create_connection=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network')); sys.argv=[sys.argv[1],'--output',sys.argv[2]]; runpy.run_path(sys.argv[0],run_name='__main__')"
    import os
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    completed=subprocess.run([sys.executable,'-c',code,str(root/'replay.py'),str(replay)],cwd=tmp_path,env=env,capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    report=json.loads((replay/'replay_result.json').read_text())
    assert report['passed'] and all(t['byte_equal'] for t in report['tables'])
    assert len([r for r in report['tables'] if r['table'].startswith('reader_adapter/')])==4
