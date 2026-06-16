"""fetch_data_node — targeted historical retrieval driven by anomaly evidence.

For each evidence entry coming out of `anomaly_check_node` (a dict of
`filters` + an `observation`), this node:

  1. Resolves the investigation window (last month + this month-to-date).
  2. Queries `pom_acr` rows matching `filters` in window (confirmed fraud).
  3. Queries `trans_log` rows matching the same `filters` (universe).
  4. Bundles per-slice counts + sample rows.

The reasoning rules for hypothesis_node are loaded from
`strategy.md` and passed through state (`fetch_strategy_body`).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.shared.historical import query_with_filters
from app.shared.schema import get_schema
from app.shared.time_window import compute_investigation_window
from app.state import AgentState


_STRATEGY_PATH = Path(__file__).parent / "strategy.md"
DEFAULT_SAMPLE_SIZE = 20


def _read_strategy() -> tuple[int, str]:
    """Return (sample_size, body). Defaults if file missing or unparseable."""
    if not _STRATEGY_PATH.exists():
        return DEFAULT_SAMPLE_SIZE, ""

    text = _STRATEGY_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    sample_size = DEFAULT_SAMPLE_SIZE
    body = text.strip()

    if lines and lines[0].strip() == "---":
        end = next(
            (i for i in range(1, len(lines)) if lines[i].strip() == "---"),
            None,
        )
        if end is not None:
            fm = "\n".join(lines[1:end])
            body = "\n".join(lines[end + 1:]).strip()
            m = re.search(r"sample_size\s*:\s*(\d+)", fm)
            if m:
                sample_size = max(1, int(m.group(1)))

    return sample_size, body


def _slice_key(filters: dict) -> str:
    return "+".join(f"{k}={filters[k]}" for k in sorted(filters))


def _sample_rows(df: pd.DataFrame, n: int) -> list[dict]:
    out: list[dict] = []
    for _, row in df.head(n).iterrows():
        out.append({k: _jsonable(v) for k, v in row.items()})
    return out


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, float) and pd.isna(v):
        return None
    if hasattr(v, "item") and not isinstance(v, str):
        try:
            return v.item()
        except Exception:
            pass
    return v


def fetch_data_node(state: AgentState) -> dict:
    decision = state.get("anomaly_decision") or {}
    evidence_list = decision.get("evidence", []) or []

    sample_size, strategy_body = _read_strategy()
    window = compute_investigation_window(datetime.utcnow())

    slices: dict[str, dict] = {}
    for ev in evidence_list:
        filters = ev.get("filters") or {}
        if not filters:
            continue

        key = _slice_key(filters)
        if key in slices:
            continue   # de-dup identical filter combinations

        pom_df = query_with_filters("pom_acr", filters, window)
        trans_df = query_with_filters("trans_log", filters, window)

        slices[key] = {
            "filters": filters,
            "observation": ev.get("observation", ""),
            "pom": {
                "count": int(len(pom_df)),
                "sample_rows": _sample_rows(pom_df, sample_size),
            },
            "trans": {
                "count": int(len(trans_df)),
                "sample_rows": _sample_rows(trans_df, sample_size),
            },
        }

    data_schema = get_schema(
        ["trans_log", "pom_acr", "user_profile", "user_journey"]
    )

    return {
        "investigation_window": window,
        "investigation_slices": slices,
        "fetch_strategy_body": strategy_body,
        "data_schema": data_schema,
    }
