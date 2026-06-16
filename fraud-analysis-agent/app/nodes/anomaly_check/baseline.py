"""Time-window helpers for anomaly_check_node.

All functions return a dict:
    {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "label": "..."}

"start" is inclusive, "end" is inclusive (query uses `<= end 23:59:59`).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

import pandas as pd

from app.shared.warehouse import warehouse_query


# ---------------------------------------------------------------------------
# Window builders
# ---------------------------------------------------------------------------

def _window(start: date, end: date, label: str) -> dict:
    return {"start": start.isoformat(), "end": end.isoformat(), "label": label}


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_current_week(now: datetime) -> dict:
    today = now.date()
    return _window(_monday(today), today, f"W0: {_monday(today)} – {today}")


def compute_prev_week(now: datetime) -> dict:
    today = now.date()
    mon = _monday(today) - timedelta(weeks=1)
    sun = mon + timedelta(days=6)
    return _window(mon, sun, f"W-1: {mon} – {sun}")


def compute_current_month(now: datetime) -> dict:
    today = now.date()
    start = today.replace(day=1)
    return _window(start, today, f"M0: {start} – {today}")


def compute_prev_month(now: datetime) -> dict:
    today = now.date()
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return _window(first_prev, last_prev, f"M-1: {first_prev} – {last_prev}")


def compute_today(now: datetime) -> dict:
    d = now.date()
    return _window(d, d, f"D0: {d}")


def compute_yesterday(now: datetime) -> dict:
    d = now.date() - timedelta(days=1)
    return _window(d, d, f"D-1: {d}")


def compute_rolling_7d(now: datetime) -> dict:
    end = now.date()
    start = end - timedelta(days=6)
    return _window(start, end, f"Rolling7: {start} – {end}")


def compute_rolling_7d_prev(now: datetime) -> dict:
    end = now.date() - timedelta(days=7)
    start = end - timedelta(days=6)
    return _window(start, end, f"Rolling7-prev: {start} – {end}")


def compute_avg_4w(now: datetime) -> dict:
    """Returns the window covering the 4 complete weeks before current week.
    Used by the caller to fetch data and divide totals by 4.
    """
    today = now.date()
    end = _monday(today) - timedelta(days=1)   # last Sunday
    start = end - timedelta(weeks=4) + timedelta(days=1)
    return _window(start, end, f"Avg4w-window: {start} – {end}")


# ---------------------------------------------------------------------------
# MySQL queries
# ---------------------------------------------------------------------------

def _query_pom(window: dict) -> pd.DataFrame:
    sql = (
        "SELECT * FROM pom_acr "
        f"WHERE reqDate >= '{window['start']}' "
        f"AND reqDate <= '{window['end']} 23:59:59'"
    )
    return warehouse_query(sql)


def fetch_all_windows(now: datetime | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    """Query pom_acr for every comparison window.

    Returns (dfs, windows) where:
      dfs     = {key: DataFrame}
      windows = {key: window_dict}  (contains label, start, end)
    """
    now = now or datetime.utcnow()
    windows = {
        "current_week":    compute_current_week(now),
        "prev_week":       compute_prev_week(now),
        "current_month":   compute_current_month(now),
        "prev_month":      compute_prev_month(now),
        "today":           compute_today(now),
        "yesterday":       compute_yesterday(now),
        "rolling_7d":      compute_rolling_7d(now),
        "rolling_7d_prev": compute_rolling_7d_prev(now),
        "avg_4w_window":   compute_avg_4w(now),
    }
    dfs = {key: _query_pom(w) for key, w in windows.items()}
    return dfs, windows


# Legacy helper kept for callers that still use it
def compute_baseline_window(now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    return compute_prev_week(now)


def query_baseline_pom_acr(window: dict) -> pd.DataFrame:
    return _query_pom(window)
