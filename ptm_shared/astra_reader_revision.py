"""Immutable literature-only package revision using existing validated v6 tables.

No quantification, source refresh, discovery, selection, or figure rendering.
Full scientific replay remains available; reader replay only reconstructs the
new interpretation artifacts from the frozen retrieval/comparison pin.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from uuid import uuid4
import pandas as pd
from .annotation_registry import digest
from .generic_workflow import json_write, object_hash
from . import astra_literature as literature_stage


def _card_without_display_order(card):
    card = deepcopy(card)
    grid = card.get('condition_grid')
    conditions = list(grid.get('conditions') or []) if isinstance(grid, dict) else []
    if isinstance(grid, dict):
        grid.pop('time_order_status', None)
        grid.pop('conditions', None)
    bindings = card.pop('source_bindings', None) or []
    trajectory = card.pop('trajectory', None) or []
    return card, conditions, bindings, trajectory


def _row_multiset(rows):
    return sorted(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows)


def assert_reader_time_projection_only(source_csv, revised_csv):
    """cards.csv may change only by a recorded-time permutation and its unresolved flag."""
    before = pd.read_csv(source_csv, low_memory=False)
    after = pd.read_csv(revised_csv, low_memory=False)
    if list(before.card_id.astype(str)) != list(after.card_id.astype(str)):
        raise ValueError('Reader card identity changed')
    if list(before.form_id.astype(str)) != list(after.form_id.astype(str)):
        raise ValueError('Reader card form changed')
    if list(before.selected.astype(str).str.lower()) != list(after.selected.astype(str).str.lower()):
        raise ValueError('Reader selection changed')
    for raw_before, raw_after in zip(before.card_json, after.card_json):
        left, left_conditions, left_bindings, left_trajectory = _card_without_display_order(json.loads(raw_before))
        right, right_conditions, right_bindings, right_trajectory = _card_without_display_order(json.loads(raw_after))
        if left != right or set(left_conditions) != set(right_conditions):
            raise ValueError('Reader card changed beyond recorded time order')
        if _row_multiset(left_bindings) != _row_multiset(right_bindings) or _row_multiset(left_trajectory) != _row_multiset(right_trajectory):
            raise ValueError('Reader time-row values changed')


def read_tables(root):
    from .astra_evidence_catalog import read_source
    dictionary=json.loads((Path(root)/'reproducibility/data_dictionary.json').read_text())
    return {name[:-4]:read_source(root,name,d) for name,d in dictionary.items()}


def _copy_package(source, root):
    """Copy only manifest-bound bytes into a new immutable revision directory."""
    run_id='g0-'+uuid4().hex
    directory=root/'enrichment_free_runs'/run_id
    directory.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((source/'manifest.json').read_text())
    for name in [*manifest['files'],'manifest.json']:
        target=directory/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,target)
    return run_id,directory


def revise_temporal(source, output_dir, *, refresh_figures=False, access_only=False, whole_only=False, review_plan_only=False, review_execution=None, checkpoint=lambda:None):
    """Reader-only revision of saved temporal rows, without literature collection.

    The source and its successful pointer are never modified. Publication to the
    caller's output root happens only after validation and atomic archive sealing.
    """
    from .astra_package import validate_package, write_tables, seal_archive, CODE_FILES, READER_CODE_FILES
    from . import astra_evidence_v6 as engine
    from .astra_reader import write_reader, validate_reader, attach_reading_guidance
    from .astra_reader_temporal import attach_temporal, VERSION
    from .astra_evidence_catalog import attach_access, VERSION as ACCESS_VERSION, INDEX, LINKS
    if review_execution is not None:
        if refresh_figures or access_only or whole_only:raise ValueError('Review execution revision cannot refresh other stages')
        review_plan_only=True
    if review_plan_only and (refresh_figures or access_only or whole_only):raise ValueError('Review planning revision only; no other refresh')
    if whole_only and (access_only or refresh_figures):raise ValueError('Whole reader revision cannot refresh figures or use access-only mode')
    if access_only and refresh_figures: raise ValueError('Evidence-access revision cannot refresh figures')
    source=Path(source).resolve();root=Path(output_dir).resolve()
    if root==source or source in root.parents:raise ValueError('Revision must not edit source package')
    validate_package(source)
    if review_execution is not None:
        from .astra_literature_review import project_review
        from .astra_evidence_catalog import EvidenceCatalog
        _,scope=project_review(review_execution,EvidenceCatalog(source))
        if not scope['requested_subjects'] or scope['requested_scope_status']!='completed':
            raise ValueError('Incomplete requested literature scope; previous success retained')
    if json.loads((source/'reproducibility/replay_config.json').read_text())['engine_profile']!=engine.PROFILE:
        raise ValueError('Temporal reader revision requires v6')
    tables=read_tables(source)
    if 'temporal/temporal_series' not in tables:raise ValueError('Saved temporal series required; no calculation will be attempted')
    origin=json.loads((source/'provenance.json').read_text())
    run_id,directory=_copy_package(source,root)
    snapshot=json.loads((source/'study/user_input_snapshot.json').read_text())
    if not (access_only or whole_only or review_plan_only) and (source/'references/finding_literature_pin.json').is_file():
        literature_stage.apply(tables,json.loads((source/'references/finding_literature_pin.json').read_text()),
            snapshot,json.loads((source/'references/literature_pin.json').read_text()))
    if not (access_only or whole_only or review_plan_only):
        attach_temporal(tables);attach_reading_guidance(tables)
        from .measured_feature_cards import apply_recorded_time_order
        apply_recorded_time_order(tables)
    if not review_plan_only:attach_access(tables)
    if review_plan_only:
        from .astra_literature_review import attach_review_plan
        attach_review_plan(tables)
        if review_execution is not None:
            from .astra_literature_review import attach_review_execution
            attach_review_execution(tables,review_execution,EvidenceCatalog(source))
    if whole_only:
        from .astra_reader_full import attach_full
        attach_full(tables)
    validate_reader(tables)
    baseline=json.loads((source/'reproducibility/data_dictionary.json').read_text())
    dictionary=deepcopy(baseline)
    changed=['reader/packet']
    if whole_only or not (access_only or review_plan_only):changed.append('reader/cards')
    update=write_tables({k:tables[k] for k in changed},directory)
    for name in changed:
        key=name+'.csv'
        update[key].update(unique_key=baseline[key]['unique_key'],row_grain=baseline[key]['row_grain'])
    dictionary.update(update);json_write(directory/'reproducibility/data_dictionary.json',dictionary)
    artifacts=write_reader(directory,tables,access_only=access_only,whole_only=whole_only,review_plan_only=review_plan_only,review_execution=review_execution)
    if not (access_only or whole_only or review_plan_only):
        if 'reader/literature_sources' in tables and json.loads(tables['reader/packet'].iloc[0].packet_json).get('literature'):
            literature_stage.write(directory,tables,pins=False)
            artifacts=sorted(set(artifacts+['reader/LITERATURE.md']))
        assert_reader_time_projection_only(source/'reader/cards.csv',directory/'reader/cards.csv')
    # Source values and selection stay fixed; ordinary temporal revisions may
    # permute cards by recorded time. M1/M3/M4 retain the original card bytes.
    allowed={'reader/packet.csv',INDEX,LINKS}
    if not (access_only or whole_only or review_plan_only):allowed.add('reader/cards.csv')
    if whole_only:
        from .astra_reader_full import TABLE_KEYS as FULL_KEYS
        allowed|={'reader/cards.csv',*[k+'.csv' for k in FULL_KEYS]}
    preserved=[name for name in baseline if name not in allowed]
    manifest=json.loads((source/'manifest.json').read_text())
    if refresh_figures:
        from .astra_figures import figure_packet
        design=json.loads((source/'study/study_design.json').read_text())
        figure_packet(tables,directory,design)
    display_files={'figures/figure_legends.json','figures/substrate_contrast_heatmap.svg',
        'figures/emerging_detection.svg','figures/emerging_detection_columns.csv'} if refresh_figures else set()
    preserved+= [name for name in manifest['files'] if name.startswith(('figures/','references/')) and name not in display_files]
    preserved+= ['reproducibility/replay_config.json']
    if access_only or whole_only or review_plan_only:
        preserved += [name for name in manifest['files'] if name.startswith('reader/') and name not in
                      {*allowed,'reader/authoring_packet.json','reader/READ_ME.md',*artifacts}]
    for name in preserved:
        if digest(source/name)!=digest(directory/name):raise ValueError('Reader revision changed preserved bytes: '+name)
    code_files=sorted(set(CODE_FILES+engine.CODE_FILES+READER_CODE_FILES))
    refreshed_code=set(code_files) if not (access_only or whole_only or review_plan_only) else {'astra_evidence_catalog.py','astra_reader.py',
        'astra_reader_revision.py','astra_package.py'}
    if whole_only:refreshed_code|={'astra_reader_full.py','astra_reader_temporal.py'}
    if review_plan_only:refreshed_code|={'astra_literature_review.py','astra_literature.py','finding_literature.py'}
    refreshed_code.update(READER_CODE_FILES)
    captured={name:digest(Path(__file__).with_name(name)) for name in refreshed_code}
    (directory/'reproducibility/code/ptm_shared').mkdir(parents=True,exist_ok=True)
    for name in refreshed_code:shutil.copyfile(Path(__file__).with_name(name),directory/'reproducibility/code/ptm_shared'/name)
    codes={name:digest(directory/'reproducibility/code/ptm_shared'/name) for name in code_files}
    revision={'operation':'saved_reader_display_revision' if refresh_figures else 'saved_temporal_reader_revision','version':VERSION,'run_id':run_id,
        'parent_run_id':origin['run_id'],'parent_manifest_sha256':digest(source/'manifest.json'),
        'scientific_recalculation':False,'finding_selection_repeated':False,'literature_queries':0,
        'display_figures_refreshed':refresh_figures,'changed_display_files':sorted(display_files),
        'preserved_table_hashes':{name:digest(directory/name) for name in preserved},
        'reader_artifacts':artifacts,'replay_scope':'saved_rows_to_reader; not_method_recalculation_or_independent_validation'}
    if access_only:
        revision.update(operation='whole_evidence_access_revision',version=ACCESS_VERSION,
                        refreshed_code_files=sorted(refreshed_code),
                        replay_scope='M1_index_from_saved_sources; existing_reader_and_literature_not_recomputed')
    if whole_only:
        from .astra_reader_full import VERSION as FULL_VERSION
        revision.update(operation='whole_reader_evidence_revision',version=FULL_VERSION,refreshed_code_files=sorted(refreshed_code),
            replay_scope='M2_all_subject_links_from_saved_rows; frozen_selection_and_literature')
    if review_plan_only:
        from .astra_literature_review import VERSION as REVIEW_VERSION
        revision.update(operation='literature_review_plan_revision',version=REVIEW_VERSION,refreshed_code_files=sorted(refreshed_code),
            new_model_calls=0,replay_scope='M3_subject_plan_from_M1_M2_saved_rows; no retrieval/comparison/science execution')
    if review_execution is not None:
        revision.update(operation='literature_subject_execution_revision',version=review_execution['schema_version'],
            literature_queries=review_execution['current_cost']['queries'],new_model_calls=review_execution['current_cost']['model_calls'],
            execution_pin_sha256=review_execution['sha256'],
            effective_literature_selection_sha256=object_hash(review_execution['literature_selection']),
            publication_policy=scope['publication_policy'],whole_review_status=scope['status'],
            replay_scope='frozen typed retrieval/comparison projection; no retrieval, model or scientific replay')
    json_write(directory/'reproducibility/temporal_reader_revision.json',revision)
    provenance=deepcopy(origin);provenance.update(run_id=run_id,parent_package_run_id=origin['run_id'],
        parent_manifest_sha256=revision['parent_manifest_sha256'],operation=revision['operation'],scientific_recalculation=False,
        code_sha256=codes,origin_analysis_code_sha256=origin.get('origin_analysis_code_sha256',origin['code_sha256']),
        stage_reuse={'scientific_tables':{'status':'reused_from_validated_package','run_id':origin['run_id']},
                    'literature':{'status':'frozen_results_reused','run_id':origin['run_id']}})
    provenance['reader_revision_sha256']=object_hash(revision)
    if review_execution is not None:
        provenance['stage_reuse']['typed_literature']={'status':scope['status'],'requested_scope_status':scope['requested_scope_status'],
            'pin_sha256':review_execution['sha256'],'execution':'explicit_separate_stage_frozen_before_revision'}
    provenance['provenance_id']=object_hash({k:v for k,v in provenance.items() if k!='provenance_id'})
    json_write(directory/'provenance.json',provenance)
    json_write(directory/'reproducibility/parent_reader_provenance.json',origin)
    plan=json.loads((directory/'study/analysis_plan.json').read_text())
    plan['reader_revision']={k:v for k,v in revision.items() if k!='preserved_table_hashes'}
    plan['code_dependencies']['evidence'].update(codes)
    json_write(directory/'study/analysis_plan.json',plan)
    json_write(directory/'reproducibility/temporal_reader_stage.json',{
        'stage':'saved_temporal_reader','status':'completed','version':VERSION,
        'parent_run_id':origin['run_id'],'source_hashes':revision['preserved_table_hashes'],
        'code_hashes':{k:codes[k] for k in ['astra_reader.py','astra_reader_temporal.py','astra_reader_revision.py']},
        'scientific_stages':'reused; see preserved original stage ledger'})
    from .astra_package import start_here
    snapshot=json.loads((source/'study/user_input_snapshot.json').read_text())
    readiness=json.loads((source/'evidence/readiness.json').read_text())
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    if packet.get('literature') and not (access_only or whole_only or review_plan_only):
        readiness['literature']=packet['literature']['summary']
        readiness['reader']['literature_comparison']=readiness['literature']['status']
        json_write(directory/'evidence/readiness.json',readiness)
    counts=dict(zip(tables['evidence/coverage_funnel'].metric,tables['evidence/coverage_funnel']['count']))
    (directory/'START_HERE_ASTRA.md').write_text(((source/'START_HERE_ASTRA.md').read_text()+
        '\n\nWhole evidence access: [catalog and query guide](reader/EVIDENCE_ACCESS.md). Summary findings are a preview, not the full evidence scope.\n' if access_only else start_here(snapshot,counts,readiness))+
        '\n\nSaved reader revision: original scientific tables and literature decisions retained; no new analysis.\n',encoding='utf-8')
    if whole_only:
        (directory/'START_HERE_ASTRA.md').write_text('Read [whole evidence denominators, question links and citation instructions](reader/FULL_EVIDENCE.md) before summary findings.\n\n'+(source/'START_HERE_ASTRA.md').read_text(),encoding='utf-8')
    if review_plan_only:
        (directory/'START_HERE_ASTRA.md').write_text((source/'START_HERE_ASTRA.md').read_text()+'\n\n[Whole-evidence literature review subjects](reader/LITERATURE_REVIEW_PLAN.md): new plan only, no new search or model comparison. Existing literature results remain authoritative.\n',encoding='utf-8')
    if review_execution is not None:
        (directory/'START_HERE_ASTRA.md').write_text('[Actual typed literature retrieval/comparison and partial coverage](reader/LITERATURE_SUBJECT_REVIEW.md). '
            'M3 plan availability is separate from actual execution. Legacy literature and scientific results are unchanged.\n\n'+
            (source/'START_HERE_ASTRA.md').read_text(),encoding='utf-8')
    (directory/'evidence_report.html').write_text((source/'evidence_report.html').read_text()+
        '\n<p><a href="reader/TEMPORAL_EVIDENCE.md">Saved temporal observations and sensitivity evidence</a></p>\n',encoding='utf-8')
    checkpoint()
    if captured!={name:digest(Path(__file__).with_name(name)) for name in refreshed_code}:raise ValueError('Reader source changed during revision')
    archive,files=seal_archive(directory,root,run_id,engine.VERSION,checkpoint)
    result=deepcopy(json.loads((source/'platform_run.json').read_text())) if (source/'platform_run.json').is_file() else {}
    result.update(run_id=run_id,provenance=provenance,analysis_plan=plan)
    for value in result.get('artifacts',{}).values():
        path=value['path'].replace(origin['run_id'],run_id);value.update(path=path,sha256=digest(root/path))
    if not result.get('artifacts'):result['artifacts']={'astra':{'path':str(archive.relative_to(root)),'sha256':digest(archive)}}
    result['artifacts']['temporal_reader']={'path':str((directory/'reader/TEMPORAL_EVIDENCE.md').relative_to(root)),
                                           'sha256':digest(directory/'reader/TEMPORAL_EVIDENCE.md')}
    result['publication_metrics']={'archive_bytes':archive.stat().st_size,'manifest_files':len(files),'scientific_recalculation':False}
    json_write(directory/'platform_run.json',result)
    pending=root/('.astra_current_'+run_id+'.json');json_write(pending,result);checkpoint();pending.replace(root/'enrichment_free_current.json')
    return result


def revise_literature(source, output_dir, *, settings=None, retriever=None, llm=None,
                      literature_pin=None, refresh_reason=None, checkpoint=lambda:None):
    from .astra_package import validate_package, write_tables, seal_archive, StageLedger, stage
    from . import astra_evidence_v6 as engine
    from .astra_reader import write_reader
    source=Path(source).resolve();root=Path(output_dir).resolve()
    if root==source or source in root.parents:raise ValueError('Revision must not edit source package')
    validate_package(source)
    config=json.loads((source/'reproducibility/replay_config.json').read_text())
    if config['engine_profile']!=engine.PROFILE:raise ValueError('Reader literature revision requires v6')
    selection_revision=None
    if literature_pin is not None:
        if not isinstance(refresh_reason,str) or not refresh_reason.strip():
            raise ValueError('Explicit literature selection refresh requires a reason')
        if literature_pin.get('schema_version')!='selected_literature_pin.v1':
            raise ValueError('Use a literature selection pin from prepare_astra_inputs')
        ids=[c['id'] for c in literature_pin['collections']]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate literature collection identity')
        requested=literature_pin.get('requested_ids')
        if requested is not None and set(ids)-set(requested):
            raise ValueError('Literature collection outside explicit selection')
        selection_revision={'schema_version':'literature_selection_revision.v1','reason':refresh_reason,
            'previous_selection':deepcopy(config['literature']),
            'previous_pin_sha256':object_hash(config['literature']),
            'effective_pin_sha256':object_hash(literature_pin),
            'selection_provenance':deepcopy(literature_pin.get('selection_provenance',{})),
            'previous_snapshot':deepcopy(config['snapshot'])}
        config['literature']=deepcopy(literature_pin)
        config['snapshot']['original']['rag_collections']=deepcopy(requested)
        for context in (config['context'],config['snapshot']['original'].get('analysis_context',{})):
            context.setdefault('literature_context',{})['selected_collection_ids']=deepcopy(requested)
        config['literature_selection_revision']=selection_revision
    elif refresh_reason is not None:
        raise ValueError('Selection refresh reason requires an explicit literature pin')
    tables=read_tables(source)
    if 'reader/packet' not in tables:raise ValueError('Completed reader adapter/package required')
    origin=json.loads((source/'provenance.json').read_text())
    run_id,directory=_copy_package(source,root)
    if selection_revision:
        # New permitted binaries must be captured separately, never guessed from a path.
        for doc in config['literature'].get('documents',[]):
            if doc.get('content_status')=='full_text_included':
                p=(directory/doc['package_file']).resolve()
                if not p.is_relative_to(directory) or not p.is_file() or digest(p)!=doc.get('sha256'):
                    raise ValueError('New literature binary must already exist in the validated package; use metadata/excerpts otherwise')
    code_files=sorted(set(engine.CODE_FILES))
    from .astra_package import CODE_FILES, READER_CODE_FILES
    code_files=sorted(set(code_files+CODE_FILES+READER_CODE_FILES))
    code_hashes={name:digest(Path(__file__).with_name(name)) for name in code_files}
    metrics=StageLedger(directory/'stage_checkpoint.json',engine.PROFILE,object_hash(code_hashes))
    from .astra_plan import STAGES
    metrics.extend({'stage':name,'status':'reused','origin_run_id':origin['run_id'],
                    'reason':'validated_immutable_package; no_recalculation'}
                   for name in STAGES if name not in {'assemble_evidence_package','validate_and_publish'})
    metrics.plan={'fingerprints':deepcopy(origin['stage_fingerprints']),'operation':'reader_literature_revision'}
    with stage('finding_literature',metrics,checkpoint,lambda _:None):
        pin=literature_stage.collect(tables,config['snapshot'],config['literature'],settings=settings,
            cache_root=root/'.astra_stage_cache',retriever=retriever,llm=llm)
        summary=literature_stage.apply(tables,pin,config['snapshot'],config['literature'])
        metrics.plan['fingerprints']['literature']=pin['request_sha256']
    with stage('assemble_evidence_package',metrics,checkpoint,lambda _:None):
        from .astra_evidence_catalog import attach_access
        attach_access(tables)
        changed={name:tables[name] for name in ['reader/packet',*literature_stage.TABLE_KEYS]}
        if selection_revision:
            from .astra_inputs import transfer_contract
            fields,transfer,brief=transfer_contract(config['snapshot'],config['design'],config['context'],config['literature'])
            for field in fields:
                if field['source_field_path'].startswith('/rag_collections') or '/literature_context/' in field['source_field_path']:
                    field.update(source_kind='explicit_literature_revision',reason=refresh_reason)
            # Replay uses the same serializer; annotation of revision provenance is separate.
            changed['study/input_field_manifest']=pd.DataFrame(transfer_contract(config['snapshot'],config['design'],config['context'],config['literature'])[0])
            json_write(directory/'study/literature_selection_revision.json',{**selection_revision,'field_provenance':fields})
            json_write(directory/'study/user_input_snapshot.json',config['snapshot'])
            json_write(directory/'study/study_context.json',config['context'])
            json_write(directory/'study/input_transfer_validation.json',transfer)
            json_write(directory/'references/literature_pin.json',config['literature'])
            json_write(directory/'reproducibility/replay_config.json',config)
            (directory/'study/STUDY_BRIEF.md').write_text(brief,encoding='utf-8')
        dictionary=json.loads((directory/'reproducibility/data_dictionary.json').read_text())
        dictionary.update(write_tables(changed,directory))
        json_write(directory/'reproducibility/data_dictionary.json',dictionary)
        write_reader(directory,tables)
        readiness=json.loads((directory/'evidence/readiness.json').read_text());readiness['literature']=summary
        readiness['reader']['literature_comparison']=summary['status']
        json_write(directory/'evidence/readiness.json',readiness)
        report=(source/'START_HERE_ASTRA.md').read_text()+'\n\nLiterature reader revision: [reader/LITERATURE.md](reader/LITERATURE.md). Read access, retrieval and semantic-review status separately; frozen replay does not verify biological judgments.\n'
        (directory/'START_HERE_ASTRA.md').write_text(report,encoding='utf-8')
        html=(source/'evidence_report.html').read_text()+'\n<p><a href="reader/LITERATURE.md">Finding literature retrieval and comparison status</a></p>\n'
        (directory/'evidence_report.html').write_text(html,encoding='utf-8')
        comparison=json.loads((directory/'references/literature_comparison_packet.json').read_text())
        comparison.update(comparison_status='see_reader_literature',finding_evidence='reader/LITERATURE.md',
                          selected_literature=config['literature'],experimental_context=config['context'])
        json_write(directory/'references/literature_comparison_packet.json',comparison)
        json_write(directory/'reproducibility/origin_analysis_provenance.json',origin)
        # Preserve original scientific-code pins; new hashes identify the reader revision code.
        provenance=deepcopy(origin);provenance.update(run_id=run_id,origin_analysis_run_id=origin.get('origin_analysis_run_id',origin['run_id']),
            parent_package_run_id=origin['run_id'],parent_manifest_sha256=digest(source/'manifest.json'),
            context_revision_id=object_hash([origin['context_revision_id'],pin['sha256']]),
            literature_result_pin_sha256=pin['sha256'],code_sha256=code_hashes,
            origin_analysis_code_sha256=origin.get('origin_analysis_code_sha256',origin['code_sha256']),
            operation='reader_literature_revision',scientific_recalculation=False)
        provenance.update(literature_pin_hash=object_hash(config['literature']),
                          input_context_hash=object_hash(config['snapshot']))
        if selection_revision:provenance['literature_selection_revision']={k:v for k,v in selection_revision.items() if k!='previous_snapshot'}
        provenance['stage_fingerprints']['literature']=pin['request_sha256']
        provenance['stage_reuse']={'scientific_tables':{'status':'reused_from_validated_package','run_id':origin['run_id']},'literature':pin['cache']}
        provenance['provenance_id']=object_hash({k:v for k,v in provenance.items() if k!='provenance_id'})
        json_write(directory/'provenance.json',provenance)
        plan=json.loads((directory/'study/analysis_plan.json').read_text())
        plan['fingerprints']['literature']=pin['request_sha256'];plan['reader_revision']={'origin_analysis_run_id':provenance['origin_analysis_run_id'],'scientific_recalculation':False}
        json_write(directory/'study/analysis_plan.json',plan)
        for name in code_files:shutil.copyfile(Path(__file__).with_name(name),directory/'reproducibility/code/ptm_shared'/name)
        # Copying is checked bytewise, including all NA/text and scientific precision.
        baseline=json.loads((source/'reproducibility/data_dictionary.json').read_text())
        preserved=[]
        for name in baseline:
            if name=='reader/packet.csv' or name[:-4] in literature_stage.TABLE_KEYS or (selection_revision and name=='study/input_field_manifest.csv'):continue
            if digest(source/name)!=digest(directory/name):raise ValueError('Scientific/card table changed: '+name)
            preserved.append(name)
        json_write(directory/'reproducibility/literature_revision.json',{'origin_run_id':origin['run_id'],'run_id':run_id,
            'preserved_table_hashes':{name:digest(directory/name) for name in preserved},
            'scientific_recalculation':False,'finding_selection_repeated':False,'figures_reused':True,
            'replay_scope':'frozen_retrieval_and_reader_projection; not_semantic_validation'})
    with stage('validate_and_publish',metrics,checkpoint,lambda _:None):
        if code_hashes!={name:digest(Path(__file__).with_name(name)) for name in code_files}:
            raise ValueError('Reader source changed during revision')
        json_write(directory/'reproducibility/stage_metrics.json',list(metrics))
        shutil.copyfile(directory/'stage_checkpoint.json',directory/'reproducibility/stage_ledger.json')
        archive,files=seal_archive(directory,root,run_id,engine.VERSION,checkpoint)
        result=deepcopy(json.loads((source/'platform_run.json').read_text())) if (source/'platform_run.json').is_file() else {}
        result.update(run_id=run_id,provenance=provenance,analysis_readiness=readiness,analysis_plan=plan)
        result['literature_pin']=deepcopy(config['literature'])
        if 'study_preview' in result:result['study_preview']['snapshot']=deepcopy(config['snapshot'])
        for key,value in result.get('artifacts',{}).items():
            path=value['path'].replace(origin['run_id'],run_id)
            value.update(path=path,sha256=digest(root/path))
        if not result.get('artifacts'):result['artifacts']={'astra':{'path':str(archive.relative_to(root)),'sha256':digest(archive)}}
        result['artifacts']['literature']={'path':str((directory/'reader/LITERATURE.md').relative_to(root)),'sha256':digest(directory/'reader/LITERATURE.md')}
        result['publication_metrics']={'archive_bytes':archive.stat().st_size,'manifest_files':len(files),'scientific_recalculation':False}
        json_write(directory/'platform_run.json',result)
        pending=root/('.astra_current_'+run_id+'.json');json_write(pending,result);checkpoint();pending.replace(root/'enrichment_free_current.json')
    return result
