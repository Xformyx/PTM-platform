import json
from copy import deepcopy
import pandas as pd
import pytest
from test_ai_catalog import saved_points
from ptm_shared.substrate_signal_flow import trajectory_projection, TRAJECTORIES, MEMBERS, legacy_crosswalk
from ptm_shared.astra_evidence_catalog import EvidenceCatalog


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
