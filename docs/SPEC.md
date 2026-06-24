# SPEC: AgentR MCP Server — Centralized Tool Management

## 1. Objective

Migrate all tool implementations out of both LangGraph agents into a **centralized MCP server**. Both agents become **MCP clients** — they keep their LangGraph graphs and LLM reasoning, but fetch and invoke tools via the MCP protocol instead of defining them locally.

**Target users:**
- fraud-analysis-agent (MCP client) — calls investigation/data tools
- fraud-config-agent-v2 (MCP client) — calls config store and session tools
- (Future) Any new agent that needs access to the same tool set

**Goals:**
- Single source of truth for all tool implementations
- Shared tools (MySQL queries, schema) defined once, reused by both agents
- Tool changes/fixes applied in one place, reflected in all agents immediately

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    mcp-server  :8000                         │
│              (fastmcp, HTTP/SSE transport)                   │
│                                                              │
│  Shared tools:          Fraud-analysis tools:                │
│  • query_with_filters   • compute_metrics                    │
│  • aggregate            • fetch_all_windows                  │
│  • raw_sql              • notify_strategist                  │
│  • get_schema           • get_schema                         │
│                                                              │
│  Config-agent tools:                                         │
│  • get_config           • fetch_fraud_report                 │
│  • save_config          • get_session / save_session         │
│  • list_configs                                              │
│                                                              │
│  External systems owned here:                                │
│  MySQL risk_db │ Local FS (sessions/) │ HTTP (fraud-agent)   │
└──────────┬──────────────────────────┬───────────────────────┘
           │ MCP / HTTP-SSE           │ MCP / HTTP-SSE
           │ langchain-mcp-adapters   │ langchain-mcp-adapters
           ▼                          ▼
┌──────────────────┐      ┌──────────────────────────┐
│ fraud-analysis-  │      │  fraud-config-agent-v2   │
│ agent            │      │                          │
│                  │      │                          │
│ LangGraph graph  │      │  LangGraph graph         │
│ LLM reasoning    │      │  LLM reasoning           │
│ (tools from MCP) │      │  (tools from MCP)        │
└──────────────────┘      └──────────────────────────┘
```

**Key principle:** Agents keep their LangGraph structure, state machines, and LLM calls. Only the tool *implementations* move to MCP. The LLM reasoning (calling LLM to decide which tool to use) stays in each agent.

---

## 3. Tool Inventory

### 3.1 Shared Tools (both agents may call)

| MCP Tool Name | Current location | What it does | External system |
|---|---|---|---|
| `query_with_filters` | fraud-analysis-agent/app/nodes/investigation/tools.py | Filter rows in warehouse tables with exact-match conditions + time windows | MySQL `risk_db` |
| `aggregate` | same file | Group by dimensions, count + sum amount | MySQL `risk_db` |
| `raw_sql` | same file | Execute validated read-only SELECT | MySQL `risk_db` |
| `get_schema` | fraud-analysis-agent/app/shared/schema.py | Return column metadata for a table | MySQL information_schema |

### 3.2 Fraud-Analysis-Agent Tools

| MCP Tool Name | Current location | What it does | External system |
|---|---|---|---|
| `compute_metrics` | app/nodes/investigation/tools.py + metrics.py | Score a rule predicate: precision/recall/F1 vs ground truth (pom_acr) | MySQL `risk_db` |
| `fetch_all_windows` | app/nodes/anomaly_check/baseline.py | Query pom_acr for 9 time-window baselines (anomaly detection) | MySQL `risk_db` |
| `notify_strategist` | app/shared/notify.py | Send pattern-ready alert to fraud strategist | stdout / Slack / email |

### 3.3 Config-Agent Tools

| MCP Tool Name | Current location | What it does | External system |
|---|---|---|---|
| `get_config` | services/config_store.py | Read latest rule config for an event_name | MySQL `rule_config` table |
| `save_config` | services/config_store.py | Write/update rule config for an event_name | MySQL `rule_config` table |
| `list_configs` | services/config_store.py | List all rule configs (with limit) | MySQL `rule_config` table |
| `fetch_fraud_report` | services/fraud_report_client.py | Fetch completed fraud-analysis run by run_id | HTTP → fraud-analysis-agent |
| `get_session` | services/memory_service.py | Load session state from file | Local FS `sessions/` |
| `save_session` | services/memory_service.py | Persist session state to file | Local FS `sessions/` |

---

## 4. Project Structure

```
AgentR/
├── mcp-server/                         # NEW — MCP server service
│   ├── pyproject.toml                  # deps: fastmcp, sqlalchemy, pymysql, httpx, pydantic, python-dotenv
│   ├── .env.example
│   ├── main.py                         # FastMCP app entry point, registers all tools
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── shared.py                   # query_with_filters, aggregate, raw_sql, get_schema
│   │   ├── investigation.py            # compute_metrics, fetch_all_windows, notify_strategist
│   │   └── config.py                   # get_config, save_config, list_configs, fetch_fraud_report, get/save_session
│   ├── db/
│   │   ├── __init__.py
│   │   └── warehouse.py                # Shared SQLAlchemy engine (moved from agents)
│   └── tests/
│       ├── conftest.py
│       ├── test_shared_tools.py
│       ├── test_investigation_tools.py
│       └── test_config_tools.py
│
├── fraud-analysis-agent/
│   ├── app/
│   │   ├── nodes/
│   │   │   └── investigation/
│   │   │       └── tools.py            # REMOVE local tool defs → replaced by MCP client tools
│   │   ├── shared/
│   │   │   ├── warehouse.py            # REMOVE (moved to mcp-server/db/warehouse.py)
│   │   │   ├── historical.py           # REMOVE or keep as thin wrapper
│   │   │   └── schema.py              # REMOVE (moved to mcp-server)
│   │   └── graph/
│   │       └── builder.py             # CHANGE: load tools from MCP client instead of local registry
│
├── fraud-config-agent-v2/
│   ├── agent/
│   │   └── graph.py                   # CHANGE: load tools from MCP client
│   └── services/                      # REMOVE: config_store.py, memory_service.py, fraud_report_client.py
│                                      #         (implementations move to mcp-server/tools/config.py)
│
├── docker-compose.yml                 # Add mcp-server service
└── SPEC.md
```

---

## 5. Agent Migration Pattern

Both agents adopt `langchain-mcp-adapters` to load tools from MCP at graph startup.

### Before (local tools)
```python
# fraud-analysis-agent/app/graph/builder.py
from app.nodes.investigation.tools import query_with_filters, aggregate, raw_sql, compute_metrics
tools = [query_with_filters, aggregate, raw_sql, compute_metrics]
llm_with_tools = llm.bind_tools(tools)
```

### After (MCP client)
```python
# fraud-analysis-agent/app/graph/builder.py
from langchain_mcp_adapters.client import MultiServerMCPClient

async def get_tools():
    client = MultiServerMCPClient({
        "agentr": {
            "url": os.environ["MCP_SERVER_URL"],  # http://mcp-server:8000/sse
            "transport": "sse",
        }
    })
    return await client.get_tools()

tools = asyncio.run(get_tools())
llm_with_tools = llm.bind_tools(tools)
```

Config agent follows the same pattern, loading its own subset of tools.

---

## 6. Environment Variables

### mcp-server/.env
```
# Database
MYSQL_HOST=
MYSQL_PORT=3306
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DB=risk_db

# Sessions (config agent memory)
SESSIONS_DIR=/app/sessions

# Downstream (for fetch_fraud_report tool)
FRAUD_AGENT_URL=http://fraud-analysis-agent:8080

# Server
MCP_SERVER_PORT=8000
```

### Agents (add one new var each)
```
MCP_SERVER_URL=http://mcp-server:8000/sse
```

All existing agent env vars related to MySQL and sessions are **removed** from agents (owned by mcp-server now).

---

## 7. Code Style

- Python ≥ 3.13, `fastmcp`, `sqlalchemy`, `pymysql`, `httpx` (async), `pydantic`.
- Each tool is an `async def` decorated with `@mcp.tool()`.
- Tool docstrings = MCP tool description shown to the LLM — keep concise and action-oriented.
- Input models use Pydantic `BaseModel`; no raw `dict` params in tool signatures.
- One shared SQLAlchemy engine (created once at startup via `lifespan`).
- One `httpx.AsyncClient` for outbound HTTP calls, also created at startup.
- SQL safety validation (`compute_metrics`, `raw_sql`) stays in the tool implementation.
- No business logic beyond what the tool currently does — 1:1 migration of existing logic.

---

## 8. Testing Strategy

- **Unit tests** (`pytest` + `pytest-asyncio`): mock SQLAlchemy and httpx with `respx` + SQLAlchemy in-memory SQLite; test each tool function in isolation.
- **Integration smoke test**: `docker-compose up`, call each tool via a minimal MCP client script, assert expected response shapes.
- Agents' existing tests: update to mock the MCP client response instead of the tool function directly.
- Migration is done incrementally — one tool group at a time (shared → investigation → config), with agent smoke tests passing after each group.

---

## 9. docker-compose Addition

```yaml
mcp-server:
  build: ./mcp-server
  ports:
    - "8000:8000"
  environment:
    MYSQL_HOST: ${MYSQL_HOST}
    MYSQL_PORT: ${MYSQL_PORT}
    MYSQL_USER: ${MYSQL_USER}
    MYSQL_PASSWORD: ${MYSQL_PASSWORD}
    MYSQL_DB: ${MYSQL_DB}
    FRAUD_AGENT_URL: http://fraud-analysis-agent:8080
    SESSIONS_DIR: /app/sessions
  volumes:
    - sessions_data:/app/sessions
  depends_on:
    - db

volumes:
  sessions_data:
```

---

## 10. Migration Order (incremental)

1. **Bootstrap** `mcp-server/` with fastmcp, health check, empty tool list.
2. **Shared tools** (`query_with_filters`, `aggregate`, `raw_sql`, `get_schema`) — migrate + update fraud-analysis-agent to use MCP client.
3. **Investigation tools** (`compute_metrics`, `fetch_all_windows`, `notify_strategist`) — migrate + verify fraud-analysis-agent end-to-end.
4. **Config tools** (`get_config`, `save_config`, `list_configs`, `fetch_fraud_report`, `get/save_session`) — migrate + update fraud-config-agent-v2.
5. **Cleanup**: remove now-dead source files from both agents.

---

## 11. Boundaries

### Always do
- Validate all tool inputs with Pydantic before touching any external system.
- Keep SQL safety checks (`raw_sql`, `compute_metrics`) identical to current implementation.
- Return structured errors — no raw exceptions propagate to MCP clients.

### Ask the user first
- Adding new tools not in the current inventory.
- Changing transport from HTTP/SSE to stdio.
- Adding authentication on the MCP server.
- Moving LLM calls (the agent's reasoning engine) into MCP — that is explicitly out of scope.

### Never do
- Move LangGraph graph logic, state machines, or LLM reasoning into the MCP server.
- Let the MCP server hold per-run state — it is stateless except for session files and DB.
- Break existing REST API contracts of either agent.
