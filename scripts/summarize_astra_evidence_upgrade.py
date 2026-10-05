"""Compare actual package populations without equating rows with active kinases."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import pandas as pd


def metrics(root):
    def table(name):
        p=root/(name+'.csv')
        return pd.read_csv(p,low_memory=False) if p.exists() else pd.DataFrame()
    forms=table('quant/summary');primary=table('quant/primary_A_input')
    edges=table('kinase/kinase_candidate_edges');profiles=table('kinase/kinase_temporal_profiles')
    calls=table('science/kinase_calls')
    out={'forms':len(forms),'parent_eligible_forms':int(forms.primary_adjustment_eligible.sum()),
         'primary_comparison_rows':len(primary),
         'repeated_joint_comparison_rows':int((primary.reference_joint_n.ge(2)&primary.target_joint_n.ge(2)).sum()),
         'site_mapping_rows_not_independent_sites':len(table('quant/site_mapping')),
         'candidate_entities_not_activity_calls':edges.candidate_id.nunique(),'candidate_edges':len(edges),
         'profile_rows_candidate_contrast_track':len(profiles),
         'calibrated_calls':int(calls.resolution.ne('no_call').sum()) if len(calls) else 0,
         'measurement_observations':len(table('science/measurement_observations')),
         'observation_sites':len(table('science/observation_sites')),
         'specificity_score_pairs':len(table('science/specificity_scores')),
         'protein_groups':table('quant/protein_contrasts').protein_group.nunique()}
    for track in ('curated_A','motif_A','localized_A','specificity_A'):
        subset=profiles.loc[profiles.track.eq(track)]
        out[track+'_with_substrates']=int(subset.n_sites.gt(0).sum())
        out[track+'_operational_coverage']=int(subset.coverage_adequate.sum())
    for name in ('science/localization_by_contrast','temporal/interval_contrasts','temporal/group_excluded_cowave','kinase/method_scores'):
        out[name+'_rows']=len(table(name))
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('baseline','current','output'):p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--replay-result',type=Path)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    before,after=metrics(args.baseline),metrics(args.current)
    rows=[]
    for metric in sorted(set(before)|set(after)):
        rows.append({'metric':metric,'population_definition':metric,'before':before.get(metric),'after':after.get(metric),
            'difference':after.get(metric,0)-before.get(metric,0),
            'interpretation':'same population' if before.get(metric)==after.get(metric) else 'versioned evidence output; not biological accuracy gain',
            'baseline_scope':'available_v5_archive_not_requested_g2'})
    pd.DataFrame(rows).to_csv(args.output/'BEFORE_AFTER_METRICS.csv',index=False)
    shutil.copyfile(args.current/'study/input_lineage.csv',args.output/'LOCALIZATION_LINEAGE.csv')
    queries=pd.read_csv(args.current/'references/source_query_ledger.csv')
    queries.groupby(['provider','status'],dropna=False).size().rename('query_records').reset_index().to_csv(args.output/'RESOURCE_COVERAGE.csv',index=False)
    if args.replay_result:shutil.copyfile(args.replay_result,args.output/'REPLAY_VALIDATION.json')
    audit={'baseline_run':json.loads((args.baseline/'provenance.json').read_text())['run_id'],
        'current_run':json.loads((args.current/'provenance.json').read_text())['run_id'],
        'exact_requested_g2_comparison':'not_run_missing_archive','performance_improvement':'not_demonstrated'}
    (args.output/'comparison_scope.json').write_text(json.dumps(audit,indent=2))
    (args.output/'checksums.json').write_text(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in args.output.iterdir() if f.is_file()},indent=2))


if __name__=='__main__':main()
