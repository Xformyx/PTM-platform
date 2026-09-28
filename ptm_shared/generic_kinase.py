"""Contrast-aware phosphorylation footprints from a compatible frozen registry.

No question text, pathway expectation or validation panel changes primary scoring.
Localization is accepted only as explicit accession/site/form evidence with source.
"""
from collections import defaultdict
import json
import re
import numpy as np
import pandas as pd

from .contrast_quantification import KEY_COLUMNS
from .report_compatible_kinase import aggregate_rows, footprint_statistics
from .report_compatible_quantification import tokens
from .study_presets import HIRCB_SNAPSHOT

VERSION='contrast_gene_balanced_footprint.v3'
REGISTRY_VERSION='species_kinase_groups.v1'
CURATED={'PhosphoSite','SIGNOR','HPRD','phosphoELM'}
GENE_GROUPS={
    '9606':{'AKT_family':['AKT1','AKT2','AKT3'],'ERK1_2_family':['MAPK1','MAPK3'],
            'MEK1_2_family':['MAP2K1','MAP2K2'],'mTOR':['MTOR'],'S6K_family':['RPS6KB1','RPS6KB2'],
            'RSK_family':['RPS6KA1','RPS6KA2','RPS6KA3','RPS6KA6'],'GSK3_family':['GSK3A','GSK3B']},
    '10116':{'AKT_family':['Akt1','Akt2','Akt3'],'ERK1_2_family':['Mapk1','Mapk3'],
             'MEK1_2_family':['Map2k1','Map2k2'],'mTOR':['Mtor'],'S6K_family':['Rps6kb1','Rps6kb2'],
             'RSK_family':['Rps6ka1','Rps6ka2','Rps6ka3','Rps6ka6'],'GSK3_family':['Gsk3a','Gsk3b']},
    '10090':{'AKT_family':['Akt1','Akt2','Akt3'],'ERK1_2_family':['Mapk1','Mapk3'],
             'MEK1_2_family':['Map2k1','Map2k2'],'mTOR':['Mtor'],'S6K_family':['Rps6kb1','Rps6kb2'],
             'RSK_family':['Rps6ka1','Rps6ka2','Rps6ka3','Rps6ka6'],'GSK3_family':['Gsk3a','Gsk3b']}}
NONCATALYTIC={
    '9606':{'CCNB1','CCNE2','CSNK2B','PRKAB1','PRKAB2','PRKAG1','PRKAG2','PRKAG3'},
    '10116':{'Ccnb1','Ccne2','Csnk2b','Prkab1','Prkab2','Prkag1','Prkag2','Prkag3'},
    '10090':{'Ccnb1','Ccne2','Csnk2b','Prkab1','Prkab2','Prkag1','Prkag2','Prkag3'}}
MAP_COLUMNS=['form_id','mapped_accession','fasta_taxonomy_id','fasta_gene','residue_type','residue_offset','site_window']
EDGE_COLUMNS=MAP_COLUMNS+['enzyme','kinase_gene','substrate_gene','site_key','site_id','sources','references',
    'curated_resources','annotation_sha256','annotation_evidence','primary_edge_eligible','exclusion_reason','source_caution',
    'curation_version','localization_probability','localization_source','strict_eligible','strict_status']
STATS=list(footprint_statistics({},{}))
PROFILE_COLUMNS=KEY_COLUMNS+['entity','entity_type','mode']+STATS+['evidence_tier','status','estimator_version','biological_p_value']
MEMBER_COLUMNS=KEY_COLUMNS+['entity','mode','substrate_gene','site_key','contribution','form_ids','annotation_sha256']


def fasta_taxonomy(path):
    result={}
    with open(path,encoding='utf-8') as f:
        for line in f:
            if not line.startswith('>'):continue
            name=line[1:].split()[0];parts=name.split('|');accession=parts[1] if len(parts)>1 else name
            match=re.search(r'\bOX=(\d+)',line)
            result[accession]=match[1] if match else None
    return result


def map_edges(analysis,snapshot,registration,context,taxa=None):
    taxa=taxa or {};mapping=[];forms=analysis['summary'].set_index('form_id')
    metadata=(registration or {}).get('metadata',{});sha=(registration or {}).get('sha256')
    supported={str(t) for t in metadata.get('taxonomy_ids',[])}
    localization={}
    for row in context.get('localization_evidence',[]):
        keys=['protein_group','modified_sequence','accession','residue_type','residue_offset','probability','source']
        if not isinstance(row,dict) or any(row.get(k) is None for k in keys):raise ValueError('Localization evidence requires form, exact accession/residue, probability and source')
        value=float(row['probability'])
        if not np.isfinite(value) or not 0<=value<=1 or not str(row['source']).strip():raise ValueError('Invalid localization probability/source')
        key=tuple(str(row[k]) for k in keys[:5])
        if key in localization:raise ValueError('Duplicate localization evidence key')
        localization[key]=(value,row['source'])
    for form in analysis['summary'].to_dict('records'):
        for item in json.loads(form['mapping_json']):
            protein=analysis['fasta'][item['accession']]['sequence']
            for site in item['sites']:
                if not re.fullmatch('[A-Z][0-9]+',site):continue
                residue=site[0];offset=int(site[1:])
                if offset<1:continue
                window=protein[max(0,offset-8):offset-1]+protein[offset-1].lower()+protein[offset:offset+7]
                mapping.append({'form_id':form['form_id'],'mapped_accession':item['accession'],
                    'fasta_taxonomy_id':taxa.get(item['accession']),'fasta_gene':item['gene'],
                    'residue_type':residue,'residue_offset':offset,'site_window':window})
    mapped=pd.DataFrame(mapping,columns=MAP_COLUMNS).drop_duplicates()
    records=[]
    if snapshot is not None:
        snap=snapshot.loc[snapshot.modification.eq('phosphorylation')].copy()
        snap['residue_offset']=pd.to_numeric(snap.residue_offset,errors='raise').astype(int)
        joined=mapped.merge(snap,left_on=['mapped_accession','residue_type','residue_offset'],right_on=['substrate','residue_type','residue_offset'])
        aliases=metadata.get('accession_aliases',{})
        tax=str(analysis['estimator'].design['study'].get('taxonomy_id'))
        noncat=NONCATALYTIC.get(tax,set())|set(metadata.get('noncatalytic_exclusions',[]))
        for row in joined.to_dict('records'):
            form=forms.loc[row['form_id']];gene=aliases.get(row['enzyme']) or analysis['fasta'].get(row['enzyme'],{}).get('gene') or row['enzyme']
            resources=CURATED.intersection(tokens(row['sources']));reasons=[];caution='';curation='none'
            if gene in noncat:reasons.append('noncatalytic')
            if not resources:reasons.append('no_curated_resource')
            if not form.primary_mapping_eligible:reasons.append('mapping_ineligible')
            if row['fasta_taxonomy_id'] and str(row['fasta_taxonomy_id']) not in supported:reasons.append('substrate_taxonomy_not_supported')
            # Frozen audit is scoped to the actual snapshot, taxon, FASTA gene/site and source.
            if sha==HIRCB_SNAPSHOT and tax=='10116':
                curation='hircb_snapshot_audit.v1'
                if (gene,row['fasta_gene'],row['residue_type'],row['residue_offset'])==('Gsk3b','Dpysl3','S',522) and 'SIGNOR' in resources:
                    reasons.append('GSK3_priming_site_not_direct_substrate_PMID16611631')
                if gene in GENE_GROUPS[tax]['S6K_family'] and row['fasta_gene'].upper()=='HNRNPA1' and row['residue_type']=='S' and row['residue_offset']==6:
                    caution='HNRNPA1_S6K_PMID16914728_PMID42644392'
            key=(str(form['Protein.Group']),str(form['Modified.Sequence']),str(row['mapped_accession']),str(row['residue_type']),str(row['residue_offset']))
            probability,source=localization.get(key,(None,None))
            strict=not reasons and probability is not None and probability>=.75 and form.n_modifications==1
            status='localized_curated_exploratory' if strict else 'no_call_localization_unavailable' if probability is None else 'no_call_localization_or_mapping_criteria'
            records.append({**{k:row[k] for k in MAP_COLUMNS},'enzyme':row['enzyme'],'kinase_gene':gene,
                'substrate_gene':row['fasta_gene'].upper(),'site_key':row['fasta_gene'].upper()+':'+row['site_window'],
                'site_id':row['mapped_accession']+':'+row['residue_type']+str(row['residue_offset']),
                'sources':row['sources'],'references':row['references'],'curated_resources':';'.join(sorted(resources)),
                'annotation_sha256':sha,'annotation_evidence':'orthology_translated_curated' if metadata.get('orthology_translation') is True else 'direct_species_curated' if metadata.get('orthology_translation') is False else 'curated_orthology_status_unknown',
                'primary_edge_eligible':not reasons,'exclusion_reason':';'.join(reasons),'source_caution':caution,
                'curation_version':curation,'localization_probability':probability,'localization_source':source,
                'strict_eligible':strict,'strict_status':status})
    edges=pd.DataFrame(records,columns=EDGE_COLUMNS).drop_duplicates()
    # Actual matched evidence, not merely a nonempty uploaded list, determines availability.
    for index,form in analysis['summary'].iterrows():
        evidence=edges.loc[edges.form_id.eq(form.form_id) & edges.localization_probability.notna()]
        if not evidence.empty:
            analysis['summary'].loc[index,'localization_probability_available']=True
            analysis['summary'].loc[index,'localization_probability']=float(evidence.localization_probability.min())
            analysis['summary'].loc[index,'strict_attribution_status']='localized_input_matched' if evidence.strict_eligible.any() else 'no_call_localization_or_mapping_criteria'
    return mapped,edges


def score_contrasts(analysis,edges,context,registration=None):
    est=analysis['estimator'];design=est.design;tax=str(design['study'].get('taxonomy_id'))
    summary=analysis['summary'].set_index('form_id')
    eligible=edges.loc[edges.primary_edge_eligible.astype(bool)]
    candidates=sorted(edges.kinase_gene.unique())  # Excluded/zero-coverage candidates remain visible as no-call.
    families=GENE_GROUPS.get(tax,{})
    entities={g:[g] for g in candidates}
    entities.update({name:members for name,members in families.items() if set(members)&set(candidates)})
    records=[];membership=[];sensitivity=[];omissions=[];emergent=[]
    panel=design.get('validation_panel') or {};holdout={str(g).upper() for g in panel.get('genes',[])} if panel.get('exclude_from_discovery_sensitivity') else set()
    modes={'primary_A':'A','unadjusted_U_all_observed':'U_all','parent_P_all_observed':'P_all','unadjusted_U_joint':'U_joint','parent_P_joint':'P_joint','strict_localized_A':'A'}
    for contrast in design['contrasts']:
        meta=est.metadata(contrast);comparison=analysis['comparisons'].loc[analysis['comparisons'].contrast_id.eq(contrast['contrast_id'])].set_index('form_id')
        allowed=set(comparison.index[comparison.included])
        for entity,members in entities.items():
            rows=eligible.loc[eligible.kinase_gene.isin(members)].to_dict('records')
            rows=[r for r in rows if summary.loc[r['form_id'],'n_modifications']==1 and r['form_id'] in allowed]
            # Dedup an identical form/site edge across kinases/resources inside a family.
            merged={}
            for row in rows:
                key=(row['form_id'],row['site_key']);old=merged.get(key)
                if old:
                    old['curated_resources']=';'.join(sorted(set(tokens(old['curated_resources']))|set(tokens(row['curated_resources']))))
                    old['source_caution']=old['source_caution'] or row['source_caution'];old['strict_eligible']|=row['strict_eligible']
                else:merged[key]=dict(row)
            rows=list(merged.values())
            for mode,axis in modes.items():
                selected=[r for r in rows if r['strict_eligible']] if mode=='strict_localized_A' else rows
                sites,genes,support=aggregate_rows(selected,comparison[axis].to_dict())
                stats=footprint_statistics(sites,genes)
                status='exploratory_footprint' if stats['coverage_adequate'] else 'no_call_insufficient_coverage'
                if mode=='strict_localized_A' and not selected:status='no_call_localization_unavailable' if not any(r['localization_probability'] is not None for r in rows) else 'no_call_localization_or_mapping_criteria'
                records.append({**meta,'entity':entity,'entity_type':'family' if entity in families else 'kinase','mode':mode,**stats,
                    'evidence_tier':'localized_curated_footprint' if mode=='strict_localized_A' else 'exploratory_footprint',
                    'status':status,'estimator_version':VERSION,'biological_p_value':None})
                for (gene,site),value in sites.items():
                    membership.append({**meta,'entity':entity,'mode':mode,'substrate_gene':gene,'site_key':site,'contribution':value,
                        'form_ids':';'.join(sorted({r['form_id'] for r in support[gene,site]})),
                        'annotation_sha256':(registration or {}).get('sha256')})
            selections={'exclude_source_caution':[r for r in rows if not r['source_caution']]}
            selections.update({'omit_source_'+source:[r for r in rows if set(tokens(r['curated_resources']))-{source}] for source in sorted(CURATED)})
            if holdout:selections['declared_panel_holdout']=[r for r in rows if r['substrate_gene'] not in holdout]
            for gene in sorted({r['substrate_gene'] for r in rows}):selections['omit_gene_'+gene]=[r for r in rows if r['substrate_gene']!=gene]
            for mode,selected in selections.items():
                sites,genes,_=aggregate_rows(selected,comparison.A.to_dict())
                sensitivity.append({**meta,'entity':entity,'mode':mode,**footprint_statistics(sites,genes),'estimator_version':VERSION})
            for index in np.r_[est.indices[contrast['reference_condition_id']],est.indices[contrast['target_condition_id']]]:
                values=analysis['arrays']['A'].copy();values[:,index]=np.nan
                delta=est.contrast(values,contrast)['value'];lookup=dict(zip(analysis['summary'].form_id,delta))
                sites,genes,_=aggregate_rows(rows,lookup)
                omissions.append({**meta,'entity':entity,'omitted_injection_id':est.samples[index]['injection_id'],
                    **footprint_statistics(sites,genes),'estimator_version':VERSION})
        for detection in analysis['detection'].loc[analysis['detection'].contrast_id.eq(contrast['contrast_id']) & analysis['detection'].baseline_status.eq('undetected')].to_dict('records'):
            for edge in eligible.loc[eligible.form_id.eq(detection['form_id'])].to_dict('records'):
                for entity,members in entities.items():
                    if edge['kinase_gene'] in members:
                        emergent.append({**detection,'entity':entity,'site_id':edge['site_id'],'kinase_gene':edge['kinase_gene'],
                            'annotation_sha256':edge['annotation_sha256'],'annotation_evidence':edge['annotation_evidence'],
                            'localization_status':edge['strict_status'],'contributes_to_baseline_score':False})
    from .contrast_quantification import DETECTION_COLUMNS
    profiles=pd.DataFrame(records,columns=PROFILE_COLUMNS)
    return {'kinase_profiles':profiles,'kinase_membership':pd.DataFrame(membership,columns=MEMBER_COLUMNS),
        'kinase_sensitivity':pd.DataFrame(sensitivity,columns=KEY_COLUMNS+['entity','mode']+STATS+['estimator_version']),
        'kinase_injection_omissions':pd.DataFrame(omissions,columns=KEY_COLUMNS+['entity','omitted_injection_id']+STATS+['estimator_version']),
        'emergent_kinase_evidence':pd.DataFrame(emergent,columns=DETECTION_COLUMNS+['entity','site_id','kinase_gene','annotation_sha256','annotation_evidence','localization_status','contributes_to_baseline_score']).drop_duplicates()}
