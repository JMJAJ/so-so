"""Claude via the official Anthropic SDK (streaming, tool use, adaptive thinking)."""

from __future__ import annotations

import json
from typing import Callable

import anthropic

from . import Reply

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str, api_key: str | None):
        self.model = model
        # api_key=None lets the SDK resolve ANTHROPIC_API_KEY / an `ant auth login` profile.
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3)

    def _messages(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for message in messages:
            role = message["role"]
            if role == "user":
                out.append({"role": "user", "content": message["text"]})
            elif role == "assistant":
                if message.get("native") is not None and isinstance(message["native"], list):
                    out.append({"role": "assistant", "content": message["native"]})
                    continue
                blocks: list[dict] = []
                if message.get("text"):
                    blocks.append({"type": "text", "text": message["text"]})
                for call in message.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": call["id"], "name": call["name"], "input": call["input"]})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(no content)"}]})
            elif role == "tool":
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": result["id"], "content": result["content"],
                     "is_error": bool(result.get("is_error"))}
                    for result in message["results"]
                ]})
        return out

    @staticmethod
    def _tools(tools: list[dict] | None) -> list[dict]:
        return [
            {"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"],
             "eager_input_streaming": True}
            for tool in tools or []
        ]

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None, *,
                 max_tokens: int = 32000, on_text: Callable[[str], None] | None = None,
                 effort: str | None = None) -> Reply:
        params: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": self._messages(messages),
            "betas": [FALLBACK_BETA],
            "extra_body": {"fallbacks": "default"},
        }
        if tools:
            params["tools"] = self._tools(tools)
        if effort:
            params["output_config"] = {"effort": effort}
        try:
            with self.client.beta.messages.stream(**params) as stream:
                for event in stream:
                    if on_text and event.type == "content_block_delta" and event.delta.type == "text_delta":
                        on_text(event.delta.text)
                final = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise RuntimeError("Anthropic rejected the API key. Update it in Settings → AI model.") from exc
        except TypeError as exc:  # raised by the SDK when no credential could be resolved at all
            if "authentication" in str(exc).lower():
                raise RuntimeError("No Anthropic API key configured. Add one in Settings → AI model or .env.") from exc
            raise

        if final.stop_reason == "refusal":
            category = getattr(getattr(final, "stop_details", None), "category", None)
            return Reply(text=f"[The model declined this request{f' ({category})' if category else ''}.]",
                         stop_reason="refusal")
        text_parts, calls = [], []
        for block in final.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_input = block.input
                if isinstance(tool_input, str):  # eager streaming can leave unparsed input
                    try:
                        tool_input = json.loads(tool_input)
                    except json.JSONDecodeError:
                        tool_input = {"__invalid_json__": tool_input}
                calls.append({"id": block.id, "name": block.name, "input": tool_input or {}})
        if final.stop_reason == "max_tokens" and calls:
            calls = []  # truncated tool input: never execute it
        native = [block.model_dump(exclude_none=True) for block in final.content]
        usage = {"input": final.usage.input_tokens, "output": final.usage.output_tokens}
        return Reply(text="".join(text_parts), tool_calls=calls, native=native,
                     stop_reason=final.stop_reason or "", usage=usage)
