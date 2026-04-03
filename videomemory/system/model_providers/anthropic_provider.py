"""Anthropic model providers."""

import logging
import os
from typing import Type

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
    ) -> BaseModel:
        if not self._client:
            raise RuntimeError("Anthropic client not initialized. Check ANTHROPIC_API_KEY environment variable.")

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

        parsed_output = getattr(response, "parsed_output", None)
        if parsed_output is None:
            raise RuntimeError("Anthropic returned no parsed structured output.")
        return response_model.model_validate(parsed_output)


class AnthropicClaudeSonnet46Provider(_BaseAnthropicProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key, model_name="claude-sonnet-4-6")


class AnthropicClaudeHaiku45Provider(_BaseAnthropicProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key, model_name="claude-haiku-4-5")


class AnthropicClaudeOpus46Provider(_BaseAnthropicProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key, model_name="claude-opus-4-6")
