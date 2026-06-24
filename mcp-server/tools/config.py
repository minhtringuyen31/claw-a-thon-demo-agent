"""Config-agent tools: rule config CRUD, session memory, fraud report fetching."""
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import quote_plus

import httpx


# ---------------------------------------------------------------------------
# Config store (MySQL rule_config table)
# ---------------------------------------------------------------------------

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
    "ALTER TABLE rule_config ADD COLUMN IF NOT EXISTS event_name VARCHAR(64) AFTER id",
    "ALTER TABLE rule_config ADD COLUMN IF NOT EXISTS description VARCHAR(255) AFTER event_name",
    "ALTER TABLE rule_config DROP COLUMN IF EXISTS app_id",
    "ALTER TABLE rule_config DROP COLUMN IF EXISTS name",
    "ALTER TABLE rule_config ADD INDEX IF NOT EXISTS idx_event (event_name)",
]


@lru_cache(maxsize=1)
def _db_engine():
    from sqlalchemy import create_engine, text
    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = os.environ.get("MYSQL_PORT", "3306")
    db = os.environ.get("MYSQL_DB", "risk_db")
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "")
    dsn = (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}?charset=utf8mb4"
    )
    engine = create_engine(dsn, pool_pre_ping=True, pool_size=5, max_overflow=10)
    with engine.begin() as conn:
        conn.execute(text(DDL_RULE_CONFIG))
        for sql in _MIGRATION_SQL:
            try:
                conn.execute(text(sql))
            except Exception:
                pass
    return engine


def _text(sql: str):
    from sqlalchemy import text
    return text(sql)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Session memory (file-based)
# ---------------------------------------------------------------------------

def _sessions_dir() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("SESSIONS_DIR", "./sessions"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path(key: str) -> pathlib.Path:
    safe = key.replace("/", "__").replace(":", "_")
    return _sessions_dir() / f"{safe}.json"


# ---------------------------------------------------------------------------
# Fraud report client
# ---------------------------------------------------------------------------

def _fraud_agent_url() -> str:
    return os.environ.get("FRAUD_AGENT_URL", "http://localhost:8080").rstrip("/")


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register(mcp) -> None:

    # --- Config store tools ---

    @mcp.tool()
    def get_config(event_name: str) -> dict:
        """Get the latest active rule config for an event_name from rule_config table.

        Returns: {"events": [config_json]} or {} if not found.
        """
        if not os.environ.get("MYSQL_HOST", "").strip():
            return {}
        with _db_engine().connect() as conn:
            row = conn.execute(
                _text(
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

    @mcp.tool()
    def save_config(
        event_name: str,
        description: str,
        config_json: dict,
        source_run_id: str | None = None,
        created_by: str | None = None,
    ) -> dict:
        """Save a new rule config record to the rule_config table.

        Returns: {written, row_id, target}
        """
        with _db_engine().begin() as conn:
            result = conn.execute(
                _text(
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

    @mcp.tool()
    def list_configs(limit: int = 100) -> dict:
        """List active rule configs ordered by most recent.

        Returns: {configs: [{id, event_name, description, config, status, source_run_id, created_by, created_at}]}
        """
        if not os.environ.get("MYSQL_HOST", "").strip():
            return {"configs": []}
        with _db_engine().connect() as conn:
            rows = conn.execute(
                _text(
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
        return {"configs": out}

    # --- Session memory tools ---

    @mcp.tool()
    def get_session(key: str) -> dict:
        """Load session state by key from the file-based session store.

        Returns: {found: bool, value: any}
        """
        p = _session_path(key)
        if p.exists():
            return {"found": True, "value": json.loads(p.read_text(encoding="utf-8"))}
        return {"found": False, "value": None}

    @mcp.tool()
    def save_session(key: str, value: dict) -> dict:
        """Persist session state to the file-based session store.

        Returns: {saved: true, key: str}
        """
        _session_path(key).write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"saved": True, "key": key}

    @mcp.tool()
    def append_session(key: str, item: dict) -> dict:
        """Append an item to a session list (creates list if key doesn't exist).

        Returns: {saved: true, key: str, length: int}
        """
        p = _session_path(key)
        existing: list = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        if not isinstance(existing, list):
            existing = [existing]
        existing.append(item)
        p.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"saved": True, "key": key, "length": len(existing)}

    # --- Fraud report fetcher ---

    @mcp.tool()
    def fetch_fraud_report(run_id: str, base_url: str | None = None) -> dict:
        """Fetch a completed fraud-analysis-agent run and return the reduced report.

        run_id: the fraud-analysis-agent run ID.
        base_url: optional override for the fraud-agent base URL.
        Returns: {run_id, status, has_pattern, final_pattern, recommendation}
        Raises error dict if run not found or not ready.
        """
        url = f"{(base_url or _fraud_agent_url()).rstrip('/')}/runs/{run_id}"
        try:
            resp = httpx.get(url, timeout=15.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"error": f"request failed: {e}"}

        run_out = resp.json()
        if run_out.get("status") not in ("completed", "running"):
            return {"error": f"run {run_id} not ready (status={run_out.get('status')})"}

        report = (run_out or {}).get("investigation_report") or {}
        fp = report.get("final_pattern") or {}
        metrics = fp.get("metrics") or {}
        return {
            "run_id": run_out.get("run_id", ""),
            "status": run_out.get("status", ""),
            "has_pattern": bool(fp.get("sql_predicate")),
            "final_pattern": {
                "description": fp.get("description", ""),
                "sql_predicate": fp.get("sql_predicate", ""),
                "signal_columns": fp.get("signal_columns", []),
                "recommended_action": fp.get("recommended_action", "none"),
                "metrics": {
                    "precision": metrics.get("precision", 0.0),
                    "recall": metrics.get("recall", 0.0),
                    "f1": metrics.get("f1", 0.0),
                },
            },
            "recommendation": report.get("recommendation", ""),
        }
