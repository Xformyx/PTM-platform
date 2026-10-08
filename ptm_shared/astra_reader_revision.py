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


def read_tables(root):
    dictionary=json.loads((Path(root)/'reproducibility/data_dictionary.json').read_text())
    return {name[:-4]:pd.read_csv(Path(root)/name,low_memory=False,float_precision='round_trip',
            dtype={k:'str' for k,v in d['dtypes'].items() if v in {'str','object'}}) for name,d in dictionary.items()}


def revise_literature(source, output_dir, *, settings=None, retriever=None, llm=None, checkpoint=lambda:None):
    from .astra_package import validate_package, write_tables, seal_archive, StageLedger, stage
    from . import astra_evidence_v6 as engine
    from .astra_reader import write_reader
    source=Path(source).resolve();root=Path(output_dir).resolve()
    if root==source or source in root.parents:raise ValueError('Revision must not edit source package')
    validate_package(source)
    config=json.loads((source/'reproducibility/replay_config.json').read_text())
    if config['engine_profile']!=engine.PROFILE:raise ValueError('Reader literature revision requires v6')
    tables=read_tables(source)
    if 'reader/packet' not in tables:raise ValueError('Completed reader adapter/package required')
    origin=json.loads((source/'provenance.json').read_text());run_id='g0-'+uuid4().hex
    directory=root/'enrichment_free_runs'/run_id
    directory.mkdir(parents=True,exist_ok=False)
    source_manifest=json.loads((source/'manifest.json').read_text())
    for name in [*source_manifest['files'],'manifest.json']:
        target=directory/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,target)
    code_files=sorted(set(engine.CODE_FILES))
    from .astra_package import CODE_FILES
    code_files=sorted(set(code_files+CODE_FILES))
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
        changed={name:tables[name] for name in ['reader/packet',*literature_stage.TABLE_KEYS]}
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
        comparison.update(comparison_status='see_reader_literature',finding_evidence='reader/LITERATURE.md')
        json_write(directory/'references/literature_comparison_packet.json',comparison)
        json_write(directory/'reproducibility/origin_analysis_provenance.json',origin)
        # Preserve original scientific-code pins; new hashes identify the reader revision code.
        provenance=deepcopy(origin);provenance.update(run_id=run_id,origin_analysis_run_id=origin.get('origin_analysis_run_id',origin['run_id']),
            parent_package_run_id=origin['run_id'],parent_manifest_sha256=digest(source/'manifest.json'),
            context_revision_id=object_hash([origin['context_revision_id'],pin['sha256']]),
            literature_result_pin_sha256=pin['sha256'],code_sha256=code_hashes,
            origin_analysis_code_sha256=origin.get('origin_analysis_code_sha256',origin['code_sha256']),
            operation='reader_literature_revision',scientific_recalculation=False)
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
            if name=='reader/packet.csv' or name[:-4] in literature_stage.TABLE_KEYS:continue
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
        for key,value in result.get('artifacts',{}).items():
            path=value['path'].replace(origin['run_id'],run_id)
            value.update(path=path,sha256=digest(root/path))
        if not result.get('artifacts'):result['artifacts']={'astra':{'path':str(archive.relative_to(root)),'sha256':digest(archive)}}
        result['artifacts']['literature']={'path':str((directory/'reader/LITERATURE.md').relative_to(root)),'sha256':digest(directory/'reader/LITERATURE.md')}
        result['publication_metrics']={'archive_bytes':archive.stat().st_size,'manifest_files':len(files),'scientific_recalculation':False}
        json_write(directory/'platform_run.json',result)
        pending=root/('.astra_current_'+run_id+'.json');json_write(pending,result);checkpoint();pending.replace(root/'enrichment_free_current.json')
    return result
