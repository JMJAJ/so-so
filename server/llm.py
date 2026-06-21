"""
Multi-provider LLM abstraction layer.
Supports: Ollama, OpenAI, Anthropic, Google Gemini, OpenRouter.
"""

import requests
from typing import Protocol


class LLMProvider(Protocol):
    def chat(self, system: str, user: str) -> str: ...
    @property
    def model_name(self) -> str: ...


# ── Ollama (local) ──

class OllamaProvider:
    def __init__(self, model: str = "minimax-m3:cloud", base_url: str = "http://localhost:11434", num_ctx: int = 8192):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._num_ctx = num_ctx

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.5, "num_ctx": self._num_ctx},
            },
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self._base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []


# ── OpenAI ──

class OpenAIProvider:
    def __init__(self, model: str = "gpt-4o-mini", api_key: str = "", base_url: str = ""):
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.5,
                "max_tokens": 16384,
            },
            timeout=120,
        )
        if not resp.ok:
            body = resp.text[:500]
            raise RuntimeError(f"HTTP {resp.status_code}: {body}")
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"No choices in response: {data.get('id', 'unknown')}")
        choice = choices[0]
        finish = choice.get("finish_reason", "")
        message = choice.get("message", {})
        content = message.get("content", "")
        if not content:
            content = message.get("reasoning_content", "")
        if not content:
            usage = data.get("usage", {})
            raise RuntimeError(f"Empty response (finish_reason={finish}, tokens: in={usage.get('prompt_tokens', '?')}, out={usage.get('completion_tokens', '?')})")
        return content


# ── Anthropic ──

class AnthropicProvider:
    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str = ""):
        self._model = model
        self._api_key = api_key

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": 4096,
                "system": system,
                "messages": [
                    {"role": "user", "content": user},
                ],
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


# ── Google Gemini ──

class GeminiProvider:
    def __init__(self, model: str = "gemini-2.0-flash", api_key: str = ""):
        self._model = model
        self._api_key = api_key

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent",
            headers={"Content-Type": "application/json"},
            params={"key": self._api_key},
            json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {
                    "temperature": 0.5,
                    "maxOutputTokens": 4096,
                },
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


# ── OpenRouter ──

class OpenRouterProvider:
    def __init__(self, model: str = "google/gemini-2.0-flash-exp:free", api_key: str = ""):
        self._model = model
        self._api_key = api_key

    @property
    def model_name(self) -> str:
        return self._model

    def chat(self, system: str, user: str) -> str:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "NEXUS Trading Terminal",
            },
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.5,
                "max_tokens": 4096,
            },
            timeout=120,
        )
        if not resp.ok:
            body = resp.text[:500]
            raise RuntimeError(f"HTTP {resp.status_code}: {body}")
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            print(f"[llm] No choices in response: {data}")
            return ""
        choice = choices[0]
        finish = choice.get("finish_reason", "")
        content = choice.get("message", {}).get("content", "")
        if not content:
            print(f"[llm] Empty content, finish_reason={finish}, usage={data.get('usage')}")
        return content or ""


# ── Factory ──

PROVIDERS = {
    "ollama": {
        "name": "Ollama (Local)",
        "needs_key": False,
        "models": [
            "minimax-m3:cloud",
            "llama3.1:8b",
            "llama3.1:70b",
            "mistral:7b",
            "mixtral:8x7b",
            "qwen2.5:14b",
            "deepseek-r1:14b",
        ],
    },
    "lmstudio": {
        "name": "LM Studio (Local)",
        "needs_key": False,
        # "models_url": "http://localhost:1234/api/v1/models",
        "models": [
            "qwen2.5-7b-instruct-1m",
            "qwen3-vl-8b-instruct",
            "qwen3.5-9b-glm5.1-distill-v1",
            "text-embedding-nomic-embed-text-v1.5",
        ],
    },
    "openai": {
        "name": "OpenAI",
        "needs_key": True,
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "o4-mini",
        ],
    },
    "anthropic": {
        "name": "Anthropic",
        "needs_key": True,
        "models": [
            "claude-sonnet-4-20250514",
            "claude-3-5-haiku-20241022",
            "claude-opus-4-20250514",
        ],
    },
    "gemini": {
        "name": "Google Gemini",
        "needs_key": True,
        "models": [
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-1.5-pro",
        ],
    },
    "openrouter": {
        "name": "OpenRouter",
        "needs_key": True,
        "models": [
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.1-8b-instruct:free",
            "deepseek/deepseek-chat",
            "anthropic/claude-sonnet-4",
            "openai/gpt-4o-mini",
            "google/gemini-2.5-pro",
        ],
    },
    "groq": {
        "name": "Groq (Free, Fast)",
        "needs_key": True,
        "models": [
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "qwen/qwen3-32b",
            "openai/gpt-oss-120b",
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "needs_key": True,
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    },
}


def create_provider(provider: str, model: str, api_key: str = "", base_url: str = "", num_ctx: int = 8192) -> LLMProvider:
    if provider == "ollama":
        return OllamaProvider(model=model, base_url=base_url or "http://localhost:11434", num_ctx=num_ctx)
    elif provider == "lmstudio":
        return OpenAIProvider(model=model, api_key=api_key or "lm-studio", base_url=base_url or "http://localhost:1234/v1")
    elif provider == "openai":
        return OpenAIProvider(model=model, api_key=api_key, base_url=base_url)
    elif provider == "anthropic":
        return AnthropicProvider(model=model, api_key=api_key)
    elif provider == "gemini":
        return GeminiProvider(model=model, api_key=api_key)
    elif provider == "openrouter":
        return OpenRouterProvider(model=model, api_key=api_key)
    elif provider == "groq":
        return OpenAIProvider(model=model, api_key=api_key, base_url=base_url or "https://api.groq.com/openai/v1")
    elif provider == "deepseek":
        return OpenAIProvider(model=model, api_key=api_key, base_url=base_url or "https://api.deepseek.com/v1")
    else:
        raise ValueError(f"Unknown provider: {provider}")
