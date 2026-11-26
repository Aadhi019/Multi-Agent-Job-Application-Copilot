from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from groq import APIConnectionError, APIStatusError, APITimeoutError, Groq, RateLimitError
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GroqServiceError(Exception):
    """Base exception for Groq service failures."""


class GroqConfigurationError(GroqServiceError):
    """Raised when GROQ_API_KEY is missing."""


class GroqAPIError(GroqServiceError):
    """Raised when Groq API calls fail after retries."""


class GroqValidationError(GroqServiceError):
    """Raised when LLM output fails Pydantic validation even after repair."""


@dataclass
class GroqResult(Generic[T]):
    data: T
    raw_text: str
    model: str
    latency_ms: int
    tokens_used: int | None
    attempts: int
    repaired: bool = False


def _strip_json_fences(raw: str) -> str:
    cleaned = raw.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return cleaned


class GroqService:
    """Wrapper around Groq chat completions with retries, timeouts, and JSON validation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        client: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.model = model or settings.groq_model or "llama-3.3-70b-versatile"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._client = client

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip() and not self.api_key.startswith("your_"))

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.is_configured:
            raise GroqConfigurationError(
                "GROQ_API_KEY is not configured. Set it in your .env file to enable AI agents."
            )
        self._client = Groq(api_key=self.api_key, timeout=self.timeout_seconds)
        return self._client

    def _call_with_retries(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> tuple[str, int | None, int]:
        client = self._get_client()
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 2):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": self.timeout_seconds,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                total_tokens = getattr(usage, "total_tokens", None) if usage else None
                return content, total_tokens, attempt
            except (RateLimitError, APIConnectionError, APITimeoutError, TimeoutError) as exc:
                last_error = exc
                logger.warning(
                    "Groq transient error on attempt %d/%d: %s",
                    attempt,
                    self.max_retries + 1,
                    exc,
                )
            except APIStatusError as exc:
                if getattr(exc, "status_code", 500) in (429, 500, 502, 503, 504):
                    last_error = exc
                    logger.warning(
                        "Groq status %s on attempt %d/%d",
                        getattr(exc, "status_code", "unknown"),
                        attempt,
                        self.max_retries + 1,
                    )
                else:
                    raise GroqAPIError(f"Groq API error: {exc}") from exc
            except GroqServiceError:
                raise
            except Exception as exc:
                raise GroqAPIError(f"Unexpected Groq client error: {exc}") from exc

            if attempt <= self.max_retries and self.backoff_seconds > 0:
                time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))

        raise GroqAPIError(f"Groq API failed after {self.max_retries + 1} attempts: {last_error}")

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> tuple[str, int, int | None]:
        started = time.perf_counter()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        text, tokens, _ = self._call_with_retries(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=False
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return text, latency_ms, tokens

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        *,
        temperature: float = 0.1,
        max_tokens: int = 3072,
    ) -> GroqResult[T]:
        """Call Groq in JSON mode, validate with Pydantic, and run one repair retry if invalid."""
        started = time.perf_counter()
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        enriched_system = (
            f"{system_prompt.strip()}\n\n"
            "You MUST respond with a single valid JSON object matching this JSON Schema:\n"
            f"{schema_json}"
        )

        messages = [
            {"role": "system", "content": enriched_system},
            {"role": "user", "content": user_prompt},
        ]

        raw_text, tokens_first, attempts_first = self._call_with_retries(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=True
        )
        total_tokens = tokens_first
        total_attempts = attempts_first

        try:
            parsed = response_model.model_validate_json(_strip_json_fences(raw_text))
            latency_ms = int((time.perf_counter() - started) * 1000)
            return GroqResult(
                data=parsed,
                raw_text=raw_text,
                model=self.model,
                latency_ms=latency_ms,
                tokens_used=total_tokens,
                attempts=total_attempts,
                repaired=False,
            )
        except (ValidationError, ValueError) as first_err:
            logger.info("Groq JSON validation failed; attempting one automatic repair retry")
            repair_messages = [
                {"role": "system", "content": enriched_system},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": raw_text},
                {
                    "role": "user",
                    "content": (
                        "Your previous JSON response failed schema validation with this error:\n"
                        f"{first_err}\n\n"
                        "Return ONLY a corrected JSON object that strictly satisfies the schema."
                    ),
                },
            ]
            repaired_raw, tokens_second, attempts_second = self._call_with_retries(
                repair_messages, temperature=0.0, max_tokens=max_tokens, json_mode=True
            )
            total_attempts += attempts_second
            if tokens_second is not None:
                total_tokens = (total_tokens or 0) + tokens_second

            try:
                parsed = response_model.model_validate_json(_strip_json_fences(repaired_raw))
                latency_ms = int((time.perf_counter() - started) * 1000)
                return GroqResult(
                    data=parsed,
                    raw_text=repaired_raw,
                    model=self.model,
                    latency_ms=latency_ms,
                    tokens_used=total_tokens,
                    attempts=total_attempts,
                    repaired=True,
                )
            except (ValidationError, ValueError) as second_err:
                raise GroqValidationError(
                    f"LLM output failed validation after repair retry: {second_err}"
                ) from second_err
