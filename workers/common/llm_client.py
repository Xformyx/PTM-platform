"""
LLM Client — unified interface with automatic Ollama → Cloud fallback.

Provider priority (auto mode):
  1. Ollama (local) — if OLLAMA_URL reachable and model installed
  2. OpenAI — if OPENAI_API_KEY set
  3. Gemini — if GEMINI_API_KEY set

Explicit provider selection via `provider` parameter still works,
but now includes **resilient fallback**: if the explicit provider fails,
the client automatically tries the full fallback chain (Ollama → OpenAI → Gemini).

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
        # Common mistake: bare "Gemini" or "gemini" without version
        if model_lower in ("gemini", "google gemini", "gemini flash", "gemini pro"):
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

    Explicit provider selection with resilient fallback:
      - provider="ollama": Ollama first, then cloud fallback on failure
      - provider="openai": OpenAI first, then Ollama/Gemini fallback on failure
      - provider="gemini": Gemini first, then Ollama/OpenAI fallback on failure
      - provider="auto": Auto-detect with full fallback chain
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
        self._fallback_enabled = True  # Always enable fallback for resilience
        self._requested_provider = provider or DEFAULT_PROVIDER

        # Resolve provider
        requested_provider = self._requested_provider

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
            f"LLMClient initialized: provider='{self.provider}', model='{self.model}', "
            f"fallback={'enabled' if self._fallback_enabled else 'disabled'}"
        )

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

        On failure, automatically tries the full fallback chain regardless
        of which provider was explicitly requested.
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
            # Cloud provider (openai or gemini)
            result = self._generate_openai_compatible(prompt, system_prompt, temp, tokens)

            # Resilient fallback: if explicit cloud provider fails, try others
            if result.startswith("[LLM Error") and self._fallback_enabled:
                logger.warning(
                    f"LLMClient: Primary provider '{self.provider}' (model='{self.model}') failed. "
                    f"Trying full fallback chain..."
                )
                fallback_result = self._try_full_fallback(prompt, system_prompt, temp, tokens)
                if fallback_result is not None:
                    return fallback_result

            return result

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

            # Cloud provider — check primary + fallback availability
            if self.api_key:
                return True
            # Even if primary has no key, fallback may be available
            if self._fallback_enabled:
                if _check_ollama_available(OLLAMA_URL, DEFAULT_MODEL):
                    return True
                if OPENAI_API_KEY or GEMINI_API_KEY:
                    return True
            return False
        except Exception:
            return False

    def _try_full_fallback(
        self, prompt: str, system_prompt: Optional[str], temp: float, max_tokens: int,
    ) -> Optional[str]:
        """Try ALL providers as fallback, skipping the one that already failed."""
        failed_provider = self.provider

        # Try Ollama (if not the failed provider)
        if failed_provider != "ollama":
            ollama_model = DEFAULT_MODEL
            if _check_ollama_available(OLLAMA_URL, ollama_model):
                logger.info(f"LLMClient: Falling back to Ollama ({ollama_model})")
                try:
                    # Temporarily switch to Ollama
                    orig_provider, orig_model, orig_url, orig_key = (
                        self.provider, self.model, self.base_url, self.api_key,
                    )
                    self.provider = "ollama"
                    self.model = ollama_model
                    self.base_url = OLLAMA_URL
                    self.api_key = ""

                    result = self._generate_ollama(prompt, system_prompt, temp, max_tokens)

                    # Restore original settings
                    self.provider, self.model, self.base_url, self.api_key = (
                        orig_provider, orig_model, orig_url, orig_key,
                    )

                    if not result.startswith("[LLM Error"):
                        return result
                except Exception as e:
                    logger.warning(f"Ollama fallback failed: {e}")
                    self.provider, self.model, self.base_url, self.api_key = (
                        orig_provider, orig_model, orig_url, orig_key,
                    )

        # Try OpenAI (if not the failed provider)
        if failed_provider != "openai" and OPENAI_API_KEY:
            logger.info(f"LLMClient: Falling back to OpenAI ({OPENAI_MODEL})")
            try:
                result = self._generate_openai_compat_with(
                    prompt, system_prompt, temp, max_tokens,
                    base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY, model=OPENAI_MODEL,
                )
                if not result.startswith("[LLM Error"):
                    return result
            except Exception as e:
                logger.warning(f"OpenAI fallback failed: {e}")

        # Try Gemini (if not the failed provider)
        if failed_provider != "gemini" and GEMINI_API_KEY:
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
                "[v95] %s: LLM call attempt %d/%d",
                section_name, attempt, max_retries,
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
                    "[v95] %s: LLM returned error on attempt %d",
                    section_name, attempt,
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
            "[v95] %s: All %d retries failed completely",
            section_name, max_retries,
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
