"""Bounded local UI fixture: real shared resolver, mocked auxiliary HTTP only."""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect
from ptm_shared.study_execution import resolve_context
from ptm_shared.study_display import study_display


async def validate(url, output):
    output.mkdir(parents=True, exist_ok=True)
    calls = []; errors = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless=True)
        page = await browser.new_page(viewport={'width': 1360, 'height': 1100})
        page.on('pageerror', lambda error: errors.append(str(error)))
        async def api(route):
            request = route.request
            if request.url.endswith('/orders/resolve-design'):
                body = request.post_data_json
                cells = body['analysis_context'].get('cell_type')
                calls.append(cells)
                if cells == 'slow cells': await asyncio.sleep(.8)
                context = resolve_context(body['analysis_context'], body['sample_config'], taxonomy_id=9606, species=body['species'], ptm_type=body['ptm_type'])
                value = {'analysis_context': context, 'study_design': context['study_design'], 'study_display': study_display(context['study_design'],context), 'analysis_plan': {'source_execution': {'message': 'local fixture'}}}
            elif '/rag/collections' in request.url: value = {'collections': []}
            elif '/llm/models' in request.url: value = {'models': []}
            elif '/sessions' in request.url: value = []
            else: value = {}
            await route.fulfill(status=200, content_type='application/json', body=json.dumps(value))
        await page.route('**/api/**', api)
        await page.goto(url+'/tests/astraInputReuse.browser.html')
        summary = page.get_by_label('입력 정보 요약', exact=True)
        await expect(summary).to_contain_text('기준 조건: Control')
        await expect(summary).to_contain_text('90min vs Control')
        await expect(summary).to_contain_text('등록 반복: 조건별 2반복 · 총 4개 측정 파일')
        assert await summary.locator('select,input[type="text"],input[type="number"]').count() == 0
        await summary.screenshot(path=str(output/'initial-summary.png'))
        await summary.get_by_role('button', name='입력 정보 수정').click()
        await page.get_by_label('Original Cell Type', exact=True).fill('slow cells')
        await expect(summary).to_contain_text('최신 입력 정보를 반영')
        for _ in range(30):
            if 'slow cells' in calls: break
            await asyncio.sleep(.05)
        assert 'slow cells' in calls
        await page.get_by_label('Original Cell Type', exact=True).fill('latest cells')
        await expect(summary).to_contain_text('latest cells')
        await asyncio.sleep(1)
        await expect(summary).not_to_contain_text('slow cells')
        # Rename source conditions before saving, including the debounce window.
        await page.get_by_label('Condition t1', exact=True).fill('120min')
        await page.get_by_label('Condition t2', exact=True).fill('120min')
        await page.get_by_label('Original Time Points', exact=True).fill('0,120min')
        await page.get_by_role('button', name='Save draft', exact=True).click()
        await expect(page.get_by_label('Saved payload')).to_contain_text('120min')
        payload = json.loads(await page.get_by_label('Saved payload').inner_text())
        assert {c['label'] for c in payload['study_design']['conditions']} == {'Control', '120min'}
        await expect(summary).to_contain_text('120min vs Control')
        await expect(summary).not_to_contain_text('90min')
        # A complete manifest added after preview must reach the summary and payload.
        await page.get_by_text('추가 데이터 정보 / 해당 항목 수정 (선택)', exact=True).click()
        await page.get_by_text('기존 sample manifest 가져오기 / 수정', exact=True).click()
        manifest = {'schema_version': 'sample_manifest.v1', 'pairing': 'paired',
            'samples': [{'sample_id': sample, 'condition': 'Control' if sample.startswith('c') else '120min',
                         'biological_unit': sample[-1], 'technical_injection': '1'} for sample in ['c1','c2','t1','t2']],
            'conditions': [{'condition': 'Control', 'time_minutes': 0}, {'condition': '120min', 'time_minutes': 120}]}
        await page.get_by_label('Sample manifest JSON').fill(json.dumps(manifest))
        await page.get_by_label('Sample manifest JSON').press('Tab')
        await expect(summary).to_contain_text('4 material · 2 biological unit')
        await expect(summary).to_contain_text('Pairing: paired')
        await page.get_by_label('DIA-NN version', exact=True).fill('2.6.0')
        await expect(summary).to_contain_text('DIA-NN version: 2.6.0')
        await page.get_by_role('button', name='Open rerun', exact=True).click()
        dialog = page.get_by_role('dialog')
        await expect(dialog.get_by_label('입력 정보 요약')).to_contain_text('4 material · 2 biological unit')
        await expect(dialog.get_by_label('입력 정보 요약')).to_contain_text('Pairing: paired')
        await expect(dialog.get_by_text('연구 질문: saved writing intent', exact=True)).to_be_visible()
        assert await dialog.locator('input:visible,textarea:visible').count() == 0
        await dialog.screenshot(path=str(output/'rerun-summary.png'))
        await dialog.get_by_role('button', name='Astra 패키지 생성', exact=True).click()
        await expect(dialog).not_to_be_visible()
        payload = json.loads(await page.get_by_label('Saved payload').inner_text())
        assert payload['analysis_context']['science']['diann_version'] == '2.6.0'
        assert payload['analysis_context']['study_design']['study']['processing']['software_version']['value'] == '2.6.0'
        assert len(payload['analysis_context']['study_design']['materials']) == 4
        assert payload['rag_collections'] == []
        await page.get_by_role('button', name='Legacy fixture', exact=True).click()
        await expect(page.get_by_role('button', name='Match configured samples', exact=True)).to_be_visible()
        await expect(page.get_by_label('Primary comparison design')).to_have_value('paired')
        assert not errors, errors
        result = {'passed': True, 'resolve_requests': len(calls), 'latest_response_wins': True,
                  'manifest_after_preview': True, 'rename_no_stale_condition': True, 'rerun_readonly': True,
                  'legacy_inputs_preserved': True, 'scope': 'local_components_real_resolver_auxiliary_HTTP_mocked_no_execution', 'page_errors': errors}
        (output/'validation.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5193')
    parser.add_argument('--output', type=Path, default=Path('/tmp/ptm-astra-input-reuse-browser'))
    args = parser.parse_args()
    if urlparse(args.url).hostname != '127.0.0.1': parser.error('Only an isolated localhost fixture is supported')
    asyncio.run(validate(args.url, args.output))
