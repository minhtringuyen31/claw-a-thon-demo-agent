from agent.state import ConfigAgentState


def test_config_agent_state_fields():
    state: ConfigAgentState = {
        "raw_input": "test pattern",
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
        "output_file": "",
    }
    assert state["raw_input"] == "test pattern"
    assert state["operation"] == "create"
    assert state["retry_count"] == 0


def test_config_agent_state_v3a_fields():
    state: ConfigAgentState = {
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
        # V3a fields
        "session_id": "session-abc-123",
        "clarify_question": "",
        "clarification_answer": "",
        "needs_clarification": False,
        "clarify_history": [],
    }
    assert state["session_id"] == "session-abc-123"
    assert state["needs_clarification"] is False
    assert state["clarify_question"] == ""
    assert state["clarification_answer"] == ""
