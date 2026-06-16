"""LLM abstraction — OpenAI-compatible endpoint with per-role model routing.

Models are picked per-call from env, with the precedence:

    LLM_MODEL_<ROLE_UPPER>   (e.g. LLM_MODEL_PLAN)
        ↓
    LLM_MODEL                (global fallback)

Roles in use:
    ingest          → tabular parsing
    anomaly         → trigger-rule evaluation
    plan / observe  → ReAct reasoning

`thinking=True` is kept as a parameter for parity with skills that route
to extended-thinking variants when available.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

from openai import OpenAI
from openai import APITimeoutError, APIConnectionError


@dataclass
class LLMResponse:
    data: dict


class BaseLLM:
    def complete_json(self, system: str, user: str) -> dict:
        raise NotImplementedError


def _resolve_model(role: str | None) -> str:
    """Pick model id by role with fallback to LLM_MODEL."""
    if role:
        m = os.environ.get(f"LLM_MODEL_{role.upper()}")
        if m:
            return m
    m = os.environ.get("LLM_MODEL")
    if not m:
        raise RuntimeError(
            "LLM_MODEL (or LLM_MODEL_<ROLE>) must be set in env"
        )
    return m


class OpenAILLM(BaseLLM):
    """OpenAI-compatible client (GreenNode AIP, OpenAI, or any compatible provider)."""

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
        """Call LLM and parse JSON. Retries up to 3x with backoff on timeout/network errors."""
        sys_msg = system + "\n\nRespond with ONLY valid JSON, no markdown, no preamble."
        last_err: Exception | None = None
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=[
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": user},
                    ],
                    extra_body={"enable_thinking": False},
                    timeout=60,
                )
                msg = resp.choices[0].message
                # Thinking models (Qwen3, DeepSeek-R1, etc.) may put the answer
                # in reasoning_content when content is empty.
                raw = msg.content or ""
                if not raw.strip():
                    raw = getattr(msg, "reasoning_content", "") or ""
                # Strip <think>...</think> blocks that some models leak into content
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
                # Strip markdown fences
                raw = re.sub(r"```json|```", "", raw).strip()
                if not raw:
                    raise ValueError(
                        f"LLM returned empty content (model={self.model}, attempt {attempt + 1})"
                    )
                return json.loads(raw)

            except (APITimeoutError, APIConnectionError) as e:
                last_err = e
                wait = 2 ** attempt  # 1s, 2s, 4s
                print(f"[OpenAILLM] network error attempt {attempt + 1}/{max_attempts} "
                      f"(model={self.model}): {e} — retrying in {wait}s")
                if attempt < max_attempts - 1:
                    time.sleep(wait)

            except (json.JSONDecodeError, ValueError) as e:
                last_err = e
                sys_msg = (
                    system
                    + "\n\nCRITICAL: Last attempt returned invalid output. "
                    "Respond with strictly valid JSON only — no markdown, "
                    "no comments, no leading/trailing whitespace."
                )

        print(f"[OpenAILLM] failed after {max_attempts} attempts for model={self.model}: {last_err}")
        return {}


def get_llm(role: str | None = None, thinking: bool = False) -> BaseLLM:
    """Factory. `role` selects the per-role model env override.

    Examples:
        get_llm(role="plan", thinking=True)
        get_llm(role="ingest")
        get_llm()   # default LLM_MODEL
    """
    return OpenAILLM(role=role, thinking=thinking)
