"""Unit tests for schema and llm mock."""
import json

from agent.schema import FraudConfig
from llm import MockLLM, get_llm


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
    out = MockLLM(role="build").complete_json("sys", "Requirement: " + json.dumps(req))
    var = out["events"][0]["variables"]
    assert var and var[0]["source"]["keyId"] == "count_txn_4h|${userid}"
