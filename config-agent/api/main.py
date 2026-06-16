import json
import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from agent.graph import build_graph

load_dotenv()

app = FastAPI(title="Config Agent V3a")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

import pathlib
_output_dir = pathlib.Path("output")
_output_dir.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(_output_dir)), name="output")

_sessions_dir = pathlib.Path("sessions")
_sessions_dir.mkdir(exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_path(session_id: str) -> pathlib.Path:
    return _sessions_dir / f"{session_id}.json"


def _load_session(session_id: str) -> dict:
    p = _session_path(session_id)
    if p.exists():
        return json.loads(p.read_text())
    return {"session_id": session_id, "title": "", "created_at": _now(), "updated_at": _now(), "messages": [], "status": "active", "final_output": None}


def _save_session(data: dict) -> None:
    data["updated_at"] = _now()
    _session_path(data["session_id"]).write_text(json.dumps(data, ensure_ascii=False, indent=2))


class PatternRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=4096)


class ChatRequest(BaseModel):
    session_id: str | None = None  # auto-generated if not provided
    message: str = Field(..., min_length=1, max_length=4096)
    clarification_answer: str = ""


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    session = _load_session(session_id)

    # Append user message
    user_content = request.clarification_answer if request.clarification_answer else request.message
    session["messages"].append({"role": "user", "content": user_content, "timestamp": _now()})
    if not session["title"]:
        session["title"] = user_content[:80]

    graph = build_graph()
    state = graph.invoke({
        "raw_input": request.message,
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
        "output_file": "",
        "session_id": session_id,
        "clarify_question": "",
        "clarification_answer": request.clarification_answer,
        "needs_clarification": False,
        "clarify_history": [],
    })

    if state.get("needs_clarification"):
        question = state["clarify_question"]
        session["messages"].append({"role": "assistant", "content": question, "timestamp": _now()})
        session["status"] = "clarifying"
        _save_session(session)
        return {"status": "clarify", "question": question, "session_id": session_id}

    if state["final_output"]:
        session["messages"].append({"role": "assistant", "content": "Config generated successfully.", "timestamp": _now()})
        session["final_output"] = state["final_output"]
        session["output_file"] = state["output_file"]
        session["status"] = "done"
        _save_session(session)
        return {"status": "done", "final_output": state["final_output"], "output_file": state["output_file"], "session_id": session_id}

    session["messages"].append({"role": "assistant", "content": "Validation failed after max retries.", "timestamp": _now()})
    session["status"] = "error"
    _save_session(session)
    return {"status": "error", "message": "Validation failed after max retries", "session_id": session_id}


@app.get("/sessions")
def list_sessions():
    sessions = []
    for p in sorted(_sessions_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            s = json.loads(p.read_text())
            sessions.append({
                "session_id": s["session_id"],
                "title": s.get("title", ""),
                "status": s.get("status", "active"),
                "created_at": s.get("created_at", ""),
                "updated_at": s.get("updated_at", ""),
                "message_count": len(s.get("messages", [])),
                "has_output": s.get("final_output") is not None,
            })
        except Exception:
            continue
    return sessions


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    p = _session_path(session_id)
    if not p.exists():
        from fastapi import HTTPException
        raise HTTPException(404, f"Session {session_id} not found")
    return json.loads(p.read_text())


@app.post("/generate-config")
def generate_config(request: PatternRequest):
    graph = build_graph()
    state = graph.invoke({
        "raw_input": request.input,
        "requirement": {},
        "plan": {},
        "existing_config": {},
        "operation": "create",
        "json_draft": {},
        "validation_errors": [],
        "final_output": {},
        "retry_count": 0,
        "output_file": "",
        "session_id": "agent-call",
        "clarify_question": "",
        "clarification_answer": "proceed",
        "needs_clarification": False,
        "clarify_history": [],
    })
    if state["final_output"]:
        return {
            "final_output": state["final_output"],
            "output_file": state["output_file"],
        }
    from fastapi import HTTPException
    raise HTTPException(
        status_code=422,
        detail={
            "error": "Validation failed after max retries",
            "validation_errors": state["validation_errors"],
        },
    )


@app.get("/configs")
def list_configs():
    files = sorted(_output_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        {"filename": f.name, "url": f"/output/{f.name}", "size": f.stat().st_size}
        for f in files
    ]


@app.get("/configs/latest")
def get_latest_config():
    files = sorted(_output_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        from fastapi import HTTPException
        raise HTTPException(404, "No configs found")
    import json
    return {"filename": files[0].name, "url": f"/output/{files[0].name}", "data": json.loads(files[0].read_text())}
