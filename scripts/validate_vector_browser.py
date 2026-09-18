"""Browser scale smoke over an existing synthetic scale artifact. Requires Playwright and a browser executable."""
import sys,json,time
from pathlib import Path
from playwright.sync_api import sync_playwright
from ptm_shared.vector_columnar import VectorColumnar
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--artifact-dir',type=Path,required=True)
parser.add_argument('--bundle',type=Path,required=True)
parser.add_argument('--browser',required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=False)
store=VectorColumnar(args.artifact_dir,'_phospho')
expected=store.density(condition=store.manifest_counts()['conditions'][0])['count']
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=args.browser,headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 methods={'manifest':store.manifest_counts,'density':store.density,'coordinates':store.coordinate_page,'distribution':store.distribution,'features':store.feature_page,'trajectories':store.trajectories}
 responses=[]
 def route(r):
  operation=r.request.url.split('/vector-view/')[-1].split('?')[0]
  if operation in methods:
   start=time.perf_counter();data=methods[operation](**((r.request.post_data_json or {}).get('options') or {}));encoded=json.dumps(data);responses.append({'operation':operation,'bytes':len(encoded.encode()),'seconds':time.perf_counter()-start});return r.fulfill(content_type='application/json',body=encoded)
  return r.fulfill(content_type='text/html',body='<html><body><div id="root" style="width:1300px"></div></body></html>')
 page.route('**/*',route);page.goto('http://fixture.local/?view=density');page.add_script_tag(path=str(args.bundle))
 page.get_by_text('정확한 좌표 조회',exact=True).wait_for();page.wait_for_function("n => document.body.innerText.includes(String(n))",arg=expected,timeout=30000)
 t=time.perf_counter();page.get_by_text('정확한 좌표 조회',exact=True).click();page.get_by_text('정확한 관측 200개 (현재 페이지)',exact=True).wait_for();drill=time.perf_counter()-t
 canvas=page.locator('canvas');box=canvas.bounding_box();t=time.perf_counter();page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.get_by_text('Protein log2FC',exact=False).first.wait_for();hover=time.perf_counter()-t
 page.screenshot(path=str(root/'density.png'),full_page=True)
 cdp=page.context.new_cdp_session(page);heap=cdp.send('Runtime.getHeapUsage')
 result={'source_rows':store.manifest_counts()['source_rows'],'heap':heap,'dom_elements':page.locator('*').count(),'drill_seconds':drill,'hover_event_seconds':hover,'responses':responses,'errors':errors,'browser':browser.version}
 print(json.dumps(result));(root/'browser-scale-result.json').write_text(json.dumps(result,indent=2));assert not errors
 browser.close();store.close()
