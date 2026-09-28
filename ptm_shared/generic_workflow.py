"""Immutable generic run, validated portable contract and offline scientific replay."""
from collections import defaultdict
import hashlib
import html
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
from uuid import uuid4
import zipfile

import numpy as np
import pandas as pd

from .study_design import PROFILE, VERSION as DESIGN_VERSION, clean_context, require_resolved
from .contrast_quantification import quantify_contrasts, VERSION as QUANT_VERSION, STRICT_VERSION, KEY_COLUMNS
from .normalization_provenance import normalize_supplied_matrices
from .report_compatible_quantification import read_fasta
from .annotation_registry import digest, require_compatible
from .generic_kinase import map_edges, score_contrasts, fasta_taxonomy, VERSION as KINASE_VERSION
from .study_temporal_context_resolution import resolve_study_temporal_context

VERSION='astra_contrast_bundle.v3'
CODE_FILES=['study_design.py','study_design.schema.json','study_presets.py','contrast_quantification.py','annotation_registry.py','generic_kinase.py',
    'generic_workflow.py','normalization_provenance.py','report_compatible_quantification.py','report_compatible_kinase.py',
    'study_temporal_context.py','study_temporal_context_resolution.py','probabilistic_cowave.py']
TABLE_KEYS={'summary':['form_id'],'comparisons':['form_id','contrast_id'],'primary_A_input':['form_id','contrast_id'],
    'runlevel':['form_id','injection_id'],'detection':['form_id','contrast_id'],
    'protein_contrasts':['protein_group','contrast_id'],'strict_unmodified_proteins':['protein_group','contrast_id'],
    'strict_unmodified_sequences':['protein_group','sequence','contrast_id'],
    'strict_parent_paired':['form_id','contrast_id'],'strict_parent_complete':['form_id','contrast_id'],
    'strict_parent_peptide_masks':['form_id','contrast_id','protein_group','sequence'],
    'strict_selected_sequences':['Protein.Group','Stripped.Sequence'],
    'site_mapping':['form_id','mapped_accession','residue_type','residue_offset'],
    'annotation_edges':['form_id','mapped_accession','residue_type','residue_offset','enzyme','sources','references'],
    'kinase_profiles':['entity','mode','contrast_id'],'kinase_membership':['entity','mode','contrast_id','substrate_gene','site_key'],
    'kinase_sensitivity':['entity','mode','contrast_id'],'kinase_injection_omissions':['entity','contrast_id','omitted_injection_id'],
    'emergent_kinase_evidence':['form_id','contrast_id','entity','site_id','kinase_gene'],
    'form_evidence_status':['form_id','contrast_id'],'validation_panel':['protein_group','contrast_id','layer'],
    'temporal_protein_summary':['protein_group','arm_id','reference_condition_id','layer']}
TABLE_MEANINGS={
    'summary':'Charge-collapsed PTM identity, raw and representative accession coordinates, exact FASTA mapping and parent eligibility.',
    'comparisons':'All form contrasts. A is usable for adjusted evidence only when included=true; raw values of ineligible forms are calculation traces.',
    'primary_A_input':'Only eligible adjusted form contrasts; the primary quantitative input for interpretation.',
    'runlevel':'Each raw injection once, including shared controls. Positive intensity/log values and original/joint masks; join contrast injection sets through study_design.json.',
    'detection':'Reference detection and arm-specific emergence. eligible_A uses the recorded post-reference, never an invented baseline fold change.',
    'protein_contrasts':'All PG rows with unit-balanced relative protein abundance changes; this is not a kinase substrate footprint.',
    'strict_unmodified_proteins':'Median of at least two eligible unmodified sequence contrasts for each protein group.',
    'strict_unmodified_sequences':'Individual strict sequence changes after technical/material/unit aggregation.',
    'strict_selected_sequences':'Selected unmodified representative precursor and its normalized intensities; excludes every backbone ever observed modified.',
    'strict_parent_paired':'Median of at least two peptide-specific PTM/PG/peptide jointly observed ratio contrasts, minimum two joint injections per condition.',
    'strict_parent_complete':'Alternative sensitivity restricted to peptides complete on all form joint injections in the contrast.',
    'strict_parent_peptide_masks':'Each candidate peptide, actual included injection IDs/counts, per-peptide paired ratio change, exclusion and complete-mask reasons.',
    'site_mapping':'Exact assigned residue-to-FASTA mappings, with observed FASTA taxonomy; assigned coordinates do not by themselves establish localization confidence.',
    'annotation_edges':'All observed frozen annotation joins including excluded edges, source caution, audit scope and matched localization input.',
    'kinase_profiles':'All supported observed candidates and families across contrasts and modes; gene-balanced footprint, coverage, no-call and descriptive direction.',
    'kinase_membership':'Per-site contribution after collapsing forms, retaining contributing form IDs and annotation digest; sites then collapse by gene median.',
    'kinase_sensitivity':'Source, gene and explicitly declared panel omissions; these do not replace primary scores.',
    'kinase_injection_omissions':'Recomputed unit-balanced A and gene-balanced footprint after omitting one actual reference or target injection.',
    'emergent_kinase_evidence':'Baseline-undetected forms linked to curated candidate kinase/family; retain individual post-reference and eligibility; never baseline-score contributors.',
    'form_evidence_status':'Detection → mapping → parent → baseline contrast → curated edge → coverage → evidence tier and no-call reason.',
    'validation_panel':'Only user-selected protein panel, with selection timing and declared temporal windows; same-experiment descriptive consistency.',
    'temporal_protein_summary':'All protein groups by arm/reference and layer on the actual measured grid. No interpolation, precise lag, direct regulation or causal inference.'}


def json_bytes(value):
    return json.dumps(clean_context(value),ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode('utf-8')


def json_write(path,value):
    Path(path).write_bytes(json_bytes(value))


def object_hash(value):return hashlib.sha256(json_bytes(value)).hexdigest()


def temporal_layers(analysis,design,context):
    conditions={c['condition_id']:c for c in design['conditions']};by_arm=defaultdict(set)
    for c in design['contrasts']:
        arm=conditions[c['target_condition_id']]['arm_id']
        by_arm[arm].update([c['target_condition_id'],c['reference_condition_id']])
    temporal={}
    for arm,cids in by_arm.items():
        times=sorted({conditions[cid]['time']['minutes'] for cid in cids})
        _,record=resolve_study_temporal_context(experimental_context=context,
            declared_conditions=[f'{t:g}min' for t in times],study_id=arm)
        temporal[arm]={**record,'measured_minutes':times,'early_late_policy':design.get('temporal_windows') or 'not_declared',
                       'used_for':'measured_grid_resolution_and_descriptive_protein_summary; no interpolation or lag fitting'}
    panel=design.get('validation_panel') or {};genes={str(g).upper() for g in panel.get('genes',[])}
    windows=design.get('temporal_windows') or {};panel_rows=[];summaries=[]
    for layer,table in [('PG',analysis['protein_contrasts']),('strict_unmodified',analysis['strict_unmodified_proteins'])]:
        for row in table.to_dict('records'):
            if genes.intersection(str(row['gene']).upper().split(';')):
                tags=[name for name,w in windows.items() if row['time_min']>=w.get('minimum_minutes',-np.inf) and row['time_min']<=w.get('maximum_minutes',np.inf)]
                panel_rows.append({**{k:row[k] for k in KEY_COLUMNS},'protein_group':row['protein_group'],'gene':row['gene'],
                    'layer':layer,'log2_change':row['log2_change'],'declared_windows':';'.join(sorted(tags)),
                    'selection_timing':panel.get('selection_timing','unknown'),
                    'interpretation':'same_experiment_descriptive_consistency_not_independent_validation'})
        for (group,arm,ref),rows in table.groupby(['protein_group','arm_id','reference_condition_id'],sort=True):
            measured=rows.loc[np.isfinite(rows.log2_change)].sort_values(['time_min','condition_id'])
            record=temporal.get(arm,{})
            summaries.append({'protein_group':group,'arm_id':arm,'reference_condition_id':ref,'layer':layer,
                'measured_contrasts':len(rows),'evaluable_contrasts':len(measured),'first_evaluable_time_min':measured.time_min.iloc[0] if len(measured) else None,
                'last_evaluable_time_min':measured.time_min.iloc[-1] if len(measured) else None,
                'observed_direction_changes':int(np.sum(np.diff(np.sign(measured.log2_change.to_numpy()))!=0)) if len(measured)>1 else None,
                'grid_resolution_minutes':record.get('context',{}).get('nominal_grid_interval_minutes'),
                'temporal_context_status':record.get('status'),'interpretation':'observed_timecourse_no_precise_lag_or_causal_estimate'})
    return {'validation_panel':pd.DataFrame(panel_rows,columns=KEY_COLUMNS+['protein_group','gene','layer','log2_change','declared_windows','selection_timing','interpretation']),
        'temporal_protein_summary':pd.DataFrame(summaries,columns=['protein_group','arm_id','reference_condition_id','layer','measured_contrasts','evaluable_contrasts','first_evaluable_time_min','last_evaluable_time_min','observed_direction_changes','grid_resolution_minutes','temporal_context_status','interpretation'])},temporal


def calculate(inputs,design,context,registration=None):
    require_resolved(design)
    raw_pr=pd.read_csv(inputs['PR'],sep='\t');raw_pg=pd.read_csv(inputs['PG'],sep='\t')
    columns=sorted(i['input_column'] for i in design['injections'])
    require_resolved(design,raw_pr.columns,raw_pg.columns)
    pr,pg,norm=normalize_supplied_matrices(raw_pr,raw_pg,columns,context['normalization_policy'])
    norm.update(scope='whole_study',sample_columns=columns,applications=1,parent_adjustment_is_separate=True,
        upstream_quantity_scale_status=design['study'].get('processing',{}).get('upstream_normalization','unknown_not_recorded'),
        median_QC={layer:{'before':raw[columns].apply(pd.to_numeric,errors='coerce').where(lambda v:np.isfinite(v)&v.gt(0)).median().to_dict(),'after':scaled[columns].median().to_dict()}
                   for layer,raw,scaled in [('PR',raw_pr,pr),('PG',raw_pg,pg)]})
    analysis=quantify_contrasts(pr,pg,read_fasta(inputs['FASTA']),design,design['study']['ptm_type'])
    snapshot=pd.read_csv(inputs['snapshot'],sep='\t') if registration else None
    mapped,edges=map_edges(analysis,snapshot,registration,context,fasta_taxonomy(inputs['FASTA']))
    tables={k:v for k,v in analysis.items() if isinstance(v,pd.DataFrame) and k not in {'pr','pg'}}
    tables.update(site_mapping=mapped,annotation_edges=edges)
    tables.update(score_contrasts(analysis,edges,context,registration))
    tables['primary_A_input']=tables['comparisons'].loc[tables['comparisons'].included].copy()
    temporal,temporal_context=temporal_layers(analysis,design,context);tables.update(temporal)
    states=[];profiles=tables['kinase_profiles'];members=tables['kinase_membership']
    for comparison in tables['comparisons'].to_dict('records'):
        fid=comparison['form_id'];form=tables['summary'].set_index('form_id').loc[fid]
        detected=tables['detection'].loc[tables['detection'].form_id.eq(fid) & tables['detection'].contrast_id.eq(comparison['contrast_id'])].iloc[0]
        own=edges.loc[edges.form_id.eq(fid) & edges.primary_edge_eligible.astype(bool)]
        involved=members.loc[members.contrast_id.eq(comparison['contrast_id']) & members['mode'].eq('primary_A') & members.form_ids.str.split(';').map(lambda ids:fid in ids)]
        adequate=profiles.loc[profiles.contrast_id.eq(comparison['contrast_id']) & profiles['mode'].eq('primary_A') & profiles.entity.isin(involved.entity)].coverage_adequate.any()
        reason=('mapping_ineligible' if not form.primary_mapping_eligible else 'parent_ineligible' if not form.primary_adjustment_eligible else
            'baseline_or_target_quantification_unavailable' if not comparison['included'] else 'kinase_not_run_no_annotation' if not registration else
            'no_curated_observed_edge' if own.empty else 'multisite_inseparable' if form.n_modifications!=1 else 'insufficient_kinase_coverage' if not adequate else '')
        states.append({'form_id':fid,'contrast_id':comparison['contrast_id'],'arm_id':comparison['arm_id'],'condition_id':comparison['condition_id'],
            'detected_n':int(detected.detected_n),'mapping_eligible':bool(form.primary_mapping_eligible),'parent_eligible':bool(form.primary_adjustment_eligible),
            'baseline_quantification_available':bool(comparison['included']),'curated_edge_count':len(own),'coverage_adequate':bool(adequate),
            'evidence_tier':'exploratory_footprint' if adequate else 'quantitative_form' if comparison['included'] else 'detection_only',
            'kinase_no_call_reason':reason,'localization_status':form.strict_attribution_status})
    tables['form_evidence_status']=pd.DataFrame(states,columns=['form_id','contrast_id','arm_id','condition_id','detected_n','mapping_eligible','parent_eligible','baseline_quantification_available','curated_edge_count','coverage_adequate','evidence_tier','kinase_no_call_reason','localization_status'])
    readiness={'schema_version':VERSION,'quantification':{'status':'available' if len(tables['comparisons']) else 'no_target_forms'},
        'parent_adjustment':{'status':'available' if len(tables['primary_A_input']) else 'no_eligible_comparisons'},
        'kinase':{'status':'not_run' if not registration else 'no_observed_curated_edges' if not edges.primary_edge_eligible.any() else 'no_eligible_primary_comparisons' if not len(tables['primary_A_input']) else 'exploratory',
            'reason':'quantification_only_requested' if context.get('annotation_mode')=='quantification_only' else 'annotation_unavailable' if not registration else None,
            'ptm_support':'phosphorylation_only','annotation_sha256':(registration or {}).get('sha256')},
        'strict_attribution':{'status':'localized_curated_input_available' if edges.strict_eligible.any() else 'no_call',
            'reason':'localization_not_matched' if not edges.strict_eligible.any() else 'coverage_still_required; not_causal_activity_validation'},
        'biological_inference':{'status':'unavailable','reason':'no_biological_pq_method_implemented','replication_declaration':design['replication_declaration']},
        'temporal':{'status':'descriptive_only','arm_contexts':temporal_context,'causal_or_precise_lag_inference':False},
        'source_caution':sorted(set(edges.source_caution.dropna())-{''}),
        'orthology_translation':(registration or {}).get('metadata',{}).get('orthology_translation','unknown'),
        'unsupported_features':['legacy_LLM_RAG_network_execution','biological_significance_tests','absolute_occupancy','causal_kinase_activity'],
        'missing_does_not_mean_inactive':True}
    return tables,norm,readiness


def validate_tables(tables,directory):
    dictionary={'schema_version':VERSION,'tables':{}}
    for name,frame in tables.items():
        keys=TABLE_KEYS[name]
        if not len(frame.columns) or frame.columns.duplicated().any():raise ValueError('Invalid CSV schema: '+name)
        if frame.duplicated(keys).any():raise ValueError('Duplicate scientific row key: '+name)
        if any(frame[k].isna().any() for k in keys):
            # An absent source/reference is an explicit component of an annotation edge key.
            if name!='annotation_edges':raise ValueError('Missing scientific row key: '+name)
        path=directory/(name+'.csv');frame.to_csv(path,index=False)
        read=pd.read_csv(path)
        if list(read.columns)!=list(frame.columns) or len(read)!=len(frame):raise ValueError('CSV write verification failed: '+name)
        dictionary['tables'][path.name]={'row_grain':' × '.join(keys),'unique_key':keys,'rows':len(frame),'columns':list(frame.columns),
            'meaning':TABLE_MEANINGS[name],
            'value_definitions':{'A':'target minus reference of same-injection log2(PTM/PG), unit-balanced; requires eligibility',
                'U_joint':'PTM log2 contrast on the exact A mask','P_joint':'PG log2 contrast on the exact A mask',
                'U_all':'PTM contrast on its own observed mask','P_all':'PG contrast on its own observed mask',
                'biological_n':'declared units with usable values, never raw injection count; unknown when undeclared',
                'statistical_unit':'declared biological unit/pair, material or explicitly unresolved observation; no p/q generated',
                'gene_balanced_mean':'mean of gene medians of site medians; coverage is at least five sites and three genes',
                'localization_probability':'supplied accession/residue/form evidence only; null means unknown',
                'eligible_A':'parent-eligible post-reference A, whose reference is identified on that row'},
            'join_keys':[k for k in keys if k.endswith('_id') or k in {'protein_group','entity'}],
            'units':'log2 relative contrast for A/U/P, ratios and changes; minutes for *_min; intensity in supplied matrix units',
            'missing':'unobserved/unavailable; never zero-filled. Inspect status, eligibility and exclusion reason fields.',
            'inference':'descriptive only; form_A=U_joint-P_joint; nonlinear kinase medians do not preserve that identity'}
    return dictionary


def build_report(design,provenance,tables,readiness):
    study=design['study'];profiles=tables['kinase_profiles']
    selected=profiles.loc[profiles['mode'].eq('primary_A')].sort_values(['coverage_adequate','n_substrate_genes','n_sites_or_units','entity','contrast_id'],ascending=[False,False,False,True,True])
    lines=['# PTM primary A evidence',f"Order: {provenance['order_code']} | Run: {provenance['run_id']}",
        f"Provenance: {provenance['provenance_id']}",f"Organism/taxonomy: {study.get('species')} / {study.get('taxonomy_id')}",
        f"PTM: {study.get('ptm_type')} | Treatment: {study.get('treatment')} | Cell/tissue: {study.get('cell_type') or study.get('tissue')}",
        f"Research question: {study.get('biological_question')}",f"Primary eligible form × contrast rows: {len(tables['primary_A_input'])}.",
        'A is a same-injection PTM/parent log ratio contrast, summarized within material and then equally across declared biological units or pairs. U_joint/P_joint use identical masks. U_all/P_all retain their own masks. Additional normalization is applied once across the recorded study sample set.',
        'These relative abundance ratios are not absolute PTM occupancy. Technical injections are not independent biological units; no biological p/q is generated.',
        '## Kinase candidates',
        'Display selection: all observed annotation candidates, including no-call rows; sorted by coverage, substrate genes, sites, entity and contrast. Families and individual kinases are separate entities.',
        '| Candidate | Target / reference | Score | Sites / genes | Status |','|---|---|---:|---:|---|']
    for row in selected.itertuples():
        score=f'{row.gene_balanced_mean:.5g}' if np.isfinite(row.gene_balanced_mean) else 'unavailable'
        lines.append(f'| {row.entity} | {row.target_label} / {row.reference_label} | {score} | {row.n_sites_or_units} / {row.n_substrate_genes} | {row.status} |')
    if selected.empty:lines.append('Kinase results unavailable: '+str(readiness['kinase']))
    lines.extend(['## Interpretation boundaries',
        'All protein groups and selected strict-unmodified sequences are exported. An optional validation panel is descriptive evidence from the same experiment, not independent validation. No early/late boundary is assigned unless declared in study_design.json.',
        'Baseline-undetected forms retain detection and their own arm-specific post-reference. No invented baseline fold change is used; different post-references must not be pooled as baseline evidence.',
        'Curated substrate footprints are exploratory associations. Kinase protein abundance, a kinase phosphosite and a substrate-set footprint are different evidence types. No-call coverage, mapping or localization does not establish biological inactivity.',
        '## Actual readiness',json.dumps(clean_context(readiness),indent=2,ensure_ascii=False),
        '## Original study context',json.dumps(study['original_context'],indent=2,ensure_ascii=False)])
    return '\n\n'.join(lines)+'\n'


def portable_files(directory,inputs,context,design,registration,run_context):
    (directory/'inputs').mkdir(exist_ok=True);(directory/'code'/'ptm_shared').mkdir(parents=True)
    copied={}
    for key,path in inputs.items():
        name={'PR':'PR.tsv','PG':'PG.tsv','FASTA':'reference.fasta','snapshot':'snapshot.tsv'}[key]
        target=directory/'inputs'/name
        if Path(path).resolve()!=target.resolve():shutil.copyfile(path,target)
        copied[key]=str(target.relative_to(directory))
    annotation=None
    if registration:
        annotation={k:v for k,v in registration.items() if k not in {'snapshot_path','reference_dir'}}
        (directory/'annotation').mkdir()
        audit_names={'annotation_metadata.json'}|set(annotation.get('metadata',{}).get('required_files',[]))|set(annotation.get('metadata',{}).get('file_sha256',{}))
        for name in sorted(audit_names):
            if Path(name).name!=name or name.startswith('.') or name.endswith(('.pem','.key')):raise ValueError('Unsupported annotation audit file name')
            path=Path(registration['reference_dir'])/name
            if path.is_file():shutil.copyfile(path,directory/'annotation'/name)
    for name in CODE_FILES:shutil.copyfile(Path(__file__).parent/name,directory/'code'/'ptm_shared'/name)
    (directory/'code'/'ptm_shared'/'__init__.py').write_text('')
    json_write(directory/'replay_config.json',{'schema_version':VERSION,'inputs':copied,'context':context,'design':design,
        'annotation':annotation,'run_context':run_context})
    (directory/'rerun.py').write_text("import argparse\nfrom pathlib import Path\nimport sys\nROOT=Path(__file__).resolve().parent\nsys.path.insert(0,str(ROOT/'code'))\nfrom ptm_shared.generic_workflow import replay_bundle\np=argparse.ArgumentParser(description='Offline scientific replay and comparison, atol=rtol=1e-10')\np.add_argument('--output',type=Path,required=True)\na=p.parse_args()\nreplay_bundle(ROOT,a.output)\n")
    versions={'python':platform.python_version(),**{name:importlib.metadata.version(name) for name in ['numpy','pandas']}}
    json_write(directory/'software_versions.json',versions)
    (directory/'requirements.txt').write_text('numpy=='+versions['numpy']+'\npandas=='+versions['pandas']+'\n')


def run_generic_analysis(order_id,config,output_dir,checkpoint=lambda:None,progress=lambda message:None):
    context=clean_context(config['experimental_context']);design=context['study_design']
    inputs={key:Path(config[name]) for key,name in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    registration=None
    if config.get('frozen_annotation'):
        f=config['frozen_annotation'];registration=require_compatible(Path(f['reference_dir']).parent,f['sha256'],design['study']['taxonomy_id'],design['study']['ptm_type'])
        inputs['snapshot']=Path(registration['snapshot_path'])
    if context.get('annotation_mode')=='required' and not registration:raise ValueError('Required kinase annotation is unavailable')
    run_id=f"g{int(config.get('run_generation') or 0)}-{uuid4().hex}"
    root=Path(output_dir);directory=root/'enrichment_free_runs'/run_id;directory.mkdir(parents=True,exist_ok=False)
    (directory/'inputs').mkdir()
    frozen_inputs={};input_hashes={}
    for key,path in inputs.items():
        expected=digest(path);name={'PR':'PR.tsv','PG':'PG.tsv','FASTA':'reference.fasta','snapshot':'snapshot.tsv'}[key]
        target=directory/'inputs'/name;shutil.copyfile(path,target)
        if digest(target)!=expected or digest(path)!=expected:raise ValueError('Input changed while freezing run bytes')
        frozen_inputs[key]=target;input_hashes[key]=expected
    inputs=frozen_inputs
    progress('Calculating canonical condition contrasts, paired parent ratios and all protein groups')
    tables,norm,readiness=calculate(inputs,design,context,registration);checkpoint()
    context_artifact={'schema_version':'study_context.v3','original_context':design['study']['original_context'],
        'study':design['study'],'arms':design['arms'],'field_provenance':design['field_provenance'],'issues':design.get('issues',[]),
        'interpretation_context':{k:v for k,v in context.items() if k in {'rag_collections','rag_collection','literature_settings','literature_context','biological_question','special_conditions'}},
        'literature_collection_contents_included':False,'effective_settings':context}
    provenance={'schema_version':VERSION,'order_id':order_id,'order_code':config['order_code'],'run_id':run_id,
        'run_generation':config.get('run_generation'),'analysis_profile':PROFILE,'analysis_preset':None,
        'study_design_sha256':object_hash(design),'study_context_sha256':object_hash(context_artifact),
        'input_hashes':input_hashes,'estimator_versions':{'quantification':QUANT_VERSION,'kinase':KINASE_VERSION,'strict_parent_default':STRICT_VERSION,'export':VERSION},
        'annotation':{k:v for k,v in (registration or {}).items() if k not in {'reference_dir','snapshot_path'}},
        'design_schema':DESIGN_VERSION,'normalization':norm,'result_policy':'immutable_run; recompute; no_relabelled_cache',
        'code_sha256':{name:digest(Path(__file__).parent/name) for name in CODE_FILES}}
    provenance['provenance_id']=object_hash(provenance)
    progress('Validating scientific table keys and writing a portable Astra bundle')
    dictionary=validate_tables(tables,directory)
    for name,value in [('study_context',context_artifact),('study_design',design),('provenance',provenance),('analysis_readiness',readiness),('data_dictionary',dictionary),('normalization_provenance',norm)]:json_write(directory/(name+'.json'),value)
    report=build_report(design,provenance,tables,readiness)
    (directory/'evidence_report.md').write_text(report,encoding='utf-8')
    (directory/'evidence_report.html').write_text('<!doctype html><html><meta charset="utf-8"><title>PTM evidence</title><body><pre style="white-space:pre-wrap">'+html.escape(report)+'</pre></body></html>',encoding='utf-8')
    (directory/'README_ASTRA.md').write_text('# Astra analysis contract\n\nRead study_context.json and study_design.json first, then analysis_readiness.json, provenance.json and data_dictionary.json. Primary input: primary_A_input.csv. comparisons.csv retains unavailable and excluded rows. Read runlevel, detection, annotation audits and sensitivity before interpreting footprints.\n\n'+report+'\nOffline replay: install the recorded numpy/pandas versions in an isolated environment, then run `python rerun.py --output replay`. All scientific CSVs are recomputed from raw input bytes. Numeric/missing/text equality and byte equality are reported separately. No network or server registry is required. Raw inputs are included. Never treat no-call as biological inactivity.\n',encoding='utf-8')
    portable_files(directory,inputs,context,design,registration,{'order_id':order_id,'run_id':run_id})
    if any(digest(path)!=input_hashes[key] for key,path in inputs.items()):raise ValueError('Frozen input bytes changed during calculation')
    contract={'schema_version':VERSION,'primary_input':'primary_A_input.csv','primary_value':'A','primary_eligibility':'included == true',
        'row_grain':'form_id × contrast_id','profile':PROFILE,'provenance_id':provenance['provenance_id'],'explanatory_channels':['U_joint','P_joint','U_all','P_all']}
    json_write(directory/'primary_input_contract.json',contract)
    checkpoint()
    files={str(p.relative_to(directory)):{'bytes':p.stat().st_size,'sha256':digest(p),**({'rows':dictionary['tables'][p.name]['rows'],'columns':dictionary['tables'][p.name]['columns']} if p.name in dictionary['tables'] else {})}
           for p in sorted(directory.rglob('*')) if p.is_file()}
    json_write(directory/'manifest.json',{'schema_version':VERSION,'run_id':run_id,'provenance_id':provenance['provenance_id'],'files':files})
    pending=root/(f'.enrichment_free_{run_id}.zip');archive=root/(f'enrichment_free_{run_id}.zip')
    with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED) as out:
        for name in [*files,'manifest.json']:out.write(directory/name,name)
    with zipfile.ZipFile(pending) as out:
        if out.testzip():raise ValueError('ZIP integrity verification failed')
        for name,info in files.items():
            if hashlib.sha256(out.read(name)).hexdigest()!=info['sha256']:raise ValueError('ZIP manifest checksum mismatch')
    checkpoint();pending.replace(archive)
    artifacts={name:{'path':str(p.relative_to(root)),'sha256':digest(p)} for name,p in {
        'astra':archive,'report':directory/'evidence_report.html','report_markdown':directory/'evidence_report.md',
        'primary_input':directory/'primary_A_input.csv','provenance':directory/'provenance.json'}.items()}
    result={'schema_version':VERSION,'run_id':run_id,'provenance':provenance,'artifacts':artifacts,'primary_input_contract':contract,
        'counts':{'forms':len(tables['summary']),'primary_comparisons':len(tables['primary_A_input']),'kinase_profiles':len(tables['kinase_profiles'])},
        'analysis_readiness':readiness,'primary_profiles':json.loads(tables['kinase_profiles'].loc[tables['kinase_profiles']['mode'].eq('primary_A')].to_json(orient='records'))}
    json_write(directory/'platform_run.json',result)
    pointer=root/f'.enrichment_free_{run_id}.json';json_write(pointer,result);checkpoint();pointer.replace(root/'enrichment_free_current.json')
    return result


def replay_bundle(directory,output):
    directory=Path(directory).resolve();output=Path(output).resolve()
    if output==directory or directory in output.parents:raise ValueError('Replay output must be outside the immutable source bundle')
    manifest=json.loads((directory/'manifest.json').read_text())
    for name,info in manifest['files'].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or digest(path)!=info['sha256']:raise ValueError('Bundle integrity failure: '+name)
    config=json.loads((directory/'replay_config.json').read_text())
    inputs={k:directory/v for k,v in config['inputs'].items()}
    tables,_,_=calculate(inputs,config['design'],config['context'],config['annotation'])
    output.mkdir(parents=True,exist_ok=False);validate_tables(tables,output)
    records=[]
    for name in sorted(tables):
        left=pd.read_csv(directory/(name+'.csv'));right=pd.read_csv(output/(name+'.csv'))
        pd.testing.assert_frame_equal(left,right,check_dtype=False,check_exact=False,atol=1e-10,rtol=1e-10)
        if not left.isna().equals(right.isna()):raise AssertionError('Missing mask differs: '+name)
        maximum=0.
        for col in left:
            if pd.api.types.is_numeric_dtype(left[col]) and not pd.api.types.is_bool_dtype(left[col]):
                delta=(left[col]-right[col]).abs().max()
                if pd.notna(delta):maximum=max(maximum,float(delta))
        records.append({'table':name,'rows':len(left),'numeric_missing_text_keys_equal':True,
            'byte_identical':digest(directory/(name+'.csv'))==digest(output/(name+'.csv')),'maximum_absolute_difference':maximum})
    json_write(output/'replay_comparison.json',{'atol':1e-10,'rtol':1e-10,'tables':records})
    print(json.dumps({'tables':len(records),'numerically_equal':len(records),'byte_identical':sum(r['byte_identical'] for r in records)}))
    return records
