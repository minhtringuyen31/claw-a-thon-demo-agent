# Risk Analysis Agent

LangGraph agent for fraud-pattern discovery.

Flow: trigger (email / post-mortem) → ingest → fetch warehouse schema →
iterate hypothesis → SQL → metrics until precision/recall thresholds hit
or max iterations exceeded → pause for strategist review → emit RuleJSON.

## Layout

```
app/
  state.py             AgentState + Pydantic payloads
  contracts/           RuleJSON contract (interface with Config Agent)
  data/                Local DuckDB mock warehouse (dev only)
  llm/                 MockLLM + OpenAI-compat client, get_llm() factory
  tools/               warehouse_query, compute_metrics, validate_sql, notify
  nodes/               ingest, fetch_data, hypothesis, sql_gen, metrics,
                       router, human_review, policy_output
  graph/               StateGraph + checkpointer factory
  service.py           FastAPI service
  main.py              CLI entry point
tests/
  test_service.py      E2E via FastAPI TestClient
review_ui.py           Streamlit review console
```

## Quick start (mock, no API key)

```bash
uv sync --extra test
uv run python -m app.data.mock_data    # generate transactions.parquet
uv run python -m app.main              # full CLI demo
uv run pytest -v                       # E2E tests
```

## API service

```bash
uv run uvicorn app.service:app --reload
# docs: http://localhost:8000/docs
```

| Method | Endpoint | Notes |
|--------|----------|-------|
| POST | `/runs` | Create run, returns `run_id`, status=`running` |
| GET  | `/runs/{run_id}` | Status + report snapshot |
| POST | `/runs/{run_id}/review` | `{decision: approve\|reject, reviewer}` |
| GET  | `/runs` | List run_ids (sqlite backend only) |
| POST | `/triggers/email` | `{subject, sender, body}` → normalize → /runs |
| POST | `/triggers/postmortem` | `{incident_id, summary, record}` → /runs |
| GET  | `/health` | health probe |

## Review UI

```bash
AGENT_URL=http://localhost:8000 uv run streamlit run review_ui.py
```

Lists runs, shows pattern + metrics + SQL, approve/reject buttons.
Completed runs surface the RuleJSON payload.

## Configuration (env)

| Var | Default | Purpose |
|-----|---------|---------|
| `USE_REAL_LLM` | unset | `1` → use OpenAI-compat client; else MockLLM |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | — | OpenAI-compat creds (GreenNode AIP, OpenAI, ...) |
| `WAREHOUSE_BACKEND` | `duckdb` | `duckdb` (dev) / `warehouse` (prod stub — implement in `app/tools`) |
| `GROUND_TRUTH_SOURCE` | `column` | `column` reads `is_fraud`; `postmortem` reads `GROUND_TRUTH_TABLE` |
| `GROUND_TRUTH_TABLE` | `confirmed_fraud` | Used when `GROUND_TRUTH_SOURCE=postmortem` |
| `CHECKPOINTER_BACKEND` | `sqlite` | `memory` / `sqlite` / `postgres` |
| `SQLITE_CHECKPOINT_PATH` | `checkpoints.db` | Path for sqlite checkpointer |
| `POSTGRES_URL` | — | Required when `CHECKPOINTER_BACKEND=postgres` |

For postgres: `uv sync --extra postgres`.

## Production swap-points

Each is an independent swap; signatures stay stable.

1. **LLM** — set `USE_REAL_LLM=1` + `LLM_*`. `hypothesis_node` already
   passes `thinking=True` (no-op on OpenAI-compat today; place to route
   to an extended-thinking model when available).
2. **Warehouse** — set `WAREHOUSE_BACKEND=warehouse` and implement the
   `warehouse_query` branch in `app/tools/__init__.py` to point at
   BigQuery / Spark / Trino.
3. **Ground truth** — `GROUND_TRUTH_SOURCE=postmortem` + a confirmed-fraud
   table makes `compute_metrics` join with the post-mortem store instead
   of the `is_fraud` column.
4. **Checkpointer** — `CHECKPOINTER_BACKEND=postgres` + `POSTGRES_URL`.
5. **Triggers** — point your IMAP listener at `/triggers/email`, your
   post-mortem DB CDC at `/triggers/postmortem`. Both normalize to
   `raw_input` and start a run.
6. **Notify** — `tools.notify_strategist` prints to stdout. Wire Slack /
   email here.
7. **SQL safety** — `tools.validate_sql` blocks writes. Production should
   add EXPLAIN cost check, row limit, query timeout.

## Router best-so-far

`router_node` tracks the highest-F1 pattern across all iterations. On
escalate, the report carries the best candidate (not the last one). On
pass, the current iteration is used since it is the one that met the
strategist's declared thresholds.
