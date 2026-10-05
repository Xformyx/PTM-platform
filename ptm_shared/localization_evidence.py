"""DIA-NN measurement → sequence site → contrast, without changing intensities.

Grammar contract is documented by DIA-NN README 5598ebbbe7a5313434f4986aa24262337ce6d5b0
and its discussion #1130. Documented-schema support is NOT real-report parity.
Unknown encodings, channels, conflicting rows and probabilities fail closed.
"""
from collections import defaultdict
import json
import re
import numpy as np
import pandas as pd
from .annotation_registry import digest
from .astra_inputs import stable_id

VERSION='localization_evidence.v2'
DOCUMENT='https://github.com/vdemichev/DiaNN/blob/5598ebbbe7a5313434f4986aa24262337ce6d5b0/README.md'
SITE_COLUMNS=['observation_site_id','observation_id','identity_id','form_id','site_id','injection_id',
 'modification_id','individual_site_posterior','site_probability','run_minimum_confidence','probability_scope',
 'evidence_source','source_file_sha256','source_row_id','site_report_source_sha256','site_report_row_id','parser_version','parser_contract','assignment_status',
 'original_field_value','peptide_offset','quantification_contributor','restriction_reasons']
LOCAL_COLUMNS=['localization_id','form_id','site_id','contrast_id','threshold','policy_id',
 'reference_joint_n','target_joint_n','reference_reported_n','target_reported_n',
 'reference_evaluable_n','target_evaluable_n','reference_pass_n','target_pass_n',
 'reference_observation_ids','target_observation_ids','supporting_observation_site_ids',
 'quantification_contributor_ids','localized_eligible','measurement_status','exclusion_reasons']
POLICY={'policy_id':'all_joint_contributors_localized.v1','threshold':.75,
        'aggregation':'all_contributing_precursors_in_every_joint_injection_both_sides',
        'scope':'operational_evidence_gate_not_calibrated_kinase_accuracy'}


def probability_sequence(raw, modified, charge, modification='UniMod:21'):
    """Consume the entire curly-brace grammar; never search a nearby residue."""
    if not isinstance(raw,str) or not raw:return {},'missing_input'
    pattern=r'\(UniMod:\d+\)|\{[^{}]+\}|[A-Z]|\d+|_'
    tokens=re.findall(pattern,raw)
    if ''.join(tokens)!=raw:return {},'unsupported_schema'
    sequence=[];values={};offset=0;last=''
    for i,token in enumerate(tokens):
        if len(token)==1 and token.isalpha():sequence.append(token);offset+=1
        elif token.startswith('{'):
            try:p=float(token[1:-1])
            except ValueError:return {},'invalid_probability'
            if not np.isfinite(p) or not 0<=p<=1:return {},'invalid_probability'
            if offset==0 or offset in values:return {},'ambiguous_semantics'
            if sequence[-1] not in 'STY' or last.startswith('(') and last!='('+modification+')':
                return {},'unsupported_modification_probability'
            values[offset]=p
        elif token.isdigit():
            if i!=len(tokens)-1 or int(token)!=charge:return {},'charge_or_sequence_mismatch'
        elif token=='_':
            if i not in (0,len(tokens)-1):return {},'unsupported_schema'
        last=token
    backbone=re.sub(r'\([^)]*\)','',str(modified)).strip('_')
    if ''.join(sequence)!=backbone:return {},'sequence_mismatch'
    return values,'parsed' if values else 'missing_input'


def protein_sites(raw):
    if raw is None or pd.isna(raw) or not str(raw):return None,'not_provided'
    raw=str(raw);groups=re.findall(r'\[([^\[\]]+)\]',raw)
    if not groups or re.sub(r'\[[^\[\]]+\]','',raw).strip('; '):return None,'unsupported_protein_sites_schema'
    result=set()
    for group in groups:
        accession,sep,positions=group.partition(':')
        if not sep:return None,'unsupported_protein_sites_schema'
        for site in positions.split(','):
            if not re.fullmatch('[STY][1-9][0-9]*',site):return None,'unsupported_protein_sites_schema'
            result.add((accession,site[0],int(site[1:])))
    return result,'parsed'


def read_site_report(path,observations,version):
    """Preserve all source rows, including unoccupied and unmatched site rows."""
    columns=['site_report_row_id','source_file_sha256','observation_id','Protein','Site','Residue',
             'Modification','Occupied','Probability','source_fields_json','status','restriction_reasons']
    if not path:return pd.DataFrame(columns=columns),{'status':'missing_input'}
    frame=pd.read_parquet(path) if str(path).endswith('.parquet') else pd.read_csv(path,sep='\t')
    keys=['Run.Index','Channel','Precursor.Lib.Index'];required=keys+['Protein','Site','Residue','Modification','Occupied','Probability']
    sha=digest(path)
    if set(required)-set(frame):return pd.DataFrame(columns=columns),{'status':'unsupported_schema','missing_columns':sorted(set(required)-set(frame)),'source_sha256':sha}
    if version not in {'2.7','2.7.0'}:
        return pd.DataFrame(columns=columns),{'status':'ambiguous_semantics','reason':'site_report_version_not_documented','source_sha256':sha}
    index=defaultdict(list)
    def key(row):
        # Numeric index columns are typed identifiers, not filename heuristics.
        def value(k):
            v=row.get(k)
            if v is None or pd.isna(v):return ''
            if k.endswith('Index'):
                try:
                    if float(v).is_integer():return str(int(float(v)))
                except (TypeError,ValueError):pass
            return str(v)
        return tuple(value(k) for k in keys)
    for o in observations.to_dict('records'):
        raw=json.loads(o['source_fields_json'])
        if all(k in raw for k in keys):index[key(raw)].append(o)
    rows=[]
    for n,r in enumerate(frame.to_dict('records'),1):
        hits=index[key(r)];reason=[];prob=pd.to_numeric(r['Probability'],errors='coerce')
        if len(hits)!=1:reason.append('main_report_unmatched' if not hits else 'main_report_ambiguous')
        if not np.isfinite(prob) or not 0<=prob<=1:reason.append('invalid_probability')
        try:
            pos=int(r['Site'])
            if pos<1 or float(r['Site'])!=pos:raise ValueError()
        except (ValueError,TypeError):reason.append('invalid_site_coordinate')
        if str(r['Modification']) not in {'UniMod:21','(UniMod:21)'}:reason.append('unsupported_modification_encoding')
        if str(r['Occupied']).lower() not in {'true','false','1','0'}:reason.append('unsupported_occupied_encoding')
        row={k:r[k] for k in ['Protein','Site','Residue','Modification','Occupied','Probability']}
        row.update(site_report_row_id=stable_id('site_report',[sha,n]),source_file_sha256=sha,
            observation_id=hits[0]['observation_id'] if len(hits)==1 else None,
            source_fields_json=json.dumps({k:None if pd.isna(v) else v for k,v in r.items()},default=str,allow_nan=False),
            status='matched' if not reason else 'restricted',restriction_reasons=';'.join(reason))
        rows.append(row)
    out=pd.DataFrame(rows,columns=columns)
    dupe=out.duplicated(['observation_id','Protein','Site','Modification'],keep=False)&out.observation_id.notna()
    out.loc[dupe,'status']='conflict';out.loc[dupe,'restriction_reasons']+=';duplicate_site_report_key'
    return out,{'status':'completed' if out.status.eq('matched').all() else 'partial','source_sha256':sha,
                'rows':len(out),'parser_contract':'diann_site_report.documented.v1','real_report_parity':'not_verified'}


def observation_sites(observations,identities,summary,reference,site_report=None):
    rows=[];entries={e['accession']:e for e in reference['entries']};forms=summary.set_index('form_id')
    identities_by_form={fid:g for fid,g in identities.groupby('form_id')}
    report_index=defaultdict(list)
    if site_report is not None:
        for r in site_report.to_dict('records'):
            report_index[(r['observation_id'],str(r['Protein']),str(r['Site']))].append(r)
    for o in observations.to_dict('records'):
        if o['form_id'] not in forms.index:continue
        form=forms.loc[o['form_id']];backbone=form['Stripped.Sequence']
        parsed,parse_status=probability_sequence(o['site_occupancy_probabilities_raw'],o['canonical_modified_sequence'],o['charge'])
        if o['diann_version'] not in {'2.7','2.7.0'} and parse_status!='missing_input':
            parsed,parse_status={},'ambiguous_semantics_version_contract_unverified'
        reported,coordinate_status=protein_sites(o['protein_sites_raw'])
        for s in identities_by_form.get(o['form_id'],pd.DataFrame()).to_dict('records'):
            seq=entries[s['input_accession']]['sequence'];starts=[m.start() for m in re.finditer('(?='+re.escape(backbone)+')',seq)]
            offsets={int(s['input_position'])-start for start in starts if 1<=int(s['input_position'])-start<=len(backbone)}
            reasons=[];p=None;scope='unavailable';source='Site.Occupancy.Probabilities';contract='diann_curly_sequence.documented.v1';raw=o['site_occupancy_probabilities_raw']
            offset=next(iter(offsets)) if len(offsets)==1 else None
            if o['match_status']!='matched':reasons.append('observation_join_or_quality_restricted')
            if offset is None:reasons.append('peptide_offset_ambiguous')
            if reported is not None and (s['input_accession'],s['residue'],int(s['input_position'])) not in reported:reasons.append('protein_sites_conflict')
            if coordinate_status not in {'parsed','not_provided'}:reasons.append(coordinate_status)
            if parse_status=='parsed' and offset in parsed:p=parsed[offset];scope='site_localization_probability'
            elif parse_status=='parsed':reasons.append('site_probability_not_reported')
            elif parse_status!='missing_input':reasons.append(parse_status)
            site_hits=report_index.get((o['observation_id'],s['input_accession'],str(s['input_position'])),[])
            site_sha=site_row=None
            if site_hits:
                sr=site_hits[0]
                site_sha=sr['source_file_sha256'];site_row=sr['site_report_row_id']
                if len(site_hits)!=1 or sr['status']!='matched':reasons.append('site_report_conflict')
                elif str(sr['Residue'])!=s['residue'] or str(sr['Occupied']).lower() not in {'true','1'}:reasons.append('site_report_assignment_conflict')
                elif p is not None and not np.isclose(p,float(sr['Probability']),rtol=0,atol=1e-6):reasons.append('main_site_probability_conflict')
                else:
                    p=float(sr['Probability']);scope='site_localization_probability';source='site_report.Probability'
                    contract='diann_site_report.documented.v1';raw=sr['source_fields_json']
            # For one occupied phosphosite only, preserve the named run minimum;
            # do not rename it an individual-site posterior.
            variable_tokens=[t for t in re.findall(r'UniMod:\d+',o['canonical_modified_sequence']) if t!='UniMod:4']
            run_min=o['localization_metric_value'] if variable_tokens==['UniMod:21'] else None
            if reasons:p=None;scope='unavailable'
            status='site_localization_supported' if p is not None else 'run_confidence_supported' if not reasons and pd.notna(run_min) else 'ambiguous' if reasons else 'missing_input'
            rows.append({'observation_site_id':stable_id('observation_site',[o['observation_id'],s['site_id']]),
                **{k:o[k] for k in ['observation_id','form_id','injection_id','source_file_sha256','source_row_id','quantification_contributor']},
                **{k:s[k] for k in ['identity_id','site_id']},'modification_id':'UniMod:21','individual_site_posterior':p,
                'site_probability':p,'run_minimum_confidence':run_min,'probability_scope':scope,'evidence_source':source,
                'site_report_source_sha256':site_sha,'site_report_row_id':site_row,
                'parser_version':VERSION,'parser_contract':contract,'assignment_status':status,'original_field_value':raw,
                'peptide_offset':offset,'restriction_reasons':';'.join(reasons)})
    return pd.DataFrame(rows,columns=SITE_COLUMNS)


def by_contrast(observations,children,identities,comparisons,policy=None,expected_contributors=None):
    policy={**POLICY,**(policy or {})};threshold=float(policy['threshold'])
    if not 0<=threshold<=1:raise ValueError('localization_threshold_invalid')
    if policy['aggregation']!=POLICY['aggregation']:raise ValueError('unsupported_localization_aggregation')
    obs=observations.loc[observations.quantification_contributor.astype(bool)].groupby(['form_id','injection_id']).observation_id.apply(set).to_dict()
    child={(r['observation_id'],r['site_id']):r for r in children.to_dict('records')};rows=[]
    contrasts={f:g.to_dict('records') for f,g in comparisons.groupby('form_id',sort=False)}
    for identity in identities.to_dict('records'):
        fid,sid=identity['form_id'],identity['site_id']
        for c in contrasts.get(fid,[]):
            record={'localization_id':stable_id('loc_contrast',[fid,sid,c['contrast_id'],policy]),'form_id':fid,'site_id':sid,
                    'contrast_id':c['contrast_id'],'threshold':threshold,'policy_id':policy['policy_id']}
            supporting=[];used=[];any_site=False;all_site=True;reason=[]
            for side in ('reference','target'):
                raw_runs=c[side+'_joint_run_ids']
                runs=set() if raw_runs is None or pd.isna(raw_runs) else set(str(raw_runs).split(';'))-{''}
                reported=evaluable=passed=0;side_ids=[]
                for run in runs:
                    ids=obs.get((fid,run),set());side_ids.extend(ids);used.extend(ids)
                    if ids:reported+=1
                    vals=[]
                    for oid in ids:
                        r=child.get((oid,sid),{});v=r.get('site_probability')
                        if v is not None and pd.notna(v):any_site=True
                        else:
                            all_site=False
                            v=r.get('run_minimum_confidence') if r.get('assignment_status')=='run_confidence_supported' else None
                        if v is not None and pd.notna(v) and r.get('assignment_status') in {'site_localization_supported','run_confidence_supported'}:
                            vals.append(float(v));supporting.append(r['observation_site_id'])
                    # Check every positive precursor that generated this form's
                    # collapsed signal; a report missing a charge cannot certify it.
                    expected=(expected_contributors or {}).get((fid,run),len(ids))
                    if ids and len(vals)==len(ids)==expected:evaluable+=1;passed+=int(min(vals)>=threshold)
                record.update({side+'_joint_n':len(runs),side+'_reported_n':reported,side+'_evaluable_n':evaluable,
                               side+'_pass_n':passed,side+'_observation_ids':';'.join(sorted(side_ids))})
                if not runs:reason.append(side+'_no_joint_observations')
                elif passed!=len(runs):reason.append(side+'_localization_incomplete_or_below_threshold')
            if not identity['site_attribution_eligible']:reason.append('site_mapping_or_multisite_ambiguous')
            record.update(supporting_observation_site_ids=';'.join(sorted(set(supporting))),quantification_contributor_ids=';'.join(sorted(set(used))),
                          localized_eligible=not reason,measurement_status='site_localization_supported' if any_site and all_site else 'run_confidence_supported' if supporting else 'missing_input',
                          exclusion_reasons=';'.join(reason))
            rows.append(record)
    return pd.DataFrame(rows,columns=LOCAL_COLUMNS)
