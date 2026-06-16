# Config Agent V3a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm clarify_loop, Web UI chat, Memory Service, và thay schema output sang format `events` mới.

**Architecture:** Graph LangGraph mở rộng thêm `memory_load_node` → `clarify_node` → `memory_save_node`. API FastAPI thêm `POST /chat` cho human và mount `static/index.html`. MockMemoryService để test, interface sẵn sàng swap sang AgentBaseMemoryService.

**Tech Stack:** Python 3.11, LangGraph 0.4.8, FastAPI, Pydantic v2, OpenAI SDK (GreenNode AIP), vanilla HTML/JS

---

## File Map

| File | Action | Mô tả |
|------|--------|-------|
| `agent/schema.py` | Rewrite | Thay FraudProfile → FraudConfig/Event/Rule/Condition/Variable/Source |
| `agent/state.py` | Modify | Thêm 4 field: session_id, clarify_question, clarification_answer, needs_clarification |
| `agent/prompts.py` | Modify | Thêm CLARIFY_SYSTEM/CLARIFY_USER, cập nhật BUILD_CONFIG_SYSTEM schema |
| `agent/nodes.py` | Modify | Thêm clarify_node, memory_load_node, memory_save_node; sửa validator_node dùng FraudConfig |
| `agent/graph.py` | Modify | Thêm 3 node mới, conditional edge clarify → END hoặc dependency_resolver |
| `services/memory_service.py` | Create | MockMemoryService + MemoryService interface |
| `api/main.py` | Modify | Thêm POST /chat, GET /, mount StaticFiles |
| `static/index.html` | Create | Web UI chat bubble |
| `tests/test_schema.py` | Rewrite | Test FraudConfig thay FraudProfile |
| `tests/test_state.py` | Modify | Thêm test 4 field mới |
| `tests/test_prompts.py` | Modify | Thêm test CLARIFY prompts |
| `tests/test_nodes.py` | Modify | Thêm test clarify_node, memory_load_node, memory_save_node |
| `tests/test_memory_service.py` | Create | Test MockMemoryService |
| `tests/test_api.py` | Modify | Thêm test POST /chat clarify + done flows |

---

### Task 1: Rewrite schema — FraudConfig thay FraudProfile

**Files:**
- Rewrite: `agent/schema.py`
- Rewrite: `tests/test_schema.py`

- [ ] **Step 1: Rewrite test file trước**

```python
# tests/test_schema.py
from agent.schema import Condition, Rule, Event, Variable, Source, FraudConfig


def test_condition_valid():
    c = Condition(field="amount", operator="GREATER_THAN", value="5000000")
    assert c.field == "amount"
    assert c.operator == "GREATER_THAN"
    assert c.value == "5000000"


def test_rule_with_conditions():
    rule = Rule(
        name="Reject High Amount",
        conditions=[Condition(field="amount", operator="GREATER_THAN", value="5000000")],
    )
    assert rule.name == "Reject High Amount"
    assert len(rule.conditions) == 1
    assert rule.description == ""
    assert rule.infoCode == ""


def test_event_defaults():
    event = Event(
        name="payment",
        actionCode="REJECT",
        rules=[
            Rule(
                name="Reject High Amount",
                conditions=[Condition(field="amount", operator="GREATER_THAN", value="5000000")],
            )
        ],
    )
    assert event.filter == "AND"
    assert event.variables == []
    assert event.decisionCode == ""


def test_fraud_config_full():
    config = FraudConfig(
        events=[
            Event(
                name="payment",
                actionCode="REJECT",
                rules=[
                    Rule(
                        name="Reject High Amount",
                        conditions=[Condition(field="amount", operator="GREATER_THAN", value="5000000")],
                    )
                ],
            )
        ]
    )
    assert len(config.events) == 1
    assert config.events[0].actionCode == "REJECT"
    dumped = config.model_dump()
    assert dumped["events"][0]["name"] == "payment"
    assert dumped["events"][0]["variables"] == []


def test_variable_with_source():
    var = Variable(
        fieldName="velocyti_amt_per_user_24hrs",
        fieldType="LONG",
        source=Source(keyId="434"),
    )
    assert var.source.keyId == "434"
```

- [ ] **Step 2: Chạy test — expect FAIL**

```bash
.venv/bin/pytest tests/test_schema.py -v
```

Expected: `ImportError` hoặc `AttributeError` vì schema cũ không có `FraudConfig`.

- [ ] **Step 3: Rewrite `agent/schema.py`**

```python
from pydantic import BaseModel


class Source(BaseModel):
    keyId: str


class Variable(BaseModel):
    fieldName: str
    fieldType: str
    source: Source


class Condition(BaseModel):
    field: str
    operator: str
    value: str


class Rule(BaseModel):
    name: str
    description: str = ""
    conditions: list[Condition]
    infoCode: str = ""


class Event(BaseModel):
    name: str
    description: str = ""
    filter: str = "AND"
    actionCode: str
    decisionCode: str = ""
    variables: list[Variable] = []
    rules: list[Rule]


class FraudConfig(BaseModel):
    events: list[Event]
```

- [ ] **Step 4: Chạy test — expect PASS**

```bash
.venv/bin/pytest tests/test_schema.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add agent/schema.py tests/test_schema.py
git commit -m "feat: replace FraudProfile with FraudConfig events schema"
```

---

### Task 2: Update ConfigAgentState — thêm 4 field V3a

**Files:**
- Modify: `agent/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Thêm test cho 4 field mới**

Mở `tests/test_state.py`, thêm test case:

```python
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
    }
    assert state["session_id"] == "session-abc-123"
    assert state["needs_clarification"] is False
    assert state["clarify_question"] == ""
    assert state["clarification_answer"] == ""
```

- [ ] **Step 2: Chạy test — expect FAIL**

```bash
.venv/bin/pytest tests/test_state.py::test_config_agent_state_v3a_fields -v
```

Expected: `TypeError` vì TypedDict chưa có 4 field mới.

- [ ] **Step 3: Update `agent/state.py`**

```python
from typing import TypedDict


class ConfigAgentState(TypedDict):
    raw_input: str
    requirement: dict
    plan: dict
    existing_config: dict
    operation: str
    json_draft: dict
    validation_errors: list
    final_output: dict
    retry_count: int
    output_file: str
    # V3a fields
    session_id: str
    clarify_question: str
    clarification_answer: str
    needs_clarification: bool
```

- [ ] **Step 4: Chạy test — expect PASS**

```bash
.venv/bin/pytest tests/test_state.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add agent/state.py tests/test_state.py
git commit -m "feat: add V3a fields to ConfigAgentState"
```

---

### Task 3: MockMemoryService

**Files:**
- Create: `services/memory_service.py`
- Create: `tests/test_memory_service.py`

- [ ] **Step 1: Viết test**

```python
# tests/test_memory_service.py
from services.memory_service import MockMemoryService


def test_get_returns_none_when_missing():
    svc = MockMemoryService()
    assert svc.get("session:abc") is None


def test_set_and_get():
    svc = MockMemoryService()
    svc.set("prefs:global", {"default_action": "REJECT"})
    result = svc.get("prefs:global")
    assert result == {"default_action": "REJECT"}


def test_set_overwrites():
    svc = MockMemoryService()
    svc.set("prefs:global", {"default_action": "REJECT"})
    svc.set("prefs:global", {"default_action": "REVIEW"})
    assert svc.get("prefs:global")["default_action"] == "REVIEW"


def test_append_creates_list():
    svc = MockMemoryService()
    svc.append("session:abc", {"input": "test1"})
    svc.append("session:abc", {"input": "test2"})
    result = svc.get("session:abc")
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["input"] == "test1"
```

- [ ] **Step 2: Chạy test — expect FAIL**

```bash
.venv/bin/pytest tests/test_memory_service.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Tạo `services/memory_service.py`**

```python
class MockMemoryService:
    def __init__(self):
        self._store: dict = {}

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value) -> None:
        self._store[key] = value

    def append(self, key: str, item: dict) -> None:
        existing = self._store.get(key)
        if isinstance(existing, list):
            existing.append(item)
        else:
            self._store[key] = [item]
```

- [ ] **Step 4: Chạy test — expect PASS**

```bash
.venv/bin/pytest tests/test_memory_service.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/memory_service.py tests/test_memory_service.py
git commit -m "feat: add MockMemoryService"
```

---

### Task 4: Thêm CLARIFY prompts + update BUILD_CONFIG_SYSTEM

**Files:**
- Modify: `agent/prompts.py`
- Modify: `tests/test_prompts.py`

- [ ] **Step 1: Thêm test cho prompts mới**

Mở `tests/test_prompts.py`, thêm:

```python
def test_clarify_prompts_exist():
    from agent.prompts import CLARIFY_SYSTEM, CLARIFY_USER
    assert isinstance(CLARIFY_SYSTEM, str) and len(CLARIFY_SYSTEM) > 0
    assert "{requirement}" in CLARIFY_USER
    assert "{clarification_answer}" in CLARIFY_USER


def test_clarify_user_formats():
    from agent.prompts import CLARIFY_USER
    formatted = CLARIFY_USER.format(
        requirement='{"app_id": "123"}',
        clarification_answer="tôi muốn reject",
    )
    assert "reject" in formatted


def test_build_config_system_has_events_schema():
    from agent.prompts import BUILD_CONFIG_SYSTEM
    assert "events" in BUILD_CONFIG_SYSTEM
    assert "actionCode" in BUILD_CONFIG_SYSTEM
```

- [ ] **Step 2: Chạy test — expect FAIL**

```bash
.venv/bin/pytest tests/test_prompts.py::test_clarify_prompts_exist tests/test_prompts.py::test_build_config_system_has_events_schema -v
```

- [ ] **Step 3: Update `agent/prompts.py`** — thêm 2 hằng số mới và sửa BUILD_CONFIG_SYSTEM

```python
CLARIFY_SYSTEM = """Bạn là fraud rule clarity checker. Đánh giá xem requirement có đủ thông tin để tạo fraud rule không.

Chỉ hỏi lại khi thiếu thông tin BẮT BUỘC:
- Không xác định được app_id hoặc event name
- Không rõ action (REJECT/REVIEW/ALLOW) và không thể suy ra
- Không có bất kỳ condition nào

KHÔNG hỏi khi có thể suy ra: "chặn" = REJECT, "cảnh báo" = REVIEW, "cho qua" = ALLOW.

Nếu đã có clarification_answer thì KHÔNG hỏi thêm — merge answer vào requirement và đánh giá là đủ rõ.

Trả về JSON only (không markdown):
{
  "needs_clarification": true/false,
  "question": "câu hỏi nếu needs_clarification=true, chuỗi rỗng nếu false"
}"""

CLARIFY_USER = """Requirement hiện tại:
{requirement}

Clarification answer (nếu có):
{clarification_answer}

Đánh giá xem requirement có đủ rõ không."""
```

Sửa `BUILD_CONFIG_SYSTEM` — thay schema cũ bằng schema mới:

```python
BUILD_CONFIG_SYSTEM = """You are a fraud rule JSON builder. Generate a complete fraud engine config JSON.

Schema:
{
  "events": [
    {
      "name": "<event name, e.g. payment>",
      "description": "<brief description>",
      "filter": "AND",
      "actionCode": "<REJECT|REVIEW|ALLOW>",
      "decisionCode": "",
      "variables": [],
      "rules": [
        {
          "name": "<rule name>",
          "description": "<rule description>",
          "conditions": [
            {"field": "<field>", "operator": "<operator>", "value": "<value>"}
          ],
          "infoCode": ""
        }
      ]
    }
  ]
}

Rules:
- variables must always be empty list [] (populated in later version)
- actionCode must be one of: REJECT, REVIEW, ALLOW
- If operation is "update", merge new rules into existing_config events — do not duplicate rules with same name
- Always respond with valid JSON only (no markdown fences)"""
```

- [ ] **Step 4: Chạy test — expect PASS**

```bash
.venv/bin/pytest tests/test_prompts.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add agent/prompts.py tests/test_prompts.py
git commit -m "feat: add CLARIFY prompts, update BUILD_CONFIG_SYSTEM for events schema"
```

---

### Task 5: Thêm 3 nodes mới + sửa validator_node

**Files:**
- Modify: `agent/nodes.py`
- Modify: `tests/test_nodes.py`

- [ ] **Step 1: Viết tests cho 3 node mới**

Mở `tests/test_nodes.py`, thêm:

```python
def test_clarify_node_needs_clarification():
    clarify_result = {"needs_clarification": True, "question": "Bạn muốn REJECT hay REVIEW?"}
    with patch("agent.nodes._call_llm", return_value=clarify_result):
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
    state = make_state(requirement=SAMPLE_REQUIREMENT, clarification_answer="tôi muốn reject")
    with patch("agent.nodes._call_llm", return_value={"needs_clarification": False, "question": ""}) as mock_llm:
        result = clarify_node(state)
    assert result["needs_clarification"] is False


def test_memory_load_node_returns_empty_when_no_data():
    from unittest.mock import MagicMock
    mock_svc = MagicMock()
    mock_svc.get.return_value = None
    with patch("agent.nodes._memory_service", mock_svc):
        state = make_state(session_id="session-abc")
        result = memory_load_node(state)
    assert result == {}


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
```

Cũng cần import mới ở đầu test file:

```python
from agent.nodes import (
    intake_node, planner_node, dependency_resolver,
    build_config_node, validator_node, output_node,
    clarify_node, memory_load_node, memory_save_node,
)
```

Và thêm vào `make_state()`:

```python
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
        # V3a
        "session_id": "test-session",
        "clarify_question": "",
        "clarification_answer": "",
        "needs_clarification": False,
    }
    base.update(kwargs)
    return base
```

- [ ] **Step 2: Chạy test — expect FAIL**

```bash
.venv/bin/pytest tests/test_nodes.py::test_clarify_node_needs_clarification -v
```

Expected: `ImportError` vì `clarify_node` chưa có.

- [ ] **Step 3: Thêm vào `agent/nodes.py`**

Thêm import:

```python
from agent.prompts import (
    INTAKE_SYSTEM, INTAKE_USER,
    PLANNER_SYSTEM, PLANNER_USER,
    BUILD_CONFIG_SYSTEM, BUILD_CONFIG_USER,
    CLARIFY_SYSTEM, CLARIFY_USER,
)
from agent.schema import FraudConfig
from services.memory_service import MockMemoryService
```

Thêm singleton memory service sau `_mock_service`:

```python
_memory_service = MockMemoryService()
```

Thêm 3 node mới:

```python
def clarify_node(state: ConfigAgentState) -> dict:
    if state.get("clarification_answer"):
        return {"needs_clarification": False, "clarify_question": ""}
    user_msg = CLARIFY_USER.format(
        requirement=json.dumps(state["requirement"], ensure_ascii=False),
        clarification_answer=state.get("clarification_answer", ""),
    )
    result = _call_llm(CLARIFY_SYSTEM, user_msg)
    return {
        "needs_clarification": bool(result.get("needs_clarification", False)),
        "clarify_question": result.get("question", ""),
    }


def memory_load_node(state: ConfigAgentState) -> dict:
    session_id = state.get("session_id", "")
    prefs = _memory_service.get("prefs:global") or {}
    conversation = _memory_service.get(f"session:{session_id}") or []
    if prefs:
        existing_req = state.get("requirement", {})
        existing_req["_prefs"] = prefs
        return {"requirement": existing_req}
    return {}


def memory_save_node(state: ConfigAgentState) -> dict:
    session_id = state.get("session_id", "")
    app_id = state["requirement"].get("app_id", "unknown")
    _memory_service.append(f"session:{session_id}", {
        "input": state["raw_input"],
        "answer": state.get("clarification_answer", ""),
        "output_file": state["output_file"],
    })
    _memory_service.set(f"profile:{app_id}", state["final_output"])
    action = state["requirement"].get("action", "")
    if action:
        prefs = _memory_service.get("prefs:global") or {}
        prefs["last_action"] = action
        _memory_service.set("prefs:global", prefs)
    return {}
```

Sửa `validator_node` dùng `FraudConfig` thay `FraudProfile`:

```python
def validator_node(state: ConfigAgentState) -> dict:
    try:
        profile = FraudConfig(**state["json_draft"])
        return {"final_output": profile.model_dump(), "validation_errors": []}
    except Exception as e:
        return {
            "validation_errors": [str(e)],
            "retry_count": state["retry_count"] + 1,
        }
```

- [ ] **Step 4: Chạy test — expect PASS**

```bash
.venv/bin/pytest tests/test_nodes.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add agent/nodes.py tests/test_nodes.py
git commit -m "feat: add clarify_node, memory_load_node, memory_save_node; validator uses FraudConfig"
```

---

### Task 6: Update LangGraph graph

**Files:**
- Modify: `agent/graph.py`
- Modify: `tests/test_graph.py`

- [ ] **Step 1: Thêm test graph mới**

Mở `tests/test_graph.py`, thêm:

```python
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
```

Cập nhật `SAMPLE_STATE_BASE` trong test file để có 4 field mới:

```python
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
```

- [ ] **Step 2: Chạy test — expect FAIL**

```bash
.venv/bin/pytest tests/test_graph.py::test_graph_has_v3a_nodes -v
```

- [ ] **Step 3: Rewrite `agent/graph.py`**

```python
from langgraph.graph import StateGraph, END
from agent.state import ConfigAgentState
from agent.nodes import (
    intake_node,
    planner_node,
    dependency_resolver,
    build_config_node,
    validator_node,
    output_node,
    clarify_node,
    memory_load_node,
    memory_save_node,
)

MAX_RETRIES = 2


def should_retry(state: ConfigAgentState) -> str:
    if state["validation_errors"] and state["retry_count"] < MAX_RETRIES:
        return "retry"
    return "done"


def should_clarify(state: ConfigAgentState) -> str:
    if state.get("needs_clarification"):
        return "clarify"
    return "proceed"


def build_graph() -> StateGraph:
    graph = StateGraph(ConfigAgentState)

    graph.add_node("memory_load_node", memory_load_node)
    graph.add_node("intake_node", intake_node)
    graph.add_node("clarify_node", clarify_node)
    graph.add_node("dependency_resolver", dependency_resolver)
    graph.add_node("planner_node", planner_node)
    graph.add_node("build_config_node", build_config_node)
    graph.add_node("validator_node", validator_node)
    graph.add_node("output_node", output_node)
    graph.add_node("memory_save_node", memory_save_node)

    graph.set_entry_point("memory_load_node")
    graph.add_edge("memory_load_node", "intake_node")
    graph.add_edge("intake_node", "clarify_node")
    graph.add_conditional_edges(
        "clarify_node",
        should_clarify,
        {"clarify": END, "proceed": "dependency_resolver"},
    )
    graph.add_edge("dependency_resolver", "planner_node")
    graph.add_edge("planner_node", "build_config_node")
    graph.add_edge("build_config_node", "validator_node")
    graph.add_conditional_edges(
        "validator_node",
        should_retry,
        {"retry": "build_config_node", "done": "output_node"},
    )
    graph.add_edge("output_node", "memory_save_node")
    graph.add_edge("memory_save_node", END)

    return graph.compile()
```

- [ ] **Step 4: Chạy test — expect PASS**

```bash
.venv/bin/pytest tests/test_graph.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add agent/graph.py tests/test_graph.py
git commit -m "feat: update graph with clarify_node, memory nodes, should_clarify edge"
```

---

### Task 7: API — POST /chat + StaticFiles mount

**Files:**
- Modify: `api/main.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Thêm tests cho /chat endpoint**

Mở `tests/test_api.py`, thêm:

```python
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
```

Cập nhật `make_mock_state` để có 4 field mới:

```python
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
    }
```

- [ ] **Step 2: Chạy test — expect FAIL**

```bash
.venv/bin/pytest tests/test_api.py::test_chat_clarify_response -v
```

- [ ] **Step 3: Update `api/main.py`**

```python
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from agent.graph import build_graph

load_dotenv()

app = FastAPI(title="Config Agent V3a")

app.mount("/static", StaticFiles(directory="static"), name="static")


class PatternRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=4096)


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=4096)
    clarification_answer: str = ""


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest):
    graph = build_graph()
    state = graph.invoke({
        "raw_input": request.message,
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
        "output_file": "",
        "session_id": request.session_id,
        "clarify_question": "",
        "clarification_answer": request.clarification_answer,
        "needs_clarification": False,
    })
    if state.get("needs_clarification"):
        return {
            "status": "clarify",
            "question": state["clarify_question"],
            "session_id": request.session_id,
        }
    if state["final_output"]:
        return {
            "status": "done",
            "final_output": state["final_output"],
            "output_file": state["output_file"],
        }
    return {
        "status": "error",
        "message": "Validation failed after max retries",
    }


@app.post("/generate-config")
def generate_config(request: PatternRequest):
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
        "session_id": "agent-call",
        "clarify_question": "",
        "clarification_answer": "proceed",  # skip clarify cho agent
        "needs_clarification": False,
    })
    if state["final_output"]:
        return {
            "final_output": state["final_output"],
            "output_file": state["output_file"],
        }
    from fastapi import HTTPException
    raise HTTPException(
        status_code=422,
        detail={
            "error": "Validation failed after max retries",
            "validation_errors": state["validation_errors"],
        },
    )
```

- [ ] **Step 4: Chạy test — expect PASS**

```bash
.venv/bin/pytest tests/test_api.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_api.py
git commit -m "feat: add POST /chat endpoint, mount StaticFiles, update /generate-config state shape"
```

---

### Task 8: Web UI (static/index.html)

**Files:**
- Create: `static/index.html`

Không có unit test cho HTML — verify bằng cách mở browser thủ công.

- [ ] **Step 1: Tạo thư mục `static/`**

```bash
mkdir -p static
```

- [ ] **Step 2: Tạo `static/index.html`**

```html
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Config Agent</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #f5f5f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
  .chat-container { width: 600px; height: 80vh; background: white; border-radius: 12px; box-shadow: 0 2px 16px rgba(0,0,0,0.1); display: flex; flex-direction: column; overflow: hidden; }
  .chat-header { padding: 14px 18px; border-bottom: 1px solid #eee; font-weight: 600; font-size: 15px; color: #333; }
  .chat-messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 75%; padding: 10px 14px; border-radius: 16px; font-size: 14px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
  .msg.user { background: #534AB7; color: white; border-radius: 16px 16px 4px 16px; align-self: flex-end; }
  .msg.agent { background: #f0f0f0; color: #333; border-radius: 16px 16px 16px 4px; align-self: flex-start; }
  .msg.agent.clarify { background: #fff3cd; border: 1px solid #ffc107; }
  .msg.agent.done { background: #d4edda; border: 1px solid #28a745; }
  .msg.agent.error { background: #f8d7da; border: 1px solid #dc3545; }
  .json-block { background: #f8f9fa; border-radius: 8px; padding: 10px; font-family: monospace; font-size: 12px; margin-top: 8px; max-height: 200px; overflow-y: auto; white-space: pre; }
  .btn-row { display: flex; gap: 8px; margin-top: 8px; }
  .btn { padding: 4px 10px; font-size: 12px; border: 1px solid #ccc; border-radius: 6px; cursor: pointer; background: white; }
  .btn:hover { background: #f0f0f0; }
  .loading { display: flex; gap: 4px; padding: 10px 14px; align-self: flex-start; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #999; animation: bounce 1.2s infinite; }
  .dot:nth-child(2) { animation-delay: 0.2s; }
  .dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce { 0%,80%,100% { transform: translateY(0); } 40% { transform: translateY(-8px); } }
  .chat-input { padding: 12px 16px; border-top: 1px solid #eee; display: flex; gap: 8px; }
  .chat-input input { flex: 1; padding: 8px 12px; border: 1px solid #ddd; border-radius: 20px; font-size: 14px; outline: none; }
  .chat-input input:focus { border-color: #534AB7; }
  .chat-input button { padding: 8px 18px; background: #534AB7; color: white; border: none; border-radius: 20px; font-size: 14px; cursor: pointer; }
  .chat-input button:hover { background: #3C3489; }
  .chat-input button:disabled { background: #aaa; cursor: not-allowed; }
</style>
</head>
<body>
<div class="chat-container">
  <div class="chat-header">🛡️ Config Agent — Fraud Rule Generator</div>
  <div class="chat-messages" id="messages">
    <div class="msg agent">Xin chào! Mô tả pattern gian lận bạn muốn tạo rule (VD: "appid 123, reject nếu amount > 5 triệu và nguồn tiền là ví điện tử").</div>
  </div>
  <div class="chat-input">
    <input type="text" id="input" placeholder="Nhập pattern gian lận..." />
    <button id="send-btn" onclick="sendMessage()">Gửi</button>
  </div>
</div>
<script>
  let sessionId = localStorage.getItem('session_id');
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem('session_id', sessionId);
  }

  let waitingForClarification = false;
  let lastMessage = '';

  function addMsg(text, type, extra) {
    const el = document.createElement('div');
    el.className = 'msg agent ' + (type || '');
    el.textContent = text;
    if (extra) el.appendChild(extra);
    document.getElementById('messages').appendChild(el);
    el.scrollIntoView({ behavior: 'smooth' });
    return el;
  }

  function addUserMsg(text) {
    const el = document.createElement('div');
    el.className = 'msg user';
    el.textContent = text;
    document.getElementById('messages').appendChild(el);
    el.scrollIntoView({ behavior: 'smooth' });
  }

  function addLoading() {
    const el = document.createElement('div');
    el.className = 'loading';
    el.id = 'loading';
    el.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
    document.getElementById('messages').appendChild(el);
    el.scrollIntoView({ behavior: 'smooth' });
    return el;
  }

  async function sendMessage() {
    const input = document.getElementById('input');
    const btn = document.getElementById('send-btn');
    const text = input.value.trim();
    if (!text) return;

    addUserMsg(text);
    input.value = '';
    btn.disabled = true;

    const payload = waitingForClarification
      ? { session_id: sessionId, message: lastMessage, clarification_answer: text }
      : { session_id: sessionId, message: text, clarification_answer: '' };

    if (!waitingForClarification) lastMessage = text;

    const loading = addLoading();
    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      loading.remove();

      if (data.status === 'clarify') {
        waitingForClarification = true;
        addMsg(data.question, 'clarify');
        input.placeholder = 'Trả lời câu hỏi...';
      } else if (data.status === 'done') {
        waitingForClarification = false;
        input.placeholder = 'Nhập pattern gian lận...';
        const jsonBlock = document.createElement('div');
        jsonBlock.className = 'json-block';
        jsonBlock.textContent = JSON.stringify(data.final_output, null, 2);
        const btnRow = document.createElement('div');
        btnRow.className = 'btn-row';
        const copyBtn = document.createElement('button');
        copyBtn.className = 'btn';
        copyBtn.textContent = '📋 Copy JSON';
        copyBtn.onclick = () => { navigator.clipboard.writeText(JSON.stringify(data.final_output, null, 2)); copyBtn.textContent = '✓ Đã copy'; };
        const fileBtn = document.createElement('a');
        fileBtn.className = 'btn';
        fileBtn.textContent = '⬇ Tải file';
        fileBtn.href = '/' + data.output_file;
        fileBtn.download = data.output_file.split('/').pop();
        btnRow.appendChild(copyBtn);
        btnRow.appendChild(fileBtn);
        const wrapper = document.createElement('div');
        wrapper.appendChild(jsonBlock);
        wrapper.appendChild(btnRow);
        addMsg('✅ Config đã tạo thành công!', 'done', wrapper);
      } else {
        waitingForClarification = false;
        addMsg('❌ Lỗi: ' + (data.message || 'Không thể tạo config'), 'error');
      }
    } catch (e) {
      loading.remove();
      addMsg('❌ Lỗi kết nối: ' + e.message, 'error');
    }
    btn.disabled = false;
    input.focus();
  }

  document.getElementById('input').addEventListener('keydown', e => {
    if (e.key === 'Enter') sendMessage();
  });
</script>
</body>
</html>
```

- [ ] **Step 3: Thêm `aiofiles` và `python-multipart` vào requirements (cần cho StaticFiles)**

```bash
.venv/bin/pip install aiofiles python-multipart
```

Cập nhật `requirements.txt`:

```
openai==2.41.1
langgraph==0.4.8
pydantic==2.11.5
fastapi==0.115.12
uvicorn==0.34.2
python-dotenv==1.1.0
aiofiles>=23.0.0
pytest==8.4.0
httpx==0.28.1
```

- [ ] **Step 4: Test thủ công**

```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

Mở browser: `http://localhost:8000` — kiểm tra chat UI hiển thị đúng.

- [ ] **Step 5: Commit**

```bash
git add static/index.html requirements.txt
git commit -m "feat: add Web UI chat (static/index.html) and aiofiles dependency"
```

---

### Task 9: Full test suite

**Files:** Không tạo file mới — chạy toàn bộ suite.

- [ ] **Step 1: Chạy toàn bộ tests**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all passed, 0 errors.

- [ ] **Step 2: Nếu có test fail do schema cũ**

Các test trong `test_nodes.py` dùng `SAMPLE_JSON_DRAFT` cũ (format tiers). Cập nhật sang format mới:

```python
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
```

- [ ] **Step 3: Chạy lại — expect all pass**

```bash
.venv/bin/pytest --tb=short -q
```

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "test: update SAMPLE_JSON_DRAFT to new events schema, full suite green"
```
