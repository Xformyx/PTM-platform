"""Isolated local API/worker acceptance fixture. Never accepts a production URL.

Credentials come only from PTM_TEST_EMAIL / PTM_TEST_PASSWORD environment variables.
Outputs contain experimental fixtures, run IDs, checksums and test assertions only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse
from uuid import uuid4
import zipfile

import httpx
import numpy as np
import pandas as pd


def make_fixture(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    samples=[]
    for arm,times in [('vehicle',[0]),('AB',[60,180]),('CuAB',[60,180])]:
        for t in times:
            for rep in [1,2,3]:samples.append({'file_name':f'{arm}_{t}_{rep}','condition':f'{arm} {t}min',
                'arm':arm,'group':'Control' if arm=='vehicle' else 'Treatment','replicate':rep})
    cols=[s['file_name'] for s in samples];pr=[];pg=[];fasta=[];annotation=[]
    for gi,gene in enumerate(['GENA','GENB','GENC','EMERGENT','EGFR']):
        accession='SYNTHETIC'+str(gi);group=accession
        peptides=['ASAAK','ASTTK'];sequence='M'+peptides[0]+'QQ'+peptides[1]+'PEPTIDEAAK'+'PEPTIDEVVK'
        fasta.append(f'>sp|{accession}|SYNTHETIC_{gene} GN={gene} OX=9606\n{sequence}\n')
        pg_values={s['file_name']:2. if s['arm']=='vehicle' else 4. if s['arm']=='AB' else 1. for s in samples}
        pg.append({'Protein.Group':group,'Genes':gene,**pg_values})
        base={'Protein.Group':group,'Protein.Ids':accession,'Genes':gene,'Proteotypic':1,'Precursor.Charge':2}
        for seq in ['PEPTIDEAAK','PEPTIDEVVK']:
            pr.append({**base,'Precursor.Id':accession+'_'+seq,'Stripped.Sequence':seq,'Modified.Sequence':seq,
                **{c:value*100 for c,value in pg_values.items()}})
        if gene=='EGFR':continue
        for si,seq in enumerate(peptides):
            values={s['file_name']:100. if s['arm']=='vehicle' else 400. if s['arm']=='AB' else 25. for s in samples}
            if gene=='EMERGENT':
                values={s['file_name']:(np.nan if s['arm']=='vehicle' or s['arm']=='CuAB' and '60min' in s['condition'] else values[s['file_name']]) for s in samples}
            if gi==1 and si==0:values['AB_60_3']=np.nan
            pr.append({**base,'Precursor.Id':accession+'_'+seq,'Stripped.Sequence':seq,'Modified.Sequence':seq[:2]+'(UniMod:21)'+seq[2:],**values})
            for kinase in ['EGFR','SRC']:
                annotation.append({'enzyme':kinase,'substrate':accession,'residue_type':'S','residue_offset':sequence.index(seq)+2,
                    'modification':'phosphorylation','sources':'PhosphoSite','references':'synthetic_fixture_not_a_citation'})
    pd.DataFrame(pr).to_csv(directory/'PR.tsv',sep='\t',index=False);pd.DataFrame(pg).to_csv(directory/'PG.tsv',sep='\t',index=False)
    (directory/'reference.fasta').write_text(''.join(fasta));pd.DataFrame(annotation).to_csv(directory/'snapshot.tsv',sep='\t',index=False)
    sha=hashlib.sha256((directory/'snapshot.tsv').read_bytes()).hexdigest()
    metadata={'schema_version':'annotation_registry.v2','database_sha256':sha,'database':'Synthetic acceptance fixture',
        'source':'Software test fixture; not a biological annotation reference','version':'fixture.v1','retrieved_utc':'not_applicable_synthetic_fixture',
        'taxonomy_ids':['9606'],'ptm_types':['phosphorylation'],'orthology_translation':False,'id_system':'UniProt_accession_and_gene_symbol'}
    (directory/'annotation_metadata.json').write_text(json.dumps(metadata,indent=2))
    context={'quantitation_export_mode':'enrichment_free_timecourse.v3','annotation_mode':'required','annotation_snapshot_sha256':sha,
        'normalization_policy':'already_normalized.v1','enrichment_status':'enrichment_free','replication_declaration':'technical_per_condition',
        'pairing_policy':'unpaired','cell_type':'합성 fixture 세포 α','treatment':'AB / CuAB software fixture',
        'biological_question':'EGFR와 SRC의 탐색적 footprint를 비교하는 합성 검증',
        'special_conditions':'실제 biological 성능 검증이 아님','time_points':'0,60,180min',
        'acquisition':{'injection_volume':{'value':7,'unit':'µL','status':'provided','source':'synthetic_fixture'}},
        'processing':{'upstream_normalization':{'value':None,'status':'unknown'}},
        'validation_panel':{'genes':['GENA'],'selection_timing':'synthetic_predeclared_test_panel'},
        'temporal_windows':{'early':{'maximum_minutes':60},'late':{'minimum_minutes':180}}}
    result={'sample_config':{'samples':samples},'analysis_context':context}
    (directory/'fixture.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',default='http://127.0.0.1:8000/api');p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--prepare-only',action='store_true')
    args=p.parse_args();url=urlparse(args.base_url)
    if url.scheme!='http' or url.hostname!='127.0.0.1':p.error('Only an isolated localhost service is allowed')
    fixture=make_fixture(args.fixture)
    if args.prepare_only:return
    args.output.mkdir(parents=True,exist_ok=True)
    client=httpx.Client(base_url=args.base_url,timeout=180)
    login=client.post('/auth/login',json={'email':os.environ['PTM_TEST_EMAIL'],'password':os.environ['PTM_TEST_PASSWORD']});login.raise_for_status()
    client.headers['Authorization']='Bearer '+login.json()['access_token']
    events=[]
    def request(method,path,**kwargs):
        r=client.request(method,path,**kwargs);events.append({'method':method,'path':path,'status':r.status_code})
        if not r.is_success:raise AssertionError(f'{method} {path}: {r.status_code}: {r.text[:2000]}')
        return r.json()
    def wait(oid):
        deadline=time.monotonic()+900;previous=None
        while time.monotonic()<deadline:
            state=request('GET',f'/orders/{oid}')
            if state['status']!=previous:print(oid,state['status'],flush=True);previous=state['status']
            if state['status']=='completed':return request('GET',f'/orders/{oid}/enrichment-free-evidence')
            if state['status'] in {'failed','cancelled'}:raise AssertionError(state.get('error_message') or state['status'])
            time.sleep(2)
        raise TimeoutError('Local validation order did not finish')
    previews=request('POST','/orders/resolve-design',json={**fixture,'species':'human','ptm_type':'phosphorylation'})
    assert previews['study_design']['status']=='resolved',previews['study_design']['issues']
    name='Generic_acceptance_'+uuid4().hex[:8]
    with (args.fixture/'PR.tsv').open('rb') as pr,(args.fixture/'PG.tsv').open('rb') as pg:
        created=request('POST','/orders',data={'project_name':name,'ptm_type':'phosphorylation','species':'human',
            'sample_config':json.dumps(fixture['sample_config']),'analysis_context':json.dumps(fixture['analysis_context']),
            'analysis_options':json.dumps({'mode':'full','quick_analysis':False}),'report_options':'{}'},
            files={'pr_matrix':('PR.tsv',pr),'pg_matrix':('PG.tsv',pg)})
    oid=created['id'];request('POST',f'/orders/{oid}/start');original=wait(oid)
    def download(oid,label,record):
        r=client.get(f'/orders/{oid}/enrichment-free-evidence',params={'artifact':'astra'});r.raise_for_status()
        assert hashlib.sha256(r.content).hexdigest()==record['artifacts']['astra']['sha256']
        path=args.output/(label+'.zip');path.write_bytes(r.content)
        with zipfile.ZipFile(path) as archive:
            design=json.loads(archive.read('study_design.json'));ctx=json.loads(archive.read('study_context.json'))
            comparisons=pd.read_csv(archive.open('comparisons.csv'));profiles=pd.read_csv(archive.open('kinase_profiles.csv'))
            assert set(design['study']['original_context'])>={'cell_type','treatment','biological_question','special_conditions','time_points'}
            assert ctx['study']['acquisition']['injection_volume']['unit']=='µL'
            primary=comparisons.loc[comparisons.included]
            assert np.allclose(primary.A,primary.U_joint-primary.P_joint,atol=1e-10)
            assert set(profiles.entity)=={'EGFR','SRC'}
            assert profiles.loc[profiles['mode'].eq('primary_A') & profiles.target_label.str.startswith('AB ')].gene_balanced_mean.gt(0).all()
            assert profiles.loc[profiles['mode'].eq('primary_A') & profiles.target_label.str.startswith('CuAB ')].gene_balanced_mean.lt(0).all()
            assert len(pd.read_csv(archive.open('protein_contrasts.csv')))==20
        return comparisons,profiles
    initial_tables=download(oid,'original',original)
    copied=request('POST',f'/orders/{oid}/duplicate',json={'new_order_name':name+'_copy'});copy_id=copied['id']
    assert request('GET',f'/orders/{copy_id}')['analysis_context']==request('GET',f'/orders/{oid}')['analysis_context']
    request('POST',f'/orders/{copy_id}/start');copy=wait(copy_id);copy_tables=download(copy_id,'copy',copy)
    request('PATCH',f'/orders/{oid}',json={'analysis_context':{'biological_question':'다른 pathway를 기대해도 수치 계산은 동일해야 한다'}})
    assert request('GET',f'/orders/{oid}/enrichment-free-evidence')['provenance']==original['provenance']
    request('POST',f'/orders/{oid}/run-stage',json={'stage':'report_generation'});rerun=wait(oid);rerun_tables=download(oid,'rerun',rerun)
    for old,copy_frame,new in zip(initial_tables,copy_tables,rerun_tables):
        pd.testing.assert_frame_equal(old,copy_frame);pd.testing.assert_frame_equal(old,new)
    assert original['provenance']['study_context_sha256']!=rerun['provenance']['study_context_sha256']
    assert len({original['run_id'],copy['run_id'],rerun['run_id']})==3
    report={'passed':True,'order_id':oid,'copy_id':copy_id,'runs':[r['run_id'] for r in [original,copy,rerun]],
        'services':['FastAPI','MySQL','Redis','Celery'],'snapshot_sha256':fixture['analysis_context']['annotation_snapshot_sha256'],
        'copy_design_context_preserved':True,'prior_result_immutable':True,'question_does_not_change_scientific_tables':True,
        'download_checksums_verified':True,'multiarm_same_time_separated':True,'fixture_only_not_biological_validation':True,'events':events}
    (args.output/'validation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='events'},indent=2))


if __name__=='__main__':main()
