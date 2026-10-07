"""Display-only regression: irregular canonical times, identities and NA cells."""
import json
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import pytest

from ptm_shared.astra_figures import figure_packet,heatmap_grid
from ptm_shared.contrast_quantification import ContrastEstimator
from ptm_shared.study_design import time_value


def fixture_tables():
    # Opaque IDs deliberately disagree with time order. Labels are not parsers.
    entries=[('condition_z','Vehicle A','control_a',0,'s'),
             ('condition_a','Vehicle B','control_b',30,'s'),
             ('condition_q','Early','arm_a',120,'s'),
             ('condition_b','Middle','arm_a',.5,'h'),
             ('condition_f','Late','arm_a',1,'d'),
             ('condition_0','Early','arm_b',2,'min'),
             ('condition_x','Middle','arm_b',30,'min')]
    conditions=[{'condition_id':cid,'label':label,'arm_id':arm,'time':time_value(value,unit)}
                for cid,label,arm,value,unit in entries]
    comparisons=[('contrast_z','condition_q','condition_z','unpaired'),
                 ('contrast_a','condition_b','condition_z','unpaired'),
                 ('contrast_b','condition_f','condition_z','unpaired'),
                 ('contrast_m','condition_b','condition_a','paired'),
                 ('contrast_y','condition_0','condition_a','paired'),
                 ('contrast_0','condition_x','condition_a','paired')]
    design={'conditions':conditions,'injections':[],'materials':[],
            'arms':[{'arm_id':a,'name':name} for a,name in [('arm_a','Treatment A'),('arm_b','Treatment B'),
                                                           ('control_a','Vehicle A'),('control_b','Vehicle B')]],
            'contrasts':[{'contrast_id':cid,'target_condition_id':target,'reference_condition_id':reference,'pairing':pair}
                         for cid,target,reference,pair in comparisons]}
    est=ContrastEstimator(design)
    comp=pd.DataFrame([{**est.metadata(c),'form_id':f,'A':np.nan if f=='form_missing' or (i+j)%4==0 else i-j}
                       for i,c in enumerate(design['contrasts']) for j,f in enumerate(['form_b','form_a','form_missing'])])
    detection=pd.DataFrame([{'form_id':f,'condition_id':c['condition_id'],'arm_id':c['arm_id'],
                            'time_min':c['time']['minutes'],'detected_n':np.nan if f=='form_missing' else i%4}
                           for i,c in enumerate(conditions) for f in ['form_b','form_a','form_missing']])
    empty_impact=pd.DataFrame(columns=['classification','U_joint','P_joint','A','form_id','contrast_id'])
    empty_impact['included']=pd.Series(dtype=bool)
    tables={'quant/comparisons':comp,'evidence/emergence_evidence':detection,
            'evidence/coverage_funnel':pd.DataFrame([{'metric':'fixture','count':3}]),
            'evidence/technical_dispersion':pd.DataFrame(columns=['track','log2_SD']),
            'evidence/parent_adjustment_impact':empty_impact,
            'kinase/kinase_temporal_profiles':pd.DataFrame(columns=['track','candidate_id','arm_id','reference_condition_id','time_min','contrast_id','activity_magnitude']),
            'quant/protein_contrasts':pd.DataFrame(columns=['protein_group','arm_id','reference_condition_id','time_min','contrast_id','log2_change']),
            'temporal/cross_layer_links':pd.DataFrame(columns=['source_peak_min','target_peak_min'])}
    return design,tables


def svg_column_labels(path):
    root=ET.parse(path,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))).getroot()
    result=[]
    for group in root.iter():
        if group.attrib.get('id','').startswith('heatmap-column-'):
            result.append('\n'.join(n.text.strip() for n in group.iter() if n.tag is ET.Comment))
    return result


def test_numeric_time_series_identity_and_missing_cells():
    design,tables=fixture_tables()
    for table,key,value,expected in [
        ('quant/comparisons','contrast_id','A',['contrast_z','contrast_a','contrast_b','contrast_m','contrast_y','contrast_0']),
        ('evidence/emergence_evidence','condition_id','detected_n',['condition_z','condition_a','condition_q','condition_0','condition_b','condition_x','condition_f'])]:
        original=tables[table]
        shuffled=original.sample(frac=1,random_state=19)
        grid,metadata=heatmap_grid(shuffled,'form_id',key,value,design)
        assert list(grid)==expected
        assert len(grid.columns)==original[key].nunique()
        assert grid.loc['form_missing'].isna().all()
        by_id=original.pivot(index='form_id',columns=key,values=value).sort_index()
        pd.testing.assert_frame_equal(grid.reindex(columns=by_id.columns),by_id,check_exact=True)
        # Canonical design order also cannot influence the chronological axis.
        permuted={**design,'conditions':list(reversed(design['conditions'])),'contrasts':list(reversed(design['contrasts']))}
        again,axis=heatmap_grid(original.sample(frac=1,random_state=37),'form_id',key,value,permuted)
        pd.testing.assert_frame_equal(grid,again,check_exact=True)
        pd.testing.assert_frame_equal(metadata,axis,check_exact=True)
        assert metadata.display_label.is_unique
        assert any('1440 min' in label for label in metadata.display_label)
        if key=='contrast_id':
            assert 'condition_z' not in grid.columns  # no synthetic baseline
            assert metadata.groupby(['arm_id','reference_condition_id','pairing']).time_min.apply(lambda s:s.is_monotonic_increasing).all()
            assert len(metadata.loc[metadata.time_min.eq(30)])==3


@pytest.mark.parametrize('conflicting',[False,True])
def test_duplicate_cells_never_silently_aggregate(conflicting):
    design,tables=fixture_tables();f=tables['quant/comparisons']
    extra=f.iloc[[1]].copy()
    if conflicting:extra['A']=999
    with pytest.raises(ValueError,match='Duplicate heatmap cells'):
        heatmap_grid(pd.concat([f,extra]),'form_id','contrast_id','A',design)


def test_table_time_conflict_is_not_silently_relabelled():
    design,tables=fixture_tables();f=tables['quant/comparisons'].copy();f.loc[0,'time_min']=100
    with pytest.raises(ValueError,match='Conflicting heatmap time_min'):
        heatmap_grid(f,'form_id','contrast_id','A',design)


def test_saved_svg_labels_match_ordered_metadata(tmp_path):
    design,tables=fixture_tables();figure_packet(tables,tmp_path,design)
    for name in ['substrate_contrast_heatmap','emerging_detection']:
        metadata=pd.read_csv(tmp_path/'figures'/(name+'_columns.csv'))
        assert svg_column_labels(tmp_path/'figures'/(name+'.svg'))==metadata.display_label.tolist()
    legends=json.loads((tmp_path/'figures/figure_legends.json').read_text())
    assert next(r for r in legends if r['figure_id']=='substrate_contrast_heatmap')['duplicate_cell_policy']=='error_no_aggregation'
