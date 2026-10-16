"""M2 whole scope is independent of summary selection. No scientific execution."""
from copy import deepcopy
import json
from unittest.mock import patch

import pandas as pd
import pytest

from ptm_shared.tests.test_astra_reader_temporal import saved, small, packet
from ptm_shared import astra_reader as reader, astra_reader_full as full
from ptm_shared.astra_package import write_tables
from ptm_shared.astra_card_inputs import encode
from ptm_shared.astra_evidence_catalog import EvidenceCatalog, evidence_id_for
from ptm_shared.generic_workflow import json_write


def descriptor(tables,tmp_path):
    d=write_tables(tables,tmp_path)
    return {'sources':{k:{**v,'unique_key':v['unique_key'] or full.KEYS.get(k[:-4])} for k,v in d.items()}}


def test_complete_projection_and_summary_independence(saved,tmp_path):
    design=packet(saved)['canonical_study_design']; scientific={k:v for k,v in saved.items() if not k.startswith('reader/')}
    original=reader.select_finding_cards;outputs=[];question_sets=[]
    # Enough real card units to exercise all four capacities, without synthetic IDs.
    for maximum in [5,15,50,0]:
        def choose(cards,**kw):
            chosen,audit=original(cards,maximum=maximum or 15)
            return ([] if maximum==0 else chosen),audit
        with patch.object(reader,'select_finding_cards',side_effect=choose):
            t={**scientific,**reader.build_reader_tables(scientific,design,{'original':{'analysis_context':{'biological_question':'How does protein adjustment change the temporal response?'}}})}
        out=tmp_path/str(maximum);out.mkdir()
        result,summary=full.project_full(t,descriptor(t,out));outputs.append(result)
        cards=[json.loads(r.card_json) for r in t['reader/cards'].itertuples()]
        qids={c['consumer_state_id']:c['question_ids'] for c in cards if c['category']=='measured_feature_observation'}
        assert all(c['question_ids']==qids[c['consumer_state_id']] for c in cards if c['category']=='quantitation_comparison')
        assert any(qids.values())
        assert len(result[full.PREFIX+'question_links'])>0
        question_sets.append(qids)
        assert summary['module_members']==len(qids)
        subjects=result[full.PREFIX+'temporal_subjects']
        assert set(subjects.subject_type)=={'raw_form_scope','observation'}
        assert not subjects.subject_id.duplicated().any()
        links=result[full.PREFIX+'temporal_links']
        # No label join: mouse/multisite/mixed subjects cannot inherit single-form contribution.
        contribution=links[links.role.eq('candidate_contribution')]
        by_id={c['card_id']:c for c in cards}
        assert {by_id[eid]['form_id'] for eid in contribution.subject_evidence_id}=={'single'}
        for r in links.itertuples():
            key=json.loads(r.source_key_json);frame=t[r.source_table[:-4]]
            matched=frame
            for field,value in key.items():matched=matched.loc[matched[field].eq(value)]
            assert len(matched)==1
            assert r.evidence_id==evidence_id_for(r.source_table,key)
    for result in outputs[1:]:
        for name in result:pd.testing.assert_frame_equal(result[name],outputs[0][name])
    assert all(q==question_sets[0] for q in question_sets)


def test_ambiguous_scope_and_frozen_literature_are_not_promoted(saved,tmp_path):
    saved.update(reader.build_reader_tables(saved,packet(saved)['canonical_study_design'],{'original':{'analysis_context':{'biological_question':'How does protein adjustment change the temporal response?'}}}))
    original=packet(saved)
    extra=saved[full.SERIES].iloc[0].copy();extra['series_id']='extra_scope'
    saved[full.SERIES]=pd.concat([saved[full.SERIES],extra.to_frame().T],ignore_index=True)
    full.attach_full(saved)
    assert packet(saved).get('literature')==original.get('literature')
    result,_=full.project_full(saved,descriptor(saved,tmp_path))
    subjects=result[full.PREFIX+'temporal_subjects']
    assert 'ambiguous' in set(subjects.status)
    bad=set(subjects.loc[subjects.status.eq('ambiguous'),'subject_id'])
    assert not set(result[full.PREFIX+'temporal_links'].subject_evidence_id)&bad
    q=result[full.PREFIX+'question_links']
    assert set(q.loc[q.role.eq('literature_context'),'status'])=={'unresolved'}


@pytest.fixture
def access_package(request):
    return request.getfixturevalue('catalog_saved')

from ptm_shared.tests.test_astra_evidence_catalog import saved as catalog_saved


def test_citations_unselected_foreign_run_and_wrong_key(access_package):
    root,tables,_=access_package
    json_write(root/'provenance.json',{'run_id':'synthetic_m2'})
    catalog=EvidenceCatalog(root)
    item=catalog.query({'selected_for_summary':False,'evidence_type':'raw_ptm'})['items'][0]
    citation={'run_id':'synthetic_m2','catalog_id':catalog.catalog['catalog_id'],
        'evidence_id':item['evidence_id'],'source_table':item['source_table'],'source_key':json.loads(item['source_key_json'])}
    result=full.validate_citations(catalog,[citation]);assert result[0]['semantic_review']=='not_performed'
    for field,value,match in [('run_id','other_run','run mismatch'),('catalog_id','other_catalog','catalog mismatch'),
                              ('evidence_id','invented','ID/key mismatch'),('source_key',{'gene':'SameLabel'},'canonical')]:
        with pytest.raises(ValueError,match=match):full.validate_citations(catalog,[{**citation,field:value}])
    source=catalog.root/citation['source_table'];source.write_text(source.read_text()+'\n')
    with pytest.raises(ValueError,match='hash mismatch'):full.validate_citations(catalog,[citation])


def test_only_selected_native_membership_links_method_results(saved,tmp_path):
    saved.update(reader.build_reader_tables(saved,packet(saved)['canonical_study_design'],{'original':{'analysis_context':{'biological_question':'How does protein adjustment change the temporal response?'}}}))
    saved['kinase/method_scores']=pd.DataFrame([{'method_result_id':'native_'+state,'candidate_id':state,'contrast_id':'one_base',
        'method_id':'official_native','method_version':'pinned','status':'insufficient_coverage','score':None,
        'membership_ids':'member_'+state,'input_universe_hash':'universe'} for state in ['selected','not_selected']])
    saved['kinase/method_membership']=pd.DataFrame([{'method_membership_id':'member_'+state,'candidate_id':state,'contrast_id':'one_base',
        'method_id':'official_native','form_ids':'single','selected':state=='selected','input_universe_hash':'universe'} for state in ['selected','not_selected']])
    other=saved['kinase/method_scores'].iloc[0].to_dict()
    other.update(method_result_id='other_version',method_version='another',input_universe_hash='other_universe')
    saved['kinase/method_scores']=pd.concat([saved['kinase/method_scores'],pd.DataFrame([other])],ignore_index=True)
    out,summary=full.project_full(saved,descriptor(saved,tmp_path));q=out[full.PREFIX+'question_links']
    assert set(q.loc[q.source_table.eq('kinase/method_scores.csv'),'evidence_id'])=={'native_selected'}
    assert set(q.loc[q.source_table.eq('kinase/method_membership.csv'),'evidence_id'])=={'member_selected'}
    assert summary['native_membership_scope']['total_rows']==2
    assert summary['native_membership_scope']['selected_rows']==1
    subjects=out[full.PREFIX+'temporal_subjects']
    assert {'native_selected','native_not_selected'} <= set(subjects.subject_id)
    assert saved['kinase/method_scores'].status.tolist()==['insufficient_coverage']*3
