# fraud-config-agent-v2

Reasoning chat-agent that turns a fraud signal into a deployable rule config, then writes it to
the hosted MySQL `risk_db` after a human confirm. Two input paths:

1. **Manual chat** — a strategist describes a fraud pattern in natural language.
2. **From report** — pull a completed `fraud-analysis-agent` run by `run_id` and reason over its
   `final_pattern` (SQL predicate, signal columns, recommended action) + `recommendation`.
   It deliberately does **not** pass through that agent's `rule_json`.

## Topology

```
START → intake → clarify ─clarify→ END (ask follow-up; resume next /chat)
                         └proceed→ dependency_resolver → build_config → validator
validator ─done→ human_review  [INTERRUPT]  ─approve→ update_conf (write MySQL) → END
                                            └reject→ END (no write)
```

- **intake** (LLM, reasoning): normalize chat text OR a serialized report into a structured
  requirement. Translates a SQL predicate into `conditions`.
- **clarify** (LLM): ask at most one question when a mandatory field is missing; history is
  persisted per session (fixes config-agent's broken multi-turn loop).
- **dependency_resolver** (tool): rule-level dedup — does the intended rule already exist, and in
  which event? → `create` vs `update`.
- **build_config** (LLM, reasoning): emit `FraudConfig` events JSON; merges into the existing
  event on update; receives prior validation errors for convergent retries.
- **validator** (tool): runs/tests the config. **Currently forced-pass** (always advances to
  review); real validation + the retry loop are wired but dormant.
- **human_review** (interrupt): strategist approves/rejects.
- **update_conf** (tool): on approve, writes to MySQL `rule_config` (atomic) + saves a plan file.

## Output schema

`FraudConfig` (events format), same as config-agent V3a — see `agent/schema.py`.

## Run

```bash
pip install -r requirements.txt

# Demo / CI: MockLLM + MockConfigStore (no LLM, no DB) — leave USE_REAL_LLM and MYSQL_HOST unset.
PYTHONPATH=. uvicorn api.main:app --host 0.0.0.0 --port 8081

# Real: set USE_REAL_LLM=1, LLM_*, and MYSQL_* (see .env.example).
```

CLI quick check:

```bash
PYTHONPATH=. python cli.py "appid 123, reject nếu tổng tiền 24h > 10 triệu và account mới hơn 7 ngày"
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat` | manual path; returns `clarify` or `awaiting_review` |
| POST | `/runs/from-report` | pull report by `run_id`, build config |
| GET | `/runs/{id}` | poll status + config plan |
| POST | `/runs/{id}/review` | `{decision: approve\|reject}` — resume past interrupt |
| GET | `/runs`, `/configs`, `/sessions`, `/health` | listings / health |

## Tests

```bash
PYTHONPATH=. pytest
```

All tests run with mocks (MockLLM, MockConfigStore, mocked report fetch) — no LLM or DB needed.

## Config (env)

See `.env.example`. `USE_REAL_LLM` toggles the real LLM; `MYSQL_HOST` toggles the real config
store; `FRAUD_AGENT_URL` points at the fraud-analysis-agent for pull-by-run_id.
