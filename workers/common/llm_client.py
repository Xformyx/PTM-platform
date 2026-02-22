"""
LLM Client — unified interface for Ollama (default) and Cloud LLMs.

Supports:
  - Ollama (local, default)
  - OpenAI (optional)
  - Google Gemini (optional, via OpenAI-compatible endpoint)
"""

import json
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen2.5:32b")


class LLMClient:
    """Unified LLM client with Ollama as default provider."""

    def __init__(
        self,
        provider: str = "ollama",
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ):
        self.provider = provider
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens

        if provider == "ollama":
            self.base_url = base_url or OLLAMA_URL
        elif provider == "openai":
            self.base_url = base_url or "https://api.openai.com/v1"
            self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        elif provider == "gemini":
            self.base_url = base_url or "https://generativelanguage.googleapis.com/v1beta/openai"
            self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        if self.provider == "ollama":
            return self._generate_ollama(prompt, system_prompt, temp, tokens)
        else:
            return self._generate_openai_compatible(prompt, system_prompt, temp, tokens)

    def is_available(self) -> bool:
        try:
            if self.provider == "ollama":
                r = requests.get(f"{self.base_url}/api/tags", timeout=5)
                if r.status_code != 200:
                    return False
                models = [m.get("name", "") for m in r.json().get("models", [])]
                if self.model not in models:
                    logger.warning(
                        f"Model '{self.model}' not found in Ollama. Available: {models}"
                    )
                    return False
                return True
            return bool(self.api_key)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    def _generate_ollama(self, prompt: str, system_prompt: Optional[str], temp: float, max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temp,
                "num_predict": max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            r = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=600)
            if r.status_code != 200:
                body = r.text[:500]
                logger.error(f"Ollama returned {r.status_code} for model '{self.model}': {body}")
                return f"[LLM Error: {r.status_code} - {body}]"
            return r.json().get("response", "").strip()
        except requests.Timeout:
            logger.error(f"Ollama request timed out for model '{self.model}'")
            return "[LLM Error: Request timed out]"
        except requests.ConnectionError:
            logger.error(f"Cannot connect to Ollama at {self.base_url}")
            return f"[LLM Error: Cannot connect to Ollama at {self.base_url}]"
        except Exception as e:
            logger.error(f"Ollama generation failed for model '{self.model}': {e}")
            return f"[LLM Error: {e}]"

    # ------------------------------------------------------------------
    # OpenAI-compatible (OpenAI, Gemini)
    # ------------------------------------------------------------------

    def _generate_openai_compatible(self, prompt: str, system_prompt: Optional[str], temp: float, max_tokens: int) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload, headers=headers, timeout=300,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"OpenAI-compatible generation failed: {e}")
            return f"[LLM Error: {e}]"
