from typing import TypedDict


class ConfigAgentState(TypedDict):
    raw_input: str
    requirement: dict        # output của intake_node
    plan: dict               # output của planner_node
    existing_config: dict    # kết quả query mock config-service
    operation: str           # "create" hoặc "update"
    json_draft: dict         # output của build_config_node
    validation_errors: list  # Pydantic errors nếu có
    final_output: dict       # validated JSON config
    retry_count: int
    output_file: str         # path file đã lưu
    # V3a fields
    session_id: str
    clarify_question: str
    clarification_answer: str
    needs_clarification: bool
    clarify_history: list  # list of {question, answer} dicts
