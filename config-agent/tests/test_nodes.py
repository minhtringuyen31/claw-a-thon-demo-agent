import json
from unittest.mock import patch, MagicMock
from agent.nodes import (
    intake_node, planner_node, dependency_resolver,
    build_config_node, validator_node, output_node,
    clarify_node, memory_load_node, memory_save_node,
)


SAMPLE_REQUIREMENT = {
    "app_id": "123",
    "profile_name": "Fraud Check App 123",
    "description": "Reject high amount",
    "conditions": [{"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}],
    "action": "REJECT",
}

SAMPLE_PLAN = {
    "profile_name": "Fraud Check App 123",
    "tiers": [{"name": "High Amount Tier", "priority": 1}],
    "rules": [{"name": "Reject High Amount", "tier": "High Amount Tier"}],
    "conditions_count": 1,
}

SAMPLE_JSON_DRAFT = {
    "events": [
        {
            "name": "payment",
            "description": "Reject high amount",
            "filter": "AND",
            "actionCode": "REJECT",
            "decisionCode": "",
            "variables": [],
            "rules": [
                {
                    "name": "Reject High Amount",
                    "description": "",
                    "conditions": [
                        {"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}
                    ],
                    "infoCode": "",
                }
            ],
        }
    ]
}


def make_state(**kwargs):
    base = {
        "raw_input": "appid 123, reject if amount > 5M",
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
        "output_file": "",
        "session_id": "test-session",
        "clarify_question": "",
        "clarification_answer": "",
        "needs_clarification": False,
        "clarify_history": [],
    }
    base.update(kwargs)
    return base


def test_intake_node_calls_llm():
    with patch("agent.nodes._call_llm", return_value=SAMPLE_REQUIREMENT) as mock_llm:
        state = make_state()
        result = intake_node(state)
        assert result["requirement"] == SAMPLE_REQUIREMENT
        mock_llm.assert_called_once()


def test_planner_node_calls_llm():
    with patch("agent.nodes._call_llm", return_value=SAMPLE_PLAN) as mock_llm:
        state = make_state(requirement=SAMPLE_REQUIREMENT)
        result = planner_node(state)
        assert result["plan"] == SAMPLE_PLAN
        mock_llm.assert_called_once()


def test_dependency_resolver_create():
    with patch("agent.nodes._mock_service") as mock_svc:
        mock_svc.get_profile.return_value = None
        state = make_state(requirement=SAMPLE_REQUIREMENT)
        result = dependency_resolver(state)
        assert result["operation"] == "create"
        assert result["existing_config"] == {}


def test_dependency_resolver_update():
    existing = {"name": "Old Profile"}
    with patch("agent.nodes._mock_service") as mock_svc:
        mock_svc.get_profile.return_value = existing
        state = make_state(requirement=SAMPLE_REQUIREMENT)
        result = dependency_resolver(state)
        assert result["operation"] == "update"
        assert result["existing_config"] == existing


def test_build_config_node_calls_llm():
    with patch("agent.nodes._call_llm", return_value=SAMPLE_JSON_DRAFT) as mock_llm:
        state = make_state(requirement=SAMPLE_REQUIREMENT, plan=SAMPLE_PLAN)
        result = build_config_node(state)
        assert result["json_draft"] == SAMPLE_JSON_DRAFT
        mock_llm.assert_called_once()


def test_validator_node_valid():
    state = make_state(json_draft=SAMPLE_JSON_DRAFT)
    result = validator_node(state)
    assert result["validation_errors"] == []
    assert "events" in result["final_output"]


def test_validator_node_invalid():
    state = make_state(json_draft={"invalid": "data"}, retry_count=0)
    result = validator_node(state)
    assert len(result["validation_errors"]) > 0
    assert result["retry_count"] == 1


def test_output_node_creates_file(tmp_path):
    with patch("agent.nodes._mock_service") as mock_svc:
        mock_svc.save_profile.return_value = {}
        with patch("agent.nodes.pathlib") as mock_pathlib:
            output_dir = tmp_path / "output"
            mock_pathlib.Path.return_value = output_dir / "Test_Profile_20260615_000000.json"
            # Use a simpler approach: patch the output dir inside output_node
            import agent.nodes as nodes_module
            original_pathlib = nodes_module.pathlib

            import pathlib as real_pathlib

            class PatchedPath:
                def __init__(self, *args):
                    self._path = real_pathlib.Path(*args) if args[0] != "output" else tmp_path / "output"

                def __truediv__(self, other):
                    return self._path / other

                def mkdir(self, **kwargs):
                    self._path.mkdir(**kwargs)

            with patch.object(nodes_module, "pathlib") as mock_pl:
                mock_pl.Path.side_effect = PatchedPath
                state = make_state(
                    requirement=SAMPLE_REQUIREMENT,
                    final_output={"name": "Test_Profile", "version": 1},
                )
                result = output_node(state)
                assert "output_file" in result
                assert result["output_file"].endswith(".json")


def test_clarify_node_needs_clarification():
    clarify_result = {"needs_clarification": True, "question": "Bạn muốn REJECT hay REVIEW?"}
    with patch("agent.nodes._call_llm", return_value=clarify_result):
        with patch("agent.nodes._memory_service"):
            state = make_state(requirement={"app_id": ""}, clarification_answer="")
            result = clarify_node(state)
    assert result["needs_clarification"] is True
    assert "REJECT" in result["clarify_question"]


def test_clarify_node_no_clarification_needed():
    clarify_result = {"needs_clarification": False, "question": ""}
    with patch("agent.nodes._call_llm", return_value=clarify_result):
        state = make_state(requirement=SAMPLE_REQUIREMENT, clarification_answer="")
        result = clarify_node(state)
    assert result["needs_clarification"] is False
    assert result["clarify_question"] == ""


def test_clarify_node_skips_when_answer_present():
    state = make_state(
        requirement=SAMPLE_REQUIREMENT,
        clarify_question="câu hỏi cũ",
        clarification_answer="tôi muốn reject",
    )
    with patch("agent.nodes._call_llm", return_value={"needs_clarification": False, "question": ""}):
        with patch("agent.nodes._memory_service"):
            result = clarify_node(state)
    assert result["needs_clarification"] is False
    assert len(result["clarify_history"]) == 1


def test_memory_load_node_returns_empty_when_no_data():
    from unittest.mock import MagicMock
    mock_svc = MagicMock()
    mock_svc.get.return_value = None
    with patch("agent.nodes._memory_service", mock_svc):
        state = make_state(session_id="session-abc")
        result = memory_load_node(state)
    assert result == {"clarify_history": []}


def test_memory_save_node_saves_profile_and_conversation():
    from unittest.mock import MagicMock
    mock_svc = MagicMock()
    with patch("agent.nodes._memory_service", mock_svc):
        state = make_state(
            session_id="session-abc",
            requirement=SAMPLE_REQUIREMENT,
            final_output={"events": []},
            output_file="output/test.json",
            clarification_answer="",
        )
        memory_save_node(state)
    mock_svc.append.assert_called_once()
    mock_svc.set.assert_called()
