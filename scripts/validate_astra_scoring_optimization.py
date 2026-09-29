"""Compare optimized scoring to recorded pre-optimization tables on identical inputs."""
import argparse,json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from ptm_shared.astra_discovery import score_candidates
p=argparse.ArgumentParser();p.add_argument('--recorded',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
design=json.loads((a.recorded/'study/study_design.json').read_text());tables={name:pd.read_csv(a.recorded/'quant'/f'{name}.csv',float_precision='round_trip') for name in ['comparisons','strict_parent_paired']}
edges=pd.read_csv(a.recorded/'kinase/kinase_candidate_edges.csv',low_memory=False,keep_default_na=False,float_precision='round_trip');start=time.monotonic();actual=score_candidates(tables,edges,design);elapsed=time.monotonic()-start
a.output.mkdir(parents=True,exist_ok=True);results=[]
for name,df in actual.items():
    path=a.output/(name+'.csv');df.to_csv(path,index=False)
    old=pd.read_csv(a.recorded/'kinase'/(name+'.csv'),low_memory=False);new=pd.read_csv(path,low_memory=False)
    pd.testing.assert_frame_equal(old,new,check_exact=False,check_dtype=False,atol=1e-10,rtol=1e-10)
    assert old.isna().equals(new.isna())
    results.append({'table':name,'rows':len(old),'keys_text_masks_numeric_equal':True})
record={'all_tables_equal':True,'elapsed_seconds':elapsed,'tables':results,'atol':1e-10,'rtol':1e-10}
(a.output/'validation.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))
