"""finalize_investigation_node — compile InvestigationReport + legacy final_report.

Picks the best pattern (passed > F1 ranking), writes the report into state,
and also fills `final_report` so the existing `human_review_node` /
`policy_output_node` / review UI keep working.
"""
from __future__ import annotations

from app.state import AgentState, InvestigationReport, PatternAttempt


def _pick_final(patterns: list[dict]) -> dict | None:
    if not patterns:
        return None
    # Only patterns that were actually scored qualify. A pattern with no
    # metrics never reaches the policy output — `compute_metrics` is the
    # only ground truth.
    scored = [
        p for p in patterns
        if (p.get("metrics") or {}).get("f1", 0) > 0
    ]
    if not scored:
        return None
    passed = [p for p in scored if p.get("status") == "passed"]
    pool = passed or scored
    return max(pool, key=lambda p: (p.get("metrics") or {}).get("f1", 0))


def _stop_reason(state: AgentState, final: dict | None) -> str:
    reason = state.get("investigation_stop_reason")
    if reason == "self_declared":
        return "self_declared"
    if final and final.get("status") == "passed":
        return "converged"
    if not (state.get("patterns_attempted") or []):
        return "no_pattern"
    return "max_iter"


def _build_recommendation(final: dict | None, stop_reason: str) -> str:
    if stop_reason == "no_pattern" or not final:
        return (
            "Không tìm được pattern đủ tốt để đề xuất rule. Khuyến nghị "
            "monitor 3-7 ngày, gắn tag case để collect thêm label, "
            "escalate human review nếu fraud amount tiếp tục tăng."
        )
    metrics = final.get("metrics") or {}
    action = final.get("recommended_action") or "monitor"
    return (
        f"Đề xuất: {action.upper()} | rule: {final.get('description', '(no description)')} "
        f"| precision={metrics.get('precision')} recall={metrics.get('recall')} "
        f"f1={metrics.get('f1')}."
    )


def _legacy_final_report(final: dict | None, state: AgentState) -> dict:
    """Shape kept compatible with the current review UI / policy_output."""
    metrics = (final or {}).get("metrics") or {}
    return {
        "pattern": {
            "description": (final or {}).get("description", ""),
            "signal_columns": (final or {}).get("signal_columns", []),
            "rationale": (final or {}).get("rationale", ""),
            "expected_precision": metrics.get("precision", 0.0),
            "expected_recall": metrics.get("recall", 0.0),
        },
        "sql": (final or {}).get("sql_predicate", ""),
        "metrics": {
            "precision": metrics.get("precision", 0.0),
            "recall": metrics.get("recall", 0.0),
            "f1": metrics.get("f1", 0.0),
            "hit_count": metrics.get("hit_count", 0),
            "total_fraud": metrics.get("total_fraud", 0),
            "total_flagged": metrics.get("total_flagged", 0),
        },
        "iteration_count": state.get("investigation_iteration", 0),
        "iteration_history": state.get("investigation_log") or [],
        "recommendation": "",
    }


def finalize_investigation_node(state: AgentState) -> dict:
    patterns = state.get("patterns_attempted") or []
    final = _pick_final(patterns)
    stop_reason = _stop_reason(state, final)
    recommendation = _build_recommendation(final, stop_reason)

    # Construct Pydantic to validate shape + coerce.
    report = InvestigationReport(
        patterns_attempted=[PatternAttempt(**p) for p in patterns],
        final_pattern=PatternAttempt(**final) if final else None,
        stop_reason=stop_reason if stop_reason in (
            "converged", "max_iter", "no_pattern", "self_declared", "error"
        ) else "error",
        iteration_count=state.get("investigation_iteration", 0),
        investigation_log=state.get("investigation_log") or [],
        recommendation=recommendation,
    )

    legacy = _legacy_final_report(final, state)
    legacy["recommendation"] = recommendation

    return {
        "investigation_report": report.model_dump(mode="json"),
        "investigation_stop_reason": stop_reason,
        "final_report": legacy,
    }
