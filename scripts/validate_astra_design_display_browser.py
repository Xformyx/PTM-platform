"""Local synthetic display only; actual resolver, no order DB or scientific run."""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright, expect
from ptm_shared.study_execution import resolve_context


async def validate(args):
    args.output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        page=await browser.new_page(viewport={'width':1360,'height':1200});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def api(route):
            if route.request.url.endswith('/orders/resolve-design'):
                body=route.request.post_data_json
                context=resolve_context(body['analysis_context'],body['sample_config'],taxonomy_id=9606,species=body['species'],ptm_type=body['ptm_type'])
                result={'analysis_context':context,'study_design':context['study_design']}
                if not args.before:
                    from ptm_shared.study_display import study_display
                    result['study_display']=study_display(context['study_design'],context)
            elif '/rag/collections' in route.request.url:result={'collections':[]}
            elif '/sessions' in route.request.url:result=[]
            else:result={}
            await route.fulfill(status=200,content_type='application/json',body=json.dumps(result))
        await page.route('**/api/**',api)
        await page.goto(args.url+'/tests/astraDesignDisplay.browser.html')
        summary=page.get_by_label('입력 정보 요약',exact=True)
        await expect(summary).to_contain_text('기준 조건: Control')
        if args.before:
            await expect(summary).to_contain_text('미기록 — descriptive 분석 · 18 injection')
            await expect(summary).to_contain_text('Biological Question')
        else:
            await expect(summary).to_contain_text('등록 반복: 조건별 3반복 · 총 18개 측정 파일')
            await expect(summary).to_contain_text('Biological Design')
            await expect(summary).not_to_contain_text('Biological Question')
        await summary.screenshot(path=str(args.output/('before.png' if args.before else 'after.png')))
        if not args.before:
            await summary.get_by_text('반복 번호·주입·유형 상세',exact=True).click()
            detail=summary.locator('details').filter(has=page.get_by_text('반복 번호·주입·유형 상세',exact=True))
            await expect(detail).to_contain_text('반복 유형: 미지정')
            await expect(detail).to_contain_text('0 material · 0 biological unit · 18 injection')
            for label in ['Control','0.5h','1h','3h','6h','24h']:
                row=detail.get_by_role('row').filter(has=page.get_by_role('cell',name=label,exact=True))
                await expect(row).to_contain_text('1, 2, 3')
                assert await row.get_by_role('cell').all_text_contents()==[label,'1, 2, 3','3','3','3','미기록','']
            await detail.screenshot(path=str(args.output/'after-detail.png'))
            await summary.get_by_role('button',name='입력 정보 수정',exact=True).click()
            field=page.get_by_label('Biological Design',exact=True)
            original='  모델 α · 처리 및 시간 계획\n반복 설계와 분석 목적 원문  '
            await expect(field).to_have_value(original)
            await page.get_by_role('button',name='Astra 패키지 생성',exact=True).click()
            await expect(page.get_by_role('dialog')).not_to_be_visible()
            saved=json.loads(await page.get_by_label('Saved payload').inner_text())
            assert saved['analysis_context']['biological_question']==original
            assert saved['report_options']['research_questions']==['별도 연구 질문 그대로']
            assert 'sample_config' not in saved
        assert not errors,errors
        (args.output/('before.json' if args.before else 'validation.json')).write_text(json.dumps({'passed':True,'before':args.before,'synthetic_files':18,'page_errors':errors},indent=2))
        print(json.dumps({'passed':True,'before':args.before,'page_errors':errors}))
        await browser.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:5193')
    p.add_argument('--output',type=Path,default=Path('/tmp/ptm-astra-design-display-browser'));p.add_argument('--before',action='store_true')
    args=p.parse_args()
    if urlparse(args.url).hostname!='127.0.0.1':p.error('Only isolated localhost fixtures are supported')
    asyncio.run(validate(args))
