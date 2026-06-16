"""RuleJSON contract — interface between Risk Agent and Config Agent.

A policy suggestion: rule name, SQL predicate (SELECT returning matched
txn_ids), the metrics that justified it, and provenance. Status is
`suggested` by default (the Risk Agent does not gate on human approval
in this pipeline — strategist review happens downstream in Config Agent
or wherever the rule lands).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RuleJSONMetrics(BaseModel):
    precision: float
    recall: float
    f1: float


class RuleJSON(BaseModel):
    rule_name: str
    fraud_type: str
    sql_predicate: str
    description: str
    signal_columns: list[str] = Field(default_factory=list)
    recommended_action: Literal[
        "monitor", "challenge", "reject", "blacklist",
        "whitelist_exclusion", "none",
    ] = "none"
    metrics: RuleJSONMetrics
    iteration_count: int
    status: Literal["suggested", "no_action"] = "suggested"
    emitted_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_run_id: Optional[str] = None
