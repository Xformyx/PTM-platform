"""Immutable filesystem revisions shared by report finalization and API readers.

Additive registry for existing artifact/release contracts. Legacy files are never
backfilled as final-ready. All paths are relative to the order output directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile

VERSION = "report_revision.v1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path, value):
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, default=str)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, path)


def read_revision(output_dir, revision_id=None):
    root = Path(output_dir) / '.report_revisions'
    if revision_id is None:
        pointer = root / 'current.json'
        if not pointer.is_file():
            return None
        revision_id = json.loads(pointer.read_text())['revision_id']
    if not re.fullmatch(r'[a-f0-9]{64}', str(revision_id)):
        raise ValueError('invalid_revision_id')
    path = root / (revision_id + '.json')
    value = json.loads(path.read_text())
    if value.get('schema_version') != VERSION or value.get('revision_id') != revision_id:
        raise ValueError('incompatible_revision')
    return value


def verify_revision(output_dir, revision):
    from .analysis_revision import _verify_immutable_file
    root = Path(output_dir).resolve()
    if not revision.get('registry_sha256') or _digest({k: v for k, v in revision.items() if k != 'registry_sha256'}) != revision['registry_sha256']:
        raise ValueError('revision_registry_integrity_mismatch')
    for artifact in revision.get('artifacts') or []:
        path = (root / artifact['filename']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('revision_artifact_integrity_mismatch')
        try:
            _verify_immutable_file(path,artifact['sha256'])
        except ValueError as exc:
            raise ValueError('revision_artifact_integrity_mismatch') from exc
        if artifact.get('linked_asset'):
            asset = (root / artifact['linked_asset']).resolve()
            if not asset.is_relative_to(root) or not asset.is_file():
                raise ValueError('revision_linked_asset_integrity_mismatch')
            try:
                _verify_immutable_file(asset,artifact['sha256'])
            except ValueError as exc:
                raise ValueError('revision_linked_asset_integrity_mismatch') from exc
    return revision


def register_revision(output_dir, *, files, manifest, release, references=(), source_revisions=(), make_current=True):
    """Copy and seal only explicitly returned artifacts, then atomically move current.

    A local lock serializes registration; the revision digest gives idempotency.
    No prior revision or source file is overwritten or deleted.
    """
    import fcntl
    output = Path(output_dir)
    root = output / '.report_revisions'
    root.mkdir(parents=True, exist_ok=True)
    report_paths = {str(Path(p)) for p in files}
    source_entries = {str(Path(a['path'])): a for a in list((manifest or {}).get('artifacts', [])) + list((manifest or {}).get('rendered_artifacts', []))
                      if a.get('path') and a.get('sha256')}
    for path, entry in source_entries.items():
        if not Path(path).is_file() or file_sha256(path) != entry['sha256']:
            raise ValueError('source_changed_before_registration')
    sources = sorted(report_paths | set(source_entries))
    bindings = [{'original_name': Path(p).name, 'sha256': file_sha256(p)} for p in sources]
    identity = {'schema_version': VERSION, 'artifacts': bindings, 'manifest': manifest,
                'release': release, 'references': list(references), 'source_revisions': list(source_revisions)}
    revision_id = _digest(identity)
    if len({b['original_name'] for b in bindings}) != len(bindings):
        raise ValueError('ambiguous_artifact_basename')
    with (root / 'registration.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        destination = root / (revision_id + '.json')
        if destination.exists():
            revision = verify_revision(output, read_revision(output, revision_id))
        else:
            artifacts = []
            for source, binding in zip(sources, bindings):
                name = f"rev_{revision_id}_{binding['original_name']}"
                target = output / name
                if not target.exists():
                    with NamedTemporaryFile(dir=output, delete=False) as temporary:
                        with Path(source).open('rb') as stream:
                            shutil.copyfileobj(stream, temporary)
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    if file_sha256(temporary.name) != binding['sha256']:
                        raise ValueError('source_changed_during_registration')
                    os.replace(temporary.name, target)
                artifacts.append({**binding, 'filename': name, 'format': target.suffix.lstrip('.'),
                                  'role': 'report' if source in report_paths else source_entries[source]['role'],
                                  'linked_asset': binding['original_name'] if binding['original_name'].startswith('asset_') else None,
                                  'source_revision_id': revision_id})
            revision = {**identity, 'revision_id': revision_id, 'artifacts': artifacts}
            revision['registry_sha256'] = _digest(revision)
            verify_revision(output, revision)
            _atomic_json(destination, revision)
        if make_current:
            _move_pointer(root, revision_id)
        index_path = root / 'index.json'
        index = json.loads(index_path.read_text()) if index_path.exists() else {'schema_version': VERSION, 'revision_ids': []}
        index['revision_ids'] = sorted(set(index['revision_ids']) | {revision_id})
        _atomic_json(index_path, index)
    return revision


def _move_pointer(root, revision_id):
    """Persist append-only pointer history, including an explicit rollback."""
    from datetime import datetime, timezone
    from uuid import uuid4
    pointer = root / 'current.json'
    previous = json.loads(pointer.read_text()).get('revision_id') if pointer.exists() else None
    if previous == revision_id:
        return
    history = root / 'history'
    history.mkdir(exist_ok=True)
    _atomic_json(history / (uuid4().hex + '.json'), {
        'previous_revision_id': previous, 'revision_id': revision_id,
        'changed_at': datetime.now(timezone.utc).isoformat(),
    })
    _atomic_json(pointer, {'revision_id': revision_id, 'schema_version': VERSION})


def select_current_revision(output_dir, revision_id):
    """Rollback by pointer only. The selected revision keeps its release policy."""
    import fcntl
    root = Path(output_dir) / '.report_revisions'
    with (root / 'registration.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        revision = verify_revision(output_dir, read_revision(output_dir, revision_id))
        _move_pointer(root, revision_id)
    return revision


def revision_download_path(output_dir, filename, revision=None):
    revision = revision or read_revision(output_dir)
    if not revision:
        raise ValueError('legacy_artifact_unverified')
    if revision.get('release', {}).get('review_artifact_available') is not True:
        raise ValueError('revision_release_withheld')
    artifact = next((a for a in revision.get('artifacts') or [] if a['filename'] == filename), None)
    if not artifact:
        raise ValueError('artifact_not_registered_in_revision')
    verify_revision(output_dir, revision)
    return Path(output_dir) / artifact['filename']


def revision_packet(output_dir, revision, role):
    verify_revision(output_dir, revision)
    artifact = next((a for a in revision['artifacts'] if a['role'] == role), None)
    if not artifact:
        raise ValueError('revision_packet_unavailable:' + role)
    return json.loads((Path(output_dir) / artifact['filename']).read_text())


def derived_revision_files(output_dir, source_revision_id):
    index_path = Path(output_dir) / '.report_revisions' / 'index.json'
    if not index_path.exists():
        return []
    result = []
    for revision_id in json.loads(index_path.read_text())['revision_ids']:
        revision = read_revision(output_dir, revision_id)
        if any(source.get('revision_id') == source_revision_id for source in revision.get('source_revisions') or []):
            verify_revision(output_dir, revision)
            if revision['release'].get('review_artifact_available'):
                result.extend(a['filename'] for a in revision['artifacts'] if a['role'] == 'report')
    return result


def backfill_legacy_revision(output_dir, files, *, audience='unresolved'):
    """Explicit migration of declared historical files, without scientific approval."""
    root = Path(output_dir).resolve()
    paths = [(root / filename).resolve() for filename in files]
    if any(not path.is_relative_to(root) for path in paths):
        raise ValueError('legacy_artifact_path_outside_order')
    return register_revision(root, files=list(map(str, paths)), manifest={'migration': 'legacy_bytes_only.v1'},
        release={'contract_version': 'reader_report_release.v7', 'status': 'legacy_not_gated',
                 'report_audience': audience, 'publish_as_final': False, 'review_artifact_available': True,
                 'reason_codes': ['legacy_source_provenance_unavailable'], 'final_artifact_withheld': False})


def main():
    """Explicit maintenance entry point; never discovers/promotes files by glob."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['verify', 'backfill', 'rollback'])
    parser.add_argument('output_dir', type=Path)
    parser.add_argument('--revision-id')
    parser.add_argument('--file', action='append', default=[])
    parser.add_argument('--audience', choices=['unresolved', 'researcher_manuscript', 'technical_audit'], default='unresolved')
    args = parser.parse_args()
    if args.operation == 'backfill':
        if not args.file:
            parser.error('backfill requires explicit --file values')
        if read_revision(args.output_dir):
            parser.error('a current revision already exists; backfill cannot replace it')
        revision = backfill_legacy_revision(args.output_dir, args.file, audience=args.audience)
    elif args.operation == 'rollback':
        if not args.revision_id:
            parser.error('rollback requires --revision-id')
        revision = select_current_revision(args.output_dir, args.revision_id)
    else:
        revision = read_revision(args.output_dir, args.revision_id)
        if not revision:
            parser.error('no registered revision')
        verify_revision(args.output_dir, revision)
    print(json.dumps({'revision_id': revision['revision_id'], 'release': revision['release'],
                      'artifact_count': len(revision['artifacts'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
