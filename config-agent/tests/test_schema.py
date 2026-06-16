from agent.schema import Condition, Rule, Event, Variable, Source, FraudConfig


def test_condition_valid():
    c = Condition(field="amount", operator="GREATER_THAN", value="5000000")
    assert c.field == "amount"
    assert c.operator == "GREATER_THAN"
    assert c.value == "5000000"


def test_rule_with_conditions():
    rule = Rule(
        name="Reject High Amount",
        conditions=[Condition(field="amount", operator="GREATER_THAN", value="5000000")],
    )
    assert rule.name == "Reject High Amount"
    assert len(rule.conditions) == 1
    assert rule.description == ""
    assert rule.infoCode == ""


def test_event_defaults():
    event = Event(
        name="payment",
        actionCode="REJECT",
        rules=[
            Rule(
                name="Reject High Amount",
                conditions=[Condition(field="amount", operator="GREATER_THAN", value="5000000")],
            )
        ],
    )
    assert event.filter == "AND"
    assert event.variables == []
    assert event.decisionCode == ""


def test_fraud_config_full():
    config = FraudConfig(
        events=[
            Event(
                name="payment",
                actionCode="REJECT",
                rules=[
                    Rule(
                        name="Reject High Amount",
                        conditions=[Condition(field="amount", operator="GREATER_THAN", value="5000000")],
                    )
                ],
            )
        ]
    )
    assert len(config.events) == 1
    assert config.events[0].actionCode == "REJECT"
    dumped = config.model_dump()
    assert dumped["events"][0]["name"] == "payment"
    assert dumped["events"][0]["variables"] == []


def test_variable_with_source():
    var = Variable(
        fieldName="velocyti_amt_per_user_24hrs",
        fieldType="LONG",
        source=Source(keyId="434"),
    )
    assert var.source.keyId == "434"
