"""Assemble the LangGraph StateGraph + checkpointer.

Topology:

  START → ingest → anomaly_check
  anomaly_check --normal--→     action_output → END
  anomaly_check --anomalous--→  fetch_data → investigation_init → plan
                                                                    ↓
                                                                   act
                                                                    ↓
                                                                  observe
                                                                    ↓
                                                       investigation_route
                                                                    │
                          ┌──── continue ──→ plan (loop) ───────────┘
                          │
                          └──── converged | self_declared | max_iter | no_pattern
                                    ↓
                          finalize_investigation
                                    ↓
                          policy_output → END

No human-review interrupt — the run completes directly. The final output
is `investigation_report` (full ReAct trace + patterns_attempted +
final_pattern) plus `rule_json` (policy suggestion, status=`suggested`
when a pattern was found, `no_action` otherwise).
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import ExitStack

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app import nodes
from app.state import AgentState


def _build_checkpointer():
    backend = os.environ.get("CHECKPOINTER_BACKEND", "sqlite").lower()
    if backend == "memory":
        return MemorySaver(), None
    if backend == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver
        path = os.environ.get("SQLITE_CHECKPOINT_PATH", "checkpoints.db")
        conn = sqlite3.connect(path, check_same_thread=False)
        return SqliteSaver(conn), conn
    if backend == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver
        url = os.environ.get("POSTGRES_URL")
        if not url:
            raise RuntimeError(
                "CHECKPOINTER_BACKEND=postgres requires POSTGRES_URL"
            )
        stack = ExitStack()
        saver = stack.enter_context(PostgresSaver.from_conn_string(url))
        saver.setup()
        return saver, stack
    raise ValueError(f"Unknown CHECKPOINTER_BACKEND={backend!r}")


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("ingest", nodes.ingest_node)
    g.add_node("anomaly_check", nodes.anomaly_check_node)
    g.add_node("action_output", nodes.action_output_node)
    g.add_node("fetch_data", nodes.fetch_data_node)

    # investigation sub-graph (ReAct)
    g.add_node("investigation_init", nodes.investigation_init_node)
    g.add_node("plan", nodes.plan_node)
    g.add_node("act", nodes.act_node)
    g.add_node("observe", nodes.observe_node)
    g.add_node("finalize_investigation", nodes.finalize_investigation_node)

    g.add_node("policy_output", nodes.policy_output_node)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "anomaly_check")

    g.add_conditional_edges(
        "anomaly_check",
        nodes.anomaly_route,
        {
            "anomalous": "fetch_data",
            "normal": "action_output",
        },
    )
    g.add_edge("action_output", END)

    g.add_edge("fetch_data", "investigation_init")
    g.add_edge("investigation_init", "plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "observe")

    g.add_conditional_edges(
        "observe",
        nodes.investigation_route,
        {
            "continue": "plan",
            "converged": "finalize_investigation",
            "self_declared": "finalize_investigation",
            "max_iter": "finalize_investigation",
            "no_pattern": "finalize_investigation",
        },
    )

    g.add_edge("finalize_investigation", "policy_output")
    g.add_edge("policy_output", END)

    if checkpointer is None:
        checkpointer, _ = _build_checkpointer()
    return g.compile(checkpointer=checkpointer)
