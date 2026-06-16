# Config Agent — Fraud Rule Generator

Agent tự động tạo fraud rule config từ mô tả ngôn ngữ tự nhiên, hỗ trợ multi-round clarification và memory theo session.

---

## Tổng quan

Config Agent nhận input là mô tả pattern gian lận bằng tiếng Việt/Anh, tự động hỏi lại khi thiếu thông tin, và sinh ra JSON config theo schema FraudConfig events.

**Flow:**

```
Input → Intake → Clarify (≤3 vòng) → Plan → Build Config → Validate → Output JSON
```

---

## Cài đặt

```bash
pip install -r requirements.txt
```

Tạo file `.env`:

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
```

---

## Chạy server

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Web UI: [http://localhost:8000](http://localhost:8000)

---

## API Integration

### Endpoint: `POST /chat`

Endpoint chính để tích hợp. Hỗ trợ multi-round clarification qua `session_id`.

**Request:**

```json
{
  "session_id": "optional-uuid",
  "message": "mô tả fraud pattern",
  "clarification_answer": ""
}
```

| Field | Type | Bắt buộc | Mô tả |
|-------|------|----------|-------|
| `session_id` | string | Không | UUID phiên làm việc. Tự động sinh nếu không truyền. |
| `message` | string | Có | Mô tả fraud pattern (max 4096 ký tự). |
| `clarification_answer` | string | Không | Câu trả lời cho câu hỏi làm rõ ở vòng trước. |

---

### Response: Đang làm rõ (`status: "clarify"`)

Agent cần thêm thông tin. 3rd party phải hỏi người dùng và gửi lại với `clarification_answer`.

```json
{
  "status": "clarify",
  "question": "App_id (hoặc event name như payment, transfer) là bắt buộc. Bạn muốn tạo rule cho ứng dụng nào?",
  "session_id": "fd22ccf0-ca0c-47e9-9306-54faabfd437d"
}
```

---

### Response: Hoàn thành (`status: "done"`)

Config đã được tạo thành công.

```json
{
  "status": "done",
  "session_id": "fd22ccf0-ca0c-47e9-9306-54faabfd437d",
  "output_file": "output/payment_20260616_120000.json",
  "final_output": {
    "events": [
      {
        "name": "payment",
        "description": "Reject payment nếu amount vượt ngưỡng",
        "filter": "AND",
        "actionCode": "REJECT",
        "decisionCode": "",
        "variables": [],
        "rules": [
          {
            "name": "high_amount_rule",
            "description": "Block nếu amount > 5,000,000",
            "conditions": [
              { "field": "amount", "operator": "GREATER_THAN", "value": "5000000" }
            ],
            "infoCode": ""
          }
        ]
      }
    ]
  }
}
```

---

### Response: Lỗi (`status: "error"`)

```json
{
  "status": "error",
  "message": "Validation failed after max retries",
  "session_id": "fd22ccf0-ca0c-47e9-9306-54faabfd437d"
}
```

---

## Luồng tích hợp multi-round

### Round 1 — Gửi yêu cầu ban đầu

**Request:**
```bash
curl -X POST http://url/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "tôi muốn block giao dịch lớn"}'
```

**Response:**
```json
{
  "status": "clarify",
  "question": "App_id (hoặc event name như payment, transfer) là bắt buộc. Bạn muốn tạo rule cho ứng dụng nào?",
  "session_id": "fd22ccf0-ca0c-47e9-9306-54faabfd437d"
}
```

→ Lưu `session_id`, hiển thị `question` cho người dùng.

---

### Round 2 — Trả lời câu hỏi làm rõ

**Request:**
```bash
curl -X POST http://url/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "fd22ccf0-ca0c-47e9-9306-54faabfd437d",
    "message": "tôi muốn block giao dịch lớn",
    "clarification_answer": "app_id 1020, event payment"
  }'
```

**Response** (nếu vẫn còn thiếu thông tin):
```json
{
  "status": "clarify",
  "question": "Ngưỡng số tiền là bao nhiêu để REJECT? (VD: 5,000,000 VND)",
  "session_id": "fd22ccf0-ca0c-47e9-9306-54faabfd437d"
}
```

---

### Round 3 — Hoàn thành

**Request:**
```bash
curl -X POST http://url/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "fd22ccf0-ca0c-47e9-9306-54faabfd437d",
    "message": "tôi muốn block giao dịch lớn",
    "clarification_answer": "reject nếu amount > 5000000"
  }'
```

**Response:**
```json
{
  "status": "done",
  "session_id": "fd22ccf0-ca0c-47e9-9306-54faabfd437d",
  "output_file": "output/payment_20260616_120000.json",
  "final_output": {
    "events": [
      {
        "name": "payment",
        "description": "Block giao dịch payment khi amount vượt ngưỡng",
        "filter": "AND",
        "actionCode": "REJECT",
        "decisionCode": "",
        "variables": [],
        "rules": [
          {
            "name": "high_amount_rule",
            "description": "Reject nếu amount > 5,000,000",
            "conditions": [
              {
                "field": "amount",
                "operator": "GREATER_THAN",
                "value": "5000000"
              }
            ],
            "infoCode": ""
          }
        ]
      }
    ]
  }
}
```

---

### Tóm tắt flow

| Vòng | Gửi | Nhận |
|------|-----|------|
| 1 | `message` | `clarify` + `question` + `session_id` |
| 2 | `message` + `session_id` + `clarification_answer` | `clarify` hoặc `done` |
| 3 | như trên | `done` (tối đa 3 vòng) |

---

### State machine phía client

```
[START]
  │
  ▼
POST /chat (message, session_id=null)
  │
  ├─ status="clarify" → hiển thị question → lấy answer từ user
  │     └─ POST /chat (message gốc, session_id, clarification_answer)
  │           └─ lặp lại tối đa 3 vòng
  │
  └─ status="done"   → xử lý final_output
  └─ status="error"  → hiển thị lỗi
```

---

## Ví dụ tích hợp Python

```python
import requests

BASE_URL = "http://localhost:8000"

def create_fraud_rule(initial_message: str, ask_user_fn) -> dict:
    """
    ask_user_fn(question: str) -> str  — callback để hỏi người dùng
    """
    session_id = None
    message = initial_message
    clarification_answer = ""

    while True:
        payload = {
            "message": message,
            "clarification_answer": clarification_answer,
        }
        if session_id:
            payload["session_id"] = session_id

        res = requests.post(f"{BASE_URL}/chat", json=payload)
        data = res.json()
        session_id = data["session_id"]

        if data["status"] == "clarify":
            clarification_answer = ask_user_fn(data["question"])
        elif data["status"] == "done":
            return data["final_output"]
        else:
            raise RuntimeError(data.get("message", "Unknown error"))
```

---

## Schema FraudConfig

```json
{
  "events": [
    {
      "name": "string",
      "description": "string",
      "filter": "AND | OR",
      "actionCode": "REJECT | REVIEW | ALLOW",
      "decisionCode": "string",
      "variables": [
        {
          "fieldName": "string",
          "fieldType": "LONG | DOUBLE | STRING",
          "source": { "keyId": "string" }
        }
      ],
      "rules": [
        {
          "name": "string",
          "description": "string",
          "conditions": [
            { "field": "string", "operator": "string", "value": "string" }
          ],
          "infoCode": "string"
        }
      ]
    }
  ]
}
```

### Velocity variables (tự động sinh)

| Condition field | fieldType | source.keyId |
|-----------------|-----------|--------------|
| `count_txn_4h` | LONG | `count_txn_4h\|${userid}` |
| `count_txn_7d` | LONG | `count_txn_7d\|${userid}` |
| `sum_amount_24h` | LONG | `sum_amount_24h\|${userid}` |
| `sum_amount_1d` | LONG | `sum_amount_1d\|${userid}` |

Các field `account_age`, `ekyc`, `amount` là static/derived — không sinh variable entry.

---

## Các endpoint khác

### `GET /health`

Kiểm tra server đang chạy.

```bash
curl http://url/health
# {"status":"ok"}
```

### `POST /generate-config`

Tạo config trực tiếp không qua clarify loop (dùng cho automation/testing).

```bash
curl -X POST http://url/generate-config \
  -H "Content-Type: application/json" \
  -d '{"input": "app 1020, payment, reject nếu amount > 5tr và chưa ekyc"}'
```

---

## Docker

```bash
docker build -t config-agent .
docker run -p 8000:8000 \
  -e LLM_API_KEY=your_key \
  -e LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1 \
  config-agent
```

---

## Chạy tests

```bash
pytest tests/ -v
```
