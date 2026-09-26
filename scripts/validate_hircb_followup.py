"""Compare original v1 artifacts and diagnose the predeclared v2 sensitivities."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd


def validate(reference, actual):
    table_results = {}
    for path in sorted(reference.glob('*.csv')):
        old, new = pd.read_csv(path), pd.read_csv(actual/path.name)
        pd.testing.assert_frame_equal(old,new[old.columns],check_dtype=False,atol=1e-10,rtol=1e-10)
        table_results[path.name] = {'rows':len(old),'original_columns_equal':True,
            'byte_equal':path.read_bytes()==(actual/path.name).read_bytes(),
            'added_columns':sorted(set(new)-set(old))}
    read = lambda name: pd.read_csv(actual/(name+'.csv'))
    primary = read('comparisons').query('included')
    old = read('strict_parent_joint_sensitivity').set_index(['form_id','time_min'])
    paired = read('strict_parent_paired_sensitivity_v2').set_index(['form_id','time_min'])
    complete = read('strict_parent_complete_mask_sensitivity_v2')
    delta = (paired.strict_parent_A-old.strict_parent_A).abs()
    flipped = (paired.strict_parent_A*old.strict_parent_A).lt(0)
    audit = read('strict_parent_peptide_mask_audit_v2')
    partial = audit.loc[audit.paired_included & ~audit.complete_mask_included,['form_id','time_min']].drop_duplicates()
    partial = partial.merge(old.loc[old.strict_parent_A.notna()].reset_index()[['form_id','time_min']])
    profiles = read('kinase_comparison_profiles_v2').set_index(['entity','mode','time_min'])
    parent_diff = (profiles.xs('parent_P_all_observed',level='mode').gene_balanced_mean -
                   profiles.xs('parent_P_joint',level='mode').gene_balanced_mean).abs()
    detection = read('detection')
    ineligible = detection.post_reference_A.notna() & ~detection.primary_adjustment_eligible
    results = {'reference_tables':table_results,'primary_comparisons':len(primary),
        'profiles_v1':len(read('kinase_profiles')),'strict_v1_available':int(old.strict_parent_A.notna().sum()),
        'paired_available':int(paired.strict_parent_A.notna().sum()),
        'complete_available':int(complete.strict_parent_A.notna().sum()),
        'comparisons_with_partial_peptide':len(partial),'paired_changed_gt_1e10':int(delta.gt(1e-10).sum()),
        'paired_difference_ge_0p1':int(delta.ge(.1).sum()),'paired_difference_ge_0p25':int(delta.ge(.25).sum()),
        'paired_difference_ge_0p5':int(delta.ge(.5).sum()),'paired_max_abs_difference':float(delta.max()),
        'paired_sign_flips':int(flipped.sum()),'paired_sign_flips_both_abs_ge_0p25':int((flipped & paired.strict_parent_A.abs().ge(.25) & old.strict_parent_A.abs().ge(.25)).sum()),
        'parent_score_joint_changed':int(parent_diff.gt(1e-10).sum()),'parent_score_joint_max_abs_difference':float(parent_diff.max()),
        'emergent_curated_forms':int(read('emergent_kinase_evidence').form_id.nunique()),
        'ineligible_raw_postreference_rows':int(ineligible.sum()),
        'ineligible_exported_eligible_A':int(detection.loc[ineligible,'eligible_A'].notna().sum()),
        'PF01255_paired':{str(t):float(paired.loc[('PF01255',t),'strict_parent_A']) for t in [15,180]}}
    expected = {'primary_comparisons':11920,'profiles_v1':3948,'strict_v1_available':11451,
        'paired_available':11451,'complete_available':11406,'comparisons_with_partial_peptide':8509,
        'paired_changed_gt_1e10':2363,'paired_difference_ge_0p1':54,'paired_difference_ge_0p25':7,
        'paired_difference_ge_0p5':2,'paired_sign_flips':27,'paired_sign_flips_both_abs_ge_0p25':0,
        'parent_score_joint_changed':132,'emergent_curated_forms':25,'ineligible_raw_postreference_rows':1025,
        'ineligible_exported_eligible_A':0}
    for key,value in expected.items():
        assert results[key]==value, (key,results[key],value)
    results['reviewer_diagnostics_match']=True
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,required=True); p.add_argument('--actual',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=validate(args.reference,args.actual)
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='reference_tables'},indent=2))
