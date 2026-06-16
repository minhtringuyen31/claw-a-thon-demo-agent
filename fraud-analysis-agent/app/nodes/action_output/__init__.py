"""action_output_node — terminal report when anomaly_check decides 'normal'.

Builds a NoActionReport that bundles the decision + both summaries +
a human-readable recommendation, then notifies the strategist. No human
review interrupt — there is no rule to approve.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.shared.notify import notify_strategist
from app.shared.pretty_report import build_pretty_report_no_action
from app.state import AgentState, NoActionReport


def action_output_node(state: AgentState) -> dict:
    decision = state.get("anomaly_decision") or {}
    baseline_window = state.get("baseline_window") or {}
    reported_summary = state.get("reported_summary") or {}
    baseline_summary = state.get("baseline_summary") or {}

    rec = (
        "No investigation needed. Reported cases align with the previous "
        f"{_window_days(baseline_window)}-day baseline."
    )

    report = NoActionReport(
        decision=decision,
        baseline_window=baseline_window,
        reported_summary=reported_summary,
        baseline_summary=baseline_summary,
        recommendation=rec,
        emitted_at=datetime.now(timezone.utc).isoformat(),
    )

    notify_strategist(
        "[NO ACTION] "
        + rec + "\n"
        + f"Confidence : {decision.get('confidence', 0)}\n"
        + f"Reasoning  : {decision.get('reasoning', '')}\n"
        + f"Evidence   : {decision.get('evidence', [])}"
    )

    no_action_dict = report.model_dump(mode="json")
    pretty = build_pretty_report_no_action({**state, "no_action_report": no_action_dict})
    return {"no_action_report": no_action_dict, "pretty_report": pretty}


def _window_days(window: dict) -> int:
    if not window:
        return 7
    from datetime import date
    try:
        start = date.fromisoformat(window["start"])
        end = date.fromisoformat(window["end"])
        return max(1, (end - start).days)
    except Exception:
        return 7
