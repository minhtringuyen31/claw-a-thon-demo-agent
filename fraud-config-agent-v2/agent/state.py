"""ConfigAgentState — persisted by LangGraph's checkpointer at each step.

Each node returns a partial update (dict of changed fields only), never mutates
state in place.
"""
from typing import Literal, Optional, TypedDict


class ConfigAgentState(TypedDict, total=False):
    # --- input ---
    raw_input: str                 # chat text, or serialized fraud report
    source_type: Literal["chat", "report"]
    run_id: str                    # source fraud-analysis-agent run (report path)
    fraud_report: dict             # {final_pattern, recommendation} pulled by run_id

    # --- intake / clarify ---
    requirement: dict              # normalized requirement (intake_node)
    session_id: str
    clarify_question: str
    clarification_answer: str
    needs_clarification: bool
    clarify_history: list          # [{question, answer}, ...]
    conversation_history: list     # [{user, requirement_summary, config_summary}, ...]

    # --- dependency resolution (rule-level dedup) ---
    operation: Literal["create", "update"]
    existing_config: dict          # the app's current config, if any
    dedup: dict                    # {found: bool, event_name, rule_name} when update

    # --- build / validate ---
    json_draft: dict               # build_config_node output
    validation_errors: list
    final_output: dict             # validated config
    retry_count: int

    # --- human review + write ---
    approved_by: Optional[str]
    review_decision: Optional[Literal["approve", "reject"]]
    output_file: str               # path of the saved config plan
    write_result: dict             # {written: bool, row_id, target}
