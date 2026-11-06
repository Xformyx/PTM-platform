"""Local C01 UI checks with the actual common resolver; no execution or DB."""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from ptm_shared.study_execution import resolve_context
from ptm_shared.study_display import study_display


async def validate(args):
    args.output.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1200});errors=[];requests=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def api(route):
            if route.request.url.endswith('/orders/resolve-design'):
                body=route.request.post_data_json;requested=body['analysis_context'].get('control_comparison') or {}
                requests.append(requested)
                if requested.get('strategy')=='shared_reference':await asyncio.sleep(.8)
                context=resolve_context(body['analysis_context'],body['sample_config'],taxonomy_id=9606,species='human')
                value={'analysis_context':context,'study_design':context['study_design'],'study_display':study_display(context['study_design'],context)}
            elif '/rag/collections' in route.request.url:value={'collections':[]}
            elif '/sessions' in route.request.url:value=[]
            else:value={}
            await route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
        await page.route('**/api/**',api)
        await page.goto(args.url+'/tests/controlComparison.browser.html')
        summary=page.get_by_label('입력 정보 요약',exact=True)
        await expect(summary).to_contain_text('Control 비교 방식: 시간대별 Control 기준')
        await expect(summary).to_contain_text('자동 판정된 제안')
        await expect(summary).to_contain_text('조건별 3반복 · 총 15개 측정 파일')
        radios=page.get_by_role('group',name='Control 비교 방식',exact=True)
        assert await radios.get_by_role('radio').count()==2
        shared=radios.get_by_role('radio',name='공통 Control 기준 (Shared control)',exact=True)
        matched=radios.get_by_role('radio',name='시간대별 Control 기준 (Time-matched controls)',exact=True)
        await expect(matched).to_be_checked()
        before=json.loads(await page.get_by_label('Source context',exact=True).inner_text())
        await page.locator('summary').filter(has_text='Control 직접 연결').click()
        assert json.loads(await page.get_by_label('Source context',exact=True).inner_text())==before
        targets=before['study_design']['control_comparison']['assignments']
        refs=before['study_design']['conditions'];zero=next(c['condition_id'] for c in refs if c['label']=='Control 0min');thirty=next(c['condition_id'] for c in refs if c['label']=='Control 30min')
        await page.get_by_label('직접 연결 '+targets[0]['target_condition_id'],exact=True).select_option(zero)
        await page.get_by_role('button',name='직접 연결 적용',exact=True).click()
        await expect(summary).to_contain_text('Control 비교 방식: Control 직접 연결')
        await expect(shared).not_to_be_checked();await expect(matched).not_to_be_checked()
        await expect(page.get_by_text('비교 기준이 변경되었습니다. 기존 결과는 유지되며, 새 기준은 다음 분석 실행에 적용됩니다.',exact=True)).to_be_visible()
        await page.get_by_role('button',name='Save draft',exact=True).click()
        await expect(page.get_by_label('Saved payload',exact=True)).to_contain_text('explicit_custom')
        saved=json.loads(await page.get_by_label('Saved payload',exact=True).inner_text())
        assert saved['control_comparison']['mappings'][targets[0]['target_condition_id']]==zero
        await page.get_by_role('button',name='Open rerun',exact=True).click()
        dialog=page.get_by_role('dialog');await expect(dialog.get_by_label('입력 정보 요약')).to_contain_text('Control 직접 연결')
        assert await dialog.locator('input:visible,textarea:visible').count()==0
        await dialog.get_by_role('button',name='입력 정보 수정',exact=True).click()
        await expect(dialog.get_by_text('현재 방식: Control 직접 연결',exact=True)).to_be_visible()
        assert await dialog.get_by_role('radio').count()==2
        assert await dialog.get_by_role('radio').evaluate_all('(rows)=>rows.every(r=>!r.checked)')
        await dialog.get_by_role('button',name='Astra 패키지 생성',exact=True).click();await expect(dialog).not_to_be_visible()
        await shared.click();await page.get_by_label('공통 Control',exact=True).select_option(thirty)
        await expect(summary).to_contain_text('Control 비교 방식: 공통 Control 기준')
        await expect(page.get_by_text('지정 Control 대비 변화',exact=True)).to_be_visible()
        await expect(page.get_by_text('시작 시점 대비 변화',exact=True)).not_to_be_visible()
        current=json.loads(await page.get_by_label('Source context',exact=True).inner_text())
        assert {c['reference_condition_id'] for c in current['study_design']['contrasts']}=={thirty}
        # Start a slow request, then keyboard-select the latest policy.
        await page.get_by_label('공통 Control',exact=True).select_option(zero)
        for _ in range(40):
            if requests[-1].get('reference_condition_id')==zero:break
            await asyncio.sleep(.05)
        assert requests[-1].get('reference_condition_id')==zero
        await shared.focus();await page.keyboard.press('ArrowRight')
        await expect(matched).to_be_checked();await expect(summary).to_contain_text('Control 비교 방식: 시간대별 Control 기준')
        await asyncio.sleep(1)
        await expect(matched).to_be_checked();await expect(summary).to_contain_text('Control 비교 방식: 시간대별 Control 기준')
        final=json.loads(await page.get_by_label('Source context',exact=True).inner_text())
        for key in ['injections','materials','replication_declaration']:
            assert final['study_design'][key]==before['study_design'][key]
        assert all(c['pairing']=='unpaired' for c in final['study_design']['contrasts'])
        await summary.screenshot(path=str(args.output/'matched-summary.png'))
        await page.get_by_role('button',name='Remove 30min Control',exact=True).click()
        await expect(summary).to_contain_text('Drug 0.5h: 같은 시간의 대응 Control이 없습니다.')
        await page.get_by_role('button',name='Save draft',exact=True).click()
        await expect(page.get_by_label('Saved payload',exact=True)).to_contain_text('matched_reference_missing')
        assert not errors,errors
        result={'passed':True,'page_errors':errors,'resolve_calls':len(requests),'scope':'synthetic_UI_real_resolver_no_execution'}
        (args.output/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
        await browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',default='http://127.0.0.1:5193');parser.add_argument('--output',type=Path,default=Path('/tmp/ptm-control-ui'))
    args=parser.parse_args()
    if urlparse(args.url).hostname!='127.0.0.1':parser.error('Only isolated localhost fixtures are supported')
    asyncio.run(validate(args))
