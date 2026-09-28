"""Versioned condition/contrast engine. No estimator groups observations by time.

Log observations → equal-weight material means → equal-weight biological-unit
means (when declared) → contrast. Paired contrasts use declared shared pair IDs.
Unknown relations permit explicitly descriptive output, never biological p/q.
Normalization occurs once, before this module sees any arm or contrast subset.
"""
from collections import defaultdict
import json
import numpy as np
import pandas as pd

from .study_design import stable_id, require_resolved
from .report_compatible_quantification import map_form, tokens, positive_matrix, mean_or_nan, assigned_positions

VERSION='material_then_unit_balanced_mean_log.v3'
STRICT_VERSION='unit_balanced_same_injection_peptide_ratios.v3'
PTM_CODES={'phosphorylation':21,'phospho':21,'ubiquitylation':121,'ubiquitination':121,'ubi':121,'acetylation':1}
IDENTITY_COLUMNS=['form_id','Protein.Group','Protein.Ids','Genes','Stripped.Sequence','Modified.Sequence',
    'n_modifications','mapping_status','mapping_json','mapped_genes','annotation_gene_discordant',
    'representative_accession','representative_gene','representative_sites','sites_all','primary_mapping_eligible',
    'localization_probability_available','localization_probability','strict_attribution_status',
    'parent_pg','parent_match','parent_gene_concordant','primary_adjustment_eligible','precursor_count']
KEY_COLUMNS=['contrast_id','arm_id','condition_id','target_condition_id','reference_condition_id',
    'time_min','reference_time_min','target_label','reference_label','comparison_interpretation','pairing']
COMPARISON_COLUMNS=KEY_COLUMNS+['form_id','A','U_joint','P_joint','U_all','P_all','decomposition_residual',
    'primary_adjustment_eligible','included','exclusion_reasons','reference_joint_n','target_joint_n',
    'reference_joint_run_ids','target_joint_run_ids','reference_biological_n','target_biological_n',
    'reference_aggregation_n','target_aggregation_n','statistical_unit','inference_status','biological_p_value','biological_q_value','estimator_version']
DETECTION_COLUMNS=KEY_COLUMNS+['form_id','baseline_status','reference_detected_n','detected_n','scheduled_n',
    'parent_observed_n','joint_observed_n','first_repeated_condition_id','first_repeated_time_min',
    'post_reference_condition_id','post_reference_time_min','post_reference_U','raw_candidate_A','eligible_A',
    'primary_mapping_eligible','primary_adjustment_eligible','inference_use_allowed','use_restriction','baseline_FC_created']
RUN_COLUMNS=['form_id','injection_id','input_column','condition_id','arm_id','time_min','material_id','biological_unit_id','pair_id',
             'ptm_intensity','parent_intensity','ptm_log2','parent_log2','adjusted_log2_ratio','U_observed','P_observed','joint_observed']
PROTEIN_COLUMNS=KEY_COLUMNS+['protein_group','gene','log2_change','reference_observed_n','target_observed_n',
                            'reference_biological_n','target_biological_n','statistical_unit','estimator_version']
STRICT_COLUMNS=KEY_COLUMNS+['form_id','strict_parent_A','PG_parent_A','peptide_n','candidate_peptide_n','status','estimator_version','min_joint_injections_per_condition','min_sequences']
PEPTIDE_COLUMNS=KEY_COLUMNS+['form_id','protein_group','sequence','precursor_id','reference_run_ids','target_run_ids',
    'reference_joint_n','target_joint_n','form_reference_joint_n','form_target_joint_n','paired_included','complete_mask_included',
    'exclusion_reason','complete_mask_exclusion_reason','paired_log2_ratio_change','estimator_version']


def _finite_mean(matrix,axis):
    return mean_or_nan(matrix,axis)


class ContrastEstimator:
    def __init__(self,design):
        self.design=design
        self.samples=sorted(design['injections'],key=lambda r:r['injection_id'])
        self.materials={r['material_id']:r for r in design['materials']}
        self.conditions={r['condition_id']:r for r in design['conditions']}
        self.indices={cid:np.asarray([i for i,s in enumerate(self.samples) if s['condition_id']==cid],dtype=int) for cid in self.conditions}
        self.columns=[s['input_column'] for s in self.samples]

    def metadata(self,contrast):
        target=self.conditions[contrast['target_condition_id']];reference=self.conditions[contrast['reference_condition_id']]
        return {'contrast_id':contrast['contrast_id'],'arm_id':target['arm_id'],'condition_id':target['condition_id'],
            'target_condition_id':target['condition_id'],'reference_condition_id':reference['condition_id'],
            'time_min':target['time']['minutes'],'reference_time_min':reference['time']['minutes'],
            'target_label':target['label'],'reference_label':reference['label'],'pairing':contrast['pairing'],
            'comparison_interpretation':'target_vs_declared_reference_condition_not_necessarily_time_zero'}

    def condition_values(self,values,condition_id):
        groups=defaultdict(list); missing_material=False
        for index in self.indices[condition_id]:
            sample=self.samples[index]; mid=sample.get('material_id')
            if not mid:mid='unresolved_observation:'+sample['injection_id'];missing_material=True
            groups[mid].append(index)
        material_values={mid:_finite_mean(values[:,indices],1) for mid,indices in sorted(groups.items())}
        all_bio=bool(groups) and all(self.materials.get(mid,{}).get('biological_unit_id') for mid in groups)
        if all_bio:
            units=defaultdict(list); pairs={}
            for mid,val in material_values.items():
                info=self.materials[mid]; unit=info['biological_unit_id'];units[unit].append(val)
                pair=info.get('pair_id')
                if unit in pairs and pairs[unit]!=pair:raise ValueError('Conflicting pair IDs within one biological unit')
                pairs[unit]=pair
            reduced={unit:_finite_mean(np.stack(vals,axis=1),1) for unit,vals in sorted(units.items())}
            return reduced,pairs,'biological_unit'
        return material_values,{mid:self.materials.get(mid,{}).get('pair_id') for mid in groups},'unresolved_observation' if missing_material else 'material'

    def contrast(self,values,contrast,minimum=1):
        values=np.atleast_2d(values)
        reference,target=contrast['reference_condition_id'],contrast['target_condition_id']
        rv,rpairs,ru=self.condition_values(values,reference);tv,tpairs,tu=self.condition_values(values,target)
        n=values.shape[0]
        rn=np.isfinite(values[:,self.indices[reference]]).sum(axis=1);tn=np.isfinite(values[:,self.indices[target]]).sum(axis=1)
        rstack=np.stack(list(rv.values()),axis=1) if rv else np.empty((n,0))
        tstack=np.stack(list(tv.values()),axis=1) if tv else np.empty((n,0))
        rcount=np.isfinite(rstack).sum(axis=1);tcount=np.isfinite(tstack).sum(axis=1)
        statistical_unit=ru if ru==tu else 'mixed_unresolved_material_design'
        if contrast.get('pairing')=='paired':
            def by_pair(vals,pairs):
                grouped=defaultdict(list)
                for unit,val in vals.items():
                    if pairs.get(unit):grouped[pairs[unit]].append(val)
                return {pair:_finite_mean(np.stack(data,axis=1),1) for pair,data in grouped.items()}
            r,t=by_pair(rv,rpairs),by_pair(tv,tpairs)
            ids=sorted(set(r)&set(t))
            deltas=np.stack([t[i]-r[i] for i in ids],axis=1) if ids else np.empty((n,0))
            delta=_finite_mean(deltas,1);rcount=tcount=np.isfinite(deltas).sum(axis=1)
            statistical_unit='declared_pair'
        else:delta=_finite_mean(tstack,1)-_finite_mean(rstack,1)
        delta=np.where((rn>=minimum)&(tn>=minimum),delta,np.nan)
        return {'value':delta,'reference_n':rn,'target_n':tn,'reference_aggregation_n':rcount,'target_aggregation_n':tcount,
                'reference_biological_n':rcount if ru=='biological_unit' else np.full(n,np.nan),
                'target_biological_n':tcount if tu=='biological_unit' else np.full(n,np.nan),
                'statistical_unit':statistical_unit}

    def run_ids(self,mask,condition_id):
        return ';'.join(self.samples[i]['injection_id'] for i in self.indices[condition_id] if mask[i])


def prepare_forms(pr,pg,fasta,estimator,ptm_type):
    if ptm_type not in PTM_CODES:raise ValueError('Quantification for this PTM modification code is not supported by the generic profile')
    code=PTM_CODES[ptm_type];columns=estimator.columns
    if pg['Protein.Group'].duplicated().any():raise ValueError('Parent Protein.Group must be unique')
    pr,pg=pr.copy(),pg.copy();pr[columns]=positive_matrix(pr,columns);pg[columns]=positive_matrix(pg,columns)
    parent_rows=dict(zip(pg['Protein.Group'].astype(str),range(len(pg))))
    accessions=defaultdict(set)
    for index,group in enumerate(pg['Protein.Group']):
        for accession in tokens(group):accessions[accession].add(index)
    forms=[];values=[];parents=[];runlevel=[]
    selected=pr.loc[pr['Modified.Sequence'].str.contains(f'(UniMod:{code})',regex=False,na=False)]
    for (group,modified),rows in selected.groupby(['Protein.Group','Modified.Sequence'],sort=True,dropna=False):
        for key in ['Protein.Ids','Genes','Stripped.Sequence']:
            if rows[key].fillna('').nunique()>1:raise ValueError('Conflicting form metadata: '+str(group)+' / '+key)
        row=rows.iloc[0]; form={k:row[k] for k in ['Protein.Group','Protein.Ids','Genes','Stripped.Sequence','Modified.Sequence']}
        mapped=map_form(row,fasta,code);mapped['n_modifications']=mapped.pop('n_phosphates')
        form.update(mapped);form['form_id']=stable_id('form',str(group)+'|'+modified)
        parent=parent_rows.get(str(group)); match='exact_protein_group'
        if parent is None:
            match='not_found'
            for field,label in [('Protein.Group','group_accession'),('Protein.Ids','protein_ids')]:
                hits=set().union(*(accessions[a] for a in tokens(row[field])))
                if hits:
                    parent=next(iter(hits)) if len(hits)==1 else None
                    match='unique_'+label+'_overlap' if parent is not None else 'ambiguous_'+label+'_overlap'
                    break
        pg_group=str(pg.iloc[parent]['Protein.Group']) if parent is not None else ''
        genes={fasta.get(a,{}).get('gene','').upper() for a in tokens(pg_group)}-{''}
        concordant=len(genes)==1 and genes==set(tokens(form['mapped_genes']))
        form.update(parent_pg=pg_group,parent_match=match,parent_gene_concordant=concordant,
            primary_adjustment_eligible=bool(form['primary_mapping_eligible'] and concordant and parent is not None),precursor_count=len(rows))
        observations=rows[columns].to_numpy(float)
        collapsed=np.where(np.isfinite(observations).any(axis=0),np.nansum(observations,axis=0),np.nan)
        parent_values=pg.iloc[parent][columns].to_numpy(float) if parent is not None else np.full(len(columns),np.nan)
        forms.append(form);values.append(collapsed);parents.append(parent_values)
    intensity=np.asarray(values).reshape(len(forms),len(columns));parent=np.asarray(parents).reshape(len(forms),len(columns))
    u,p=np.log2(intensity),np.log2(parent)
    for fi,form in enumerate(forms):
        for j,sample in enumerate(estimator.samples):
            condition=estimator.conditions[sample['condition_id']];material=estimator.materials.get(sample.get('material_id'),{})
            runlevel.append({'form_id':form['form_id'],**{k:sample.get(k) for k in ['injection_id','input_column','condition_id','material_id']},
                'arm_id':condition['arm_id'],'time_min':condition['time']['minutes'],'biological_unit_id':material.get('biological_unit_id'),
                'pair_id':material.get('pair_id'),'ptm_intensity':intensity[fi,j],'parent_intensity':parent[fi,j],
                'ptm_log2':u[fi,j],'parent_log2':p[fi,j],'adjusted_log2_ratio':u[fi,j]-p[fi,j],
                'U_observed':bool(np.isfinite(u[fi,j])),'P_observed':bool(np.isfinite(p[fi,j])),
                'joint_observed':bool(np.isfinite(u[fi,j]-p[fi,j]))})
    return {'summary':pd.DataFrame(forms,columns=IDENTITY_COLUMNS),'runlevel':pd.DataFrame(runlevel,columns=RUN_COLUMNS),
            'arrays':{'U':u,'P':p,'A':u-p},'pr':pr,'pg':pg,'fasta':fasta,'ptm_code':code,'estimator':estimator}


def quantify_contrasts(pr,pg,fasta,design,ptm_type='phosphorylation'):
    require_resolved(design,pr.columns,pg.columns)
    estimator=ContrastEstimator(design);result=prepare_forms(pr,pg,fasta,estimator,ptm_type)
    arrays=result['arrays'];joint=np.isfinite(arrays['A']);records=[]
    summary=result['summary']
    for c in design['contrasts']:
        values={axis:estimator.contrast(data,c) for axis,data in {**arrays,
            'U_joint':np.where(joint,arrays['U'],np.nan),'P_joint':np.where(joint,arrays['P'],np.nan)}.items()}
        for fi,form in enumerate(summary.to_dict('records')):
            a=values['A']; adjusted=a['value'][fi]; reasons=[]
            if not form['primary_mapping_eligible']:reasons.append('mapping_ineligible')
            if not form['primary_adjustment_eligible']:reasons.append('parent_ineligible')
            if a['reference_n'][fi]<1:reasons.append('reference_joint_unobserved')
            if a['target_n'][fi]<1:reasons.append('target_joint_unobserved')
            if not np.isfinite(adjusted) and not reasons:reasons.append('no_common_declared_pairs')
            records.append({**estimator.metadata(c),'form_id':form['form_id'],'A':adjusted,
                'U_joint':values['U_joint']['value'][fi],'P_joint':values['P_joint']['value'][fi],
                'U_all':values['U']['value'][fi],'P_all':values['P']['value'][fi],
                'decomposition_residual':adjusted-(values['U_joint']['value'][fi]-values['P_joint']['value'][fi]),
                'primary_adjustment_eligible':form['primary_adjustment_eligible'],'included':not reasons,
                'exclusion_reasons':';'.join(reasons),'reference_joint_n':int(a['reference_n'][fi]),'target_joint_n':int(a['target_n'][fi]),
                'reference_joint_run_ids':estimator.run_ids(joint[fi],c['reference_condition_id']),
                'target_joint_run_ids':estimator.run_ids(joint[fi],c['target_condition_id']),
                **{key:(float(a[key][fi]) if np.isfinite(a[key][fi]) else None) for key in
                   ['reference_biological_n','target_biological_n','reference_aggregation_n','target_aggregation_n']},
                'statistical_unit':a['statistical_unit'],'inference_status':'descriptive_only_no_biological_test_implemented',
                'biological_p_value':None,'biological_q_value':None,'estimator_version':VERSION})
    result['comparisons']=pd.DataFrame(records,columns=COMPARISON_COLUMNS)
    result['detection']=detection_by_arm(result,design)
    result['protein_contrasts']=protein_contrasts(result,design)
    result.update(strict_parent_layers(result,design))
    return result


def detection_by_arm(analysis,design):
    est=analysis['estimator'];u=analysis['arrays']['U'];p=analysis['arrays']['P'];a=analysis['arrays']['A'];records=[]
    for c in design['contrasts']:
        meta=est.metadata(c);arm=meta['arm_id'];ref=c['reference_condition_id'];target=c['target_condition_id']
        # A trajectory is defined by arm AND reference; shared references are not copied into runlevel.
        trajectory={x['target_condition_id'] for x in design['contrasts'] if x['reference_condition_id']==ref and est.conditions[x['target_condition_id']]['arm_id']==arm}
        ordered=sorted(trajectory,key=lambda cid:(est.conditions[cid]['time']['minutes'],cid))
        for fi,form in enumerate(analysis['summary'].to_dict('records')):
            first=next((cid for cid in ordered if np.isfinite(u[fi,est.indices[cid]]).sum()>=2),None)
            first_joint=next((cid for cid in ordered if np.isfinite(a[fi,est.indices[cid]]).sum()>=2),None)
            target_time=est.conditions[target]['time']['minutes']
            def post(values,reference):
                if reference is None or target_time<est.conditions[reference]['time']['minutes']:return np.nan
                return float(est.contrast(values[fi],{**c,'reference_condition_id':reference})['value'][0])
            post_u=post(u,first);post_a=post(a,first_joint)
            rn=int(np.isfinite(u[fi,est.indices[ref]]).sum());tn=int(np.isfinite(u[fi,est.indices[target]]).sum())
            eligible=form['primary_adjustment_eligible'] and np.isfinite(post_a)
            records.append({**meta,'form_id':form['form_id'],'baseline_status':'undetected' if rn==0 else 'observed',
                'reference_detected_n':rn,'detected_n':tn,'scheduled_n':len(est.indices[target]),
                'parent_observed_n':int(np.isfinite(p[fi,est.indices[target]]).sum()),'joint_observed_n':int(np.isfinite(a[fi,est.indices[target]]).sum()),
                'first_repeated_condition_id':first,'first_repeated_time_min':est.conditions[first]['time']['minutes'] if first else None,
                'post_reference_condition_id':first_joint,'post_reference_time_min':est.conditions[first_joint]['time']['minutes'] if first_joint else None,
                'post_reference_U':post_u,'raw_candidate_A':post_a,'eligible_A':post_a if eligible else np.nan,
                'primary_mapping_eligible':form['primary_mapping_eligible'],'primary_adjustment_eligible':form['primary_adjustment_eligible'],
                'inference_use_allowed':bool(eligible),'use_restriction':'post_reference_only_never_pool_different_references' if eligible else 'parent_or_post_reference_unavailable',
                'baseline_FC_created':False})
    return pd.DataFrame(records,columns=DETECTION_COLUMNS)


def protein_contrasts(analysis,design):
    est=analysis['estimator'];pg=analysis['pg'];logs=np.log2(positive_matrix(pg,est.columns));records=[]
    for c in design['contrasts']:
        values=est.contrast(logs,c)
        for i,row in enumerate(pg.to_dict('records')):
            records.append({**est.metadata(c),'protein_group':row['Protein.Group'],'gene':row.get('Genes',''),
                'log2_change':values['value'][i],'reference_observed_n':int(values['reference_n'][i]),'target_observed_n':int(values['target_n'][i]),
                'reference_biological_n':values['reference_biological_n'][i],'target_biological_n':values['target_biological_n'][i],
                'statistical_unit':values['statistical_unit'],'estimator_version':VERSION})
    return pd.DataFrame(records,columns=PROTEIN_COLUMNS)


def strict_parent_layers(analysis,design):
    est=analysis['estimator'];pr=analysis['pr'];columns=est.columns
    modified=set(pr.loc[pr['Modified.Sequence'].ne(pr['Stripped.Sequence']),'Stripped.Sequence'])
    gene=pr.Genes.fillna('');group_counts=pr.groupby('Stripped.Sequence')['Protein.Group'].nunique()
    selected=pr.loc[pr['Modified.Sequence'].eq(pr['Stripped.Sequence']) & pr.Proteotypic.eq(1) & pr['Protein.Group'].notna()
        & gene.str.strip().ne('') & ~gene.str.contains(';') & ~pr['Stripped.Sequence'].isin(modified)
        & pr['Stripped.Sequence'].map(group_counts).eq(1)].copy()
    selected['observed_n']=selected[columns].notna().sum(axis=1);selected['median_intensity']=selected[columns].median(axis=1)
    selected=selected.sort_values(['observed_n','median_intensity','Precursor.Charge','Precursor.Id'],ascending=[False,False,True,True],kind='stable').drop_duplicates(['Protein.Group','Stripped.Sequence']).reset_index(drop=True)
    logs=np.log2(positive_matrix(selected,columns));groups=selected.groupby('Protein.Group').indices
    sequence_rows=[];protein_rows=[];paired=[];complete=[];audit=[]
    forms=analysis['summary'].set_index('form_id');fi_map={f:i for i,f in enumerate(analysis['summary'].form_id)}
    contrasts={c['contrast_id']:c for c in design['contrasts']}
    for c in design['contrasts']:
        changes=est.contrast(logs,c)
        for i,row in enumerate(selected.to_dict('records')):
            sequence_rows.append({**est.metadata(c),'protein_group':row['Protein.Group'],'gene':row['Genes'],'sequence':row['Stripped.Sequence'],
                'precursor_id':row['Precursor.Id'],'log2_change':changes['value'][i],'reference_observed_n':int(changes['reference_n'][i]),
                'target_observed_n':int(changes['target_n'][i]),'estimator_version':VERSION})
        for group,indices in groups.items():
            vals=changes['value'][indices];valid=vals[np.isfinite(vals)]
            protein_rows.append({**est.metadata(c),'protein_group':group,'gene':selected.iloc[indices[0]]['Genes'],
                'log2_change':float(np.median(valid)) if len(valid)>=2 else np.nan,'peptide_n':len(valid),
                'status':'evaluable' if len(valid)>=2 else 'insufficient_sequences','estimator_version':VERSION})
    for row in analysis['comparisons'].loc[analysis['comparisons'].included].to_dict('records'):
        fid=row['form_id'];fi=fi_map[fid];c=contrasts[row['contrast_id']];meta=est.metadata(c);group=forms.loc[fid,'parent_pg']
        candidates=np.asarray(groups.get(group,[]),dtype=int);joint=np.isfinite(analysis['arrays']['A'][fi])
        ratios=np.where(joint,analysis['arrays']['U'][fi]-logs[candidates],np.nan)
        changes=est.contrast(ratios,c,minimum=2);valid=np.isfinite(changes['value'])
        observed_indices=np.r_[est.indices[c['reference_condition_id']],est.indices[c['target_condition_id']]]
        complete_mask=np.isfinite(logs[candidates][:,observed_indices[joint[observed_indices]]]).all(axis=1)
        for j,index in enumerate(candidates):
            peptide=selected.iloc[index];mask=np.isfinite(ratios[j]);reasons=[]
            if changes['reference_n'][j]<2:reasons.append('reference_joint_n_lt2')
            if changes['target_n'][j]<2:reasons.append('target_joint_n_lt2')
            if not valid[j] and not reasons:reasons.append('no_common_declared_pairs')
            audit.append({**meta,'form_id':fid,'protein_group':group,'sequence':peptide['Stripped.Sequence'],'precursor_id':peptide['Precursor.Id'],
                'reference_run_ids':est.run_ids(mask,c['reference_condition_id']),'target_run_ids':est.run_ids(mask,c['target_condition_id']),
                'reference_joint_n':int(changes['reference_n'][j]),'target_joint_n':int(changes['target_n'][j]),
                'form_reference_joint_n':row['reference_joint_n'],'form_target_joint_n':row['target_joint_n'],
                'paired_included':bool(valid[j]),'complete_mask_included':bool(valid[j] and complete_mask[j]),
                'exclusion_reason':';'.join(reasons),'complete_mask_exclusion_reason':';'.join(reasons+([] if complete_mask[j] else ['missing_on_form_joint_run'])),
                'paired_log2_ratio_change':changes['value'][j],'estimator_version':STRICT_VERSION})
        for target,mask,version in [(paired,valid,STRICT_VERSION),(complete,valid&complete_mask,STRICT_VERSION+'.complete_mask')]:
            vals=changes['value'][mask]
            target.append({**meta,'form_id':fid,'strict_parent_A':float(np.median(vals)) if len(vals)>=2 else np.nan,
                'PG_parent_A':row['A'],'peptide_n':len(vals),'candidate_peptide_n':len(candidates),
                'status':'evaluable' if len(vals)>=2 else 'insufficient_sequences','estimator_version':version,
                'min_joint_injections_per_condition':2,'min_sequences':2})
    return {'strict_parent_paired':pd.DataFrame(paired,columns=STRICT_COLUMNS),'strict_parent_complete':pd.DataFrame(complete,columns=STRICT_COLUMNS),
        'strict_parent_peptide_masks':pd.DataFrame(audit,columns=PEPTIDE_COLUMNS),
        'strict_unmodified_sequences':pd.DataFrame(sequence_rows,columns=KEY_COLUMNS+['protein_group','gene','sequence','precursor_id','log2_change','reference_observed_n','target_observed_n','estimator_version']),
        'strict_unmodified_proteins':pd.DataFrame(protein_rows,columns=KEY_COLUMNS+['protein_group','gene','log2_change','peptide_n','status','estimator_version']),
        'strict_selected_sequences':selected[['Protein.Group','Genes','Stripped.Sequence','Precursor.Id']+columns]}
