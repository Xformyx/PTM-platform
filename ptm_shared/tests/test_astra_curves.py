"""Round 03: display selection must not change observations or scientific calls."""
import json

import numpy as np
import pandas as pd
import pytest

from ptm_shared.astra_figures import curve_series,figure_packet
from ptm_shared.feature_identity import project_reader_display_identity
from ptm_shared.tests.test_astra_figures import fixture_tables


def curve_fixture():
    design,tables=fixture_tables()
    metadata=tables['quant/comparisons'].drop_duplicates('contrast_id').iloc[:3].drop(columns=['form_id','A'])
    rows=[]
    for cid,name,values in [('a_missing','Missing',[np.nan]*3),('z_gap','Same',[1.,np.nan,3.]),
                            ('y_single','Same',[np.nan,0.,np.nan]),('x_other','Same',[2.,np.nan,np.nan]),
                            ('w_family','FamilyExample',[1.,2.,3.])]:
        for r,value in zip(metadata.to_dict('records'),values):
            rows.append({**r,'candidate_id':cid,'candidate_gene':name,'activity_magnitude':value,
                         'track':'curated_A','coverage_adequate':False})
    frame=pd.DataFrame(rows).sample(frac=1,random_state=8).reset_index(drop=True)
    edges=pd.DataFrame([{'candidate_id':cid,'kinase_taxon':taxon,'candidate_resolution':resolution,'candidate_accession':accession}
                        for cid,taxon,resolution,accession in [('z_gap',10116,'gene_or_accession','R1'),
                            ('y_single',9606,'gene_or_accession','H1'),('x_other',10116,'gene_or_accession','R2'),
                            ('w_family',10116,'family','')]])
    tables['kinase/kinase_temporal_profiles']=frame
    tables['kinase/kinase_candidate_edges']=edges
    return design,tables


def test_finite_selection_labels_and_exact_points():
    design,tables=curve_fixture();f=tables['kinase/kinase_temporal_profiles'];snapshot=f.copy(deep=True)
    selection,points=curve_series(f,'candidate_id','activity_magnitude',design,'curated_A',tables['kinase/kinase_candidate_edges'])
    assert selection.candidate_id.tolist()==['w_family','z_gap','x_other','y_single','a_missing']
    assert selection.finite_observation_count.tolist()==[3,2,1,1,0]
    assert selection.selected.tolist()==[True,True,True,True,False]
    assert selection.display_label.is_unique
    assert 'family' in selection.iloc[0].display_label
    assert 'taxon 9606' in selection.set_index('candidate_id').loc['y_single','display_label']
    assert 'taxon 10116' in selection.set_index('candidate_id').loc['z_gap','display_label']
    assert points.coverage_adequate.eq(False).all()  # no threshold gating
    assert points.plotted_point.sum()==7
    selected=f.loc[f.candidate_id.isin(selection.loc[selection.selected,'candidate_id'])]
    keys=['candidate_id','contrast_id']
    pd.testing.assert_frame_equal(points[f.columns].sort_values(keys).reset_index(drop=True),
                                  selected.sort_values(keys).reset_index(drop=True),check_exact=True)
    pd.testing.assert_frame_equal(f,snapshot,check_exact=True)
    again,other=curve_series(f.sample(frac=1,random_state=59),'candidate_id','activity_magnitude',design,'curated_A',tables['kinase/kinase_candidate_edges'])
    pd.testing.assert_frame_equal(selection,again,check_exact=True)
    pd.testing.assert_frame_equal(points,other,check_exact=True)


def test_limit_is_applied_after_finite_filter_with_stable_ties():
    design,tables=curve_fixture();row=tables['kinase/kinase_temporal_profiles'].iloc[0].to_dict()
    f=pd.DataFrame([{**row,'candidate_id':f'a_missing_{i}','activity_magnitude':np.nan} for i in range(15)]+
                   [{**row,'candidate_id':f'z_valid_{i:02}','activity_magnitude':float(i)} for i in range(15)])
    selection,points=curve_series(f.sample(frac=1,random_state=31),'candidate_id','activity_magnitude',design,'curated_A')
    assert selection.loc[selection.selected,'candidate_id'].tolist()==[f'z_valid_{i:02}' for i in range(12)]
    assert selection.selection_reason.value_counts().to_dict()=={'no_finite_value_at_finite_time':15,'selected_finite_observation_rank':12,'display_limit_12':3}
    assert len(points)==12


def test_saved_curve_paths_keep_missing_intervals_and_singleton(tmp_path,monkeypatch):
    import matplotlib.figure
    from matplotlib.path import Path
    design,tables=curve_fixture();captured={}
    original=matplotlib.figure.Figure.savefig
    def capture(fig,path,**kwargs):
        if path.name=='kinase_footprints.svg':
            for line in fig.axes[0].lines:
                if (line.get_gid() or '').startswith('curve-series-'):
                    captured[line.get_label()]={'x':line.get_xdata(),'y':line.get_ydata(),
                         'moves':sum(code==Path.MOVETO for _,code in line.get_path().iter_segments()),'marker':line.get_marker()}
        return original(fig,path,**kwargs)
    monkeypatch.setattr(matplotlib.figure.Figure,'savefig',capture)
    figure_packet(tables,tmp_path,design)
    selection=pd.read_csv(tmp_path/'figures/kinase_footprints_selection.csv')
    points=pd.read_csv(tmp_path/'figures/kinase_footprints_points.csv')
    for r in selection.loc[selection.selected].itertuples():
        actual=captured[f'{r.display_label} (n={r.finite_observation_count})']
        expected=points.loc[points.candidate_id.eq(r.candidate_id)]
        np.testing.assert_array_equal(actual['x'],expected.time_min)
        np.testing.assert_array_equal(actual['y'],expected.activity_magnitude)
        assert actual['marker']=='o'
        if r.candidate_id=='z_gap':assert actual['moves']==2  # two separate segments, no bridge
        if r.candidate_id=='y_single':assert np.isfinite(actual['y']).sum()==1
    assert len(captured)==4


@pytest.mark.parametrize('empty',[False,True])
def test_no_finite_data_has_reason_without_legend(tmp_path,empty):
    design,tables=curve_fixture()
    f=tables['kinase/kinase_temporal_profiles'].copy();f.activity_magnitude=np.nan
    tables['kinase/kinase_temporal_profiles']=f.iloc[:0] if empty else f
    figure_packet(tables,tmp_path,design)
    svg=(tmp_path/'figures/kinase_footprints.svg').read_text()
    assert 'Not evaluable: no finite observations' in svg
    assert 'legend_1' not in svg
    legends=json.loads((tmp_path/'figures/figure_legends.json').read_text())
    record=next(r for r in legends if r['figure_id']=='kinase_footprints')
    assert record['selected_series']==record['plotted_points']==0


def test_protein_labels_and_distinct_references_are_preserved():
    design,tables=fixture_tables()
    f=tables['quant/comparisons'].loc[lambda x:x.form_id.eq('form_b')].drop(columns=['form_id']).rename(columns={'A':'log2_change'})
    f=f.assign(protein_group='GROUP1',gene='MouseSymbol',log2_change=1.)
    other=f.assign(protein_group='GROUP2')
    original=pd.concat([f,other],ignore_index=True)
    selection,points=curve_series(original,'protein_group','log2_change',design)
    assert len(selection)==6 and selection.display_label.is_unique
    assert selection.display_label.str.startswith('MouseSymbol').all()
    assert not selection.display_label.str.contains('precursor').any()
    pd.testing.assert_frame_equal(points[original.columns].sort_values(['protein_group','contrast_id']).reset_index(drop=True),
                                  original.sort_values(['protein_group','contrast_id']).reset_index(drop=True),check_exact=True)


def test_entity_projection_is_distinct_from_precursor_projection():
    assert project_reader_display_identity({'candidate_gene':'Akt1','candidate_resolution':'family'},reader_measurement_unit='kinase_candidate')=='Akt1 family'
    assert project_reader_display_identity({'candidate_gene':'ERK1_2_family','candidate_resolution':'family'},reader_measurement_unit='kinase_candidate')=='ERK1_2 family'
    assert project_reader_display_identity({'candidate_gene':'Broad','candidate_resolution':'motif_class'},reader_measurement_unit='kinase_candidate')=='Broad motif class'
    assert project_reader_display_identity({'gene':'Akt1','position':'S2'})=='AKT1 modified-precursor feature annotated at S2'
    from ptm_shared.astra_package import CODE_FILES
    assert 'feature_identity.py' in CODE_FILES  # renderer dependency ships in portable code


def test_duplicate_curve_observation_is_not_hidden():
    design,tables=curve_fixture();f=tables['kinase/kinase_temporal_profiles']
    with pytest.raises(ValueError,match='Duplicate curve'):
        curve_series(pd.concat([f,f.iloc[[0]]]),'candidate_id','activity_magnitude',design,'curated_A')
