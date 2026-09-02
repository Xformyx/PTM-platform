"""Shared JSON artifact I/O for large RAG / Report files.

Concurrent writers opening the same path with ``open(..., "w")`` can leave a
complete first document plus a trailing fragment. ``json.load`` then raises
``Extra data``. Writes go through a temp file + ``os.replace`` so readers only
see a complete document. Loaders take the first complete value and ignore a
trailing fragment if one is already on disk.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("ptm-workers.json-files")


def atomic_write_json(
    path: str | Path,
    payload: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
    default: Any = str,
    ensure_ascii: bool = False,
) -> None:
    """Write JSON so a concurrent reader never sees a half-written file."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(
                payload,
                indent=indent,
                sort_keys=sort_keys,
                default=default,
                ensure_ascii=ensure_ascii,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def load_json_first_value(path: str | Path) -> Any:
    """Load the first complete JSON value from ``path``.

    If a later writer appended a fragment after a finished array/object,
    ``json.load`` fails with Extra data. The first value is the intended
    artifact; leftover bytes are logged and discarded.
    """
    dest = Path(path)
    text = dest.read_text(encoding="utf-8")
    obj, end = json.JSONDecoder().raw_decode(text)
    leftover = text[end:].strip()
    if leftover:
        logger.warning(
            "Ignoring trailing Extra data in %s after first JSON value "
            "(end=%s leftover_chars=%s)",
            dest.name,
            end,
            len(leftover),
        )
    return obj
