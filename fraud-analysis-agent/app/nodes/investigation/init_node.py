"""investigation_init_node — load KB + skill, reset investigation state."""
from __future__ import annotations

from pathlib import Path

from app.state import AgentState


_HERE = Path(__file__).parent
_KB = _HERE / "kb.md"
_SKILL = _HERE / "skill.md"


def _load(path: Path, fallback: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return fallback


def investigation_init_node(state: AgentState) -> dict:
    return {
        "investigation_kb_body": _load(
            _KB,
            fallback="(no KB file at app/nodes/investigation/kb.md)",
        ),
        "investigation_skill_body": _load(
            _SKILL,
            fallback="(no skill file at app/nodes/investigation/skill.md)",
        ),
        "investigation_iteration": 0,
        "investigation_log": [],
        "patterns_attempted": [],
        "current_hypothesis": None,
        "investigation_stop_reason": None,
    }
