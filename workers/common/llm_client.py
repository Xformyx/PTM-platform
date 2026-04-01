"""
LLM Client — unified interface for Ollama / OpenAI / Gemini.

Provider selection:
  - "auto" (default): Ollama → OpenAI → Gemini 순서로 사용 가능한 첫 번째 provider 선택
  - "ollama" / "openai" / "gemini": 해당 provider만 사용, 실패 시 fallback 없음

Explicit provider를 선택한 경우 해당 provider로만 시도하며,
실패 시 다른 provider로 자동 전환하지 않습니다.
이는 사용자가 어떤 모델로 리포트가 생성되었는지 명확히 확인할 수 있도록 하기 위함입니다.

Environment variables:
  OLLAMA_URL       — Ollama server URL (default: http://host.docker.internal:11434)
  LLM_MODEL        — Default model name (default: gemma3:27b)
  OPENAI_API_KEY   — OpenAI API key
  OPENAI_MODEL     — OpenAI model (default: gpt-4.1-mini)
  GEMINI_API_KEY   — Gemini API key
  GEMINI_MODEL     — Gemini model (default: gemini-2.5-flash)
  LLM_PROVIDER     — Force provider: "ollama", "openai", "gemini", or "auto" (default: auto)
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gemma3:27b")

# Cloud settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# Global provider preference
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "auto")

# Known valid model names per provider (for validation / normalization)
_KNOWN_GEMINI_MODELS = {
    "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
    "gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.0-pro",
}
_KNOWN_OPENAI_MODELS = {
    "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
    "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo",
    "o3-mini",
}


def _infer_provider_from_model(provider: str, model: Optional[str]) -> str:
    """Infer provider from model when provider is ollama/auto but model is a cloud model."""
    if not model or not model.strip():
        return provider or "ollama"
    m = model.strip().lower()
    if provider in ("ollama", "auto") or not provider:
        if m in _KNOWN_GEMINI_MODELS or m.startswith("gemini-"):
            return "gemini"
        if m in _KNOWN_OPENAI_MODELS or m.startswith("gpt-") or "gpt-4" in m:
            return "openai"
    return provider or "ollama"


def _normalize_model_name(provider: str, model: str) -> str:
    """Normalize and validate model name for the given provider.

    Catches common mistakes like using display names ("Gemini") instead of
    API model IDs ("gemini-2.5-flash").
    """
    if not model:
        return model

    model_lower = model.strip().lower()

    if provider == "gemini":
        # Exact match
        if model in _KNOWN_GEMINI_MODELS:
            return model
        # Case-insensitive match
        for known in _KNOWN_GEMINI_MODELS:
            if model_lower == known.lower():
                logger.info(f"Model name normalized: '{model}' → '{known}'")
                return known
        # Common mistake: bare "Gemini" or display names (e.g. "Gemini_Joseph")
        _DISPLAY_NAME_ALIASES = (
            "gemini", "google gemini", "gemini flash", "gemini pro",
            "gemini_joseph", "joseph",  # DB에 표시명이 model_id로 잘못 등록된 경우
        )
        if model_lower in _DISPLAY_NAME_ALIASES:
            fallback_model = GEMINI_MODEL  # Use env default (gemini-2.5-flash)
            logger.warning(
                f"Invalid Gemini model name '{model}' — "
                f"normalized to '{fallback_model}'. "
                f"Valid names: {sorted(_KNOWN_GEMINI_MODELS)}"
            )
            return fallback_model
        # Unknown but specific — pass through (may be a new model)
        logger.info(f"Gemini model '{model}' not in known list, passing through as-is")
        return model

    elif provider == "openai":
        if model in _KNOWN_OPENAI_MODELS:
            return model
        for known in _KNOWN_OPENAI_MODELS:
            if model_lower == known.lower():
                logger.info(f"Model name normalized: '{model}' → '{known}'")
                return known
        # Common mistake: bare "OpenAI" or "GPT"
        if model_lower in ("openai", "gpt", "chatgpt"):
            fallback_model = OPENAI_MODEL
            logger.warning(
                f"Invalid OpenAI model name '{model}' — "
                f"normalized to '{fallback_model}'"
            )
            return fallback_model
        return model

    return model


def _check_ollama_available(base_url: str, model: str) -> bool:
    """Check if Ollama is reachable and has the requested model."""
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=5)
        if r.status_code != 200:
            return False
        models = [m.get("name", "") for m in r.json().get("models", [])]
        # Check exact match
        if model in models:
            return True
        # Also check base name match (e.g., "gemma3" matches "gemma3:27b")
        base_name = model.split(":")[0]
        for m in models:
            if m.startswith(base_name):
                return True
        return False
    except Exception:
        return False


class LLMClient:
    """Unified LLM client — no automatic fallback on explicit provider selection.

    - "auto" mode: auto-detect best available provider (Ollama → OpenAI → Gemini)
    - Explicit provider: use ONLY that provider. On failure, return clear error.

    This ensures the user always knows which model generated the report.
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
        self._requested_provider = provider or DEFAULT_PROVIDER

        # Resolve provider — infer from model when provider is ollama but model is cloud (e.g. gemini-2.5-flash)
        requested_provider = _infer_provider_from_model(self._requested_provider, model)

        if requested_provider == "auto":
            self._init_auto(model, base_url, api_key)
        elif requested_provider == "ollama":
            self.provider = "ollama"
            self.model = model or DEFAULT_MODEL
            self.base_url = base_url or OLLAMA_URL
            self.api_key = ""
        elif requested_provider == "openai":
            self.provider = "openai"
            self.model = _normalize_model_name("openai", model or OPENAI_MODEL)
            self.base_url = base_url or OPENAI_BASE_URL
            self.api_key = api_key or OPENAI_API_KEY
        elif requested_provider == "gemini":
            self.provider = "gemini"
            self.model = _normalize_model_name("gemini", model or GEMINI_MODEL)
            self.base_url = base_url or GEMINI_BASE_URL
            self.api_key = api_key or GEMINI_API_KEY
        else:
            raise ValueError(f"Unknown LLM provider: {requested_provider}")

        logger.info(
            f"LLMClient initialized: provider='{self.provider}', model='{self.model}'"
        )

    def _init_auto(self, model: Optional[str], base_url: Optional[str], api_key: Optional[str]):
        """Auto-detect best available provider (Ollama → OpenAI → Gemini)."""
        ollama_url = base_url or OLLAMA_URL
        ollama_model = model or DEFAULT_MODEL

        # Try Ollama first
        if _check_ollama_available(ollama_url, ollama_model):
            self.provider = "ollama"
            self.model = ollama_model
            self.base_url = ollama_url
            self.api_key = ""
            logger.info(f"LLMClient [auto]: selected Ollama ({self.model})")
            return

        # Try OpenAI
        if api_key or OPENAI_API_KEY:
            self.provider = "openai"
            self.model = OPENAI_MODEL
            self.base_url = OPENAI_BASE_URL
            self.api_key = api_key or OPENAI_API_KEY
            logger.info(f"LLMClient [auto]: Ollama not available, selected OpenAI ({self.model})")
            return

        # Try Gemini
        if GEMINI_API_KEY:
            self.provider = "gemini"
            self.model = GEMINI_MODEL
            self.base_url = GEMINI_BASE_URL
            self.api_key = GEMINI_API_KEY
            logger.info(f"LLMClient [auto]: Ollama not available, selected Gemini ({self.model})")
            return

        # No provider available — set Ollama as default (will fail gracefully with clear error)
        self.provider = "ollama"
        self.model = ollama_model
        self.base_url = ollama_url
        self.api_key = ""
        logger.warning("LLMClient [auto]: No LLM provider available (Ollama unreachable, no API keys)")

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using the configured LLM provider.

        No automatic fallback — if the selected provider fails, returns a clear
        error message so the user can identify and fix the issue.
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        if self.provider == "ollama":
            return self._generate_ollama(prompt, system_prompt, temp, tokens)
        else:
            return self._generate_openai_compatible(prompt, system_prompt, temp, tokens)

    def is_available(self) -> bool:
        """Check if the configured LLM provider is available."""
        try:
            if self.provider == "ollama":
                return _check_ollama_available(self.base_url, self.model)
            # Cloud provider — check if API key is set
            if self.api_key:
                return True
            return False
        except Exception:
            return False

    def get_provider_info(self) -> str:
        """Return a human-readable string describing the current provider/model."""
        return f"{self.provider}:{self.model}"

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
                error_msg = (
                    f"Ollama returned HTTP {r.status_code} for model '{self.model}'. "
                    f"Response: {body}"
                )
                logger.error(error_msg)
                return f"[LLM Error: {error_msg}]"
            return r.json().get("response", "").strip()
        except requests.Timeout:
            error_msg = (
                f"Ollama request timed out (600s) for model '{self.model}' "
                f"at {self.base_url}. The model may be too slow for this prompt size."
            )
            logger.error(error_msg)
            return f"[LLM Error: {error_msg}]"
        except requests.ConnectionError:
            error_msg = (
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Please verify: (1) Ollama is running ('ollama serve'), "
                f"(2) The URL is correct, "
                f"(3) Docker can reach host.docker.internal."
            )
            logger.error(error_msg)
            return f"[LLM Error: {error_msg}]"
        except Exception as e:
            error_msg = f"Ollama generation failed for model '{self.model}': {e}"
            logger.error(error_msg)
            return f"[LLM Error: {error_msg}]"

    # ------------------------------------------------------------------
    # v95: Retry wrapper for minimum word-count enforcement
    # ------------------------------------------------------------------

    def generate_with_retry(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        min_words: int = 200,
        section_name: str = "Section",
        max_retries: int = 3,
        retry_boost_prompt: str = "",
    ) -> Optional[str]:
        """Generate text with automatic retry when output is too short.

        If the LLM returns ``None`` or fewer than *min_words* words, retries
        up to *max_retries* times with progressively stronger instructions.

        Returns the generated text, or ``None`` if all retries fail.
        """
        best_result: Optional[str] = None
        best_word_count = 0
        base_temp = temperature if temperature is not None else self.temperature

        for attempt in range(1, max_retries + 1):
            logger.info(
                "[v95] %s: LLM call attempt %d/%d (provider=%s, model=%s)",
                section_name, attempt, max_retries, self.provider, self.model,
            )

            current_prompt = prompt
            if attempt > 1:
                boost = (
                    f"\n## CRITICAL: YOUR PREVIOUS RESPONSE WAS TOO SHORT "
                    f"(attempt {attempt}/{max_retries})\n"
                    f"Your previous response contained only {best_word_count} words, "
                    f"which is FAR below the minimum requirement of {min_words} words.\n"
                    f"You MUST write a comprehensive, detailed {section_name} section "
                    f"with AT LEAST {min_words} words.\n"
                    f"Do NOT summarize — provide FULL detailed analysis with specific "
                    f"protein names, Log2FC values, and biological interpretation.\n"
                    f"Every subsection MUST contain at least 2-3 sentences of "
                    f"substantive content.\n"
                )
                if retry_boost_prompt:
                    boost += f"\n{retry_boost_prompt}\n"
                current_prompt = prompt + boost

            current_temp = min(base_temp + (attempt - 1) * 0.1, 0.8)

            result = self.generate(
                prompt=current_prompt,
                system_prompt=system_prompt,
                temperature=current_temp,
                max_tokens=max_tokens,
            )

            if result is None or result.startswith("[LLM Error"):
                logger.warning(
                    "[v95] %s: LLM returned error on attempt %d: %s",
                    section_name, attempt, result[:200] if result else "None",
                )
                continue

            word_count = len(result.strip().split())
            logger.info(
                "[v95] %s: Attempt %d produced %d words (min: %d)",
                section_name, attempt, word_count, min_words,
            )

            if word_count > best_word_count:
                best_result = result
                best_word_count = word_count

            if word_count >= min_words:
                logger.info(
                    "[v95] %s: Accepted with %d words on attempt %d",
                    section_name, word_count, attempt,
                )
                return result

            logger.warning(
                "[v95] %s: %d words < %d minimum, retrying...",
                section_name, word_count, min_words,
            )

        if best_result and best_word_count > 0:
            logger.warning(
                "[v95] %s: All %d retries exhausted. Using best result (%d words)",
                section_name, max_retries, best_word_count,
            )
            return best_result

        logger.error(
            "[v95] %s: All %d retries failed completely (provider=%s, model=%s)",
            section_name, max_retries, self.provider, self.model,
        )
        return None

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

        # v9.30: Log prompt size for debugging
        total_prompt_chars = len(prompt) + (len(system_prompt) if system_prompt else 0)
        logger.info(
            f"[LLM] {model}@{base_url}: prompt={total_prompt_chars:,} chars, "
            f"max_tokens={max_tokens}, temp={temp}"
        )

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

        # v9.30: Increase timeout for large prompts (600s for cloud APIs)
        timeout = 600

        try:
            r = requests.post(
                f"{base_url}/chat/completions",
                json=payload, headers=headers, timeout=timeout,
            )
            r.raise_for_status()
            result = r.json()["choices"][0]["message"]["content"].strip()
            logger.info(
                f"[LLM] {model}: success, response={len(result):,} chars, "
                f"{len(result.split()):,} words"
            )
            return result
        except requests.HTTPError as e:
            status = getattr(r, 'status_code', 'unknown')
            body = getattr(r, 'text', '')[:500]
            error_msg = (
                f"{model}@{base_url} returned HTTP {status}. "
                f"Prompt size: {total_prompt_chars:,} chars. "
                f"Response: {body}. "
                f"Please check: (1) model name is a valid API model ID "
                f"(e.g. 'gemini-2.5-flash', not 'Gemini'), "
                f"(2) API key is valid, "
                f"(3) prompt is within context window limits."
            )
            logger.error(f"OpenAI-compatible generation failed: {error_msg}")
            return f"[LLM Error: {error_msg}]"
        except requests.ConnectionError:
            error_msg = (
                f"Cannot connect to {base_url}. "
                f"Please check network connectivity and API endpoint URL."
            )
            logger.error(error_msg)
            return f"[LLM Error: {error_msg}]"
        except requests.Timeout:
            error_msg = (
                f"Request to {model}@{base_url} timed out ({timeout}s). "
                f"Prompt size: {total_prompt_chars:,} chars. "
                f"The prompt may be too large or the API may be overloaded."
            )
            logger.error(error_msg)
            return f"[LLM Error: {error_msg}]"
        except Exception as e:
            error_msg = (
                f"OpenAI-compatible generation failed ({model}@{base_url}): {e}. "
                f"Prompt size: {total_prompt_chars:,} chars."
            )
            logger.error(error_msg)
            return f"[LLM Error: {error_msg}]"
