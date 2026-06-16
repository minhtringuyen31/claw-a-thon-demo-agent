"""Node-level tests with MockLLM + an injected MockConfigStore."""
import agent.nodes as nodes
from agent.nodes import (
    build_config_node, clarify_node, dependency_resolver, human_review_node,
    intake_node, update_conf_node, validator_node,
)
from services.config_store import MockConfigStore


def _state(**kw):
    base = {
        "raw_input": "", "source_type": "chat", "run_id": "", "fraud_report": {},
        "requirement": {}, "session_id": "", "clarify_question": "",
        "clarification_answer": "", "needs_clarification": False, "clarify_history": [],
        "operation": "create", "existing_config": {}, "dedup": {},
        "json_draft": {}, "validation_errors": [], "final_output": {}, "retry_count": 0,
        "approved_by": None, "review_decision": None, "output_file": "", "write_result": {},
    }
    base.update(kw)
    return base


def test_intake_chat():
    out = intake_node(_state(raw_input="appid 123, reject nếu amount > 5tr"))
    assert out["requirement"]["app_id"] == "123"
    assert out["requirement"]["action"] == "REJECT"


def test_intake_report():
    report = {
        "recommendation": "Đề xuất REJECT.",
        "final_pattern": {"description": "high amount", "sql_predicate": "amount > 5000000",
                          "signal_columns": ["amount"], "recommended_action": "reject", "metrics": {}},
    }
    out = intake_node(_state(source_type="report", fraud_report=report))
    assert out["requirement"]["action"] == "REJECT"


def test_clarify_proceeds():
    out = clarify_node(_state(requirement={"app_id": "1", "action": "REJECT",
                                           "conditions": [{"field": "amount"}]}))
    assert out["needs_clarification"] is False


def test_dependency_resolver_create_when_empty(monkeypatch):
    monkeypatch.setattr(nodes, "get_config_store", lambda: MockConfigStore())
    out = dependency_resolver(_state(requirement={"app_id": "999", "profile_name": "X",
                                                  "conditions": [{"field": "amount", "operator": "GREATER_THAN", "value": "1"}]}))
    assert out["operation"] == "create"
    assert out["dedup"]["found"] is False


def test_dependency_resolver_update_when_rule_exists(monkeypatch):
    store = MockConfigStore()
    store.save_config("123", "cfg", {"events": [{
        "name": "payment", "actionCode": "REJECT",
        "rules": [{"name": "High Amount", "conditions": [
            {"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}]}],
    }]})
    monkeypatch.setattr(nodes, "get_config_store", lambda: store)
    req = {"app_id": "123", "profile_name": "High Amount",
           "conditions": [{"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}]}
    out = dependency_resolver(_state(requirement=req))
    assert out["operation"] == "update"
    assert out["dedup"]["found"] is True
    assert out["dedup"]["event_name"] == "payment"


def test_build_config_velocity():
    req = {"app_id": "1", "event_name": "payment", "action": "REJECT",
           "conditions": [{"field": "sum_amount_24h", "operator": "GREATER_THAN", "value": "10000000"}]}
    out = build_config_node(_state(requirement=req))
    ev = out["json_draft"]["events"][0]
    assert ev["actionCode"] == "REJECT"
    assert ev["variables"][0]["source"]["keyId"] == "sum_amount_24h|${userid}"


def test_build_config_emits_appid_as_condition():
    req = {"app_id": "123", "event_name": "payment", "action": "REJECT",
           "conditions": [{"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}]}
    out = build_config_node(_state(requirement=req))
    conds = out["json_draft"]["events"][0]["rules"][0]["conditions"]
    # appID is the FIRST condition, and is not promoted to a variable.
    assert conds[0] == {"field": "appID", "operator": "EQUALS", "value": "123"}
    assert out["json_draft"]["events"][0]["variables"] == []
    # no top-level app_id field on the config
    assert "app_id" not in out["json_draft"]


def test_build_config_skips_appid_when_unknown():
    req = {"app_id": "unknown", "event_name": "payment", "action": "REVIEW",
           "conditions": [{"field": "amount", "operator": "GREATER_THAN", "value": "1"}]}
    out = build_config_node(_state(requirement=req))
    conds = out["json_draft"]["events"][0]["rules"][0]["conditions"]
    assert all(c["field"] not in ("appID", "appid") for c in conds)


def test_validator_forced_pass_on_valid():
    draft = {"events": [{"name": "payment", "actionCode": "REJECT",
             "rules": [{"name": "r", "conditions": [{"field": "amount", "operator": "GT", "value": "1"}]}]}]}
    out = validator_node(_state(json_draft=draft))
    assert out["validation_errors"] == []
    assert out["final_output"]["events"][0]["name"] == "payment"


def test_validator_forced_pass_on_garbage():
    out = validator_node(_state(json_draft={"totally": "wrong"}))
    assert out["validation_errors"] == []
    assert out["final_output"] == {"totally": "wrong"}


def test_human_review_is_noop():
    assert human_review_node(_state()) == {}


def test_update_conf_writes_on_approve(monkeypatch):
    store = MockConfigStore()
    monkeypatch.setattr(nodes, "get_config_store", lambda: store)
    out = update_conf_node(_state(
        review_decision="approve", approved_by="me",
        requirement={"app_id": "123", "profile_name": "R"},
        final_output={"events": []}, run_id="run-1",
    ))
    assert out["write_result"]["written"] is True
    assert store.get_config("123") == {"events": []}


def test_update_conf_skips_on_reject():
    out = update_conf_node(_state(review_decision="reject", final_output={"events": []}))
    assert out["write_result"]["written"] is False
