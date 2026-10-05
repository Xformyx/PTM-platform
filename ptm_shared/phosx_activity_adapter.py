"""Pinned official PhosX functions with deterministic single-worker process seeds.

This is the native ranked-enrichment track, separate from the descriptive A
footprint. The official scoring, membership, KS, null and FDR routines run intact.
No activation-loop/upstream evidence is silently added.
"""
import argparse
import hashlib
import importlib.metadata
import json
import multiprocessing
from pathlib import Path
import time
import numpy as np

VERSION='phosx_native_adapter.v1'


def execute(ranked_input,matrix,background,output,*,residue='ST',permutations=10000,seed=1729):
    if importlib.metadata.version('phosx')!='0.23.1':raise ValueError('pinned_PhosX_0.23.1_required')
    import phosx.kinase_activity as activity
    import phosx.pssm_enrichment as enrichment
    from phosx.utils import read_seqrnk
    if residue not in {'ST','Y'}:raise ValueError('unsupported_center_residue_class')
    if permutations<100:raise ValueError('at_least_100_method_null_permutations_required')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    # Preserve the official parser's exact filter and sort, including tied ranks.
    # This row order, rather than caller array position, identifies memberships.
    ranked=read_seqrnk(str(ranked_input),residue=='ST',residue=='Y')
    ranked['input_row_index']=ranked.index
    ranked.sort_values(by='Score',ascending=False,inplace=True,ignore_index=True)
    ranked.to_csv(output/'native_input_order.tsv',sep='\t',index=False)
    context=multiprocessing.get_context('spawn')
    def seeded_pool(processes):
        if processes!=1:raise ValueError('pinned_serial_worker_required')
        return context.Pool(processes=1,initializer=np.random.seed,initargs=(seed,))
    old=(activity.Pool,enrichment.Pool);activity.Pool=enrichment.Pool=seeded_pool
    start=time.monotonic()
    try:
        results,membership=activity.compute_kinase_activities(str(ranked_input),str(matrix),str(background),n_perm=permutations,
            n_top_kinases=5,min_n_hits=4,min_quantile=.90 if residue=='Y' else .95,n_proc=1,
            plot_figures=False,ser_thr_only=residue=='ST',tyr_only=residue=='Y')
    finally:activity.Pool,enrichment.Pool=old
    # Upstream untested-kinase rows can originate from a set. Canonical label
    # order changes presentation only; preserve every official value and NA.
    results=results.sort_index();membership=membership.sort_index(axis=1)
    # Native zero for untested activity must not become measured inactivity.
    results.to_csv(output/'native_results.tsv',sep='\t');membership.to_csv(output/'native_membership.tsv',sep='\t')
    typed=results.copy();typed['status']=np.where(typed['p value'].notna(),'computed_method_enrichment','insufficient_coverage')
    typed.loc[typed['p value'].isna(),'Activity Score']=np.nan
    typed['statistical_unit']='ranked_observed_site';typed['biological_p_value']=np.nan
    typed['direction_semantics']='enrichment_at_ranked_list_extremes_not_causal_activation'
    typed.to_csv(output/'typed_results.tsv',sep='\t')
    hashes=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    record={'method_id':'PhosX_native_functions','method_version':'0.23.1','code_commit':'b556f59c39f099b5f3fcb574a8a70856c3fdc82c',
        'adapter':VERSION,'status':'executed','input_universe_hash':hashes(ranked_input),'matrix_sha256':hashes(matrix),
        'background_sha256':hashes(background),'eligible_site_count':len(read_seqrnk(str(ranked_input),residue=='ST',residue=='Y')),
        'parameters':{'residue':residue,'permutations':permutations,'seed':seed,'n_proc':1,'min_n_hits':4,'n_top_kinases':5,
                      'min_quantile':.90 if residue=='Y' else .95,'upstream_activation_evidence':False},
        'seed_policy':'spawned_single_worker_numpy_seed; official_null_algorithm_unchanged',
        'score_name':'Activity Score','method_p':'official_rank_permutation_p','method_q':'official_BH_FDR',
        'null_model':'rank_permutation_over_observed_sites_not_biological_units','multiple_testing_family':'evaluable_kinases_of_residue_class',
        'runtime_seconds':time.monotonic()-start,'output_hash':hashes(output/'native_results.tsv'),
        'independent_benchmark':'not_performed_by_adapter','official_parity':'official_functions_invoked_not_equivalence_to_2024_release'}
    (output/'execution.json').write_text(json.dumps(record,indent=2,allow_nan=False))
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('input','matrix','background','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--residue',choices=['ST','Y'],default='ST');p.add_argument('--permutations',type=int,default=10000);p.add_argument('--seed',type=int,default=1729)
    a=p.parse_args();execute(a.input,a.matrix,a.background,a.output,residue=a.residue,permutations=a.permutations,seed=a.seed)


if __name__=='__main__':main()
