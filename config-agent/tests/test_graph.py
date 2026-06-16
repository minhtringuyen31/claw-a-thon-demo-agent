from unittest.mock import patch, MagicMock
from agent.graph import build_graph, should_retry


SAMPLE_STATE_BASE = {
    "raw_input": "test",
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
}


def test_should_retry_when_errors_and_under_max():
    state = {**SAMPLE_STATE_BASE, "validation_errors": ["error"], "retry_count": 0}
    assert should_retry(state) == "retry"


def test_should_retry_when_errors_and_at_max():
    state = {**SAMPLE_STATE_BASE, "validation_errors": ["error"], "retry_count": 2}
    assert should_retry(state) == "done"


def test_should_not_retry_when_no_errors():
    state = {**SAMPLE_STATE_BASE, "validation_errors": [], "retry_count": 0}
    assert should_retry(state) == "done"


def test_build_graph_returns_compiled_graph():
    graph = build_graph()
    assert graph is not None


def test_graph_has_correct_nodes():
    graph = build_graph()
    node_names = set(graph.nodes.keys())
    expected = {"intake_node", "planner_node", "dependency_resolver", "build_config_node", "validator_node", "output_node"}
    assert expected.issubset(node_names)


def test_graph_has_v3a_nodes():
    graph = build_graph()
    node_names = set(graph.nodes.keys())
    assert "clarify_node" in node_names
    assert "memory_load_node" in node_names
    assert "memory_save_node" in node_names


def test_should_clarify_true():
    from agent.graph import should_clarify
    state = {**SAMPLE_STATE_BASE, "needs_clarification": True}
    assert should_clarify(state) == "clarify"


def test_should_clarify_false():
    from agent.graph import should_clarify
    state = {**SAMPLE_STATE_BASE, "needs_clarification": False}
    assert should_clarify(state) == "proceed"
