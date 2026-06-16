"""LangGraph topology.

START → intake → clarify ─clarify→ END
                         └proceed→ dependency_resolver → build_config → validator
validator ─retry→ build_config        (dormant: validator currently always passes)
          └done→ human_review  [INTERRUPT before]
human_review ─approve→ update_conf → END
             └reject→ END
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from agent.nodes import (
    build_config_node,
    clarify_node,
    dependency_resolver,
    human_review_node,
    intake_node,
    update_conf_node,
    validator_node,
)
from agent.state import ConfigAgentState

MAX_RETRIES = 2


def should_clarify(state: ConfigAgentState) -> str:
    return "clarify" if state.get("needs_clarification") else "proceed"


def should_retry(state: ConfigAgentState) -> str:
    if state.get("validation_errors") and state.get("retry_count", 0) < MAX_RETRIES:
        return "retry"
    return "done"


def should_write(state: ConfigAgentState) -> str:
    return "approve" if state.get("review_decision") == "approve" else "reject"


def build_graph(checkpointer=None):
    graph = StateGraph(ConfigAgentState)

    graph.add_node("intake", intake_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("dependency_resolver", dependency_resolver)
    graph.add_node("build_config", build_config_node)
    graph.add_node("validator", validator_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("update_conf", update_conf_node)

    graph.set_entry_point("intake")
    graph.add_edge("intake", "clarify")
    graph.add_conditional_edges(
        "clarify", should_clarify,
        {"clarify": END, "proceed": "dependency_resolver"},
    )
    graph.add_edge("dependency_resolver", "build_config")
    graph.add_edge("build_config", "validator")
    graph.add_conditional_edges(
        "validator", should_retry,
        {"retry": "build_config", "done": "human_review"},
    )
    # Always pass through update_conf; it writes only on approve (and records a
    # write_result either way, so callers can distinguish rejected vs written).
    graph.add_edge("human_review", "update_conf")
    graph.add_edge("update_conf", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],
    )
