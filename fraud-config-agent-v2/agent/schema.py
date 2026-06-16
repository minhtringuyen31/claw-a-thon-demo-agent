"""Output schema — FraudConfig events format (consumed by config-service / MySQL).

Copied from config-agent V3a so v2 emits the same contract:
    FraudConfig → Event[] → Rule[] → Condition[]   (+ Event.variables[] for velocity fields)
"""
from typing import Literal

from pydantic import BaseModel


class Source(BaseModel):
    keyId: str


class Variable(BaseModel):
    fieldName: str
    fieldType: str
    source: Source


class Condition(BaseModel):
    field: str
    operator: str
    value: str


class Rule(BaseModel):
    name: str
    description: str = ""
    conditions: list[Condition]
    infoCode: str = ""


class Event(BaseModel):
    name: str
    description: str = ""
    filter: Literal["AND", "OR"] = "AND"
    actionCode: str
    decisionCode: str = ""
    variables: list[Variable] = []
    rules: list[Rule]


class FraudConfig(BaseModel):
    events: list[Event]
