# Fraud Rule Suggestion Agent — MVP Design

**Date:** 2026-06-13  
**Status:** Draft

---

## Overview

A LangGraph-based agent that reads a fraud pattern (free-text from CLI or structured JSON from another agent) and outputs a JSON rule config compatible with the in-house fraud engine schema.

---

## Input

Two entry modes:

1. **CLI** — user types free-text describing the fraud pattern, e.g.:
   > "appid 123, nếu số tiền > 5 triệu và nguồn tiền là ví điện tử thì reject"

2. **Agent mode** — receives a JSON payload via HTTP (FastAPI) from another agent:
   ```json
   { "input": "free-text pattern string" }
   ```

Both modes feed the same LangGraph pipeline.

---

## Architecture

Three LangGraph nodes in sequence, with retry loop on validation failure:

```
[ParseNode] → [RuleBuilderNode] → [ValidatorNode]
                    ↑                    |
                    └────────────────────┘  (retry up to 2x if invalid)
```

### Graph State

```python
class FraudRuleState(TypedDict):
    raw_input: str
    parsed_intent: dict        # extracted entities
    json_draft: dict           # generated rule config
    validation_errors: list    # schema errors if any
    final_output: dict         # valid JSON config
    retry_count: int
```

### Node 1 — ParseNode

- Uses LLM to extract structured intent from free-text
- Output: `parsed_intent` with fields like:
  ```json
  {
    "profile_name": "...",
    "filter": "AND",
    "conditions": [
      { "field": "amount", "operator": "GREATER_THAN", "value": "5000000" }
    ],
    "action": "reject",
    "tier_name": "..."
  }
  ```

### Node 2 — RuleBuilderNode

- Takes `parsed_intent` and generates a full JSON rule config matching the fraud engine schema
- Uses a system prompt that includes the schema structure and example config
- Output: `json_draft`

### Node 3 — ValidatorNode

- Validates `json_draft` against required schema fields using Pydantic models
- If valid: sets `final_output`, ends graph
- If invalid: appends errors to `validation_errors`, increments `retry_count`
- If `retry_count >= 2`: returns error response with `json_draft` for manual fix

---

## Output

Valid JSON rule config matching fraud engine schema:

```json
{
  "id": null,
  "version": 1,
  "name": "...",
  "filter": "AND",
  "conditions": [...],
  "tiers": [
    {
      "name": "...",
      "status": 1,
      "priority": 1,
      "filter": "AND",
      "conditions": [...],
      "rules": [
        {
          "name": "...",
          "status": 1,
          "ruleCatch": "AND",
          "conditions": [...]
        }
      ]
    }
  ]
}
```

`id` fields are `null` on create — fraud engine assigns them on import.

---

## Tech Stack

- Python 3.11+
- LangGraph + LangChain
- Claude (Anthropic SDK) as LLM
- Pydantic for schema validation
- FastAPI for HTTP endpoint (agent mode)
- `python-dotenv` for config

---

## Project Structure

```
my-agent/
├── agent/
│   ├── graph.py          # LangGraph graph definition
│   ├── nodes.py          # ParseNode, RuleBuilderNode, ValidatorNode
│   ├── state.py          # FraudRuleState TypedDict
│   ├── schema.py         # Pydantic models for fraud engine schema
│   └── prompts.py        # LLM system prompts
├── api/
│   └── main.py           # FastAPI app (agent mode entry point)
├── cli.py                # CLI entry point
├── requirements.txt
└── .env.example
```

---

## Out of Scope (MVP)

- Mapping cứng giữa business terms và schema IDs (dùng LLM suy luận)
- UI/dashboard
- Storing generated rules to database
- Authentication cho HTTP endpoint
- Multi-language support beyond Vietnamese/English

---

## Success Criteria (MVP)

1. CLI nhận free-text, xuất valid JSON config
2. FastAPI endpoint nhận `{"input": "..."}`, trả về JSON config
3. Validator bắt được missing required fields
4. Retry logic hoạt động (tối đa 2 lần)
