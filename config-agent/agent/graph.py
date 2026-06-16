from langgraph.graph import StateGraph, END
from agent.state import ConfigAgentState
from agent.nodes import (
    intake_node,
    planner_node,
    dependency_resolver,
    build_config_node,
    validator_node,
    output_node,
    clarify_node,
    memory_load_node,
    memory_save_node,
)

MAX_RETRIES = 2


def should_retry(state: ConfigAgentState) -> str:
    if state["validation_errors"] and state["retry_count"] < MAX_RETRIES:
        return "retry"
    return "done"


def should_clarify(state: ConfigAgentState) -> str:
    if state.get("needs_clarification"):
        return "clarify"
    return "proceed"


def build_graph() -> StateGraph:
    graph = StateGraph(ConfigAgentState)

    graph.add_node("memory_load_node", memory_load_node)
    graph.add_node("intake_node", intake_node)
    graph.add_node("clarify_node", clarify_node)
    graph.add_node("dependency_resolver", dependency_resolver)
    graph.add_node("planner_node", planner_node)
    graph.add_node("build_config_node", build_config_node)
    graph.add_node("validator_node", validator_node)
    graph.add_node("output_node", output_node)
    graph.add_node("memory_save_node", memory_save_node)

    graph.set_entry_point("memory_load_node")
    graph.add_edge("memory_load_node", "intake_node")
    graph.add_edge("intake_node", "clarify_node")
    graph.add_conditional_edges(
        "clarify_node",
        should_clarify,
        {"clarify": END, "proceed": "dependency_resolver"},
    )
    graph.add_edge("dependency_resolver", "planner_node")
    graph.add_edge("planner_node", "build_config_node")
    graph.add_edge("build_config_node", "validator_node")
    graph.add_conditional_edges(
        "validator_node",
        should_retry,
        {"retry": "build_config_node", "done": "output_node"},
    )
    graph.add_edge("output_node", "memory_save_node")
    graph.add_edge("memory_save_node", END)

    return graph.compile()
