"""Astra v4 orchestrator: immutable inputs → typed evidence → validated archive.

Legacy v2/v3 runs remain readable and use their original entry points. This
contract exports the v3 tables under quant/ with an explicit migration map.
"""
from contextlib import contextmanager
import hashlib
import html
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import re
import shutil
import time
from uuid import uuid4
import zipfile

import numpy as np
import pandas as pd

from .astra_plan import PROFILE, resolve_plan, effective_context, validate_execution
from .astra_inputs import capture_order, transfer_contract, stable_id, sanitize_research
from .astra_sources import resolve_sources
from .astra_discovery import discover, mapped_sites, score_candidates, VERSION as KINASE_VERSION
from .astra_temporal import integrate_temporal
from .astra_evidence import quantitative_evidence, censoring_bounds, candidate_context_and_omissions
from .generic_workflow import calculate, json_write, json_bytes, object_hash, CODE_FILES as V3_CODE, TABLE_KEYS
from .annotation_registry import digest
from .generic_kinase import fasta_taxonomy

VERSION='astra_analysis_package.v4'
CODE_FILES=sorted(set(V3_CODE+['astra_plan.py','astra_inputs.py','astra_sources.py','astra_discovery.py','astra_temporal.py',
    'astra_evidence.py','astra_figures.py','astra_package.py','kea3_evidence.py','motif_candidate_calibration.py','motif_library.json',
    'substrate_temporal_dynamics.py','kinase_trajectory_evidence.py','directed_temporal_relationship.py']))
EXTRA_KEYS={'kinase_candidate_edges':['edge_id'],'kinase_temporal_profiles':['candidate_id','contrast_id','track'],
    'substrate_contributions':['contribution_id'],'candidate_sensitivity':['candidate_id','contrast_id','track','omission_kind','omitted_id'],
    'temporal_series':['series_id'],'ptm_temporal_features':['feature_id'],'protein_temporal_features':['feature_id'],
    'kinase_temporal_features':['feature_id'],'kinase_fixed_membership':['candidate_id','series_id','contrast_id','track'],
    'target_excluded_anchors':['candidate_id','series_id','track','site_key'],'cross_layer_links':['link_id'],
    'parent_adjustment_impact':['impact_id'],'technical_injection_omissions':['form_id','contrast_id','omitted_injection_id'],
    'normalization_offsets':['form_id','contrast_id'],'emergence_evidence':['emergence_id'],
    'feature_evidence_ledger':['evidence_id'],'technical_dispersion':['form_id','condition_id','material_id','track'],
    'input_field_manifest':['source_field_path'],'source_query_ledger':['query_id'],'kea3_results':['library','kinase'],
    'coverage_funnel':['metric','denominator'],'kinase_candidate_summary':['candidate_id','series_id'], 'censoring_bounds':['bound_id'],
    'kinase_protein_context':['candidate_id','contrast_id','protein_group'],'kinase_self_site_context':['candidate_id','form_id','contrast_id'],
    'kinase_technical_omissions':['candidate_id','contrast_id','track','omitted_injection_id']}


def quant_cached(inputs,design,context,root,fingerprint):
    """Validated immutable stage cache, including failed-run successes; never a stale relabel."""
    cache=Path(root)/'.astra_stage_cache'/fingerprint;descriptor=cache/'stage.json'
    if descriptor.is_file():
        meta=json.loads(descriptor.read_text());tables={};valid=True
        for name,item in meta['tables'].items():
            path=cache/(name+'.csv')
            if not path.is_file() or digest(path)!=item['sha256']:valid=False;break
            tables[name]=pd.read_csv(path,float_precision='round_trip')
        if valid:
            # These v3 context-only projections are rebuilt, never copied from old questions/panels.
            from .generic_workflow import temporal_layers
            layers,_=temporal_layers(tables,design,context);tables.update(layers)
            return (tables,meta['normalization'],meta['readiness']),{'status':'reused','fingerprint':fingerprint,'origin_analysis_run_id':meta['origin_run_id']}
    result=calculate(inputs,design,{**context,'annotation_mode':'quantification_only'},None)
    tables,norm,readiness=result;pending=cache.with_name('.'+fingerprint+'-'+uuid4().hex);pending.mkdir(parents=True)
    files={}
    for name,df in tables.items():
        path=pending/(name+'.csv');df.to_csv(path,index=False);files[name]={'sha256':digest(path),'rows':len(df)}
    json_write(pending/'stage.json',{'fingerprint':fingerprint,'origin_run_id':Path(inputs['PR']).parents[1].name,
                                    'tables':files,'normalization':norm,'readiness':readiness})
    if not cache.exists():pending.rename(cache)
    # Concurrent writers keep the first complete immutable stage; no deletion of another run.
    return result,{'status':'computed','fingerprint':fingerprint,'origin_analysis_run_id':Path(inputs['PR']).parents[1].name}


@contextmanager
def stage(name,metrics,checkpoint,progress):
    checkpoint();progress(name);start=time.monotonic()
    try:yield
    except Exception:
        metrics.append({'stage':name,'status':'failed','elapsed_seconds':time.monotonic()-start});raise
    metrics.append({'stage':name,'status':'completed','elapsed_seconds':time.monotonic()-start,
        'process_peak_memory_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024)})
    checkpoint()


def compute_science(inputs,design,context,sources,*,quant=None,alternative=None,checkpoint=lambda:None,execute=lambda name,fn:fn()):
    context=effective_context(context)
    if quant is None:quant=calculate(inputs,design,{**context,'annotation_mode':'quantification_only'},None)
    tables,norm,readiness=quant
    if alternative is None:
        other='legacy_median.v1' if context['normalization_policy']=='already_normalized.v1' else 'already_normalized.v1'
        alternative=calculate(inputs,design,{**context,'normalization_policy':other,'annotation_mode':'quantification_only'},None)
    alt_tables,alt_norm,_=alternative;checkpoint()
    mapped,edges,motif=execute('discover_regulators',lambda:discover(tables,design,inputs['FASTA'],context,sources))
    tables['site_mapping']=mapped
    discovery=execute('score_regulator_footprints',lambda:score_candidates(tables,edges,design));checkpoint()
    evidence=quantitative_evidence(tables,alt_tables,design,norm,alt_norm,{**discovery,'source_queries':sources['queries']})
    temporal=execute('integrate_temporal_layers',lambda:integrate_temporal(tables,discovery,design,context,sources.get('context'),evidence['parent_adjustment_impact']));checkpoint()
    evidence['censoring_bounds']=censoring_bounds(tables,design,context.get('detection_limit_model'))
    discovery.update(candidate_context_and_omissions(tables,discovery,evidence['technical_injection_omissions']))
    scientific={**{'quant/'+k:v for k,v in tables.items()},**{'kinase/'+k:v for k,v in discovery.items()},
                **{'temporal/'+k:v for k,v in temporal.items()},**{'evidence/'+k:v for k,v in evidence.items()}}
    queries=[]
    for q in sources['queries']:
        queries.append({k:q.get(k) for k in ['query_id','provider','provider_version','parser_version','status','retrieved_utc','response_sha256','license_scope','endpoint','cache_hit','reason']}|
                       {'query':json.dumps(q.get('query'),ensure_ascii=False,sort_keys=True),'raw_payload_ref':'references/source_pin.json#/queries/'+str(len(queries))})
    queries.append({'query_id':stable_id('query',[motif['library_version']]),'provider':'repository_motif_library','provider_version':motif['library_version'],'parser_version':'exact_center.v1','status':'hit','response_sha256':digest(Path(__file__).with_name('motif_library.json')),'license_scope':'repository','query':'observed_unique_gene_sequence_center','raw_payload_ref':'methods/motif.json'})
    scientific['references/source_query_ledger']=pd.DataFrame(queries,columns=['query_id','provider','provider_version','parser_version','status','retrieved_utc','response_sha256','license_scope','endpoint','cache_hit','reason','query','raw_payload_ref'])
    scientific['kinase/kea3_results']=pd.DataFrame(sources.get('kea',[]),columns=['kinase','library','rank','score','p_value','q_value','statistic_type','overlapping_genes','background','direction','direct_site_evidence','source_row_position','query_id'])
    # Fixed public summary policy: all candidates, source tiers then independent gene coverage.
    summaries=[];profiles=discovery['kinase_temporal_profiles'];features=temporal['kinase_temporal_features']
    for (candidate,sid),fs in features.groupby(['entity_id','series_id'],sort=True):
        es=edges.loc[edges.candidate_id.eq(candidate)];pr=profiles.loc[profiles.candidate_id.eq(candidate)]
        summaries.append({'candidate_id':candidate,'series_id':sid,'candidate_name':es.candidate_gene.iloc[0],
            'curated_edges':int(es.edge_type.str.startswith('curated').sum()),'motif_edges':int(es.edge_type.eq('sequence_motif_candidate').sum()),
            'source_count':es.provider.nunique(),'unique_publications':len(set(re.findall(r'\b\d{5,9}\b',';'.join(es.PMIDs.fillna('').astype(str))))),
            'biological_evidence_count':None,'maximum_independent_genes':int(pr.n_genes.max()),
            'footprint_evaluable':bool(pr.coverage_adequate.any()),'kinase_protein_abundance':'see protein tables; absence does not remove candidate',
            'priority_rule':'curated tier, independent genes, coverage, consistency; no composite probability',
            'activity_is_separate':True})
    scientific['kinase/kinase_candidate_summary']=pd.DataFrame(summaries,columns=['candidate_id','series_id','candidate_name','curated_edges','motif_edges','source_count','unique_publications','biological_evidence_count','maximum_independent_genes','footprint_evaluable','kinase_protein_abundance','priority_rule','activity_is_separate'])
    counts={'forms':len(tables['summary']),'mapped_forms':int(tables['summary'].primary_mapping_eligible.sum()),
            'parent_eligible':int(tables['summary'].primary_adjustment_eligible.sum()),'primary_comparisons':len(tables['primary_A_input']),
            'repeated_comparisons':int((tables['primary_A_input'].reference_joint_n.ge(2)&tables['primary_A_input'].target_joint_n.ge(2)).sum()),
            'candidate_entities':edges.candidate_id.nunique(),'candidate_edges':len(edges),'kinase_profile_rows':len(profiles),
            'protein_groups':tables['protein_contrasts'].protein_group.nunique()}
    scientific['evidence/coverage_funnel']=pd.DataFrame([{'metric':k,'count':v,'denominator':'all_forms' if k in {'mapped_forms','parent_eligible'} else 'recorded_row_grain',
        'denominator_count':len(tables['summary']) if k in {'mapped_forms','parent_eligible'} else v} for k,v in counts.items()])
    failed=[{'provider':q['provider'],'status':q['status'],'reason':q.get('reason')} for q in sources['queries'] if q['status'] not in {'hit','no_hit'}]
    readiness.update(schema_version=VERSION,completion_status='completed_with_limitations' if failed or not edges.localization_probability.notna().any() else 'completed',
        kinase={'status':'not_applicable' if design['study']['ptm_type'] not in {'phosphorylation','phospho'} else 'candidates_with_separate_activity_evaluation' if len(edges) else 'no_observed_edge',
                'curated_edges':int(edges.edge_type.str.startswith('curated').sum()),'motif_edges':int(edges.edge_type.eq('sequence_motif_candidate').sum())},
        strict_attribution={'status':'localized_subset_available' if pd.to_numeric(edges.localization_probability,errors='coerce').ge(.75).any() else 'no_call','reason':'actual matched localization required'},
        temporal={'status':'measured_grid_descriptive','series':len(temporal['temporal_series']),'precise_lag':'unavailable'},
        protein_integration={'status':'available','scope':'all_PG_and_strict_unmodified; evidence_constrained_links'},
        provider_limitations=failed,normalization_sensitivity={'status':'computed','primary':context['normalization_policy'],'alternative':alt_norm['normalization_policy']},
        LOD_bounds={'status':'conditional_supplied_model' if evidence['censoring_bounds'].status.eq('conditional_lower_bound').any() else 'unavailable','reason':'supplied_limits_only; no_limit_inferred_from_data'},
        needed_for_stronger_attribution=['identity_matched_localization','more_independent_substrate_genes','independent_biological_design_or_validation'])
    return scientific,norm,alt_norm,readiness,motif,counts


def validate_science(tables,design):
    forms=set(tables['quant/summary'].form_id);contrasts={c['contrast_id'] for c in design['contrasts']};candidates=set(tables['kinase/kinase_candidate_edges'].candidate_id)
    edges=set(tables['kinase/kinase_candidate_edges'].edge_id)
    conditions={c['condition_id'] for c in design['conditions']}
    series=set(tables['temporal/temporal_series'].series_id)
    feature_ids=set().union(*(set(tables['temporal/'+k].feature_id) for k in ['ptm_temporal_features','kinase_temporal_features','protein_temporal_features']))
    missing=(set(TABLE_KEYS)|set(EXTRA_KEYS)-{'input_field_manifest'})-{name.rsplit('/',1)[-1] for name in tables}
    if missing:raise ValueError('Required scientific table missing: '+','.join(sorted(missing)))
    checks=[]
    for name,df in tables.items():
        short=name.split('/')[-1];keys=TABLE_KEYS.get(short) if name.startswith('quant/') else EXTRA_KEYS.get(short)
        if keys and (any(k not in df for k in keys) or df.duplicated(keys).any()):raise ValueError('Duplicate/missing row key: '+name)
        if not len(df.columns):raise ValueError('Missing header: '+name)
        for column,universe in [('form_id',forms),('contrast_id',contrasts),('candidate_id',candidates),('condition_id',conditions),('reference_condition_id',conditions),('series_id',series),('source_evidence_id',feature_ids),('target_evidence_id',feature_ids)]:
            if column in df and not set(df[column].dropna())<=universe:raise ValueError('Foreign key mismatch: '+name+'/'+column)
        for column,universe in [('form_ids',forms),('edge_ids',edges),('candidate_edge_ids',edges),('candidate_ids',candidates)]:
            if column in df:
                values=set(';'.join(df[column].dropna().astype(str)).split(';'))-{''}
                if not values<=universe:raise ValueError('Foreign key mismatch: '+name+'/'+column)
        checks.append({'check_id':name,'schema_keys_FK':'passed','rows':len(df),'unique_key':keys})
    comparison=tables['quant/comparisons'];finite_rows=comparison.loc[comparison.included]
    if len(finite_rows) and not np.allclose(finite_rows.A.to_numpy(float),(finite_rows.U_joint-finite_rows.P_joint).to_numpy(float),atol=1e-10,rtol=1e-10):raise ValueError('Same-mask form identity failed')
    offset=tables['evidence/normalization_offsets'].dropna(subset=['expected_A_offset','observed_A_offset'])
    if len(offset) and not np.allclose(offset.expected_A_offset.to_numpy(float),offset.observed_A_offset.to_numpy(float),atol=1e-10,rtol=1e-10):raise ValueError('Normalization factor offset mismatch')
    checks.append({'check_id':'same_mask_identity_and_scaling_offsets','status':'passed'})
    return checks


def write_tables(tables,directory):
    dictionary={}
    for name,frame in tables.items():
        path=directory/(name+'.csv');path.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(path,index=False)
        read=pd.read_csv(path,low_memory=False)
        if list(read)!=list(frame) or len(read)!=len(frame):raise ValueError('CSV write truncated: '+name)
        short=name.split('/')[-1];keys=TABLE_KEYS.get(short) if name.startswith('quant/') else EXTRA_KEYS.get(short)
        dictionary[name+'.csv']={'rows':len(frame),'columns':list(frame),'unique_key':keys,
            'dtypes':{k:str(v) for k,v in frame.dtypes.items()},'nullable':True,
            'missing':'unobserved/unavailable; never zero; status/reasons accompany quantities',
            'units':'minutes; log2 relative contrast; original positive intensity; counts as named',
            'row_grain':keys,'inference':'descriptive; p/q only explicitly labeled external gene-set statistics'}
    return dictionary


from .astra_figures import figure_packet


def start_here(snapshot,counts,readiness):
    original=snapshot['original']
    return '\n\n'.join(['# START HERE — Astra analysis package',f"Project: {original.get('project_name')} | Order: {original.get('order_code')}",
        'Read study/STUDY_BRIEF.md, user_input_snapshot.json, study_design.json, analysis_plan.json, references/source_pin.json and methods/statistics_inventory.json first.',
        'Use the complete biological question, report_options.research_questions, special conditions and selected literature. Do not ask again for information already supplied. Expectations are not measurements.',
        'Primary quantitative evidence: quant/primary_A_input.csv. Check actual masks and rows when a summary conflicts; record the conflict.',
        json.dumps(counts,ensure_ascii=False),'Profile rows are candidate × contrast × track, not discovered or activated kinase counts.',
        'Kinase protein abundance, observed kinase regulatory sites and substrate footprints are separate evidence. Curated native, orthology, motif, KEA/network and literature hypotheses must remain distinct.',
        'Include baseline-undetected emergence and post-reference evidence without inventing baseline FC. Different post-references cannot be averaged as one baseline curve.',
        'Explain U/P/A and alternate-parent/normalization effects using parent_adjustment_impact and raw masks. Ratios are not absolute occupancy.',
        'Evaluate direction, observed onset/peak/duration/recovery/order on the measured grid, including gaps and censoring; do not infer precise lag or causality from sparse sampling.',
        'Full PG and strict-unmodified proteins are same-experiment supporting evidence. Mathematical parent coupling and shared normalization/baseline are not independent validation.',
        'Missing detection, unavailable annotation, low coverage and strict no-call are not kinase inactivity. Do not invent localization, biological replicates, p/q or primary-literature conclusions.',
        'Compare supplied papers and additional primary literature using cell model/species/receptor overexpression/treatment/dose/starvation/time/acquisition/enrichment/method differences. Distinguish concordant, discrepant and not evaluable. Never claim unread attachments were compared.',
        'If Nature full article is requested, prepare Abstract, Introduction, Results, Discussion, Methods, Data/Code availability, Figure legends, numbered references and limitations. Validate citation-order PMID/DOI/title/author/year. Incomplete bibliography requires lookup.',
        'Retain a claim-to-evidence table linking each main result to exact table/row IDs, supporting and opposing observations, and source queries. Database relationships are prior knowledge, not direct measurements in this experiment.',
        'No superiority over Astra-only or enriched experiments has been established. See evidence/readiness.json for performed, limited and unavailable stages.',
        'Offline: install reproducibility/requirements.txt in an isolated environment, then python replay.py --output <new-directory>. All raw inputs and permitted pinned source records are included; no network calls occur.'])+'\n'


def run_astra_analysis(order_id,config,output_dir,checkpoint=lambda:None,progress=lambda message:None):
    context=sanitize_research(effective_context(config['experimental_context']));design=context['study_design']
    validate_execution(context,design['study']['ptm_type'],config['species_tax_id'])
    root=Path(output_dir);run_id=f"g{int(config.get('run_generation') or 0)}-{uuid4().hex}"
    directory=root/'enrichment_free_runs'/run_id;directory.mkdir(parents=True,exist_ok=False)
    for folder in ['study','inputs','references','methods','evidence','reproducibility']: (directory/folder).mkdir()
    metrics=[];inputs={};hashes={}
    with stage('resolve_inputs_and_plan',metrics,checkpoint,progress):
        for key,field,name in [('PR','pr_matrix_path','PR.tsv'),('PG','pg_matrix_path','PG.tsv'),('FASTA','fasta_path','reference.fasta')]:
            original=Path(config[field]);sha=digest(original);target=directory/'inputs'/name;shutil.copyfile(original,target)
            if digest(target)!=sha or digest(original)!=sha:raise ValueError('Input changed during immutable capture')
            inputs[key]=target;hashes[key]=sha
        snapshot=config.get('user_input_snapshot') or capture_order({'id':order_id,'order_code':config['order_code'],'analysis_context':context})
        snapshot=sanitize_research(snapshot);literature=config.get('literature_pin') or {'collections':[],'documents':[],'status':'not_persisted_in_source_order'}
        plan=resolve_plan(context,hashes,taxa=fasta_taxonomy(inputs['FASTA']).values())
    with stage('quantify_evidence',metrics,checkpoint,progress):
        quant,quant_reuse=quant_cached(inputs,design,context,root,plan['fingerprints']['quant'])
        other='legacy_median.v1' if context['normalization_policy']=='already_normalized.v1' else 'already_normalized.v1'
        alt_context={**context,'normalization_policy':other}
        alt_plan=resolve_plan(alt_context,hashes)
        alternative,alt_reuse=quant_cached(inputs,design,alt_context,root,alt_plan['fingerprints']['quant'])
    with stage('resolve_annotation',metrics,checkpoint,progress):
        mapped,_,fasta=mapped_sites(quant[0],design,inputs['FASTA'],context,[])
        fixtures=json.loads(Path(config['source_fixtures_path']).read_text()) if config.get('source_fixtures_path') else config.get('source_fixtures')
        prior_pins=[]
        if context.get('refresh_references'):
            for path in sorted((root/'enrichment_free_runs').glob('*/references/source_pin.json')):
                prior_pins.append(json.loads(path.read_text()))
        sources=resolve_sources(config['reference_root'],mapped.to_dict('records'),fasta,design['study']['ptm_type'],
            pin_sha=config.get('source_pin_sha256'),refresh=context.get('refresh_references',False),fixtures=fixtures,checkpoint=checkpoint,prior_pins=prior_pins)
        plan=resolve_plan(context,hashes,sources['pin_sha256'],fasta_taxonomy(inputs['FASTA']).values())
    def execute(name,fn):
        with stage(name,metrics,checkpoint,progress):return fn()
    scientific,norm,altnorm,readiness,motif,counts=compute_science(inputs,design,context,sources,quant=quant,alternative=alternative,checkpoint=checkpoint,execute=execute)
    with stage('assemble_evidence_package',metrics,checkpoint,progress):
        fields,transfer,brief=transfer_contract(snapshot,design,context,literature)
        scientific['study/input_field_manifest']=pd.DataFrame(fields)
        validation=validate_science(scientific,design);dictionary=write_tables(scientific,directory)
        provenance={'schema_version':VERSION,'order_id':order_id,'order_code':config['order_code'],'run_id':run_id,'analysis_profile':PROFILE,
            'input_hashes':hashes,'design_hash':object_hash(design),'input_context_hash':object_hash(snapshot),'literature_pin_hash':object_hash(literature),
            'source_pin_sha256':sources['pin_sha256'],'stage_fingerprints':plan['fingerprints'],'normalization':norm,
            'stage_reuse':{'quant':quant_reuse,'normalization_sensitivity':alt_reuse},'context_revision_id':object_hash(snapshot),
            'estimator_versions':{'quantification':plan['estimator'],'kinase':KINASE_VERSION,'temporal':'observed_grid_temporal.v1','strict_parent_default':'unit_balanced_same_injection_peptide_ratios.v3','export':VERSION},
            'code_sha256':{name:digest(Path(__file__).parent/name) for name in CODE_FILES}}
        provenance['provenance_id']=object_hash(provenance)
        json_write(directory/'provenance.json',provenance)
        for name,value in [('study/user_input_snapshot',snapshot),('study/study_context',context),('study/study_design',design),
            ('study/analysis_plan',plan),('study/input_transfer_validation',transfer),('references/literature_pin',literature),
            ('references/source_pin',sources),('evidence/readiness',readiness),('methods/normalization',{'primary':norm,'sensitivity':altnorm}),
            ('methods/motif',motif),('reproducibility/data_dictionary',dictionary),('reproducibility/package_validation',{'checks':validation,'unexpected_input_omissions':transfer['unexpected_missing']})]:json_write(directory/(name+'.json'),value)
        json_write(directory/'references/bibliographic_records.json',sources.get('bibliography',[]))
        json_write(directory/'references/context_relations.json',sources.get('context',[]))
        json_write(directory/'references/literature_comparison_packet.json',{'source':'recorded_input_not_measured_results','study':design['study'],'experimental_context':context,'selected_literature':literature,'comparison_status':'not_performed_by_platform'})
        (directory/'study/STUDY_BRIEF.md').write_text(brief,encoding='utf-8')
        for doc in literature.get('documents',[]):
            if doc.get('content_status')=='full_text_included':
                relative=Path(doc['package_file'])
                if relative.is_absolute() or '..' in relative.parts or relative.parts[:2] not in {('references','documents'),('study','supporting_inputs')}:raise ValueError('Unsafe literature package path')
                if not re.fullmatch('[a-f0-9]{64}',str(doc.get('sha256',''))):raise ValueError('Invalid literature object digest')
                original=Path(config['reference_root'])/'literature_objects'/doc['sha256'];target=directory/relative
                if digest(original)!=doc['sha256']:raise ValueError('Pinned literature content missing or changed')
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
        report=start_here(snapshot,counts,readiness);(directory/'START_HERE_ASTRA.md').write_text(report,encoding='utf-8')
        (directory/'evidence_report.html').write_text('<!doctype html><meta charset="utf-8"><title>Astra evidence</title><pre style="white-space:pre-wrap">'+html.escape(report+'\n'+brief)+'</pre>',encoding='utf-8')
        stats=[{'input_ids':'see row-grained tables and data_dictionary','n':{'injections':len(design['injections']),'materials':len(design['materials']),'biological_unit_ids':sorted({m.get('biological_unit_id') for m in design['materials'] if m.get('biological_unit_id')})},'statistic_id':name,'method_version':version,'unit':unit,'status':status,'null_or_universe':universe,'multiple_testing_family':None} for name,version,unit,status,universe in [
            ('biological_pq','not_implemented','independent_biological_unit','unavailable','not_defined'),
            ('technical_omission','astra_evidence.v1','injection_within_declared_material','computed','not_a_hypothesis_test'),
            ('motif_weight',motif['library_version'],'candidate_per_observed_sequence','relative_support_not_probability','observed_deduplicated_gene_balanced_sequences'),
            ('gene_set_enrichment','kea3_typed_response.v3','gene_set','provider_nullable_statistics','external_library_background_uncontrolled'),
            ('temporal_LOTO','observed_grid_temporal.v1','observed_timepoint','descriptive_sensitivity','not_biological_replicates')]]
        json_write(directory/'methods/statistics_inventory.json',stats)
        (directory/'methods/METHODS.md').write_text('Material → biological-unit equal-weight mean-log contrasts. A=U_joint−P_joint at form level. Generic requires ≥1 joint observation per side; strict alternative parent requires ≥2 joint injections and ≥2 sequences. Repeated subset is separate. No biological p/q. Gene-balanced medians require ≥5 sites/3 genes only for operational coverage; all lower-support candidates remain. Motif patterns are repository heuristics, exactly center-anchored, with relative gene-balanced background support, not posterior probabilities. Adjacent trapezoids never bridge an NA interval and do assume a straight segment between observed endpoints. Onset/recovery are brackets, peaks are sampled maxima. Full proteins and same-experiment links are descriptive, not causal or independent validation. Additional scaling occurs once over the whole recorded study; separate PR/PG factors and A offsets are exported. LOD bounds are unavailable without a validated model.\n',encoding='utf-8')
        claims=[]
        for r in scientific['evidence/parent_adjustment_impact'].to_dict('records'):
            claims.append({'claim_id':stable_id('claim',[r['form_id'],r['contrast_id']]),'claim_type':'observed_parent_adjustment_effect',
                'supporting_rows':[r['impact_id']],'opposing_or_sensitivity_rows':[r['impact_id']],
                'table':'evidence/parent_adjustment_impact.csv','statement':r['classification'],'limits':['relative_ratio_not_occupancy','technical_not_biological_replication','not_kinase_causality']})
        (directory/'evidence/evidence_claims.jsonl').write_bytes(b'\n'.join(json_bytes(c).replace(b'\n',b' ') for c in claims)+b'\n')
        figure_packet(scientific,directory)
        code=directory/'reproducibility/code/ptm_shared';code.mkdir(parents=True)
        for name in CODE_FILES:shutil.copyfile(Path(__file__).parent/name,code/name)
        (code/'__init__.py').write_text('')
        versions={'python':platform.python_version(),**{p:importlib.metadata.version(p) for p in ['numpy','pandas','matplotlib']}}
        json_write(directory/'methods/software_versions.json',versions)
        (directory/'reproducibility/requirements.txt').write_text('\n'.join(p+'=='+versions[p] for p in ['numpy','pandas','matplotlib'])+'\n')
        json_write(directory/'reproducibility/replay_config.json',{'context':context,'design':design,'inputs':{k:str(p.relative_to(directory)) for k,p in inputs.items()},'snapshot':snapshot,'literature':literature})
        (directory/'replay.py').write_text("from pathlib import Path\nimport sys,argparse\nROOT=Path(__file__).resolve().parent\nsys.path.insert(0,str(ROOT/'reproducibility/code'))\nfrom ptm_shared.astra_package import replay_package,validate_package\np=argparse.ArgumentParser()\np.add_argument('--output',type=Path)\np.add_argument('--validate-only',action='store_true')\na=p.parse_args()\nvalidate_package(ROOT) if a.validate_only else replay_package(ROOT,a.output)\n")
        json_write(directory/'reproducibility/v3_migration.json',{'legacy_v3_tables':{name+'.csv':'quant/'+name+'.csv' for name in TABLE_KEYS},'v3_tables_preserve_meanings':True,'new_typed_kinase_tables_are_additional_not_curated_replacements':True})
    with stage('validate_and_publish',metrics,checkpoint,progress):
        publication_started=time.monotonic()
        json_write(directory/'reproducibility/stage_metrics.json',metrics+[{'stage':'validate_and_publish','status':'archive_publication_metrics_recorded_in_platform_run','note':'Archive duration/size cannot be hashed inside that same archive without changing them'}])
        files={str(p.relative_to(directory)):{'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(directory.rglob('*')) if p.is_file()}
        json_write(directory/'manifest.json',{'schema_version':VERSION,'run_id':run_id,'files':files})
        validate_package(directory)
        archive=root/(f'astra_analysis_package_{run_id}.zip');pending=archive.with_name('.'+archive.name)
        with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED) as z:
            for name in [*files,'manifest.json']:z.write(directory/name,name)
        with zipfile.ZipFile(pending) as z:
            if z.testzip():raise ValueError('Archive CRC failure')
            for name,item in files.items():
                if hashlib.sha256(z.read(name)).hexdigest()!=item['sha256']:raise ValueError('Archive manifest failure')
        checkpoint();pending.replace(archive)
        artifacts={name:{'path':str(path.relative_to(root)),'sha256':digest(path)} for name,path in {
            'astra':archive,'report':directory/'evidence_report.html','report_markdown':directory/'START_HERE_ASTRA.md',
            'start_here':directory/'START_HERE_ASTRA.md','study_brief':directory/'study/STUDY_BRIEF.md',
            'primary_input':directory/'quant/primary_A_input.csv','provenance':directory/'provenance.json'}.items()}
        preview=scientific['kinase/kinase_temporal_profiles'].loc[lambda f:f.track.isin(['curated_A','motif_A'])].copy()
        conditions={c['condition_id']:c for c in design['conditions']}
        preview['target_label']=preview.condition_id.map(lambda cid:conditions[cid]['label'])
        preview['reference_label']=preview.reference_condition_id.map(lambda cid:conditions[cid]['label'])
        preview=preview.rename(columns={'candidate_gene':'entity','activity_magnitude':'gene_balanced_mean','n_sites':'n_sites_or_units','n_genes':'n_substrate_genes','activity_status':'descriptive_pattern'})
        result={'schema_version':VERSION,'run_id':run_id,'provenance':provenance,'artifacts':artifacts,'counts':counts,'analysis_readiness':readiness,
            'primary_profiles':json.loads(preview.to_json(orient='records')),'source_pin_sha256':sources['pin_sha256'],'literature_pin':literature,
            'publication_metrics':{'elapsed_seconds':time.monotonic()-publication_started,'archive_bytes':archive.stat().st_size,'manifest_files':len(files),'source_requests':len(sources['queries']),'cache_hits':sum(bool(q.get('cache_hit')) for q in sources['queries'])},
            'study_preview':{'snapshot':snapshot,'brief':brief,'transfer_validation':transfer},'analysis_plan':plan}
        json_write(directory/'platform_run.json',result)
        pointer=root/('.astra_current_'+run_id+'.json');json_write(pointer,result);checkpoint();pointer.replace(root/'enrichment_free_current.json')
    return result


def validate_package(directory):
    directory=Path(directory).resolve();manifest=json.loads((directory/'manifest.json').read_text())
    for name,entry in manifest['files'].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or digest(path)!=entry['sha256'] or path.stat().st_size!=entry['bytes']:
            raise ValueError('Package hash/missing-file failure: '+name)
    dictionary=json.loads((directory/'reproducibility/data_dictionary.json').read_text());tables={}
    for name,entry in dictionary.items():
        df=pd.read_csv(directory/name,low_memory=False)
        if list(df)!=entry['columns'] or len(df)!=entry['rows']:raise ValueError('Package CSV schema failure: '+name)
        tables[name[:-4]]=df
    checks=validate_science(tables,json.loads((directory/'study/study_design.json').read_text()))
    print(json.dumps({'manifest_files':len(manifest['files']),'scientific_tables':len(tables),'validated':True}))
    return checks


def replay_package(directory,output):
    directory=Path(directory).resolve()
    if output is None:raise ValueError('--output or --validate-only is required')
    output=Path(output).resolve()
    if output==directory or directory in output.parents:raise ValueError('Replay cannot overwrite the source package')
    validate_package(directory);config=json.loads((directory/'reproducibility/replay_config.json').read_text())
    inputs={k:directory/v for k,v in config['inputs'].items()};sources=json.loads((directory/'references/source_pin.json').read_text())
    tables,*_=compute_science(inputs,config['design'],config['context'],sources)
    fields,_,_=transfer_contract(config['snapshot'],config['design'],config['context'],config['literature'])
    tables['study/input_field_manifest']=pd.DataFrame(fields)
    validate_science(tables,config['design']);output.mkdir(parents=True,exist_ok=False);write_tables(tables,output)
    results=[]
    for name in tables:
        a,b=[pd.read_csv(p/(name+'.csv'),low_memory=False) for p in [directory,output]]
        pd.testing.assert_frame_equal(a,b,check_dtype=False,check_exact=False,atol=1e-10,rtol=1e-10)
        if not a.isna().equals(b.isna()):raise ValueError('Replay NA mask differs: '+name)
        results.append({'table':name,'rows':len(a),'values_text_keys_masks_equal':True,'byte_equal':digest(directory/(name+'.csv'))==digest(output/(name+'.csv'))})
    json_write(output/'replay_result.json',{'passed':True,'atol':1e-10,'rtol':1e-10,'tables':results,'network_requests':0})
    print(json.dumps({'replayed_tables':len(results),'byte_identical':sum(r['byte_equal'] for r in results)}))
