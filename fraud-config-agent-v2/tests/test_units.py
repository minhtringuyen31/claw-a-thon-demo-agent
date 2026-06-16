"""Unit tests for schema, llm mock, report client, config store."""
from agent.schema import FraudConfig
from llm import MockLLM, get_llm
from services.config_store import MockConfigStore
from services.fraud_report_client import MockReportClient, extract_report


# --- schema ---

VALID_CONFIG = {
    "events": [{
        "name": "payment", "actionCode": "REJECT",
        "rules": [{"name": "r1", "conditions": [
            {"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}]}],
    }]
}


def test_fraud_config_valid():
    cfg = FraudConfig(**VALID_CONFIG)
    assert cfg.events[0].actionCode == "REJECT"
    assert cfg.events[0].rules[0].conditions[0].field == "amount"


# --- llm mock ---

def test_get_llm_returns_mock_by_default():
    assert isinstance(get_llm(role="intake"), MockLLM)


def test_mock_intake_extracts_action_and_appid():
    out = MockLLM(role="intake").complete_json("sys", "appid 123, reject nếu amount lớn")
    assert out["app_id"] == "123"
    assert out["action"] == "REJECT"
    assert out["conditions"]


def test_mock_clarify_no_question():
    out = MockLLM(role="clarify").complete_json("sys", "{}")
    assert out["needs_clarification"] is False


def test_mock_build_adds_velocity_variable():
    req = {"app_id": "1", "event_name": "payment", "action": "REJECT",
           "conditions": [{"field": "count_txn_4h", "operator": "GREATER_THAN", "value": "10"}]}
    out = MockLLM(role="build").complete_json("sys", "Requirement: " + __import__("json").dumps(req))
    var = out["events"][0]["variables"]
    assert var and var[0]["source"]["keyId"] == "count_txn_4h|${userid}"


# --- report client ---

def _run_out(action="reject", sql="sum_amount_24h > 10000000"):
    return {
        "run_id": "run-1", "status": "completed",
        "investigation_report": {
            "recommendation": "Đề xuất REJECT các giao dịch khả nghi.",
            "final_pattern": {
                "description": "High velocity amount",
                "sql_predicate": sql,
                "signal_columns": ["sum_amount_24h"],
                "recommended_action": action,
                "metrics": {"precision": 0.9, "recall": 0.7, "f1": 0.79},
            },
        },
    }


def test_extract_report_reduces_fields():
    r = extract_report(_run_out())
    assert r["has_pattern"] is True
    assert r["final_pattern"]["recommended_action"] == "reject"
    assert r["final_pattern"]["metrics"]["precision"] == 0.9
    assert "REJECT" in r["recommendation"]


def test_mock_report_client_fetch():
    c = MockReportClient({"run-1": _run_out()})
    r = c.fetch_report("run-1")
    assert r["final_pattern"]["sql_predicate"].startswith("sum_amount_24h")


# --- config store ---

def test_mock_config_store_roundtrip():
    s = MockConfigStore()
    assert s.get_config("123") == {}
    res = s.save_config("123", "r", VALID_CONFIG, source_run_id="run-1", created_by="me")
    assert res["written"] is True and res["target"] == "mock"
    assert s.get_config("123") == VALID_CONFIG
