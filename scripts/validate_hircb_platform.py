"""Real HTTP → MySQL/Redis/Celery validation against an isolated running stack.

Never run against a production service: this creates orders and uploads PR/PG.
"""
import argparse
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000/api')
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.base_url.startswith('http://127.0.0.1:'):
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
    sample_config={'samples':[{'file_name':s['original_column'],'condition':conditions[s['time_min']],
                              'group':'Control' if s['time_min']==0 else 'Treatment','replicate':s['run_suffix']} for s in samples]}
    name='HIRcB_followup_'+uuid4().hex[:8]
    client=httpx.Client(base_url=args.base_url,timeout=120)
    login=client.post('/auth/login',json={'email':'admin@ptm.local','password':'local_validation_only'})
    login.raise_for_status()
    client.headers['Authorization']='Bearer '+login.json()['access_token']
    events=[]
    def request(method,path,**kwargs):
        response=client.request(method,path,**kwargs)
        events.append({'method':method,'path':path,'status':response.status_code})
        response.raise_for_status()
        return response.json()
    def wait(order_id):
        deadline=time.monotonic()+900
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
    with (args.inputs/'report.pr_matrix.tsv').open('rb') as pr,(args.inputs/'report.pg_matrix.tsv').open('rb') as pg:
        order=request('POST','/orders',data={'project_name':name,'ptm_type':'phosphorylation','species':'Rat_hir',
            'sample_config':json.dumps(sample_config),'analysis_context':json.dumps(context),
            'analysis_options':json.dumps({'mode':'full','quick_analysis':False}),
            'report_options':json.dumps({'top_n_ptms':50})},
            files={'pr_matrix':('report.pr_matrix.tsv',pr),'pg_matrix':('report.pg_matrix.tsv',pg)})
    order_id=order['id']
    print('created',order_id,name,flush=True)
    (args.output/'order.json').write_text(json.dumps(order,indent=2))
    request('POST',f'/orders/{order_id}/start')
    original=wait(order_id)
    assert original['counts']['primary_comparisons']==11920
    assert original['counts']['kinase_profiles_v1']==3948
    copied=request('POST',f'/orders/{order_id}/duplicate',json={'new_order_name':name+'_copy'})
    copy_id=copied['id']
    copy_state=request('GET',f'/orders/{copy_id}')
    assert copy_state['analysis_context']==request('GET',f'/orders/{order_id}')['analysis_context']
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
    for key in ['input_files','design_sha256','declared_design','normalization','estimator_versions','annotation_sha256']:
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
    result={'passed':True,'order_id':order_id,'copy_id':copy_id,'order_code':name,
        'real_services':['FastAPI','MySQL','Redis','Celery'],'run_ids':[r['run_id'] for r in [original,copy_result,rerun]],
        'copy_settings_preserved':True,'edited_settings_do_not_relabel_prior_results':True,
        'report_rerun_uses_primary_A_pipeline':True,'events':events}
    (args.output/'validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='events'},indent=2))


if __name__=='__main__':
    main()
