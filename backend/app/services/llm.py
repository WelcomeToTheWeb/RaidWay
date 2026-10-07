"""Provider-agnostic LLM adapter.

Configure with environment variables:
- ``LLM_PROVIDER``: ``mistral`` | ``anthropic`` | ``openai`` | ``openai_compatible`` | ``mock`` (default: mock)
- ``LLM_MODEL``: model name (provider-specific default if unset)
- ``LLM_API_KEY`` / provider-specific keys (``MISTRAL_API_KEY``, ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``)
- ``LLM_BASE_URL``: override for openai-compatible endpoints
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol

log = logging.getLogger(__name__)

PROVIDER_DEFAULT_MODELS = {
    "mistral": "mistral-large-latest",
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "openai_compatible": None,
    "mock": "mock-analyst",
}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str


class LLMProvider(Protocol):
    name: str
    default_model: str

    def complete(self, system: str, user: str, model: Optional[str] = None, temperature: float = 0.3) -> LLMResponse: ...


class MistralProvider:
    name = "mistral"
    default_model = PROVIDER_DEFAULT_MODELS["mistral"]

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url or "https://api.mistral.ai/v1"

    def complete(self, system: str, user: str, model: Optional[str] = None, temperature: float = 0.3) -> LLMResponse:
        try:
            from mistralai import Mistral
        except ImportError as e:
            raise LLMError("Install `mistralai` to use the mistral provider (`pip install mistralai`).") from e
        client = Mistral(api_key=self.api_key, server_url=self.base_url)
        resp = client.chat.complete(
            model=model or self.default_model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        return LLMResponse(text=text, provider=self.name, model=model or self.default_model)


class AnthropicProvider:
    name = "anthropic"
    default_model = PROVIDER_DEFAULT_MODELS["anthropic"]

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url

    def complete(self, system: str, user: str, model: Optional[str] = None, temperature: float = 0.3) -> LLMResponse:
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("Install `anthropic` to use the anthropic provider (`pip install anthropic`).") from e
        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = anthropic.Anthropic(**kwargs)
        resp = client.messages.create(
            model=model or self.default_model,
            max_tokens=4096,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        return LLMResponse(text=text, provider=self.name, model=model or self.default_model)


class OpenAICompatibleProvider:
    name = "openai_compatible"
    default_model = PROVIDER_DEFAULT_MODELS["openai_compatible"]

    def __init__(self, api_key: str, base_url: Optional[str] = None, name: str = "openai_compatible"):
        self.api_key = api_key
        self.base_url = base_url
        self.name = name
        if name == "openai":
            self.default_model = PROVIDER_DEFAULT_MODELS["openai"]

    def complete(self, system: str, user: str, model: Optional[str] = None, temperature: float = 0.3) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError("Install `openai` to use this provider (`pip install openai`).") from e
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=model or self.default_model or "gpt-4o",
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        return LLMResponse(text=text, provider=self.name, model=model or self.default_model or "gpt-4o")


class MockProvider:
    """Deterministic offline provider so the app works without any API key."""

    name = "mock"
    default_model = PROVIDER_DEFAULT_MODELS["mock"]

    def complete(self, system: str, user: str, model: Optional[str] = None, temperature: float = 0.3) -> LLMResponse:
        text = self._analyst_reply(user)
        return LLMResponse(text=text, provider=self.name, model=model or self.default_model)

    def _analyst_reply(self, user: str) -> str:
        lowered = user.lower()
        # Pull a few numbers out of the prompt so mock replies feel grounded.
        damage = re.search(r'"total_damage":\s*(\d+)', user)
        deaths = re.search(r'"total_deaths":\s*(\d+)', user)
        lines = [
            "## Mock Analysis (offline mode)",
            "",
            "This is a placeholder analysis because no LLM provider is configured.",
            "Set LLM_PROVIDER and the matching API key environment variable for real coaching.",
            "",
        ]
        if damage:
            lines.append(f"- Raid damage done: **{int(damage.group(1)):,}**.")
        if deaths:
            lines.append(f"- Total deaths: **{deaths.group(1)}**.")
        lines += [
            "- Review the player table for low activity % and deaths early in the fight.",
            "- Compare top damage performers against the bottom quartile for ability-usage gaps.",
        ]
        if "what" in lowered or "how" in lowered or "improve" in lowered or "better" in lowered:
            lines.append("- Suggested focus: cooldown usage timing, downtime reduction, and defensive usage before deaths.")
        return "\n".join(lines)


def get_provider(env: Optional[dict[str, str]] = None) -> LLMProvider:
    e = env if env is not None else dict(os.environ)
    name = (e.get("LLM_PROVIDER") or "mock").strip().lower()
    base_url = e.get("LLM_BASE_URL") or None
    if name == "mock":
        return MockProvider()
    if name == "mistral":
        key = e.get("LLM_API_KEY") or e.get("MISTRAL_API_KEY")
        if not key:
            raise LLMError("LLM_PROVIDER=mistral requires LLM_API_KEY or MISTRAL_API_KEY.")
        return MistralProvider(api_key=key, base_url=base_url)
    if name == "anthropic":
        key = e.get("LLM_API_KEY") or e.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("LLM_PROVIDER=anthropic requires LLM_API_KEY or ANTHROPIC_API_KEY.")
        return AnthropicProvider(api_key=key, base_url=base_url)
    if name in ("openai", "openai_compatible"):
        key = e.get("LLM_API_KEY") or e.get("OPENAI_API_KEY")
        if not key:
            raise LLMError(f"LLM_PROVIDER={name} requires LLM_API_KEY or OPENAI_API_KEY.")
        return OpenAICompatibleProvider(api_key=key, base_url=base_url, name=name)
    raise LLMError(f"Unknown LLM_PROVIDER '{name}'. Choose from: mistral, anthropic, openai, openai_compatible, mock.")


def provider_status(env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    e = env if env is not None else dict(os.environ)
    name = (e.get("LLM_PROVIDER") or "mock").strip().lower()
    try:
        p = get_provider(e)
        return {"provider": name, "model": os.environ.get("LLM_MODEL") or p.default_model, "ready": True, "error": None}
    except LLMError as ex:
        return {"provider": name, "model": e.get("LLM_MODEL") or "", "ready": False, "error": str(ex)}
