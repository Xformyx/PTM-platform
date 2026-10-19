"""Per-call trace across section threads; no request headers or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

_events = ContextVar("generation_transport_events", default=None)


@contextmanager
def capture_generation():
    events = []
    token = _events.set(events)
    try:
        yield events
    finally:
        _events.reset(token)


def record_generation_event(**event):
    current = _events.get()
    if current is not None:
        current.append(deepcopy(event))


def persist_generation_trace(root, trace):
    """Private, immutable diagnostic object beside the existing stage cache.

    Not an execution cache or a package artifact. Callers pass only prompt/body
    data, never HTTP headers, endpoint credentials or environment variables.
    Failed comparisons are retained too; a missing trace is reported explicitly.
    """
    import hashlib
    import json
    import os
    from pathlib import Path
    from uuid import uuid4
    if root is None:
        return {'status': 'not_persisted', 'reason': 'internal_trace_root_not_configured'}
    payload = json.dumps(trace, ensure_ascii=False, sort_keys=True, default=str).encode()
    sha = hashlib.sha256(payload).hexdigest()
    directory = Path(root) / 'generation_traces'
    temporary = None
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = directory / ('.' + uuid4().hex)
        with temporary.open('xb') as handle:
            os.chmod(temporary, 0o600)
            handle.write(payload)
        target = directory / (sha + '.json')
        # Same bytes may be reused; no existing object is overwritten.
        os.link(temporary, target)
        return {'status': 'stored', 'trace_id': sha, 'sha256': sha,
                'scope': 'internal_only; not_a_package_source'}
    except FileExistsError:
        if target.read_bytes() != payload:
            raise ValueError('generation_trace_hash_collision')
        return {'status': 'stored', 'trace_id': sha, 'sha256': sha,
                'scope': 'internal_only; not_a_package_source'}
    except OSError as error:
        return {'status': 'failed', 'reason': type(error).__name__}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
