import os
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from agent.graph import build_graph

load_dotenv()

app = FastAPI(title="Config Agent V3a")

app.mount("/static", StaticFiles(directory="static"), name="static")


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
        return {
            "status": "clarify",
            "question": state["clarify_question"],
            "session_id": session_id,
        }
    if state["final_output"]:
        return {
            "status": "done",
            "final_output": state["final_output"],
            "output_file": state["output_file"],
            "session_id": session_id,
        }
    return {
        "status": "error",
        "message": "Validation failed after max retries",
        "session_id": session_id,
    }


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
