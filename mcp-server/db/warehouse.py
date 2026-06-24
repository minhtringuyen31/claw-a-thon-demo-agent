"""Shared MySQL warehouse client for the MCP server."""
from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@lru_cache(maxsize=1)
def _engine() -> Engine:
    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = os.environ.get("MYSQL_PORT", "3306")
    db = os.environ.get("MYSQL_DB", "risk_db")
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "")
    dsn = (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}?charset=utf8mb4"
    )
    return create_engine(dsn, pool_pre_ping=True, pool_size=5, max_overflow=10)


def warehouse_query(sql: str) -> pd.DataFrame:
    with _engine().connect() as conn:
        return pd.read_sql(text(sql), conn)
