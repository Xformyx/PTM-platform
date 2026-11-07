import asyncio,json,sys
from pathlib import Path
from playwright.async_api import async_playwright,expect
if len(sys.argv)!=2:raise SystemExit('usage: validate_control_actual_browser.py VALIDATION_DIRECTORY')
OUT=Path(sys.argv[1])
expect.set_options(timeout=60000)
async def main():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
  page=await browser.new_page(viewport={'width':1440,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  # These ancillary endpoints are not part of the minimal API router. The
  # design, Order GET/PATCH, and submission resolver use real HTTP/MySQL.
  async def auxiliary(route):
   body={'collections':[]} if '/rag/' in route.request.url else []
   await route.fulfill(status=200,content_type='application/json',body=json.dumps(body))
  await page.route('**/api/rag/collections*',auxiliary);await page.route('**/api/sessions*',auxiliary)
  await page.goto('http://127.0.0.1:5197/tests/controlActual.browser.html?order=1')
  summary=page.get_by_label('입력 정보 요약',exact=True)
  await expect(summary).to_contain_text('공통 Control 기준')
  initial=json.loads(await page.get_by_label('Source context',exact=True).inner_text())
  await page.get_by_role('radio',name='시간대별 Control 기준 (Time-matched controls)',exact=True).check()
  await expect(summary).to_contain_text('같은 시간의 대응 Control이 없습니다.')
  failed=json.loads(await page.get_by_label('Source context',exact=True).inner_text())
  assert not failed['study_design']['contrasts']
  await page.get_by_role('radio',name='공통 Control 기준 (Shared control)',exact=True).check()
  await expect(summary).to_contain_text('공통 Control 기준')
  await page.get_by_role('button',name='Save actual draft',exact=True).click();await expect(page.get_by_role('status',name='Validation state')).to_have_text('saved')
  saved=json.loads(await page.get_by_label('Persisted order',exact=True).inner_text());design=saved['analysis_context']['study_design']
  assert saved['analysis_context']['control_comparison']['strategy']=='shared_reference'
  for key in ['injections','materials','replication_declaration']:assert design[key]==initial['study_design'][key],key
  assert len(design['injections'])==21 and len(design['contrasts'])==6
  assert all(c['pairing']=='unknown' for c in design['contrasts'])
  await page.reload();await expect(page.get_by_role('status',name='Validation state')).to_have_text('restored')
  await expect(page.get_by_role('radio',name='공통 Control 기준 (Shared control)',exact=True)).to_be_checked()
  await page.get_by_role('button',name='Open saved Astra summary',exact=True).click();dialog=page.get_by_role('dialog')
  await expect(dialog.get_by_label('입력 정보 요약')).to_contain_text('공통 Control 기준')
  assert await dialog.get_by_role('radio').count()==0
  assert await dialog.locator('input:visible,textarea:visible').count()==0
  await dialog.get_by_label('입력 정보 요약').screenshot(path=str(OUT/'actual-summary.png'))
  await dialog.get_by_role('button',name='입력 정보 수정',exact=True).click()
  await expect(dialog.get_by_role('radio',name='공통 Control 기준 (Shared control)',exact=True)).to_be_checked()
  # Save via the actual rerun payload merger, without dispatching here.
  await dialog.get_by_role('button',name='Astra 패키지 생성',exact=True).click();await expect(dialog).not_to_be_visible()
  restored=json.loads(await page.get_by_label('Persisted order',exact=True).inner_text())
  for key in ['injections','materials','contrasts']:assert restored['analysis_context']['study_design'][key]==design[key],key
  assert restored['report_options']['research_questions']==saved['report_options']['research_questions']
  (OUT/'UI_SAVED_ORDER.json').write_text(json.dumps(restored,ensure_ascii=False,indent=2))
  result={'passed':not errors,'page_errors':errors,'actual_input':True,'real_http':['resolve-design','Order GET','Order PATCH'],'ui_scope':'production StudyInputFields/SampleDesignFields/RerunOptionsModal in local validation shell; not production full application','ancillary_stubs':['rag collections listing','sessions listing'],'injections':21,'contrasts':6,'missing_time_matched_references':'all six targets unresolved; no fallback','biological_mapping_unchanged':True}
  (OUT/'UI_VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));await browser.close()
asyncio.run(main())
