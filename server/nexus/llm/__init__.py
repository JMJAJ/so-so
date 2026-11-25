"""Pluggable LLM providers with tool calling.

Conversation history is kept in a provider-neutral, append-only list:
  {"role": "user", "text": str}
  {"role": "assistant", "text": str, "tool_calls": [{"id", "name", "input"}], "native": <provider blocks>}
  {"role": "tool", "results": [{"id", "name", "content": str, "is_error": bool}]}
Each adapter replays its own `native` assistant content unchanged (required for
Claude thinking blocks) and rebuilds from text/tool_calls otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from .. import config


@dataclass
class Reply:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    native: object = None
    stop_reason: str = ""
    usage: dict = field(default_factory=dict)

    def as_message(self) -> dict:
        return {"role": "assistant", "text": self.text, "tool_calls": self.tool_calls, "native": self.native}


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None, *,
                 max_tokens: int = 16000, on_text: Callable[[str], None] | None = None,
                 effort: str | None = None) -> Reply: ...


PROVIDERS = {
    "anthropic": {"label": "Anthropic (Claude)", "default_model": "claude-sonnet-5-5", "key": "anthropic_api_key"},
    "openai": {"label": "OpenAI", "default_model": "gpt-5", "key": "openai_api_key",
               "base_url": "https://api.openai.com/v1"},
    "openrouter": {"label": "OpenRouter", "default_model": "anthropic/claude-sonnet-5.5", "key": "openrouter_api_key",
                   "base_url": "https://openrouter.ai/api/v1"},
    "nvidia": {"label": "NVIDIA NIM (free tier)", "default_model": "nvidia/nemotron-3-ultra-550b-a55b",
               "fast_model": "minimaxai/minimax-m3.1-flash", "key": "nvidia_api_key",
               "base_url": "https://integrate.api.nvidia.com/v1"},
    "ollama": {"label": "Ollama (local)", "default_model": "qwen3:14b", "key": None,
               "base_url": "http://localhost:11434/v1"},
    "lmstudio": {"label": "LM Studio (local)", "default_model": "local-model", "key": None,
                 "base_url": "http://localhost:1234/v1"},
}


def create(kind: str = "main") -> Provider:
    """`kind` = "main" (analyst/chat) or "fast" (bulk headline classification)."""
    provider = config.get("llm_provider")
    model = config.get("llm_model") if kind == "main" else config.get("llm_fast_model")
    meta = PROVIDERS.get(provider)
    if not meta:
        raise RuntimeError(f"Unknown LLM provider '{provider}'")
    if provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        key = config.secret("anthropic_api_key")
        return AnthropicProvider(model or meta["default_model"], key or None)
    from .openai_compat import OpenAICompatProvider

    if kind == "fast" and (not model or model.startswith("claude-")):
        model = config.get("llm_model")
    key = config.secret(meta["key"]) if meta["key"] else "not-needed"
    base_url = config.get("llm_base_url") or meta["base_url"]
    return OpenAICompatProvider(provider, model or meta["default_model"], key, base_url)
