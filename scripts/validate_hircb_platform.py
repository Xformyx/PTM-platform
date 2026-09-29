"""Real HTTP → MySQL/Redis/Celery validation against an isolated running stack.

Never run against a production service: this creates orders and uploads PR/PG.
"""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import uuid4
from urllib.parse import urlparse
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000/api')
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reference-preset',action='store_true',help='New canonical design with explicit HIRc-B reference adapter and session-declared metadata')
    parser.add_argument('--single-run',action='store_true',help='Create and download one real-input package; Copy/Rerun is verified separately')
    parser.add_argument('--astra',action='store_true',help='Validate the new automatic Astra package separately from reference regression')
    args=parser.parse_args()
    if urlparse(args.base_url).scheme!='http' or urlparse(args.base_url).hostname!='127.0.0.1':
        parser.error('This validation script requires an isolated localhost service')
    args.output.mkdir(parents=True,exist_ok=True)
    samples=json.loads((args.inputs/'validation-results/delivery/astra_handoff/samples.json').read_text())
    conditions={s['time_min']: 'Control' if s['time_min']==0 else f"{s['time_min']}min" for s in samples}
    manifest={'schema_version':'sample_manifest.v1','pairing':'unpaired',
        'samples':[{'sample_id':s['original_column'],'condition':conditions[s['time_min']],
                    'biological_unit':f"material_{s['time_min']}",'technical_injection':str(s['run_suffix'])} for s in samples],
        'conditions':[{'condition':c,'time_minutes':t} for t,c in conditions.items()]}
    context={'quantitation_export_mode':'enrichment_free_primary.v2','enrichment_status':'enrichment_free',
        'normalization_policy':'already_normalized.v1','sample_manifest':manifest,
        'annotation_snapshot_sha256':'80c9ae707a853169b6890a1e393f72f9f0b57edbf94e0c1e6f61dec57594de07'}
    if args.reference_preset:
        context.update(quantitation_export_mode='enrichment_free_timecourse.v3',analysis_preset='hircb_insulin_reference.v1',
            annotation_mode='required',cell_type='HIRc-B',treatment='insulin',time_points='0,1,5,15,30,60,180min',
            biological_question=None,special_conditions='serum starvation 12 h',
            acquisition_metadata={'insulin_concentration':'100 nM','starvation_duration':'12 h','injection_amount':'10 µL'},
            acquisition={'injection_volume':{'value':10,'unit':'µL','status':'provided','source':'user_declaration_2026-09-26'},
                         'injected_peptide_mass':{'value':None,'status':'unknown'}},
            pre_treatment={'name':'serum starvation','duration':12,'unit':'h','source':'user_declaration_2026-09-26'},
            processing={k:{'value':None,'status':'unknown'} for k in ['software_version','upstream_normalization']})
    if args.astra:
        context.update(quantitation_export_mode='astra_analysis.v4',replication_declaration='technical_per_condition',
            cell_type='HIRc-B rat fibroblast; human INSR overexpression',treatment='insulin',time_points='0,1,5,15,30,60,180min',
            biological_question='Parent-adjusted PTM, kinase candidate and temporal protein evidence for insulin response',
            special_conditions='Enrichment-free Astral DIA; serum starvation 12 h',
            treatments=[{'name':'insulin','dose':100,'unit':'nM','source':'user_declaration_2026-09-26'}],
            acquisition_metadata={'insulin_concentration':'100 nM'},
            acquisition={'injection_volume':{'value':10,'unit':'µL','status':'provided','source':'user_declaration_2026-09-26'},'injected_peptide_mass':{'value':None,'status':'unknown'}},
            pre_treatment={'name':'serum starvation','duration':12,'unit':'h','source':'user_declaration_2026-09-26'},
            processing={k:{'value':None,'status':'unknown'} for k in ['software_version','upstream_normalization']})
        for field in ['annotation_snapshot_sha256','annotation_mode','analysis_preset']:context.pop(field,None)
    sample_config={'samples':[{'file_name':s['original_column'],'condition':conditions[s['time_min']],
                              'group':'Control' if s['time_min']==0 else 'Treatment','replicate':s['run_suffix']} for s in samples]}
    name='HIRcB_followup_'+uuid4().hex[:8]
    client=httpx.Client(base_url=args.base_url,timeout=120)
    login=client.post('/auth/login',json={'email':os.environ['PTM_TEST_EMAIL'],'password':os.environ['PTM_TEST_PASSWORD']})
    login.raise_for_status()
    client.headers['Authorization']='Bearer '+login.json()['access_token']
    events=[]
    def request(method,path,**kwargs):
        response=client.request(method,path,**kwargs)
        events.append({'method':method,'path':path,'status':response.status_code})
        response.raise_for_status()
        return response.json()
    def wait(order_id):
        deadline=time.monotonic()+7200
        previous=None
        while time.monotonic()<deadline:
            state=request('GET',f'/orders/{order_id}')
            if state['status']!=previous:
                print(order_id,state['status'],flush=True); previous=state['status']
            if state['status']=='completed':
                return request('GET',f'/orders/{order_id}/enrichment-free-evidence')
            if state['status'] in ('failed','cancelled'):
                raise AssertionError(state.get('error_message',state))
            time.sleep(3)
        raise TimeoutError(order_id)
    assert request('GET','/orders/frozen-annotations')['snapshots']
    attachment=args.inputs/'HIRcB_Insulin_Full_Article (2).docx'
    attachment_files={'research_attachments':(attachment.name,attachment.read_bytes())} if args.astra and attachment.exists() else {}
    with (args.inputs/'report.pr_matrix.tsv').open('rb') as pr,(args.inputs/'report.pg_matrix.tsv').open('rb') as pg:
        order=request('POST','/orders',data={'project_name':name,'ptm_type':'phosphorylation','species':'Rat_hir',
            'sample_config':json.dumps(sample_config),'analysis_context':json.dumps(context),
            'analysis_options':json.dumps({'mode':'full','quick_analysis':False}),
            'report_options':json.dumps({'top_n_ptms':50})},
            files={'pr_matrix':('report.pr_matrix.tsv',pr),'pg_matrix':('report.pg_matrix.tsv',pg),**attachment_files})
    order_id=order['id']
    print('created',order_id,name,flush=True)
    (args.output/'order.json').write_text(json.dumps({'id':order_id,'order_code':name,'species':'Rat_hir','ptm_type':'phosphorylation','source':'validation_request','analysis_context':context},indent=2,ensure_ascii=False))
    request('POST',f'/orders/{order_id}/start')
    original=wait(order_id)
    if args.astra:
        assert original['schema_version']=='astra_analysis_package.v4'
        assert original['counts']['forms']==2824 and original['counts']['parent_eligible']==2625
        assert original['study_preview']['transfer_validation']['unexpected_missing']==0
    else:
        assert original['counts']['primary_comparisons']==11920
        assert original['counts']['kinase_profiles_v1']==3948
    if args.single_run:
        import hashlib,zipfile,io
        response=client.get(f'/orders/{order_id}/enrichment-free-evidence',params={'artifact':'astra'});response.raise_for_status()
        assert hashlib.sha256(response.content).hexdigest()==original['artifacts']['astra']['sha256']
        (args.output/'astra_analysis_package.zip').write_bytes(response.content)
        (args.output/'recorded_run.json').write_text(json.dumps(original,indent=2,ensure_ascii=False))
        if attachment_files:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                pin=json.loads(archive.read('references/literature_pin.json'))
                doc=next(r for r in pin['documents'] if r['filename']==attachment.name)
                assert archive.read(doc['package_file'])==attachment.read_bytes()
        (args.output/'validation.json').write_text(json.dumps({'passed':True,'order_id':order_id,'run_id':original['run_id'],'attachment_bytes_preserved':bool(attachment_files),'download_checksum_verified':True},indent=2))
        print('Single-run package and attached original verified',flush=True);return
    copied=request('POST',f'/orders/{order_id}/duplicate',json={'new_order_name':name+'_copy'})
    copy_id=copied['id']
    copy_state=request('GET',f'/orders/{copy_id}')
    if args.astra:assert copy_state['analysis_context']['study_design']==request('GET',f'/orders/{order_id}')['analysis_context']['study_design']
    else:assert copy_state['analysis_context']==request('GET',f'/orders/{order_id}')['analysis_context']
    request('POST',f'/orders/{copy_id}/start')
    copy_result=wait(copy_id)
    # Settings edits must never relabel an existing result. Then restore the
    # original policy before rerunning so the new primary output is comparable.
    request('PATCH',f'/orders/{order_id}',json={'analysis_context':{'normalization_policy':'legacy_median.v1'}})
    after_edit=request('GET',f'/orders/{order_id}/enrichment-free-evidence')
    assert after_edit['provenance']==original['provenance']
    assert after_edit['provenance']['normalization']['normalization_policy']=='already_normalized.v1'
    request('PATCH',f'/orders/{order_id}',json={'analysis_context':{'normalization_policy':'already_normalized.v1'}})
    # A report-stage request follows the primary-A full-run path, never legacy RAG.
    request('POST',f'/orders/{order_id}/run-stage',json={'stage':'report_generation'})
    rerun=wait(order_id)
    assert len({r['run_id'] for r in [original,copy_result,rerun]})==3
    for key in (['input_hashes','design_hash','normalization','estimator_versions','source_pin_sha256'] if args.astra else ['input_files','design_sha256','declared_design','normalization','estimator_versions','annotation_sha256']):
        assert original['provenance'][key]==copy_result['provenance'][key]==rerun['provenance'][key],key
    for label,record in [('original',original),('copy',copy_result),('rerun',rerun)]:
        (args.output/(label+'.json')).write_text(json.dumps(record,indent=2))
        oid=copy_id if label=='copy' else order_id
        # Artifact endpoint verifies recorded checksums before delivery.
        if label!='original':
            for artifact in ('report','primary_input','astra'):
                response=client.get(f'/orders/{oid}/enrichment-free-evidence',params={'artifact':artifact})
                response.raise_for_status()
                import hashlib
                assert hashlib.sha256(response.content).hexdigest()==record['artifacts'][artifact]['sha256']
                if artifact=='astra':(args.output/(label+'.zip')).write_bytes(response.content)
    result={'passed':True,'order_id':order_id,'copy_id':copy_id,'order_code':name,
        'real_services':['FastAPI','MySQL','Redis','Celery'],'run_ids':[r['run_id'] for r in [original,copy_result,rerun]],
        'copy_settings_preserved':True,'edited_settings_do_not_relabel_prior_results':True,'reference_preset':args.reference_preset,'astra':args.astra,
        'report_rerun_uses_primary_A_pipeline':True,'events':events}
    (args.output/'validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='events'},indent=2))


if __name__=='__main__':
    main()
