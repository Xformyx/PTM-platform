"""Per-call trace across section threads; no request headers or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar

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
        current.append(event)
