"""CLI entry point — runs the agent end-to-end with a sample email.

    python -m app.main
"""
from __future__ import annotations

import uuid

from app.graph import build_graph
from app.state import ThresholdConfig


SAMPLE_EMAIL = """\
From: fraud-ops@company.vn
Subject: [URGENT] Suspicious high-value night transactions

Team, we've flagged 3 cases (c001, c002, c003) of high-value transactions
occurring late at night from devices that appear in multiple accounts.
Please analyze the last 90 days and propose a detection rule.
"""


def run() -> None:
    app = build_graph()
    run_id = str(uuid.uuid4())[:8]
    config = {"configurable": {"thread_id": run_id}}

    initial = {
        "run_id": run_id,
        "source_type": "email",
        "raw_input": SAMPLE_EMAIL,
        "threshold_config": ThresholdConfig(
            min_precision=0.80, min_recall=0.60, max_iterations=6
        ).model_dump(),
    }

    print(f"\n>>> Starting run {run_id}\n")

    for event in app.stream(initial, config):
        for node_name, update in event.items():
            _print_step(node_name, update)

    snapshot = app.get_state(config)
    print(f"\n>>> PAUSED at: {snapshot.next}  (waiting for strategist)\n")

    report = snapshot.values["final_report"]
    print(f"    Pattern : {report['pattern']['description']}")
    print(
        f"    Metrics : precision={report['metrics']['precision']} "
        f"recall={report['metrics']['recall']} f1={report['metrics']['f1']}"
    )
    print(f"    Iterations: {report['iteration_count']}")

    print("\n>>> Strategist APPROVES -> resuming\n")
    app.update_state(
        config, {"review_decision": "approve", "approved_by": "minhtri"}
    )

    for event in app.stream(None, config):
        for node_name, update in event.items():
            _print_step(node_name, update)

    final = app.get_state(config).values["final_report"]
    rule = app.get_state(config).values.get("rule_json")
    print("\n>>> DONE")
    print(f"    {final['recommendation']}")
    print(f"    Rule SQL: {final['sql']}")
    if rule:
        print(f"    RuleJSON.rule_name: {rule['rule_name']}")
    print()


def _print_step(node_name: str, update: dict) -> None:
    keys = list(update.keys()) if isinstance(update, dict) else []
    extra = ""
    if "metrics" in keys:
        m = update["metrics"]
        extra = f"  -> precision={m['precision']} recall={m['recall']}"
    if "route" in keys:
        extra = f"  -> route={update['route']}"
    print(f"  [{node_name}]{extra}")


if __name__ == "__main__":
    run()
