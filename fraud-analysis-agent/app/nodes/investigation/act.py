"""act_node — dispatch the planned tool call and attach observation.

Pure dispatcher; no LLM. Failures land as `{"error": ...}` in the
observation so the loop can recover instead of crashing.
"""
from __future__ import annotations

from app.state import AgentState
from app.nodes.investigation.tools import TOOL_REGISTRY


OBSERVATION_TRUNCATE_KEYS = ("sample_rows", "rows_sample")


def _truncate_observation(obs: dict, cap: int = 15) -> dict:
    """Defensive cap in case a tool returned more rows than expected."""
    out = dict(obs)
    for key in OBSERVATION_TRUNCATE_KEYS:
        if isinstance(out.get(key), list) and len(out[key]) > cap:
            out[key] = out[key][:cap]
    return out


def act_node(state: AgentState) -> dict:
    step = dict(state.get("current_step") or {})
    tool_name = step.get("tool")
    args = step.get("args") or {}

    if tool_name not in TOOL_REGISTRY:
        step["observation"] = {
            "error": (
                f"unknown tool {tool_name!r}; valid: {list(TOOL_REGISTRY)}"
            )
        }
        return {"current_step": step}

    try:
        result = TOOL_REGISTRY[tool_name](**args)
    except TypeError as e:
        result = {"error": f"bad args for {tool_name}: {e}"}
    except Exception as e:  # noqa: BLE001
        result = {"error": f"{type(e).__name__}: {e}"}

    step["observation"] = _truncate_observation(result)
    return {"current_step": step}
