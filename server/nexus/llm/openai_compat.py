"""Any OpenAI-compatible chat-completions endpoint (OpenAI, OpenRouter, Ollama, LM Studio)."""

from __future__ import annotations

import json
from typing import Callable

from openai import OpenAI

from . import Reply


class OpenAICompatProvider:
    def __init__(self, name: str, model: str, api_key: str, base_url: str):
        self.name = name
        self.model = model
        self.client = OpenAI(api_key=api_key or "not-needed", base_url=base_url, timeout=600, max_retries=2)

    @staticmethod
    def _messages(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for message in messages:
            if message["role"] == "user":
                out.append({"role": "user", "content": message["text"]})
            elif message["role"] == "assistant":
                entry: dict = {"role": "assistant", "content": message.get("text") or ""}
                if message.get("tool_calls"):
                    entry["tool_calls"] = [
                        {"id": call["id"], "type": "function",
                         "function": {"name": call["name"], "arguments": json.dumps(call["input"])}}
                        for call in message["tool_calls"]
                    ]
                out.append(entry)
            elif message["role"] == "tool":
                for result in message["results"]:
                    out.append({"role": "tool", "tool_call_id": result["id"], "content": result["content"]})
        return out

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None, *,
                 max_tokens: int = 16000, on_text: Callable[[str], None] | None = None,
                 effort: str | None = None) -> Reply:
        params: dict = {"model": self.model, "messages": self._messages(system, messages), "stream": True,
                        "max_tokens": max_tokens}
        if tools:
            params["tools"] = [{"type": "function", "function": {
                "name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}}
                for tool in tools]
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        finish = ""
        for chunk in self.client.chat.completions.create(**params):
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                text_parts.append(delta.content)
                if on_text:
                    on_text(delta.content)
            for tool_delta in (delta.tool_calls if delta and delta.tool_calls else []):
                slot = calls.setdefault(tool_delta.index, {"id": "", "name": "", "arguments": ""})
                if tool_delta.id:
                    slot["id"] = tool_delta.id
                if tool_delta.function and tool_delta.function.name:
                    slot["name"] += tool_delta.function.name
                if tool_delta.function and tool_delta.function.arguments:
                    slot["arguments"] += tool_delta.function.arguments
            if choice.finish_reason:
                finish = choice.finish_reason
        tool_calls = []
        for index, slot in sorted(calls.items()):
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {"__invalid_json__": slot["arguments"]}
            tool_calls.append({"id": slot["id"] or f"call_{index}", "name": slot["name"], "input": arguments})
        if finish == "length":
            tool_calls = []
        return Reply(text="".join(text_parts), tool_calls=tool_calls, native=None, stop_reason=finish)
