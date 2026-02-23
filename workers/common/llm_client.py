"""
LLM Client — unified interface with automatic Ollama → Cloud fallback.

Provider priority (auto mode):
  1. Ollama (local) — if OLLAMA_URL reachable and model installed
  2. OpenAI — if OPENAI_API_KEY set
  3. Gemini — if GEMINI_API_KEY set

Explicit provider selection via `provider` parameter still works.

Environment variables:
  OLLAMA_URL       — Ollama server URL (default: http://host.docker.internal:11434)
  LLM_MODEL        — Default model name (default: gemma3:27b)
  OPENAI_API_KEY   — OpenAI API key for cloud fallback
  OPENAI_MODEL     — OpenAI model (default: gpt-4.1-mini)
  GEMINI_API_KEY   — Gemini API key for cloud fallback
  GEMINI_MODEL     — Gemini model (default: gemini-2.5-flash)
  LLM_PROVIDER     — Force provider: "ollama", "openai", "gemini", or "auto" (default: auto)
"""

import json
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gemma3:27b")

# Cloud fallback settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# Global provider preference
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "auto")


def _check_ollama_available(base_url: str, model: str) -> bool:
    """Check if Ollama is reachable and has the requested model."""
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=5)
        if r.status_code != 200:
            return False
        models = [m.get("name", "") for m in r.json().get("models", [])]
        # Check exact match or base name match (e.g., "gemma3:27b" matches "gemma3:27b")
        if model in models:
            return True
        # Also check without tag suffix
        base_name = model.split(":")[0]
        for m in models:
            if m.startswith(base_name):
                return True
        return False
    except Exception:
        return False


class LLMClient:
    """Unified LLM client with automatic Ollama → Cloud fallback.

    In "auto" mode (default), the client:
      1. Tries Ollama first (if reachable and model available)
      2. Falls back to OpenAI (if OPENAI_API_KEY set)
      3. Falls back to Gemini (if GEMINI_API_KEY set)
      4. Returns error if no provider available

    Explicit provider selection:
      - provider="ollama": Ollama only (no fallback)
      - provider="openai": OpenAI only
      - provider="gemini": Gemini only
      - provider="auto": Auto-detect with fallback chain
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.6,
        max_tokens: int = 4096,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._fallback_enabled = False

        # Resolve provider
        requested_provider = provider or DEFAULT_PROVIDER

        if requested_provider == "auto":
            self._init_auto(model, base_url, api_key)
        elif requested_provider == "ollama":
            self.provider = "ollama"
            self.model = model or DEFAULT_MODEL
            self.base_url = base_url or OLLAMA_URL
            self.api_key = ""
        elif requested_provider == "openai":
            self.provider = "openai"
            self.model = model or OPENAI_MODEL
            self.base_url = base_url or OPENAI_BASE_URL
            self.api_key = api_key or OPENAI_API_KEY
        elif requested_provider == "gemini":
            self.provider = "gemini"
            self.model = model or GEMINI_MODEL
            self.base_url = base_url or GEMINI_BASE_URL
            self.api_key = api_key or GEMINI_API_KEY
        else:
            raise ValueError(f"Unknown LLM provider: {requested_provider}")

    def _init_auto(self, model: Optional[str], base_url: Optional[str], api_key: Optional[str]):
        """Auto-detect best available provider."""
        ollama_url = base_url or OLLAMA_URL
        ollama_model = model or DEFAULT_MODEL

        # Try Ollama first
        if _check_ollama_available(ollama_url, ollama_model):
            self.provider = "ollama"
            self.model = ollama_model
            self.base_url = ollama_url
            self.api_key = ""
            self._fallback_enabled = True
            logger.info(f"LLMClient: auto-selected Ollama ({self.model}) with cloud fallback enabled")
            return

        # Try OpenAI
        if api_key or OPENAI_API_KEY:
            self.provider = "openai"
            self.model = OPENAI_MODEL
            self.base_url = OPENAI_BASE_URL
            self.api_key = api_key or OPENAI_API_KEY
            logger.info(f"LLMClient: Ollama not available, using OpenAI ({self.model})")
            return

        # Try Gemini
        if GEMINI_API_KEY:
            self.provider = "gemini"
            self.model = GEMINI_MODEL
            self.base_url = GEMINI_BASE_URL
            self.api_key = GEMINI_API_KEY
            logger.info(f"LLMClient: Ollama not available, using Gemini ({self.model})")
            return

        # No provider available — set Ollama as default (will fail gracefully)
        self.provider = "ollama"
        self.model = ollama_model
        self.base_url = ollama_url
        self.api_key = ""
        logger.warning("LLMClient: No LLM provider available (Ollama unreachable, no API keys)")

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using the configured LLM provider.

        If in auto mode with Ollama as primary, falls back to cloud on failure.
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        if self.provider == "ollama":
            result = self._generate_ollama(prompt, system_prompt, temp, tokens)

            # Auto-fallback to cloud if Ollama fails
            if result.startswith("[LLM Error") and self._fallback_enabled:
                fallback_result = self._try_cloud_fallback(prompt, system_prompt, temp, tokens)
                if fallback_result is not None:
                    return fallback_result

            return result
        else:
            return self._generate_openai_compatible(prompt, system_prompt, temp, tokens)

    def is_available(self) -> bool:
        """Check if any LLM provider is available."""
        try:
            if self.provider == "ollama":
                if _check_ollama_available(self.base_url, self.model):
                    return True
                # Check fallback availability
                if self._fallback_enabled:
                    if OPENAI_API_KEY or GEMINI_API_KEY:
                        return True
                return False
            return bool(self.api_key)
        except Exception:
            return False

    def _try_cloud_fallback(
        self, prompt: str, system_prompt: Optional[str], temp: float, max_tokens: int,
    ) -> Optional[str]:
        """Try cloud providers as fallback when Ollama fails."""
        # Try OpenAI
        if OPENAI_API_KEY:
            logger.info(f"LLMClient: Ollama failed, falling back to OpenAI ({OPENAI_MODEL})")
            try:
                result = self._generate_openai_compat_with(
                    prompt, system_prompt, temp, max_tokens,
                    base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY, model=OPENAI_MODEL,
                )
                if not result.startswith("[LLM Error"):
                    return result
            except Exception as e:
                logger.warning(f"OpenAI fallback failed: {e}")

        # Try Gemini
        if GEMINI_API_KEY:
            logger.info(f"LLMClient: Falling back to Gemini ({GEMINI_MODEL})")
            try:
                result = self._generate_openai_compat_with(
                    prompt, system_prompt, temp, max_tokens,
                    base_url=GEMINI_BASE_URL, api_key=GEMINI_API_KEY, model=GEMINI_MODEL,
                )
                if not result.startswith("[LLM Error"):
                    return result
            except Exception as e:
                logger.warning(f"Gemini fallback failed: {e}")

        return None

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
        return self._generate_openai_compat_with(
            prompt, system_prompt, temp, max_tokens,
            base_url=self.base_url, api_key=self.api_key, model=self.model,
        )

    def _generate_openai_compat_with(
        self, prompt: str, system_prompt: Optional[str], temp: float, max_tokens: int,
        base_url: str, api_key: str, model: str,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tokens,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        try:
            r = requests.post(
                f"{base_url}/chat/completions",
                json=payload, headers=headers, timeout=300,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"OpenAI-compatible generation failed ({model}@{base_url}): {e}")
            return f"[LLM Error: {e}]"
