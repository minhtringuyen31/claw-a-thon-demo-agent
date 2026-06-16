"""Markdown-rendered investigation report.

Two flavors:
  build_pretty_report_investigation(state)  → full report (anomaly + ReAct trace + patterns + rule)
  build_pretty_report_no_action(state)      → short report for the no-anomaly branch

Both return a single markdown string. Used by `policy_output_node` and
`action_output_node` and surfaced via the API `pretty_report` field.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


# --------------------------- helpers -------------------------------------

def _h(level: int, text: str) -> str:
    return f"{'#' * level} {text}\n"


def _kv(label: str, value: Any) -> str:
    if value is None or value == "":
        value = "—"
    return f"- **{label}:** {value}\n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(v: Any, places: int = 4) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{places}f}"
    except (TypeError, ValueError):
        return str(v)


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _safe_json(value: Any, max_chars: int = 200) -> str:
    try:
        return _truncate(
            json.dumps(value, ensure_ascii=False, default=str),
            max_chars,
        )
    except Exception:
        return _truncate(str(value), max_chars)


# --------------------------- anomaly section -----------------------------

def _section_anomaly(decision: dict) -> str:
    if not decision:
        return ""
    is_anom = decision.get("is_anomalous")
    badge = "**ANOMALOUS**" if is_anom else "**NOT ANOMALOUS**"
    out = _h(2, "Anomaly Check")
    out += _kv("Decision", badge)
    out += _kv("Confidence", _num(decision.get("confidence"), 2))
    reasoning = decision.get("reasoning")
    if reasoning:
        out += "\n**Reasoning:**\n"
        out += f"> {reasoning.strip()}\n"
    evidence = decision.get("evidence") or []
    if evidence:
        out += "\n**Evidence:**\n\n"
        out += "| # | Filters | Observation |\n|---|---|---|\n"
        for i, ev in enumerate(evidence, 1):
            filters = _safe_json(ev.get("filters") or {}, max_chars=60)
            obs = _truncate(ev.get("observation") or "", 180).replace("|", "\\|")
            out += f"| {i} | `{filters}` | {obs} |\n"
    out += "\n"
    return out


# --------------------------- investigation summary -----------------------

def _section_investigation_overview(report: dict) -> str:
    if not report:
        return ""
    out = _h(2, "Investigation Overview")
    out += _kv("Stop reason", report.get("stop_reason"))
    out += _kv("Iterations", report.get("iteration_count"))
    out += _kv("Patterns attempted", len(report.get("patterns_attempted") or []))
    rec = report.get("recommendation")
    if rec:
        out += f"\n> {rec.strip()}\n"
    out += "\n"
    return out


# --------------------------- ReAct trace ---------------------------------

def _section_react_trace(report: dict) -> str:
    log = report.get("investigation_log") or []
    if not log:
        return ""
    out = _h(2, "ReAct Trace")
    for step in log:
        it = step.get("iteration", "?")
        tool = step.get("tool") or "—"
        out += _h(3, f"Iteration {it} — `{tool}`")
        plan = step.get("plan_thought")
        if plan:
            out += f"**Plan:**\n> {plan.strip()}\n\n"
        hyp = step.get("hypothesis_being_tested")
        if hyp:
            out += f"**Hypothesis:** {hyp.strip()}\n\n"
        args = step.get("args") or {}
        if args:
            out += "**Args:** `" + _safe_json(args, 240) + "`\n\n"
        obs = step.get("observation") or {}
        if obs:
            obs_summary = _summarize_observation(obs)
            out += f"**Observation:** {obs_summary}\n\n"
        nt = step.get("next_thought")
        if nt:
            out += f"**Next thought:**\n> {nt.strip()}\n\n"
    return out


def _summarize_observation(obs: dict) -> str:
    """Render an observation as compact inline markdown."""
    if "error" in obs:
        return f"**ERROR** — `{_truncate(obs['error'], 200)}`"
    parts: list[str] = []
    for key in ("precision", "recall", "f1", "hit_count", "total_fraud", "total_flagged"):
        if key in obs:
            parts.append(f"{key}={_num(obs[key], 4) if key in ('precision','recall','f1') else obs[key]}")
    if parts:
        return ", ".join(parts)
    for key in ("count", "total_count", "row_count"):
        if key in obs:
            parts.append(f"{key}={obs[key]}")
    for key in ("total_amount_vnd",):
        if key in obs:
            parts.append(f"{key}={obs[key]:,}")
    sample = obs.get("sample_rows") or obs.get("rows_sample")
    if sample:
        parts.append(f"sample[0]={_safe_json(sample[0], 140)}")
    by_keys = [k for k in obs if k.startswith("by_")]
    if by_keys:
        for bk in by_keys[:3]:
            head = obs.get(bk) or []
            if head:
                parts.append(f"{bk}[0..2]={_safe_json(head[:3], 200)}")
    return " · ".join(parts) if parts else f"`{_safe_json(obs, 240)}`"


# --------------------------- patterns table ------------------------------

def _section_patterns(report: dict) -> str:
    patterns = report.get("patterns_attempted") or []
    if not patterns:
        return ""
    out = _h(2, "Patterns Attempted")
    out += "| # | Status | Description | Precision | Recall | F1 | Action |\n"
    out += "|---|---|---|---|---|---|---|\n"
    for p in patterns:
        m = p.get("metrics") or {}
        desc = _truncate(p.get("description") or "—", 80).replace("|", "\\|")
        out += (
            f"| {p.get('iteration', '?')} "
            f"| {p.get('status', '?')} "
            f"| {desc} "
            f"| {_num(m.get('precision'))} "
            f"| {_num(m.get('recall'))} "
            f"| {_num(m.get('f1'))} "
            f"| {p.get('recommended_action', '—')} |\n"
        )
    out += "\n"
    return out


# --------------------------- final pattern --------------------------------

def _section_final_pattern(report: dict) -> str:
    final = report.get("final_pattern")
    if not final:
        out = _h(2, "Final Pattern")
        out += "_No pattern qualified — no rule recommendation produced._\n\n"
        return out

    out = _h(2, "Final Pattern")
    out += _kv("Description", final.get("description"))
    out += _kv("Status", final.get("status"))
    out += _kv("Recommended action", final.get("recommended_action"))
    m = final.get("metrics") or {}
    if m:
        out += (
            "\n**Metrics:** "
            f"P={_num(m.get('precision'))}  "
            f"R={_num(m.get('recall'))}  "
            f"F1={_num(m.get('f1'))}  "
            f"hits={m.get('hit_count')}/{m.get('total_fraud')}  "
            f"flagged={m.get('total_flagged')}\n"
        )
    sql = final.get("sql_predicate")
    if sql:
        out += "\n**SQL:**\n```sql\n" + sql.strip() + "\n```\n"
    rationale = final.get("rationale")
    if rationale:
        out += f"\n**Rationale:**\n> {rationale.strip()}\n"
    notes = final.get("notes")
    if notes:
        out += f"\n**Notes:** {notes.strip()}\n"
    out += "\n"
    return out


# --------------------------- rule_json ------------------------------------

def _section_policy(rule_json: dict | None) -> str:
    if not rule_json:
        return ""
    out = _h(2, "Policy Suggestion (RuleJSON)")
    out += _kv("rule_name", rule_json.get("rule_name"))
    out += _kv("fraud_type", rule_json.get("fraud_type"))
    out += _kv("status", rule_json.get("status"))
    out += _kv("recommended_action", rule_json.get("recommended_action"))
    out += _kv("emitted_at", rule_json.get("emitted_at"))
    out += "\n```json\n" + json.dumps(rule_json, indent=2, ensure_ascii=False) + "\n```\n"
    return out


# --------------------------- public builders ------------------------------

def build_pretty_report_investigation(state: dict) -> str:
    """Full report — anomaly + ReAct trace + patterns + final pattern + policy."""
    out = _h(1, "Risk Analysis Agent — Investigation Report")
    out += _kv("Run ID", state.get("run_id"))
    out += _kv("Source", state.get("source_type"))
    out += _kv("Emitted at", _now())
    out += "\n---\n\n"

    out += _section_anomaly(state.get("anomaly_decision") or {})
    out += "\n---\n\n"

    report = state.get("investigation_report") or {}
    out += _section_investigation_overview(report)
    out += _section_react_trace(report)
    out += _section_patterns(report)
    out += _section_final_pattern(report)
    out += "\n---\n\n"

    out += _section_policy(state.get("rule_json"))
    return out


def build_pretty_report_no_action(state: dict) -> str:
    """Short report for the no-anomaly branch."""
    out = _h(1, "Risk Analysis Agent — No-Action Report")
    out += _kv("Run ID", state.get("run_id"))
    out += _kv("Source", state.get("source_type"))
    out += _kv("Emitted at", _now())
    out += "\n---\n\n"

    out += _section_anomaly(state.get("anomaly_decision") or {})
    out += "\n---\n\n"

    no_action = state.get("no_action_report") or {}
    if no_action:
        out += _h(2, "Conclusion")
        out += f"> {no_action.get('recommendation', '').strip()}\n\n"
        bw = no_action.get("baseline_window") or {}
        if bw:
            out += _kv("Baseline window", f"{bw.get('start')} → {bw.get('end')}")
        out += "\n"
    return out
