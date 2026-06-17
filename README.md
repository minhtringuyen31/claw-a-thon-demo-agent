# AgentR — Risk & Fraud Agent System

AgentR là một hệ thống agent AI phục vụ nội bộ phòng ban **Risk ** của **ZaloPay**: tự động **phát hiện xu hướng gian lận (fraud)** từ report của các stakeholders, **điều tra** trên data warehouse giao dịch ZaloPay để tìm ra pattern có precision/recall đủ tốt, rồi **biến pattern đó thành rule config** triển khai được trên hệ thống rule-engine của **Risk Platform** — với human (strategist) xác nhận trước khi action.

Hệ thống gồm **hai agent LangGraph** nối thành một pipeline, dùng chung một MySQL warehouse `risk_db`:

```
   Email Report / Post-mortem update event
              │
              ▼
   ┌─────────────────────────┐        RuleJSON / final_pattern        ┌──────────────────────────┐
   │  fraud-analysis-agent    │  ──────────  (qua run_id)  ──────────▶ │  config-agent            │
   │  (Risk Analysis Agent)   │                                        │  (Config Agent)            │
   │  phát hiện + điều tra     │                                        │  sinh rule config + ghi DB │
   └─────────────────────────┘                                        └──────────────────────────┘
              │                                                                     │
              ▼                                                                     ▼
   MySQL risk_db (trans_log, pom_acr,                                   MySQL risk_db.rule_config
   user_profile, user_journey, ...)                                         (rule đã duyệt, active)
```

- **Agent 1 — `fraud-analysis-agent`** điều tra dữ liệu, đề xuất pattern (SQL predicate + metrics + action).
- **Agent 2 — `config-agent`** nhận pattern đó (hoặc mô tả chat của strategist), sinh ra `FraudConfig` JSON và ghi vào `risk_db.rule_config` sau khi người duyệt.

> ⚠️ **Lưu ý về thiết kế:** Code hiện tại đã **khác đáng kể** so với các tài liệu thiết kế ban đầu trong `docs/`. README này mô tả **trạng thái implementation thực tế**. Các điểm divergence chính được liệt kê ở [§7](#7-divergence-so-với-tài-liệu-thiết-kế-ban-đầu).

---

## Mục lục

1. [Thành phần dự án](#1-thành-phần-dự-án)
2. [Agent 1 — fraud-analysis-agent](#2-agent-1--fraud-analysis-agent-risk-analysis-agent)
3. [Agent 2 — fraud-config-agent-v2](#3-agent-2--fraud-config-agent-v2-config-agent)
4. [Tầng dữ liệu dùng chung](#4-tầng-dữ-liệu-dùng-chung-mysql-risk_db)
5. [Chạy thử nhanh](#5-chạy-thử-nhanh)
6. [Biến môi trường](#6-biến-môi-trường)
7. [Divergence so với tài liệu thiết kế ban đầu](#7-divergence-so-với-tài-liệu-thiết-kế-ban-đầu)
8. [Triển khai](#8-triển-khai)
9. [Cấu trúc repo](#9-cấu-trúc-repo)

---

## 1. Thành phần dự án

| Thư mục | Vai trò | Trạng thái |
|---|---|---|
| **`fraud-analysis-agent/`** | **Risk Analysis Agent** — phát hiện anomaly + điều tra ReAct + sinh RuleJSON. FastAPI, port `8080` (map `8081` ngoài). | ✅ Active |
| **`fraud-config-agent-v2/`** | **Config Agent (v2)** — sinh `FraudConfig` rule và ghi MySQL sau human review. FastAPI, port `8080` (map `8081`). | ✅ Active |
| `risk-portal-ui/` | Frontend React + Vite (template Metronic 9) cho Risk Portal, gọi `fraud-analysis-agent`. Port `3000`. | ✅ Active |
| `config-agent/` | Phiên bản **V1** của Config Agent (có `rule.json`). Bị thay thế bởi `fraud-config-agent-v2`. | 🗄️ Legacy |
| `agent/` + `ui/` | Scaffold demo gốc (một "Mock Interviewer" Streamlit) từ lúc khởi tạo project trên AgentBase. Không thuộc nghiệp vụ risk. | 🗄️ Legacy/demo |
| `docs/` | Tài liệu thiết kế gốc (AgentR Overview/System Design PDF, knowledge base fraud, workflow, diagram). | 📚 Reference |
| `docker-compose.yml` | Orchestrate cả 4 service (agent demo, fraud-analysis-agent, ui, risk-portal-ui). | — |

> `docker-compose.yml` ở root vẫn build service `agent` (demo interviewer) và `ui` cũ. Pipeline risk thực tế là **`fraud-analysis-agent` + `fraud-config-agent-v2` + `risk-portal-ui`**.

---

## 2. Agent 1 — `fraud-analysis-agent` (Risk Analysis Agent)

Một agent LangGraph phát hiện làn sóng gian lận mới nổi từ report, điều tra trên warehouse bằng vòng lặp **ReAct**, và phát ra một **RuleJSON** (gợi ý policy) kèm toàn bộ trace điều tra để audit.

### Workflow (StateGraph)

```
START → ingest → anomaly_check ──(normal)──▶ action_output → END
                       │
                  (anomalous)
                       ▼
                  fetch_data → investigation_init → plan ⇄ act ⇄ observe
                                                        │           │
                                                        └──── router ┘
                                       (continue / converged / max_iter / no_pattern)
                                                        │
                                                        ▼
                                          finalize_investigation → policy_output → END
```

**Các node** (`app/nodes/`):

- **`ingest`** — parse email / post-mortem JSON thành `FraudContext` (reported_cases, severity, time_hint). _LLM role `ingest`._
- **`anomaly_check`** — query nhiều cửa sổ thời gian (week/month/rolling) theo các chiều `appID, integratedChannel, bankType, bankCode, is_kyc`, áp các trigger rule (amount/count/concentration) định nghĩa trong `anomaly_check/strategy.md`. Trả `AnomalyDecision` và route. _LLM role `anomaly`._ (`baseline.py`)
- **`action_output`** — nếu không anomaly: phát `NoActionReport` rồi kết thúc.
- **Vòng điều tra ReAct** (`investigation/`):
  - **`init_node`** — nạp `kb.md` (catalog metric, threshold, rule template) và `skill.md` (chiến lược thinking + escalation), khởi tạo bộ đếm.
  - **`plan`** — LLM reasoning chọn tool kế tiếp + hypothesis đang test. _LLM role `plan`._
  - **`act`** — chạy tool từ registry: `query_with_filters`, `aggregate`, `compute_metrics`, `raw_sql` (`tools.py`). SQL bị chặn write qua `sql_safety.py`.
  - **`observe`** — LLM phân tích kết quả, ghi `PatternAttempt` với metrics; status được **tính lại bằng code** (`metrics.py`) chứ không tin status do LLM tự khai. _LLM role `observe`._
  - **`router`** — guard vòng lặp: `converged` khi precision rất cao hoặc đã escalate qua ≥2 nguồn dữ liệu; ngược lại `continue` / `max_iter` / `no_pattern`.
- **`finalize_investigation`** — chọn pattern F1 tốt nhất trong các pattern `passed`, dựng `InvestigationReport`.
- **`policy_output`** — dựng `RuleJSON` (`contracts/rulejson.py`) + `pretty_report` markdown (`shared/pretty_report.py`).

State đầy đủ ở `app/state.py` (`AgentState` TypedDict + các Pydantic model: `FraudContext`, `AnomalyDecision`, `PatternAttempt`, `InvestigationStep`, `InvestigationReport`).

### API (`app/service.py`)

| Method | Endpoint | Ghi chú |
|---|---|---|
| POST | `/runs` | Tạo run (async, background task), trả `run_id`. |
| GET | `/runs/{run_id}` | Poll trạng thái + snapshot report. |
| GET | `/runs/{run_id}/stream` | SSE stream các bước điều tra (replay + live). |
| DELETE | `/runs/{run_id}` | Hủy run. |
| GET | `/runs` | List run_id (backend sqlite). |
| POST | `/triggers/email` | Webhook email → normalize → `/runs`. |
| POST | `/triggers/postmortem` | Webhook post-mortem → `/runs`. |
| GET | `/health` | Health probe. |

### Đặc điểm kỹ thuật

- **Tech:** Python ≥3.13, LangGraph, FastAPI/Uvicorn, Pydantic v2, OpenAI-compatible client, SQLAlchemy + PyMySQL, Pandas. Review UI bằng Streamlit (`review_ui.py`, read-only).
- **Checkpointer:** LangGraph SQLite (`checkpoints.db`) mặc định; chọn được `memory` / `postgres` qua env.
- **Warehouse:** MySQL `risk_db` (qua `shared/warehouse.py`); có mock DuckDB/parquet trong `app/data/` cho dev.
- **LLM:** OpenAI-compatible (VNG MAAS / GreenNode AIP…), routing theo role qua `LLM_MODEL_<ROLE>` với fallback `LLM_MODEL`; có `MockLLM` khi `USE_REAL_LLM` chưa bật.
- **Tests:** `tests/test_service.py` (E2E qua TestClient, mock), `scripts/e2e_test.py`, `scripts/test_scenarios.py`.

---

## 3. Agent 2 — `fraud-config-agent-v2` (Config Agent)

Agent chat reasoning biến một fraud signal thành **rule config triển khai được** (`FraudConfig` JSON), ghi vào MySQL `risk_db.rule_config` sau khi người xác nhận. Hai đường vào:

1. **Manual chat** — strategist mô tả pattern bằng ngôn ngữ tự nhiên (hỗ trợ tiếng Việt).
2. **From report** — kéo một run đã hoàn tất của `fraud-analysis-agent` theo `run_id`, đọc `final_pattern` (SQL predicate, signal columns, recommended action) + `recommendation` và **tự reason ra config** (cố ý **không** dùng thẳng `rule_json` của agent kia).

### Workflow (StateGraph + interrupt)

```
START → intake → clarify ──clarify──▶ END (hỏi lại; resume ở /chat kế tiếp)
                        └─proceed─▶ dependency_resolver → build_config → validator
validator ──done──▶ human_review  [INTERRUPT]  ──approve──▶ update_conf (ghi MySQL) → END
                                                └─reject──▶ END (không ghi)
```

**Các node** (`agent/nodes.py`):

- **`intake`** (LLM reasoning) — normalize chat text hoặc report đã serialize thành `requirement`; dịch SQL predicate thành mảng `conditions`.
- **`clarify`** (LLM) — hỏi tối đa 1 câu khi thiếu field bắt buộc (`app_id`/`event_name`, `action`, ≥1 condition); history lưu theo session (sửa lỗi multi-turn của V1).
- **`dependency_resolver`** (tool) — dedup mức rule: rule đã tồn tại trong event nào chưa → `create` vs `update`.
- **`build_config`** (LLM reasoning) — phát `FraudConfig` events JSON; khi update thì merge vào event hiện có; nhận lỗi validate trước đó để retry hội tụ.
- **`validator`** (tool) — **hiện forced-pass** (luôn cho qua review); logic validate + vòng retry đã nối nhưng đang dormant.
- **`human_review`** — interrupt; strategist approve/reject.
- **`update_conf`** (tool) — khi approve: ghi MySQL `rule_config` (atomic theo event) + lưu file plan `output/` + breadcrumb session.

State ở `agent/state.py` (`ConfigAgentState`). Schema output ở `agent/schema.py`.

### Output: `FraudConfig` JSON

```
FraudConfig → events[]
  Event   → name, description, filter("AND"/"OR"), actionCode, decisionCode, variables[], rules[]
  Rule    → name, description, conditions[], infoCode
  Condition → field, operator, value
  Variable  → fieldName, fieldType("LONG"/"DOUBLE"/"STRING"), source:{keyId}
```

Operator: `GREATER_THAN(_OR_EQUAL)`, `LESS_THAN(_OR_EQUAL)`, `EQUALS`, `NOT_EQUALS`, `CONTAINS`. Field gồm velocity (`count_txn_Xh`, `sum_amount_Xd`…), derived (`account_age` tính bằng giây), static (`ekyc`, `bankCode`, `amount`, `bankType`…). Ví dụ thực tế trong `output/*.json`.

### Services (`services/`)

- **`fraud_report_client.py`** — GET `{FRAUD_AGENT_URL}/runs/{run_id}`, trích `final_pattern` + `recommendation` (có `MockReportClient` cho test).
- **`config_store.py`** — `MySQLConfigStore` (ghi `risk_db.rule_config`) hoặc `MockConfigStore` (in-memory cho CI/demo).
- **`memory_service.py`** — `FileMemoryService` lưu session/clarify/conversation history dưới `sessions/`.

### API (`api/main.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | Đường manual; trả `clarify` hoặc `awaiting_review`. |
| POST | `/runs/from-report` | Kéo report theo `run_id`, build config. |
| GET | `/runs/{id}` | Poll trạng thái + config plan. |
| POST | `/runs/{id}/review` | `{decision: approve\|reject}` — resume qua interrupt. |
| GET | `/runs`, `/rules`, `/configs`, `/sessions`, `/health` | Listings / rule đã deploy / health. |
| GET | `/` | Chat UI tĩnh (`static/index.html`, tiếng Việt). |

### Đặc điểm kỹ thuật

- **Tech:** Python 3.11, LangGraph (+ SqliteSaver), FastAPI/Uvicorn, Pydantic v2, OpenAI SDK, SQLAlchemy + PyMySQL, httpx.
- **CLI:** `cli.py` chạy nhanh local (tự auto-approve để xem hết luồng), dùng MemorySaver.
- **LLM:** OpenAI-compatible VNG MAAS; mặc định `minimax/minimax-m2.5`, role `clarify` dùng `google/gemma-4-31b-it`; có `MockLLM`.
- **Tests:** `tests/` (test_nodes, test_units, test_api, test_graph) — chạy hoàn toàn bằng mock.

---

## 4. Tầng dữ liệu dùng chung (MySQL `risk_db`)

Cả hai agent dùng chung một MySQL warehouse (trong `docker-compose.yml` trỏ tới host GreenNode self-hosted):

| Bảng | Vai trò |
|---|---|
| `trans_log` | Toàn bộ giao dịch (transID, appID, userID, reqDate, userChargeAmount, integratedChannel, bankType, bankCode, is_kyc, …). |
| `pom_acr` | Subset fraud đã xác nhận (cột trans_log + `fraud_type`, `report_date`, `is_loss`). |
| `user_profile` | Identity/KYC/trust (account age, ekyc/nfc status, cccd, linked bank/card, trust flags). |
| `user_journey` | Sự kiện trước giao dịch (register, login_new_device, change_phone, reset_pin, map_bank, eKYC, change_device…). |
| `rule_config` | **Output** của Config Agent: rule đã duyệt (event_name, config_json, status, source_run_id, created_by, created_at). |

`fraud-analysis-agent` **đọc** 4 bảng đầu để điều tra; `fraud-config-agent-v2` **ghi** vào `rule_config`. Tham khảo knowledge base nghiệp vụ ở `docs/Fraud_Analysis_Knowledge.md` (trigger rule A/B/C, metric theo nguồn, ngưỡng candidate rule, tiêu chí accept theo action MONITOR/CHALLENGE/REJECT/BLACKLIST).

---

## 5. Chạy thử nhanh

### fraud-analysis-agent (mock, không cần API key)

```bash
cd fraud-analysis-agent
uv sync --extra test
uv run python -m app.data.mock_data           # sinh data warehouse mock
uv run python -m app.main                      # demo CLI end-to-end
uv run uvicorn app.service:app --reload        # API tại http://localhost:8000/docs
uv run pytest -v                               # E2E tests
# Review UI:
AGENT_URL=http://localhost:8000 uv run streamlit run review_ui.py
```

### fraud-config-agent-v2 (mock: MockLLM + MockConfigStore)

```bash
cd fraud-config-agent-v2
pip install -r requirements.txt
PYTHONPATH=. uvicorn api.main:app --host 0.0.0.0 --port 8081   # để trống USE_REAL_LLM & MYSQL_HOST
PYTHONPATH=. pytest

# CLI nhanh:
PYTHONPATH=. python cli.py "appid 123, reject nếu tổng tiền 24h > 10 triệu và account mới hơn 7 ngày"
```

### Toàn bộ pipeline qua Docker Compose

```bash
cp .env.example .env   # điền LLM_* và MYSQL_*
docker-compose up --build
# fraud-analysis-agent → :8081, risk-portal-ui → :3000
```

---

## 6. Biến môi trường

Dùng chung (`.env.example` ở root):

| Biến | Mục đích |
|---|---|
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Endpoint OpenAI-compatible + model mặc định. |
| `LLM_MODEL_<ROLE>` | Override model theo role: `INGEST`, `ANOMALY`, `PLAN`, `OBSERVE` (analysis); `INTAKE`, `CLARIFY`, `BUILD` (config). |
| `USE_REAL_LLM` | `1` → dùng LLM thật; bỏ trống → `MockLLM`. |
| `MYSQL_HOST`/`PORT`/`DB`/`USER`/`PASSWORD` | Warehouse MySQL (`risk_db`). Bỏ trống `MYSQL_HOST` ở config-agent → `MockConfigStore`. |
| `CHECKPOINTER_BACKEND`, `SQLITE_CHECKPOINT_PATH`, `POSTGRES_URL` | Backend checkpoint (analysis agent). |
| `FRAUD_AGENT_URL` | (config-agent) base URL của fraud-analysis-agent để pull report. |
| `AGENT_ENDPOINT_URL`, `VITE_AGENT_URL`, `VITE_SERVER_URL` | UI trỏ tới agent. |

---

## 7. Divergence so với tài liệu thiết kế ban đầu

Tài liệu trong `docs/` (AgentR Overview/System Design, `AGENT_WORKFLOW.md`, diagram) mô tả thiết kế gốc; implementation đã thay đổi:

- **Vòng điều tra → ReAct.** Docs/README cũ nói tới các node rời rạc `hypothesis_node` / `sql_gen_node` / `metrics` / `human_review`. Thực tế gộp thành **vòng ReAct `plan → act → observe → router`** dưới `app/nodes/investigation/`, với 4 tool (`query_with_filters`, `aggregate`, `compute_metrics`, `raw_sql`) thay cho `sql_gen` riêng.
- **Human review chuyển sang Config Agent.** `fraud-analysis-agent` chạy autonomous tới khi phát RuleJSON (không dừng chờ duyệt; `review_ui.py` chỉ read-only). **Cổng human-in-the-loop thực sự nằm ở `fraud-config-agent-v2`** (interrupt trước `human_review`, approve/reject qua `/runs/{id}/review`).
- **Config Agent đã vượt qua giai đoạn "chỉ đọc".** `IMPLEMENTATION_PLAN.md` (Giai đoạn 2) chủ trương DỪNG ở việc xuất config plan, **chưa** làm `update_conf`. Thực tế `fraud-config-agent-v2` **đã có write-path**: `update_conf` ghi thẳng MySQL `rule_config` sau khi approve.
- **`validator` đang dormant.** Node validate + vòng retry đã nối nhưng hiện **forced-pass** (luôn qua review).
- **Config Agent reason lại config, không passthrough RuleJSON.** Thay vì tiêu thụ trực tiếp `rule_json` của analysis agent, V2 chỉ lấy `final_pattern` + `recommendation` rồi tự sinh `FraudConfig`.
- **Đã có 2 thế hệ Config Agent.** `config-agent/` (V1) bị thay bằng `fraud-config-agent-v2/` (sửa loop clarify multi-turn, đổi sang schema `FraudConfig` events).
- **Warehouse mặc định.** Docs nhắc DuckDB cho dev; cấu hình deploy hiện trỏ **MySQL `risk_db`** (DuckDB/parquet chỉ còn là mock layer).

Khi đọc `docs/`, hãy coi đó là **ý đồ thiết kế**, còn nguồn chân lý về hành vi là code trong `fraud-analysis-agent/` và `fraud-config-agent-v2/`.

---

## 8. Triển khai

- **GreenNode AgentBase / VNG Cloud AI Platform.** Project khởi tạo trên AgentBase (`.greennode.json`, thư mục `.agentbase/`); endpoint runtime dạng `*.agentbase-runtime.aiplatform.vngcloud.vn`. LLM phục vụ qua VNG MAAS (`maas-llm-aiplatform-hcm.api.vngcloud.vn/v1`).
- **Docker.** Mỗi agent có `Dockerfile` riêng (expose `8080`). `docker-compose.yml` ở root build cả pipeline. Image dùng `uv` (analysis agent, Python 3.13) hoặc `pip` (config agent, Python 3.11).

---

## 9. Cấu trúc repo

```
.
├── fraud-analysis-agent/      # Agent 1: Risk Analysis Agent (LangGraph + ReAct + FastAPI)
│   ├── app/
│   │   ├── nodes/             # ingest, anomaly_check, fetch_data, investigation/*, action_output, policy_output
│   │   ├── contracts/         # rulejson.py (contract handoff sang Config Agent)
│   │   ├── shared/            # warehouse, historical, sql_safety, pretty_report, time_window
│   │   ├── llm/, data/        # LLM client (real+mock); mock warehouse DuckDB/parquet
│   │   ├── graph/             # StateGraph + checkpointer factory
│   │   ├── state.py, service.py, main.py
│   ├── review_ui.py, scripts/, tests/, Dockerfile, docker-compose.yml
├── fraud-config-agent-v2/     # Agent 2: Config Agent (LangGraph + interrupt + FastAPI)
│   ├── agent/                 # graph.py, nodes.py, state.py, schema.py, prompts.py
│   ├── services/              # fraud_report_client, config_store, memory_service
│   ├── llm/, api/, static/    # LLM client; FastAPI; chat UI tĩnh
│   ├── output/, sessions/     # rule plan đã sinh; session memory
│   ├── cli.py, tests/, Dockerfile
├── risk-portal-ui/            # Frontend React + Vite (Metronic 9)
├── config-agent/              # Config Agent V1 (legacy)
├── agent/ + ui/               # Scaffold demo gốc (Mock Interviewer) — legacy
├── docs/                      # Tài liệu thiết kế gốc + knowledge base fraud + diagrams
├── docker-compose.yml
├── IMPLEMENTATION_PLAN.md     # Kế hoạch 4 giai đoạn (lưu ý đã vượt qua một số mốc)
└── README.md
```