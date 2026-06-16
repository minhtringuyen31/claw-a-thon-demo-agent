"""AgentState + structured payloads.

Persisted by LangGraph's checkpointer at each step. Each node receives the
full state and returns a partial update (dict of changed fields only).
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class FraudContext(BaseModel):
    reported_cases: list[dict] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    time_hint: Optional[str] = None
    raw_summary: str = ""


class MetricsResult(BaseModel):
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    hit_count: int = 0
    total_fraud: int = 0
    total_flagged: int = 0


class ThresholdConfig(BaseModel):
    min_precision: float = 0.80
    min_recall: float = 0.60
    max_iterations: int = 10


class AnomalyEvidence(BaseModel):
    filters: dict = Field(default_factory=dict)
    observation: str = ""


class AnomalyDecision(BaseModel):
    is_anomalous: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    evidence: list[AnomalyEvidence] = Field(default_factory=list)


class NoActionReport(BaseModel):
    decision: dict
    baseline_window: dict
    reported_summary: dict
    baseline_summary: dict
    recommendation: str
    emitted_at: str


# --- Investigation sub-graph ----------------------------------------------

class PatternAttempt(BaseModel):
    """One candidate rule tested during investigation."""
    iteration: int
    description: str
    sql_predicate: str = ""
    signal_columns: list[str] = Field(default_factory=list)
    rationale: str = ""
    metrics: Optional[MetricsResult] = None
    recommended_action: Literal[
        "monitor", "challenge", "reject", "blacklist", "whitelist_exclusion", "none"
    ] = "none"
    status: Literal["candidate", "passed", "failed", "abandoned"] = "candidate"
    notes: str = ""


class InvestigationStep(BaseModel):
    """One ReAct iteration: plan → act → observe."""
    iteration: int
    plan_thought: str = ""
    tool: str = ""
    args: dict = Field(default_factory=dict)
    hypothesis_being_tested: Optional[str] = None
    observation: dict = Field(default_factory=dict)   # tool result (capped)
    next_thought: str = ""


class InvestigationReport(BaseModel):
    """Final output of the investigation sub-graph."""
    patterns_attempted: list[PatternAttempt] = Field(default_factory=list)
    final_pattern: Optional[PatternAttempt] = None
    stop_reason: Literal[
        "converged", "max_iter", "no_pattern", "self_declared", "error"
    ] = "no_pattern"
    iteration_count: int = 0
    investigation_log: list[InvestigationStep] = Field(default_factory=list)
    recommendation: str = ""


# --- AgentState -----------------------------------------------------------

class AgentState(TypedDict, total=False):
    # ingest
    source_type: Literal["email", "postmortem"]
    raw_input: str
    fraud_context: dict                  # FraudContext.model_dump()

    # anomaly_check
    baseline_window: dict
    baseline_summary: dict
    reported_summary: dict
    anomaly_decision: dict               # AnomalyDecision.model_dump()
    no_action_report: dict               # NoActionReport.model_dump()

    # fetch_data
    investigation_window: dict
    investigation_slices: dict
    fetch_strategy_body: str
    data_schema: dict

    threshold_config: dict

    # investigation sub-graph (ReAct loop)
    investigation_kb_body: str
    investigation_skill_body: str
    investigation_iteration: int
    current_step: dict                   # InvestigationStep.model_dump() in flight
    current_hypothesis: Optional[str]
    investigation_log: Annotated[list[dict], add]   # one entry per completed iteration
    patterns_attempted: list[dict]       # replaced (not appended) each observe
    investigation_stop_reason: Optional[str]
    investigation_report: dict           # InvestigationReport.model_dump()

    # human review + final output
    approved_by: Optional[str]
    review_decision: Optional[Literal["approve", "reject"]]
    final_report: dict                   # compatibility wrapper for review UI
    rule_json: dict
    pretty_report: str                   # markdown render of the run

    # meta
    run_id: str
