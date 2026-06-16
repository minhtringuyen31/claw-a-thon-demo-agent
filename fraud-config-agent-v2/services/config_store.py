"""Config store — read existing event config + write approved config.

Each record corresponds to the config of ONE event (event_name).
An event has multiple rules inside config_json.

Two interchangeable implementations:
    MySQLConfigStore   writes to the hosted risk_db `rule_config` table
    MockConfigStore    in-memory dict (CI / tests / demo)

Interface:
    get_config(event_name) -> dict   latest event config_json, or {}
    save_config(event_name, description, config_json, source_run_id, created_by) -> dict
    list_configs(limit) -> list[dict]
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import quote_plus

DDL_RULE_CONFIG = """
CREATE TABLE IF NOT EXISTS rule_config (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_name    VARCHAR(64),
    description   VARCHAR(255),
    config_json   JSON,
    status        TINYINT DEFAULT 1,
    source_run_id VARCHAR(64),
    created_by    VARCHAR(64),
    created_at    DATETIME,
    INDEX idx_event (event_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_MIGRATION_SQL = [
    # Add event_name if missing (old schema had app_id instead)
    """ALTER TABLE rule_config ADD COLUMN IF NOT EXISTS event_name VARCHAR(64) AFTER id""",
    # Add description if missing (old schema had name)
    """ALTER TABLE rule_config ADD COLUMN IF NOT EXISTS description VARCHAR(255) AFTER event_name""",
    # Drop obsolete columns if they exist
    """ALTER TABLE rule_config DROP COLUMN IF EXISTS app_id""",
    """ALTER TABLE rule_config DROP COLUMN IF EXISTS name""",
    # Add index if missing
    """ALTER TABLE rule_config ADD INDEX IF NOT EXISTS idx_event (event_name)""",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MySQLConfigStore:
    def __init__(self):
        from sqlalchemy import text
        self._text = text
        self._engine = self._make_engine()
        with self._engine.begin() as conn:
            conn.execute(text(DDL_RULE_CONFIG))
            # Run migrations for existing tables with old schema.
            for sql in _MIGRATION_SQL:
                try:
                    conn.execute(text(sql))
                except Exception:
                    pass  # column may already exist or not exist — ignore

    @staticmethod
    def _make_engine():
        from sqlalchemy import create_engine
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

    def get_config(self, event_name: str) -> dict:
        """Return the latest event config for event_name, wrapped as {"events": [ev]} for compat."""
        with self._engine.connect() as conn:
            row = conn.execute(
                self._text(
                    "SELECT config_json FROM rule_config "
                    "WHERE event_name = :ev AND status = 1 "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"ev": event_name},
            ).scalar()
        if not row:
            return {}
        ev = json.loads(row) if isinstance(row, (str, bytes)) else row
        return {"events": [ev]}

    def list_configs(self, limit: int = 100) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                self._text(
                    "SELECT id, event_name, description, config_json, status, "
                    "source_run_id, created_by, created_at FROM rule_config "
                    "WHERE status = 1 ORDER BY id DESC LIMIT :lim"
                ),
                {"lim": limit},
            ).mappings().all()
        out = []
        for r in rows:
            cfg = r["config_json"]
            if isinstance(cfg, (str, bytes)):
                cfg = json.loads(cfg)
            created = r["created_at"]
            out.append({
                "id": r["id"],
                "event_name": r["event_name"],
                "description": r["description"],
                "config": cfg,
                "status": r["status"],
                "source_run_id": r["source_run_id"],
                "created_by": r["created_by"],
                "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
            })
        return out

    def save_config(self, event_name: str, description: str, config_json: dict,
                    source_run_id: str | None = None, created_by: str | None = None) -> dict:
        with self._engine.begin() as conn:
            result = conn.execute(
                self._text(
                    "INSERT INTO rule_config "
                    "(event_name, description, config_json, status, source_run_id, created_by, created_at) "
                    "VALUES (:ev, :desc, :cfg, 1, :run, :by, :ts)"
                ),
                {
                    "ev": event_name,
                    "desc": description,
                    "cfg": json.dumps(config_json, ensure_ascii=False),
                    "run": source_run_id,
                    "by": created_by,
                    "ts": _now(),
                },
            )
            row_id = result.lastrowid
        return {"written": True, "row_id": row_id, "target": "mysql:rule_config"}


class MockConfigStore:
    def __init__(self):
        self._store: dict[str, dict] = {}
        self._rows: list[dict] = []

    def get_config(self, event_name: str) -> dict:
        ev = self._store.get(event_name)
        return {"events": [ev]} if ev else {}

    def list_configs(self, limit: int = 100) -> list[dict]:
        out = []
        for r in reversed(self._rows[-limit:]):
            out.append({
                "id": r["id"],
                "event_name": r["event_name"],
                "description": r["description"],
                "config": r["config_json"],
                "status": 1,
                "source_run_id": r.get("source_run_id"),
                "created_by": r.get("created_by"),
                "created_at": r.get("created_at"),
            })
        return out

    def save_config(self, event_name: str, description: str, config_json: dict,
                    source_run_id: str | None = None, created_by: str | None = None) -> dict:
        self._store[event_name] = config_json
        row_id = len(self._rows) + 1
        self._rows.append({
            "id": row_id,
            "event_name": event_name,
            "description": description,
            "config_json": config_json,
            "source_run_id": source_run_id,
            "created_by": created_by,
            "created_at": _now().isoformat(),
        })
        return {"written": True, "row_id": row_id, "target": "mock"}


@lru_cache(maxsize=1)
def get_config_store():
    """Real store only when MYSQL_HOST is set; MockConfigStore otherwise."""
    if os.environ.get("MYSQL_HOST", "").strip():
        return MySQLConfigStore()
    return MockConfigStore()