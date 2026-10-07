"""Round 03: inspect and render an existing ZIP; never run scientific stages."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import types
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd

from ptm_shared.astra_figures import figure_packet


CURVES={'kinase_footprints':('kinase/kinase_temporal_profiles','candidate_id','activity_magnitude','curated_A'),
        'protein_trajectories':('quant/protein_contrasts','protein_group','log2_change',None)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-commit',default='21e136d28957a4c63ee6c66daa2d83cbbf11c528')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    sha=hashlib.sha256(args.archive.read_bytes()).hexdigest()
    before=args.output/'before';after=args.output/'after';before.mkdir();after.mkdir()
    baseline=subprocess.check_output(['git','show',args.baseline_commit+':ptm_shared/astra_figures.py'])
    old=types.ModuleType('ptm_shared._round03_reviewed_baseline');old.__package__='ptm_shared'
    exec(compile(baseline,'reviewed_round02_astra_figures.py','exec'),old.__dict__)
    with zipfile.ZipFile(args.archive) as z:
        design=json.loads(z.read('study/study_design.json'))
        run_id=json.loads(z.read('provenance.json'))['run_id']
        legends=json.loads(z.read('figures/figure_legends.json'))
        keys={r['source_table'] for r in legends}|{'kinase/kinase_candidate_edges'}
        tables={key:pd.read_csv(io.BytesIO(z.read(key+'.csv')),float_precision='round_trip',low_memory=False) for key in keys}
        original=args.output/'original_svg';original.mkdir()
        for name in CURVES:(original/(name+'.svg')).write_bytes(z.read('figures/'+name+'.svg'))
    snapshots={k:f.copy(deep=True) for k,f in tables.items()}
    old.figure_packet(tables,before,design)
    figure_packet(tables,after,design)
    results=[]
    for name,(key,entity,value,track) in CURVES.items():
        frame=tables[key];frame=frame.loc[frame.track.eq(track)] if track else frame
        groups=list(frame.groupby([entity,'arm_id','reference_condition_id'],sort=True))
        previous=[]
        for i,(ident,g) in enumerate(groups):
            previous.append({**dict(zip([entity,'arm_id','reference_condition_id'],ident)),
                             'selected':i<12,'finite_observations':int(np.isfinite(g[value]).sum())})
        previous=pd.DataFrame(previous);previous.to_csv(args.output/(name+'_before_selection.csv'),index=False)
        selected=pd.read_csv(after/'figures'/(name+'_selection.csv'),keep_default_na=False)
        points=pd.read_csv(after/'figures'/(name+'_points.csv'),float_precision='round_trip')
        included=selected.loc[selected.selected]
        assert len(included)<=12 and included.finite_observation_count.gt(0).all()
        assert included.display_label.is_unique
        svg=ET.parse(after/'figures'/(name+'.svg'),parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))).getroot()
        comments=[n.text.strip() for n in svg.iter() if n.tag is ET.Comment]
        point_count=0
        for n,r in enumerate(included.to_dict('records'),1):
            source=frame.loc[frame[entity].eq(r[entity]) & frame.arm_id.eq(r['arm_id']) & frame.reference_condition_id.eq(r['reference_condition_id'])]
            if 'pairing' in source:source=source.loc[source.pairing.eq(r['pairing'])]
            plotted=points.loc[points.plot_series_key.eq(r['plot_series_key'])]
            pd.testing.assert_frame_equal(source.sort_values('contrast_id').reset_index(drop=True),
                plotted[source.columns].sort_values('contrast_id').reset_index(drop=True),check_exact=True)
            finite=np.isfinite(plotted[value]) & np.isfinite(plotted.time_min)
            assert finite.equals(plotted.plotted_point)
            assert int(finite.sum())==r['finite_observation_count']
            group=next(g for g in svg.iter() if g.attrib.get('id')==f'curve-series-{n}')
            markers=[node for node in group.iter() if node.tag.endswith('}use') and 'x' in node.attrib and 'y' in node.attrib]
            assert len(markers)==int(finite.sum()),'Saved SVG markers must match finite source points'
            assert f"{r['display_label']} (n={r['finite_observation_count']})" in comments
            point_count+=len(markers)
        results.append({'figure':name,'all_series':len(previous),'all_finite_series':int(previous.finite_observations.gt(0).sum()),
            'all_finite_observations':int(previous.finite_observations.sum()),
            'before_selected_series':int(previous.selected.sum()),
            'before_selected_finite_series':int((previous.selected & previous.finite_observations.gt(0)).sum()),
            'before_selected_finite_observations':int(previous.loc[previous.selected,'finite_observations'].sum()),
            'after_selected_series':len(included),'after_svg_points':point_count,'after_retained_na_rows':int(points[value].isna().sum()),
            'values_na_time_and_source_fields_exact':True,'saved_svg_markers_and_labels_match':True,
            'selected':included.to_dict('records')})
    unchanged=[]
    for r in legends:
        suffixes=['_source.csv']+(['.svg'] if r['figure_id'] not in CURVES else [])
        if r['figure_id'] in {'substrate_contrast_heatmap','emerging_detection'}:suffixes+=['_columns.csv']
        for suffix in suffixes:
            filename=r['figure_id']+suffix
            assert (before/'figures'/filename).read_bytes()==(after/'figures'/filename).read_bytes(),filename
            unchanged.append(filename)
    for k,f in tables.items():pd.testing.assert_frame_equal(f,snapshots[k],check_exact=True)
    assert hashlib.sha256(args.archive.read_bytes()).hexdigest()==sha
    result={'passed':True,'archive':str(args.archive),'archive_sha256':sha,'run_id':run_id,
            'baseline_commit':args.baseline_commit,'original_zip_unchanged':True,'source_tables_unchanged':True,
            'scope':'figure_only_no_quantification_or_reference_acquisition','curves':results,
            'outputs_byte_identical':unchanged,'visual_review':'pending_separate_saved_svg_render'}
    (args.output/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='curves'},ensure_ascii=False,indent=2))
    for r in results:print(json.dumps({k:v for k,v in r.items() if k!='selected'},ensure_ascii=False))


if __name__=='__main__':main()
