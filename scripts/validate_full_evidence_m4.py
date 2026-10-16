"""Publish frozen M4 execution and audit preservation/replay, never run research."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from unittest.mock import patch
from ptm_shared.annotation_registry import digest
from ptm_shared.generic_workflow import json_write
from ptm_shared.astra_reader_revision import revise_temporal
from ptm_shared.astra_evidence_catalog import EvidenceCatalog
from ptm_shared.astra_reader_full import validate_citations
from ptm_shared import astra_literature_review as review


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path);p.add_argument('--pin',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--package',type=Path)
    args=p.parse_args();source=args.source.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    pin=json.loads(args.pin.read_text());started=time.monotonic()
    manifest=json.loads((source/'manifest.json').read_text())['files'];baseline={n:v['sha256'] for n,v in manifest.items()}
    json_write(out/'BASELINE_HASHES.json',baseline)
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    def replay(root):
        run=subprocess.run([sys.executable,'scripts/replay_astra_reader.py','--package',str(root),'--output',str(out/'reader-replay')],
                           env=env,capture_output=True,text=True)
        (out/'REPLAY_LOG.txt').write_text(run.stdout+run.stderr)
        if run.returncode:raise RuntimeError('Reader replay failed; previous pointer retained; see REPLAY_LOG.txt')
    def publication_checkpoint():
        pending=list((out/'revision').glob('.astra_current_*.json'))
        if pending:
            if len(pending)!=1:raise ValueError('Ambiguous pending publication')
            run_id=json.loads(pending[0].read_text())['run_id']
            replay(out/'revision/enrichment_free_runs'/run_id)
    with ExitStack() as guards:
        for name in ['ptm_shared.astra_package.compute_science','ptm_shared.astra_literature.collect',
                     'ptm_shared.finding_literature.retrieve_finding_literature','ptm_shared.astra_literature._runtime',
                     'ptm_shared.astra_literature_review.execute_review','socket.create_connection','urllib.request.urlopen']:
            guards.enter_context(patch(name,side_effect=AssertionError('Frozen M4 publication forbids '+name)))
        if args.package:
            root=args.package.resolve();result=json.loads((root/'platform_run.json').read_text())
        else:
            result=revise_temporal(source,out/'revision',review_execution=pin,checkpoint=publication_checkpoint)
            root=out/'revision/enrichment_free_runs'/result['run_id']
        json_write(out/'REVISION_RESULT.json',result)
        changed={n:{'before':h,'after':digest(root/n)} for n,h in baseline.items() if digest(root/n)!=h}
        allowed={'reader/packet.csv','reader/authoring_packet.json','reader/READ_ME.md','reader/EVIDENCE_ACCESS.md',
            'reader/evidence_catalog.json',review.META,review.GUIDE,'reproducibility/data_dictionary.json','provenance.json',
            'reproducibility/parent_reader_provenance.json','reproducibility/temporal_reader_revision.json',
            'reproducibility/temporal_reader_stage.json','study/analysis_plan.json','START_HERE_ASTRA.md','evidence_report.html'}
        allowed|={'reproducibility/code/ptm_shared/'+n for n in ['astra_package.py','astra_reader.py','astra_reader_revision.py','astra_literature_review.py']}
        if set(changed)-allowed:raise ValueError('Unexpected changed files: '+str(set(changed)-allowed))
        preserved={n:h for n,h in baseline.items() if n not in changed}
        quant={n:h for n,h in preserved.items() if n.startswith('quant/') and n.endswith('.csv')}
        assert len(quant)==22
        mandatory=[n for n in baseline if n.startswith(('quant/','science/','kinase/','temporal/','figures/','references/','reader_adapter/'))]
        mandatory+=['reader/findings.csv','reader/cards.csv','reader/coverage.csv',review.PLAN,
                    'reader/question_map.json','reproducibility/replay_config.json']
        assert all(n in preserved for n in mandatory)
        assert all(digest(source/n)==h for n,h in baseline.items())
        old=json.loads((source/'reader/authoring_packet.json').read_text());packet=json.loads((root/'reader/authoring_packet.json').read_text())
        for key in ('reader_cards','research_question_evidence_map','literature','original_questions','temporal_evidence','whole_evidence'):
            assert packet.get(key)==old.get(key),key
        catalog=EvidenceCatalog(root);summary=review.validate_execution(catalog)
        assert review.replay_review(pin,catalog)==pin['retrieval']
        citations=[{'run_id':result['run_id'],'catalog_id':catalog.catalog['catalog_id'],**ref} for ref in pin['subject_evidence'].values()]
        validated=validate_citations(catalog,citations)
        assert all(r['status']=='source_anchor_validated' for r in validated)
        # The original M1 index still records review_status=not_recorded: external
        # author review logs cannot be inferred from platform retrieval.
        assert set(catalog.index.review_status)=={'not_recorded'}
    if args.package:replay(root)
    replay=json.loads((out/'reader-replay/READER_REPLAY_VALIDATION.json').read_text());assert replay['frozen_typed_literature_rebuilt']
    links=[]
    for name in [review.EXECUTION_GUIDE,review.GUIDE,'reader/READ_ME.md','START_HERE_ASTRA.md']:
        for target in re.findall(r'\]\(([^)]+)\)',(root/name).read_text()):
            if '://' in target or target.startswith('#'):continue
            path=(root/name).parent/target.split('#')[0]
            if not path.exists():raise ValueError('Broken relative link: '+name+' -> '+target)
            links.append({'source':name,'target':target})
    archive=root.parents[1]/('astra_analysis_package_'+result['run_id']+'.zip')
    report={'passed':True,'baseline_run':source.name,'run_id':result['run_id'],'package_root':str(root),
        'archive':str(archive),'zip_sha256':digest(archive),'elapsed_seconds':time.monotonic()-started,
        'execution_summary':summary,'preserved_files':preserved,'preserved_quant_csv':quant,
        'changed_existing_files':changed,'added_files':sorted(set(json.loads((root/'manifest.json').read_text())['files'])-set(baseline)),
        'mandatory_preserved_files':len(mandatory),'typed_citations_validated':len(validated),'relative_links_checked':len(links),
        'reader_replay':replay,'publication_network_calls':0,'publication_model_calls':0,
        'scientific_recalculation':False,'scope':'actual execution frozen before publication; offline replay checks reconstruction, not new retrieval or semantic validity',
        'git':{'push':False,'deployment':False,'flag_changes':False}}
    json_write(out/'FULL_EVIDENCE_M4_VALIDATION.json',report)
    print(json.dumps({k:report[k] for k in ['passed','run_id','zip_sha256','execution_summary','elapsed_seconds']},ensure_ascii=False))


if __name__=='__main__':main()
