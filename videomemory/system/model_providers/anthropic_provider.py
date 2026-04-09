"""Anthropic model providers."""

import logging
import os
import time
from typing import Any, Optional, Type

from anthropic import Anthropic
from pydantic import BaseModel

from .base import BaseModelProvider

logger = logging.getLogger("AnthropicProvider")


class _BaseAnthropicProvider(BaseModelProvider):
    """Base Anthropic provider with structured-output parsing."""

    def __init__(self, api_key: str = None, model_name: str = None):
        if api_key is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
        super().__init__(api_key)
        self._model_name = str(model_name or "").strip()
        self._canonical_model_name = self._model_name
        self._api_model_name = self._model_name

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not found. Anthropic provider will fail.")
            self._client = None
        else:
            try:
                self._client = Anthropic(api_key=self.api_key)
                logger.info("Initialized Anthropic client for %s", self._model_name)
            except Exception as exc:
                logger.error("Failed to initialize Anthropic client: %s", exc)
                self._client = None

    def _sync_generate_content(
        self,
        image_base64: str,
        prompt: str,
        response_model: Type[BaseModel],
        usage_context: Optional[dict[str, Any]] = None,
    ) -> BaseModel:
        if not self._client:
            raise RuntimeError("Anthropic client not initialized. Check ANTHROPIC_API_KEY environment variable.")

        started_at = time.time()
        response = self._client.messages.parse(
            model=self._model_name,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            output_format=response_model,
        )
        latency_ms = round((time.time() - started_at) * 1000.0, 3)
        usage = getattr(response, "usage", None)
        input_tokens = self._coerce_optional_int(getattr(usage, "input_tokens", None))
        output_tokens = self._coerce_optional_int(getattr(usage, "output_tokens", None))
        total_tokens = None
        if input_tokens is not None or output_tokens is not None:
            total_tokens = int(input_tokens or 0) + int(output_tokens or 0)

        parsed_output = getattr(response, "parsed_output", None)
        if parsed_output is None:
            self._emit_usage_event(
                usage_context=usage_context,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                was_success=False,
            )
            raise RuntimeError("Anthropic returned no parsed structured output.")
        parsed = response_model.model_validate(parsed_output)
        self._emit_usage_event(
            usage_context=usage_context,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            was_success=True,
        )
        return parsed


class AnthropicClaudeSonnet46Provider(_BaseAnthropicProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key, model_name="claude-sonnet-4-6")


class AnthropicClaudeHaiku45Provider(_BaseAnthropicProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key, model_name="claude-haiku-4-5")


class AnthropicClaudeOpus46Provider(_BaseAnthropicProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key, model_name="claude-opus-4-6")
