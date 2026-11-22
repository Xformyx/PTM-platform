"""Exercise production vector components with saved synthetic API responses."""
import argparse
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright


def canonical_fixture(directory):
    from ptm_shared.astra_package import write_tables
    from ptm_shared.astra_evidence_catalog import EvidenceCatalog, write_evidence_access
    from ptm_shared.generic_workflow import json_write
    from ptm_shared.substrate_signal_reader import write_signal_flow
    from test_substrate_signal_flow import fixture, kinase_fixture

    root,tables,design,registry=fixture(directory)
    kinase_fixture(tables,design,registry)
    json_write(root/'reproducibility/data_dictionary.json',write_tables(tables,root))
    write_evidence_access(root)
    write_signal_flow(root,tables)
    return EvidenceCatalog(root),json.loads((root/'provenance.json').read_text())['run_id']


def check(args, directory):
    from ptm_shared.substrate_signal_view import signal_page
    catalog,run_id=canonical_fixture(directory)
    fixture=json.loads((args.fixture/'responses.json').read_text())
    responses=fixture['responses']
    scatter=responses['/orders/1/vector-scatter-data?axis=adjusted']
    page_data=responses['/orders/1/vector-plot-data?mode=per_condition_top_n&n=50&axis=unadjusted']
    selected=[]
    errors=[]
    writes=[]
    def route(request):
        u=urlparse(request.request.url)
        path=u.path.removeprefix('/api')
        query=parse_qs(u.query)
        if path.endswith('vector-scatter-data'):
            data=scatter
        elif path.endswith('vector-plot-data'):
            data=page_data if query.get('axis')==['unadjusted'] else {**page_data,'top_n_ptms':[],'vector_data':[]}
        elif path.endswith('/feature-detail'):
            body=request.request.post_data_json
            assert body['measurement_revision']==scatter['measurement_revision']
            fid=body['options']['feature_id'];selected.append(fid)
            data=responses['detail/'+fid]
        elif path.endswith('/vector-plots'):
            data={'files':[]}
        elif path.endswith('/enrichment-free-evidence'):
            data={'run_id':run_id,'counts':{},'provenance':{'estimator_versions':{},'normalization':{}},'primary_profiles':[]}
        elif '/substrate-signal/' in path:
            body=request.request.post_data_json
            if 'canonical' in request.request.frame.url:
                assert body['expected_run_id']==run_id
                if path.rsplit('/',1)[-1]!='substrate_trajectories' or 'form_id' in body['filters']:
                    assert body['expected_catalog_id']==catalog.catalog['catalog_id']
                data={**signal_page(catalog,path.rsplit('/',1)[-1],body['filters'],body.get('cursor'),body['limit']),
                      'run_id':run_id}
            else:
                data={'status':'unavailable','reason':'legacy_fixture','items':[],'total_count':0,'next_cursor':None}
        elif '/evidence-runs' in path:
            data=responses.get(path,{'records':[],'next_cursor':None,'total_count':0})
            for k in ('feature_id','track','mode','n'):
                if k in query:
                    key=path+'?'+'&'.join(x+'='+query[x][0] for x in ('feature_id','track','mode','n') if x in query)
                    data=responses.get(key,data)
                    break
        elif path.endswith('global-kinase-modules'):
            assert request.request.post_data_json.get('_cache_probe') is True
            data={'kinase_modules':[],'summary':{'execution_status':'not_requested'},'_cached':False}
        elif path.endswith('vector-view/manifest'):
            return request.fulfill(status=409,json={'detail':'columnar_snapshot_unavailable'})
        else:
            if request.request.method!='GET': writes.append(path)
            data={}
        request.fulfill(json=data)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=args.browser,headless=True)
        try:
            page=browser.new_page(viewport={'width':1440,'height':950})
            page.set_default_timeout(8000)
            page.on('pageerror',lambda e:errors.append(e.stack))
            page.route('**/api/orders/**',route)
            entry=args.url+'/tests/vectorWorkspace.browser.html'
            page.goto(entry)
            panel=page.get_by_test_id('scatter-condition').first
            panel.get_by_text('원본 관측 선택',exact=True).click()
            panel.locator('li button:not([disabled])').first.click()
            exact=page.get_by_role('region',name='선택 기질')
            exact.wait_for()
            assert exact.locator('tbody tr').count()==len(responses['detail/'+selected[0]]['condition_grid'])
            observations=responses['detail/'+selected[0]]
            times=[point['time_minutes'] for point in observations['condition_grid']]
            assert len(set(b-a for a,b in zip(times,times[1:])))>1
            lines=exact.locator('.recharts-line')
            lines.nth(2).locator('path.recharts-line-curve').wait_for()
            path=lines.first.locator("path.recharts-line-curve").get_attribute("d")
            positions=[float(x) for x in re.findall(r"[ML]([-0-9.]+),",path)]
            assert len(positions)==len(times),(positions,times)
            for x,t in zip(positions,times):
                assert abs((x-positions[0])/(positions[-1]-positions[0])-(t-times[0])/(times[-1]-times[0]))<1e-5
            assert lines.nth(2).locator('path.recharts-line-curve').get_attribute('d').count('M')==2
            page.get_by_role('button',name='Independent PTM (U)',exact=True).click()
            page.get_by_test_id('top-n-setting').wait_for()
            page.get_by_role('button',name='Deselect All',exact=True).click()
            page.get_by_role('button',name='Select All',exact=True).wait_for()
            for width in [1440,1280,990,390]:
                page.set_viewport_size({'width':width,'height':900})
                try:
                    page.wait_for_function('document.documentElement.scrollWidth<=innerWidth',timeout=3000)
                except Exception:
                    print(page.evaluate("Array.from(document.querySelectorAll('*')).filter(e=>e.getBoundingClientRect().right>innerWidth+1 && !e.closest('table,pre,svg')).slice(0,16).map(e=>[e.tagName,e.className,e.offsetWidth])"))
                    raise
            page.get_by_role('button',name='이 precursor의 Kinase·경로 근거').click()
            page.get_by_text('같은 측정 revision의 precursor',exact=False).wait_for()
            page.get_by_text('선택 precursor:',exact=False).wait_for()
            widths=[1440,1280,990,390]
            for width in widths:
                page.set_viewport_size({'width':width,'height':900})
                page.get_by_role('tab',name='Kinase·경로 근거').focus()
                page.wait_for_function('document.documentElement.scrollWidth<=innerWidth',timeout=3000)
            page.goto(entry+'?canonical')
            page.get_by_role('region',name='전체 기질 기반 신호 흐름').wait_for()
            flow=page.get_by_role('region',name='전체 기질 기반 신호 흐름')
            flow.locator('li button').first.click()
            form=flow.get_by_role('region',name='Form 시간 반응 상세')
            form.get_by_role('button',name='K1 · curated_A',exact=True).click()
            form.get_by_role('region',name='Kinase substrate 근거').get_by_text('구별 불가 후보:',exact=False).wait_for()
            flow.get_by_role('button',name='검토 pin f',exact=True).click()
            with page.expect_download() as saved:
                flow.get_by_role('button',name='검토 pin과 원본 참조 내보내기').click()
            packet=json.loads(Path(saved.value.path()).read_text())
            assert packet['catalog_id']==catalog.catalog['catalog_id'] and packet['run_id']==run_id
            assert all(p['source_ref'] for p in packet['trajectories'][0]['points'])
            assert not writes and not errors,(writes,errors)
            print(json.dumps({'widths':widths,'feature_id':selected[0],'revision':scatter['measurement_revision'],
                              'empty_A_to_U':True,'canonical_run_binding':True,'canonical_pin_source_refs':True,'svg_time_spacing_and_gap':True,'console_exceptions':errors,'unexpected_posts':writes}))
        except Exception:
            print({'errors':errors,'writes':writes,'page':page.locator('body').inner_text()[:2400]}, flush=True)
            raise
        finally:
            browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--url',required=True)
    parser.add_argument('--browser',required=True)
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(root),str(root/'ptm_shared/tests')]
    with TemporaryDirectory() as directory:
        check(parser.parse_args(),Path(directory))
