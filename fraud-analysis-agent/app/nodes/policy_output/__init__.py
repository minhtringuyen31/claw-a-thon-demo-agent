"""policy_output_node — emit RuleJSON policy suggestion (no human gate).

Runs straight after `finalize_investigation`. If the investigation found
a pattern → emit a `suggested` RuleJSON. If no pattern was found → emit a
`no_action` RuleJSON shell so downstream consumers have a predictable
contract.

Strategist review (if needed) happens downstream — this agent does not
block on it.
"""
from __future__ import annotations

from app.contracts.rulejson import RuleJSON, RuleJSONMetrics
from app.shared.pretty_report import build_pretty_report_investigation
from app.state import AgentState


def _derive_fraud_type(state: AgentState) -> str:
    cases = (state.get("fraud_context") or {}).get("reported_cases") or []
    codes = sorted({
        str(c.get("fraud_type"))
        for c in cases
        if isinstance(c, dict) and c.get("fraud_type")
    })
    if not codes:
        return "unknown"
    if len(codes) == 1:
        return codes[0]
    return "+".join(codes)


def policy_output_node(state: AgentState) -> dict:
    report = state.get("investigation_report") or {}
    final_pattern = report.get("final_pattern") or {}
    fraud_type = _derive_fraud_type(state)

    metrics = final_pattern.get("metrics") or {}
    has_pattern = bool(final_pattern.get("sql_predicate"))

    rule = RuleJSON(
        rule_name=f"fraud_{fraud_type}",
        fraud_type=fraud_type,
        sql_predicate=final_pattern.get("sql_predicate", ""),
        description=final_pattern.get("description", ""),
        signal_columns=final_pattern.get("signal_columns", []),
        recommended_action=final_pattern.get("recommended_action") or "none",
        metrics=RuleJSONMetrics(
            precision=metrics.get("precision", 0.0) if metrics else 0.0,
            recall=metrics.get("recall", 0.0) if metrics else 0.0,
            f1=metrics.get("f1", 0.0) if metrics else 0.0,
        ),
        iteration_count=report.get("iteration_count", 0),
        status="suggested" if has_pattern else "no_action",
        source_run_id=state.get("run_id"),
    )

    rule_dict = rule.model_dump()
    # Build the pretty markdown report from the full state + the new rule.
    pretty = build_pretty_report_investigation({**state, "rule_json": rule_dict})
    return {"rule_json": rule_dict, "pretty_report": pretty}
