"""Actual chart/kinase/virtual heatmap browser regression over synthetic API responses."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import argparse,shutil
parser=argparse.ArgumentParser()
parser.add_argument('--fixture-dir',type=Path,required=True)
parser.add_argument('--bundle',type=Path,required=True)
parser.add_argument('--css',type=Path,required=True)
parser.add_argument('--browser',required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=False)
for name in ('response.json','job-response.json','job-vector-response.json','job-members-response.json','response_global_1.json','response_global_2.json','response_global_50.json'):
 shutil.copyfile(args.fixture_dir/name,root/name)
shutil.copyfile(args.bundle,root/'browser.js')
fixture=json.loads((root/'response.json').read_text())
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=args.browser,headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1200}); errors=[]
 page.on('pageerror',lambda error:errors.append(str(error)))
 def route(r):
  url=r.request.url
  if '/vector-plot-data' in url: return r.fulfill(json=fixture)
  if '/api/orders/1' in url: return r.fulfill(json={'kinase_modules':[],'ip_overlay_data':None,'summary':{}})
  return r.fulfill(content_type='text/html',body='<html><body><div id="root" style="width:1380px;height:1100px"></div></body></html>')
 page.route('**/*',route);page.goto('http://fixture.local/')
 page.add_script_tag(path=str(root/'browser.js'))
 page.get_by_test_id('top-n-setting').wait_for()
 page.locator('.recharts-wrapper').first.wait_for()
 page.screenshot(path=str(root/'chart.png'),full_page=True)
 dots=page.locator('.recharts-line-dots circle').count()
 summary={'setting':page.get_by_test_id('top-n-setting').inner_text(),'dots':dots,'errors':errors,'lines':page.locator('.recharts-line').count()}
 (root/'browser-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
 print(json.dumps(summary,ensure_ascii=False))
 assert not errors
 assert dots==5, f'expected all 5 finite observations, got {dots}'
 paths=page.locator('.recharts-line-curve').evaluate_all('(xs)=>xs.map(x=>x.getAttribute("d"))')
 # A missing middle observation must not produce a connecting segment.
 assert sum(('L' in path or 'C' in path) for path in paths if path)==1, paths
 box=page.locator('input[type=checkbox]').first;box.uncheck()
 page.wait_for_function("document.querySelectorAll('.recharts-line-dots circle').length < 5")
 box.check()
 page.wait_for_function("document.querySelectorAll('.recharts-line-dots circle').length === 5")
 summary.update(gap_paths=paths, checkbox_preserves_selection=True)
 (root/'browser-result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
 page2=browser.new_page(viewport={'width':1440,'height':1200});kinase_errors=[]
 page2.on('pageerror',lambda e:kinase_errors.append(str(e)))
 data=json.loads((root/'job-response.json').read_text());vectors=json.loads((root/'job-vector-response.json').read_text())
 page2.add_init_script('window.fixture='+json.dumps(vectors))
 def job_route(r):
  if 'global-kinase-modules' in r.request.url or 'kinase-activity-heatmap' in r.request.url:return r.fulfill(json=data)
  if '/inventory' in r.request.url:return r.fulfill(json=json.loads((root/'job-members-response.json').read_text()))
  if '/api/' in r.request.url:return r.fulfill(json={})
  return r.fulfill(content_type='text/html',body='<div id="root" style="width:1300px"></div>')
 page2.route('**/*',job_route);page2.goto('http://fixture.local/?view=kinase');page2.add_script_tag(path=str(root/'browser.js'))
 page2.get_by_role('button',name='Kinase Modules',exact=False).first.wait_for()
 page2.get_by_role('button',name='Kinase Modules',exact=False).first.click()
 page2.get_by_role('button',name='K1 · 후보 4',exact=True).click()
 page2.wait_for_function("document.querySelectorAll('[data-testid=paged-kinase-modules] details').length===4")
 page2.get_by_role('button',name='Heatmap',exact=False).first.click()
 page2.get_by_text('K1',exact=True).first.wait_for()
 page2.screenshot(path=str(root/'kinase.png'),full_page=True)
 print(json.dumps({'kinase_browser_errors':kinase_errors,'kinase_body':page2.locator('body').inner_text()[:1000]}))
 assert not kinase_errors
 page3=browser.new_page(viewport={'width':1440,'height':900})
 virtual_errors=[];page3.on('pageerror',lambda e:virtual_errors.append(str(e)))
 synthetic={'conditions':[f'{i}min' for i in range(80)],'rows':[{'kinase':f'fixture_{i}','scores':{f'{j}min':(None if j==40 else 0 if i==499 else i-j) for j in range(80)}} for i in range(500)]}
 page3.add_init_script('window.fixture='+json.dumps(synthetic));page3.route('**/*',lambda r:r.fulfill(content_type='text/html',body='<div id="root"></div>'))
 page3.goto('http://fixture.local/?view=virtual');page3.add_script_tag(path=str(root/'browser.js'))
 page3.add_style_tag(path=str(args.css))
 page3.get_by_test_id('virtual-score-heatmap').wait_for()
 viewport=page3.locator('[data-testid=virtual-score-heatmap] > div').first
 viewport.evaluate('(e)=>{e.scrollTop=e.scrollHeight;e.scrollLeft=e.scrollWidth;}')
 page3.wait_for_timeout(200)
 page3.screenshot(path=str(root/'virtual-heatmap.png'),full_page=True)
 page3.get_by_role('button',name='fixture_499',exact=True).wait_for(timeout=2000)
 page3.get_by_role('button',name='fixture_499',exact=True).click()
 assert '"79min": 0' in page3.locator('pre').inner_text()
 assert '"40min": null' in page3.locator('pre').inner_text()
 # Every synthetic trajectory has a missing condition at column 40.
 # The base Canvas must have no painted pixels at that x coordinate.
 missing_column=page3.locator('canvas').first.evaluate("e=>{const x=Math.round(20+40/79*1160),pixels=e.getContext('2d').getImageData(x,0,1,400).data;let n=0;for(let i=3;i<pixels.length;i+=4)n+=pixels[i]>0;return n;}")
 assert missing_column==0
 assert not errors
 virtual={'source_cells':40000,'dom_elements':page3.locator('*').count(),'tail_zero_and_null_preserved':True,'canvas_missing_column_painted_pixels':missing_column,'errors':virtual_errors}
 assert virtual['dom_elements']<1000 and not virtual_errors
 (root/'virtual-heatmap-result.json').write_text(json.dumps(virtual,indent=2));print(json.dumps(virtual))
 browser.close()
