"""Tool registry exposed to the investigation ReAct loop.

Each tool here is the **LLM-facing wrapper** that:
  - takes primitive args (str, dict, list — JSON-serializable)
  - returns a small JSON-serializable dict (no DataFrames, no Timestamps)

`act_node` looks up the tool by name in `TOOL_REGISTRY` and calls it.

Tables exposed to the agent:
  trans_log     — universe of transactions
  pom_acr       — confirmed-fraud subset of trans_log (extra fraud_type/is_loss/report_date)
  user_profile  — 1 row / user (identity + KYC/NFC + trust flags)
  user_journey  — append-only event log per user
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

import pandas as pd

from app.shared.historical import (
    TIME_COL_BY_TABLE,
    _format_filter_value,
    aggregate_by,
    query_with_filters,
)
from app.shared.sql_safety import UnsafeSQLError, validate_sql
from app.shared.warehouse import warehouse_query
from app.nodes.investigation.metrics import compute_metrics as _compute_metrics

SAMPLE_CAP = 15
ROWS_PREVIEW_CAP = 15
ALLOWED_TABLES = ("trans_log", "pom_acr", "user_profile", "user_journey")


# --------------------------- helpers -------------------------------------

def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, float) and pd.isna(v):
        return None
    if hasattr(v, "item") and not isinstance(v, str):
        try:
            return v.item()
        except Exception:
            pass
    return v


def _rows_jsonable(df: pd.DataFrame, n: int) -> list[dict]:
    return [
        {k: _jsonable(v) for k, v in row.items()}
        for _, row in df.head(n).iterrows()
    ]


def _normalize_window(window: dict | None) -> dict | None:
    if not window:
        return None
    if "start" not in window or "end" not in window:
        return None
    return {
        "start": window["start"],
        "end": window["end"],
        "column": window.get("column"),
    }


def _check_table(table: str) -> dict | None:
    if table not in ALLOWED_TABLES:
        return {
            "error": (
                f"unknown table {table!r}; "
                f"valid: {list(ALLOWED_TABLES)}"
            )
        }
    return None


# --------------------------- tool: query_with_filters --------------------

def tool_query_with_filters(
    table: str,
    filters: dict | None = None,
    window: dict | None = None,
    limit: int | None = None,
) -> dict:
    """Filter rows in any of the 4 warehouse tables by exact-match.

    Args:
      table   : "trans_log" | "pom_acr" | "user_profile" | "user_journey"
      filters : {col: value, ...} AND-combined. {} = no col filter.
      window  : {start, end} — applied to the table's time column:
                 trans_log/pom_acr → reqDate,
                 user_journey      → event_time,
                 user_profile      → account_created_date.
                 Pass `null` to skip the time filter.
      limit   : optional row cap (default 5000 when no other constraint).

    Returns: {table, filters, window, count, sample_rows (capped 15)}
    """
    err = _check_table(table)
    if err:
        return err
    filters = filters or {}
    w = _normalize_window(window)
    effective_limit = limit if limit is not None else (5000 if not w and not filters else None)
    df = query_with_filters(table, filters, w, limit=effective_limit)
    return {
        "table": table,
        "filters": filters,
        "window": w,
        "count": int(len(df)),
        "sample_rows": _rows_jsonable(df, SAMPLE_CAP),
    }


# --------------------------- tool: aggregate -----------------------------

def tool_aggregate(
    table: str,
    dimensions: list[str],
    filters: dict | None = None,
    window: dict | None = None,
) -> dict:
    """Group rows in a table by `dimensions` and count (+ sum amount if available).

    Args:
      table      : one of the 4 tables (see ALLOWED_TABLES).
      dimensions : list of column names to group by.
      filters    : optional pre-filter {col: value}.
      window     : optional time window (uses the table's time column).

    Returns:
      {table, filters, window,
       total_count, total_amount_vnd (only when userChargeAmount exists),
       by_<dim>: [{<dim>, count, amount_vnd?}, ...]}
    """
    err = _check_table(table)
    if err:
        return err
    filters = filters or {}
    w = _normalize_window(window)
    df = query_with_filters(table, filters, w, limit=50_000 if (not w and not filters) else None)

    has_amount = "userChargeAmount" in df.columns
    base: dict[str, Any] = {
        "table": table,
        "filters": filters,
        "window": w,
        "total_count": int(len(df)),
    }
    if has_amount:
        base["total_amount_vnd"] = int(df["userChargeAmount"].sum()) if not df.empty else 0

    if df.empty:
        return {**base, **{f"by_{d}": [] for d in dimensions}}

    agg = aggregate_by(df, dimensions)
    return {**base, **{f"by_{d}": agg.get(d, []) for d in dimensions}}


# --------------------------- tool: compute_metrics -----------------------

def tool_compute_metrics(
    sql_predicate: str,
    window: dict | None = None,
    fraud_types: list[str] | None = None,
) -> dict:
    """Score a candidate rule.

    Args:
      sql_predicate : SELECT returning a `transID` column on trans_log
                      (can JOIN user_profile / user_journey).
                      e.g. "SELECT t.transID FROM trans_log t
                            JOIN user_profile up USING(userID)
                            WHERE t.bankType='international'
                              AND DATEDIFF(t.reqDate, up.account_created_date) <= 7"
      window        : optional truth-set time window
      fraud_types   : optional list of fraud_type codes to restrict truth set

    Returns: {precision, recall, f1, hit_count, total_fraud, total_flagged}
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
    w = _normalize_window(window)
    metrics = _compute_metrics(matched_ids, w, fraud_types)
    return {**metrics, "sql_predicate": sql_predicate}


# --------------------------- tool: raw_sql -------------------------------

def tool_raw_sql(sql: str) -> dict:
    """Execute a single READ-ONLY SELECT (any of the 4 tables, JOINs allowed).

    Returns: {columns, rows_sample (capped 15), row_count}
    """
    try:
        validate_sql(sql)
    except UnsafeSQLError as e:
        return {"error": f"unsafe sql: {e}"}
    try:
        df = warehouse_query(sql)
    except Exception as e:
        return {"error": f"query failed: {e}"}
    return {
        "columns": list(df.columns),
        "row_count": int(len(df)),
        "rows_sample": _rows_jsonable(df, ROWS_PREVIEW_CAP),
    }


# --------------------------- registry -----------------------------------

TOOL_REGISTRY: dict[str, Callable[..., dict]] = {
    "query_with_filters": tool_query_with_filters,
    "aggregate": tool_aggregate,
    "compute_metrics": tool_compute_metrics,
    "raw_sql": tool_raw_sql,
}


TOOL_REGISTRY_SPEC = """\
Available tools (call by name with the listed args; return value is a JSON dict).

Tables exposed to the agent:
  trans_log     : universe of all transactions (time col = reqDate)
  pom_acr       : confirmed-fraud subset (time col = reqDate; extras: fraud_type, is_loss, report_date)
  user_profile  : 1 row / user (identity + KYC/NFC + trust flags; time col = account_created_date)
  user_journey  : event log per user (time col = event_time)

Join order recommendation (per KB):
  trans_log/pom_acr  →  user_profile  →  user_journey
Join keys: userID across all four tables. transID links trans_log ↔ pom_acr.

1. query_with_filters(table, filters?, window?, limit?)
     table   : one of {trans_log, pom_acr, user_profile, user_journey}
     filters : {<column>: <value>, ...}   AND-combined exact match. {} = no filter.
     window  : {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} on the table's time column.
               Pass null to skip the time filter.
     limit   : optional cap (default 5000 when no filter+window).
   Returns: {count, sample_rows (<= 15)}

2. aggregate(table, dimensions, filters?, window?)
     table      : one of the 4 tables.
     dimensions : [<column>, ...]   group-by columns.
     filters    : optional pre-filter {col: value}.
     window     : optional time window (uses the table's time column).
   Returns: {total_count, total_amount_vnd (only when amount column exists),
             by_<dim>: [{<dim>, count, amount_vnd?}, ...]}

3. compute_metrics(sql_predicate, window?, fraud_types?)
     sql_predicate : single SELECT returning a `transID` column.
                     JOINs with user_profile / user_journey allowed.
                     Examples:
                       "SELECT transID FROM trans_log
                        WHERE bankType='international' AND userChargeAmount>=5000000"
                       "SELECT t.transID FROM trans_log t
                        JOIN user_profile up USING(userID)
                        WHERE t.bankType='international' AND t.userChargeAmount>=5000000
                          AND DATEDIFF(t.reqDate, up.account_created_date) <= 7"
                       "SELECT t.transID FROM trans_log t
                        JOIN user_profile up USING(userID)
                        WHERE t.bankType='international' AND t.userChargeAmount>=5000000
                          AND DATEDIFF(t.reqDate, up.account_created_date) <= 7
                          AND EXISTS (SELECT 1 FROM user_journey j
                                      WHERE j.userID=t.userID AND j.event_type='map_card'
                                        AND j.event_time<t.reqDate
                                        AND TIMESTAMPDIFF(HOUR, j.event_time, t.reqDate) <= 24)"
     window        : optional truth-set time window
     fraud_types   : optional ["CF","AT",...] to restrict truth set
   Returns: {precision, recall, f1, hit_count, total_fraud, total_flagged}

4. raw_sql(sql)
     sql : single READ-ONLY SELECT (writes blocked).
   Returns: {columns, row_count, rows_sample (<= 15)}
"""
