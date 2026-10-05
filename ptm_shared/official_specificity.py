"""Optional official PhosX PSSM scorer; distinct from full ranked enrichment.

Uses the installed pinned implementation. A manifest must explicitly authorize
local use and derived-result export; resource redistribution is checked elsewhere.
"""
import importlib.metadata
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .annotation_registry import digest
from .astra_inputs import stable_id

PHOSX_VERSION='0.23.1'
PHOSX_COMMIT='b556f59c39f099b5f3fcb574a8a70856c3fdc82c'


def score_phosx(sites,entries,manifest):
    from .kinase_specificity import COLUMNS
    path=Path(manifest);meta=json.loads(path.read_text());state={**meta,'adapter':'phosx_official_pssm.v1','official_full_method_executed':False}
    if meta.get('local_use_permission')!='permitted' or meta.get('derived_export_permission')!='permitted':
        return pd.DataFrame(columns=COLUMNS),{**state,'status':'license_unresolved'}
    try:
        if importlib.metadata.version('phosx')!=PHOSX_VERSION:raise ImportError('version_mismatch')
        from phosx.utils import read_pssms,read_pssm_score_quantiles
        from phosx.pssms import pssm_scoring,quantile_scaling,binarise_pssm_scores
    except (ImportError,importlib.metadata.PackageNotFoundError) as e:
        return pd.DataFrame(columns=COLUMNS),{**state,'status':'resource_unavailable','reason':'pinned_phosx_environment_unavailable'}
    files={}
    for name in ('matrix','background'):
        file=(path.parent/meta[name+'_file']).resolve()
        if not file.is_relative_to(path.parent.resolve()) or not file.is_file() or digest(file)!=meta[name+'_sha256']:raise ValueError('official_resource_checksum_invalid:'+name)
        files[name]=file
    matrices=read_pssms(str(files['matrix']));background=read_pssm_score_quantiles(str(files['background']))
    offsets=list(next(iter(matrices.values())).index)
    if offsets!=list(range(-5,5)) or any(list(m.index)!=offsets for m in matrices.values()):raise ValueError('official_matrix_offsets_unsupported')
    permitted=set(meta['supported_center_residues']);fasta={e['accession']:e for e in entries};eligible=[];excluded=[]
    for site in sites.to_dict('records'):
        sequence=fasta[site['input_accession']]['sequence'];pos=int(site['input_position'])-1
        window=''.join(sequence[pos+o] if 0<=pos+o<len(sequence) else '_' for o in offsets)
        reason='unsupported_center_residue' if sequence[pos] not in permitted else 'priming_context_unresolved' if site.get('form_modification_count',1)>1 else 'unsupported_residue' if any(a not in set(next(iter(matrices.values())).columns)|{'_'} for a in window) else None
        (excluded if reason else eligible).append({**site,'window':window,'reason':reason})
    unique=sorted({r['window'] for r in eligible});scored=pd.DataFrame([pssm_scoring(seq,matrices) for seq in unique],index=unique)
    scaled=scored.apply(quantile_scaling,args=[{k:np.sort(background[k].to_numpy(float)) for k in background}],axis=0) if unique else scored.copy()
    top=int(meta.get('n_top_kinases',5));minimum=float(meta.get('min_quantile',.90 if permitted=={'Y'} else .95))
    if top>=len(matrices):raise ValueError('official_top_rank_exceeds_candidate_universe')
    selected=binarise_pssm_scores(scaled,n=top,m=minimum) if unique else scaled.copy();rows=[]
    for site in eligible+excluded:
        for kinase in sorted(matrices):
            enzyme=(meta.get('enzyme_mapping') or {}).get(kinase,{})
            # Matrix label is an assayed human enzyme; inferred organism remains
            # unknown until the resource supplies verified entity mapping.
            accession=enzyme.get('accession',kinase);taxon=enzyme.get('taxon');reason=site['reason'];w=site['window']
            rows.append({'specificity_id':stable_id('official_specificity',[site['site_id'],site['form_id'],kinase,meta['matrix_sha256'],meta['background_sha256'],PHOSX_COMMIT]),
                **{k:site[k] for k in ('site_id','form_id','measurement_group_id','substrate_taxon')},
                'candidate_id':stable_id('specificity_candidate',[taxon,accession]),'kinase_accession':accession,'kinase_taxon':taxon,
                'reference_assay_taxon':meta['assay_taxon'],'resource_id':meta['resource_id'],
                'matrix_sha256':meta['matrix_sha256'],'background_sha256':meta['background_sha256'],'sequence_window':w,
                'score':None if reason else float(scored.at[w,kinase]),'percentile':None if reason else float(scaled.at[w,kinase]*100),
                'percentile_scale':'0_to_100_reference_background','rank':None,'status':'not_evaluable' if reason else 'scored',
                'restriction_reasons':reason or 'assay_compatibility_not_current_cell_relation','edge_type':'experimental_specificity_prediction',
                'official_parity_status':'official_function_invoked_resource_specific_parity_separate',
                'membership_selected':False if reason else bool(selected.at[w,kinase]),'selection_policy_id':'PhosX-0.23.1.binarise_pssm_scores',
                'selection_threshold':minimum*100,'membership_weight':0 if reason else float(selected.at[w,kinase]),
                'selection_reason':reason or ('official_percentile_top_rank_pass' if selected.at[w,kinase] else 'official_percentile_or_rank_below_policy')})
    columns=COLUMNS+['membership_selected','selection_policy_id','selection_threshold','membership_weight','selection_reason']
    out=pd.DataFrame(rows,columns=columns)
    return out,{**state,'status':'official_pssm_scored','code_version':PHOSX_VERSION,'code_commit':PHOSX_COMMIT,
        'matrix_offsets':offsets,'terminal_policy':'official_underscore_neutral_factor','n_top_kinases':top,'min_quantile':minimum,
        'official_parity_status':'official_function_invoked; full_method_parity_separate','scope':'PSSM_selection_only_not_full_PhosX_activity'}
