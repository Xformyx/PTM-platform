"""Convert deploy GIT_DATE stamps to Asia/Seoul for UI display."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

_GIT_DATE_CI = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?: ([+-])(\d{2}):?(\d{2}))?$"
)


def format_git_date_kst(raw: str) -> str:
    """Convert a GIT_DATE / git %ci/%cI stamp to Asia/Seoul wall time.

    Deploy used to strip the offset from ``git log --format=%ci``, so a naive
    ``YYYY-MM-DD HH:MM:SS`` is UTC (the commit object's remaining clock).
    """
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        match = _GIT_DATE_CI.match(text)
        if match:
            wall, sign, hours, minutes = match.groups()
            if sign and hours is not None and minutes is not None:
                dt = datetime.strptime(
                    f"{wall} {sign}{hours}{minutes}", "%Y-%m-%d %H:%M:%S %z"
                )
            else:
                dt = datetime.strptime(wall, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=ZoneInfo("UTC")
                )
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    except (ValueError, TypeError):
        return text
    return dt.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
