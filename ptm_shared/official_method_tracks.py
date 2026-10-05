"""Native PhosX execution boundary; only permitted pinned resources are consumed."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd
from .astra_inputs import stable_id
from .annotation_registry import digest
from .evidence_methods import METHOD_COLUMNS

MEMBER_COLUMNS=['method_membership_id','candidate_id','contrast_id','method_id','measurement_group_id','form_ids','site_ids',
    'sequence','ranking_statistic','selected','input_universe_hash']
EXEC_COLUMNS=['execution_id','method_id','contrast_id','status','reason','parameters','runtime_seconds','input_hash','output_hash','log']


def execute_tracks(scientific,inputs,context,resource):
    empty=lambda:(pd.DataFrame(columns=METHOD_COLUMNS+['native_score']),pd.DataFrame(columns=MEMBER_COLUMNS),pd.DataFrame(columns=EXEC_COLUMNS))
    path=inputs.get('_LOCAL_SPECIFICITY',inputs.get('SPECIFICITY'))
    if not path:return empty()
    manifest=json.loads(Path(path).read_text())
    if manifest.get('adapter')!='phosx_official.v1' or resource.get('status')!='official_pssm_scored':return empty()
    if manifest.get('local_use_permission')!='permitted' or manifest.get('derived_export_permission')!='permitted':return empty()
    comparisons=scientific['quant/comparisons'];ids=scientific['science/site_identity_audit'];scores=scientific['science/specificity_scores']
    edges=scientific['kinase/kinase_candidate_edges'];by_score=edges.loc[edges.edge_type.eq('experimental_specificity_prediction')].set_index('specificity_id').candidate_id.to_dict()
    candidate_by_label={}
    for r in scores.itertuples():candidate_by_label[r.kinase_accession]=by_score.get(r.specificity_id)
    sequence_map=scores.loc[scores.status.eq('scored')].drop_duplicates(['form_id','site_id']).set_index(['form_id','site_id']).sequence_window.to_dict()
    eligible=ids.loc[ids.site_attribution_eligible.astype(bool)].copy()
    values=[];members=[];executions=[];settings=context.get('science',{}).get('official_methods',{}).get('PhosX',{})
    residues=set(manifest['supported_center_residues']);kind='Y' if residues=={'Y'} else 'ST'
    # Input site labels are never mapped to human by gene capitalization.
    for contrast,g in comparisons.loc[comparisons.included & comparisons.A.notna()].groupby('contrast_id',sort=True):
        matched=eligible.merge(g[['form_id','A']],on='form_id');rows=[]
        for group,block in matched.groupby('measurement_group_id',sort=True):
            keys={(r.form_id,r.site_id) for r in block.itertuples()};windows={sequence_map[k] for k in keys if k in sequence_map}
            if len(windows)!=1:continue
            window=next(iter(windows))
            if window[5] not in residues:continue
            score=float(block.A.median())
            if not np.isfinite(score) or score==0:continue # official native input policy, explicitly recorded
            rows.append({'measurement_group_id':group,'form_ids':';'.join(sorted(set(block.form_id))),
                'site_ids':';'.join(sorted(set(block.site_id))),'sequence':window,'A':score})
        # Equal windows from different measured groups remain separate observations;
        # group exclusion/sensitivity is provided in the parent evidence layer.
        frame=pd.DataFrame(rows,columns=['measurement_group_id','form_ids','site_ids','sequence','A'])
        if not len(frame):continue
        frame=frame.sort_values(['A','measurement_group_id'],ascending=[False,True]).reset_index(drop=True)
        with tempfile.TemporaryDirectory(prefix='ptm-native-phosx-') as work:
            work=Path(work);ranked=work/'ranked.tsv';frame[['sequence','A']].to_csv(ranked,sep='\t',index=False,header=False)
            output=work/'native';perms=int(settings.get('permutations',10000));seed=int(settings.get('seed',1729))
            command=[sys.executable,'-m','ptm_shared.phosx_activity_adapter','--input',str(ranked),
                '--matrix',str(Path(path).parent/manifest['matrix_file']),'--background',str(Path(path).parent/manifest['background_file']),
                '--output',str(output),'--residue',kind,'--permutations',str(perms),'--seed',str(seed)]
            # Fresh process supports Celery prefork workers and isolates PRNG state.
            try:
                result=subprocess.run(command,capture_output=True,text=True,timeout=int(settings.get('timeout_seconds',14400)),shell=False)
                reason=None if result.returncode==0 else 'native_process_failed'
                log=(result.stderr+result.stdout).replace(str(work),'<method-work-directory>')
            except subprocess.TimeoutExpired:
                reason='native_method_timeout';log='Native method time budget exhausted; quantification retained.'
            record=json.loads((output/'execution.json').read_text()) if not reason else {}
            context.setdefault('_method_runtime',[]).append({'method':'PhosX','contrast_id':contrast,
                'runtime_seconds':record.get('runtime_seconds'),'log':log,'status':reason or 'executed'})
            executions.append({'execution_id':stable_id('native_method',['PhosX',contrast,digest(ranked),manifest['matrix_sha256'],perms,seed]),
                'method_id':'PhosX_native_functions','contrast_id':contrast,'status':'executed' if not reason else 'failed','reason':reason,
                'parameters':json.dumps({**record.get('parameters',{}),'ranking_statistic':'A','zero_policy':'official_native_excludes_zero',
                    'input_unit':'one_per_measurement_group','source_pin_scope':'declared_local_resource'},sort_keys=True),
                'runtime_seconds':None,'input_hash':digest(ranked),'output_hash':record.get('output_hash'),
                'log':'See methods/native_execution_runtime.json; timing excluded from scientific replay'})
            if reason:continue
            native=pd.read_csv(output/'native_results.tsv',sep='\t',index_col=0);membership=pd.read_csv(output/'native_membership.tsv',sep='\t',index_col=0)
            order=pd.read_csv(output/'native_input_order.tsv',sep='\t')
            if len(order)!=len(frame) or len(membership)!=len(frame):raise ValueError('native_membership_input_row_mismatch')
            native_frame=frame.iloc[order.input_row_index.to_numpy(int)].reset_index(drop=True)
            if native_frame.sequence.tolist()!=order.Sequence.tolist() or not np.allclose(native_frame.A,order.Score,rtol=1e-12,atol=1e-12):raise ValueError('native_membership_identity_mismatch')
            for kinase,r in native.iterrows():
                mapping=(manifest.get('enzyme_mapping') or {}).get(kinase,{})
                candidate=candidate_by_label.get(mapping.get('accession',kinase))
                if not candidate:continue
                p=r['p value'];tested=pd.notna(p);contributing=[]
                if kinase in membership:
                    for i,selected in enumerate(membership[kinase]):
                        if i>=len(frame):raise ValueError('native_membership_input_row_mismatch')
                        observation=native_frame.iloc[i]
                        mid=stable_id('native_membership',[candidate,contrast,observation.measurement_group_id,manifest['matrix_sha256']])
                        members.append({'method_membership_id':mid,'candidate_id':candidate,'contrast_id':contrast,'method_id':'PhosX_native_functions',
                            **{k:observation[k] for k in ('measurement_group_id','form_ids','site_ids','sequence')},'ranking_statistic':observation.A,
                            'selected':bool(selected),'input_universe_hash':digest(ranked)})
                        if selected:contributing.append(mid)
                values.append({'method_result_id':stable_id('method_result',['PhosX',candidate,contrast,manifest['matrix_sha256']]),
                    'method_id':'PhosX_native_functions','method_version':'0.23.1','candidate_id':candidate,'contrast_id':contrast,
                    'score_name':'Activity Score','score':r['Activity Score'] if tested else None,'native_score':r['Activity Score'],
                    'direction_semantics':'signed_rank_enrichment_not_causal_activation','method_p':p,'method_q':r['FDR q value'],
                    'null_model':'official_site_rank_permutation_not_biological_units','multiple_testing_family':contrast+':PhosX:'+kind,
                    'eligible_site_count':len(contributing),'universe_count':len(frame),'input_universe_hash':digest(ranked),
                    'membership_ids':';'.join(contributing),'status':'computed_method_enrichment' if tested else 'insufficient_coverage',
                    'statistical_unit':'measurement_group','biological_p_value':None})
    return pd.DataFrame(values,columns=METHOD_COLUMNS+['native_score']),pd.DataFrame(members,columns=MEMBER_COLUMNS),pd.DataFrame(executions,columns=EXEC_COLUMNS)
