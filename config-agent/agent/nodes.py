import json
import os
import pathlib
from datetime import datetime
from openai import OpenAI
from agent.state import ConfigAgentState
from agent.schema import FraudConfig
from agent.prompts import (
    INTAKE_SYSTEM, INTAKE_USER,
    PLANNER_SYSTEM, PLANNER_USER,
    BUILD_CONFIG_SYSTEM, BUILD_CONFIG_USER,
    CLARIFY_SYSTEM, CLARIFY_USER,
)
from services.mock_config_service import MockConfigService
from services.memory_service import MockMemoryService

MODEL = "minimax/minimax-m2.5"
_mock_service = MockConfigService()
_memory_service = MockMemoryService()


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ["LLM_BASE_URL"],
    )


def _extract_json_text(text: str) -> str:
    import re
    text = text.strip()
    # Strip <think>...</think> reasoning blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()
    return text


def _call_llm(system: str, user: str) -> dict:
    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    raw = response.choices[0].message.content
    return json.loads(_extract_json_text(raw))


def intake_node(state: ConfigAgentState) -> dict:
    user_msg = INTAKE_USER.format(raw_input=state["raw_input"])
    requirement = _call_llm(INTAKE_SYSTEM, user_msg)
    return {"requirement": requirement}


def planner_node(state: ConfigAgentState) -> dict:
    user_msg = PLANNER_USER.format(requirement=json.dumps(state["requirement"], ensure_ascii=False))
    plan = _call_llm(PLANNER_SYSTEM, user_msg)
    return {"plan": plan}


def dependency_resolver(state: ConfigAgentState) -> dict:
    app_id = state["requirement"].get("app_id", "")
    existing = _mock_service.get_profile(app_id)
    if existing:
        return {"operation": "update", "existing_config": existing}
    return {"operation": "create", "existing_config": {}}


def build_config_node(state: ConfigAgentState) -> dict:
    user_msg = BUILD_CONFIG_USER.format(
        requirement=json.dumps(state["requirement"], ensure_ascii=False),
        plan=json.dumps(state["plan"], ensure_ascii=False),
        operation=state["operation"],
        existing_config=json.dumps(state["existing_config"], ensure_ascii=False),
    )
    json_draft = _call_llm(BUILD_CONFIG_SYSTEM, user_msg)
    return {"json_draft": json_draft}


def validator_node(state: ConfigAgentState) -> dict:
    try:
        profile = FraudConfig(**state["json_draft"])
        return {"final_output": profile.model_dump(), "validation_errors": []}
    except Exception as e:
        return {
            "validation_errors": [str(e)],
            "retry_count": state["retry_count"] + 1,
        }


def output_node(state: ConfigAgentState) -> dict:
    profile_name = state["final_output"].get("name", "output").replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{profile_name}_{timestamp}.json"
    output_dir = pathlib.Path("output")
    output_dir.mkdir(exist_ok=True)
    filepath = output_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state["final_output"], f, indent=2, ensure_ascii=False)
    _mock_service.save_profile(
        state["requirement"].get("app_id", "unknown"),
        state["final_output"],
    )
    return {"output_file": str(filepath)}


def clarify_node(state: ConfigAgentState) -> dict:
    history = list(state.get("clarify_history") or [])

    # Record latest answer if we have one
    if state.get("clarification_answer") and state.get("clarify_question"):
        history.append({
            "question": state["clarify_question"],
            "answer": state["clarification_answer"],
        })
        _memory_service.set(f"clarify:{state.get('session_id', '')}", history)

    user_msg = CLARIFY_USER.format(
        requirement=json.dumps(state["requirement"], ensure_ascii=False),
        history=json.dumps(history, ensure_ascii=False),
    )
    result = _call_llm(CLARIFY_SYSTEM, user_msg)

    if result.get("needs_clarification"):
        return {
            "needs_clarification": True,
            "clarify_question": result.get("question", ""),
            "clarify_history": history,
        }

    # Merge all answers into requirement so downstream nodes have full context
    updated_req = dict(state.get("requirement", {}))
    updated_req["_clarifications"] = history
    return {
        "needs_clarification": False,
        "clarify_question": "",
        "clarify_history": history,
        "requirement": updated_req,
    }


def memory_load_node(state: ConfigAgentState) -> dict:
    session_id = state.get("session_id", "")
    prefs = _memory_service.get("prefs:global") or {}
    clarify_history = _memory_service.get(f"clarify:{session_id}") or []

    result: dict = {"clarify_history": clarify_history}
    if prefs:
        existing_req = dict(state.get("requirement", {}))
        existing_req["_prefs"] = prefs
        result["requirement"] = existing_req
    return result


def memory_save_node(state: ConfigAgentState) -> dict:
    session_id = state.get("session_id", "")
    app_id = state["requirement"].get("app_id", "unknown")
    _memory_service.append(f"session:{session_id}", {
        "input": state["raw_input"],
        "clarify_history": state.get("clarify_history", []),
        "output_file": state["output_file"],
    })
    if state["final_output"]:
        _memory_service.set(f"profile:{app_id}", state["final_output"])
    _memory_service.set(f"clarify:{session_id}", [])  # clear after done
    action = state["requirement"].get("action", "")
    if action:
        prefs = _memory_service.get("prefs:global") or {}
        prefs["last_action"] = action
        _memory_service.set("prefs:global", prefs)
    return {}
