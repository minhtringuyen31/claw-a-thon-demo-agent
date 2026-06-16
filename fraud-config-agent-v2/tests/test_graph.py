"""Graph routers + full end-to-end with MemorySaver (interrupt → review → write)."""
import uuid

from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph, should_clarify, should_retry, should_write


def test_routers():
    assert should_clarify({"needs_clarification": True}) == "clarify"
    assert should_clarify({"needs_clarification": False}) == "proceed"
    assert should_retry({"validation_errors": ["e"], "retry_count": 0}) == "retry"
    assert should_retry({"validation_errors": [], "retry_count": 0}) == "done"
    assert should_write({"review_decision": "approve"}) == "approve"
    assert should_write({"review_decision": "reject"}) == "reject"


def test_graph_nodes_present():
    g = build_graph(checkpointer=MemorySaver())
    names = set(g.get_graph().nodes.keys())
    for n in ("intake", "clarify", "dependency_resolver", "build_config",
              "validator", "human_review", "update_conf"):
        assert n in names


def test_end_to_end_interrupt_then_approve():
    g = build_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    g.invoke({
        "raw_input": "appid 123, reject nếu tổng tiền 24h > 10 triệu",
        "source_type": "chat", "session_id": "", "clarification_answer": "",
        "clarify_history": [], "needs_clarification": False, "retry_count": 0,
    }, cfg)

    snap = g.get_state(cfg)
    assert "human_review" in snap.next            # paused at the gate
    assert snap.values["final_output"]["events"]  # config plan ready

    g.update_state(cfg, {"review_decision": "approve", "approved_by": "tester"})
    g.invoke(None, cfg)
    final = g.get_state(cfg)
    assert not final.next                          # finished
    assert final.values["write_result"]["written"] is True


def test_end_to_end_reject_writes_nothing():
    g = build_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    g.invoke({
        "raw_input": "appid 55, review nếu amount > 1tr",
        "source_type": "chat", "session_id": "", "clarification_answer": "",
        "clarify_history": [], "needs_clarification": False, "retry_count": 0,
    }, cfg)
    g.update_state(cfg, {"review_decision": "reject"})
    g.invoke(None, cfg)
    final = g.get_state(cfg)
    assert final.values["write_result"]["written"] is False
