"""CLI for quick local runs (no human gate — auto-approves to show the full path).

    python cli.py "appid 123, reject nếu tổng tiền 24h > 10 triệu và account mới hơn 7 ngày"
"""
import json
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()

from agent.graph import build_graph  # noqa: E402


def run_cli(raw_input: str, approve: bool = True) -> dict:
    from langgraph.checkpoint.memory import MemorySaver
    graph = build_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state = {
        "raw_input": raw_input, "source_type": "chat", "session_id": "cli",
        "clarification_answer": "proceed", "clarify_history": [],
        "needs_clarification": False, "retry_count": 0,
    }
    graph.invoke(state, cfg)
    snap = graph.get_state(cfg)
    if "human_review" in (snap.next or ()):
        if not approve:
            return {"status": "awaiting_review", "final_output": snap.values.get("final_output", {})}
        graph.update_state(cfg, {"review_decision": "approve", "approved_by": "cli"})
        graph.invoke(None, cfg)
        snap = graph.get_state(cfg)
    v = snap.values
    return {
        "status": "completed" if v.get("write_result", {}).get("written") else "clarify",
        "operation": v.get("operation"),
        "final_output": v.get("final_output", {}),
        "write_result": v.get("write_result", {}),
        "question": v.get("clarify_question", ""),
    }


if __name__ == "__main__":
    raw = " ".join(sys.argv[1:]) or sys.stdin.read().strip()
    print(json.dumps(run_cli(raw), indent=2, ensure_ascii=False))
