"""Version-declared, exact run/precursor evidence joins. No basename matching.

Supported export schema is pinned separately from DIA-NN's numeric release. Run
minimum confidence is kept at precursor scope, never replicated as site posterior.
TSV is projected/chunked; Parquet uses optional pyarrow record batches.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .annotation_registry import digest
from .astra_inputs import stable_id
from .study_design import stable_id as form_key

VERSION='diann_observations.v1'
SUPPORTED={'1.8.1','1.8.2','1.8.2 beta 27','2.0','2.1','2.2','2.3','2.4','2.5','2.6','2.7','2.7.0'}
REQUIRED=['Run','Precursor.Id','Modified.Sequence','Precursor.Charge','Protein.Group','Protein.Ids']
OPTIONAL=['PTM.Site.Confidence','Lib.PTM.Site.Confidence','Site.Occupancy.Probabilities','Protein.Sites',
          'Q.Value','Peptidoform.Q.Value','Global.Peptidoform.Q.Value','PG.Q.Value','Global.PG.Q.Value',
          'Precursor.Quantity','Precursor.Normalised']
OPTIONAL += ['Run.Index','Channel','Precursor.Lib.Index','Global.Q.Value','Lib.Peptidoform.Q.Value','PEP']
COLUMNS=['schema_version','observation_id','source_file_sha256','source_row_id','diann_version','injection_id',
 'input_column','raw_run','raw_precursor_id','raw_modified_sequence','canonical_modified_sequence','charge','protein_group',
 'form_id','accession_candidates','localization_metric_name','localization_metric_value','localization_scope',
 'library_localization_confidence','site_occupancy_probabilities_raw','protein_sites_raw','identification_q_values',
 'quantification_quality','matrix_row_index','matrix_intensity','quantification_contributor','match_status','restriction_reasons']
COLUMNS.append('source_fields_json')


def batches(path):
    if Path(path).suffix.lower()=='.parquet':
        try:import pyarrow.parquet as pq
        except ImportError:raise ValueError('parquet_dependency_unavailable: install pinned pyarrow') from None
        reader=pq.ParquetFile(path);columns=reader.schema.names
        if set(REQUIRED)-set(columns):raise ValueError('unsupported_diann_schema:'+','.join(sorted(set(REQUIRED)-set(columns))))
        for batch in reader.iter_batches(batch_size=50000,columns=[c for c in REQUIRED+OPTIONAL if c in columns]):yield batch.to_pandas()
    else:
        columns=pd.read_csv(path,sep='\t',nrows=0).columns
        if set(REQUIRED)-set(columns):raise ValueError('unsupported_diann_schema:'+','.join(sorted(set(REQUIRED)-set(columns))))
        yield from pd.read_csv(path,sep='\t',usecols=[c for c in REQUIRED+OPTIONAL if c in columns],chunksize=50000)


def observations(path, version, pr, design, crosswalk_path=None, *, exact_group_sets=False):
    if not path:return pd.DataFrame(columns=COLUMNS),{'status':'unavailable','reason':'diann_report_not_provided','parser_version':VERSION}
    if version not in SUPPORTED:raise ValueError('unsupported_diann_version: explicit supported version required')
    sha=digest(path);injections={r['input_column']:r['injection_id'] for r in design['injections']}
    from .contrast_quantification import PTM_CODES
    target_token=f"(UniMod:{PTM_CODES.get(design['study']['ptm_type'],-1)})"
    run_map=dict(injections)
    channel_crosswalk=False
    if crosswalk_path:
        cross=pd.read_csv(crosswalk_path,sep=None,engine='python',dtype=str,keep_default_na=False)
        if not {'Run','input_column','injection_id'}<=set(cross):raise ValueError('crosswalk_schema_required')
        channel_crosswalk=exact_group_sets and 'Channel' in cross
        if cross.duplicated(['Run','Channel'] if channel_crosswalk else ['Run']).any() or cross.injection_id.duplicated().any():raise ValueError('crosswalk_not_one_to_one')
        if any(injections.get(r.input_column)!=r.injection_id for r in cross.itertuples()):raise ValueError('crosswalk_design_conflict')
        run_map={(r.Run,r.Channel) if channel_crosswalk else r.Run:r.injection_id for r in cross.itertuples()}
    columns={v:k for k,v in injections.items()};lookup={}
    group_key=lambda value:tuple(sorted(str(value).split(';'))) if exact_group_sets else str(value)
    for idx,r in pr.iterrows():
        key=(str(r['Precursor.Id']),str(r['Modified.Sequence']),group_key(r['Protein.Group']),int(r['Precursor.Charge']))
        lookup.setdefault(key,[]).append(idx)
    out=[];seen={};row_number=0
    for batch in batches(path):
        for r in batch.to_dict('records'):
            row_number+=1;reasons=[]
            raw_key=(str(r['Run']),str(r.get('Channel',''))) if channel_crosswalk else str(r['Run'])
            inj=run_map.get(raw_key);col=columns.get(inj)
            try:
                charge=int(r['Precursor.Charge'])
                if float(r['Precursor.Charge'])!=charge:raise ValueError('fractional charge')
            except (ValueError,TypeError):charge=None;reasons.append('invalid_charge')
            key=(str(r['Precursor.Id']),str(r['Modified.Sequence']),group_key(r['Protein.Group']),charge)
            hits=lookup.get(key,[]);index=hits[0] if len(hits)==1 else None
            if not inj:reasons.append('run_crosswalk_required')
            if not hits:reasons.append('matrix_precursor_unmatched')
            if len(hits)>1:reasons.append('matrix_precursor_ambiguous')
            if exact_group_sets and index is not None and group_key(r['Protein.Ids'])!=group_key(pr.at[index,'Protein.Ids']):
                reasons.append('report_matrix_accession_conflict')
            value=pd.to_numeric(pd.Series([r.get('PTM.Site.Confidence')]),errors='coerce').iloc[0]
            library=pd.to_numeric(pd.Series([r.get('Lib.PTM.Site.Confidence')]),errors='coerce').iloc[0]
            for metric,v in [('run_confidence',value),('library_confidence',library)]:
                raw=r.get('PTM.Site.Confidence' if metric=='run_confidence' else 'Lib.PTM.Site.Confidence')
                if pd.notna(raw) and (pd.isna(v) or not np.isfinite(v) or not 0<=v<=1):reasons.append('invalid_'+metric)
            q={k:(None if pd.isna(r.get(k)) else r.get(k)) for k in OPTIONAL if k.endswith('Q.Value') and k in r}
            for k,v in q.items():
                if v is not None:
                    try:valid=np.isfinite(float(v)) and 0<=float(v)<=1
                    except (ValueError,TypeError):valid=False
                    if not valid:reasons.append('invalid_'+k)
            intensity=float(pr.at[index,col]) if index is not None and col and pd.notna(pr.at[index,col]) else np.nan
            contributor=np.isfinite(intensity) and intensity>0
            if not contributor:reasons.append('not_quantification_contributor')
            record={'schema_version':VERSION,'observation_id':stable_id('observation',[sha,row_number]),'source_file_sha256':sha,
                'source_row_id':row_number,'diann_version':version,'injection_id':inj,'input_column':col,'raw_run':r['Run'],
                'raw_precursor_id':r['Precursor.Id'],'raw_modified_sequence':r['Modified.Sequence'],
                'canonical_modified_sequence':r['Modified.Sequence'],'charge':charge,'protein_group':r['Protein.Group'],
                'form_id':form_key('form',str(pr.at[index,'Protein.Group'] if exact_group_sets else r['Protein.Group'])+'|'+str(r['Modified.Sequence'])) if index is not None and target_token in str(r['Modified.Sequence']) else None,
                'accession_candidates':r['Protein.Ids'],'localization_metric_name':'PTM.Site.Confidence',
                'localization_metric_value':value,'localization_scope':'run_precursor_minimum_occupied_site',
                'library_localization_confidence':library,'site_occupancy_probabilities_raw':r.get('Site.Occupancy.Probabilities'),
                'protein_sites_raw':r.get('Protein.Sites'),'identification_q_values':json.dumps(q,sort_keys=True),
                'quantification_quality':'matrix_positive' if contributor else 'matrix_unobserved','matrix_row_index':index,
                'matrix_intensity':intensity,'quantification_contributor':bool(contributor),'match_status':'matched' if not reasons else 'restricted',
                'restriction_reasons':';'.join(reasons),
                'source_fields_json':json.dumps({k:None if pd.isna(v) else str(v) if isinstance(v,float) and not np.isfinite(v) else v for k,v in r.items()},ensure_ascii=False,sort_keys=True,allow_nan=False)}
            duplicate=(raw_key,*key)
            if duplicate in seen:
                # Neither highest confidence nor first row wins; all duplicate keys remain visible.
                record['restriction_reasons']+=';duplicate_observation_key';record['match_status']='conflict'
                for old in seen[duplicate]:
                    out[old]['restriction_reasons']+=';duplicate_observation_key';out[old]['match_status']='conflict'
            seen.setdefault(duplicate,[]).append(len(out));out.append(record)
    return pd.DataFrame(out,columns=COLUMNS),{'status':'audit_available','parser_version':VERSION,'rows':len(out),
        'source_sha256':sha,'version':version,'confidence_semantics':'minimum_occupied_site_not_each_site_posterior',
        'site_probability_parser':'raw_only_not_supported','official_real_report_parity':'not_verified'}


def apply_observation_policy(pr, obs, design, policy):
    mode=policy.get('mode','audit_only')
    if mode=='audit_only':return pr.copy()
    if mode!='validated_observations':raise ValueError('unknown_observation_policy')
    if obs.empty:raise ValueError('validated_observations_requires_diann_report')
    if policy.get('normalization_scope')!='recompute_once_after_filter':raise ValueError('declare_observation_normalization_scope')
    threshold=policy.get('minimum_run_confidence');maxq=policy.get('maximum_precursor_q')
    if threshold is None or maxq is None or not 0<=threshold<=1 or not 0<=maxq<=1:raise ValueError('explicit_observation_thresholds_required')
    result=pr.copy();columns=[i['input_column'] for i in design['injections']]
    # Only modified precursor evidence is filtered. PG and strict-unmodified inputs
    # retain their own provenance; neither is assigned fictitious localization.
    target=pr['Modified.Sequence'].ne(pr['Stripped.Sequence']);result.loc[target,columns]=np.nan
    for r in obs.loc[obs.match_status.eq('matched')].to_dict('records'):
        q=json.loads(r['identification_q_values']).get('Q.Value')
        if pd.notna(r['localization_metric_value']) and r['localization_metric_value']>=threshold and q is not None and float(q)<=maxq:
            idx=int(r['matrix_row_index'])
            if target.at[idx]:result.at[idx,r['input_column']]=pr.at[idx,r['input_column']]
    return result
