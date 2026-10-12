"""Color semantics and candidate labels cannot change measurement identity."""
import json
import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import Normalize


def test_zero_neutral_and_one_grid_scale():
    from ptm_shared.astra_figures import heatmap_style
    grid=pd.DataFrame([[-.2,0,4],[np.nan,-3,1.]])
    before=grid.copy(deep=True);style=heatmap_style(grid,'A')
    norm=Normalize(style['vmin'],style['vmax'])
    assert norm(0)==.5 and norm(-4)==0 and norm(4)==1
    assert norm(-.2)<norm(0)<norm(1)
    pd.testing.assert_frame_equal(grid,before)
    for values in [[0.,0.],[np.nan,np.nan]]:
        empty=heatmap_style(pd.DataFrame([values]),'A')
        assert empty['vmin']==-1 and empty['vmax']==1
        assert 'display_only' in empty['range_reason']


def test_counts_are_sequential_with_explicit_missing():
    from ptm_shared.astra_figures import heatmap_style
    style=heatmap_style(pd.DataFrame([[0,1,3,np.nan]]),'detected_n')
    assert style['vmin']==0 and style['vmax']==3 and style['cmap']=='Blues'
    assert style['unit']=='Detected injections (count)' and style['finite_cells']==3
    assert style['missing_color']=='#bdbdbd'
    for value in [-1,.5]:
        with pytest.raises(ValueError,match='nonnegative integers'):
            heatmap_style(pd.DataFrame([[value]]),'detected_n')


def test_candidate_mapping_is_not_collapsed_to_one_site_or_precursor():
    from ptm_shared.astra_figures import heatmap_rows
    mapping=[{'gene':'Same','accession':'A','sites':['S10']},
             {'gene':'Same','accession':'B-2','sites':['S31','T32']}]
    summary=pd.DataFrame([{'form_id':fid,'mapping_json':json.dumps(mapping),'precursor_count':2,
        'strict_attribution_status':'no_call_localization_unavailable','mapping_status':'multiple_mappings'} for fid in ['a','b']])
    audit=pd.DataFrame([{'form_id':'a','substrate_taxon':'9606'},{'form_id':'a','substrate_taxon':'10116'}])
    rows=heatmap_rows(['a','b','unresolved'],{'quant/summary':summary,'science/site_identity_audit':audit})
    assert rows.form_id.tolist()==['a','b','unresolved']
    assert rows.iloc[0].candidate_sites=='S10;S31;T32'
    assert 'multiple mappings' in rows.iloc[0].display_label
    assert '9606' in rows.iloc[0].display_label and '10116' in rows.iloc[0].display_label
    assert 'precursor' not in rows.iloc[0].display_label and 'localized' not in rows.iloc[0].display_label
    assert rows.iloc[2].display_label=='unresolved'
    assert json.loads(rows.iloc[0].mapping_json)==mapping


def test_saved_color_units_rows_and_detection_denominators(tmp_path):
    from ptm_shared.astra_figures import figure_packet
    from ptm_shared.tests.test_astra_figures import fixture_tables
    design,tables=fixture_tables()
    tables['evidence/emergence_evidence']['scheduled_n']=4
    figure_packet(tables,tmp_path,design)
    for name in ['substrate_contrast_heatmap','emerging_detection']:
        rows=pd.read_csv(tmp_path/'figures'/f'{name}_rows.csv')
        assert rows.form_id.tolist()==['form_a','form_b','form_missing']
        assert (tmp_path/'figures'/f'{name}.png').is_file()
    columns=pd.read_csv(tmp_path/'figures/emerging_detection_columns.csv')
    assert columns.scheduled_injection_counts.eq('[4]').all()
    assert columns.denominator_scope.str.contains('not biological n').all()
