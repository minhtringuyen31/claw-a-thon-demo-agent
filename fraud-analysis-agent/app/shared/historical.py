"""Query pom_acr for historical fraud and aggregate the result.

The aggregates are designed to feed hypothesis_node: distributions, top
values, quantiles — concrete numbers it can ground threshold choices on
instead of guessing.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from app.shared.warehouse import warehouse_query


TOP_K = 10
DEFAULT_SAMPLE = 30


# Time column per table — used by query_with_filters to apply the window.
# Tables not in this map skip the time filter when window is provided.
TIME_COL_BY_TABLE: dict[str, str | None] = {
    "trans_log": "reqDate",
    "pom_acr": "reqDate",
    "user_profile": "account_created_date",   # snapshot; time filter optional
    "user_journey": "event_time",
}


def aggregate_by(df: pd.DataFrame, dimensions: list[str]) -> dict[str, list[dict]]:
    """Count + (if present) sum userChargeAmount per value per column.

    Returns {dim: [{<dim>: value, "count": int, "amount_vnd": int}, ...]}
    sorted by amount_vnd desc (or count desc if no amount column).
    Missing columns return [].
    """
    if df.empty:
        return {dim: [] for dim in dimensions}
    has_amount = "userChargeAmount" in df.columns
    out: dict[str, list[dict]] = {}
    for dim in dimensions:
        if dim not in df.columns:
            out[dim] = []
            continue
        if has_amount:
            agg = (
                df.groupby(dim, dropna=False)
                .agg(count=(dim, "size"), amount_vnd=("userChargeAmount", "sum"))
                .reset_index()
                .sort_values("amount_vnd", ascending=False)
            )
            out[dim] = [
                {
                    dim: _jsonable(row[dim]),
                    "count": int(row["count"]),
                    "amount_vnd": int(row["amount_vnd"]),
                }
                for _, row in agg.iterrows()
            ]
        else:
            agg = (
                df.groupby(dim, dropna=False)
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
            )
            out[dim] = [
                {dim: _jsonable(row[dim]), "count": int(row["count"])}
                for _, row in agg.iterrows()
            ]
    return out


def count_by(df: pd.DataFrame, dimensions: list[str]) -> dict[str, list[dict]]:
    """Count rows per value for each requested column.

    Returns `{dim: [{<dim>: value, "n": int}, ...]}` sorted by count desc.
    Missing columns return `[]` for that dim.
    """
    out: dict[str, list[dict]] = {}
    if df.empty:
        return {dim: [] for dim in dimensions}
    for dim in dimensions:
        if dim not in df.columns:
            out[dim] = []
            continue
        counts = (
            df.groupby(dim, dropna=False)
            .size()
            .reset_index(name="n")
            .sort_values("n", ascending=False)
        )
        out[dim] = [
            {dim: _jsonable(row[dim]), "n": int(row["n"])}
            for _, row in counts.iterrows()
        ]
    return out


def _format_filter_value(val: Any) -> str:
    """Render a Python value as a SQL literal."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val).replace("'", "''")
    return f"'{s}'"


def query_with_filters(
    table: str,
    filters: dict,
    window: dict | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """SELECT * FROM <table> WHERE <filters> AND <window on time col>.

    Time column is picked per-table from TIME_COL_BY_TABLE:
      - trans_log / pom_acr : reqDate
      - user_journey        : event_time
      - user_profile        : account_created_date (window optional)
    Tables not in the map skip the time filter.

    Filters are AND-combined exact-match. Empty filters + no window =
    `SELECT * FROM table LIMIT <limit>`.
    """
    clauses: list[str] = []
    time_col = TIME_COL_BY_TABLE.get(table)
    if window and time_col:
        clauses.append(f"{time_col} >= '{window['start']}'")
        clauses.append(f"{time_col} <= '{window['end']} 23:59:59'")
    for col, val in filters.items():
        clauses.append(f"{col} = {_format_filter_value(val)}")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    limit_clause = f" LIMIT {limit}" if limit else ""
    sql = f"SELECT * FROM {table}{where}{limit_clause}"
    return warehouse_query(sql)


def query_pom_acr(fraud_types: list[str], window: dict) -> pd.DataFrame:
    """SELECT * FROM pom_acr filtered by fraud_type IN (...) AND window."""
    if not fraud_types:
        return pd.DataFrame()
    types_csv = ", ".join(f"'{_escape(t)}'" for t in fraud_types)
    sql = (
        f"SELECT * FROM pom_acr "
        f"WHERE fraud_type IN ({types_csv}) "
        f"AND reqDate >= '{window['start']}' "
        f"AND reqDate <= '{window['end']} 23:59:59'"
    )
    return warehouse_query(sql)


def aggregate_pom_acr(
    df: pd.DataFrame,
    sample_n: int = DEFAULT_SAMPLE,
    top_k: int = TOP_K,
) -> dict:
    if df.empty:
        return _empty_aggregate()

    df = df.copy()
    df["reqDate"] = pd.to_datetime(df["reqDate"])
    df["_hour"] = df["reqDate"].dt.hour
    df["_dow"] = df["reqDate"].dt.day_name()

    loss_mask = df["is_loss"] == 1 if "is_loss" in df.columns else pd.Series(True, index=df.index)
    amt = df["userChargeAmount"]

    return {
        "total_cases": int(len(df)),
        "total_loss_vnd": int(df.loc[loss_mask, "userChargeAmount"].sum()),
        "top_channels": _top(df, "integratedChannel", top_k),
        "top_banks": _top(df, "bankCode", top_k),
        "top_apps": _top(df, "appName", top_k),
        "top_categories": _top(df, "reportCat", top_k),
        "top_bank_types": _top(df, "bankType", top_k),
        "fraud_type_breakdown": _top(df, "fraud_type", top_k),
        "amount_quantiles": {
            "p25": int(amt.quantile(0.25)),
            "p50": int(amt.quantile(0.50)),
            "p75": int(amt.quantile(0.75)),
            "p95": int(amt.quantile(0.95)),
            "max": int(amt.max()),
        },
        "hour_of_day": [
            {"hour": h, "n": int((df["_hour"] == h).sum())}
            for h in range(24)
        ],
        "day_of_week": [
            {"dow": d, "n": int((df["_dow"] == d).sum())}
            for d in ["Monday", "Tuesday", "Wednesday", "Thursday",
                      "Friday", "Saturday", "Sunday"]
        ],
        "sample_rows": _sample_rows(df.drop(columns=["_hour", "_dow"]), sample_n),
    }


def _top(df: pd.DataFrame, col: str, n: int) -> list[dict]:
    if df.empty or col not in df.columns:
        return []
    agg = (
        df.groupby(col)
        .agg(n=("userChargeAmount", "count"), loss_vnd=("userChargeAmount", "sum"))
        .reset_index()
        .sort_values("n", ascending=False)
        .head(n)
    )
    return [
        {col: row[col], "n": int(row["n"]), "loss_vnd": int(row["loss_vnd"])}
        for _, row in agg.iterrows()
    ]


def _sample_rows(df: pd.DataFrame, n: int) -> list[dict]:
    out = []
    for _, row in df.head(n).iterrows():
        out.append({k: _jsonable(v) for k, v in row.items()})
    return out


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return v.isoformat() if hasattr(v, "isoformat") else str(v)
    if isinstance(v, float) and pd.isna(v):
        return None
    # numpy scalars → python scalars (json can't serialize np.int64 / np.float64)
    if hasattr(v, "item") and not isinstance(v, str):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    return v


def _escape(s: str) -> str:
    return s.replace("'", "''")


def _empty_aggregate() -> dict:
    return {
        "total_cases": 0,
        "total_loss_vnd": 0,
        "top_channels": [],
        "top_banks": [],
        "top_apps": [],
        "top_categories": [],
        "top_bank_types": [],
        "fraud_type_breakdown": [],
        "amount_quantiles": {},
        "hour_of_day": [],
        "day_of_week": [],
        "sample_rows": [],
    }
