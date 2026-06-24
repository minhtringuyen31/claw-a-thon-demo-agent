"""Fraud-analysis-agent specific tools: metrics scoring and anomaly baselines."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from db.sql_safety import UnsafeSQLError, validate_sql
from db.warehouse import warehouse_query


# ---------------------------------------------------------------------------
# Helpers shared across tools
# ---------------------------------------------------------------------------

def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return v.isoformat()
    if isinstance(v, float) and pd.isna(v):
        return None
    if hasattr(v, "item") and not isinstance(v, str):
        try:
            return v.item()
        except Exception:
            pass
    return v


def _load_ground_truth(window: dict | None, fraud_types: list[str] | None) -> set[str]:
    src = os.environ.get("GROUND_TRUTH_SOURCE", "pom_acr").lower()
    if src == "pom_acr":
        clauses = ["1=1"]
        if window:
            clauses.append(
                f"reqDate >= '{window['start']}' AND reqDate <= '{window['end']} 23:59:59'"
            )
        if fraud_types:
            types_csv = ", ".join(f"'{t}'" for t in fraud_types)
            clauses.append(f"fraud_type IN ({types_csv})")
        df = warehouse_query(f"SELECT transID FROM pom_acr WHERE {' AND '.join(clauses)}")
        return set(df["transID"].astype(str))
    if src == "column":
        df = warehouse_query("SELECT txn_id FROM transactions WHERE is_fraud = 1")
        return set(df["txn_id"].astype(str))
    raise ValueError(f"Unknown GROUND_TRUTH_SOURCE={src!r}")


def _build_windows(now: datetime) -> dict[str, dict]:
    today = now.date()

    def _mon(d: date) -> date:
        return d - timedelta(days=d.weekday())

    def _w(s: date, e: date, label: str) -> dict:
        return {"start": s.isoformat(), "end": e.isoformat(), "label": label}

    cur_week_start = _mon(today)
    prev_week_start = cur_week_start - timedelta(weeks=1)
    prev_week_end = cur_week_start - timedelta(days=1)
    cur_month_start = today.replace(day=1)
    first_prev = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    last_prev = today.replace(day=1) - timedelta(days=1)
    yesterday = today - timedelta(days=1)
    rolling_start = today - timedelta(days=6)
    rolling_prev_end = today - timedelta(days=7)
    rolling_prev_start = rolling_prev_end - timedelta(days=6)
    avg4w_end = cur_week_start - timedelta(days=1)
    avg4w_start = avg4w_end - timedelta(weeks=4) + timedelta(days=1)

    return {
        "current_week":    _w(cur_week_start, today,            f"W0: {cur_week_start} – {today}"),
        "prev_week":       _w(prev_week_start, prev_week_end,   f"W-1: {prev_week_start} – {prev_week_end}"),
        "current_month":   _w(cur_month_start, today,           f"M0: {cur_month_start} – {today}"),
        "prev_month":      _w(first_prev, last_prev,            f"M-1: {first_prev} – {last_prev}"),
        "today":           _w(today, today,                     f"D0: {today}"),
        "yesterday":       _w(yesterday, yesterday,             f"D-1: {yesterday}"),
        "rolling_7d":      _w(rolling_start, today,             f"Rolling7: {rolling_start} – {today}"),
        "rolling_7d_prev": _w(rolling_prev_start, rolling_prev_end, f"Rolling7-prev: {rolling_prev_start} – {rolling_prev_end}"),
        "avg_4w":          _w(avg4w_start, avg4w_end,           f"Avg4w-window: {avg4w_start} – {avg4w_end}"),
    }


def _period_summary(df: pd.DataFrame, label: str, dimensions: list[str]) -> dict:
    if df.empty:
        return {
            "label": label,
            "total_amount_vnd": 0,
            "total_count": 0,
            **{f"by_{dim}": [] for dim in dimensions},
        }
    has_amount = "userChargeAmount" in df.columns
    result: dict[str, Any] = {
        "label": label,
        "total_count": int(len(df)),
        "total_amount_vnd": int(df["userChargeAmount"].sum()) if has_amount else 0,
    }
    for dim in dimensions:
        if dim not in df.columns:
            result[f"by_{dim}"] = []
            continue
        if has_amount:
            agg = (
                df.groupby(dim, dropna=False)
                .agg(count=(dim, "size"), amount_vnd=("userChargeAmount", "sum"))
                .reset_index()
                .sort_values("amount_vnd", ascending=False)
            )
            result[f"by_{dim}"] = [
                {dim: _jsonable(r[dim]), "count": int(r["count"]), "amount_vnd": int(r["amount_vnd"])}
                for _, r in agg.iterrows()
            ]
        else:
            agg = (
                df.groupby(dim, dropna=False)
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
            )
            result[f"by_{dim}"] = [
                {dim: _jsonable(r[dim]), "count": int(r["count"])}
                for _, r in agg.iterrows()
            ]
    return result


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp) -> None:
    @mcp.tool()
    def compute_metrics(
        sql_predicate: str,
        window: dict | None = None,
        fraud_types: list[str] | None = None,
    ) -> dict:
        """Score a candidate fraud rule: precision/recall/F1 vs pom_acr ground truth.

        sql_predicate: SELECT returning a transID column on trans_log (JOINs to
                       user_profile/user_journey allowed).
        window: optional {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} to restrict truth set.
        fraud_types: optional list of fraud_type codes to restrict truth set.
        Returns: {precision, recall, f1, hit_count, total_fraud, total_flagged, sql_predicate}
        """
        try:
            validate_sql(sql_predicate)
        except UnsafeSQLError as e:
            return {"error": f"unsafe sql: {e}"}
        try:
            df = warehouse_query(sql_predicate)
        except Exception as e:
            return {"error": f"query failed: {e}"}
        if "transID" not in df.columns:
            return {"error": "sql_predicate must return a 'transID' column"}

        matched_ids = [str(x) for x in df["transID"].tolist()]
        truth = _load_ground_truth(window, fraud_types)
        flagged = set(matched_ids)
        tp = len(flagged & truth)
        fp = len(flagged - truth)
        fn = len(truth - flagged)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "hit_count": tp,
            "total_fraud": len(truth),
            "total_flagged": len(flagged),
            "sql_predicate": sql_predicate,
        }

    @mcp.tool()
    def fetch_anomaly_baselines(dimensions: list[str]) -> dict:
        """Query pom_acr for 9 time windows and return aggregated per-period summaries.

        dimensions: list of columns to aggregate by (e.g. ["appID", "bankType"]).
        Returns: {current_week, prev_week, current_month, prev_month, today,
                  yesterday, rolling_7d, rolling_7d_prev, avg_4w}
        Each period: {label, start, end, total_count, total_amount_vnd, by_<dim>: [...]}
        avg_4w totals are divided by 4 to give weekly averages.
        """
        now = datetime.utcnow()
        windows = _build_windows(now)
        result: dict[str, dict] = {}

        for key, w in windows.items():
            sql = (
                "SELECT * FROM pom_acr "
                f"WHERE reqDate >= '{w['start']}' "
                f"AND reqDate <= '{w['end']} 23:59:59'"
            )
            df = warehouse_query(sql)
            summary = _period_summary(df, w["label"], dimensions)
            summary["start"] = w["start"]
            summary["end"] = w["end"]

            if key == "avg_4w":
                summary["total_amount_vnd"] = summary["total_amount_vnd"] // 4
                summary["total_count"] = summary["total_count"] // 4
                for dim in dimensions:
                    k = f"by_{dim}"
                    summary[k] = [
                        {
                            **item,
                            "count": item["count"] // 4,
                            **({"amount_vnd": item["amount_vnd"] // 4} if "amount_vnd" in item else {}),
                        }
                        for item in summary.get(k, [])
                    ]

            result[key] = summary

        return result

    @mcp.tool()
    def notify_strategist(summary: str) -> dict:
        """Send a pattern-ready notification to the fraud strategist.

        In development: prints to stdout. In production: send to Slack/email.
        Returns: {notified: true}
        """
        print("\n" + "=" * 60)
        print("NOTIFY STRATEGIST — pattern ready for review:")
        print(summary)
        print("=" * 60 + "\n")
        return {"notified": True}
