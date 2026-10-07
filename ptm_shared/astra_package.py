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


def quant_cached(inputs,design,context,root,fingerprint,calculator=None):
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
    result=(calculator or calculate)(inputs,design,{**context,'annotation_mode':'quantification_only'},None)
    tables,norm,readiness=result;pending=cache.with_name('.'+fingerprint+'-'+uuid4().hex);pending.mkdir(parents=True)
    files={}
    for name,df in tables.items():
        path=pending/(name+'.csv');df.to_csv(path,index=False);files[name]={'sha256':digest(path),'rows':len(df)}
    origin=Path(inputs.get('PR',inputs['PG'])).parents[1].name
    json_write(pending/'stage.json',{'fingerprint':fingerprint,'origin_run_id':origin,
                                    'tables':files,'normalization':norm,'readiness':readiness})
    if not cache.exists():pending.rename(cache)
    # Concurrent writers keep the first complete immutable stage; no deletion of another run.
    return result,{'status':'computed','fingerprint':fingerprint,'origin_analysis_run_id':origin}


class StageLedger(list):
    """Durable per-run transitions. A failed run never edits the completed pointer."""
    def __init__(self,path,profile,code_hash):
        super().__init__();self.path=path;self.profile=profile;self.code_hash=code_hash;self.plan={}

    def persist(self):
        from .astra_plan import STAGES
        dependencies={**STAGES,'identity_localization':['quantify_evidence'],
            'discover_regulators':['identity_localization','resolve_annotation']}
        seen={r['stage']:r for r in self}
        rows=[{**{'stage':name,'status':'queued'},**seen.get(name,{}),'dependencies':deps,
            'code_hash':self.code_hash,'config_hash':object_hash(self.plan),'checkpoint':self.plan.get('fingerprints',{})} for name,deps in dependencies.items()]
        temporary=self.path.with_suffix('.tmp');json_write(temporary,{'profile':self.profile,'stages':rows});temporary.replace(self.path)


@contextmanager
def stage(name,metrics,checkpoint,progress):
    from datetime import datetime,timezone
    checkpoint();progress(name);start=time.monotonic()
    row={'stage':name,'status':'running','started_utc':datetime.now(timezone.utc).isoformat()};metrics.append(row)
    if hasattr(metrics,'persist'):metrics.persist()
    try:yield
    except Exception:
        row.update(status='failed',elapsed_seconds=time.monotonic()-start)
        if hasattr(metrics,'persist'):metrics.persist()
        raise
    row.update(status='completed',elapsed_seconds=time.monotonic()-start,finished_utc=datetime.now(timezone.utc).isoformat(),
        process_peak_memory_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if platform.system()=='Darwin' else 1024))
    if hasattr(metrics,'persist'):metrics.persist()
    checkpoint()


def compute_science(inputs,design,context,sources,*,quant=None,alternative=None,checkpoint=lambda:None,execute=lambda name,fn:fn(),engine=None):
    context=effective_context(context)
    calculate_stage=engine.calculate if engine else calculate
    discover_stage=engine.discover if engine else discover
    temporal_stage=engine.integrate_temporal if engine else integrate_temporal
    science_inputs=inputs
    if engine:
        fasta,reference=engine.normalized_reference(inputs,context)
        science_inputs={**inputs,'FASTA':fasta}
        context={**context,'_runtime_reference':reference,'_runtime_inputs':inputs}
    if quant is None:quant=calculate_stage(inputs,design,{**context,'annotation_mode':'quantification_only'},None)
    tables,norm,readiness=quant
    if alternative is None:
        other='legacy_median.v1' if context['normalization_policy']=='already_normalized.v1' else 'already_normalized.v1'
        alternative=calculate_stage(inputs,design,{**context,'normalization_policy':other,'annotation_mode':'quantification_only'},None)
    alt_tables,alt_norm,_=alternative;checkpoint()
    if engine and hasattr(engine,'prepare_evidence'):
        context['_source_pin_sha256']=sources.get('pin_sha256')
        canonical=execute('identity_localization',lambda:engine.prepare_evidence(tables,inputs,design,context)['_canonical_evidence'])
        context={**context,'_canonical_evidence':canonical}
    mapped,edges,motif=execute('discover_regulators',lambda:discover_stage(tables,design,science_inputs['FASTA'],context,sources))
    tables['site_mapping']=mapped
    discovery=execute('score_regulator_footprints',lambda:engine.score_candidates(tables,edges,design,context) if engine and hasattr(engine,'score_candidates') else score_candidates(tables,edges,design,science=bool(engine)));checkpoint()
    evidence=quantitative_evidence(tables,alt_tables,design,norm,alt_norm,{**discovery,'source_queries':sources['queries']})
    temporal=execute('integrate_temporal_layers',lambda:temporal_stage(tables,discovery,design,context,sources.get('context'),evidence['parent_adjustment_impact']));checkpoint()
    evidence['censoring_bounds']=censoring_bounds(tables,design,context.get('detection_limit_model'))
    discovery.update(candidate_context_and_omissions(tables,discovery,evidence['technical_injection_omissions'],context.get('_runtime_reference')))
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
    if engine:scientific=engine.augment(scientific,inputs,design,context,readiness)
    return scientific,norm,alt_norm,readiness,motif,counts


def validate_science(tables,design):
    if 'science/inference_results' in tables:
        from . import astra_evidence_v6 as science_engine
    elif any(name.startswith('science/') for name in tables):
        from . import astra_science as science_engine
    else:
        science_engine=None
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
        if name.startswith('science/'):
            keys=science_engine.KEYS.get(short)
        elif science_engine and hasattr(science_engine,'ADDITIONAL_KEYS'):
            keys=keys or science_engine.ADDITIONAL_KEYS.get(name)
        if keys and (any(k not in df for k in keys) or df.duplicated(keys).any()):raise ValueError('Duplicate/missing row key: '+name)
        if not len(df.columns):raise ValueError('Missing header: '+name)
        for column,universe in [('form_id',forms),('contrast_id',contrasts),('candidate_id',candidates),('condition_id',conditions),('reference_condition_id',conditions),('series_id',series),('source_evidence_id',feature_ids),('target_evidence_id',feature_ids)]:
            if not name.startswith('science/') and column in df and not set(df[column].dropna())<=universe:raise ValueError('Foreign key mismatch: '+name+'/'+column)
        for column,universe in [('form_ids',forms),('edge_ids',edges),('candidate_edge_ids',edges),('candidate_ids',candidates)]:
            if column in df:
                values=set(';'.join(df[column].dropna().astype(str)).split(';'))-{''}
                if not values<=universe:raise ValueError('Foreign key mismatch: '+name+'/'+column)
        checks.append({'check_id':name,'schema_keys_FK':'passed','rows':len(df),'unique_key':keys})
    if design.get('schema_version')=='study_design.v4':
        missing_science={'science/'+key for key in science_engine.KEYS}-set(tables)
        missing_science|=set(getattr(science_engine,'ADDITIONAL_KEYS',{}))-set(tables)
        if missing_science:raise ValueError('Required science table missing: '+','.join(sorted(missing_science)))
    if any(name.startswith('science/') for name in tables):
        science_engine.validate_tables(tables,design)
    comparison=tables['quant/comparisons'];finite_rows=comparison.loc[comparison.included]
    if len(finite_rows) and not np.allclose(finite_rows.A.to_numpy(float),(finite_rows.U_joint-finite_rows.P_joint).to_numpy(float),atol=1e-10,rtol=1e-10):raise ValueError('Same-mask form identity failed')
    offset=tables['evidence/normalization_offsets'].dropna(subset=['expected_A_offset','observed_A_offset'])
    if len(offset) and not np.allclose(offset.expected_A_offset.to_numpy(float),offset.observed_A_offset.to_numpy(float),atol=1e-10,rtol=1e-10):raise ValueError('Normalization factor offset mismatch')
    checks.append({'check_id':'same_mask_identity_and_scaling_offsets','status':'passed'})
    return checks


def write_tables(tables,directory):
    if 'science/inference_results' in tables:
        from . import astra_evidence_v6 as science_engine
    elif any(name.startswith('science/') for name in tables):
        from . import astra_science as science_engine
    else:
        science_engine=None
    dictionary={}
    for name,frame in tables.items():
        path=directory/(name+'.csv');path.parent.mkdir(parents=True,exist_ok=True);frame.to_csv(path,index=False)
        read=pd.read_csv(path,low_memory=False)
        if list(read)!=list(frame) or len(read)!=len(frame):raise ValueError('CSV write truncated: '+name)
        short=name.split('/')[-1];keys=TABLE_KEYS.get(short) if name.startswith('quant/') else EXTRA_KEYS.get(short)
        if name.startswith('science/'):
            keys=science_engine.KEYS.get(short)
        elif science_engine and hasattr(science_engine,'ADDITIONAL_KEYS'):
            keys=keys or science_engine.ADDITIONAL_KEYS.get(name)
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
        'Replay: install reproducibility/requirements.txt in an isolated environment, then python replay.py --output <new-directory>. Supplied measurement inputs and permitted pinned source records are included. Check reproducibility/replay_config.json for required external restricted resources before claiming self-contained replay; replay makes no network calls.'])+'\n'


def run_astra_analysis(order_id,config,output_dir,checkpoint=lambda:None,progress=lambda message:None,*,engine=None):
    package_version=engine.VERSION if engine else VERSION
    profile=engine.PROFILE if engine else PROFILE
    code_files=sorted(set(CODE_FILES+(engine.CODE_FILES if engine else [])))
    code_capture={name:digest(Path(__file__).parent/name) for name in code_files}
    plan_resolver=engine.resolve_plan if engine else resolve_plan
    context=sanitize_research(effective_context(config['experimental_context']));design=context['study_design']
    (engine.validate_execution if engine else validate_execution)(context,design['study']['ptm_type'],config['species_tax_id'])
    root=Path(output_dir);run_id=f"g{int(config.get('run_generation') or 0)}-{uuid4().hex}"
    directory=root/'enrichment_free_runs'/run_id;directory.mkdir(parents=True,exist_ok=False)
    for folder in ['study','inputs','references','methods','evidence','reproducibility']: (directory/folder).mkdir()
    metrics=StageLedger(directory/'stage_checkpoint.json',profile,object_hash(code_capture));inputs={};hashes={}
    with stage('resolve_inputs_and_plan',metrics,checkpoint,progress):
        for key,field,name in [('PR','pr_matrix_path','PR.tsv'),('PG','pg_matrix_path','PG.tsv'),('FASTA','fasta_path','reference.fasta')]:
            if engine and not config.get(field):continue
            original=Path(config[field]);sha=digest(original);target=directory/'inputs'/name;shutil.copyfile(original,target)
            if digest(target)!=sha or digest(original)!=sha:raise ValueError('Input changed during immutable capture')
            inputs[key]=target;hashes[key]=sha
        if engine:
            for key,field in engine.INPUT_FIELDS.items():
                if not config.get(field):continue
                original=Path(config[field]);target=directory/'inputs'/(key+original.suffix)
                if key=='SPECIFICITY':
                    target=directory/'inputs/specificity'/(key+original.suffix)
                    target.parent.mkdir(parents=True,exist_ok=True)
                sha=digest(original);shutil.copyfile(original,target)
                if digest(target)!=sha or digest(original)!=sha:raise ValueError('Scientific input changed during capture')
                inputs[key]=target;hashes[key]=sha
                if key=='SPECIFICITY':
                    resource=json.loads(target.read_text())
                    if resource.get('redistribution_status')!='permitted':
                        # Preserve the resource request/hash, but neither export nor
                        # execute a resource whose package permission is unresolved.
                        # Quantification and all other supported stages continue.
                        inputs['SPECIFICITY_RESTRICTED']=inputs.pop('SPECIFICITY')
                        hashes['SPECIFICITY_RESTRICTED']=hashes.pop('SPECIFICITY')
                        if engine.PROFILE=='astra_analysis.v6' and resource.get('local_use_permission')=='permitted' and resource.get('derived_export_permission')=='permitted':
                            inputs['_LOCAL_SPECIFICITY']=original
                            hashes['SPECIFICITY']=sha
                        continue
                    for part in ('matrix','background'):
                        relative=Path(resource[part+'_file'])
                        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe specificity resource path')
                        dest=target.parent/relative;dest.parent.mkdir(parents=True,exist_ok=True)
                        if dest.resolve()==target.resolve():raise ValueError('Specificity resource would overwrite its manifest')
                        shutil.copyfile(original.parent/relative,dest)
                        if digest(dest)!=resource[part+'_sha256']:raise ValueError('Specificity input checksum mismatch')
            engine.normalized_reference(inputs,context)
        snapshot=config.get('user_input_snapshot') or capture_order({'id':order_id,'order_code':config['order_code'],'analysis_context':context})
        snapshot=sanitize_research(snapshot);literature=config.get('literature_pin') or {'collections':[],'documents':[],'status':'not_persisted_in_source_order'}
        plan=plan_resolver(context,hashes,taxa=fasta_taxonomy(inputs['FASTA']).values())
        metrics.plan=plan
    with stage('quantify_evidence',metrics,checkpoint,progress):
        quant,quant_reuse=quant_cached(inputs,design,context,root,plan['fingerprints']['quant'],calculator=engine.calculate if engine else None) if not engine or engine.PROFILE=='astra_analysis.v6' else (engine.calculate(inputs,design,context),{'status':'computed','fingerprint':plan['fingerprints']['quant']})
        other='legacy_median.v1' if context['normalization_policy']=='already_normalized.v1' else 'already_normalized.v1'
        alt_context={**context,'normalization_policy':other}
        alt_plan=plan_resolver(alt_context,hashes)
        alternative,alt_reuse=quant_cached(inputs,design,alt_context,root,alt_plan['fingerprints']['quant'],calculator=engine.calculate if engine else None) if not engine or engine.PROFILE=='astra_analysis.v6' else (engine.calculate(inputs,design,alt_context),{'status':'computed','fingerprint':alt_plan['fingerprints']['quant']})
    with stage('resolve_annotation',metrics,checkpoint,progress):
        mapped,_,fasta=mapped_sites(quant[0],design,engine.normalized_reference(inputs,context)[0] if engine else inputs['FASTA'],context,[])
        fixtures=json.loads(Path(config['source_fixtures_path']).read_text()) if config.get('source_fixtures_path') else config.get('source_fixtures')
        prior_pins=[]
        if context.get('refresh_references'):
            for path in sorted((root/'enrichment_free_runs').glob('*/references/source_pin.json')):
                prior_pins.append(json.loads(path.read_text()))
        query_mapping=engine.source_universe(quant[0],mapped,inputs,context) if engine and hasattr(engine,'source_universe') else mapped.to_dict('records')
        sources=resolve_sources(config['reference_root'],query_mapping,fasta,design['study']['ptm_type'],
            pin_sha=config.get('source_pin_sha256'),refresh=context.get('refresh_references',False),fixtures=fixtures,checkpoint=checkpoint,prior_pins=prior_pins,
            **({'query_policy':'taxon_round_robin.v1'} if engine else {}),
            **({'acquisition_policy':context.get('acquisition_policy',{'mode':'research_full'})} if engine and engine.PROFILE=='astra_analysis.v6' else {}))
        plan=plan_resolver(context,hashes,sources['pin_sha256'],fasta_taxonomy(inputs['FASTA']).values())
        metrics.plan=plan
    evidence_reuse={}
    def execute(name,fn):
        with stage(name,metrics,checkpoint,progress):
            if engine and engine.PROFILE=='astra_analysis.v6':
                from .evidence_stage_cache import cached_stage
                # Canonical preparation also scores the pinned specificity
                # resource, so it depends on the discovery fingerprint.
                stage_keys={'identity_localization':'discovery','discover_regulators':'discovery',
                    'score_regulator_footprints':'discovery','integrate_temporal_layers':'temporal'}
                if name in stage_keys:
                    fingerprint=object_hash([plan['fingerprints'][stage_keys[name]],code_capture['astra_evidence_v6.py']])
                    result,reuse=cached_stage(root/'evidence_cache',name,fingerprint,fn)
                    evidence_reuse[name]=reuse
                    return result
            return fn()
    scientific,norm,altnorm,readiness,motif,counts=compute_science(inputs,design,context,sources,quant=quant,alternative=alternative,checkpoint=checkpoint,execute=execute,engine=engine)
    with stage('assemble_evidence_package',metrics,checkpoint,progress):
        if engine and code_capture!={name:digest(Path(__file__).parent/name) for name in code_files}:
            raise ValueError('Scientific source changed during execution; retry on a frozen release')
        fields,transfer,brief=transfer_contract(snapshot,design,context,literature)
        scientific['study/input_field_manifest']=pd.DataFrame(fields)
        validation=validate_science(scientific,design);dictionary=write_tables(scientific,directory)
        provenance={'schema_version':package_version,'order_id':order_id,'order_code':config['order_code'],'run_id':run_id,'analysis_profile':profile,
            'input_hashes':hashes,'design_hash':object_hash(design),'input_context_hash':object_hash(snapshot),'literature_pin_hash':object_hash(literature),
            'source_pin_sha256':sources['pin_sha256'],'stage_fingerprints':plan['fingerprints'],'normalization':norm,
            'stage_reuse':{'quant':quant_reuse,'normalization_sensitivity':alt_reuse,**evidence_reuse},'context_revision_id':object_hash(snapshot),
            'estimator_versions':{'quantification':plan['estimator'],'kinase':KINASE_VERSION,'temporal':'observed_grid_temporal.v1','strict_parent_default':'unit_balanced_same_injection_peptide_ratios.v3','export':package_version},
            'code_sha256':{name:digest(Path(__file__).parent/name) for name in code_files}}
        provenance['provenance_id']=object_hash(provenance)
        if engine:
            provenance['estimator_versions'].update(kinase='gene_balanced_exact_site.v5.experimental',
                measurement='diann_observations.v1',reference='reference_inventory.v1',
                selective_call='selective_evidence.v1.experimental',specificity='experimental_specificity_adapter.v1',
                observation_policy=context.get('science',{}).get('observation_policy',{'mode':'audit_only'}))
            if engine.PROFILE=='astra_analysis.v6':
                provenance['estimator_versions'].update(kinase='gene_balanced_contrast_evidence.v6.experimental',
                    measurement='localization_evidence.v2',selective_call='evidence_resolution.v2',
                    specificity='see_methods_method_registry_and_resource_manifest')
            provenance['provenance_id']=object_hash({k:v for k,v in provenance.items() if k!='provenance_id'})
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
        if engine and hasattr(engine,'write_artifacts'):engine.write_artifacts(directory,scientific,context,inputs,sources,readiness)
        report=start_here(snapshot,counts,readiness);
        if engine and hasattr(engine,'report_addendum'):report+=engine.report_addendum(scientific,readiness)
        if engine and engine.PROFILE!='astra_analysis.v6':report+='\n## Experimental scientific evidence\nRead science/measurement_observations.csv and site_identity_audit.csv for exact observation and sequence provenance. Read science/kinase_calls.csv for each uncalibrated abstention; proposals are not validated calls. Specificity parity and independent benchmark improvement are not established. See evidence/readiness.json for resource/assay status. The taxon is inherited from the recorded Order, never inferred from a pathway.\n'
        (directory/'START_HERE_ASTRA.md').write_text(report,encoding='utf-8')
        (directory/'evidence_report.html').write_text('<!doctype html><meta charset="utf-8"><title>Astra evidence</title><pre style="white-space:pre-wrap">'+html.escape(report+'\n'+brief)+'</pre>',encoding='utf-8')
        stats=[{'input_ids':'see row-grained tables and data_dictionary','n':{'injections':len(design['injections']),'materials':len(design['materials']),'biological_unit_ids':sorted({m.get('biological_unit_id') for m in design['materials'] if m.get('biological_unit_id')})},'statistic_id':name,'method_version':version,'unit':unit,'status':status,'null_or_universe':universe,'multiple_testing_family':None} for name,version,unit,status,universe in [
            ('biological_pq','not_implemented','independent_biological_unit','unavailable','not_defined'),
            ('technical_omission','astra_evidence.v1','injection_within_declared_material','computed','not_a_hypothesis_test'),
            ('motif_weight',motif['library_version'],'candidate_per_observed_sequence','relative_support_not_probability','observed_deduplicated_gene_balanced_sequences'),
            ('gene_set_enrichment','kea3_typed_response.v3','gene_set','provider_nullable_statistics','external_library_background_uncontrolled'),
            ('temporal_LOTO','observed_grid_temporal.v1','observed_timepoint','descriptive_sensitivity','not_biological_replicates')]]
        if engine:
            for name,table,unit in [('biological_interval','replicate_uncertainty','declared_biological_unit_or_pair'),('perturbation_interaction','perturbation_validation','declared_validation_unit_or_pair'),('experimental_specificity','specificity_scores','site_sequence_per_assay_matrix'),('selective_call','kinase_calls','candidate_contrast')]:
                frame=scientific['science/'+table]
                stats.append({'statistic_id':name,'input_ids':'science/'+table+'.csv','method_version':package_version,
                    'unit':unit,'n':len(frame),'status':'see_row_status_and_readiness','null_or_universe':'not_a_biological_p_value',
                    'multiple_testing_family':None,'calibration':'unvalidated_experimental','missing_value':'unavailable_never_zero_or_one'})
            if design['study'].get('design_axis')=='cross_sectional':
                next(s for s in stats if s['statistic_id']=='temporal_LOTO')['status']='not_applicable_cross_sectional'
        json_write(directory/'methods/statistics_inventory.json',stats)
        (directory/'methods/METHODS.md').write_text('Material → biological-unit equal-weight mean-log contrasts. A=U_joint−P_joint at form level. Generic requires ≥1 joint observation per side; strict alternative parent requires ≥2 joint injections and ≥2 sequences. Repeated subset is separate. No biological p/q. Gene-balanced medians require ≥5 sites/3 genes only for operational coverage; all lower-support candidates remain. Motif patterns are repository heuristics, exactly center-anchored, with relative gene-balanced background support, not posterior probabilities. Adjacent trapezoids never bridge an NA interval and do assume a straight segment between observed endpoints. Onset/recovery are brackets, peaks are sampled maxima. Full proteins and same-experiment links are descriptive, not causal or independent validation. Additional scaling occurs once over the whole recorded study; separate PR/PG factors and A offsets are exported. LOD bounds are unavailable without a validated model.\n',encoding='utf-8')
        if engine and engine.PROFILE!='astra_analysis.v6':
            with (directory/'methods/METHODS.md').open('a',encoding='utf-8') as method:
                method.write('\nExperimental v5: exact run/precursor observation audit; minimum occupied-site confidence is not an individual site posterior. Optional validated-observation filtering requires explicitly recorded thresholds and renormalization scope. Site keys use accession, taxon, sequence hash and residue/position. Enzyme and substrate taxa are separate; unknown enzyme taxonomy restricts protein/context joins. Specificity uses only the declared local matrix semantics and permitted pinned resources; official atlas parity is not established. Confirmed calls remain no_call (uncalibrated_policy). Optional biological percentile intervals require at least 3 declared independent units/pairs and resample joint PTM/parent ratios together; technical-only data have no biological interval. Perturbation records are cohort-scoped. These methods are not MSstatsPTM, PhosX, KSTAR or independent validation. Cross-sectional inputs have no temporal event/AUC analysis. Protein-only inputs have no PTM adjustment or kinase call.\n')
        claims=[]
        for r in scientific['evidence/parent_adjustment_impact'].to_dict('records'):
            claims.append({'claim_id':stable_id('claim',[r['form_id'],r['contrast_id']]),'claim_type':'observed_parent_adjustment_effect',
                'supporting_rows':[r['impact_id']],'opposing_or_sensitivity_rows':[r['impact_id']],
                'table':'evidence/parent_adjustment_impact.csv','statement':r['classification'],'limits':['relative_ratio_not_occupancy','technical_not_biological_replication','not_kinase_causality']})
        (directory/'evidence/evidence_claims.jsonl').write_bytes(b'\n'.join(json_bytes(c).replace(b'\n',b' ') for c in claims)+b'\n')
        figure_packet(scientific,directory,design) if design['study'].get('design_axis')!='cross_sectional' else None
        code=directory/'reproducibility/code/ptm_shared';code.mkdir(parents=True)
        for name in code_files:shutil.copyfile(Path(__file__).parent/name,code/name)
        (code/'__init__.py').write_text('')
        versions={'python':platform.python_version(),**{p:importlib.metadata.version(p) for p in ['numpy','pandas','matplotlib']}}
        if engine:
            versions['pyarrow']=importlib.metadata.version('pyarrow')
        if readiness.get('specificity',{}).get('status')=='official_pssm_scored':
            for dependency in ('phosx','h5py','tables','tqdm'):
                versions[dependency]=importlib.metadata.version(dependency)
        json_write(directory/'methods/software_versions.json',versions)
        (directory/'reproducibility/requirements.txt').write_text('\n'.join(
            'phosx @ git+https://github.com/alussana/phosx.git@b556f59c39f099b5f3fcb574a8a70856c3fdc82c' if p=='phosx' else p+'=='+v
            for p,v in versions.items() if p!='python')+'\n')
        if engine and engine.PROFILE=='astra_analysis.v6':
            with (directory/'methods/METHODS.md').open('a',encoding='utf-8') as method:
                method.write('\nV6 audit-only preserves matrix quantification. Localization is joined by precursor and injection, then gated on the actual reference and target joint masks. Run minimum confidence, library confidence, q-values and parsed site probability retain separate scopes. Specificity membership consumes a recorded percentile/rank policy; unselected scores remain exported. Method enrichment p/q are separate from biological p/q. Calibrated inference requires a domain/resource-matched policy artifact; descriptive and exploratory signals remain available without one. Actual optional method executions and restrictions are recorded in methods/method_registry.json. Biological improvement and independent experimental validation are not implied.\n')
        json_write(directory/'reproducibility/replay_config.json',{'engine_profile':profile,'context':context,'design':design,'inputs':{k:str(p.relative_to(directory)) for k,p in inputs.items() if not k.startswith('_')},
            'required_external_resources':{'specificity_manifest_sha256':digest(inputs['_LOCAL_SPECIFICITY'])} if '_LOCAL_SPECIFICITY' in inputs else {},'snapshot':snapshot,'literature':literature})
        (directory/'replay.py').write_text("from pathlib import Path\nimport sys,argparse\nROOT=Path(__file__).resolve().parent\nsys.path.insert(0,str(ROOT/'reproducibility/code'))\nfrom ptm_shared.astra_package import replay_package,validate_package\np=argparse.ArgumentParser()\np.add_argument('--output',type=Path)\np.add_argument('--validate-only',action='store_true')\np.add_argument('--specificity-manifest',type=Path)\na=p.parse_args()\nvalidate_package(ROOT) if a.validate_only else replay_package(ROOT,a.output,specificity_manifest=a.specificity_manifest)\n")
        json_write(directory/'reproducibility/v3_migration.json',{'legacy_v3_tables':{name+'.csv':'quant/'+name+'.csv' for name in TABLE_KEYS},'v3_tables_preserve_meanings':True,'new_typed_kinase_tables_are_additional_not_curated_replacements':True})
    with stage('validate_and_publish',metrics,checkpoint,progress):
        publication_started=time.monotonic()
        json_write(directory/'reproducibility/stage_metrics.json',metrics+[{'stage':'validate_and_publish','status':'archive_publication_metrics_recorded_in_platform_run','note':'Archive duration/size cannot be hashed inside that same archive without changing them'}])
        shutil.copyfile(directory/'stage_checkpoint.json',directory/'reproducibility/stage_ledger.json')
        files={str(p.relative_to(directory)):{'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(directory.rglob('*')) if p.is_file() and p.name!='stage_checkpoint.json'}
        json_write(directory/'manifest.json',{'schema_version':package_version,'run_id':run_id,'files':files})
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
        if engine:
            for key,relative in [('kinase_calls','science/kinase_calls.csv'),('measurement_audit','science/measurement_observations.csv'),('protein_input','quant/protein_contrasts.csv')]:
                artifacts[key]={'path':str((directory/relative).relative_to(root)),'sha256':digest(directory/relative)}
        preview=scientific['kinase/kinase_temporal_profiles'].loc[lambda f:f.track.isin(['curated_A','motif_A','specificity_A'] if engine else ['curated_A','motif_A'])].copy()
        conditions={c['condition_id']:c for c in design['conditions']}
        preview['target_label']=preview.condition_id.map(lambda cid:conditions[cid]['label'])
        preview['reference_label']=preview.reference_condition_id.map(lambda cid:conditions[cid]['label'])
        preview=preview.rename(columns={'candidate_gene':'entity','activity_magnitude':'gene_balanced_mean','n_sites':'n_sites_or_units','n_genes':'n_substrate_genes','activity_status':'descriptive_pattern'})
        result={'schema_version':package_version,'run_id':run_id,'provenance':provenance,'artifacts':artifacts,'counts':counts,'analysis_readiness':readiness,
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


def replay_package(directory,output,*,specificity_manifest=None):
    directory=Path(directory).resolve()
    if output is None:raise ValueError('--output or --validate-only is required')
    output=Path(output).resolve()
    if output==directory or directory in output.parents:raise ValueError('Replay cannot overwrite the source package')
    validate_package(directory);config=json.loads((directory/'reproducibility/replay_config.json').read_text())
    inputs={k:directory/v for k,v in config['inputs'].items()};sources=json.loads((directory/'references/source_pin.json').read_text())
    required=config.get('required_external_resources',{})
    if required:
        if not specificity_manifest or digest(Path(specificity_manifest))!=required.get('specificity_manifest_sha256'):
            raise ValueError('Conditional replay requires the identical permitted local specificity manifest and resources')
        inputs['_LOCAL_SPECIFICITY']=Path(specificity_manifest)
    engine=None
    if config.get('engine_profile')=='astra_analysis.v5':
        from . import astra_science as engine
    if config.get('engine_profile')=='astra_analysis.v6':
        from . import astra_evidence_v6 as engine
    tables,*_=compute_science(inputs,config['design'],config['context'],sources,engine=engine)
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
