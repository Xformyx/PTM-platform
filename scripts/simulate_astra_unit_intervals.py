"""Synthetic null/effect coverage diagnostic. Not a biological benchmark or calibration."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from ptm_shared.contrast_quantification import ContrastEstimator
from ptm_shared.science_inference import unit_intervals


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    rng=np.random.default_rng(20261001);results=[]
    for n in (3,8,20):
        design={'replication_declaration':'independent_biological_units','conditions':[{'condition_id':c,'arm_id':c,'label':c,'time':None} for c in ['r','t']],
                'contrasts':[{'contrast_id':'c','reference_condition_id':'r','target_condition_id':'t','pairing':'paired'}],
                'materials':[],'injections':[]}
        for c in ['r','t']:
            for i in range(n):
                mid=f'{c}{i}';design['materials'].append({'material_id':mid,'biological_unit_id':f'donor{i}','pair_id':f'pair{i}'})
                for rep in (1,2):design['injections'].append({'injection_id':f'{mid}_{rep}','input_column':f'{mid}_{rep}','condition_id':c,'material_id':mid})
        for effect in (0.,1.):
            # Each row is a separate simulated experiment, not an independent peptide.
            base=rng.normal(size=(300,n));delta=rng.normal(effect,1,size=(300,n))
            joint=np.concatenate([np.repeat(base,2,axis=1),np.repeat(base+delta,2,axis=1)],axis=1)
            out=unit_intervals({'arrays':{'A':joint},'summary':pd.DataFrame({'form_id':[f'simulation_{i}' for i in range(300)]}),
                'estimator':ContrastEstimator(design)},design,{'enabled':True,'resamples':500})
            valid=out.interval_low.notna();coverage=((out.interval_low<=effect)&(out.interval_high>=effect))
            results.append({'independent_units':n,'effect':effect,'simulations':300,'evaluable':int(valid.sum()),
                'coverage_of_nominal_95_percent_interval':float(coverage[valid].mean()),
                'design':'paired Gaussian unit effects with duplicated technical measurements',
                'release_interpretation':'diagnostic_only_experimental_not_calibrated'})
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({'seed':20261001,'results':results,
        'limitations':'Percentile bootstrap can under-cover at small n; this diagnostic does not establish biological validity or change policy thresholds.'},indent=2))
    print(args.output.read_text())


if __name__=='__main__':main()
