"""Local UI validation against the real isolated HIRcB API and worker results."""
import argparse
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--order-id',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--url',default='http://127.0.0.1:5173')
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1100})
        errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(args.url+'/login')
        page.get_by_placeholder('Enter your email').fill('admin@ptm.local')
        page.get_by_placeholder('Enter your password').fill('local_validation_only')
        page.locator('button[type=submit]').click()
        page.wait_for_url(args.url+'/admin',timeout=30000)
        page.goto(args.url+f'/admin/orders/{args.order_id}')
        section=page.get_by_role('region',name='Primary A evidence')
        expect(section.get_by_role('heading',name='Primary A evidence')).to_be_visible(timeout=30000)
        expect(section.get_by_text('11,920',exact=True)).to_be_visible()
        expect(section.get_by_text('3,948',exact=True)).to_be_visible()
        expect(page.get_by_role('tab',name='Vector Plot',exact=True)).to_be_disabled()
        expect(page.get_by_text('Primary A evidence pipeline',exact=True)).to_be_visible()
        expect(page.get_by_text('RAG Enrichment',exact=True)).to_have_count(0)
        page.get_by_label('Candidate kinase / family').select_option('AKT_family')
        expect(section.get_by_text('coherent_increase',exact=True)).to_have_count(4)
        page.screenshot(path=str(args.output/'primary-a-evidence.png'),full_page=True)
        downloaded={}
        for button,key in [('Download primary A','primary_input'),('Download evidence report','report'),('Download Astra bundle','astra')]:
            with page.expect_download(timeout=60000) as download:
                section.get_by_role('button',name=button,exact=True).click()
            target=args.output/download.value.suggested_filename
            download.value.save_as(str(target))
            downloaded[key]={'filename':target.name,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
        page.get_by_role('button',name='Order Duplicate',exact=True).click()
        dialog=page.get_by_role('dialog')
        expect(dialog.get_by_label('Additional form evidence export')).to_have_value('enrichment_free_primary.v2')
        expect(dialog.get_by_label('Additional global normalization')).to_have_value('already_normalized.v1')
        expect(dialog.get_by_label('Frozen annotation snapshot')).to_have_value('80c9ae707a853169b6890a1e393f72f9f0b57edbf94e0c1e6f61dec57594de07')
        expect(dialog.get_by_label('Primary Control time in minutes')).to_have_value('0')
        expect(dialog.get_by_label('Primary 180min time in minutes')).to_have_value('180')
        expect(dialog.locator('input[aria-label^="Biological unit"]')).to_have_count(21)
        page.screenshot(path=str(args.output/'duplicate-settings.png'),full_page=True)
        assert not errors,errors
        result={'passed':True,'order_id':args.order_id,'page_errors':errors,'downloads':downloaded,
            'primary_A_default_tab':True,'legacy_vector_disabled':True,'copy_dialog_design_and_profile_preserved':True}
        (args.output/'validation.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
        browser.close()


if __name__=='__main__':main()
