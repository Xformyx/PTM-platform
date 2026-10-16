"""M1: summary-independent access, exact keys, scope and preserved restrictions."""
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from ptm_shared import astra_evidence_catalog as access, astra_reader as reader
from ptm_shared.astra_card_inputs import project_card_inputs
from ptm_shared.astra_package import write_tables
from ptm_shared.generic_workflow import json_write
from ptm_shared.tests.test_astra_card_inputs import small, config


@pytest.fixture
def saved(small, tmp_path):
    tables, inputs, design = small
    tables = {**tables, **project_card_inputs(tables, inputs, design, {})}
    contrasts = tables['quant/comparisons']
    proteins = contrasts[['form_id','contrast_id','arm_id','reference_condition_id','time_min','reference_time_min','pairing']].rename(columns={'form_id':'protein_group'})
    proteins['gene'] = 'SameLabel'; proteins['log2_change'] = 0.125
    tables['quant/protein_contrasts'] = proteins
    tables['quant/summary']['parent_pg'] = tables['quant/summary'].form_id
    tables['quant/detection'] = contrasts[['form_id','contrast_id','arm_id','time_min','reference_condition_id']].copy()
    tables['quant/detection']['baseline_status'] = 'reference_undetected'
    tables['quant/detection']['post_reference_time_min'] = 30
    tables['evidence/emergence_evidence'] = pd.DataFrame([{'emergence_id':'emerge1','form_id':'mixed','condition_id':'one','time_min':30}])
    tables['kinase/method_scores'] = pd.DataFrame([{'method_result_id':'method1','candidate_id':'candidate1',
        'contrast_id':'one_base','method_id':'PhosX_native_functions','method_version':'0.23.1','status':'insufficient_coverage',
        'score':None,'method_p':None,'method_q':None}])
    tables['science/inference_results'] = pd.DataFrame([{'call_id':'call1','proposed_entity_id':'candidate1',
        'contrast_or_window_id':'one_base','inference_status':'abstained','resolution':'no_call','track':'specificity_A',
        'no_call_reasons':'uncalibrated_policy'}])
    tables['kinase/kinase_candidate_edges'] = pd.DataFrame([{'edge_id':'edge1','candidate_id':'candidate1',
        'candidate_gene':'AKT1','candidate_accession':'assay_unresolved','kinase_taxon':None}])
    tables['kinase/substrate_contributions'] = pd.DataFrame([{'contribution_id':'contribution1','form_ids':'single;multisite',
        'candidate_id':'candidate1','contrast_id':'one_base','track':'specificity_A'}])
    tables.update(reader.build_reader_tables(tables,design))
    root=tmp_path/'package'; root.mkdir();(root/'reproducibility').mkdir()
    dictionary=write_tables(tables,root)
    json_write(root/'reproducibility/data_dictionary.json',dictionary)
    access.write_evidence_access(root)
    return root,tables,design


def test_all_keys_pagination_unselected_withheld_and_scope(saved):
    root,tables,_=saved; catalog=access.EvidenceCatalog(root)
    for name in access.REQUIRED:
        original=tables[name[:-4]]; keys=catalog.catalog['sources'][name]['unique_key']
        indexed=catalog.index.loc[catalog.index.source_table.eq(name)]
        assert len(indexed)==len(original)
        assert set(indexed.source_key_json)=={access.encode({k:r[k] for k in keys}) for r in original.to_dict('records')}
    populations=[]
    for size in [1,7,10000]:
        found=[];cursor=None
        while True:
            page=catalog.query({},cursor,size);found.extend(i['evidence_id'] for i in page['items']);cursor=page['next_cursor']
            if cursor is None:break
        assert len(found)==page['total_count']==len(set(found));populations.append(found)
    assert populations[0]==populations[1]==populations[2]
    raw=catalog.query({'source_table':'reader_adapter/form_contrasts.csv','status':'withheld'})
    assert raw['total_count']==18
    resolved=catalog.resolve([r['evidence_id'] for r in raw['items']])
    assert all(json.loads(r['source_row']['row_json'])['localization_probability'] is None for r in resolved)
    # Exact form/reference/NA preserved even when display labels are identical.
    found=catalog.query({'entity':'samelabel','source_table':'reader_adapter/form_contrasts.csv'},page_size=1000)['items']
    assert {r['form_id'] for r in found}==set(tables['quant/summary'].form_id)
    assert {tuple(json.loads(r['taxa_json'])) for r in found} >= {('9606',),('10090',),('10090','9606')}
    for ref in ['base','other_base']:
        rows=catalog.query({'form_id':'single','reference_condition_id':ref,'evidence_type':'raw_ptm'})['items']
        assert [r['time_min'] for r in rows]==[30,60,120]
        raw=[json.loads(r['source_row']['row_json']) for r in catalog.resolve([r['evidence_id'] for r in rows])]
        assert raw[1]['A'] is None and raw[0]['A']==1
        assert raw[0]['U_all']==3 and raw[0]['U_joint']==2
    method=catalog.query({'entity':'akt1','evidence_type':'method_result'})
    result=catalog.resolve([method['items'][0]['evidence_id']])[0]['source_row']
    assert result['status']=='insufficient_coverage' and result['score'] is None
    call=catalog.resolve(['call1'])[0]['source_row'];assert call['resolution']=='no_call'
    links=catalog.resolve_links(['single'])['links']
    assert any(r['relation_type']=='precursor_member_of' for r in links)
    cmp=catalog.query({'form_id':'single','evidence_type':'ptm_contrast','contrast_id':'one_base'})['items'][0]
    links=catalog.resolve_links([cmp['evidence_id']])['links']
    assert any(r['relation_type']=='same_experiment_parent_context' for r in links)
    assert any(r['relation_type']=='substrate_contribution_from' for r in links)
    assert len(catalog.source_rows('kinase/substrate_contributions.csv',[{'contribution_id':'contribution1'}]))==1


def test_selection_not_access_and_empty_selected(saved,tmp_path):
    root,tables,design=saved
    original=reader.select_finding_cards; outputs=[]
    scientific={k:v for k,v in tables.items() if not k.startswith('reader/')}
    for maximum in [5,15,50,0]:
        def choose(cards, maximum_unused=15, **kw):
            picked,audit=original(cards,maximum=maximum or 15)
            return ([] if maximum==0 else picked),audit
        with patch.object(reader,'select_finding_cards',side_effect=choose):
            variant={**scientific,**reader.build_reader_tables(scientific,design)}
        out=tmp_path/str(maximum);out.mkdir()
        d=write_tables(variant,out);index,catalog,links=access.build_evidence_index(out,d)
        outputs.append((index.drop(columns=['selected_for_summary']),links,catalog['indexed_rows']))
    for a,b,count in outputs[1:]:
        pd.testing.assert_frame_equal(a,outputs[0][0]);pd.testing.assert_frame_equal(b,outputs[0][1]);assert count==outputs[0][2]


def test_integrity_cursor_and_legacy(saved,tmp_path):
    root,tables,_=saved;c=access.EvidenceCatalog(root)
    token=c.query(page_size=1)['next_cursor']
    with pytest.raises(ValueError,match='Cursor'):c.query({'entity':'AKT1'},token)
    with pytest.raises(ValueError,match='Unknown evidence'):c.resolve(['made_up'])
    with pytest.raises(ValueError,match='Invalid canonical'):c.source_rows('quant/summary.csv',[{'gene':'SameLabel'}])
    with pytest.raises(ValueError,match='Unknown source key'):c.source_rows('quant/summary.csv',[{'form_id':'missing'}])
    with pytest.raises(ValueError,match='Unregistered source'):c.source_rows('../../secret',[{}])
    old=access.EvidenceCatalog(tmp_path/'legacy');assert old.catalog['catalog_available'] is False
    with pytest.raises(ValueError,match='catalog_available=false'):old.query()
    path=root/'quant/summary.csv';path.write_text(path.read_text()+'\n')
    with pytest.raises(ValueError,match='hash mismatch'):c.query({},token)
    with pytest.raises(ValueError,match='hash mismatch'):access.EvidenceCatalog(root)
    access.write_evidence_access(root)
    with pytest.raises(ValueError,match='Cursor'):access.EvidenceCatalog(root).query({},token)


def test_duplicate_missing_and_broken_fk(saved,tmp_path):
    _,tables,_=saved
    for kind in ['duplicate','missing','fk']:
        bad={k:v.copy() for k,v in tables.items()}
        if kind=='duplicate':bad['quant/protein_contrasts']=pd.concat([bad['quant/protein_contrasts'],bad['quant/protein_contrasts'].iloc[:1]])
        if kind=='missing':del bad['quant/detection']
        if kind=='fk':bad['kinase/substrate_contributions'].loc[0,'form_ids']='made_up'
        out=tmp_path/kind;out.mkdir();d=write_tables(bad,out)
        with pytest.raises(ValueError,match={'duplicate':'Duplicate source key','missing':'Missing required','fk':'Broken evidence link FK'}[kind]):
            access.build_evidence_index(out,d)


def test_numeric_time_and_distinct_arms_with_shuffled_rows(saved,tmp_path):
    _,tables,_=saved
    changed={k:v.copy() for k,v in tables.items()}
    # Two explicit arms at identical numeric times and with distinct references.
    # This exercises metadata projection, not a new time parser or estimator.
    for name in ['quant/comparisons','quant/detection','quant/protein_contrasts']:
        f=changed[name]
        f['arm_id']=f.reference_condition_id.map({'base':'arm-A','other_base':'arm-B'})
    f=changed['reader_adapter/form_contrasts']
    def update(value):
        row=json.loads(value);row['arm_id']='arm-A' if row['reference_condition_id']=='base' else 'arm-B'
        return access.encode(row)
    f['row_json']=f.row_json.map(update)
    for name in changed:changed[name]=changed[name].sample(frac=1,random_state=24).reset_index(drop=True)
    out=tmp_path/'shuffled';out.mkdir();(out/'reproducibility').mkdir()
    json_write(out/'reproducibility/data_dictionary.json',write_tables(changed,out));access.write_evidence_access(out)
    c=access.EvidenceCatalog(out)
    for arm,ref in [('arm-A','base'),('arm-B','other_base')]:
        items=c.query({'form_id':'single','evidence_type':'raw_ptm','arm_id':arm})['items']
        assert [r['time_min'] for r in items]==[30,60,120]
        assert {json.loads(r['scope_json'])['reference_condition_id'] for r in items}=={ref}


def test_normal_v6_generation_and_reader_only_replay(config,tmp_path):
    import subprocess,sys
    from ptm_shared import astra_evidence_v6 as engine
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    with patch.object(reader,'write_evidence_access',wraps=reader.write_evidence_access) as called:
        result=engine.run('m1-fixture',config,tmp_path/'out')
    assert called.call_count==1
    root=tmp_path/'out/enrichment_free_runs'/result['run_id']
    c=access.EvidenceCatalog(root);assert c.query()['total_count']>0
    assert 'astra_evidence_catalog.py' in result['provenance']['code_sha256']
    assert 'astra_reader_full.py' in result['provenance']['code_sha256']
    assert (root/'reader/full_question_links.csv').is_file()
    assert (root/'reader/full_temporal_links.csv').is_file()
    completed=subprocess.run([sys.executable,'scripts/replay_astra_reader.py','--package',str(root),'--output',str(tmp_path/'replay')],capture_output=True,text=True)
    assert completed.returncode==0,completed.stderr
    report=json.loads((tmp_path/'replay/READER_REPLAY_VALIDATION.json').read_text())
    assert report['network_requests']==0 and all(r['byte_equal'] for r in report['files'])
    from ptm_shared.astra_reader_revision import revise_temporal
    revision_root=tmp_path/'revision';revision_root.mkdir()
    pointer=revision_root/'enrichment_free_current.json';pointer.write_text('previous_success')
    with patch.object(reader,'write_evidence_access',side_effect=ValueError('bad access revision')):
        with pytest.raises(ValueError,match='bad access revision'):
            revise_temporal(root,revision_root,access_only=True)
    assert pointer.read_text()=='previous_success'
    with patch('ptm_shared.astra_reader_full.write_full',side_effect=ValueError('bad full revision')):
        with pytest.raises(ValueError,match='bad full revision'):
            revise_temporal(root,revision_root,whole_only=True)
    assert pointer.read_text()=='previous_success'


def test_access_code_does_not_invalidate_scientific_fingerprints(config):
    from ptm_shared import astra_evidence_v6 as engine
    context=config['experimental_context'];before=engine.resolve_plan(context)
    original=engine.digest
    with patch.object(engine,'digest',side_effect=lambda p:'changed_reader_code' if Path(p).name in {'astra_evidence_catalog.py','astra_reader_full.py'} else original(p)):
        after=engine.resolve_plan(context)
    assert before['fingerprints']==after['fingerprints']


def test_reader_access_failure_preserves_success_pointer(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    out=tmp_path/'out';out.mkdir();pointer=out/'enrichment_free_current.json'
    pointer.write_text('{"run_id":"previous_success"}')
    with patch.object(reader,'write_evidence_access',side_effect=ValueError('catalog validation failed')):
        with pytest.raises(ValueError,match='catalog validation failed'):engine.run('m1-failure',config,out)
    assert pointer.read_text()=='{"run_id":"previous_success"}'
