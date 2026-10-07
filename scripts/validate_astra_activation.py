"""Round 01: normal v5 UI request -> flag-enabled API -> immutable v6 package.

Only isolated localhost services are accepted. Credentials are read from the same
PTM_TEST_* environment contract as validate_astra_platform.py. No production
orders, feature flags, estimator, figure policy or source pins are modified.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse
from uuid import uuid4
import zipfile

import httpx
import pandas as pd


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(directory, name, value):
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def package_contract(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        read = lambda name: json.loads(z.read(name))
        context = read('study/study_context.json')
        context = context.get('experimental_context', context)
        return {
            'run_id': read('provenance.json')['run_id'],
            'context': context['quantitation_export_mode'],
            'plan': read('study/analysis_plan.json')['profile'],
            'provenance': read('provenance.json')['analysis_profile'],
            'schema': read('provenance.json')['schema_version'],
            'replay': read('reproducibility/replay_config.json')['engine_profile'],
            'input_sha256': {name: sha(z.read(name)) for name in ('inputs/PR.tsv', 'inputs/PG.tsv', 'inputs/reference.fasta')},
            'source_pin_sha256': sha(z.read('references/source_pin.json')),
            'recorded_source_pin_sha256': read('references/source_pin.json').get('pin_sha256'),
            'source_acquisition_policy': read('references/source_pin.json').get('acquisition_policy'),
            'required_v6_files': {name: name in z.namelist() for name in (
                'science/localization_by_contrast.csv', 'science/inference_results.csv',
                'study/input_lineage.csv', 'methods/method_registry.json')},
            'archive_sha256': sha(data),
        }


def compare_quant(before, after):
    checks = []
    with zipfile.ZipFile(before) as a, zipfile.ZipFile(after) as b:
        names = sorted(n for n in a.namelist() if n.startswith('quant/') and n.endswith('.csv'))
        assert len(names) == 22, 'Record a changed contract instead of silently reducing the comparison universe'
        for name in names:
            left, right = pd.read_csv(a.open(name)), pd.read_csv(b.open(name))
            assert left.columns.tolist() == right.columns.tolist(), name
            pd.testing.assert_frame_equal(left.isna(), right.isna(), check_exact=True)
            # IDs/text are compared exactly; floating values alone have tolerance.
            numeric = left.select_dtypes(include='number').columns
            pd.testing.assert_frame_equal(left.drop(columns=numeric), right.drop(columns=numeric), check_exact=True)
            pd.testing.assert_frame_equal(left[numeric], right[numeric], check_exact=False, atol=1e-10, rtol=1e-10)
            checks.append({'table': name, 'rows': len(left), 'ids_text_na_equal': True,
                           'numeric_equal_atol_rtol_1e_10': True, 'byte_equal': a.read(name) == b.read(name)})
    return checks


def dispatch_record(order_id):
    """Read only allowlisted fields of this test's late-acked local task."""
    from redis import Redis
    url = os.environ.get('CELERY_BROKER_URL', '')
    if urlparse(url).hostname not in {'127.0.0.1', 'localhost'}:
        raise ValueError('Dispatch audit requires the isolated localhost broker')
    with Redis.from_url(url) as broker:
        for raw in broker.hvals('unacked'):
            message, *_ = json.loads(raw)
            try:
                args, _, *_ = json.loads(base64.b64decode(message['body']))
            except (ValueError, TypeError, KeyError):
                continue
            if len(args) < 2 or args[0] != order_id or not isinstance(args[1], dict):
                continue
            config = args[1]
            return {'order_id': order_id, 'task_id': message['headers']['id'],
                    'dispatch_mode': config.get('experimental_context', {}).get('quantitation_export_mode'),
                    'source_pin_sha256': config.get('source_pin_sha256'),
                    'species_tax_id': config.get('species_tax_id'),
                    'inspection': 'own_isolated_broker_unacked_message_allowlisted_fields'}
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['create', 'wait', 'rerun', 'results', 'compare'])
    p.add_argument('--base-url', required=True)
    p.add_argument('--ui-url', default='http://127.0.0.1:5178')
    p.add_argument('--archive', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--label', choices=['v5', 'v6'], default='v5')
    p.add_argument('--draft-only', action='store_true', help='Verify create persistence without scheduling another full run')
    args = p.parse_args()
    for url in (args.base_url, args.ui_url):
        if urlparse(url).scheme != 'http' or urlparse(url).hostname != '127.0.0.1':
            p.error('Only isolated localhost validation is allowed')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.phase == 'compare':
        checks = compare_quant(args.output/'v5.zip', args.output/'v6.zip')
        before, after = [package_contract((args.output/(v+'.zip')).read_bytes()) for v in ('v5', 'v6')]
        assert before['archive_sha256'] == json.loads((args.output/'v5-contract.json').read_text())['archive_sha256']
        assert all(before[k] == 'astra_analysis.v5' for k in ('context', 'plan', 'provenance', 'replay'))
        assert before['input_sha256'] == after['input_sha256']
        assert before['source_pin_sha256'] == after['source_pin_sha256']
        assert before['recorded_source_pin_sha256'] == after['recorded_source_pin_sha256']
        assert before['run_id'] != after['run_id']
        assert all(after[k] == 'astra_analysis.v6' for k in ('context', 'plan', 'provenance', 'replay'))
        assert all(after['required_v6_files'].values())
        write(args.output, 'validation.json', {'passed': True, 'before': before, 'after': after,
              'quant': checks, 'scope': 'normal_UI_activation_same_inputs_and_pin_not_annotation_refresh'})
        print(json.dumps({'passed': True, 'run_ids': [before['run_id'], after['run_id']], 'quant_tables': len(checks)}))
        return
    client = httpx.Client(base_url=args.base_url, timeout=600)
    response = client.post('/auth/login', json={'email': os.environ['PTM_TEST_EMAIL'], 'password': os.environ['PTM_TEST_PASSWORD']})
    response.raise_for_status(); client.headers['Authorization'] = 'Bearer '+response.json()['access_token']
    def request(method, route, **kwargs):
        response = client.request(method, route, **kwargs); response.raise_for_status(); return response.json()
    if args.phase == 'create':
        with zipfile.ZipFile(args.archive) as z:
            saved = json.loads(z.read('reproducibility/replay_config.json'))
            original = saved['snapshot']['original']; context = saved['context']
            pin = sha(z.read('references/source_pin.json'))
            # Stored upload paths belong to the old order. Re-upload included
            # attachments with their original bytes through the normal API.
            context.pop('research_attachment_records', None)
            context.update(quantitation_export_mode='astra_analysis.v5', refresh_references=False, astra_source_pin_sha256=pin)
            # Use the actual frontend helper, rather than a hand-written v6 request.
            helper = (Path(__file__).resolve().parents[1]/'frontend/src/lib/analysisContext.ts').as_uri()
            code = 'import {withPersistedExportMode} from '+json.dumps(helper)+'; let s=""; for await (const x of process.stdin) s+=x; console.log(JSON.stringify(withPersistedExportMode(JSON.parse(s))));'
            context = json.loads(subprocess.check_output(['node', '--experimental-strip-types', '--input-type=module', '-e', code], input=json.dumps(context), text=True))
            assert context['quantitation_export_mode'] == 'astra_analysis.v5'
            payload = {'project_name': 'Round01_HIRcB_'+uuid4().hex[:8], 'species': original['species'],
                       'ptm_type': original['ptm_type'], 'sample_config': json.dumps(original['sample_config']),
                       'analysis_context': json.dumps(context, ensure_ascii=False),
                       'analysis_options': json.dumps(original.get('analysis_options') or {'mode': 'full'}),
                       'report_options': json.dumps(original.get('report_options') or {}), 'rag_collections': '[]'}
            files = {field: (Path(saved['inputs'][key]).name, z.read(saved['inputs'][key]))
                     for key, field in [('PR', 'pr_matrix'), ('PG', 'pg_matrix'), ('FASTA', 'fasta_file')]}
            uploads = list(files.items())
            for doc in saved['literature'].get('documents', []):
                if doc.get('role') == 'user_supplied_research_attachment' and doc.get('content_status') == 'full_text_included':
                    data = z.read(doc['package_file'])
                    assert sha(data) == doc['sha256']
                    uploads.append(('research_attachments', (doc['filename'], data)))
            created = request('POST', '/orders', data=payload, files=uploads)
        oid = created['id']; state = request('GET', f'/orders/{oid}')
        assert state['analysis_context']['quantitation_export_mode'] == 'astra_analysis.'+args.label
        write(args.output, 'order.json', {'id': oid, 'order_code': state['order_code'], 'requested_mode': context['quantitation_export_mode'],
              'persisted_mode': state['analysis_context']['quantitation_export_mode'], 'source_pin_sha256': pin,
              'origin_archive_sha256': sha(args.archive.read_bytes()), 'input_sha256': {field: sha(data) for field, (_, data) in files.items()}})
        if not args.draft_only:
            request('POST', f'/orders/{oid}/start')
        print('created_draft' if args.draft_only else 'created_and_started', oid, flush=True); return
    oid = json.loads((args.output/'order.json').read_text())['id']
    if args.phase in {'rerun', 'results'}:
        # Browser actions match the existing validate_astra_browser.py route.
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100}); observed = []; errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def capture(req):
                if req.method == 'PATCH' and urlparse(req.url).path == f'/api/orders/{oid}':
                    body = req.post_data_json
                    observed.append({'method': 'PATCH', 'route': f'/orders/{oid}',
                                     'requested_mode': body['analysis_context']['quantitation_export_mode']})
            page.on('request', capture)
            page.goto(args.ui_url+'/login'); page.get_by_placeholder('Enter your email').fill(os.environ['PTM_TEST_EMAIL'])
            page.get_by_placeholder('Enter your password').fill(os.environ['PTM_TEST_PASSWORD']); page.locator('button[type=submit]').click()
            page.wait_for_url(args.ui_url+'/admin'); page.goto(args.ui_url+f'/admin/orders/{oid}')
            if args.phase == 'results':
                expected = json.loads((args.output/'v6-contract.json').read_text())
                section = page.get_by_role('region', name='Primary A evidence')
                expect(section.get_by_role('heading', name='Astra 분석 패키지')).to_be_visible(timeout=30000)
                expect(section).to_contain_text(expected['run_id'])
                section.screenshot(path=str(args.output/'v6-results.png'))
                with page.expect_download() as downloaded:
                    section.get_by_role('button', name='패키지 다운로드', exact=True).click()
                target = args.output/downloaded.value.suggested_filename
                downloaded.value.save_as(str(target))
                assert sha(target.read_bytes()) == expected['archive_sha256']
                page.get_by_role('tab', name='Results', exact=True).click()
                expect(page.get_by_text(f'astra_analysis_package_{expected["run_id"]}.zip', exact=True)).to_be_visible(timeout=30000)
                page.screenshot(path=str(args.output/'v6-data-files.png'))
                assert not errors, errors
                write(args.output, 'ui-results.json', {'passed': True, 'run_id': expected['run_id'],
                      'download_file': target.name, 'download_sha256': expected['archive_sha256'],
                      'same_as_API_download': True, 'results_data_files_same_run': True, 'page_errors': errors})
                print('normal_UI_results_and_download_verified', expected['run_id'], flush=True)
                browser.close(); return
            state = request('GET', f'/orders/{oid}')
            start_button = 'Retry Analysis' if state['status'] == 'failed' else 'Re-run from Beginning'
            page.get_by_role('button', name=start_button, exact=True).click()
            dialog = page.get_by_role('dialog'); expect(dialog.get_by_role('button', name='Confirm & create Astra package', exact=True)).to_be_visible()
            dialog.screenshot(path=str(args.output/'normal-rerun.png'))
            with page.expect_response(lambda r: r.request.method == 'POST' and urlparse(r.url).path == f'/api/orders/{oid}/start', timeout=120000) as started:
                dialog.get_by_role('button', name='Confirm & create Astra package', exact=True).click()
            assert started.value.ok, started.value.status
            assert observed and all(row['requested_mode'] == 'astra_analysis.v5' for row in observed), observed
            state = request('GET', f'/orders/{oid}')
            assert state['analysis_context']['quantitation_export_mode'] == 'astra_analysis.v6'
            # Previous successful package stays available while the new run executes.
            previous = request('GET', f'/orders/{oid}/enrichment-free-evidence')
            before = json.loads((args.output/'v5-contract.json').read_text())
            assert previous['run_id'] == before['run_id']
            write(args.output, 'ui-request.json', {'start_button': start_button, 'requests': observed, 'persisted_mode': state['analysis_context']['quantitation_export_mode'],
                  'previous_success_pointer_preserved_while_running': True, 'previous_run_id': previous['run_id']})
            print('normal_UI_v5_request_persisted_and_started_as_v6', oid, flush=True); browser.close()
        return
    deadline = time.monotonic()+7200; prior = None
    while time.monotonic() < deadline:
        if not (args.output/(args.label+'-dispatch.json')).exists():
            dispatched = dispatch_record(oid)
            if dispatched:
                assert dispatched['dispatch_mode'] == 'astra_analysis.'+args.label
                write(args.output, args.label+'-dispatch.json', dispatched)
        state = request('GET', f'/orders/{oid}')
        marker = (state['status'], state.get('stage_detail'))
        if marker != prior: print(oid, marker, flush=True); prior = marker
        if state['status'] == 'completed':
            record = request('GET', f'/orders/{oid}/enrichment-free-evidence')
            response = client.get(f'/orders/{oid}/enrichment-free-evidence', params={'artifact': 'astra'}); response.raise_for_status()
            assert sha(response.content) == record['artifacts']['astra']['sha256']
            (args.output/(args.label+'.zip')).write_bytes(response.content)
            contract = package_contract(response.content)
            assert all(contract[k] == 'astra_analysis.'+args.label for k in ('context', 'plan', 'provenance', 'replay')), contract
            write(args.output, args.label+'-contract.json', contract)
            print('verified', contract['run_id'], args.label, flush=True); return
        if state['status'] in {'failed', 'cancelled'}: raise AssertionError(state.get('error_message') or marker)
        time.sleep(10)
    raise TimeoutError('Isolated run did not complete within the recorded test budget')


if __name__ == '__main__':
    main()
