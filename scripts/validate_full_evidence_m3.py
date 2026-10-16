"""Audit an immutable M3 plan revision using saved M2 evidence; no real retrieval."""
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
from ptm_shared.astra_card_inputs import encode
from ptm_shared.generic_workflow import json_write, object_hash
from ptm_shared.astra_evidence_catalog import EvidenceCatalog, read_source
from ptm_shared.astra_reader_revision import revise_temporal
from ptm_shared.astra_reader_full import validate_citations
from ptm_shared import astra_literature_review as review


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--package',type=Path)
    args=p.parse_args();source=args.source.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();manifest=json.loads((source/'manifest.json').read_text())['files']
    baseline={name:entry['sha256'] for name,entry in manifest.items()}
    json_write(out/'BASELINE_HASHES.json',baseline)
    with ExitStack() as guards:
        for name in ['ptm_shared.astra_package.compute_science','ptm_shared.astra_literature.collect',
                     'ptm_shared.finding_literature.retrieve_finding_literature',
                     'ptm_shared.astra_literature._runtime','ptm_shared.astra_literature_review.execute_review',
                     'socket.create_connection','urllib.request.urlopen']:
            guards.enter_context(patch(name,side_effect=AssertionError('M3 actual validation forbids execution: '+name)))
        if args.package:
            root=args.package.resolve();result=json.loads((root/'platform_run.json').read_text())
        else:
            result=revise_temporal(source,out/'revision',review_plan_only=True)
            root=out/'revision/enrichment_free_runs'/result['run_id']
        json_write(out/'REVISION_RESULT.json',result)
        changed={name:{'before':sha,'after':digest(root/name)} for name,sha in baseline.items() if digest(root/name)!=sha}
        allowed={'reader/packet.csv','reader/authoring_packet.json','reader/READ_ME.md','reader/EVIDENCE_ACCESS.md',
            'reader/evidence_catalog.json','reproducibility/data_dictionary.json','provenance.json',
            'reproducibility/parent_reader_provenance.json','reproducibility/temporal_reader_revision.json',
            'reproducibility/temporal_reader_stage.json','study/analysis_plan.json','START_HERE_ASTRA.md','evidence_report.html'}
        allowed|={'reproducibility/code/ptm_shared/'+n for n in ['astra_package.py','astra_reader.py','astra_reader_revision.py',
                    'astra_literature.py','finding_literature.py','astra_literature_review.py']}
        if set(changed)-allowed:raise ValueError('Unexpected modified files: '+str(set(changed)-allowed))
        preserved={n:s for n,s in baseline.items() if n not in changed}
        quant={n:s for n,s in preserved.items() if n.startswith('quant/') and n.endswith('.csv')}
        assert len(quant)==22
        assert all(digest(source/n)==sha for n,sha in baseline.items())
        packet=json.loads((root/'reader/authoring_packet.json').read_text())
        old=json.loads((source/'reader/authoring_packet.json').read_text())
        compare=json.loads(json.dumps(packet));compare.pop('literature_review_plan')
        compare['authoring_rules'].pop('literature_review_subjects')
        assert compare==old, 'Only M3 packet extension may change'
        catalog=EvidenceCatalog(root);validation=review.validate_plan(catalog)
        plan=read_source(root,review.PLAN,catalog.catalog['sources'][review.PLAN])
        qname='reader/full_question_links.csv';questions=read_source(root,qname,catalog.catalog['sources'][qname])
        sweeps=[]
        for maximum in [5,15,50,0]:
            catalog.index['selected_for_summary']=False
            catalog.index.loc[catalog.index.index[:maximum],'selected_for_summary']=True
            generated=review.build_plan(catalog,questions)
            sweeps.append({'summary_maximum':maximum,'subjects':len(generated),'semantic_hash':object_hash(generated.to_dict('records'))})
        assert len({r['semantic_hash'] for r in sweeps})==1
        config=json.loads((root/'reproducibility/replay_config.json').read_text())
        tables={'reader/packet':read_source(root,'reader/packet.csv',catalog.catalog['sources']['reader/packet.csv'])}
        examples=[]
        cases=[('MAPK1','form_97aa4b58cee5c391','observation'),('GSK3A','form_6618452f34b3cbbc','observation'),
               ('MAPK3','form_eeaed22a5119b2f5','raw_ptm'),('IRS1','form_9951a8944f668c17','raw_ptm'),
               ('INSR_shared','form_d4f68593541e8e86','raw_ptm')]
        for label,fid,kind in cases:
            matches=catalog.query({'form_id':fid,'evidence_type':kind},page_size=100)['items']
            assert matches, (label,kind)
            eid=matches[0]['evidence_id'];subject=plan.loc[plan.evidence_id.eq(eid)].iloc[0]
            payload,_=review.resolve_subjects(catalog,plan,[subject.review_subject_id],tables,config['snapshot'],config['literature'])
            examples.append({'label':label,'form_id':fid,'subject':subject.to_dict(),'resolved_input':payload[0]})
        for kind in ['protein','detection','method_result','inference']:
            subject=plan.loc[plan.subject_type.eq(kind)].iloc[0]
            payload,_=review.resolve_subjects(catalog,plan,[subject.review_subject_id],tables,config['snapshot'],config['literature'])
            examples.append({'label':kind,'subject':subject.to_dict(),'resolved_input':payload[0]})
        citations=[{'run_id':result['run_id'],'catalog_id':catalog.catalog['catalog_id'],
            'evidence_id':e['subject']['evidence_id'],'source_table':e['subject']['source_table'],
            'source_key':json.loads(e['subject']['source_key_json'])} for e in examples[:3]]
        anchors=validate_citations(catalog,citations)
        assert all(a['status']=='source_anchor_validated' for a in anchors)
        json_write(out/'RESOLVED_EXAMPLES.json',examples)
        meta=json.loads((root/review.META).read_text())
        assert meta['current_queries']==meta['current_model_calls']==0
    # Execute package-local CLI and reconstruction in isolated Python; no repository imports.
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    command=[sys.executable,'scripts/replay_astra_reader.py','--package',str(root),'--output',str(out/'reader-replay')]
    done=subprocess.run(command,env=env,capture_output=True,text=True)
    (out/'REPLAY_LOG.txt').write_text(done.stdout+done.stderr)
    if done.returncode:raise RuntimeError('Reader replay failed; see REPLAY_LOG.txt')
    replay=json.loads((out/'reader-replay/READER_REPLAY_VALIDATION.json').read_text())
    script="import sys,runpy,socket;socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(AssertionError('network'));sys.path.insert(0,sys.argv.pop(1));runpy.run_module('ptm_shared.astra_literature_review',run_name='__main__')"
    cli=subprocess.run([sys.executable,'-I','-c',script,str(root/'reproducibility/code'),'--package',str(root),
        '--evidence-id',examples[0]['subject']['evidence_id']],capture_output=True,text=True,env=env,cwd='/tmp')
    if cli.returncode:raise RuntimeError(cli.stderr)
    cli_result=json.loads(cli.stdout);assert cli_result['execution']=='not_requested'
    json_write(out/'CLI_RESULT.json',cli_result)
    links=[]
    for name in [review.GUIDE,'START_HERE_ASTRA.md','reader/READ_ME.md']:
        for target in re.findall(r'\]\(([^)]+)\)',(root/name).read_text()):
            if '://' in target or target.startswith('#'):continue
            path=(root/name).parent/target.split('#')[0]
            if not path.exists():raise ValueError('Broken relative link: '+name+' -> '+target)
            links.append({'source':name,'target':target})
    archive=Path(result['artifacts']['astra']['path']) if 'astra' in result.get('artifacts',{}) else None
    if archive is None or not archive.is_absolute():
        archive=root.parents[1]/('astra_analysis_package_'+result['run_id']+'.zip')
    report={'passed':True,'baseline_run':json.loads((source/'provenance.json').read_text())['run_id'],
        'run_id':result['run_id'],'package_root':str(root),'archive':str(archive),'zip_sha256':digest(archive),
        'elapsed_seconds':time.monotonic()-started,'actual_retrievals':0,'actual_model_calls':0,'scientific_recalculation':False,
        'plan_validation':validation,'plan_metadata':meta,'summary_independence':sweeps,
        'preserved_files':preserved,'preserved_quant_csv':quant,'changed_existing_files':changed,
        'added_files':sorted(set(json.loads((root/'manifest.json').read_text())['files'])-set(baseline)),
        'packet_only_M3_extension':True,'typed_citations_validated':len(anchors),'relative_links_checked':len(links),
        'reader_replay':replay,'query_cli':'package-local executed; resolved unselected MAPK1, no retrieval',
        'scope':'M3 planning and input access only; original frozen literature preserved; M4 not performed',
        'git':{'base':'4a29b769a106c513a6e39a33aaab948f9369699a','push':False,'deployment':False,'flags_changed':False}}
    json_write(out/'FULL_EVIDENCE_M3_VALIDATION.json',report)
    print(encode({k:report[k] for k in ['passed','run_id','zip_sha256','elapsed_seconds','plan_validation']}))


if __name__=='__main__':main()
