"""FastAPI service for the Risk Analysis Agent.

Endpoints:
  POST /runs                    - create a run (async, returns run_id)
  GET  /runs/{run_id}           - poll status + full investigation report
  GET  /runs/{run_id}/stream    - SSE stream of investigation_log entries
  GET  /runs                    - list known run_ids
  POST /triggers/email          - email-listener webhook
  POST /triggers/postmortem     - post-mortem DB event webhook
  GET  /health

Run:
  uvicorn app.service:app --reload
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.graph import _build_checkpointer, build_graph
from app.state import ThresholdConfig


# ---------- checkpointer + graph (shared across requests) ----------

CHECKPOINTER, _CP_HANDLE = _build_checkpointer()
APP_GRAPH = build_graph(checkpointer=CHECKPOINTER)

# ---------- streaming state ----------
# One asyncio.Queue per active run. Items are tuples: ("step", entry_dict) | ("done", None).
_run_queues: dict[str, asyncio.Queue] = {}
_event_loop: asyncio.AbstractEventLoop | None = None
# threading.Event per run — set to request cancellation of background task
import threading
_cancel_flags: dict[str, threading.Event] = {}


# ---------- API models ----------

class SourceType(str, Enum):
    email = "email"
    postmortem = "postmortem"


class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class CreateRunRequest(BaseModel):
    source_type: SourceType
    raw_input: str = Field(..., description="Email text or post-mortem record")
    min_precision: float = 0.80
    min_recall: float = 0.60
    max_iterations: int = 10


class EmailTriggerRequest(BaseModel):
    subject: Optional[str] = None
    sender: Optional[str] = None
    body: str
    min_precision: float = 0.80
    min_recall: float = 0.60
    max_iterations: int = 10


class PostmortemTriggerRequest(BaseModel):
    incident_id: Optional[str] = None
    summary: Optional[str] = None
    record: dict[str, Any] = Field(default_factory=dict)
    min_precision: float = 0.80
    min_recall: float = 0.60
    max_iterations: int = 10


class RunOut(BaseModel):
    run_id: str
    status: RunStatus
    anomaly_decision: Optional[dict] = None
    investigation_window: Optional[dict] = None
    investigation_report: Optional[dict] = None
    no_action_report: Optional[dict] = None
    rule_json: Optional[dict] = None
    pretty_report: Optional[str] = None


# ---------- helpers ----------

def _cfg(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _push(run_id: str, kind: str, data: Any) -> None:
    """Thread-safe push from background thread into the run's asyncio queue."""
    q = _run_queues.get(run_id)
    if q and _event_loop and _event_loop.is_running():
        try:
            _event_loop.call_soon_threadsafe(q.put_nowait, (kind, data))
        except RuntimeError:
            pass  # loop closed between the is_running() check and the call


def _node_event(node_name: str, update: dict) -> dict | None:
    """Build a synthetic trace event for a non-investigation node update."""
    if node_name == "ingest" and "fraud_context" in update:
        fc = update["fraud_context"] or {}
        return {
            "node": "ingest",
            "raw_summary": fc.get("raw_summary", ""),
            "severity": fc.get("severity", ""),
            "cases_count": len(fc.get("reported_cases", [])),
        }
    if node_name == "anomaly_check" and "anomaly_decision" in update:
        ad = update["anomaly_decision"] or {}
        return {
            "node": "anomaly_check",
            "is_anomalous": ad.get("is_anomalous"),
            "confidence": ad.get("confidence"),
            "reasoning": ad.get("reasoning", ""),
            "evidence": ad.get("evidence", []),
        }
    if node_name == "fetch_data":
        slices = update.get("investigation_slices") or {}
        window = update.get("investigation_window") or {}
        return {
            "node": "fetch_data",
            "slices_count": len(slices),
            "slice_keys": list(slices.keys()),
            "window_start": window.get("start", ""),
            "window_end": window.get("end", ""),
        }
    if node_name == "finalize_investigation" and "investigation_report" in update:
        ir = update["investigation_report"] or {}
        return {
            "node": "finalize_investigation",
            "stop_reason": ir.get("stop_reason"),
            "iteration_count": ir.get("iteration_count"),
            "has_final_pattern": ir.get("final_pattern") is not None,
        }
    if node_name == "policy_output" and "rule_json" in update:
        rj = update["rule_json"] or {}
        return {
            "node": "policy_output",
            "rule_name": rj.get("rule_name"),
            "recommended_action": rj.get("recommended_action"),
            "status": rj.get("status"),
            "metrics": rj.get("metrics"),
        }
    if node_name == "action_output":
        nr = update.get("no_action_report") or {}
        return {
            "node": "action_output",
            "recommendation": nr.get("recommendation", "No anomaly detected."),
        }
    return None


def _replay_events(v: dict) -> list[dict]:
    """Reconstruct ordered trace events from a completed (or partial) checkpoint."""
    events: list[dict] = []

    fc = v.get("fraud_context") or {}
    if fc:
        events.append({
            "node": "ingest",
            "raw_summary": fc.get("raw_summary", ""),
            "severity": fc.get("severity", ""),
            "cases_count": len(fc.get("reported_cases", [])),
        })

    ad = v.get("anomaly_decision") or {}
    if ad:
        events.append({
            "node": "anomaly_check",
            "is_anomalous": ad.get("is_anomalous"),
            "confidence": ad.get("confidence"),
            "reasoning": ad.get("reasoning", ""),
            "evidence": ad.get("evidence", []),
        })

    slices = v.get("investigation_slices") or {}
    window = v.get("investigation_window") or {}
    if slices or window:
        events.append({
            "node": "fetch_data",
            "slices_count": len(slices),
            "slice_keys": list(slices.keys()),
            "window_start": window.get("start", ""),
            "window_end": window.get("end", ""),
        })

    for entry in v.get("investigation_log") or []:
        events.append(entry)

    ir = v.get("investigation_report") or {}
    if ir:
        events.append({
            "node": "finalize_investigation",
            "stop_reason": ir.get("stop_reason"),
            "iteration_count": ir.get("iteration_count"),
            "has_final_pattern": ir.get("final_pattern") is not None,
        })

    rj = v.get("rule_json") or {}
    if rj:
        events.append({
            "node": "policy_output",
            "rule_name": rj.get("rule_name"),
            "recommended_action": rj.get("recommended_action"),
            "status": rj.get("status"),
            "metrics": rj.get("metrics"),
        })

    nr = v.get("no_action_report") or {}
    if nr and not slices:
        events.append({
            "node": "action_output",
            "recommendation": nr.get("recommendation", ""),
        })

    return events


def _stream_to_end(run_id: str, initial: dict) -> None:
    """Background task: run graph and push trace events for every node."""
    cancel = _cancel_flags.get(run_id)
    try:
        for event in APP_GRAPH.stream(initial, _cfg(run_id), stream_mode="updates"):
            if cancel and cancel.is_set():
                print(f"[run {run_id}] cancelled")
                break
            for node_name, update in event.items():
                if not isinstance(update, dict):
                    continue
                # investigation_log uses `add` reducer → only NEW entries arrive here
                for entry in update.get("investigation_log", []):
                    _push(run_id, "step", entry)
                # Per-node synthetic events for all other nodes
                evt = _node_event(node_name, update)
                if evt is not None:
                    _push(run_id, "step", evt)
    except Exception as e:  # noqa: BLE001
        print(f"[run {run_id}] error: {e}")
    finally:
        _push(run_id, "done", None)
        _cancel_flags.pop(run_id, None)


def _snapshot_to_out(run_id: str) -> RunOut:
    snap = APP_GRAPH.get_state(_cfg(run_id))
    if not snap.values:
        raise HTTPException(404, f"Run {run_id} not found")
    v = snap.values
    status = RunStatus.completed if not snap.next else RunStatus.running
    return RunOut(
        run_id=run_id,
        status=status,
        anomaly_decision=v.get("anomaly_decision"),
        investigation_window=v.get("investigation_window"),
        investigation_report=v.get("investigation_report"),
        no_action_report=v.get("no_action_report"),
        rule_json=v.get("rule_json"),
        pretty_report=v.get("pretty_report"),
    )


def _start_run(req: CreateRunRequest, bg: BackgroundTasks) -> RunOut:
    run_id = str(uuid.uuid4())[:8]
    # Create queue and cancel flag before background task starts
    _run_queues[run_id] = asyncio.Queue()
    _cancel_flags[run_id] = threading.Event()
    initial = {
        "run_id": run_id,
        "source_type": req.source_type.value,
        "raw_input": req.raw_input,
        "threshold_config": ThresholdConfig(
            min_precision=req.min_precision,
            min_recall=req.min_recall,
            max_iterations=req.max_iterations,
        ).model_dump(),
    }
    bg.add_task(_stream_to_end, run_id, initial)
    return RunOut(run_id=run_id, status=RunStatus.running)


# ---------- app ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    yield
    _run_queues.clear()


app = FastAPI(title="Risk Analysis Agent", version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- endpoints ----------

@app.post("/runs", response_model=RunOut, status_code=202)
def create_run(req: CreateRunRequest, bg: BackgroundTasks):
    return _start_run(req, bg)


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """SSE endpoint — streams InvestigationStep entries as they are produced.

    Protocol:
      data: <json>          — one InvestigationStep dict per event
      event: done\ndata: {} — signals end of stream
      : keepalive           — comment sent every 15 s to keep the connection alive
    """
    # Replay entries already checkpointed (client may connect mid-run or after completion)
    snap = APP_GRAPH.get_state(_cfg(run_id))
    if not snap or not snap.values:
        raise HTTPException(404, f"Run {run_id} not found")

    already_done = not snap.next
    replay = _replay_events(snap.values)

    # Ensure a queue exists (needed when connecting to a still-running run)
    if run_id not in _run_queues:
        _run_queues[run_id] = asyncio.Queue()
    queue = _run_queues[run_id]

    async def generate():
        # 1. Replay all persisted events in order (ingest → anomaly → fetch → iterations → finalize → policy)
        for entry in replay:
            yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"

        # 2. If run is already finished, close immediately
        if already_done:
            yield "event: done\ndata: {}\n\n"
            _run_queues.pop(run_id, None)
            return

        # 3. Stream new entries from queue as they arrive
        while True:
            try:
                kind, data = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            if kind == "done":
                yield "event: done\ndata: {}\n\n"
                _run_queues.pop(run_id, None)
                break

            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str):
    return _snapshot_to_out(run_id)


@app.get("/runs", response_model=list[str])
def list_runs():
    if isinstance(_CP_HANDLE, sqlite3.Connection):
        rows = _CP_HANDLE.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        ).fetchall()
        return [r[0] for r in rows]
    return []


@app.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: str):
    # Signal cancellation if background task is still running
    flag = _cancel_flags.get(run_id)
    if flag:
        flag.set()
    _run_queues.pop(run_id, None)
    # Erase from checkpoints DB
    if isinstance(_CP_HANDLE, sqlite3.Connection):
        _CP_HANDLE.execute("DELETE FROM checkpoints WHERE thread_id = ?", (run_id,))
        _CP_HANDLE.execute("DELETE FROM writes WHERE thread_id = ?", (run_id,))
        _CP_HANDLE.commit()


@app.post("/triggers/email", response_model=RunOut, status_code=202)
def trigger_email(req: EmailTriggerRequest, bg: BackgroundTasks):
    header_lines = []
    if req.sender:
        header_lines.append(f"From: {req.sender}")
    if req.subject:
        header_lines.append(f"Subject: {req.subject}")
    raw = "\n".join(header_lines + ["", req.body]) if header_lines else req.body
    return _start_run(
        CreateRunRequest(
            source_type=SourceType.email,
            raw_input=raw,
            min_precision=req.min_precision,
            min_recall=req.min_recall,
            max_iterations=req.max_iterations,
        ),
        bg,
    )


@app.post("/triggers/postmortem", response_model=RunOut, status_code=202)
def trigger_postmortem(req: PostmortemTriggerRequest, bg: BackgroundTasks):
    parts = []
    if req.incident_id:
        parts.append(f"Incident: {req.incident_id}")
    if req.summary:
        parts.append(f"Summary: {req.summary}")
    if req.record:
        parts.append("Record:\n" + json.dumps(req.record, indent=2, ensure_ascii=False))
    raw = "\n".join(parts) if parts else "(empty post-mortem record)"
    return _start_run(
        CreateRunRequest(
            source_type=SourceType.postmortem,
            raw_input=raw,
            min_precision=req.min_precision,
            min_recall=req.min_recall,
            max_iterations=req.max_iterations,
        ),
        bg,
    )


@app.get("/health")
def health():
    return {"status": "ok"}
