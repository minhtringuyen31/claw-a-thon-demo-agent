"""E2E API tests via FastAPI TestClient (MockLLM + MockConfigStore)."""
from fastapi.testclient import TestClient

import api.main as main
from api.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_reaches_awaiting_review():
    r = client.post("/chat", json={
        "message": "appid 123, reject nếu tổng tiền 24h > 10 triệu và account mới hơn 7 ngày",
    })
    data = r.json()
    assert data["status"] == "awaiting_review"
    assert data["final_output"]["events"]
    assert data["run_id"]


def test_get_run_and_approve_writes():
    run_id = client.post("/chat", json={"message": "appid 777, reject nếu amount > 5tr"}).json()["run_id"]

    got = client.get(f"/runs/{run_id}").json()
    assert got["status"] == "awaiting_review"

    rev = client.post(f"/runs/{run_id}/review", json={"decision": "approve", "approved_by": "tester"})
    body = rev.json()
    assert body["status"] == "completed"
    assert body["write_result"]["written"] is True


def test_review_reject_no_write():
    run_id = client.post("/chat", json={"message": "appid 888, review nếu amount > 1tr"}).json()["run_id"]
    rev = client.post(f"/runs/{run_id}/review", json={"decision": "reject"}).json()
    assert rev["status"] == "rejected"
    assert rev["write_result"]["written"] is False


def test_review_unknown_run_404():
    assert client.post("/runs/does-not-exist/review", json={"decision": "approve"}).status_code == 404


def test_from_report_path(monkeypatch):
    canned = {
        "run_id": "fraud-run-9", "status": "completed", "has_pattern": True,
        "final_pattern": {"description": "high amount", "sql_predicate": "amount > 5000000",
                          "signal_columns": ["amount"], "recommended_action": "reject",
                          "metrics": {"precision": 0.9, "recall": 0.7, "f1": 0.79}},
        "recommendation": "Đề xuất REJECT.",
    }
    monkeypatch.setattr(main, "fetch_report", lambda run_id, base_url=None: canned)
    r = client.post("/runs/from-report", json={"run_id": "fraud-run-9"})
    data = r.json()
    assert data["status"] == "awaiting_review"
    assert data["source_run_id"] == "fraud-run-9"
    assert data["final_output"]["events"]
