"""Typed candidate relations and separate, gene-balanced quantitative tracks."""
from collections import defaultdict
import json
import re
import numpy as np
import pandas as pd

from .astra_inputs import stable_id
from .contrast_quantification import ContrastEstimator
from .generic_kinase import map_edges, fasta_taxonomy, GENE_GROUPS
from .motif_candidate_calibration import load_motif_library, anchored_match, anchored_background
from .report_compatible_quantification import read_fasta

VERSION = 'typed_regulator_evidence.v1.1'
EDGE_COLUMNS = ['edge_id','candidate_id','candidate_gene','candidate_accession','candidate_resolution','form_id','site_id',
    'measurement_group_id','substrate_gene','input_fasta_gene','substrate_gene_source','protein_group','input_accession','input_position','representative_accession',
    'representative_position','substrate_taxon','kinase_taxon','source_taxon','sequence_window','modified_center','edge_type',
    'directness','provider','original_resource','evidence_record_ids','PMIDs','DOIs','reference_ids','orthology_method',
    'site_mapping_status','localization_probability','localization_source','localization_status','primary_quant_eligibility',
    'motif_id','motif_version','motif_information_bits','motif_background','relative_candidate_weight','source_query_id',
    'ambiguity_group','duplicate_evidence_group','restriction_reasons','footprint_eligible','source_caution']
PROFILE_COLUMNS = ['candidate_id','candidate_gene','contrast_id','arm_id','condition_id','reference_condition_id','time_min',
    'track','activity_magnitude','n_sites','n_genes','n_measurement_groups','positive_genes','negative_genes','direction_consistency',
    'coverage_adequate','activity_status','membership_hash','identifiability_group','priority_tier','statistic_type']
CONTRIBUTION_COLUMNS = ['contribution_id','candidate_id','contrast_id','track','measurement_group_id','site_key','substrate_gene',
    'form_ids','site_ids','edge_ids','value','gene_weight','site_weight','source_query_ids','restriction_reasons']


def mapped_sites(tables, design, fasta_path, context, snapshots):
    analysis = {**tables, 'estimator':ContrastEstimator(design), 'fasta':read_fasta(fasta_path)}
    mapping, _ = map_edges(analysis, None, None, context, fasta_taxonomy(fasta_path))
    joined = []
    for source in snapshots:
        frame = pd.DataFrame(source['rows']) if source['rows'] else pd.DataFrame(columns=['enzyme','substrate','residue_type','residue_offset','modification','sources','references'])
        _, edges = map_edges(analysis, frame, source, context, fasta_taxonomy(fasta_path))
        edges['source_query_id'] = source['query_id']; joined.append(edges)
    return mapping, pd.concat(joined, ignore_index=True) if joined else pd.DataFrame(), analysis['fasta']


def _blank(value):
    """Missing FASTA text is an empty string, not NaN.

    구현 대상: discover()의 substrate gene 해석. 유전자가 없으면 unresolved.
    사전등록: 해당 없음. 2026-09-30 Order 83이 representative_gene NaN에서
    stable_id JSON 직렬화에 실패했다. NaN은 비어 있음을 뜻한다.
    해석 한계: 유전자명이 없다는 기록이다. 같은 서열창을 같은 유전자로 묶지 않는다.
    주장 금지: 이 처리로 kinase 귀속 정확도를 주장하지 않는다.
    """
    if isinstance(value, (list, tuple, dict)):
        return value
    try:
        if value is None or pd.isna(value):
            return ''
    except (TypeError, ValueError):
        return ''
    return str(value)


def discover(tables, design, fasta_path, context, sources):
    mapped, curated, fasta = mapped_sites(tables, design, fasta_path, context, sources['snapshots'])
    science=context.get('quantitation_export_mode')=='astra_analysis.v5'
    reference=context.get('_science_reference',{})
    identities={r['accession']:r for r in reference.get('entries',[])}
    family_groups=GENE_GROUPS
    if science:
        from pathlib import Path
        family_groups=json.loads(Path(__file__).with_name('kinase_family_registry.json').read_text())['taxa']
    forms = tables['summary'].set_index('form_id'); library = load_motif_library(); sites = []
    for r in mapped.to_dict('records'):
        sequence = fasta[r['mapped_accession']]['sequence']; center = int(r['residue_offset'])-1
        if center < 0 or center >= len(sequence) or sequence[center] != r['residue_type']: continue
        # Constant center, explicit terminal padding; do not strip padding before anchoring.
        window = ''.join(sequence[i] if 0 <= i < len(sequence) else '_' for i in range(center-7,center+8))
        form=forms.loc[r['form_id']]
        fasta_gene=_blank(r['fasta_gene'])
        resolved_gene=fasta_gene or (_blank(form.representative_gene) if form.primary_mapping_eligible else '')
        sites.append({**r, 'fasta_gene':fasta_gene, 'fasta_taxonomy_id':_blank(r['fasta_taxonomy_id']), 'gene':resolved_gene,'sequence_window':window,'modified_center':7})
    background = anchored_background(sites, library)
    base_by_site = {}; records = []
    localized={(str(r['protein_group']),str(r['modified_sequence']),str(r['accession']),str(r['residue_type']),str(r['residue_offset'])):r for r in context.get('localization_evidence',[])}
    for s in sites:
        f = forms.loc[s['form_id']]; site_id = s['mapped_accession']+':'+s['residue_type']+str(s['residue_offset'])
        mg = stable_id('measurement',[str(f['Stripped.Sequence'])] if science else [str(f['Protein.Group']),str(f['Stripped.Sequence'])])
        restrictions = []
        if not s['gene']:restrictions.append('substrate_gene_unresolved')
        if not f.primary_mapping_eligible: restrictions.append('mapping_ineligible')
        if len(set(str(f['Protein.Ids']).split(';'))) > 1: restrictions.append('multi_accession_site_uncertainty')
        if f.n_modifications != 1: restrictions.append('inseparable_multisite')
        if not f.primary_adjustment_eligible: restrictions.append('parent_ineligible')
        base = {'form_id':s['form_id'],'site_id':site_id,'measurement_group_id':mg,'substrate_gene':s['gene'],'input_fasta_gene':s['fasta_gene'],
            'substrate_gene_source':'input_FASTA_GN' if s['fasta_gene'] else 'unambiguous_form_representative_gene' if s['gene'] else 'unresolved',
            'protein_group':f['Protein.Group'],'input_accession':s['mapped_accession'],'input_position':s['residue_offset'],
            'representative_accession':f.representative_accession,'representative_position':f.representative_sites,
            'substrate_taxon':s['fasta_taxonomy_id'],'sequence_window':s['sequence_window'],'modified_center':7,
            'site_mapping_status':f.mapping_status,'localization_probability':None,'localization_source':None,
            'localization_status':'unknown','primary_quant_eligibility':bool(f.primary_adjustment_eligible),
            'ambiguity_group':stable_id('shared_site',[s['gene'],s['sequence_window']] if s['gene'] else ['unresolved',site_id]),
            'restriction_reasons':restrictions,'footprint_eligible':bool(f.primary_adjustment_eligible and f.n_modifications==1 and s['gene'])}
        supplied=localized.get((str(f['Protein.Group']),str(f['Modified.Sequence']),str(s['mapped_accession']),str(s['residue_type']),str(s['residue_offset'])))
        if supplied:base.update(localization_probability=float(supplied['probability']),localization_source=supplied['source'],localization_status='provided')
        if science:
            identity=identities.get(s['mapped_accession'],{})
            base.update(site_id=stable_id('site_identity',[s['fasta_taxonomy_id'],s['mapped_accession'],identity.get('sequence_sha256'),s['residue_type'],s['residue_offset'],reference.get('reference_sha256')]))
            base['ambiguity_group']=mg
            mappings=json.loads(f.mapping_json)
            if len(mappings)!=1:
                base['restriction_reasons'].append('site_mapping_ambiguous')
                base['footprint_eligible']=False
        base_by_site[(s['form_id'],site_id)] = base
    def add(base, candidate, kind, provider, query_id, *, accession=None, resources='', pmids='', probability=None, loc_source=None, extra=None):
        if probability is None or pd.isna(probability):probability=base.get('localization_probability');loc_source=base.get('localization_source')
        probability = float(probability) if probability is not None and np.isfinite(float(probability)) else None
        row = dict(base); restrictions = list(base['restriction_reasons'])
        row.update(candidate_gene=candidate,candidate_accession=accession,candidate_resolution='family' if kind=='sequence_motif_candidate' else 'gene_or_accession',
            candidate_id=stable_id('candidate',[base['substrate_taxon'],candidate]),kinase_taxon=base['substrate_taxon'],
            source_taxon='9606' if kind=='curated_site_orthology' else base['substrate_taxon'],edge_type=kind,
            directness='site_relation_recorded' if kind.startswith('curated') else 'sequence_hypothesis' if kind=='sequence_motif_candidate' else 'protein_association_not_exact_site',provider=provider,
            original_resource=resources,source_query_id=query_id,PMIDs=pmids,DOIs='',reference_ids=pmids,
            orthology_method='provider_translated_exact_FASTA_site; native_validation_not_established' if kind=='curated_site_orthology' else 'not_used',
            localization_probability=probability,localization_source=loc_source,localization_status='provided' if probability is not None else 'unknown',
            duplicate_evidence_group=stable_id('publication_edge',[base['site_id'],candidate,sorted(set(re.findall(r'\d{5,9}',str(pmids))))]),
            motif_id=None,motif_version=None,motif_information_bits=None,motif_background=None,relative_candidate_weight=None,source_caution=None)
        if science:
            enzyme=identities.get(accession,{})
            enzyme_taxon=enzyme.get('taxon')
            enzyme_taxa={str(enzyme_taxon)} if enzyme_taxon is not None else set()
            for snap in sources.get('snapshots',[]):
                if snap.get('query_id')==query_id:
                    for source_row in snap.get('rows',[]):
                        if source_row.get('enzyme')==accession:
                            stated=source_row.get('enzyme_taxon',source_row.get('enzyme_taxonomy_id'))
                            if stated is not None and str(stated):enzyme_taxa.add(str(stated))
            enzyme_taxon=next(iter(enzyme_taxa)) if len(enzyme_taxa)==1 else None
            if len(enzyme_taxa)>1:restrictions.append('enzyme_taxonomy_conflict')
            row.update(kinase_taxon=str(enzyme_taxon) if enzyme_taxon is not None else None,
                candidate_id=stable_id('candidate',[str(enzyme_taxon) if enzyme_taxon is not None else 'unknown:'+query_id,accession or candidate]),
                host_taxon=reference.get('host_taxon'),reference_assay_taxon=None,
                enzyme_taxonomy_source='explicit_accession_evidence' if enzyme_taxon is not None else 'unknown',
                candidate_resolution='motif_class' if kind=='sequence_motif_candidate' else 'gene_or_accession')
            if enzyme_taxon is None:restrictions.append('enzyme_taxonomy_unresolved')
        if kind=='curated_site_orthology':restrictions.append('provider_site_translation_not_independently_aligned')
        if probability is None: restrictions.append('unresolved_localization')
        row.update(extra or {}); row['restriction_reasons']=';'.join(sorted(set(restrictions+str(row.get('additional_restrictions','')).split(';'))-{''}))
        row['edge_id']=stable_id('edge',[base['form_id'],base['site_id'],candidate,kind,query_id,resources,pmids])
        row['evidence_record_ids']=row['edge_id']; records.append(row)
    if not curated.empty:
        for r in curated.to_dict('records'):
            base=base_by_site.get((r['form_id'],r['site_id']))
            if not base: continue
            kind='curated_site_orthology' if r['annotation_evidence']=='orthology_translated_curated' else 'curated_exact_site_native'
            if r['annotation_evidence']=='curated_orthology_status_unknown':kind='curated_site_taxon_unverified'
            if not r['curated_resources']: kind='protein_level_kinase_association'
            add(base,r['kinase_gene'],kind,'OmniPath',r['source_query_id'],accession=r['enzyme'],resources=r['sources'],pmids=r['references'],
                probability=r['localization_probability'],loc_source=r['localization_source'],
                extra={'footprint_eligible':bool(base['footprint_eligible'] and r['primary_edge_eligible'] and kind!='curated_site_taxon_unverified'),
                       'source_caution':r['source_caution'],'additional_restrictions':r['exclusion_reason']})
    # Curated family rollups preserve original members/source IDs, with no isoform claim.
    for row in list(records):
        for family,members in family_groups.get(str(row['kinase_taxon'] if science else row['substrate_taxon']),{}).items():
            if row['candidate_gene'] in members:
                family_row={**row,'candidate_gene':family,'candidate_accession':None,'candidate_resolution':'family',
                    'candidate_id':stable_id('candidate',[row['kinase_taxon'] if science else row['substrate_taxon'],family]),
                    'edge_id':stable_id('edge',[row['edge_id'],family])}
                records.append(family_row)
    for relation in sources.get('relations',[]):
        if not (relation.get('enzyme_id') or relation.get('enzyme_name')): continue
        site=relation['accession']+':'+relation['site']
        for (_,sid),base in base_by_site.items():
            if sid==site:
                add(base,relation.get('enzyme_name') or relation['enzyme_id'],'curated_exact_site_native','iPTMnet',relation['query_id'],
                    accession=relation.get('enzyme_id'),resources=';'.join(relation['sources']),pmids=';'.join(relation['pmids']))
    if design['study']['ptm_type'] in {'phosphorylation','phospho'}:
        for base in base_by_site.values():
            matched=[(name,item) for name,item in library['patterns'].items() if name in background and anchored_match(item['pattern'],base['sequence_window'],7)]
            total=sum(max(background[name]['information_bits'],.05) for name,_ in matched)
            for name,item in matched:
                add(base,name,'sequence_motif_candidate','repository_motif_library',stable_id('query',[library['version']]),
                    resources=library['source'],extra={'motif_id':name,'motif_version':library['version'],
                        'motif_information_bits':background[name]['information_bits'],'motif_background':json.dumps(background[name],sort_keys=True),
                        'relative_candidate_weight':max(background[name]['information_bits'],.05)/total})
    edges=pd.DataFrame(records,columns=EDGE_COLUMNS+(['host_taxon','reference_assay_taxon','enzyme_taxonomy_source'] if science else [])).drop_duplicates('edge_id')
    return mapped, edges, {'library_version':library['version'],'background':background,'weight_meaning':'relative_sequence_support_not_probability',
                          'background_policy':'unique_gene_sequence_center; equal_gene_weight','anchoring':'named_ptm_group_exactly_at_center; terminal_padding_preserved'}


def score_candidates(tables,edges,design,*,science=False):
    contributions=[];profiles=[];sensitivity=[]
    strict=tables['strict_parent_paired'].set_index(['form_id','contrast_id']).strict_parent_A.to_dict()
    comparisons=tables['comparisons']; estimator=ContrastEstimator(design)
    tracks={'curated_A':'A','localized_A':'A','motif_A':'A','U_all':'U_all','U_joint':'U_joint','P_all':'P_all','P_joint':'P_joint','strict_parent_A':'strict_parent_A','repeated_A':'A','native_A':'A','shared_site_excluded_A':'A','source_caution_excluded_A':'A','unadjusted_only_U':'U_all'}
    sharing=edges.loc[edges.edge_type.str.startswith('curated')&edges.candidate_resolution.ne('family')].groupby('ambiguity_group').candidate_id.nunique().to_dict()
    if science:tracks['specificity_A']='A'
    for (candidate,gene), candidate_edges in edges.groupby(['candidate_id','candidate_gene'],sort=True):
        for contrast in design['contrasts']:
            meta=estimator.metadata(contrast); comp=comparisons.loc[comparisons.contrast_id.eq(contrast['contrast_id'])]
            joined=candidate_edges.merge(comp,on='form_id',suffixes=('','_quant'))
            for track,value_col in tracks.items():
                rows=joined.loc[~joined.restriction_reasons.str.contains('mapping_ineligible|inseparable_multisite|substrate_gene_unresolved')].copy() if track=='unadjusted_only_U' else joined.loc[joined.footprint_eligible.astype(bool)&joined.included.astype(bool)].copy()
                rows=rows.loc[rows.edge_type.eq('sequence_motif_candidate') if track=='motif_A' else rows.edge_type.eq('experimental_specificity_prediction') if track=='specificity_A' else rows.edge_type.isin(['curated_exact_site_native','curated_site_orthology'])]
                if track=='localized_A':rows=rows.loc[pd.to_numeric(rows.localization_probability,errors='coerce').ge(.75)&~rows.restriction_reasons.str.contains('multi_accession')]
                if track=='native_A':rows=rows.loc[rows.edge_type.eq('curated_exact_site_native')]
                if track=='shared_site_excluded_A':rows=rows.loc[rows.ambiguity_group.map(sharing).fillna(0).le(1)]
                if track=='source_caution_excluded_A':rows=rows.loc[rows.source_caution.fillna('').eq('')]
                if track=='repeated_A':rows=rows.loc[rows.reference_joint_n.ge(2)&rows.target_joint_n.ge(2)]
                if value_col=='strict_parent_A':rows[value_col]=[strict.get((r.form_id,r.contrast_id),np.nan) for r in rows.itertuples()]
                rows=rows.loc[pd.to_numeric(rows[value_col],errors='coerce').notna()]
                site_rows=[]
                # Group record indices once; avoid constructing a DataFrame for every site.
                grouped=defaultdict(list)
                for item in rows.to_dict('records'):grouped[((str(item['substrate_taxon'])+':'+item['substrate_gene']) if science else item['substrate_gene'],item['site_id'] if science else item['sequence_window'])].append(item)
                for (substrate,window),group in sorted(grouped.items()):
                    values_by_form={r['form_id']:r[value_col] for r in group}
                    combined=lambda field:';'.join(sorted({r[field] for r in group}))
                    record={'candidate_id':candidate,'contrast_id':contrast['contrast_id'],'track':track,
                        'measurement_group_id':combined('measurement_group_id'),'site_key':stable_id('site',[substrate,window]),'substrate_gene':substrate,
                        'form_ids':combined('form_id'),'site_ids':combined('site_id'),'edge_ids':combined('edge_id'),
                        'value':float(np.median(list(values_by_form.values()))),'source_query_ids':combined('source_query_id'),
                        'restriction_reasons':';'.join(sorted(set(';'.join(r['restriction_reasons'] for r in group).split(';'))-{''}))}
                    record['contribution_id']=stable_id('contribution',[candidate,contrast['contrast_id'],track,record['site_key']]);site_rows.append(record)
                genes=defaultdict(list)
                for r in site_rows:genes[r['substrate_gene']].append(r['value'])
                values={g:float(np.median(v)) for g,v in genes.items()};score=float(np.mean(list(values.values()))) if values else np.nan
                positive=sum(v>0 for v in values.values());negative=sum(v<0 for v in values.values())
                for r in site_rows:
                    r.update(gene_weight=1/len(genes),site_weight=1/len(genes[r['substrate_gene']]))
                contributions.extend(site_rows)
                member_ids=sorted(r['site_key'] for r in site_rows);adequate=len(site_rows)>=5 and len(genes)>=3
                profiles.append({'candidate_id':candidate,'candidate_gene':gene,**{k:meta[k] for k in ['contrast_id','arm_id','condition_id','reference_condition_id','time_min']},
                    'track':track,'activity_magnitude':score,'n_sites':len(site_rows),'n_genes':len(genes),
                    'n_measurement_groups':len({m for r in site_rows for m in r['measurement_group_id'].split(';')}),
                    'positive_genes':positive,'negative_genes':negative,'direction_consistency':max(positive,negative)/len(genes) if genes else np.nan,
                    'coverage_adequate':adequate,'activity_status':'descriptive_footprint' if adequate else 'low_coverage' if genes else 'not_evaluable',
                    'membership_hash':stable_id('members',member_ids),'identifiability_group':stable_id('identical_support',[contrast['contrast_id'],track,member_ids]),
                    'priority_tier':'curated_supported' if track not in {'motif_A','specificity_A'} and adequate else 'exploratory','statistic_type':'gene_balanced_effect_not_kinase_activity_test'})
                if track not in {'curated_A','motif_A','specificity_A'} or not site_rows:continue
                # Recompute medians only for genes touched by an omission; all other
                # gene medians retain their original order and values.
                by_gene=defaultdict(list)
                for r in site_rows:by_gene[r['substrate_gene']].append(r)
                for kind,column in [('gene','substrate_gene'),('site','site_key'),('measurement_group','measurement_group_id'),('source','source_query_ids')]:
                    affected=defaultdict(set)
                    for r in site_rows:
                        tokens=set(str(r[column]).split(';'))
                        for token in tokens:
                            if kind!='source' or len(tokens)==1:affected[token].add(r['substrate_gene'])
                    for omitted in sorted({v for r in site_rows for v in str(r[column]).split(';')}):
                        changed=dict(values)
                        for substrate in affected.get(omitted,set()):
                            kept=[r['value'] for r in by_gene[substrate] if (set(str(r[column]).split(';'))-{omitted} if kind=='source' else omitted not in str(r[column]).split(';'))]
                            if kept:changed[substrate]=float(np.median(kept))
                            else:changed.pop(substrate,None)
                        estimate=float(np.mean(list(changed.values()))) if changed else np.nan
                        sensitivity.append({'candidate_id':candidate,'contrast_id':contrast['contrast_id'],'track':track,'omission_kind':kind,'omitted_id':omitted,'score':estimate,'primary_score':score,'remaining_genes':len(changed),'independent_validation':False})
    return {'kinase_candidate_edges':edges,'kinase_temporal_profiles':pd.DataFrame(profiles,columns=PROFILE_COLUMNS),
            'substrate_contributions':pd.DataFrame(contributions,columns=CONTRIBUTION_COLUMNS),
            'candidate_sensitivity':pd.DataFrame(sensitivity,columns=['candidate_id','contrast_id','track','omission_kind','omitted_id','score','primary_score','remaining_genes','independent_validation'])}
