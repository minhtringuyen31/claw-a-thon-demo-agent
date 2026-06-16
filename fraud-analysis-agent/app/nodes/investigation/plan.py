"""plan_node — LLM picks the next tool + args + hypothesis under test.

Output (strict JSON) becomes `current_step`. `act_node` reads it and runs
the tool; `observe_node` reads the observation and decides next.
"""
from __future__ import annotations

import json
from typing import Any

from app.llm import get_llm
from app.state import AgentState
from app.nodes.investigation.tools import TOOL_REGISTRY_SPEC


_ROLE = (
    "You are a senior fraud-risk strategist running a ReAct investigation "
    "loop. Each iteration you choose ONE tool call to advance toward a "
    "candidate fraud detection rule. Use the knowledge base (KB) for the "
    "what (rules, thresholds, acceptance criteria) and the skill guide for "
    "the how (tool-selection priorities, stop conditions)."
)


_OUTPUT_SCHEMA = (
    "Respond with ONLY JSON in this exact shape:\n"
    "{\n"
    '  "plan_thought":            string,   // 2-4 Vietnamese sentences: '
    "what you observed last iter, what you want to test now, why this tool\n"
    '  "hypothesis_being_tested": string | null,   // short label '
    "(e.g. \"international card + amount >= 5M is a CF signal\")\n"
    '  "tool":                    "query_with_filters"|"aggregate"'
    "|\"compute_metrics\"|\"raw_sql\",\n"
    '  "args":                    { ... }    // args for the chosen tool\n'
    "}\n"
    "No markdown, no commentary."
)


def _trim_log(log: list[dict], n: int = 3) -> list[dict]:
    """Keep only the last N entries to control prompt size."""
    return log[-n:]


def _trim_patterns(patterns: list[dict], n: int = 8) -> list[dict]:
    """Keep most-recent + best-by-F1 patterns, capped."""
    if len(patterns) <= n:
        return patterns
    scored = sorted(
        patterns,
        key=lambda p: (p.get("metrics") or {}).get("f1", 0),
        reverse=True,
    )
    return scored[:n]


def _build_system(state: AgentState) -> str:
    return "\n\n".join([
        _ROLE,
        "KNOWLEDGE BASE:\n" + state.get("investigation_kb_body", ""),
        "SKILL GUIDE:\n" + state.get("investigation_skill_body", ""),
        TOOL_REGISTRY_SPEC,
        _OUTPUT_SCHEMA,
    ])


def _build_user(state: AgentState) -> str:
    iteration = state.get("investigation_iteration", 0) + 1
    decision = state.get("anomaly_decision") or {}
    slices = state.get("investigation_slices") or {}
    threshold_cfg = state.get("threshold_config") or {}

    context = {
        "iteration": iteration,
        "anomaly_summary": {
            "is_anomalous": decision.get("is_anomalous"),
            "reasoning": decision.get("reasoning"),
            "evidence": decision.get("evidence", []),
        },
        "investigation_slices_overview": {
            k: {
                "filters": v.get("filters"),
                "observation": v.get("observation"),
                "pom_count": v.get("pom", {}).get("count"),
                "trans_count": v.get("trans", {}).get("count"),
            }
            for k, v in slices.items()
        },
        "data_schema_tables": list((state.get("data_schema") or {}).keys()),
        "trans_log_columns": [
            c["column"]
            for c in (state.get("data_schema") or {}).get("trans_log", [])
        ],
        "investigation_window": state.get("investigation_window"),
        "current_hypothesis": state.get("current_hypothesis"),
        "threshold_target": {
            "min_precision": threshold_cfg.get("min_precision"),
            "min_recall": threshold_cfg.get("min_recall"),
            "max_iterations": threshold_cfg.get("max_iterations"),
        },
        "patterns_attempted": _trim_patterns(state.get("patterns_attempted") or []),
        "recent_log": _trim_log(state.get("investigation_log") or []),
    }

    return (
        "CURRENT INVESTIGATION CONTEXT (JSON):\n"
        + json.dumps(context, ensure_ascii=False, indent=2, default=str)
    )


def plan_node(state: AgentState) -> dict:
    llm = get_llm(role="plan", thinking=True)
    raw = llm.complete_json(_build_system(state), _build_user(state))

    iteration = state.get("investigation_iteration", 0) + 1
    step: dict[str, Any] = {
        "iteration": iteration,
        "plan_thought": str(raw.get("plan_thought", "")),
        "tool": str(raw.get("tool", "")),
        "args": raw.get("args", {}) or {},
        "hypothesis_being_tested": raw.get("hypothesis_being_tested"),
        "observation": {},
        "next_thought": "",
    }
    return {"current_step": step}
