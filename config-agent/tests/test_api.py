from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

SAMPLE_FINAL_OUTPUT = {
    "events": [
        {
            "name": "payment",
            "description": "Test event",
            "filter": "AND",
            "actionCode": "REJECT",
            "decisionCode": "",
            "variables": [],
            "rules": [
                {
                    "name": "High Amount Rule",
                    "description": "",
                    "conditions": [{"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}],
                    "infoCode": "",
                }
            ],
        }
    ]
}


def make_mock_state(final_output=None, validation_errors=None, json_draft=None, output_file="output/test.json"):
    return {
        "raw_input": "test",
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": json_draft or {},
        "validation_errors": validation_errors or [],
        "final_output": final_output or {},
        "retry_count": 0,
        "output_file": output_file,
        "session_id": "test-session",
        "clarify_question": "",
        "clarification_answer": "",
        "needs_clarification": False,
        "clarify_history": [],
    }


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generate_config_success():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = make_mock_state(final_output=SAMPLE_FINAL_OUTPUT)
    with patch("api.main.build_graph", return_value=mock_graph):
        response = client.post("/generate-config", json={"input": "appid 123, reject if amount > 5M"})
    assert response.status_code == 200
    data = response.json()
    assert "final_output" in data


def test_generate_config_validation_failure():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = make_mock_state(
        final_output={},
        validation_errors=["name field required"],
        json_draft={"bad": "data"},
    )
    with patch("api.main.build_graph", return_value=mock_graph):
        response = client.post("/generate-config", json={"input": "bad input"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "validation_errors" in detail


def test_generate_config_empty_input():
    response = client.post("/generate-config", json={"input": ""})
    assert response.status_code == 422


def test_chat_clarify_response():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        **make_mock_state(),
        "needs_clarification": True,
        "clarify_question": "Bạn muốn REJECT hay REVIEW?",
        "session_id": "abc-123",
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        response = client.post("/chat", json={
            "session_id": "abc-123",
            "message": "chặn giao dịch lạ",
            "clarification_answer": "",
        })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "clarify"
    assert "question" in data
    assert data["session_id"] == "abc-123"


def test_chat_done_response():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        **make_mock_state(final_output=SAMPLE_FINAL_OUTPUT),
        "needs_clarification": False,
        "clarify_question": "",
        "session_id": "abc-123",
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        response = client.post("/chat", json={
            "session_id": "abc-123",
            "message": "appid 123, reject nếu amount > 5M",
            "clarification_answer": "",
        })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "done"
    assert "final_output" in data


def test_chat_validation_error():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        **make_mock_state(validation_errors=["name required"], json_draft={}),
        "needs_clarification": False,
        "clarify_question": "",
        "session_id": "abc-123",
    }
    with patch("api.main.build_graph", return_value=mock_graph):
        response = client.post("/chat", json={
            "session_id": "abc-123",
            "message": "bad input",
            "clarification_answer": "",
        })
    assert response.status_code == 200
    assert response.json()["status"] == "error"
