import json
import pytest
from test_ai_catalog import saved_points
from ptm_shared import astra_evidence_catalog as access
from ptm_shared.effect_series import resolve_series
from ptm_shared.generic_workflow import object_hash,json_write
from ptm_shared.annotation_registry import digest


def collect(c,request):
    rows=[];cursor=None
    while True:
        page=c.bundle({**request,'continuation':cursor})
        assert page['returned_count']==len(page['items'])
        assert page['count_unit']=='source_row_representations_not_independent_observations'
        assert len(access.encode(page).encode())<=request['byte_budget']
        assert page['items'],page
        rows+=page['items'];cursor=page['next_cursor']
        if cursor is None:break
    return rows


def test_budget_continuation_is_not_population_limit(tmp_path):
    root,_,design=saved_points(tmp_path/'p',mixed=True);c=access.EvidenceCatalog(root)
    sid=next(iter(resolve_series(design)[0]));scope={'effect_series_id':sid}
    expected=None
    for rows,budget in [(1,30000),(5,60000),(100,1000000)]:
        result=collect(c,{'catalog_id':c.catalog['catalog_id'],'scope':scope,'row_budget':rows,'byte_budget':budget})
        ids=[r['evidence_ref']['evidence_id'] for r in result]
        if expected is not None:assert ids==expected
        expected=ids
        assert any(r['evidence']['status_json'].find('withheld')>=0 for r in result)
        assert any(r['evidence']['status_json'].find('no_call')>=0 for r in result)
        for r in result:
            original=c.source_rows(r['evidence_ref']['source_table'],[r['evidence_ref']['source_key']])[0]
            assert r['values']==original
    first=c.bundle({'scope':scope,'row_budget':1,'byte_budget':30000})
    with pytest.raises(ValueError,match='Cursor'):c.bundle({'scope':{},'continuation':first['next_cursor']})
    with pytest.raises(ValueError,match='catalog'):c.bundle({'catalog_id':'wrong'})


def test_tiny_budget_does_not_skip_large_row_and_source_change_rejects(tmp_path):
    root,_,_=saved_points(tmp_path/'p');c=access.EvidenceCatalog(root)
    request={'scope':{'evidence_type':'ptm_contrast'},'byte_budget':1000}
    p=c.bundle(request)
    assert p['returned_count']==0 and p['remaining_count']==6 and p['next_cursor']
    assert p['limit_reason']=='byte_budget_requires_larger_response' and p['minimum_required_bytes']>1000
    more=c.bundle({**request,'byte_budget':p['minimum_required_bytes']+1000,'continuation':p['next_cursor']})
    assert more['items']
    with (root/'quant/comparisons.csv').open('a') as f:f.write('\n')
    with pytest.raises(ValueError,match='hash'):c.bundle({**request,'continuation':p['next_cursor']})


def test_duplicate_key_outside_requested_rows_is_rejected(tmp_path):
    root,_,_=saved_points(tmp_path/'p')
    path=root/'quant/comparisons.csv';lines=path.read_text().splitlines();path.write_text('\n'.join(lines+[lines[1]])+'\n')
    catalog=json.loads((root/access.CATALOG).read_text());meta=catalog['sources']['quant/comparisons.csv']
    meta.update(sha256=digest(path),rows=meta['rows']+1)
    catalog['catalog_id']=object_hash({k:v for k,v in catalog.items() if k!='catalog_id'});json_write(root/access.CATALOG,catalog)
    c=access.EvidenceCatalog(root)
    with pytest.raises(ValueError,match='Duplicate'):
        c.source_rows('quant/comparisons.csv',[{'form_id':'f','contrast_id':'c_0'}])


def test_stored_question_roles_and_unreviewed_literal_sources(tmp_path):
    import pandas as pd
    from ptm_shared.astra_package import write_tables
    root,_,_=saved_points(tmp_path/'p');c=access.EvidenceCatalog(root)
    e=c.query({'evidence_type':'ptm_contrast'},page_size=1)['items'][0]
    frames={'reader/full_question_links':pd.DataFrame([{'link_id':'q-link','question_id':'Q1',
        'subject_evidence_ids_json':json.dumps([e['evidence_id']]),'source_table':e['source_table'],
        'source_key_json':e['source_key_json'],'evidence_id':e['evidence_id'],'role':'opposing_observation','status':'linked','reason':None}]),
        'reader/literature_sources':pd.DataFrame([{'source_key':'source1','source_json':json.dumps({'document':'Stored permitted excerpt.',
            'export_status':'permitted','claim_support_status':'not_verified'}),'schema_version':'fixture'}])}
    d=json.loads((root/'reproducibility/data_dictionary.json').read_text());d.update(write_tables(frames,root))
    json_write(root/'reproducibility/data_dictionary.json',d);access.write_evidence_access(root);c=access.EvidenceCatalog(root)
    page=c.bundle({'scope':{'question_id':'Q1'},'source_roles':['opposing_observation']})
    assert page['total_count']==1 and page['items'][0]['evidence_ref']['evidence_id']==e['evidence_id']
    assert page['additional_context_access'][0]['table']=='reader/literature_sources.csv'
    lit=c.bundle({'scope':{'source_table':'reader/literature_sources.csv'},'source_roles':['literature_context']})
    assert json.loads(lit['items'][0]['values']['source_json'])['document']=='Stored permitted excerpt.'
    assert lit['review_status']=='not_performed_by_bundle'
