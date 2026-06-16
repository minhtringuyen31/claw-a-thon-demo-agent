"""End-to-end test of the Risk Analysis Agent.

Streams the graph from a sample fraud-ops email and prints each node fire
+ key state changes. Uses MemorySaver (no checkpoint persistence) so the
run is isolated.

    uv run python scripts/e2e_test.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

os.environ.setdefault("CHECKPOINTER_BACKEND", "memory")

from app.graph import build_graph
from app.state import ThresholdConfig


SAMPLE_EMAIL = """\
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


def main() -> None:
    graph = build_graph()
    run_id = str(uuid.uuid4())[:8]
    cfg = {"configurable": {"thread_id": run_id}}
    initial = {
        "run_id": run_id,
        "source_type": "email",
        "raw_input": SAMPLE_EMAIL,
        "threshold_config": ThresholdConfig(
            min_precision=0.90,
            min_recall=0.20,
            max_iterations=12,
        ).model_dump(),
    }

    print(f"\n>>> Starting run {run_id}\n")
    t0 = time.time()
    last_state: dict = {}
    for event in graph.stream(initial, cfg, stream_mode="updates"):
        for node, update in event.items():
            elapsed = time.time() - t0
            keys = list(update.keys()) if isinstance(update, dict) else []
            _print_step(node, update, elapsed)
            last_state.update(update)
    print(f"\n>>> Finished in {time.time() - t0:.1f}s\n")

    snap = graph.get_state(cfg).values
    _print_summary(snap)

    pretty = snap.get("pretty_report")
    if pretty:
        print()
        print("#" * 80)
        print("# PRETTY REPORT (markdown)")
        print("#" * 80)
        print(pretty)


def _print_step(node: str, update: dict | None, elapsed: float) -> None:
    if not isinstance(update, dict):
        print(f"  [{elapsed:6.1f}s] [{node}]  (no update)")
        return
    extras: list[str] = []
    if "anomaly_decision" in update:
        d = update["anomaly_decision"] or {}
        extras.append(f"is_anomalous={d.get('is_anomalous')} conf={d.get('confidence')}")
    if "investigation_window" in update:
        w = update["investigation_window"] or {}
        extras.append(f"window {w.get('start')}→{w.get('end')}")
    if "investigation_slices" in update:
        n = len(update["investigation_slices"] or {})
        extras.append(f"{n} slice(s)")
    if "current_step" in update and update["current_step"]:
        cs = update["current_step"]
        if cs.get("tool"):
            extras.append(f"tool={cs.get('tool')}")
        if cs.get("observation"):
            obs = cs["observation"]
            if "precision" in obs:
                extras.append(
                    f"P={obs.get('precision')} R={obs.get('recall')} F1={obs.get('f1')}"
                )
            elif "count" in obs:
                extras.append(f"count={obs.get('count')}")
            elif "total_count" in obs:
                extras.append(f"total={obs.get('total_count')}")
            elif "error" in obs:
                extras.append(f"ERR={obs['error'][:50]}")
    if "patterns_attempted" in update:
        extras.append(f"patterns={len(update['patterns_attempted'] or [])}")
    if "investigation_iteration" in update:
        extras.append(f"iter={update['investigation_iteration']}")
    if "investigation_stop_reason" in update:
        extras.append(f"stop={update['investigation_stop_reason']}")
    if "investigation_report" in update:
        r = update["investigation_report"] or {}
        extras.append(f"stop_reason={r.get('stop_reason')} final={'YES' if r.get('final_pattern') else 'NO'}")
    if "rule_json" in update:
        rj = update["rule_json"] or {}
        extras.append(f"rule_status={rj.get('status')} action={rj.get('recommended_action')}")

    suffix = "  ".join(extras)
    print(f"  [{elapsed:6.1f}s] [{node}]  {suffix}")


def _print_summary(snap: dict) -> None:
    decision = snap.get("anomaly_decision") or {}
    print("=" * 80)
    print("ANOMALY DECISION")
    print(f"  is_anomalous : {decision.get('is_anomalous')}")
    print(f"  confidence   : {decision.get('confidence')}")
    print(f"  reasoning    : {decision.get('reasoning')}")
    for ev in decision.get("evidence") or []:
        print(f"  evidence     : filters={ev.get('filters')}  obs={ev.get('observation')}")
    print()

    report = snap.get("investigation_report") or {}
    if report:
        print("=" * 80)
        print("INVESTIGATION REPORT")
        print(f"  stop_reason       : {report.get('stop_reason')}")
        print(f"  iterations        : {report.get('iteration_count')}")
        print(f"  patterns_attempted: {len(report.get('patterns_attempted') or [])}")
        print(f"  recommendation    : {report.get('recommendation')}")
        print()

        final = report.get("final_pattern")
        if final:
            print("  FINAL PATTERN:")
            print(f"    description : {final.get('description')}")
            print(f"    sql         : {final.get('sql_predicate')}")
            m = final.get("metrics") or {}
            print(
                f"    metrics     : P={m.get('precision')} "
                f"R={m.get('recall')} F1={m.get('f1')} "
                f"hits={m.get('hit_count')}/{m.get('total_fraud')} "
                f"flagged={m.get('total_flagged')}"
            )
            print(f"    action      : {final.get('recommended_action')}")
            print()

        print("  ALL PATTERNS ATTEMPTED:")
        for p in report.get("patterns_attempted") or []:
            m = p.get("metrics") or {}
            mstr = (
                f"P={m.get('precision')} R={m.get('recall')} F1={m.get('f1')}"
                if m else "no metrics"
            )
            print(
                f"    #{p.get('iteration')} [{p.get('status')}] "
                f"{p.get('description')}  →  {mstr}  "
                f"action={p.get('recommended_action')}"
            )
        print()

    rj = snap.get("rule_json")
    if rj:
        print("=" * 80)
        print("RULE JSON (policy suggestion)")
        print(json.dumps(rj, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
