"""investigation_route — conditional edge after observe_node.

Returns one of: "continue", "converged", "max_iter", "self_declared",
"no_pattern". `app/graph` maps these to plan / finalize_investigation.

Two guardrails on "converged":
  1. The pattern must satisfy the *actual* min_precision + min_recall
     thresholds (we do not trust LLM-set status fields).
  2. We must have crossed ESCALATION_MIN_SOURCES distinct data sources
     (translog vs profile vs journey) OR the rule must already exceed
     a stricter precision bar — this enforces KB §1's
     `translog → profile → journey` escalation order even when the LLM
     wants to stop early.
"""
from __future__ import annotations

from app.state import AgentState


# Pattern is allowed to short-circuit escalation only when precision is
# THIS high — i.e. a translog-only Reject-quality rule with strong
# precision can stop without forcing a profile/journey attempt.
SHORTCIRCUIT_PRECISION = 0.95


def _pattern_meets_threshold(p: dict, cfg: dict) -> bool:
    m = p.get("metrics") or {}
    if not m:
        return False
    return (
        m.get("precision", 0) >= cfg.get("min_precision", 0.9)
        and m.get("recall", 0) >= cfg.get("min_recall", 0.2)
    )


def _source_of(p: dict) -> str:
    """Classify which data sources a pattern's SQL touches."""
    sql = (p.get("sql_predicate") or "").lower()
    if "user_journey" in sql:
        return "journey"
    if "user_profile" in sql:
        return "profile"
    return "translog"


def _sources_explored(patterns: list[dict]) -> set[str]:
    return {_source_of(p) for p in patterns if p.get("sql_predicate")}


def _best_qualified(patterns: list[dict], cfg: dict) -> dict | None:
    qualified = [p for p in patterns if _pattern_meets_threshold(p, cfg)]
    if not qualified:
        return None
    return max(qualified, key=lambda p: (p.get("metrics") or {}).get("f1", 0))


def investigation_route(state: AgentState) -> str:
    reason = state.get("investigation_stop_reason")
    cfg = state.get("threshold_config") or {}
    patterns = state.get("patterns_attempted") or []
    iteration = state.get("investigation_iteration", 0)
    max_iter = int(cfg.get("max_iterations", 10))

    best = _best_qualified(patterns, cfg)

    # `converged` only when actual metrics pass threshold AND one of:
    #   - precision is already ≥ SHORTCIRCUIT_PRECISION (excellent rule)
    #   - we've actually tried multiple data sources (escalation completed)
    if best:
        precision_high = (best.get("metrics") or {}).get("precision", 0) >= SHORTCIRCUIT_PRECISION
        sources_tried = _sources_explored(patterns)
        if precision_high or len(sources_tried) >= 2:
            return "converged"
        # Otherwise: keep going to attempt profile/journey escalation
        # (unless out of iterations).

    if reason == "self_declared":
        # Honor self-declared stop, but downgrade to "no_pattern" if no
        # qualified rule exists yet — prevents the LLM from punting too early.
        return "self_declared" if best else "no_pattern"

    if iteration >= max_iter:
        return "max_iter" if patterns else "no_pattern"

    return "continue"
