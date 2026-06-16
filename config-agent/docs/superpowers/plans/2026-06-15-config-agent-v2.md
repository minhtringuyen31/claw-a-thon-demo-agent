# Config Agent V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild fraud rule suggestion agent với 6 nodes (intake → planner → dependency_resolver → build_config → validator → output), MockConfigService, và LLM via GreenNode AIP.

**Architecture:** LangGraph pipeline tuyến tính, validator có retry loop tối đa 2x về build_config. dependency_resolver dùng MockConfigService (in-memory) để quyết định create vs update. LLM dùng OpenAI SDK trỏ vào GreenNode AIP endpoint.

**Tech Stack:** Python 3.11+, LangGraph, OpenAI SDK (GreenNode AIP), Pydantic v2, FastAPI, python-dotenv

---

## File Map

| File | Responsibility |
|------|----------------|
| `agent/state.py` | `ConfigAgentState` TypedDict |
| `agent/schema.py` | Pydantic models (unchanged) |
| `agent/prompts.py` | `INTAKE_PROMPT`, `PLANNER_PROMPT`, `BUILD_CONFIG_PROMPT` |
| `services/__init__.py` | empty |
| `services/mock_config_service.py` | `MockConfigService` in-memory store |
| `agent/nodes.py` | 6 node functions |
| `agent/graph.py` | LangGraph graph + `should_retry` |
| `cli.py` | CLI với `-o` flag |
| `api/main.py` | FastAPI endpoint |
| `output/.gitkeep` | folder lưu JSON output |

---

### Task 1: Xóa code cũ, tạo scaffold

**Files:**
- Delete: `agent/nodes.py`, `agent/graph.py`, `agent/state.py`, `agent/prompts.py`
- Create: `services/__init__.py`, `output/.gitkeep`

- [ ] **Step 1: Xóa các file cũ sẽ rebuild**

```bash
rm agent/nodes.py agent/graph.py agent/state.py agent/prompts.py
```

- [ ] **Step 2: Tạo services package và output folder**

```bash
mkdir -p services output
touch services/__init__.py output/.gitkeep
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove old agent files, scaffold services/ and output/"
```

---

### Task 2: ConfigAgentState

**Files:**
- Create: `agent/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_state.py -v
```

Expected: `ImportError: cannot import name 'ConfigAgentState'`

- [ ] **Step 3: Implement**

```python
# agent/state.py
from typing import TypedDict


class ConfigAgentState(TypedDict):
    raw_input: str
    requirement: dict        # output của intake_node
    plan: dict               # output của planner_node
    existing_config: dict    # kết quả query mock config-service
    operation: str           # "create" hoặc "update"
    json_draft: dict         # output của build_config_node
    validation_errors: list  # Pydantic errors nếu có
    final_output: dict       # validated JSON config
    retry_count: int
    output_file: str         # path file đã lưu
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_state.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/state.py tests/test_state.py
git commit -m "feat: add ConfigAgentState TypedDict"
```

---

### Task 3: MockConfigService

**Files:**
- Create: `services/mock_config_service.py`
- Create: `tests/test_mock_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mock_service.py
from services.mock_config_service import MockConfigService


def test_get_profile_returns_none_when_not_exists():
    svc = MockConfigService()
    assert svc.get_profile("999") is None


def test_save_and_get_profile():
    svc = MockConfigService()
    profile = {"id": None, "name": "Test", "filter": "AND", "conditions": [], "tiers": []}
    saved = svc.save_profile("123", profile)
    assert saved["app_id"] == "123"
    result = svc.get_profile("123")
    assert result is not None
    assert result["name"] == "Test"


def test_save_overwrites_existing():
    svc = MockConfigService()
    svc.save_profile("123", {"name": "Old", "filter": "AND", "conditions": [], "tiers": []})
    svc.save_profile("123", {"name": "New", "filter": "AND", "conditions": [], "tiers": []})
    assert svc.get_profile("123")["name"] == "New"


def test_get_all_profiles():
    svc = MockConfigService()
    svc.save_profile("1", {"name": "A", "filter": "AND", "conditions": [], "tiers": []})
    svc.save_profile("2", {"name": "B", "filter": "AND", "conditions": [], "tiers": []})
    assert len(svc.get_all_profiles()) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_mock_service.py -v
```

Expected: `ImportError: cannot import name 'MockConfigService'`

- [ ] **Step 3: Implement**

```python
# services/mock_config_service.py
from datetime import datetime


class MockConfigService:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def get_profile(self, app_id: str) -> dict | None:
        return self._store.get(app_id)

    def save_profile(self, app_id: str, profile: dict) -> dict:
        record = {**profile, "app_id": app_id, "saved_at": datetime.utcnow().isoformat()}
        self._store[app_id] = record
        return record

    def get_all_profiles(self) -> list[dict]:
        return list(self._store.values())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_mock_service.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/mock_config_service.py tests/test_mock_service.py
git commit -m "feat: add MockConfigService with in-memory store"
```

---

### Task 4: Pydantic schema (unchanged)

**Files:**
- Verify: `agent/schema.py` — giữ nguyên từ MVP

- [ ] **Step 1: Verify schema tests vẫn pass**

```bash
.venv/bin/python -m pytest tests/test_schema.py -v
```

Expected: All 6 tests PASS (không cần thay đổi gì)

---

### Task 5: LLM Prompts

**Files:**
- Create: `agent/prompts.py`
- Create: `tests/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompts.py
from agent.prompts import INTAKE_PROMPT, PLANNER_PROMPT, BUILD_CONFIG_PROMPT


def test_intake_prompt_has_required_instructions():
    assert "JSON" in INTAKE_PROMPT
    assert "app_id" in INTAKE_PROMPT
    assert "conditions" in INTAKE_PROMPT
    assert "action" in INTAKE_PROMPT


def test_planner_prompt_has_required_instructions():
    assert "JSON" in PLANNER_PROMPT
    assert "tiers" in PLANNER_PROMPT
    assert "rules" in PLANNER_PROMPT
    assert "{requirement}" in PLANNER_PROMPT


def test_build_config_prompt_has_placeholders():
    assert "{requirement}" in BUILD_CONFIG_PROMPT
    assert "{plan}" in BUILD_CONFIG_PROMPT
    assert "{operation}" in BUILD_CONFIG_PROMPT
    assert "{existing_config}" in BUILD_CONFIG_PROMPT
    assert "null" in BUILD_CONFIG_PROMPT
    assert "tiers" in BUILD_CONFIG_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_prompts.py -v
```

Expected: `ImportError: cannot import name 'INTAKE_PROMPT'`

- [ ] **Step 3: Implement**

```python
# agent/prompts.py

INTAKE_PROMPT = """You are a fraud rule analyst. Extract structured intent from a free-text fraud pattern.

Return ONLY valid JSON with this exact structure:
{
  "app_id": "<appid value or null if not mentioned>",
  "profile_name": "<descriptive name for this rule set>",
  "description": "<one sentence summary of what this rule does>",
  "conditions": [
    {
      "field": "<field name: amount | fundingSource | cardNumber | appid | ...>",
      "operator": "<EQUAL | NOT_EQUAL | GREATER_THAN | LESS_THAN | GREATER_THAN_OR_EQUAL | LESS_THAN_OR_EQUAL | CONTAINS | IN>",
      "value": "<string value>"
    }
  ],
  "action": "<REJECT | ALLOW | REVIEW>"
}

Rules:
- Infer field names: "số tiền" → amount, "nguồn tiền" → fundingSource, "số thẻ" → cardNumber
- Convert Vietnamese numbers: "5 triệu" → "5000000", "10 triệu" → "10000000"
- Return ONLY the JSON object, no explanation
"""

PLANNER_PROMPT = """You are a fraud engine config planner. Given a fraud requirement, plan the components needed.

Requirement:
{requirement}

Return ONLY valid JSON with this exact structure:
{
  "profile_name": "<name from requirement>",
  "tiers": [
    {"name": "<tier name>", "priority": 1}
  ],
  "rules": [
    {"name": "<rule name>", "tier": "<tier name it belongs to>"}
  ],
  "conditions_count": <total number of conditions>
}

Rules:
- Group related conditions into the same rule
- Use AND logic by default
- Return ONLY the JSON object, no explanation
"""

BUILD_CONFIG_PROMPT = """You are a fraud engine configuration generator.

Operation: {operation}
Requirement: {requirement}
Plan: {plan}
Existing config (for update): {existing_config}

Generate a complete JSON config matching this schema exactly:
{{
  "id": null,
  "version": 1,
  "name": "<profile name>",
  "filter": "AND",
  "conditions": [],
  "tiers": [
    {{
      "id": null,
      "name": "<tier name>",
      "status": 1,
      "priority": 1,
      "filter": "AND",
      "conditions": [],
      "rules": [
        {{
          "id": null,
          "name": "<rule name>",
          "status": 1,
          "ruleCatch": "AND",
          "conditions": [
            {{
              "id": null,
              "field": "<field>",
              "operator": "<operator>",
              "value": "<value>"
            }}
          ]
        }}
      ]
    }}
  ]
}}

Rules:
- ALL "id" fields MUST be null
- status is always 1
- If operation is "update", preserve existing tiers and merge new ones
- Return ONLY the JSON object, no markdown fences, no explanation
"""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_prompts.py -v
```

Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/prompts.py tests/test_prompts.py
git commit -m "feat: add intake, planner, build_config LLM prompts"
```

---

### Task 6: Nodes

**Files:**
- Create: `agent/nodes.py`
- Create: `tests/test_nodes.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_nodes.py
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from agent.state import ConfigAgentState
from agent.nodes import (
    intake_node, planner_node, dependency_resolver_node,
    build_config_node, validator_node, output_node,
)
from services.mock_config_service import MockConfigService


def make_state(**kwargs) -> ConfigAgentState:
    defaults: ConfigAgentState = {
        "raw_input": "",
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
    defaults.update(kwargs)
    return defaults


def test_dependency_resolver_create_when_no_existing():
    svc = MockConfigService()
    state = make_state(requirement={"app_id": "999"})
    result = dependency_resolver_node(state, svc)
    assert result["operation"] == "create"
    assert result["existing_config"] == {}


def test_dependency_resolver_update_when_existing():
    svc = MockConfigService()
    existing = {"id": None, "name": "Old Profile", "filter": "AND", "conditions": [], "tiers": []}
    svc.save_profile("123", existing)
    state = make_state(requirement={"app_id": "123"})
    result = dependency_resolver_node(state, svc)
    assert result["operation"] == "update"
    assert result["existing_config"]["name"] == "Old Profile"


def test_validator_node_valid():
    valid_draft = {
        "id": None, "version": 1, "name": "Test", "filter": "AND", "conditions": [],
        "tiers": [{"id": None, "name": "T1", "status": 1, "priority": 1, "filter": "AND",
                   "conditions": [], "rules": [{"id": None, "name": "R1", "status": 1,
                   "ruleCatch": "AND", "conditions": [{"id": None, "field": "amount",
                   "operator": "GREATER_THAN", "value": "1000"}]}]}]
    }
    state = make_state(json_draft=valid_draft)
    result = validator_node(state)
    assert result["validation_errors"] == []
    assert result["final_output"]["name"] == "Test"


def test_validator_node_invalid():
    state = make_state(json_draft={"id": None}, retry_count=0)
    result = validator_node(state)
    assert len(result["validation_errors"]) > 0
    assert result["retry_count"] == 1


def test_output_node_saves_file(tmp_path):
    final = {"id": None, "version": 1, "name": "My Profile", "filter": "AND",
             "conditions": [], "tiers": []}
    state = make_state(final_output=final)
    with patch("agent.nodes.OUTPUT_DIR", str(tmp_path)):
        result = output_node(state)
    assert result["output_file"] != ""
    assert os.path.exists(result["output_file"])
    with open(result["output_file"]) as f:
        data = json.load(f)
    assert data["name"] == "My Profile"


@patch("agent.nodes.llm_client")
def test_intake_node_calls_llm(mock_client):
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "app_id": "123", "profile_name": "Test", "description": "desc",
            "conditions": [{"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}],
            "action": "REJECT"
        })))]
    )
    state = make_state(raw_input="appid 123, amount > 5tr reject")
    result = intake_node(state)
    assert result["requirement"]["app_id"] == "123"
    assert len(result["requirement"]["conditions"]) == 1


@patch("agent.nodes.llm_client")
def test_planner_node_calls_llm(mock_client):
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "profile_name": "Test", "tiers": [{"name": "T1", "priority": 1}],
            "rules": [{"name": "R1", "tier": "T1"}], "conditions_count": 1
        })))]
    )
    state = make_state(requirement={"app_id": "123", "profile_name": "Test"})
    result = planner_node(state)
    assert result["plan"]["profile_name"] == "Test"
    assert len(result["plan"]["tiers"]) == 1


@patch("agent.nodes.llm_client")
def test_build_config_node_calls_llm(mock_client):
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "id": None, "version": 1, "name": "Test", "filter": "AND",
            "conditions": [], "tiers": []
        })))]
    )
    state = make_state(requirement={"app_id": "123"}, plan={"profile_name": "Test"},
                       operation="create", existing_config={})
    result = build_config_node(state)
    assert result["json_draft"]["name"] == "Test"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_nodes.py -v
```

Expected: `ImportError: cannot import name 'intake_node'`

- [ ] **Step 3: Implement**

```python
# agent/nodes.py
import json
import os
from datetime import datetime
from openai import OpenAI
from pydantic import ValidationError
from dotenv import load_dotenv

from agent.state import ConfigAgentState
from agent.schema import FraudProfile
from agent.prompts import INTAKE_PROMPT, PLANNER_PROMPT, BUILD_CONFIG_PROMPT
from services.mock_config_service import MockConfigService

load_dotenv()

llm_client = OpenAI(
    api_key=os.environ.get("LLM_API_KEY", ""),
    base_url=os.environ.get("LLM_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"),
)
MODEL = os.environ.get("LLM_MODEL", "minimax/minimax-m2.5")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")

_mock_service = MockConfigService()


def _call_llm(system: str, user: str) -> str:
    response = llm_client.chat.completions.create(
        model=MODEL,
        max_tokens=8192,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)


def intake_node(state: ConfigAgentState) -> ConfigAgentState:
    text = _call_llm(INTAKE_PROMPT, state["raw_input"])
    try:
        requirement = _parse_json(text)
    except json.JSONDecodeError as e:
        requirement = {"_error": str(e), "raw": text}
    return {**state, "requirement": requirement}


def planner_node(state: ConfigAgentState) -> ConfigAgentState:
    prompt = PLANNER_PROMPT.format(
        requirement=json.dumps(state["requirement"], ensure_ascii=False)
    )
    text = _call_llm(prompt, "List the components needed.")
    try:
        plan = _parse_json(text)
    except json.JSONDecodeError as e:
        plan = {"_error": str(e), "raw": text}
    return {**state, "plan": plan}


def dependency_resolver_node(
    state: ConfigAgentState,
    service: MockConfigService | None = None,
) -> ConfigAgentState:
    svc = service or _mock_service
    app_id = state["requirement"].get("app_id")
    existing = svc.get_profile(app_id) if app_id else None
    if existing:
        return {**state, "operation": "update", "existing_config": existing}
    return {**state, "operation": "create", "existing_config": {}}


def build_config_node(state: ConfigAgentState) -> ConfigAgentState:
    prompt = BUILD_CONFIG_PROMPT.format(
        requirement=json.dumps(state["requirement"], ensure_ascii=False, indent=2),
        plan=json.dumps(state["plan"], ensure_ascii=False, indent=2),
        operation=state["operation"],
        existing_config=json.dumps(state["existing_config"], ensure_ascii=False, indent=2),
    )
    text = _call_llm(prompt, "Generate the fraud rule JSON config.")
    try:
        draft = _parse_json(text)
    except json.JSONDecodeError as e:
        return {**state, "json_draft": {}, "validation_errors": [f"LLM returned invalid JSON: {e}"],
                "retry_count": state["retry_count"] + 1}
    return {**state, "json_draft": draft, "validation_errors": []}


def validator_node(state: ConfigAgentState) -> ConfigAgentState:
    try:
        profile = FraudProfile.model_validate(state["json_draft"])
        return {**state, "validation_errors": [], "final_output": profile.model_dump()}
    except ValidationError as e:
        errors = [err["msg"] for err in e.errors()]
        return {**state, "validation_errors": errors, "final_output": {},
                "retry_count": state["retry_count"] + 1}


def output_node(state: ConfigAgentState) -> ConfigAgentState:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    profile_name = state["final_output"].get("name", "rule").replace(" ", "_")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{profile_name}_{timestamp}.json"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state["final_output"], f, indent=2, ensure_ascii=False)
    return {**state, "output_file": filepath}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_nodes.py -v
```

Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/nodes.py tests/test_nodes.py
git commit -m "feat: implement 6 agent nodes"
```

---

### Task 7: LangGraph graph

**Files:**
- Create: `agent/graph.py`
- Create: `tests/test_graph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_graph.py
from agent.graph import build_graph, should_retry


def make_state(validation_errors=None, retry_count=0, final_output=None):
    return {
        "raw_input": "", "requirement": {}, "plan": {}, "existing_config": {},
        "operation": "create", "json_draft": {}, "final_output": final_output or {},
        "validation_errors": validation_errors or [], "retry_count": retry_count,
        "output_file": "",
    }


def test_should_retry_when_errors_and_under_limit():
    state = make_state(validation_errors=["missing field"], retry_count=1)
    assert should_retry(state) == "build_config"


def test_should_end_when_no_errors():
    state = make_state(validation_errors=[], final_output={"name": "Test"})
    assert should_retry(state) == "__end__"


def test_should_end_when_max_retries_exceeded():
    state = make_state(validation_errors=["error"], retry_count=2)
    assert should_retry(state) == "__end__"


def test_build_graph_compiles():
    graph = build_graph()
    assert graph is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_graph.py -v
```

Expected: `ImportError: cannot import name 'build_graph'`

- [ ] **Step 3: Implement**

```python
# agent/graph.py
from langgraph.graph import StateGraph, END
from agent.state import ConfigAgentState
from agent.nodes import (
    intake_node, planner_node, dependency_resolver_node,
    build_config_node, validator_node, output_node,
)

MAX_RETRIES = 2


def should_retry(state: ConfigAgentState) -> str:
    if state["validation_errors"] and state["retry_count"] < MAX_RETRIES:
        return "build_config"
    return "__end__"


def build_graph():
    builder = StateGraph(ConfigAgentState)
    builder.add_node("intake", intake_node)
    builder.add_node("planner", planner_node)
    builder.add_node("dependency_resolver", dependency_resolver_node)
    builder.add_node("build_config", build_config_node)
    builder.add_node("validator", validator_node)
    builder.add_node("output", output_node)

    builder.set_entry_point("intake")
    builder.add_edge("intake", "planner")
    builder.add_edge("planner", "dependency_resolver")
    builder.add_edge("dependency_resolver", "build_config")
    builder.add_edge("build_config", "validator")
    builder.add_conditional_edges("validator", should_retry, {
        "build_config": "build_config",
        "__end__": "output",
    })
    builder.add_edge("output", END)

    return builder.compile()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_graph.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/graph.py tests/test_graph.py
git commit -m "feat: assemble LangGraph v2 graph with 6 nodes"
```

---

### Task 8: CLI

**Files:**
- Modify: `cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import json
import os
from unittest.mock import patch, MagicMock
from cli import run_cli


def make_success_state(output_file="/tmp/test_rule.json"):
    return {
        "raw_input": "test", "requirement": {}, "plan": {}, "existing_config": {},
        "operation": "create", "json_draft": {},
        "validation_errors": [],
        "final_output": {"id": None, "version": 1, "name": "Test", "filter": "AND",
                         "conditions": [], "tiers": []},
        "retry_count": 0,
        "output_file": output_file,
    }


@patch("cli.build_graph")
def test_run_cli_returns_final_output(mock_build_graph):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = make_success_state()
    mock_build_graph.return_value = mock_graph

    result = run_cli("appid 123 reject")
    assert result["final_output"]["name"] == "Test"
    assert result["output_file"] == "/tmp/test_rule.json"


@patch("cli.build_graph")
def test_run_cli_returns_error_on_failure(mock_build_graph):
    failed_state = {
        "raw_input": "test", "requirement": {}, "plan": {}, "existing_config": {},
        "operation": "create", "json_draft": {"id": None},
        "validation_errors": ["missing: name"],
        "final_output": {}, "retry_count": 2, "output_file": "",
    }
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = failed_state
    mock_build_graph.return_value = mock_graph

    result = run_cli("bad input")
    assert "_error" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: `ImportError` hoặc test fail vì `run_cli` trả về format cũ

- [ ] **Step 3: Implement**

```python
# cli.py
import json
import sys
import argparse
from dotenv import load_dotenv
from agent.graph import build_graph

load_dotenv()


def run_cli(raw_input: str) -> dict:
    graph = build_graph()
    state = graph.invoke({
        "raw_input": raw_input,
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
        "output_file": "",
    })
    if state["final_output"]:
        return {"final_output": state["final_output"], "output_file": state["output_file"]}
    return {
        "_error": "Validation failed after max retries",
        "_validation_errors": state["validation_errors"],
        "_draft": state["json_draft"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pattern", nargs="*", help="Fraud pattern description")
    parser.add_argument("-o", "--output", help="Save output to file (e.g. rule.json)")
    args = parser.parse_args()

    if args.pattern:
        raw = " ".join(args.pattern)
    else:
        print("Enter fraud pattern (end with Ctrl+D):")
        raw = sys.stdin.read().strip()

    result = run_cli(raw)
    output_str = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_str)
        print(f"Saved to {args.output}")
    else:
        print(output_str)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add cli.py tests/test_cli.py
git commit -m "feat: update CLI for v2 graph"
```

---

### Task 9: FastAPI endpoint

**Files:**
- Modify: `api/main.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api.py
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def make_success_state():
    return {
        "raw_input": "test", "requirement": {}, "plan": {}, "existing_config": {},
        "operation": "create", "json_draft": {},
        "validation_errors": [],
        "final_output": {"id": None, "version": 1, "name": "API Test", "filter": "AND",
                         "conditions": [], "tiers": []},
        "retry_count": 0,
        "output_file": "/tmp/api_test.json",
    }


@patch("api.main.build_graph")
def test_generate_rule_success(mock_build_graph):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = make_success_state()
    mock_build_graph.return_value = mock_graph

    response = client.post("/generate-rule", json={"input": "appid 123 reject"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "API Test"
    assert data["id"] is None


@patch("api.main.build_graph")
def test_generate_rule_validation_failure(mock_build_graph):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "raw_input": "test", "requirement": {}, "plan": {}, "existing_config": {},
        "operation": "create", "json_draft": {"id": None},
        "validation_errors": ["missing: name"],
        "final_output": {}, "retry_count": 2, "output_file": "",
    }
    mock_build_graph.return_value = mock_graph

    response = client.post("/generate-rule", json={"input": "bad"})
    assert response.status_code == 422
    assert "validation_errors" in response.json()["detail"]


def test_generate_rule_missing_input():
    response = client.post("/generate-rule", json={})
    assert response.status_code == 422


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_api.py -v
```

Expected: Tests fail vì `api/main.py` dùng state format cũ

- [ ] **Step 3: Implement**

```python
# api/main.py
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from agent.graph import build_graph

load_dotenv()

app = FastAPI(title="Config Agent V2")


class RuleRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=4096)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate-rule")
def generate_rule(request: RuleRequest):
    graph = build_graph()
    state = graph.invoke({
        "raw_input": request.input,
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
        "output_file": "",
    })
    if state["final_output"]:
        return state["final_output"]
    raise HTTPException(
        status_code=422,
        detail={
            "error": "Validation failed after max retries",
            "validation_errors": state["validation_errors"],
            "draft": state["json_draft"],
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_api.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_api.py
git commit -m "feat: update FastAPI endpoint for v2 graph"
```

---

### Task 10: Full test suite + smoke test

**Files:**
- Verify all tests pass

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 2: Smoke test CLI**

```bash
source .env && .venv/bin/python cli.py "appid 456, nếu số tiền lớn hơn 10 triệu và nguồn tiền là thẻ tín dụng thì reject"
```

Expected: JSON output với `final_output` hợp lệ, file được lưu vào `output/`

- [ ] **Step 3: Commit final**

```bash
git add output/.gitkeep
git commit -m "feat: config agent v2 complete"
```

---

## Self-Review

**Spec coverage:**
- ✅ intake_node — Task 6
- ✅ planner_node — Task 6
- ✅ dependency_resolver — Task 6, Task 3
- ✅ build_config_node — Task 6
- ✅ validator_node (Pydantic, retry 2x) — Task 6, Task 7
- ✅ output_node (lưu file) — Task 6
- ✅ MockConfigService (create vs update) — Task 3
- ✅ LLM via GreenNode AIP OpenAI SDK — Task 6
- ✅ CLI với -o flag — Task 8
- ✅ FastAPI endpoint — Task 9

**Type consistency:**
- `ConfigAgentState` defined Task 2, used in Tasks 6, 7, 8, 9 ✅
- `MockConfigService` defined Task 3, used in Task 6 (`dependency_resolver_node`) ✅
- `build_graph()` defined Task 7, imported in Tasks 8, 9 ✅
- `should_retry` returns `"build_config"` or `"__end__"` — matches graph edges in Task 7 ✅
- `output_node` goes to `END` after saving file — validator conditional edge routes to `"output"` not `END` directly ✅
