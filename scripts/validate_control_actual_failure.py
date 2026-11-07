"""Fail one isolated C05A run before publication; verify the real success pointer.

Requires the explicit validation adapter in validate_control_actual_runtime.py.
This never edits an existing package or resets a failed Order to completed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(2**20), b''):
            digest.update(block)
    return digest.hexdigest()


def request(path, post=False):
    request = urllib.request.Request('http://127.0.0.1:8027/api/orders/1' + path,
        data=b'' if post else None, method='POST' if post else 'GET')
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    root = output / 'delivery/C05A_ACTUAL'
    order = request('')
    assert order['order_code'] == 'C05A_ACTUAL' and order['status'] == 'completed'
    assert json.loads((output / 'PACKAGE_VALIDATION.json').read_text())['passed']
    pointer_path = root / 'enrichment_free_current.json'
    before = sha(pointer_path)
    pointer = json.loads(pointer_path.read_text())
    archive = root / pointer['artifacts']['astra']['path']
    archive_before = sha(archive)
    source = json.loads((output / 'PREDECLARED.json').read_text())
    source_pointer = Path(source['baseline_pointer'])
    source_pointer_before = sha(source_pointer)
    marker = output / 'FAIL_NEXT'
    if marker.exists():
        raise FileExistsError('Failure marker already present')
    marker.write_text('deliberate validation failure; not production configuration')
    try:
        dispatch = request('/start', post=True)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            state = request('')
            if state['status'] in {'failed', 'completed', 'cancelled'}:
                break
            time.sleep(2)
        assert state['status'] == 'failed', state['status']
        assert sha(pointer_path) == before
        assert sha(archive) == archive_before
        assert sha(source_pointer) == source_pointer_before
        download_pointer = request('/enrichment-free-evidence')
        assert download_pointer['run_id'] == pointer['run_id']
        assert download_pointer['artifacts']['astra']['sha256'] == archive_before
        result = {'passed': True, 'injected_failure': 'before compute_science/publication',
            'order_status': state['status'], 'task_id': dispatch['task_id'],
            'preserved_run_id': pointer['run_id'], 'pointer_sha256': before,
            'archive_sha256': archive_before, 'original_source_pointer_sha256': source_pointer_before,
            'download_pointer_matches_preserved_success': True, 'transport': 'real API/MySQL/Redis/Celery'}
        (output / 'FAILURE_VALIDATION.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        # Only the marker created by this invocation; never remove input/output data.
        marker.unlink()


if __name__ == '__main__':
    main()
