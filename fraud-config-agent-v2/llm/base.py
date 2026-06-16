"""LLM abstraction — OpenAI-compatible endpoint with per-role model routing.

Ported from fraud-analysis-agent. Two implementations:

    OpenAILLM   real provider (VNG MAAS / OpenAI-compatible), used when USE_REAL_LLM is set
    MockLLM     deterministic canned JSON per role, used otherwise (CI / tests / demo)

Model precedence for the real client:

    LLM_MODEL_<ROLE_UPPER>   (e.g. LLM_MODEL_BUILD)
        ↓
    LLM_MODEL                (global fallback)

Roles in use here:
    intake     parse report / chat → structured requirement
    clarify    decide whether a follow-up question is needed
    build      reason requirement → FraudConfig events JSON
"""
from __future__ import annotations

import json
import os
import re

from openai import OpenAI


class BaseLLM:
    def complete_json(self, system: str, user: str) -> dict:
        raise NotImplementedError


def _resolve_model(role: str | None) -> str:
    if role:
        m = os.environ.get(f"LLM_MODEL_{role.upper()}")
        if m:
            return m
    m = os.environ.get("LLM_MODEL")
    if not m:
        raise RuntimeError("LLM_MODEL (or LLM_MODEL_<ROLE>) must be set in env")
    return m


class OpenAILLM(BaseLLM):
    """OpenAI-compatible client (VNG MAAS, OpenAI, or any compatible provider)."""

    def __init__(self, role: str | None = None, thinking: bool = False):
        api_key = os.environ.get("LLM_API_KEY")
        base_url = os.environ.get("LLM_BASE_URL")
        if not api_key or not base_url:
            raise RuntimeError("LLM_API_KEY / LLM_BASE_URL must be set")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.role = role
        self.model = _resolve_model(role)
        self.thinking = thinking

    def complete_json(self, system: str, user: str) -> dict:
        sys_msg = system + "\n\nRespond with ONLY valid JSON, no markdown, no preamble."
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=[
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": user},
                    ],
                    extra_body={"enable_thinking": False},
                )
                msg = resp.choices[0].message
                # Thinking models may put the answer in reasoning_content.
                raw = msg.content or ""
                if not raw.strip():
                    raw = getattr(msg, "reasoning_content", "") or ""
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
                raw = re.sub(r"```json|```", "", raw).strip()
                if not raw:
                    raise ValueError(
                        f"LLM returned empty content (model={self.model}, attempt {attempt + 1})"
                    )
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError) as e:
                last_err = e
                sys_msg = (
                    system
                    + "\n\nCRITICAL: Last attempt returned invalid output. "
                    "Respond with strictly valid JSON only — no markdown, "
                    "no comments, no leading/trailing whitespace."
                )
        print(f"[OpenAILLM] JSON parse failed twice for model={self.model}: {last_err}")
        return {}


# --------------------------------------------------------------------------
# MockLLM — deterministic, dependency-free. Returns reasonable canned JSON so
# the whole graph runs end-to-end without a provider (CI / tests / demo).
# It does a light keyword parse of the user message so the demo feels real.
# --------------------------------------------------------------------------

_OP_WORDS = {
    ">": "GREATER_THAN", ">=": "GREATER_THAN_OR_EQUAL",
    "<": "LESS_THAN", "<=": "LESS_THAN_OR_EQUAL", "=": "EQUALS",
}


def _mock_requirement(user: str) -> dict:
    # intake_node wraps the raw input in a prompt; recover just the payload.
    payload = user.split("input:\n\n", 1)[-1].strip() if "input:\n\n" in user else user.strip()
    text = payload.lower()
    app_id = ""
    m = re.search(r"app\s*id\s*[:=]?\s*(\d+)", text) or re.search(r"appid\s*(\d+)", text)
    if m:
        app_id = m.group(1)

    action = "REVIEW"
    if any(k in text for k in ("reject", "chặn", "từ chối", "block")):
        action = "REJECT"
    elif any(k in text for k in ("allow", "cho qua", "chấp nhận")):
        action = "ALLOW"

    conditions: list[dict] = []
    # velocity: sum_amount over a window (single capture group → list of strings)
    for val in re.findall(r"(\d[\d_.,]*)\s*(?:triệu|tr\b|million|m\b)", text):
        amount = int(float(val.replace(",", "").replace("_", "").replace(".", "")) * 1_000_000)
        conditions.append({"field": "sum_amount_24h", "operator": "GREATER_THAN", "value": str(amount)})
        break
    # account age: "mới hơn X ngày"
    am = re.search(r"(?:mới hơn|younger than|under)\s*(\d+)\s*(?:ngày|day)", text)
    if am:
        conditions.append({"field": "account_age", "operator": "LESS_THAN", "value": str(int(am.group(1)) * 86400)})
    if not conditions:
        conditions.append({"field": "amount", "operator": "GREATER_THAN", "value": "5000000"})

    return {
        "app_id": app_id or "unknown",
        "event_name": "payment",
        "profile_name": f"Rule for app {app_id or 'unknown'}",
        "description": payload[:160],
        "conditions": conditions,
        "action": action,
    }


def _mock_build_config(requirement: dict) -> dict:
    conditions = list(requirement.get("conditions") or [])
    # app scope is a CONDITION inside the rule, not a top-level field.
    app_id = requirement.get("app_id", "")
    if app_id and app_id != "unknown" and not any(
        c.get("field") in ("appID", "appid") for c in conditions
    ):
        conditions = [{"field": "appID", "operator": "EQUALS", "value": str(app_id)}] + conditions
    variables = []
    for c in conditions:
        f = c.get("field", "")
        if f.startswith(("count_txn_", "sum_amount_")):
            ftype = "LONG"
            variables.append({
                "fieldName": f,
                "fieldType": ftype,
                "source": {"keyId": f"{f}|${{userid}}"},
            })
    return {
        "events": [
            {
                "name": requirement.get("event_name", "payment"),
                "description": requirement.get("description", ""),
                "filter": "AND",
                "actionCode": requirement.get("action", "REVIEW"),
                "decisionCode": "",
                "variables": variables,
                "rules": [
                    {
                        "name": requirement.get("profile_name", "Generated Rule"),
                        "description": requirement.get("description", ""),
                        "conditions": conditions,
                        "infoCode": "",
                    }
                ],
            }
        ]
    }


class MockLLM(BaseLLM):
    def __init__(self, role: str | None = None, thinking: bool = False):
        self.role = role
        self.thinking = thinking

    def complete_json(self, system: str, user: str) -> dict:
        role = (self.role or "").lower()
        if role == "intake":
            # user message is the raw input (chat text or serialized report).
            return _mock_requirement(user)
        if role == "clarify":
            return {"needs_clarification": False, "question": ""}
        if role == "build":
            # `user` carries "Requirement: {...}" on one line; recover that object.
            req = {}
            m = re.search(r"^Requirement:\s*(\{.*\})\s*$", user, flags=re.MULTILINE)
            if m:
                try:
                    req = json.loads(m.group(1))
                except Exception:
                    req = {}
            return _mock_build_config(req if isinstance(req, dict) else {})
        return {}


def get_llm(role: str | None = None, thinking: bool = False) -> BaseLLM:
    """Factory. Real client only when USE_REAL_LLM is truthy; MockLLM otherwise."""
    if os.environ.get("USE_REAL_LLM", "").strip().lower() in ("1", "true", "yes"):
        return OpenAILLM(role=role, thinking=thinking)
    return MockLLM(role=role, thinking=thinking)
