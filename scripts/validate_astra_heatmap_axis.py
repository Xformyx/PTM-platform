"""Round 02: regenerate figures only from an immutable, existing Astra ZIP."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import types
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from ptm_shared.astra_figures import figure_packet,heatmap_grid


HEATMAPS={'substrate_contrast_heatmap':('quant/comparisons','contrast_id','A'),
          'emerging_detection':('evidence/emergence_evidence','condition_id','detected_n')}


def svg_labels(path,ordered=False):
    root=ET.parse(path,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))).getroot()
    prefix='heatmap-column-' if ordered else 'xtick_'
    return ['\n'.join(n.text.strip() for n in group.iter() if n.tag is ET.Comment)
            for group in root.iter() if group.attrib.get('id','').startswith(prefix)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-commit',required=True,help='Reviewed code revision matching the ZIP renderer')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    sha=hashlib.sha256(args.archive.read_bytes()).hexdigest()
    before=args.output/'before';after=args.output/'after';before.mkdir();after.mkdir()
    with zipfile.ZipFile(args.archive) as z:
        design=json.loads(z.read('study/study_design.json'))
        run_id=json.loads(z.read('provenance.json'))['run_id']
        source=z.read('reproducibility/code/ptm_shared/astra_figures.py')
        reviewed=subprocess.check_output(['git','show',args.baseline_commit+':ptm_shared/astra_figures.py'])
        assert source==reviewed,'Review the archived renderer before executing it'
        old=types.ModuleType('ptm_shared._reviewed_heatmap_baseline');old.__package__='ptm_shared'
        exec(compile(source,'reviewed_archived_astra_figures.py','exec'),old.__dict__)
        legends=json.loads(z.read('figures/figure_legends.json'))
        tables={r['source_table']:pd.read_csv(io.BytesIO(z.read(r['source_table']+'.csv')),float_precision='round_trip') for r in legends}
        snapshots={key:table.copy(deep=True) for key,table in tables.items()}
        original=args.output/'original_svg';original.mkdir()
        for name in HEATMAPS:(original/(name+'.svg')).write_bytes(z.read('figures/'+name+'.svg'))
        old.figure_packet(tables,before)
        figure_packet(tables,after,design)
    results=[]
    for name,(key,column,value) in HEATMAPS.items():
        frame=tables[key]
        old_grid=frame.pivot_table(index='form_id',columns=column,values=value,aggfunc='first',dropna=False).sort_index()
        grid,metadata=heatmap_grid(frame,'form_id',column,value,design)
        assert svg_labels(original/(name+'.svg'))==list(old_grid.columns)
        assert svg_labels(before/'figures'/(name+'.svg'))==list(old_grid.columns)
        assert svg_labels(after/'figures'/(name+'.svg'),ordered=True)==metadata.display_label.tolist()
        exported=pd.read_csv(after/'figures'/(name+'_columns.csv'))
        assert exported.column_id.tolist()==list(grid.columns)
        assert exported.display_label.tolist()==metadata.display_label.tolist()
        new_full=frame.pivot(index='form_id',columns=column,values=value).sort_index().reindex(columns=grid.columns)
        pd.testing.assert_frame_equal(new_full.reindex(columns=old_grid.columns),old_grid,check_exact=True)
        pd.testing.assert_frame_equal(grid.reindex(columns=old_grid.columns),old_grid.iloc[:50],check_exact=True)
        assert set(grid.columns)==set(frame[column]),'No synthetic baseline or omitted condition'
        grid.to_csv(args.output/(name+'_displayed_grid.csv'))
        clock=metadata.set_index('column_id').time_min
        results.append({'figure':name,'before_ids':list(old_grid.columns),'before_minutes':clock.reindex(old_grid.columns).tolist(),
                        'after_ids':list(grid.columns),'after_minutes':metadata.time_min.tolist(),'labels':metadata.display_label.tolist(),
                        'source_rows':len(frame),'full_grid_cells':int(new_full.size),'full_grid_na':int(new_full.isna().sum().sum()),
                        'displayed_grid_cells':int(grid.size),'displayed_grid_na':int(grid.isna().sum().sum()),
                        'values_na_exact':True,'selected_rows_unchanged':True,'no_added_columns':True,'saved_svg_labels_match_metadata':True})
    unchanged=[]
    for key,frame in tables.items():pd.testing.assert_frame_equal(frame,snapshots[key],check_exact=True)
    for r in legends:
        for suffix in ['_source.csv']+(['.svg'] if r['figure_id'] not in HEATMAPS else []):
            filename=r['figure_id']+suffix
            assert (before/'figures'/filename).read_bytes()==(after/'figures'/filename).read_bytes(),filename
            unchanged.append(filename)
    assert hashlib.sha256(args.archive.read_bytes()).hexdigest()==sha
    result={'passed':True,'run_id':run_id,'archive':str(args.archive),'archive_sha256':sha,'original_zip_unchanged':True,
            'baseline_commit':args.baseline_commit,'validation_scope':'figure_regeneration_only_no_quantification_or_source_acquisition',
            'heatmaps':results,'other_outputs_byte_identical':unchanged}
    (args.output/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
