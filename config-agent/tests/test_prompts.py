from agent.prompts import (
    INTAKE_SYSTEM,
    INTAKE_USER,
    PLANNER_SYSTEM,
    PLANNER_USER,
    BUILD_CONFIG_SYSTEM,
    BUILD_CONFIG_USER,
)


def test_intake_prompts_exist():
    assert isinstance(INTAKE_SYSTEM, str) and len(INTAKE_SYSTEM) > 0
    assert "{raw_input}" in INTAKE_USER


def test_planner_prompts_exist():
    assert isinstance(PLANNER_SYSTEM, str) and len(PLANNER_SYSTEM) > 0
    assert "{requirement}" in PLANNER_USER


def test_build_config_prompts_exist():
    assert isinstance(BUILD_CONFIG_SYSTEM, str) and len(BUILD_CONFIG_SYSTEM) > 0
    assert "{requirement}" in BUILD_CONFIG_USER
    assert "{plan}" in BUILD_CONFIG_USER
    assert "{operation}" in BUILD_CONFIG_USER
    assert "{existing_config}" in BUILD_CONFIG_USER


def test_intake_user_formats():
    formatted = INTAKE_USER.format(raw_input="test input")
    assert "test input" in formatted


def test_planner_user_formats():
    formatted = PLANNER_USER.format(requirement='{"app_id": "1"}')
    assert '{"app_id": "1"}' in formatted


def test_build_config_user_formats():
    formatted = BUILD_CONFIG_USER.format(
        requirement='{"app_id": "1"}',
        plan='{"profile_name": "Test"}',
        operation="create",
        existing_config="{}",
    )
    assert "create" in formatted


def test_clarify_prompts_exist():
    from agent.prompts import CLARIFY_SYSTEM, CLARIFY_USER
    assert isinstance(CLARIFY_SYSTEM, str) and len(CLARIFY_SYSTEM) > 0
    assert "{requirement}" in CLARIFY_USER
    assert "{history}" in CLARIFY_USER


def test_clarify_user_formats():
    from agent.prompts import CLARIFY_USER
    formatted = CLARIFY_USER.format(
        requirement='{"app_id": "123"}',
        history='[{"question": "action?", "answer": "tôi muốn reject"}]',
    )
    assert "reject" in formatted


def test_build_config_system_has_events_schema():
    from agent.prompts import BUILD_CONFIG_SYSTEM
    assert "events" in BUILD_CONFIG_SYSTEM
    assert "actionCode" in BUILD_CONFIG_SYSTEM
