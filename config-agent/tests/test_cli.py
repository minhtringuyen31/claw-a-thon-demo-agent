from unittest.mock import patch, MagicMock
from cli import run_cli


SAMPLE_FINAL_OUTPUT = {
    "id": None,
    "version": 1,
    "name": "Test Profile",
    "filter": "AND",
    "conditions": [],
    "tiers": [],
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
    }


def test_run_cli_success():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = make_mock_state(final_output=SAMPLE_FINAL_OUTPUT)
    with patch("cli.build_graph", return_value=mock_graph):
        result = run_cli("appid 123, reject if amount > 5M")
    assert "final_output" in result
    assert result["final_output"]["name"] == "Test Profile"
    assert "output_file" in result


def test_run_cli_failure():
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = make_mock_state(
        final_output={},
        validation_errors=["name field required"],
        json_draft={"bad": "data"},
    )
    with patch("cli.build_graph", return_value=mock_graph):
        result = run_cli("bad input")
    assert "_error" in result
    assert "_validation_errors" in result
