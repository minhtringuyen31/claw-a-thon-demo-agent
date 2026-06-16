"""Scenario tests for the Risk Analysis Agent.

Each scenario:
  - sends a different (source, body, threshold) into the graph
  - prints a concise per-node trace
  - asserts expectations on the final state

Run:
    uv run python scripts/test_scenarios.py [scenario_name]

Without an arg → runs all scenarios sequentially.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Callable

os.environ.setdefault("CHECKPOINTER_BACKEND", "memory")

from app.graph import build_graph
from app.state import ThresholdConfig


# ---------- shared fraud-ops email body (planted CF scenario) -----------

CF_EMAIL = """\
From: fraud-ops@company.vn
Subject: [URGENT] CF chargeback wave on international cards — please profile

Team, we've flagged ~50 CF cases in the past week, all on international
cards from newly-onboarded accounts. Please analyse and propose a
detection rule we can deploy.

| appID | transID | reqDate | userChargeAmount | bankType | bankCode | pmcID | integratedChannel | fraud_type | appName |
|---|---|---|---|---|---|---|---|---|---|
| 5210 | 260608F0001000 | 2026-06-08 02:14:00 | 12000000 | international | ZPCC | 36 | CREDIT CARD | CF | Zalo Pay |
| 149  | 260609F0002001 | 2026-06-09 03:45:00 |  8000000 | international | ZPCC | 36 | CREDIT CARD | CF | Mobile Payment |
| 356  | 260610F0003002 | 2026-06-10 23:20:00 | 20000000 | international | ZPCC | 36 | CREDIT CARD | CF | TIKI.VN.GW |
| 4012 | 260611F0004003 | 2026-06-11 01:10:00 | 30000000 | international | ZPCC | 36 | CREDIT CARD | CF | Shopee |
"""

CF_POSTMORTEM = """\
Incident: INC-2026-0613-CF
Summary: Chargeback wave on international cards via map-card abuse
Record:
{
  "incident_id": "INC-2026-0613-CF",
  "fraud_type": "CF",
  "loss_vnd": 3680000000,
  "window": "tu?n W23 / 2026",
  "vector": "Newly onboarded account -> map international card -> high-value transactions before bank can react",
  "cases": [
    {"appID": 5210, "transID": "260608F0001000", "reqDate": "2026-06-08 02:14:00", "userChargeAmount": 12000000, "bankType": "international", "bankCode": "ZPCC", "pmcID": 36, "integratedChannel": "CREDIT CARD", "fraud_type": "CF", "appName": "Zalo Pay"},
    {"appID": 149, "transID": "260609F0002001", "reqDate": "2026-06-09 03:45:00", "userChargeAmount": 8000000, "bankType": "international", "bankCode": "ZPCC", "pmcID": 36, "integratedChannel": "CREDIT CARD", "fraud_type": "CF", "appName": "Mobile Payment"},
    {"appID": 356, "transID": "260610F0003002", "reqDate": "2026-06-10 23:20:00", "userChargeAmount": 20000000, "bankType": "international", "bankCode": "ZPCC", "pmcID": 36, "integratedChannel": "CREDIT CARD", "fraud_type": "CF", "appName": "TIKI.VN.GW"},
    {"appID": 4012, "transID": "260611F0004003", "reqDate": "2026-06-11 01:10:00", "userChargeAmount": 30000000, "bankType": "international", "bankCode": "ZPCC", "pmcID": 36, "integratedChannel": "CREDIT CARD", "fraud_type": "CF", "appName": "Shopee"}
  ]
}
"""


# ---------- scenarios ---------------------------------------------------

@dataclass
class Scenario:
    name: str
    description: str
    source_type: str            # "email" | "postmortem"
    raw_input: str
    threshold: ThresholdConfig
    check: Callable[[dict], list[str]]   # returns list of pass/fail messages


def _check_strict(state: dict) -> list[str]:
    report = state.get("investigation_report") or {}
    final = report.get("final_pattern") or {}
    sql = (final.get("sql_predicate") or "").lower()
    m = (final.get("metrics") or {})
    out = []
    out.append(
        f"  precision >= 0.95     : "
        + ("OK" if m.get("precision", 0) >= 0.95 else f"FAIL ({m.get('precision')})")
    )
    out.append(
        f"  sql touches user_profile : "
        + ("OK" if "user_profile" in sql else "FAIL")
    )
    out.append(
        f"  sql touches user_journey : "
        + ("OK" if "user_journey" in sql else "WARN — wanted journey escalation")
    )
    return out


def _check_permissive(state: dict) -> list[str]:
    report = state.get("investigation_report") or {}
    final = report.get("final_pattern") or {}
    m = (final.get("metrics") or {})
    out = []
    out.append(
        f"  precision >= 0.70     : "
        + ("OK" if m.get("precision", 0) >= 0.70 else f"FAIL ({m.get('precision')})")
    )
    out.append(
        f"  recall    >= 0.50     : "
        + ("OK" if m.get("recall", 0) >= 0.50 else f"FAIL ({m.get('recall')})")
    )
    out.append(
        f"  iterations <= 6       : "
        + ("OK" if report.get("iteration_count", 99) <= 6 else f"WARN ({report.get('iteration_count')})")
    )
    return out


def _check_postmortem(state: dict) -> list[str]:
    fc = state.get("fraud_context") or {}
    out = []
    out.append(
        f"  source_type           : "
        + ("OK" if (state.get("source_type") or "") == "postmortem" else "FAIL")
    )
    out.append(
        f"  reported_cases parsed : "
        + ("OK" if len(fc.get("reported_cases") or []) >= 3 else "FAIL")
    )
    report = state.get("investigation_report") or {}
    final = report.get("final_pattern") or {}
    m = (final.get("metrics") or {})
    out.append(
        f"  some pattern found    : "
        + ("OK" if m.get("precision", 0) > 0 else "FAIL")
    )
    return out


SCENARIOS = [
    Scenario(
        name="strict",
        description="Strict threshold (P>=0.95, R>=0.05) — force Layer 3 journey escalation",
        source_type="email",
        raw_input=CF_EMAIL,
        threshold=ThresholdConfig(min_precision=0.95, min_recall=0.05, max_iterations=12),
        check=_check_strict,
    ),
    Scenario(
        name="permissive",
        description="Permissive threshold (P>=0.70, R>=0.50) — Layer 1 or Layer 2 should converge fast",
        source_type="email",
        raw_input=CF_EMAIL,
        threshold=ThresholdConfig(min_precision=0.70, min_recall=0.50, max_iterations=8),
        check=_check_permissive,
    ),
    Scenario(
        name="postmortem",
        description="Postmortem source — verify ingest of JSON-style record + agent flow",
        source_type="postmortem",
        raw_input=CF_POSTMORTEM,
        threshold=ThresholdConfig(min_precision=0.90, min_recall=0.20, max_iterations=10),
        check=_check_postmortem,
    ),
]


# ---------- runner ------------------------------------------------------

def run_scenario(s: Scenario) -> None:
    print("=" * 80)
    print(f"SCENARIO: {s.name}")
    print(f"  {s.description}")
    print(f"  source_type   = {s.source_type}")
    print(f"  threshold     = P>={s.threshold.min_precision} R>={s.threshold.min_recall} "
          f"max_iter={s.threshold.max_iterations}")
    print("=" * 80)

    graph = build_graph()
    run_id = f"{s.name}-{str(uuid.uuid4())[:6]}"
    cfg = {"configurable": {"thread_id": run_id}}
    initial = {
        "run_id": run_id,
        "source_type": s.source_type,
        "raw_input": s.raw_input,
        "threshold_config": s.threshold.model_dump(),
    }

    t0 = time.time()
    for event in graph.stream(initial, cfg, stream_mode="updates"):
        for node, update in event.items():
            elapsed = time.time() - t0
            _print_short(node, update, elapsed)
    duration = time.time() - t0
    print(f"\n  total time : {duration:.1f}s")

    snap = graph.get_state(cfg).values
    snap["source_type"] = s.source_type   # make available to checks

    report = snap.get("investigation_report") or {}
    final = report.get("final_pattern") or {}
    no_action = snap.get("no_action_report")

    print()
    print("  --- final summary ---")
    if no_action:
        print(f"  no_action     : {no_action.get('recommendation')}")
    if report:
        print(f"  stop_reason   : {report.get('stop_reason')}")
        print(f"  iterations    : {report.get('iteration_count')}")
        print(f"  patterns      : {len(report.get('patterns_attempted') or [])}")
    if final:
        m = final.get("metrics") or {}
        print(f"  final_pattern : {final.get('description')}")
        print(f"  metrics       : P={m.get('precision')} R={m.get('recall')} F1={m.get('f1')}")
        print(f"  action        : {final.get('recommended_action')}")
    rj = snap.get("rule_json") or {}
    if rj:
        print(f"  rule_json     : status={rj.get('status')} action={rj.get('recommended_action')}")

    print()
    print("  --- assertions ---")
    for line in s.check(snap):
        print(line)
    print()


def _print_short(node: str, update: dict | None, elapsed: float) -> None:
    if not isinstance(update, dict):
        return
    extras: list[str] = []
    if "anomaly_decision" in update:
        d = update["anomaly_decision"] or {}
        extras.append(f"anomalous={d.get('is_anomalous')}")
    if "current_step" in update and update["current_step"]:
        cs = update["current_step"]
        if cs.get("tool"):
            extras.append(f"tool={cs.get('tool')}")
        obs = cs.get("observation") or {}
        if "precision" in obs:
            extras.append(
                f"P={obs.get('precision')} R={obs.get('recall')} F1={obs.get('f1')}"
            )
        elif "error" in obs:
            extras.append(f"ERR={obs['error'][:40]}")
    if "patterns_attempted" in update:
        extras.append(f"patterns={len(update['patterns_attempted'] or [])}")
    if "investigation_stop_reason" in update:
        extras.append(f"stop={update['investigation_stop_reason']}")
    if "investigation_report" in update:
        r = update["investigation_report"] or {}
        extras.append(f"stop_reason={r.get('stop_reason')}")
    if "rule_json" in update:
        rj = update["rule_json"] or {}
        extras.append(f"rule={rj.get('status')}/{rj.get('recommended_action')}")
    print(f"  [{elapsed:6.1f}s] [{node}]  " + "  ".join(extras))


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else None
    scenarios = [s for s in SCENARIOS if target is None or s.name == target]
    if not scenarios:
        print(f"No scenario matching {target!r}. Available: {[s.name for s in SCENARIOS]}")
        sys.exit(1)

    for s in scenarios:
        run_scenario(s)
    print("=" * 80)
    print(f"DONE — ran {len(scenarios)} scenario(s)")


if __name__ == "__main__":
    main()
