"""FastAPI service for fraud-config-agent-v2.

Two entry paths feed one graph:
  - POST /chat              manual strategist input (with clarify loop)
  - POST /runs/from-report  pull a fraud-analysis-agent run by id, reason it into config

Both pause at the human-review interrupt; resume via POST /runs/{id}/review.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from agent.graph import build_graph  # noqa: E402  (after load_dotenv)
from mcp_client import call_tool  # noqa: E402

app = FastAPI(title="Fraud Config Agent v2")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

_BASE = pathlib.Path(__file__).resolve().parent.parent
_output_dir = _BASE / "output"
_output_dir.mkdir(exist_ok=True)
_sessions_dir = _BASE / "sessions"
_sessions_dir.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(_output_dir)), name="output")
app.mount("/static", StaticFiles(directory=str(_BASE / "static")), name="static")

# Shared checkpointer (interrupt/resume needs persistence).
from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402

_conn = sqlite3.connect(str(_BASE / "checkpoints.db"), check_same_thread=False)
_checkpointer = SqliteSaver(_conn)
_graph = build_graph(checkpointer=_checkpointer)


def _mem_get(key: str):
    r = call_tool("get_session", key=key)
    return r.get("value") if r.get("found") else None


def _mem_set(key: str, value) -> None:
    call_tool("save_session", key=key, value=value)


def _mem_append(key: str, item: dict) -> None:
    call_tool("append_session", key=key, item=item)

# Lightweight run registry (for listing; truth lives in the checkpointer).
_runs: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cfg(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _initial_state(**kw) -> dict:
    base = {
        "raw_input": "", "source_type": "chat", "run_id": "", "fraud_report": {},
        "requirement": {}, "session_id": "", "clarify_question": "",
        "clarification_answer": "", "needs_clarification": False, "clarify_history": [],
        "conversation_history": [],
        "operation": "create", "existing_config": {}, "dedup": {},
        "json_draft": {}, "validation_errors": [], "final_output": {}, "retry_count": 0,
        "approved_by": None, "review_decision": None, "output_file": "", "write_result": {},
    }
    base.update(kw)
    return base


def _status_of(run_id: str) -> tuple[str, dict]:
    """Return (status, values) by inspecting the checkpointed graph state."""
    snap = _graph.get_state(_cfg(run_id))
    values = snap.values or {}
    if values.get("needs_clarification"):
        return "clarify", values
    if snap.next and "human_review" in snap.next:
        return "awaiting_review", values
    if not snap.next:
        if values.get("write_result", {}).get("written"):
            return "completed", values
        if values.get("review_decision") == "reject":
            return "rejected", values
        if values.get("final_output"):
            return "awaiting_review", values  # finished build, never resumed
    return "running", values


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1, max_length=4096)
    clarification_answer: str = ""


class FromReportRequest(BaseModel):
    run_id: str = Field(..., min_length=1)
    fraud_agent_url: str | None = None
    session_id: str | None = None


class ReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    approved_by: str = ""


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@app.get("/")
def root():
    return FileResponse(str(_BASE / "static" / "index.html"))


@app.get("/health")
def health():
    return {"status": "ok"}


def _summarize_requirement(req: dict) -> str:
    if not req:
        return ""
    parts = []
    if req.get("event_name"):
        parts.append(f"event={req['event_name']}")
    if req.get("action"):
        parts.append(f"action={req['action']}")
    conds = req.get("conditions") or []
    if conds:
        parts.append(f"{len(conds)} conditions: " + "; ".join(
            f"{c.get('field')} {c.get('operator')} {c.get('value')}" for c in conds[:4]
        ) + ("…" if len(conds) > 4 else ""))
    return ", ".join(parts)


def _summarize_config(final_output: dict) -> str:
    if not final_output:
        return ""
    events = final_output.get("events") or []
    if not events:
        return ""
    ev = events[0]
    rules = ev.get("rules") or []
    rule_name = rules[0].get("name", "") if rules else ""
    n_conds = len(rules[0].get("conditions") or []) if rules else 0
    return f"event={ev.get('name')}, rule='{rule_name}', {n_conds} conditions, action={ev.get('actionCode')}"


def _run_chat(message: str, session_id: str, clarification_answer: str) -> dict:
    clarify_history = _mem_get(f"clarify:{session_id}") or []
    conv_history = _mem_get(f"conv:{session_id}") or []
    # Use the last turn's final_output as the base config for in-session modifications
    # (avoids pulling stale/unrelated configs from DB).
    prev_final_output = conv_history[-1].get("final_output", {}) if conv_history else {}
    run_id = str(uuid.uuid4())
    state = _initial_state(
        raw_input=message, source_type="chat", session_id=session_id,
        clarification_answer=clarification_answer, clarify_history=clarify_history,
        clarify_question=(clarify_history[-1]["question"] if (clarification_answer and clarify_history) else ""),
        conversation_history=conv_history,
        existing_config=prev_final_output,
    )
    _graph.invoke(state, _cfg(run_id))
    _runs[run_id] = {"session_id": session_id, "source_type": "chat", "created_at": _now()}
    status, values = _status_of(run_id)

    if status == "clarify":
        _mem_set(f"clarify:{session_id}", values.get("clarify_history", []))
        return {"status": "clarify", "question": values.get("clarify_question", ""),
                "session_id": session_id, "run_id": run_id}

    # Proceeded — save this turn to conversation history.
    _mem_set(f"clarify:{session_id}", [])
    turn = {
        "user": message[:300],
        "requirement_summary": _summarize_requirement(values.get("requirement", {})),
        "config_summary": _summarize_config(values.get("final_output", {})),
        "final_output": values.get("final_output", {}),
    }
    updated_conv = (conv_history or []) + [turn]
    _mem_set(f"conv:{session_id}", updated_conv[-10:])  # keep last 10 turns

    return {"status": status, "run_id": run_id, "session_id": session_id,
            "final_output": values.get("final_output", {}),
            "operation": values.get("operation"), "dedup": values.get("dedup")}


@app.post("/chat")
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    answer = req.clarification_answer.strip()
    return _run_chat(req.message, session_id, answer)


@app.post("/runs/from-report")
def from_report(req: FromReportRequest):
    kwargs = {"run_id": req.run_id}
    if req.fraud_agent_url:
        kwargs["base_url"] = req.fraud_agent_url
    report = call_tool("fetch_fraud_report", **kwargs)
    if "error" in report:
        status_code = 409 if "not ready" in report["error"] else 502
        raise HTTPException(status_code, report["error"])

    session_id = req.session_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    state = _initial_state(
        source_type="report", fraud_report=report, run_id=req.run_id,
        session_id=session_id, raw_input=report.get("recommendation", ""),
    )
    _graph.invoke(state, _cfg(run_id))
    _runs[run_id] = {"session_id": session_id, "source_type": "report",
                     "source_run_id": req.run_id, "created_at": _now()}
    status, values = _status_of(run_id)
    return {"status": status, "run_id": run_id, "session_id": session_id,
            "source_run_id": req.run_id,
            "final_output": values.get("final_output", {}),
            "operation": values.get("operation"), "dedup": values.get("dedup"),
            "question": values.get("clarify_question", "")}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    snap = _graph.get_state(_cfg(run_id))
    if not snap.values:
        raise HTTPException(404, f"run {run_id} not found")
    status, values = _status_of(run_id)
    meta = _runs.get(run_id, {})
    return {
        "run_id": run_id, "status": status,
        "source_type": meta.get("source_type"),
        "source_run_id": meta.get("source_run_id"),
        "operation": values.get("operation"),
        "dedup": values.get("dedup"),
        "requirement": values.get("requirement", {}),
        "final_output": values.get("final_output", {}),
        "output_file": values.get("output_file", ""),
        "write_result": values.get("write_result", {}),
    }


@app.post("/runs/{run_id}/review")
def review(run_id: str, req: ReviewRequest):
    snap = _graph.get_state(_cfg(run_id))
    if not snap.values:
        raise HTTPException(404, f"run {run_id} not found")
    if "human_review" not in (snap.next or ()):
        raise HTTPException(409, f"run {run_id} is not awaiting review (next={snap.next})")

    _graph.update_state(
        _cfg(run_id),
        {"review_decision": req.decision, "approved_by": req.approved_by or "strategist"},
    )
    _graph.invoke(None, _cfg(run_id))  # resume past the interrupt
    status, values = _status_of(run_id)
    return {"run_id": run_id, "status": status,
            "write_result": values.get("write_result", {}),
            "output_file": values.get("output_file", "")}


@app.get("/runs")
def list_runs():
    return [{"run_id": rid, **meta, "status": _status_of(rid)[0]} for rid, meta in _runs.items()]


@app.get("/rules")
def list_db_rules(limit: int = 100):
    """Deployed rules read straight from the config store (via MCP)."""
    result = call_tool("list_configs", limit=limit)
    return result.get("configs", [])


@app.get("/configs")
def list_configs():
    files = sorted(_output_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"filename": f.name, "url": f"/output/{f.name}", "size": f.stat().st_size} for f in files]


@app.get("/sessions")
def list_sessions():
    out = []
    for p in sorted(_sessions_dir.glob("session_*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({"file": p.name, "entries": len(data) if isinstance(data, list) else 1})
        except Exception:
            continue
    return out
