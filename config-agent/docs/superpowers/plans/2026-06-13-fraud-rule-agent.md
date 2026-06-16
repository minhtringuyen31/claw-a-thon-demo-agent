# Fraud Rule Suggestion Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MVP LangGraph agent that reads free-text fraud patterns (from CLI or HTTP) and outputs valid JSON rule configs for the in-house fraud engine.

**Architecture:** Three-node LangGraph pipeline — ParseNode extracts intent with LLM, RuleBuilderNode generates fraud engine JSON, ValidatorNode checks Pydantic schema with up to 2 retries back to RuleBuilderNode. FastAPI exposes the same pipeline via HTTP for agent-to-agent mode.

**Tech Stack:** Python 3.11+, LangGraph, LangChain, Anthropic SDK (`claude-opus-4-8`), Pydantic v2, FastAPI, python-dotenv

---

## File Map

| File | Responsibility |
|------|----------------|
| `agent/state.py` | `FraudRuleState` TypedDict — single source of truth for graph state |
| `agent/schema.py` | Pydantic models for fraud engine JSON (Profile → Tiers → Rules → Conditions) |
| `agent/prompts.py` | System prompts for ParseNode and RuleBuilderNode |
| `agent/nodes.py` | `parse_node`, `rule_builder_node`, `validator_node` functions |
| `agent/graph.py` | LangGraph graph assembly — wires nodes + retry conditional edge |
| `api/main.py` | FastAPI app with `POST /generate-rule` endpoint |
| `cli.py` | CLI entry point — reads stdin, runs graph, prints JSON |
| `requirements.txt` | Pinned dependencies |
| `.env.example` | Environment variable template |

---

### Task 1: Project scaffold and dependencies

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `agent/__init__.py`
- Create: `api/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```
anthropic==0.54.0
langchain==0.3.25
langchain-anthropic==0.3.15
langgraph==0.4.8
pydantic==2.11.5
fastapi==0.115.12
uvicorn==0.34.2
python-dotenv==1.1.0
pytest==8.4.0
pytest-asyncio==0.25.3
httpx==0.28.1
```

- [ ] **Step 2: Create .env.example**

```
ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 3: Create empty __init__ files**

```bash
mkdir -p agent api tests
touch agent/__init__.py api/__init__.py tests/__init__.py
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: All packages install without errors.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example agent/__init__.py api/__init__.py tests/__init__.py
git commit -m "feat: project scaffold and dependencies"
```

---

### Task 2: Graph state

**Files:**
- Create: `agent/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
from agent.state import FraudRuleState

def test_fraud_rule_state_fields():
    state: FraudRuleState = {
        "raw_input": "test",
        "parsed_intent": {},
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
    }
    assert state["raw_input"] == "test"
    assert state["retry_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_state.py -v
```

Expected: `ImportError: cannot import name 'FraudRuleState'`

- [ ] **Step 3: Implement state**

```python
# agent/state.py
from typing import TypedDict


class FraudRuleState(TypedDict):
    raw_input: str
    parsed_intent: dict
    json_draft: dict
    validation_errors: list
    final_output: dict
    retry_count: int
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_state.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agent/state.py tests/test_state.py
git commit -m "feat: add FraudRuleState TypedDict"
```

---

### Task 3: Fraud engine Pydantic schema

**Files:**
- Create: `agent/schema.py`
- Create: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema.py
import pytest
from pydantic import ValidationError
from agent.schema import Condition, Rule, Tier, FraudProfile


def test_condition_valid():
    c = Condition(field="amount", operator="GREATER_THAN", value="5000000")
    assert c.field == "amount"


def test_condition_missing_field():
    with pytest.raises(ValidationError):
        Condition(operator="GREATER_THAN", value="5000000")


def test_rule_valid():
    r = Rule(
        id=None,
        name="High amount",
        status=1,
        ruleCatch="AND",
        conditions=[Condition(field="amount", operator="GREATER_THAN", value="5000000")],
    )
    assert r.id is None
    assert r.status == 1


def test_tier_valid():
    t = Tier(
        id=None,
        name="Default Tier",
        status=1,
        priority=1,
        filter="AND",
        conditions=[],
        rules=[
            Rule(
                id=None,
                name="Test Rule",
                status=1,
                ruleCatch="AND",
                conditions=[Condition(field="amount", operator="GREATER_THAN", value="100")],
            )
        ],
    )
    assert t.priority == 1


def test_fraud_profile_valid():
    profile = FraudProfile(
        id=None,
        version=1,
        name="Test Profile",
        filter="AND",
        conditions=[],
        tiers=[
            Tier(
                id=None,
                name="Tier 1",
                status=1,
                priority=1,
                filter="AND",
                conditions=[],
                rules=[
                    Rule(
                        id=None,
                        name="Rule 1",
                        status=1,
                        ruleCatch="AND",
                        conditions=[Condition(field="appid", operator="EQUAL", value="123")],
                    )
                ],
            )
        ],
    )
    assert profile.id is None
    assert len(profile.tiers) == 1


def test_fraud_profile_serializes_null_ids():
    profile = FraudProfile(
        id=None,
        version=1,
        name="Test",
        filter="AND",
        conditions=[],
        tiers=[],
    )
    data = profile.model_dump()
    assert data["id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_schema.py -v
```

Expected: `ImportError: cannot import name 'Condition'`

- [ ] **Step 3: Implement schema**

```python
# agent/schema.py
from typing import Optional
from pydantic import BaseModel


class Condition(BaseModel):
    id: Optional[int] = None
    field: str
    operator: str
    value: str


class Rule(BaseModel):
    id: Optional[int] = None
    name: str
    status: int = 1
    ruleCatch: str = "AND"
    conditions: list[Condition]


class Tier(BaseModel):
    id: Optional[int] = None
    name: str
    status: int = 1
    priority: int = 1
    filter: str = "AND"
    conditions: list[Condition]
    rules: list[Rule]


class FraudProfile(BaseModel):
    id: Optional[int] = None
    version: int = 1
    name: str
    filter: str = "AND"
    conditions: list[Condition]
    tiers: list[Tier]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_schema.py -v
```

Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/schema.py tests/test_schema.py
git commit -m "feat: add Pydantic schema for fraud engine JSON"
```

---

### Task 4: LLM system prompts

**Files:**
- Create: `agent/prompts.py`
- Create: `tests/test_prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompts.py
from agent.prompts import PARSE_SYSTEM_PROMPT, RULE_BUILDER_SYSTEM_PROMPT


def test_parse_prompt_contains_required_instructions():
    assert "JSON" in PARSE_SYSTEM_PROMPT
    assert "conditions" in PARSE_SYSTEM_PROMPT
    assert "action" in PARSE_SYSTEM_PROMPT


def test_rule_builder_prompt_contains_schema_description():
    assert "FraudProfile" in RULE_BUILDER_SYSTEM_PROMPT or "tiers" in RULE_BUILDER_SYSTEM_PROMPT
    assert "null" in RULE_BUILDER_SYSTEM_PROMPT
    assert "JSON" in RULE_BUILDER_SYSTEM_PROMPT


def test_rule_builder_prompt_contains_validation_errors_placeholder():
    assert "{validation_errors}" in RULE_BUILDER_SYSTEM_PROMPT or "validation_errors" in RULE_BUILDER_SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_prompts.py -v
```

Expected: `ImportError: cannot import name 'PARSE_SYSTEM_PROMPT'`

- [ ] **Step 3: Implement prompts**

```python
# agent/prompts.py

PARSE_SYSTEM_PROMPT = """You are a fraud rule analyst. Extract structured intent from a free-text fraud pattern description.

The user will describe a fraud check scenario. Extract the following and return ONLY valid JSON:

{
  "profile_name": "<descriptive name for this rule set>",
  "filter": "AND",
  "profile_conditions": [],
  "tier_name": "<tier name>",
  "tier_filter": "AND",
  "tier_conditions": [],
  "rule_name": "<rule name>",
  "rule_catch": "AND",
  "conditions": [
    {
      "field": "<field being checked, e.g. amount, appid, fundingSource, cardNumber>",
      "operator": "<EQUAL | NOT_EQUAL | GREATER_THAN | LESS_THAN | GREATER_THAN_OR_EQUAL | LESS_THAN_OR_EQUAL | CONTAINS | IN>",
      "value": "<value as string>"
    }
  ],
  "action": "<REJECT | ALLOW | REVIEW>"
}

Rules:
- Infer field names from context (e.g. "số tiền" → amount, "nguồn tiền" → fundingSource, "appid" → appid, "số thẻ" → cardNumber)
- Convert Vietnamese number words to digits (e.g. "5 triệu" → "5000000")
- Operators must be one of: EQUAL, NOT_EQUAL, GREATER_THAN, LESS_THAN, GREATER_THAN_OR_EQUAL, LESS_THAN_OR_EQUAL, CONTAINS, IN
- Return ONLY the JSON object, no explanation
"""

RULE_BUILDER_SYSTEM_PROMPT = """You are a fraud engine configuration generator. Convert parsed fraud intent into a complete JSON rule config.

The fraud engine schema is:

{
  "id": null,
  "version": 1,
  "name": "<profile name>",
  "filter": "AND",
  "conditions": [],
  "tiers": [
    {
      "id": null,
      "name": "<tier name>",
      "status": 1,
      "priority": 1,
      "filter": "AND",
      "conditions": [],
      "rules": [
        {
          "id": null,
          "name": "<rule name>",
          "status": 1,
          "ruleCatch": "AND",
          "conditions": [
            {
              "id": null,
              "field": "<field>",
              "operator": "<operator>",
              "value": "<value>"
            }
          ]
        }
      ]
    }
  ]
}

IMPORTANT:
- All "id" fields MUST be null (the fraud engine assigns IDs on import)
- status is always 1 (active)
- Return ONLY the JSON object, no explanation, no markdown fences
- If there are validation_errors from a previous attempt, fix those specific issues

Parsed intent:
{parsed_intent}

Previous validation errors (fix these if present):
{validation_errors}
"""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_prompts.py -v
```

Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/prompts.py tests/test_prompts.py
git commit -m "feat: add LLM system prompts for parse and rule builder nodes"
```

---

### Task 5: LangGraph nodes

**Files:**
- Create: `agent/nodes.py`
- Create: `tests/test_nodes.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_nodes.py
import json
import pytest
from unittest.mock import patch, MagicMock
from agent.state import FraudRuleState
from agent.nodes import parse_node, rule_builder_node, validator_node


def make_state(**kwargs) -> FraudRuleState:
    defaults: FraudRuleState = {
        "raw_input": "",
        "parsed_intent": {},
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
    }
    defaults.update(kwargs)
    return defaults


def test_validator_node_valid_schema():
    valid_draft = {
        "id": None,
        "version": 1,
        "name": "Test",
        "filter": "AND",
        "conditions": [],
        "tiers": [
            {
                "id": None,
                "name": "T1",
                "status": 1,
                "priority": 1,
                "filter": "AND",
                "conditions": [],
                "rules": [
                    {
                        "id": None,
                        "name": "R1",
                        "status": 1,
                        "ruleCatch": "AND",
                        "conditions": [
                            {"id": None, "field": "amount", "operator": "GREATER_THAN", "value": "1000"}
                        ],
                    }
                ],
            }
        ],
    }
    state = make_state(json_draft=valid_draft)
    result = validator_node(state)
    assert result["validation_errors"] == []
    assert result["final_output"] == valid_draft


def test_validator_node_invalid_schema():
    invalid_draft = {"id": None, "version": 1}  # missing required fields
    state = make_state(json_draft=invalid_draft, retry_count=0)
    result = validator_node(state)
    assert len(result["validation_errors"]) > 0
    assert result["retry_count"] == 1
    assert result["final_output"] == {}


def test_validator_node_max_retries_exceeded():
    invalid_draft = {"id": None}
    state = make_state(json_draft=invalid_draft, retry_count=2)
    result = validator_node(state)
    assert result["retry_count"] == 3
    assert result["final_output"] == {}


@patch("agent.nodes.anthropic_client")
def test_parse_node_calls_llm(mock_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "profile_name": "Test",
        "filter": "AND",
        "profile_conditions": [],
        "tier_name": "Tier 1",
        "tier_filter": "AND",
        "tier_conditions": [],
        "rule_name": "Rule 1",
        "rule_catch": "AND",
        "conditions": [{"field": "amount", "operator": "GREATER_THAN", "value": "5000000"}],
        "action": "REJECT",
    }))]
    mock_client.messages.create.return_value = mock_response

    state = make_state(raw_input="amount > 5 million reject")
    result = parse_node(state)
    assert result["parsed_intent"]["profile_name"] == "Test"
    assert len(result["parsed_intent"]["conditions"]) == 1


@patch("agent.nodes.anthropic_client")
def test_rule_builder_node_calls_llm(mock_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "id": None,
        "version": 1,
        "name": "Test Profile",
        "filter": "AND",
        "conditions": [],
        "tiers": [],
    }))]
    mock_client.messages.create.return_value = mock_response

    state = make_state(parsed_intent={"profile_name": "Test Profile"})
    result = rule_builder_node(state)
    assert result["json_draft"]["name"] == "Test Profile"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_nodes.py -v
```

Expected: `ImportError: cannot import name 'parse_node'`

- [ ] **Step 3: Implement nodes**

```python
# agent/nodes.py
import json
import os
import anthropic
from pydantic import ValidationError
from agent.state import FraudRuleState
from agent.schema import FraudProfile
from agent.prompts import PARSE_SYSTEM_PROMPT, RULE_BUILDER_SYSTEM_PROMPT

anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


def parse_node(state: FraudRuleState) -> FraudRuleState:
    response = anthropic_client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=PARSE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": state["raw_input"]}],
    )
    text = next(block.text for block in response.content if hasattr(block, "text"))
    parsed = json.loads(text)
    return {**state, "parsed_intent": parsed}


def rule_builder_node(state: FraudRuleState) -> FraudRuleState:
    prompt = RULE_BUILDER_SYSTEM_PROMPT.format(
        parsed_intent=json.dumps(state["parsed_intent"], indent=2, ensure_ascii=False),
        validation_errors=json.dumps(state["validation_errors"], ensure_ascii=False) if state["validation_errors"] else "none",
    )
    response = anthropic_client.messages.create(
        model="claude-opus-4-8",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=prompt,
        messages=[{"role": "user", "content": "Generate the fraud rule JSON config."}],
    )
    text = next(block.text for block in response.content if hasattr(block, "text"))
    draft = json.loads(text)
    return {**state, "json_draft": draft, "validation_errors": []}


def validator_node(state: FraudRuleState) -> FraudRuleState:
    try:
        FraudProfile.model_validate(state["json_draft"])
        return {**state, "validation_errors": [], "final_output": state["json_draft"]}
    except ValidationError as e:
        errors = [err["msg"] for err in e.errors()]
        return {
            **state,
            "validation_errors": errors,
            "final_output": {},
            "retry_count": state["retry_count"] + 1,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_nodes.py -v
```

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/nodes.py tests/test_nodes.py
git commit -m "feat: implement LangGraph nodes — parse, rule_builder, validator"
```

---

### Task 6: LangGraph graph assembly

**Files:**
- Create: `agent/graph.py`
- Create: `tests/test_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph.py
from unittest.mock import patch, MagicMock
import json
from agent.graph import build_graph, should_retry


def make_invalid_state(retry_count=0):
    return {
        "raw_input": "test",
        "parsed_intent": {},
        "json_draft": {},
        "validation_errors": ["missing field: name"],
        "final_output": {},
        "retry_count": retry_count,
    }


def make_valid_state():
    return {
        "raw_input": "test",
        "parsed_intent": {},
        "json_draft": {"id": None, "version": 1, "name": "Test", "filter": "AND", "conditions": [], "tiers": []},
        "validation_errors": [],
        "final_output": {"id": None, "name": "Test"},
        "retry_count": 0,
    }


def test_should_retry_when_errors_and_under_limit():
    state = make_invalid_state(retry_count=1)
    assert should_retry(state) == "rule_builder"


def test_should_end_when_no_errors():
    state = make_valid_state()
    assert should_retry(state) == "__end__"


def test_should_end_when_max_retries_exceeded():
    state = make_invalid_state(retry_count=2)
    assert should_retry(state) == "__end__"


def test_build_graph_returns_compilable_graph():
    graph = build_graph()
    assert graph is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_graph.py -v
```

Expected: `ImportError: cannot import name 'build_graph'`

- [ ] **Step 3: Implement graph**

```python
# agent/graph.py
from langgraph.graph import StateGraph, END
from agent.state import FraudRuleState
from agent.nodes import parse_node, rule_builder_node, validator_node

MAX_RETRIES = 2


def should_retry(state: FraudRuleState) -> str:
    if state["validation_errors"] and state["retry_count"] < MAX_RETRIES:
        return "rule_builder"
    return "__end__"


def build_graph():
    builder = StateGraph(FraudRuleState)
    builder.add_node("parse", parse_node)
    builder.add_node("rule_builder", rule_builder_node)
    builder.add_node("validator", validator_node)

    builder.set_entry_point("parse")
    builder.add_edge("parse", "rule_builder")
    builder.add_edge("rule_builder", "validator")
    builder.add_conditional_edges("validator", should_retry, {
        "rule_builder": "rule_builder",
        "__end__": END,
    })

    return builder.compile()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_graph.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agent/graph.py tests/test_graph.py
git commit -m "feat: assemble LangGraph graph with retry conditional edge"
```

---

### Task 7: CLI entry point

**Files:**
- Create: `cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json
from unittest.mock import patch, MagicMock
from cli import run_cli


def make_final_state():
    return {
        "raw_input": "appid 123 reject all",
        "parsed_intent": {"profile_name": "Test"},
        "json_draft": {},
        "validation_errors": [],
        "final_output": {
            "id": None,
            "version": 1,
            "name": "Test Profile",
            "filter": "AND",
            "conditions": [],
            "tiers": [],
        },
        "retry_count": 0,
    }


@patch("cli.build_graph")
def test_run_cli_returns_final_output(mock_build_graph):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = make_final_state()
    mock_build_graph.return_value = mock_graph

    result = run_cli("appid 123 reject all")
    assert result["id"] is None
    assert result["name"] == "Test Profile"


@patch("cli.build_graph")
def test_run_cli_returns_draft_on_validation_failure(mock_build_graph):
    failed_state = {
        "raw_input": "test",
        "parsed_intent": {},
        "json_draft": {"id": None, "name": "Partial"},
        "validation_errors": ["missing field: tiers"],
        "final_output": {},
        "retry_count": 2,
    }
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = failed_state
    mock_build_graph.return_value = mock_graph

    result = run_cli("test")
    assert "_error" in result
    assert result["_draft"]["name"] == "Partial"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError: cannot import name 'run_cli'`

- [ ] **Step 3: Implement CLI**

```python
# cli.py
import json
import sys
from dotenv import load_dotenv
from agent.graph import build_graph

load_dotenv()


def run_cli(raw_input: str) -> dict:
    graph = build_graph()
    state = graph.invoke({
        "raw_input": raw_input,
        "parsed_intent": {},
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
    })
    if state["final_output"]:
        return state["final_output"]
    return {
        "_error": "Validation failed after max retries",
        "_validation_errors": state["validation_errors"],
        "_draft": state["json_draft"],
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raw = " ".join(sys.argv[1:])
    else:
        print("Enter fraud pattern (end with Ctrl+D):")
        raw = sys.stdin.read().strip()

    result = run_cli(raw)
    print(json.dumps(result, indent=2, ensure_ascii=False))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add cli.py tests/test_cli.py
git commit -m "feat: add CLI entry point"
```

---

### Task 8: FastAPI HTTP endpoint

**Files:**
- Create: `api/main.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def make_final_state(name="API Test Profile"):
    return {
        "raw_input": "test",
        "parsed_intent": {},
        "json_draft": {},
        "validation_errors": [],
        "final_output": {
            "id": None,
            "version": 1,
            "name": name,
            "filter": "AND",
            "conditions": [],
            "tiers": [],
        },
        "retry_count": 0,
    }


@patch("api.main.build_graph")
def test_generate_rule_success(mock_build_graph):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = make_final_state()
    mock_build_graph.return_value = mock_graph

    response = client.post("/generate-rule", json={"input": "appid 123 reject"})
    assert response.status_code == 200
    data = response.json()
    assert data["id"] is None
    assert data["name"] == "API Test Profile"


@patch("api.main.build_graph")
def test_generate_rule_validation_failure(mock_build_graph):
    mock_graph = MagicMock()
    mock_graph.invoke.return_value = {
        "raw_input": "test",
        "parsed_intent": {},
        "json_draft": {"id": None},
        "validation_errors": ["missing: name"],
        "final_output": {},
        "retry_count": 2,
    }
    mock_build_graph.return_value = mock_graph

    response = client.post("/generate-rule", json={"input": "bad input"})
    assert response.status_code == 422
    data = response.json()
    assert "validation_errors" in data["detail"]


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
pytest tests/test_api.py -v
```

Expected: `ImportError: cannot import name 'app'`

- [ ] **Step 3: Implement FastAPI app**

```python
# api/main.py
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent.graph import build_graph

load_dotenv()

app = FastAPI(title="Fraud Rule Suggestion Agent")


class RuleRequest(BaseModel):
    input: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/generate-rule")
def generate_rule(request: RuleRequest):
    graph = build_graph()
    state = graph.invoke({
        "raw_input": request.input,
        "parsed_intent": {},
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
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

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_api.py
git commit -m "feat: add FastAPI HTTP endpoint for agent-to-agent mode"
```

---

### Task 9: Full test suite + smoke test

**Files:**
- Verify all tests pass
- Smoke test end-to-end with real API key

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests PASS (no skips, no errors)

- [ ] **Step 2: Smoke test CLI (requires ANTHROPIC_API_KEY)**

```bash
cp .env.example .env
# Edit .env and add your real ANTHROPIC_API_KEY
python cli.py "appid là 123, nếu số tiền giao dịch lớn hơn 5 triệu và nguồn tiền là ví điện tử thì reject"
```

Expected: Valid JSON printed to stdout with `id: null`, `tiers` array, `conditions` with amount and fundingSource fields.

- [ ] **Step 3: Smoke test API (requires ANTHROPIC_API_KEY)**

```bash
uvicorn api.main:app --reload &
curl -s -X POST http://localhost:8000/generate-rule \
  -H "Content-Type: application/json" \
  -d '{"input": "appid 456, block if card number starts with 4111"}' | python -m json.tool
```

Expected: JSON response with `id: null` and fraud engine schema structure.

- [ ] **Step 4: Stop uvicorn and commit**

```bash
# Ctrl+C to stop uvicorn
git add .
git commit -m "feat: MVP complete — fraud rule suggestion agent"
```

---

## Self-Review

**Spec coverage:**
- ✅ CLI entry point — Task 7
- ✅ FastAPI HTTP endpoint — Task 8
- ✅ ParseNode with LLM — Task 5
- ✅ RuleBuilderNode with LLM — Task 5
- ✅ ValidatorNode with Pydantic — Task 5
- ✅ Retry loop up to 2x — Task 6 (`should_retry`, `MAX_RETRIES = 2`)
- ✅ `id: null` on create — Task 3 (schema), Task 4 (prompt)
- ✅ Free-text Vietnamese/English input — Task 4 (prompts include Vietnamese field mapping)
- ✅ Profile → Tiers → Rules → Conditions hierarchy — Task 3

**Type consistency check:**
- `FraudRuleState` defined in Task 2, used in Tasks 5, 6, 7, 8 — consistent
- `FraudProfile`, `Tier`, `Rule`, `Condition` defined in Task 3, used in Task 5 (`validator_node`) — consistent
- `build_graph()` defined in Task 6, imported in Task 7 (`cli.py`) and Task 8 (`api/main.py`) — consistent
- `parse_node`, `rule_builder_node`, `validator_node` defined in Task 5, imported in Task 6 — consistent

**No placeholders found.**
