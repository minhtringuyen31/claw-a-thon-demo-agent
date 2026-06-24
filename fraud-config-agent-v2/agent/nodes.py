"""Graph nodes. Each returns a partial state update (dict)."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

from agent.prompts import (
    BUILD_CONFIG_SYSTEM, BUILD_CONFIG_USER,
    CLARIFY_SYSTEM, CLARIFY_USER,
    INTAKE_SYSTEM, INTAKE_USER,
)
from agent.schema import FraudConfig
from llm import get_llm
from mcp_client import call_tool


def _get_config(event_name: str) -> dict:
    return call_tool("get_config", event_name=event_name)


def _save_config(event_name: str, description: str, config_json: dict,
                 source_run_id: str | None = None, created_by: str | None = None) -> dict:
    return call_tool("save_config", event_name=event_name, description=description,
                     config_json=config_json, source_run_id=source_run_id, created_by=created_by)


def _append_session(key: str, item: dict) -> None:
    call_tool("append_session", key=key, item=item)


def _call_llm(role: str, system: str, user: str) -> dict:
    return get_llm(role=role).complete_json(system, user)


def _format_history(history: list) -> str:
    if not history:
        return ""
    lines = ["Previous turns in this session (use for context — app_id, event, action, conditions already established):\n"]
    for i, turn in enumerate(history, 1):
        lines.append(f"Turn {i}:")
        lines.append(f"  User: {turn.get('user', '')[:200]}")
        if turn.get("requirement_summary"):
            lines.append(f"  Extracted requirement: {turn['requirement_summary']}")
        if turn.get("config_summary"):
            lines.append(f"  Config built: {turn['config_summary']}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _condition_key(conditions: list[dict]) -> set:
    # Ignore the appID scope condition: dedup compares fraud logic, and the
    # config is already fetched per-app (rule_config is keyed by app_id).
    return {
        (c.get("field"), c.get("operator"), str(c.get("value")))
        for c in (conditions or [])
        if c.get("field") not in ("appID", "appid")
    }


# --------------------------------------------------------------------------

def _serialize_report(report: dict) -> str:
    fp = report.get("final_pattern") or {}
    m = fp.get("metrics") or {}
    return (
        "[FRAUD-ANALYSIS-AGENT REPORT]\n"
        f"Recommendation: {report.get('recommendation', '')}\n"
        f"Final pattern description: {fp.get('description', '')}\n"
        f"SQL predicate: {fp.get('sql_predicate', '')}\n"
        f"Signal columns: {', '.join(fp.get('signal_columns', []))}\n"
        f"Recommended action: {fp.get('recommended_action', 'none')}\n"
        f"Metrics: precision={m.get('precision')} recall={m.get('recall')} f1={m.get('f1')}"
    )


def intake_node(state: "dict") -> dict:
    if state.get("source_type") == "report" and state.get("fraud_report"):
        raw = _serialize_report(state["fraud_report"])
    else:
        raw = state.get("raw_input", "")
    history_text = _format_history(state.get("conversation_history") or [])
    requirement = _call_llm(
        "intake", INTAKE_SYSTEM,
        INTAKE_USER.format(raw_input=raw, conversation_history=history_text),
    )
    return {"requirement": requirement or {}}


def clarify_node(state: "dict") -> dict:
    history = list(state.get("clarify_history") or [])

    # Record the latest answer (if resuming a clarification round).
    if state.get("clarification_answer") and state.get("clarify_question"):
        history.append({
            "question": state["clarify_question"],
            "answer": state["clarification_answer"],
        })

    result = _call_llm(
        "clarify", CLARIFY_SYSTEM,
        CLARIFY_USER.format(
            requirement=json.dumps(state.get("requirement", {}), ensure_ascii=False),
            history=json.dumps(history, ensure_ascii=False),
        ),
    )

    if result.get("needs_clarification"):
        return {
            "needs_clarification": True,
            "clarify_question": result.get("question", ""),
            "clarify_history": history,
        }

    # Merge accumulated answers into requirement for downstream context.
    updated_req = dict(state.get("requirement", {}))
    if history:
        updated_req["_clarifications"] = history
    return {
        "needs_clarification": False,
        "clarify_question": "",
        "clarify_history": history,
        "requirement": updated_req,
    }


def dependency_resolver(state: "dict") -> dict:
    """Rule-level dedup: does the intended rule already live in the target event?"""
    req = state.get("requirement", {})
    intended_event = (req.get("event_name") or "").strip().lower()

    # Prefer session-level existing_config (in-progress edits) over DB.
    existing = state.get("existing_config") or (
        _get_config(intended_event) if intended_event else {}
    ) or {}

    # If the intended event name differs from existing, treat as fresh create.
    existing_event_names = {
        (ev.get("name") or "").strip().lower()
        for ev in (existing.get("events") or [])
    }
    if intended_event and existing_event_names and intended_event not in existing_event_names:
        return {"operation": "create", "existing_config": {}, "dedup": {"found": False, "event_name": "", "rule_name": ""}}

    intended_name = (req.get("profile_name") or "").strip().lower()
    intended_conds = _condition_key(req.get("conditions"))

    found = {"found": False, "event_name": "", "rule_name": ""}
    for event in existing.get("events", []) or []:
        for rule in event.get("rules", []) or []:
            same_name = (rule.get("name", "").strip().lower() == intended_name and intended_name)
            same_conds = intended_conds and _condition_key(rule.get("conditions")) == intended_conds
            if same_name or same_conds:
                found = {"found": True, "event_name": event.get("name", ""), "rule_name": rule.get("name", "")}
                break
        if found["found"]:
            break

    operation = "update" if (existing and found["found"]) else "create"
    return {"operation": operation, "existing_config": existing, "dedup": found}


def build_config_node(state: "dict") -> dict:
    user_msg = BUILD_CONFIG_USER.format(
        requirement=json.dumps(state.get("requirement", {}), ensure_ascii=False),
        operation=state.get("operation", "create"),
        dedup=json.dumps(state.get("dedup", {}), ensure_ascii=False),
        existing_config=json.dumps(state.get("existing_config", {}), ensure_ascii=False),
        validation_errors=json.dumps(state.get("validation_errors", []), ensure_ascii=False),
    )
    json_draft = _call_llm("build", BUILD_CONFIG_SYSTEM, user_msg)
    return {"json_draft": json_draft or {}}


def validator_node(state: "dict") -> dict:
    """Run/test the config. FOR NOW always passes (see plan).

    Best-effort Pydantic coercion to clean shape; on any failure we still pass
    through the raw draft so the graph always reaches human_review.
    """
    draft = state.get("json_draft", {}) or {}
    try:
        final = FraudConfig(**draft).model_dump()
    except Exception:
        final = draft
    return {"final_output": final, "validation_errors": []}


def human_review_node(state: "dict") -> dict:
    """Marker node. The interrupt happens BEFORE this runs; on resume the API has
    injected `review_decision` / `approved_by` into state. Nothing to compute."""
    return {}


def update_conf_node(state: "dict") -> dict:
    """Write the approved config to the store (MySQL) + save a plan file.

    Each event in final_output.events is saved as a separate record keyed by event_name.
    """
    if state.get("review_decision") != "approve":
        return {"write_result": {"written": False, "reason": "not approved"}}

    final = state.get("final_output", {}) or {}
    req = state.get("requirement", {})
    events = final.get("events") or []

    if not events:
        return {"write_result": {"written": False, "reason": "no events in final_output"}}

    # Save a plan file for download / audit (full config).
    out_dir = pathlib.Path("output")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    first_event_name = (events[0].get("name") or "unknown").replace(" ", "_")
    fname = f"{first_event_name}_{ts}.json"
    fpath = out_dir / fname
    fpath.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save each event as a separate DB record.
    last_result: dict = {}
    for ev in events:
        event_name = ev.get("name") or req.get("event_name") or "unknown"
        description = (
            ev.get("description")
            or req.get("description")
            or req.get("profile_name")
            or event_name
        )
        last_result = _save_config(
            event_name=event_name,
            description=description,
            config_json=ev,
            source_run_id=state.get("run_id"),
            created_by=state.get("approved_by"),
        )

    write_result = {**last_result, "events_saved": len(events)}

    # Persist a session breadcrumb via MCP.
    sid = state.get("session_id", "")
    if sid:
        _append_session(f"session:{sid}", {
            "event_name": first_event_name,
            "output_file": str(fpath), "write_result": write_result,
        })

    return {"output_file": str(fpath), "write_result": write_result}
