"""Client for pulling a completed fraud-analysis-agent run by run_id.

Contract (from fraud-analysis-agent GET /runs/{run_id} → RunOut):
    investigation_report.final_pattern.{description, sql_predicate,
        signal_columns, recommended_action, metrics.{precision,recall,f1}}
    investigation_report.recommendation

We deliberately consume `final_pattern` + `recommendation` — NOT `rule_json` —
so v2 reasons the config itself rather than passing through a SQL predicate.
"""
from __future__ import annotations

import os

import httpx


class ReportNotReady(Exception):
    pass


def _base_url(override: str | None = None) -> str:
    return (override or os.environ.get("FRAUD_AGENT_URL") or "http://localhost:8000").rstrip("/")


def extract_report(run_out: dict) -> dict:
    """Reduce a RunOut payload to the fields v2 reasons over."""
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


def fetch_report(run_id: str, base_url: str | None = None, timeout: float = 15.0) -> dict:
    """GET /runs/{run_id} and return the reduced report. Raises if not completed."""
    url = f"{_base_url(base_url)}/runs/{run_id}"
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    run_out = resp.json()
    if run_out.get("status") not in ("completed", "running"):
        raise ReportNotReady(f"run {run_id} status={run_out.get('status')}")
    if not (run_out.get("investigation_report") or {}).get("final_pattern"):
        # run completed but no pattern (no_action) — still return reduced shell
        pass
    return extract_report(run_out)


class MockReportClient:
    """In-memory report source for tests/demo. Seeded with canned RunOut dicts."""

    def __init__(self, runs: dict[str, dict] | None = None):
        self._runs = runs or {}

    def set(self, run_id: str, run_out: dict) -> None:
        self._runs[run_id] = run_out

    def fetch_report(self, run_id: str, base_url: str | None = None) -> dict:
        if run_id not in self._runs:
            raise ReportNotReady(f"run {run_id} not found")
        return extract_report(self._runs[run_id])
