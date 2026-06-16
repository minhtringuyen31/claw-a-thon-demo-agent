"""observe_node — LLM analyzes the observation and decides next move.

Outputs:
  - `next_thought`         : analysis of what the observation tells us
  - `updated_hypothesis`   : refined hypothesis (or null)
  - `new_pattern_attempt`  : record a candidate / passed / failed pattern
                             (populated mostly after compute_metrics calls)
  - `stop`                 : true when the agent self-declares done

Side effects on state:
  - append the completed step to `investigation_log`
  - replace `patterns_attempted` with the appended-version
  - increment `investigation_iteration`
  - clear `current_step`
  - set `investigation_stop_reason="self_declared"` when stop=true
"""
from __future__ import annotations

import json
from typing import Any

from app.llm import get_llm
from app.state import AgentState


_ROLE = (
    "You are the same senior fraud-risk strategist. The previous turn "
    "you decided to call a tool; now you have the observation. Reason "
    "over it using the KB rules / acceptance criteria and decide what "
    "to do next."
)


_OUTPUT_SCHEMA = (
    "Respond with ONLY JSON in this exact shape:\n"
    "{\n"
    '  "next_thought":        string,   // 2-4 Vietnamese sentences\n'
    '  "updated_hypothesis":  string | null,\n'
    '  "new_pattern_attempt": null | {\n'
    '    "description":         string,\n'
    '    "sql_predicate":       string,    // copy from args.sql_predicate when tool=compute_metrics\n'
    '    "signal_columns":      [string, ...],\n'
    '    "rationale":           string,\n'
    '    "metrics": {                  // REQUIRED when tool=compute_metrics this iteration\n'
    '      "precision":     number,    // copy verbatim from observation.precision\n'
    '      "recall":        number,    // copy verbatim from observation.recall\n'
    '      "f1":            number,    // copy verbatim from observation.f1\n'
    '      "hit_count":     number,    // copy verbatim from observation.hit_count\n'
    '      "total_fraud":   number,    // copy verbatim from observation.total_fraud\n'
    '      "total_flagged": number     // copy verbatim from observation.total_flagged\n'
    "    },\n"
    '    "recommended_action":  "monitor"|"challenge"|"reject"|"blacklist"'
    "|\"whitelist_exclusion\"|\"none\",\n"
    '    "status":              "candidate"|"passed"|"failed"|"abandoned",\n'
    '    "notes":               string\n'
    "  },\n"
    '  "stop":                boolean   // true when you self-declare done\n'
    "}\n\n"
    "RULES:\n"
    "- Only record `new_pattern_attempt` after a `compute_metrics` call "
    "(skip for exploratory aggregate/query/raw_sql calls; set null).\n"
    "- When recording, you MUST copy `metrics` verbatim from the observation. "
    "Do NOT set `metrics` to null when the observation contains them.\n"
    "- `sql_predicate` MUST be the exact SQL you passed as `args.sql_predicate`.\n"
    "- No markdown, no commentary."
)


def _build_system(state: AgentState) -> str:
    return "\n\n".join([
        _ROLE,
        "KNOWLEDGE BASE:\n" + state.get("investigation_kb_body", ""),
        "SKILL GUIDE:\n" + state.get("investigation_skill_body", ""),
        _OUTPUT_SCHEMA,
    ])


def _build_user(state: AgentState) -> str:
    step = state.get("current_step") or {}
    threshold_cfg = state.get("threshold_config") or {}
    payload = {
        "iteration": step.get("iteration"),
        "plan_thought": step.get("plan_thought"),
        "tool": step.get("tool"),
        "args": step.get("args"),
        "hypothesis_being_tested": step.get("hypothesis_being_tested"),
        "observation": step.get("observation"),
        "threshold_target": {
            "min_precision": threshold_cfg.get("min_precision"),
            "min_recall": threshold_cfg.get("min_recall"),
        },
        "patterns_attempted_so_far": state.get("patterns_attempted") or [],
    }
    return (
        "OBSERVATION CONTEXT (JSON):\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )


def _classify_status(metrics: dict | None, cfg: dict) -> str:
    if not metrics:
        return "candidate"
    p = metrics.get("precision", 0)
    r = metrics.get("recall", 0)
    if p >= cfg.get("min_precision", 0.9) and r >= cfg.get("min_recall", 0.2):
        return "passed"
    if p < 0.7 and r < 0.2:
        return "failed"
    return "candidate"


def observe_node(state: AgentState) -> dict:
    llm = get_llm(role="observe", thinking=True)
    raw: dict[str, Any] = llm.complete_json(_build_system(state), _build_user(state))

    step = dict(state.get("current_step") or {})
    step["next_thought"] = str(raw.get("next_thought", ""))

    update: dict[str, Any] = {
        "investigation_log": [step],
        "current_step": None,
        "current_hypothesis": raw.get("updated_hypothesis") or state.get(
            "current_hypothesis"
        ),
        "investigation_iteration": (
            state.get("investigation_iteration", 0) + 1
        ),
    }

    cfg = state.get("threshold_config") or {}
    step_tool = step.get("tool")
    obs = step.get("observation") or {}
    args = step.get("args") or {}

    new_attempt = raw.get("new_pattern_attempt")

    # ---- Layer 3 defense: AUTO-RECORD whenever compute_metrics succeeded ----
    # `compute_metrics` is the only ground truth for precision/recall/F1.
    # If the LLM forgot to record (set new_pattern_attempt=null) or returned
    # an empty dict, synthesize one from the observation so finalize_investigation
    # has the metric to score against.
    if (
        step_tool == "compute_metrics"
        and "precision" in obs   # tool succeeded (not an error result)
        and (not isinstance(new_attempt, dict) or not new_attempt)
    ):
        new_attempt = {
            "description": (
                raw.get("updated_hypothesis")
                or step.get("hypothesis_being_tested")
                or state.get("current_hypothesis")
                or f"auto-recorded compute_metrics iter {step.get('iteration')}"
            ),
            "sql_predicate": args.get("sql_predicate", ""),
            "signal_columns": [],
            "rationale": str(raw.get("next_thought", ""))[:300],
            "metrics": None,            # filled by Layer 2 just below
            "recommended_action": "none",
            "status": "",                # filled by deterministic classifier below
            "notes": "Auto-recorded: LLM did not record this compute_metrics call.",
        }

    if isinstance(new_attempt, dict) and new_attempt:
        # Layer 2: defensive fill for metrics + sql_predicate when the LLM
        # returned the structure but dropped fields.
        if step_tool == "compute_metrics":
            if not new_attempt.get("metrics") and "precision" in obs:
                new_attempt["metrics"] = {
                    k: obs.get(k, 0)
                    for k in (
                        "precision", "recall", "f1",
                        "hit_count", "total_fraud", "total_flagged",
                    )
                }
            if not new_attempt.get("sql_predicate") and args.get("sql_predicate"):
                new_attempt["sql_predicate"] = args["sql_predicate"]

        # Status is ALWAYS deterministic — ignore LLM-set value. The LLM tends
        # to mark borderline rules as "passed" when they shouldn't be.
        new_attempt["status"] = _classify_status(
            new_attempt.get("metrics"), cfg
        )
        new_attempt.setdefault("iteration", step.get("iteration"))
        prev = list(state.get("patterns_attempted") or [])
        update["patterns_attempted"] = prev + [new_attempt]

    if bool(raw.get("stop")):
        update["investigation_stop_reason"] = "self_declared"

    return update
