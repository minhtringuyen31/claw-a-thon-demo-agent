# Config Agent V2 — Design Spec

**Date:** 2026-06-15  
**Status:** Approved

---

## Overview

Rebuild hoàn toàn fraud rule suggestion agent theo diagram "Config Agent — runtime & flow". Agent nhận plain text pattern, sinh JSON rule config hợp lệ cho fraud engine, và lưu file output. Không có clarify_loop, human_review_node, hay dry-run config-service (để sau).

---

## Input

- **Một nguồn duy nhất:** plain text (CLI hoặc HTTP)
- **Ví dụ:** `"appid 123, nếu số tiền > 5 triệu và nguồn tiền là ví điện tử thì reject"`

---

## Architecture

```
[plain text input]
       ↓
  intake_node (LLM)
  normalize → structured requirement
       ↓
  planner_node (LLM)
  liệt kê components cần tạo
       ↓
  dependency_resolver (no LLM)
  query mock config-service → create vs update
       ↓
  build_config_node (LLM)
  generate full JSON config
       ↓
  validator_node (Pydantic)
  validate schema, retry tối đa 2x
       ↓
  output_node
  lưu file JSON + stdout
```

---

## Graph State

```python
class ConfigAgentState(TypedDict):
    raw_input: str
    requirement: dict        # output intake_node
    plan: dict               # output planner_node
    existing_config: dict    # kết quả query mock config-service
    operation: str           # "create" hoặc "update"
    json_draft: dict         # output build_config_node
    validation_errors: list  # Pydantic errors nếu có
    final_output: dict       # validated JSON config
    retry_count: int         # số lần retry validator
    output_file: str         # path file đã lưu
```

---

## Node Details

### intake_node (LLM)
Normalize free-text input thành structured requirement.

Output `requirement`:
```json
{
  "app_id": "123",
  "profile_name": "Fraud Check App 123",
  "description": "Reject high amount e-wallet transactions",
  "conditions": [
    {"field": "amount", "operator": "GREATER_THAN", "value": "5000000"},
    {"field": "fundingSource", "operator": "EQUAL", "value": "ví điện tử"}
  ],
  "action": "REJECT"
}
```

### planner_node (LLM)
Đọc requirement, liệt kê components sẽ cần trong JSON output.

Output `plan`:
```json
{
  "profile_name": "Fraud Check App 123",
  "tiers": [{"name": "High Amount E-wallet Tier", "priority": 1}],
  "rules": [{"name": "Reject High Amount E-wallet", "tier": "High Amount E-wallet Tier"}],
  "conditions_count": 2
}
```

### dependency_resolver (no LLM)
Query mock config-service để kiểm tra profile đã tồn tại chưa.

- `GET /api/profiles?app_id=<id>` → có → `operation="update"`, lưu `existing_config`
- Không có → `operation="create"`, `existing_config={}`

### build_config_node (LLM)
Nhận `requirement` + `plan` + `existing_config` + `operation` → generate JSON hoàn chỉnh theo fraud engine schema. Nếu `operation="update"`, merge với `existing_config`.

### validator_node (Pydantic)
Validate `json_draft` với Pydantic models. Nếu fail: tăng `retry_count`, trả về errors. Graph retry về `build_config_node` tối đa 2 lần.

### output_node
Lưu `final_output` vào `output/<profile_name>_<timestamp>.json`. In JSON ra stdout.

---

## Mock Config Service

```python
class MockConfigService:
    def get_profile(self, app_id: str) -> dict | None: ...
    def save_profile(self, profile: dict) -> dict: ...
```

Lưu in-memory (dict). Khi production ready, swap bằng `RealConfigService` với HTTP calls — interface giữ nguyên.

---

## Fraud Engine Schema (unchanged)

```json
{
  "id": null,
  "version": 1,
  "name": "...",
  "filter": "AND",
  "conditions": [],
  "tiers": [
    {
      "id": null,
      "name": "...",
      "status": 1,
      "priority": 1,
      "filter": "AND",
      "conditions": [],
      "rules": [
        {
          "id": null,
          "name": "...",
          "status": 1,
          "ruleCatch": "AND",
          "conditions": [
            {"id": null, "field": "...", "operator": "...", "value": "..."}
          ]
        }
      ]
    }
  ]
}
```

`id` fields là `null` — fraud engine assign khi import.

---

## File Structure

```
my-agent/
├── agent/
│   ├── state.py                  # ConfigAgentState TypedDict
│   ├── schema.py                 # Pydantic models (unchanged)
│   ├── prompts.py                # intake, planner, build_config prompts
│   ├── nodes.py                  # 6 nodes
│   └── graph.py                  # LangGraph graph
├── services/
│   └── mock_config_service.py    # MockConfigService
├── api/
│   └── main.py                   # FastAPI endpoint
├── cli.py                        # CLI với -o flag
├── output/                       # JSON output files
└── tests/
    ├── test_state.py
    ├── test_schema.py
    ├── test_prompts.py
    ├── test_nodes.py
    ├── test_graph.py
    ├── test_mock_service.py
    ├── test_cli.py
    └── test_api.py
```

---

## Tech Stack

- Python 3.11+
- LangGraph + LangChain
- OpenAI SDK (GreenNode AIP compatible)
- LLM: `minimax/minimax-m2.5` qua GreenNode AIP
- Pydantic v2
- FastAPI + uvicorn
- python-dotenv

---

## Out of Scope (V2)

- clarify_loop (hỏi lại khi mơ hồ)
- human_review_node (confirm trước khi apply)
- Dry-run qua config-service thật
- Knowledge base / RAG
- Input từ Risk Agent (structured RuleJSON)

---

## Success Criteria

1. CLI nhận plain text → xuất valid JSON file
2. `dependency_resolver` phân biệt được create vs update
3. Validator retry đúng tối đa 2 lần
4. Swap MockConfigService → RealConfigService không cần sửa node code
