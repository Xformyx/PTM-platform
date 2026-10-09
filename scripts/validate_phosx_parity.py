"""Independent PhosX 0.23.1 reference calls from frozen Astra measurement tables.

This runner never uses platform scores as expected values. It reconstructs the
FASTA windows and A-ranked input from the original package, invokes official
functions, and optionally compares a new package. No upstream activation step.
"""
import argparse
import hashlib
import importlib.metadata
import json
import multiprocessing
from pathlib import Path
import numpy as np
import pandas as pd
from Bio import SeqIO

ATOL=RTOL=1e-12  # same float64 functions; native five-decimal p/q must agree too


def seeded_pool(processes):
    if processes!=1:raise ValueError('Serial parity worker required')
    return multiprocessing.get_context('spawn').Pool(1,initializer=np.random.seed,initargs=(1729,))


def reference(source,manifest,contrast,output,permutations=10000):
    if importlib.metadata.version('phosx')!='0.23.1':raise ValueError('Requires PhosX 0.23.1')
    from phosx.utils import read_pssms,read_pssm_score_quantiles,read_seqrnk
    from phosx.pssms import pssm_scoring,quantile_scaling,binarise_pssm_scores
    import phosx.kinase_activity as activity
    import phosx.pssm_enrichment as enrichment
    source=Path(source);manifest=Path(manifest);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    meta=json.loads(manifest.read_text());files={}
    for role in ['matrix','background']:
        files[role]=manifest.parent/meta[role+'_file']
        assert hashlib.sha256(files[role].read_bytes()).hexdigest()==meta[role+'_sha256']
    ids=pd.read_csv(source/'science/site_identity_audit.csv',float_precision='round_trip')
    comp=pd.read_csv(source/'quant/comparisons.csv',float_precision='round_trip')
    comp=comp.loc[comp.contrast_id.eq(contrast)&comp.included&comp.A.notna()]
    ids=ids.loc[ids.site_attribution_eligible&ids.form_id.isin(comp.form_id)].copy()
    entries={r.id.split('|')[1] if '|' in r.id else r.id:str(r.seq) for r in SeqIO.parse(source/'inputs/reference.fasta','fasta')}
    matrices=read_pssms(str(files['matrix']));background=read_pssm_score_quantiles(str(files['background']))
    offsets=list(next(iter(matrices.values())).index);alphabet=set(next(iter(matrices.values())).columns)
    eligible=[];excluded=[]
    for row in ids.to_dict('records'):
        seq=entries[row['input_accession']];pos=int(row['input_position'])-1
        window=''.join(seq[pos+i] if 0<=pos+i<len(seq) else '_' for i in offsets)
        reason='unsupported_center_residue' if seq[pos] not in meta['supported_center_residues'] else 'priming_context_unresolved' if row['form_modification_count']>1 else 'unsupported_residue' if set(window)-alphabet-{'_'} else None
        (excluded if reason else eligible).append({**row,'sequence':window,'reason':reason})
    sites=pd.DataFrame(eligible);sites.to_csv(output/'reference_sites.csv',index=False)
    pd.DataFrame(excluded).to_csv(output/'excluded_sites.csv',index=False)
    sequences=sorted(set(sites.sequence));raw=pd.DataFrame([pssm_scoring(s,matrices) for s in sequences],index=sequences)
    scaled=raw.apply(quantile_scaling,args=[{k:np.sort(background[k].to_numpy(float)) for k in background}],axis=0)
    selected=binarise_pssm_scores(scaled,n=meta['n_top_kinases'],m=meta['min_quantile'])
    for name,frame in [('raw',raw),('percentile',scaled*100),('selection',selected)]:frame.to_csv(output/(name+'.csv'))
    rows=[];exclusions=[]
    for group,block in sites.merge(comp[['form_id','A']],on='form_id').groupby('measurement_group_id',sort=True):
        score=float(block.A.median())
        reason='multiple_sequence_windows_within_measurement_group' if block.sequence.nunique()!=1 else 'nonfinite_A' if not np.isfinite(score) else 'official_native_excludes_zero_A' if score==0 else None
        if reason:
            exclusions.append({'measurement_group_id':group,'reason':reason,'forms':block.form_id.tolist(),
                'sites':block.site_id.tolist(),'windows':block.sequence.unique().tolist(),'form_A':block.A.tolist()})
            continue
        rows.append({'measurement_group_id':group,'sequence':block.sequence.iloc[0],'A':score,
            'form_ids':';'.join(sorted(set(block.form_id))),'site_ids':';'.join(sorted(set(block.site_id)))})
    frame=pd.DataFrame(rows).sort_values(['A','measurement_group_id'],ascending=[False,True]).reset_index(drop=True)
    (output/'input_exclusions.json').write_text(json.dumps(exclusions,indent=2)+'\n')
    frame.to_csv(output/'input_bindings.csv',index=False)
    ranked=output/'ranked.tsv';frame[['sequence','A']].to_csv(ranked,sep='\t',index=False,header=False)
    order=read_seqrnk(str(ranked),True,False);order['input_row_index']=order.index
    order.sort_values('Score',ascending=False,inplace=True,ignore_index=True);order.to_csv(output/'input_order.csv',index=False)
    old=activity.Pool,enrichment.Pool;activity.Pool=enrichment.Pool=seeded_pool
    try:
        results,membership=activity.compute_kinase_activities(str(ranked),str(files['matrix']),str(files['background']),
            n_perm=permutations,n_top_kinases=5,min_n_hits=4,min_quantile=.95,n_proc=1,plot_figures=False,ser_thr_only=True,tyr_only=False)
    finally:activity.Pool,enrichment.Pool=old
    results.sort_index().to_csv(output/'native_results.csv');membership.sort_index(axis=1).to_csv(output/'native_membership.csv')
    record={'implementation':'independent_official_functions','version':'0.23.1','contrast_id':contrast,'permutations':permutations,
        'seed':1729,'upstream_activation_evidence':False,'matrix_sha256':meta['matrix_sha256'],'background_sha256':meta['background_sha256'],
        'input_hash':hashlib.sha256(ranked.read_bytes()).hexdigest(),'eligible_sites':len(sites),'excluded_sites':len(excluded),
        'measurement_groups':len(frame),'native_evaluable_kinases':int(results['p value'].notna().sum()),'atol':ATOL,'rtol':RTOL}
    (output/'reference.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def compare(reference_dir,actual):
    reference_dir=Path(reference_dir);actual=Path(actual)
    read=lambda n:pd.read_csv(reference_dir/n,index_col=0,float_precision='round_trip')
    record=json.loads((reference_dir/'reference.json').read_text());cid=record['contrast_id']
    expected={k:read(k+'.csv') for k in ['raw','percentile','selection']}
    scores=pd.read_csv(actual/'science/specificity_scores.csv',float_precision='round_trip')
    assert set(scores.matrix_sha256)=={record['matrix_sha256']}
    assert set(scores.background_sha256)=={record['background_sha256']}
    assert int(scores.status.eq('scored').sum())==record['eligible_sites']*len(expected['raw'].columns)
    assert int(scores.status.eq('not_evaluable').sum())==record['excluded_sites']*len(expected['raw'].columns)
    deltas={'raw_score':0.,'percentile':0.,'native_score_p_q':0.}
    for row in scores.loc[scores.status.eq('scored')].itertuples():
        for col,key in [('score','raw'),('percentile','percentile')]:
            np.testing.assert_allclose(getattr(row,col),expected[key].at[row.sequence_window,row.kinase_accession],rtol=RTOL,atol=ATOL)
            metric='raw_score' if col=='score' else col
            deltas[metric]=max(deltas[metric],abs(getattr(row,col)-expected[key].at[row.sequence_window,row.kinase_accession]))
        assert row.membership_selected==bool(expected['selection'].at[row.sequence_window,row.kinase_accession])
    # Check the emitted sequence itself against the baseline identity, not just score equality.
    sites=pd.read_csv(reference_dir/'reference_sites.csv').set_index(['form_id','site_id'])
    for row in scores.loc[scores.status.eq('scored')].itertuples():
        assert row.sequence_window==sites.loc[(row.form_id,row.site_id),'sequence']
    edges=pd.read_csv(actual/'kinase/kinase_candidate_edges.csv',low_memory=False)
    label=edges.loc[edges.edge_type.eq('experimental_specificity_prediction')].drop_duplicates('candidate_id').set_index('candidate_id').candidate_accession.to_dict()
    method=pd.read_csv(actual/'kinase/method_scores.csv',float_precision='round_trip')
    method=method.loc[method.method_id.eq('PhosX_native_functions')];assert set(method.contrast_id)=={cid}
    native=read('native_results.csv');assert len(method)==len(native)
    for row in method.itertuples():
        r=native.loc[label[row.candidate_id]]
        for col,source in [('native_score','Activity Score'),('method_p','p value'),('method_q','FDR q value')]:
            np.testing.assert_allclose(getattr(row,col),r[source],rtol=RTOL,atol=ATOL,equal_nan=True)
            if pd.notna(r[source]):deltas['native_score_p_q']=max(deltas['native_score_p_q'],abs(getattr(row,col)-r[source]))
    memberships=pd.read_csv(actual/'kinase/method_membership.csv',float_precision='round_trip');expected_members=read('native_membership.csv')
    bindings=pd.read_csv(reference_dir/'input_bindings.csv',float_precision='round_trip')
    order=pd.read_csv(reference_dir/'input_order.csv');ordered=bindings.iloc[order.input_row_index.to_numpy(int)].reset_index(drop=True)
    indexes={v:i for i,v in enumerate(ordered.measurement_group_id)}
    assert len(memberships)==expected_members.size
    for row in memberships.itertuples():
        idx=indexes[row.measurement_group_id];assert row.selected==bool(expected_members.loc[idx,label[row.candidate_id]])
        assert row.sequence==ordered.iloc[idx].sequence
        np.testing.assert_allclose(row.ranking_statistic,ordered.iloc[idx].A,atol=ATOL,rtol=RTOL)
    execution=pd.read_csv(actual/'kinase/method_executions.csv');executed=execution.loc[execution.status.eq('executed')]
    assert executed.input_hash.tolist()==[record['input_hash']]
    result={**record,'passed':True,'scored_rows_compared':int(scores.status.eq('scored').sum()),'native_results_compared':len(method),
        'native_membership_rows_compared':len(memberships),'maximum_absolute_differences':deltas,
        'skip_count':0,'comparison_scope':'raw_score_percentile_selection_native_activity_p_q_and_membership'}
    (reference_dir/'PARITY_RESULTS.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path);p.add_argument('--manifest',type=Path);p.add_argument('--contrast')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--actual',type=Path);p.add_argument('--compare-only',action='store_true')
    a=p.parse_args()
    if not a.compare_only:print(json.dumps(reference(a.source,a.manifest,a.contrast,a.output)))
    if a.actual:print(json.dumps(compare(a.output,a.actual)))


if __name__=='__main__':main()
