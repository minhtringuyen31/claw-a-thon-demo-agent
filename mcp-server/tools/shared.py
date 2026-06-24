"""Shared warehouse tools — usable by both agents."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from db.sql_safety import UnsafeSQLError, validate_sql
from db.warehouse import warehouse_query

ALLOWED_TABLES = ("trans_log", "pom_acr", "user_profile", "user_journey")
TIME_COL_BY_TABLE: dict[str, str] = {
    "trans_log": "reqDate",
    "pom_acr": "reqDate",
    "user_profile": "account_created_date",
    "user_journey": "event_time",
}
SAMPLE_CAP = 15


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


def _rows(df: pd.DataFrame, n: int) -> list[dict]:
    return [
        {k: _jsonable(v) for k, v in row.items()}
        for _, row in df.head(n).iterrows()
    ]


def _normalize_window(window: dict | None) -> dict | None:
    if not window or "start" not in window or "end" not in window:
        return None
    return {"start": window["start"], "end": window["end"], "column": window.get("column")}


def _check_table(table: str) -> dict | None:
    if table not in ALLOWED_TABLES:
        return {"error": f"unknown table {table!r}; valid: {list(ALLOWED_TABLES)}"}
    return None


def _format_filter_value(val: Any) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    return f"'{str(val).replace(chr(39), chr(39)*2)}'"


def _qwf(table: str, filters: dict, window: dict | None, limit: int | None) -> pd.DataFrame:
    clauses: list[str] = []
    time_col = TIME_COL_BY_TABLE.get(table)
    if window and time_col:
        clauses.append(f"{time_col} >= '{window['start']}'")
        clauses.append(f"{time_col} <= '{window['end']} 23:59:59'")
    for col, val in filters.items():
        clauses.append(f"{col} = {_format_filter_value(val)}")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    limit_clause = f" LIMIT {limit}" if limit else ""
    return warehouse_query(f"SELECT * FROM {table}{where}{limit_clause}")


def register(mcp) -> None:
    @mcp.tool()
    def query_with_filters(
        table: str,
        filters: dict | None = None,
        window: dict | None = None,
        limit: int | None = None,
    ) -> dict:
        """Filter rows in any warehouse table by exact-match conditions.

        table: trans_log | pom_acr | user_profile | user_journey
        filters: {col: value} AND-combined exact match. {} = no filter.
        window: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} on the table's time column.
        limit: optional row cap (default 5000 when no filter+window).
        Returns: {table, filters, window, count, sample_rows (<=15)}
        """
        err = _check_table(table)
        if err:
            return err
        filters = filters or {}
        w = _normalize_window(window)
        eff_limit = limit if limit is not None else (5000 if not w and not filters else None)
        df = _qwf(table, filters, w, eff_limit)
        return {
            "table": table,
            "filters": filters,
            "window": w,
            "count": int(len(df)),
            "sample_rows": _rows(df, SAMPLE_CAP),
        }

    @mcp.tool()
    def aggregate(
        table: str,
        dimensions: list[str],
        filters: dict | None = None,
        window: dict | None = None,
    ) -> dict:
        """Group rows by dimensions and count (+sum userChargeAmount if available).

        table: one of the 4 warehouse tables.
        dimensions: list of columns to group by.
        filters: optional pre-filter {col: value}.
        window: optional time window on the table's time column.
        Returns: {total_count, total_amount_vnd?, by_<dim>: [{dim_val, count, amount_vnd?}]}
        """
        err = _check_table(table)
        if err:
            return err
        filters = filters or {}
        w = _normalize_window(window)
        df = _qwf(table, filters, w, 50_000 if not w and not filters else None)
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

        agg_result: dict[str, list] = {}
        for dim in dimensions:
            if dim not in df.columns:
                agg_result[f"by_{dim}"] = []
                continue
            if has_amount:
                agg_df = (
                    df.groupby(dim, dropna=False)
                    .agg(count=(dim, "size"), amount_vnd=("userChargeAmount", "sum"))
                    .reset_index()
                    .sort_values("amount_vnd", ascending=False)
                )
                agg_result[f"by_{dim}"] = [
                    {dim: _jsonable(r[dim]), "count": int(r["count"]), "amount_vnd": int(r["amount_vnd"])}
                    for _, r in agg_df.iterrows()
                ]
            else:
                agg_df = (
                    df.groupby(dim, dropna=False)
                    .size()
                    .reset_index(name="count")
                    .sort_values("count", ascending=False)
                )
                agg_result[f"by_{dim}"] = [
                    {dim: _jsonable(r[dim]), "count": int(r["count"])}
                    for _, r in agg_df.iterrows()
                ]
        return {**base, **agg_result}

    @mcp.tool()
    def raw_sql(sql: str) -> dict:
        """Execute a single read-only SELECT (JOINs across the 4 warehouse tables allowed).

        Returns: {columns, row_count, rows_sample (<=15)}
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
            "rows_sample": _rows(df, SAMPLE_CAP),
        }

    @mcp.tool()
    def get_schema(tables: list[str]) -> dict:
        """Return column metadata for warehouse tables via DESCRIBE.

        Valid tables: trans_log, pom_acr, user_profile, user_journey, rule_config.
        Returns: {table: [{column, dtype, nullable}]}
        """
        out: dict[str, list] = {}
        for t in tables:
            try:
                df = warehouse_query(f"DESCRIBE {t}")
                out[t] = [
                    {
                        "column": r["Field"],
                        "dtype": r["Type"],
                        "nullable": str(r["Null"]).upper() == "YES",
                    }
                    for _, r in df.iterrows()
                ]
            except Exception as e:
                out[t] = [{"error": str(e)}]
        return out
