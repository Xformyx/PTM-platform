"""Real local UI acceptance plus explicit annotation HTTP fault injection."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from playwright.sync_api import sync_playwright,expect


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--order-id',type=int,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--url',default='http://127.0.0.1:5173')
    args=p.parse_args()
    if urlparse(args.url).hostname!='127.0.0.1':p.error('Only an isolated local UI is supported')
    args.output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(args.url+'/login');page.get_by_placeholder('Enter your email').fill(os.environ['PTM_TEST_EMAIL'])
        page.get_by_placeholder('Enter your password').fill(os.environ['PTM_TEST_PASSWORD']);page.locator('button[type=submit]').click()
        page.wait_for_url(args.url+'/admin');page.goto(args.url+f'/admin/orders/{args.order_id}')
        section=page.get_by_role('region',name='Primary A evidence')
        expect(section.get_by_role('heading',name='Primary A evidence')).to_be_visible(timeout=30000)
        page.get_by_label('Candidate kinase / family').select_option('EGFR')
        expect(section.get_by_text('AB 60min / vehicle 0min (60)',exact=True)).to_be_visible()
        expect(section.get_by_text('CuAB 60min / vehicle 0min (60)',exact=True)).to_be_visible()
        section.screenshot(path=str(args.output/'generic-evidence.png'))
        with page.expect_download() as download:section.get_by_role('button',name='Download Astra bundle',exact=True).click()
        target=args.output/download.value.suggested_filename;download.value.save_as(str(target))
        recorded=re.search(r'Recorded run: (\S+)',section.inner_text()).group(1)
        page.get_by_role('tab',name='Results',exact=True).click()
        expect(page.get_by_text(f'enrichment_free_{recorded}.zip',exact=True)).to_be_visible(timeout=30000)
        page.get_by_role('tab',name='Primary A evidence',exact=True).click()
        page.get_by_role('button',name='Order Duplicate',exact=True).click();dialog=page.get_by_role('dialog')
        expect(dialog.get_by_text('Review imported study design',exact=True)).to_be_visible()
        expect(dialog.get_by_label('Time AB 60min',exact=True)).to_have_value('60')
        expect(dialog.get_by_label('Time CuAB 60min',exact=True)).to_have_value('60')
        expect(dialog.get_by_label('Replication declaration')).to_have_count(0)
        expect(dialog.get_by_label('Annotation analysis')).to_have_value('required')
        expect(dialog.get_by_label('Frozen annotation snapshot')).not_to_have_value('')
        dialog.get_by_text('Optional acquisition and processing information',exact=True).click()
        expect(dialog.get_by_label('injection_volume',exact=True)).to_have_value('7')
        expect(dialog.get_by_label('injection_volume unit',exact=True)).to_have_value('µL')
        dialog.get_by_text('Optional acquisition and processing information',exact=True).click()
        dialog.screenshot(path=str(args.output/'imported-study-design.png'))
        # Same actual UI component, explicitly injected HTTP failure states.
        scenarios=[('unauthorized',401,{},'Annotation lookup requires an authorized session.'),
            ('server_error',500,{},'Annotation service could not read the registry.'),
            ('network_error',0,{},'Annotation lookup failed because the server could not be reached.'),
            ('metadata_invalid',200,{'snapshots':None},'Registry metadata could not be validated.'),
            ('empty_registry',200,{'status':'empty_registry','snapshots':[]},'No annotation is registered.'),
            ('incompatible',200,{'status':'no_compatible_snapshot','snapshots':[{'sha256':'a'*64,'status':'incompatible','reasons':['taxonomy_not_supported']}]},'No compatible annotation is available'),
            ('checksum_invalid',200,{'status':'no_compatible_snapshot','snapshots':[{'sha256':'a'*64,'status':'checksum_invalid','reasons':['checksum_invalid']}]},'checksum_invalid')]
        for name,status,body,text in scenarios:
            dialog.get_by_label('Annotation analysis').select_option('quantification_only')
            page.route('**/api/orders/frozen-annotations?*',lambda route,request,status=status,body=body:route.abort() if status==0 else route.fulfill(status=status,json=body))
            dialog.get_by_label('Annotation analysis').select_option('required')
            expect(dialog.locator('p').filter(has_text=text).first).to_be_visible(timeout=10000)
            page.unroute('**/api/orders/frozen-annotations?*')
        dialog.get_by_label('Annotation analysis').select_option('quantification_only')
        dialog.get_by_label('Annotation analysis').select_option('required')
        expect(dialog.get_by_label('Frozen annotation snapshot')).not_to_have_value('')
        dialog.get_by_placeholder('Enter new order name').fill('Generic_UI_copy_'+uuid4().hex[:8])
        dialog.get_by_role('button',name='Create Duplicate',exact=True).click()
        page.wait_for_url(lambda url:str(url).startswith(args.url+'/admin/orders/') and not str(url).endswith('/'+str(args.order_id)),timeout=30000)
        copy_id=int(page.url.rsplit('/',1)[-1]);page.get_by_role('button',name='Start Analysis',exact=True).click()
        section=page.get_by_role('region',name='Primary A evidence')
        expect(section.get_by_role('button',name='Download Astra bundle')).to_be_visible(timeout=180000)
        old_run=re.search(r'Recorded run: (\S+)',section.inner_text()).group(1)
        page.get_by_role('button',name='Re-run from Beginning',exact=True).click()
        confirm=page.get_by_role('dialog');expect(confirm.get_by_label('Time AB 60min',exact=True)).to_have_value('60')
        confirm.get_by_role('button',name='Confirm & Re-run Primary A evidence',exact=True).click()
        expect(section.locator('p').filter(has_text='Recorded run:')).not_to_contain_text(old_run,timeout=180000)
        assert not errors,errors
        record={'passed':True,'order_id':args.order_id,'ui_copy_order_id':copy_id,'page_errors':errors,
            'download_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'imported_design_preserved':True,
            'results_data_files_same_run_zip':True,
            'replication_not_reasked':True,'volume_unit_preserved':True,'same_time_arms_visible_separately':True,
            'snapshot_fault_injection_states':[s[0] for s in scenarios],'ui_copy_start_and_rerun_completed':True}
        (args.output/'validation.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2));browser.close()


if __name__=='__main__':main()
