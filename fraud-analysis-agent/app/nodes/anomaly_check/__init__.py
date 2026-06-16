"""anomaly_check_node — detect fraud trend anomalies across multiple time windows.

Queries pom_acr for 8 comparison windows (current_week, prev_week,
current_month, prev_month, today, yesterday, rolling_7d, rolling_7d_prev,
avg_4w), aggregates count + amount per dimension, then asks the LLM to apply
the trigger conditions defined in strategy.md.

Routes:
  is_anomalous = True  → fetch_data → investigation pipeline
  is_anomalous = False → action_output → END
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.nodes.anomaly_check.baseline import fetch_all_windows
from app.shared.historical import aggregate_by
from app.llm import get_llm
from app.state import AgentState, AnomalyDecision


_STRATEGY_PATH = Path(__file__).parent / "strategy.md"
_DEFAULT_DIMENSIONS = ["appID", "integratedChannel", "bankType", "bankCode", "is_kyc"]


# ---------------------------------------------------------------------------
# Strategy file reader
# ---------------------------------------------------------------------------

def _read_strategy() -> tuple[list[str], str]:
    """Return (dimensions, strategy_body). Falls back to defaults if missing."""
    if not _STRATEGY_PATH.exists():
        return _DEFAULT_DIMENSIONS, "(No strategy file — use general heuristics.)"

    text = _STRATEGY_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    dims = _DEFAULT_DIMENSIONS
    body = text.strip()

    if lines and lines[0].strip() == "---":
        end = next(
            (i for i in range(1, len(lines)) if lines[i].strip() == "---"),
            None,
        )
        if end is not None:
            fm = "\n".join(lines[1:end])
            body = "\n".join(lines[end + 1:]).strip()
            m = re.search(r"dimensions\s*:\s*\[([^\]]+)\]", fm)
            if m:
                parsed = [s.strip() for s in m.group(1).split(",") if s.strip()]
                if parsed:
                    dims = parsed

    return dims, body


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _period_summary(df: pd.DataFrame, label: str, dimensions: list[str]) -> dict:
    """Build the per-period summary dict passed to the LLM."""
    if df.empty:
        return {
            "label": label,
            "total_amount_vnd": 0,
            "total_count": 0,
            **{f"by_{dim}": [] for dim in dimensions},
        }
    agg = aggregate_by(df, dimensions)
    return {
        "label": label,
        "total_amount_vnd": int(df["userChargeAmount"].sum()),
        "total_count": int(len(df)),
        **{f"by_{dim}": agg.get(dim, []) for dim in dimensions},
    }


def _avg_4w_summary(df_4w: pd.DataFrame, label: str, dimensions: list[str]) -> dict:
    """Divide 4-week totals by 4 to get the per-week average."""
    s = _period_summary(df_4w, label, dimensions)
    s["total_amount_vnd"] = s["total_amount_vnd"] // 4
    s["total_count"] = s["total_count"] // 4
    for dim in dimensions:
        key = f"by_{dim}"
        s[key] = [
            {**item, "amount_vnd": item["amount_vnd"] // 4, "count": item["count"] // 4}
            for item in s.get(key, [])
        ]
    return s


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_ROLE = (
    "You are a fraud risk analyst at a Vietnamese fintech payment platform. "
    "Your task is to determine whether fraud in the current period is anomalous "
    "compared to historical baselines, and if so, identify which dimension is the "
    "root cause."
)

_SCHEMA = (
    "Return ONLY JSON with this exact shape:\n"
    "{\n"
    '  "is_anomalous": boolean,\n'
    '  "confidence":   number (0.0..1.0),\n'
    '  "reasoning":    string,  // 3-5 Vietnamese sentences explaining which triggers fired\n'
    '  "evidence": [\n'
    "    {\n"
    '      "filters":     { <column>: <value> },  // dimension that caused the trigger\n'
    '      "observation": string                   // specific numbers + trigger rule cited\n'
    "    }, ...\n"
    "  ]\n"
    "}\n"
    "No markdown, no commentary. Always include >= 2 evidence items."
)


def _build_system(strategy_body: str) -> str:
    return "\n\n".join([_ROLE, "STRATEGY:\n" + strategy_body, _SCHEMA])


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def anomaly_check_node(state: AgentState) -> dict:
    fraud_context = state.get("fraud_context") or {}
    dimensions, strategy_body = _read_strategy()

    # 1. Query all comparison windows from pom_acr
    now = datetime.utcnow()
    dfs, windows = fetch_all_windows(now)

    # 2. Build per-period summaries
    periods = {
        "current_week":    _period_summary(dfs["current_week"],    windows["current_week"]["label"],    dimensions),
        "prev_week":       _period_summary(dfs["prev_week"],       windows["prev_week"]["label"],       dimensions),
        "current_month":   _period_summary(dfs["current_month"],   windows["current_month"]["label"],   dimensions),
        "prev_month":      _period_summary(dfs["prev_month"],      windows["prev_month"]["label"],      dimensions),
        "today":           _period_summary(dfs["today"],           windows["today"]["label"],           dimensions),
        "yesterday":       _period_summary(dfs["yesterday"],       windows["yesterday"]["label"],       dimensions),
        "rolling_7d":      _period_summary(dfs["rolling_7d"],      windows["rolling_7d"]["label"],      dimensions),
        "rolling_7d_prev": _period_summary(dfs["rolling_7d_prev"], windows["rolling_7d_prev"]["label"], dimensions),
        "avg_4w":          _avg_4w_summary(dfs["avg_4w_window"],   windows["avg_4w_window"]["label"],   dimensions),
    }

    # 3. LLM applies trigger rules from strategy
    llm = get_llm(role="anomaly", thinking=True)
    user = (
        "report_context:\n"
        + json.dumps(
            {
                "severity": fraud_context.get("severity"),
                "raw_summary": fraud_context.get("raw_summary"),
                "reported_cases_count": len(fraud_context.get("reported_cases", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nperiods:\n"
        + json.dumps(periods, ensure_ascii=False, indent=2)
    )

    decision = AnomalyDecision(**llm.complete_json(_build_system(strategy_body), user))

    # Keep baseline_window / baseline_summary for backwards-compat with action_output_node
    return {
        "baseline_window": {"start": windows["prev_week"]["start"], "end": windows["prev_week"]["end"], "column": "reqDate"},
        "baseline_summary": periods["prev_week"],
        "reported_summary": periods["current_week"],
        "anomaly_decision": decision.model_dump(mode="json"),
    }


def anomaly_route(state: AgentState) -> str:
    decision = state.get("anomaly_decision") or {}
    return "anomalous" if decision.get("is_anomalous") else "normal"
