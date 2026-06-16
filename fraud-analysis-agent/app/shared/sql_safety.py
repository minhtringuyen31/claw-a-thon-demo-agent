"""SQL safety guard for LLM-generated queries."""
from __future__ import annotations

import re


_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|MERGE|GRANT|REVOKE)\b",
    re.I,
)


class UnsafeSQLError(Exception):
    pass


def validate_sql(sql: str) -> str:
    """Block write statements — the agent is read-only on the warehouse.

    Minimal guard. Production should add EXPLAIN cost check, row limit,
    query timeout.
    """
    if _FORBIDDEN.search(sql):
        raise UnsafeSQLError(f"SQL contains forbidden write command: {sql[:80]}")
    if sql.count(";") > 1:
        raise UnsafeSQLError("Multiple statements not allowed")
    return sql
