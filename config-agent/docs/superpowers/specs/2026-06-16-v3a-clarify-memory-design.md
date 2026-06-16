# Config Agent V3a — Clarify Loop + Web UI + Memory

**Date:** 2026-06-16  
**Status:** Approved  
**Builds on:** V2 (feat/fraud-rule-agent branch)

---

## Overview

Thêm 3 tính năng vào Config Agent V2:
1. **clarify_loop** — agent hỏi lại human khi input mập mờ (không giới hạn vòng)
2. **Web UI** — giao diện chat HTML phục vụ từ FastAPI
3. **Memory** — lưu conversation, profiles, preferences qua AgentBase Memory Service

Đồng thời **thay thế hoàn toàn output schema** từ `FraudProfile` (tiers/rules) sang format `events` mới.

Không thay đổi luồng `/generate-config` (agent-to-agent). Không implement MySQL hay velocity rules (V3b).

---

## Endpoints

### `POST /chat` (mới — dành cho human)

```
Request:
{
  "session_id": "uuid-do-client-gen",
  "message": "appid 123, chặn giao dịch lạ",
  "clarification_answer": ""        // rỗng lần đầu, điền khi trả lời câu hỏi
}

Response — cần hỏi lại:
{
  "status": "clarify",
  "question": "Bạn muốn chặn theo tiêu chí nào? Số tiền, nguồn tiền, hay tần suất?",
  "session_id": "uuid-do-client-gen"
}

Response — hoàn tất:
{
  "status": "done",
  "final_output": { ...fraud profile JSON... },
  "output_file": "output/Fraud_Check_App_123_20260616_001317.json"
}

Response — lỗi:
{
  "status": "error",
  "message": "Validation failed after max retries"
}
```

### `POST /generate-config` (giữ nguyên — dành cho agent)

Không thay đổi contract. Chỉ update state shape bên trong để dùng đúng 14 field của V3a state. Không có clarify, trả về kết quả đồng bộ.

---

## Graph State (V3a)

Thêm 4 field mới vào `ConfigAgentState`:

```python
class ConfigAgentState(TypedDict):
    # --- V2 fields (giữ nguyên) ---
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

    # --- V3a fields (mới) ---
    session_id: str             # key cho AgentBase Memory
    clarify_question: str       # câu hỏi agent muốn hỏi
    clarification_answer: str   # câu trả lời từ human
    needs_clarification: bool   # flag để API layer dừng sớm
```

---

## Architecture

```
POST /chat
    │
    ▼
memory_load_node          ← load prefs + conversation từ Memory
    │
    ▼
intake_node (LLM)         ← normalize raw_input, context-aware nhờ prefs
    │
    ▼
clarify_node (LLM)        ← đánh giá độ rõ của requirement
    │
    ├── needs_clarification=True ──▶ END
    │                                (API trả về {status:"clarify", question})
    │
    └── needs_clarification=False
            │
            ▼
    dependency_resolver   ← MockConfigService (V2, giữ nguyên)
            │
            ▼
    planner_node (LLM)
            │
            ▼
    build_config_node (LLM)
            │
            ▼
    validator_node (Pydantic) ──[retry]──▶ build_config_node
            │
         [done]
            │
            ▼
    output_node           ← lưu file JSON
            │
            ▼
    memory_save_node      ← lưu profile + conversation + preferences
            │
            ▼
           END
           (API trả về {status:"done", final_output, output_file})
```

---

## Node Details

### memory_load_node (mới, no LLM)

Load 2 loại data từ AgentBase Memory Service:

| Key | Nội dung |
|-----|----------|
| `session:{session_id}` | Lịch sử conversation của phiên này |
| `prefs:global` | Preferences: action mặc định, field hay dùng |

Nếu Memory không có data → trả về dict rỗng, không lỗi.

Output vào state: inject vào `requirement` context (preferences) để `intake_node` dùng.

### clarify_node (mới, LLM)

Prompt: đánh giá `requirement` có đủ để sinh fraud rule không.

Thiếu thông tin **bắt buộc** mới hỏi lại:
- `app_id` không xác định được
- `action` (REJECT/REVIEW/ALLOW) không rõ
- Không có condition nào

**Không hỏi** nếu có thể suy ra được (VD: "chặn" → REJECT, "cảnh báo" → REVIEW).

Nếu `clarification_answer` đã có trong state → **skip**, đi thẳng (merge answer vào requirement).

Output:
```python
{"needs_clarification": True, "clarify_question": "Bạn muốn chặn hay chỉ cảnh báo?"}
# hoặc
{"needs_clarification": False, "clarify_question": ""}
```

### memory_save_node (mới, no LLM)

Lưu 3 loại data sau khi output_node chạy xong:

| Key | Nội dung |
|-----|----------|
| `session:{session_id}` | Append conversation turn: `{input, answer, output_file}` |
| `profile:{app_id}` | `final_output` (thay thế MockConfigService trong memory) |
| `prefs:global` | Cập nhật: action cuối dùng, field hay xuất hiện |

---

## Prompts mới

### CLARIFY_SYSTEM

```
Bạn là fraud rule clarity checker. Đánh giá xem requirement có đủ thông tin để tạo fraud rule không.

Chỉ hỏi lại khi thiếu thông tin BẮT BUỘC:
- Không xác định được app_id
- Không rõ action (REJECT/REVIEW/ALLOW)
- Không có bất kỳ condition nào

KHÔNG hỏi khi có thể suy ra: "chặn" = REJECT, "cảnh báo" = REVIEW, "cho qua" = ALLOW.

Trả về JSON:
{
  "needs_clarification": true/false,
  "question": "câu hỏi nếu needs_clarification=true, rỗng nếu false"
}
```

### CLARIFY_USER

```
Requirement hiện tại:
{requirement}

Clarification answer (nếu có):
{clarification_answer}

Đánh giá xem requirement có đủ rõ không.
```

---

## Web UI (`static/index.html`)

File HTML tĩnh, serve từ FastAPI qua `StaticFiles`. Không cần framework JS.

**Tính năng:**
- Chat bubble 2 chiều (user bên phải — tím, agent bên trái — xám)
- `session_id` sinh 1 lần khi load trang, lưu `localStorage`
- Gửi `POST /chat`, xử lý 2 loại response:
  - `status:"clarify"` → hiển thị câu hỏi, cho user nhập đáp án, gửi lại với `clarification_answer`
  - `status:"done"` → hiển thị JSON config, nút Copy + Tải file
- Loading indicator khi đang chờ response

**Mount trong FastAPI:**
```python
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
```

---

## Memory Service Integration

Dùng **AgentBase Memory Service** qua SDK GreenNode (`greennode-agentbase` hoặc HTTP API).

Credentials tự inject bởi AgentBase Runtime (`GREENNODE_CLIENT_ID`, `GREENNODE_CLIENT_SECRET`) — không cần config thêm trong `.env`.

**Interface:**
```python
class MemoryService:
    def get(self, key: str) -> dict | None: ...
    def set(self, key: str, value: dict) -> None: ...
    def append(self, key: str, item: dict) -> None: ...
```

Implement `MockMemoryService` (in-memory dict) để test, swap bằng `AgentBaseMemoryService` khi deploy.

---

## File Structure (thay đổi)

```
my-agent/
├── agent/
│   ├── state.py          ← thêm 4 field mới
│   ├── prompts.py        ← thêm CLARIFY_SYSTEM, CLARIFY_USER
│   ├── nodes.py          ← thêm clarify_node, memory_load_node, memory_save_node
│   └── graph.py          ← update graph: thêm nodes + conditional edge
├── services/
│   ├── mock_config_service.py   ← giữ nguyên
│   └── memory_service.py        ← mới: MockMemoryService + AgentBaseMemoryService interface
├── api/
│   └── main.py           ← thêm POST /chat, mount StaticFiles, GET /
├── static/
│   └── index.html        ← mới: Web UI chat
└── tests/
    ├── test_state.py      ← thêm test 4 field mới
    ├── test_prompts.py    ← thêm test CLARIFY prompts
    ├── test_nodes.py      ← thêm test clarify_node, memory nodes
    ├── test_memory_service.py  ← mới
    └── test_api.py        ← thêm test POST /chat (clarify + done flows)
```

---

## Success Criteria

1. `/chat` trả về `{status:"clarify"}` khi input mập mờ
2. `/chat` trả về `{status:"done"}` sau khi user trả lời đủ
3. `/generate-config` không thay đổi behavior (agent-to-agent vẫn hoạt động)
4. Web UI hiển thị chat bubble, xử lý clarify/done đúng
5. Memory load/save không làm crash khi Memory Service chưa có data
6. Swap MockMemoryService → AgentBaseMemoryService không cần sửa node code

---

## Output Schema Mới (thay thế FraudProfile)

`agent/schema.py` được viết lại hoàn toàn:

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
    actionCode: str          # "REJECT" | "REVIEW" | "ALLOW"
    decisionCode: str = ""
    variables: list[Variable] = []   # để [] trong V3a, V3b populate từ accumulation_key
    rules: list[Rule]

class FraudConfig(BaseModel):
    events: list[Event]
```

`validator_node` validate `json_draft` với `FraudConfig(**json_draft)`.

`BUILD_CONFIG_SYSTEM` prompt cập nhật schema mới để LLM sinh đúng format.

---

## Out of Scope (V3a)

- Populate `variables[].source.keyId` từ accumulation_key — V3b
- MySQL integration (event config, accumulate keys) — V3b
- Velocity rule support — V3b
- Multi-user session isolation
- Rate limiting trên `/chat`
