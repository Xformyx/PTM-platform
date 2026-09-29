"""Render the package's existing SVGs in a local browser for visual review."""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--browser',required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    figures=sorted((a.package/'figures').glob('*.svg'));errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=a.browser,headless=True)
        page=browser.new_page(viewport={'width':1200,'height':800})
        page.on('pageerror',lambda e:errors.append(str(e)))
        for svg in figures:
            page.set_content('<meta charset="utf-8"><style>body{margin:0;background:white}svg{width:100%;height:auto}</style>'+svg.read_text())
            page.locator('svg').screenshot(path=str(a.output/(svg.stem+'.png')))
        browser.close()
    assert figures and not errors,errors
    (a.output/'render_validation.json').write_text(json.dumps({'rendered_figures':len(figures),'browser_errors':errors,'visual_review':'separate_manual_inspection_required'},indent=2))


if __name__=='__main__':main()
