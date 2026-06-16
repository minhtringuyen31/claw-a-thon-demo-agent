"""Deterministic resolver: natural-language `time_hint` → ISO date range.

LLM stays out of date arithmetic. This is pure regex + calendar math so the
window is reproducible across runs.

Returns: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "column": "reqDate"}
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

DEFAULT_DAYS = 90
FILTER_COLUMN = "reqDate"


def compute_investigation_window(now: Optional[datetime] = None) -> dict:
    """Window = [first day of previous month, today].

    Captures "previous month + this month-to-date" — covers the typical
    weekly-report cadence (e.g. report at week 1 of June → window includes
    all of May plus June 1..today).
    """
    now = now or datetime.utcnow()
    today = now.date()
    if today.month == 1:
        prev_start = date(today.year - 1, 12, 1)
    else:
        prev_start = date(today.year, today.month - 1, 1)
    return {
        "start": prev_start.isoformat(),
        "end": today.isoformat(),
        "column": FILTER_COLUMN,
    }


def resolve_time_window(
    time_hint: Optional[str],
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.utcnow()
    today = now.date()

    if not time_hint:
        return _window(today - timedelta(days=DEFAULT_DAYS), today)

    s = time_hint.strip().lower()

    # "last N day|week|month"  /  "past N day..."
    m = re.search(r"(?:last|past)\s+(\d+)\s+(day|week|month)", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = _delta(n, unit)
        return _window(today - delta, today)

    # "N ngày|tuần|tháng qua|gần đây"
    m = re.search(r"(\d+)\s*(ngày|tuần|tháng)", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = _delta(n, _vn_unit(unit))
        return _window(today - delta, today)

    # "Q[1-4] YYYY" or "quý N YYYY"
    m = re.search(r"q(?:uý\s*)?([1-4])\s*[/\- ]?\s*(\d{4})", s)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        start = date(y, (q - 1) * 3 + 1, 1)
        end_month = q * 3
        end = _month_end(y, end_month)
        return _window(start, end)

    # "tháng N/YYYY" or "tháng N"
    m = re.search(r"tháng\s*(\d{1,2})(?:\s*[/-]\s*(\d{4}))?", s)
    if m:
        mo = int(m.group(1))
        y = int(m.group(2)) if m.group(2) else today.year
        return _window(date(y, mo, 1), _month_end(y, mo))

    # "YYYY-MM"
    m = re.search(r"(\d{4})-(\d{1,2})\b", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return _window(date(y, mo, 1), _month_end(y, mo))

    return _window(today - timedelta(days=DEFAULT_DAYS), today)


def _vn_unit(u: str) -> str:
    return {"ngày": "day", "tuần": "week", "tháng": "month"}[u]


def _delta(n: int, unit: str) -> timedelta:
    if unit == "day":
        return timedelta(days=n)
    if unit == "week":
        return timedelta(days=n * 7)
    return timedelta(days=n * 30)


def _month_end(y: int, mo: int) -> date:
    if mo == 12:
        return date(y, 12, 31)
    return date(y, mo + 1, 1) - timedelta(days=1)


def _window(start: date, end: date) -> dict:
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "column": FILTER_COLUMN,
    }
