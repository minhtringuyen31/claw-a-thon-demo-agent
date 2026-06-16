"""E2E tests for the Risk Analysis Agent service.

Uses FastAPI TestClient + mocked warehouse_query + mocked LLM so the suite
runs offline without any database or API key.

Run:
  uv run pytest -v
"""
from __future__ import annotations

import os
import time
import uuid
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

os.environ.setdefault("CHECKPOINTER_BACKEND", "sqlite")
os.environ.setdefault(
    "SQLITE_CHECKPOINT_PATH",
    f"/tmp/risk_agent_test_{uuid.uuid4().hex[:8]}.db",
)
# Dummy LLM credentials so OpenAILLM.__init__ doesn't raise at import time.
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:9999")
os.environ.setdefault("LLM_MODEL", "test-model")


SAMPLE_EMAIL = """\
From: fraud-ops@company.vn
Subject: [URGENT] Suspicious high-value night transactions

3 cases of reused devices, high amounts, night hours. Analyze last 90 days.
"""

# --- mock payloads --------------------------------------------------------

_INGEST_RESPONSE = {
    "reported_cases": [
        {
            "appID": 149, "pmcID": 36, "transType": 15,
            "transID": "250103000921213",
            "reqDate": "2026-04-03 12:28:47",
            "userChargeAmount": 10_000_000,
            "integratedChannel": "CREDIT CARD",
            "bankCode": "ZPCC", "bankType": "international",
            "fraud_type": "CF",
            "appName": "Mobile Payment", "reportCat": "Game",
        }
    ],
    "severity": "high",
    "time_hint": "last 90 days",
    "raw_summary": "Chargeback fraud trên thẻ quốc tế.",
}

_ANOMALY_RESPONSE = {
    "is_anomalous": True,
    "confidence": 0.85,
    "reasoning": "Báo cáo lệch baseline ở bankType international.",
    "evidence": [
        {
            "filters": {"bankType": "international"},
            "observation": "100% international vs baseline ~45%",
        }
    ],
}

_BASELINE_DF = pd.DataFrame([
    {
        "transID": "B001", "appID": 100, "pmcID": 39, "transType": 15,
        "reqDate": "2026-06-06 10:00:00", "userChargeAmount": 5_000_000,
        "integratedChannel": "domestic_napas", "bankType": "domestic_napas",
        "bankCode": "ZPVCB", "fraud_type": "CF", "appName": "App A",
        "reportCat": "Finance",
    },
    {
        "transID": "B002", "appID": 200, "pmcID": 36, "transType": 15,
        "reqDate": "2026-06-07 11:00:00", "userChargeAmount": 3_000_000,
        "integratedChannel": "CREDIT CARD", "bankType": "international",
        "bankCode": "ZPCC", "fraud_type": "CF", "appName": "App B",
        "reportCat": "Game",
    },
])


# --- fixtures -------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    with (
        patch("app.llm.base.OpenAI"),
        patch(
            "app.tools.warehouse.warehouse_query",
            return_value=_BASELINE_DF,
        ),
    ):
        from fastapi.testclient import TestClient
        from app.service import app as fastapi_app

        # Patch LLM responses at the node level so we control each call.
        def _fake_complete_json(system, user):
            if "fraud-report parser" in system:
                return _INGEST_RESPONSE
            if "ACR (account-risk)" in system:
                return _ANOMALY_RESPONSE
            return {}

        with patch(
            "app.llm.base.OpenAILLM.complete_json",
            side_effect=_fake_complete_json,
        ):
            with TestClient(fastapi_app) as c:
                yield c


# --- helpers --------------------------------------------------------------

def _wait_status(client, run_id: str, target: str, timeout: float = 15.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/runs/{run_id}").json()
        if last["status"] == target:
            return last
        time.sleep(0.2)
    raise TimeoutError(
        f"run {run_id} did not reach '{target}', last: {last}"
    )


# --- tests ----------------------------------------------------------------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_run_completes_with_anomaly(client):
    resp = client.post("/runs", json={
        "source_type": "email",
        "raw_input": SAMPLE_EMAIL,
    })
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]

    r = _wait_status(client, run_id, "completed")
    assert r["anomaly_decision"]["is_anomalous"] is True
    assert r["anomaly_decision"]["confidence"] > 0


def test_run_completes_with_normal(client):
    normal_resp = {**_ANOMALY_RESPONSE, "is_anomalous": False, "confidence": 0.9}

    def _fake_normal(system, user):
        if "fraud-report parser" in system:
            return _INGEST_RESPONSE
        if "ACR (account-risk)" in system:
            return normal_resp
        return {}

    with patch(
        "app.llm.base.OpenAILLM.complete_json",
        side_effect=_fake_normal,
    ):
        resp = client.post("/runs", json={
            "source_type": "postmortem",
            "raw_input": SAMPLE_EMAIL,
        })
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]
        r = _wait_status(client, run_id, "completed")
        assert r["anomaly_decision"]["is_anomalous"] is False


def test_list_runs(client):
    runs = client.get("/runs").json()
    assert isinstance(runs, list)
    assert len(runs) >= 1


def test_trigger_email_endpoint(client):
    resp = client.post("/triggers/email", json={
        "subject": "Suspicious transactions",
        "sender": "fraud-ops@company.vn",
        "body": "3 cases of reused devices.",
    })
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    r = _wait_status(client, run_id, "completed")
    assert "anomaly_decision" in r


def test_trigger_postmortem_endpoint(client):
    resp = client.post("/triggers/postmortem", json={
        "incident_id": "INC-001",
        "summary": "High-amount night frauds",
        "record": {"loss_vnd": 120_000_000, "cases": ["c001", "c002"]},
    })
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    r = _wait_status(client, run_id, "completed")
    assert "anomaly_decision" in r


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))