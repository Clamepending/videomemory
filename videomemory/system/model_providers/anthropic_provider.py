"""Anthropic model providers."""

import json
import logging
import os
from typing import Type

from anthropic import Anthropic
from pydantic import BaseModel

from .base import BaseModelProvider

logger = logging.getLogger("AnthropicProvider")


class _BaseAnthropicProvider(BaseModelProvider):
    """Base class for Anthropic providers with shared functionality."""

    def __init__(self, api_key: str = None, model_name: str = None):
        if api_key is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
        super().__init__(api_key)
        self._model_name = model_name

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not found. Anthropic provider will fail.")
            self._client = None
        else:
            try:
                self._client = Anthropic(api_key=self.api_key)
                logger.info("Initialized Anthropic client for %s", self._model_name)
            except Exception as e:
                logger.error("Failed to initialize Anthropic client: %s", e)
                self._client = None

    def _sync_generate_content(
        self,
        image_base64: str,
        prompt: str,
        response_model: Type[BaseModel],
    ) -> BaseModel:
        if not self._client:
            raise RuntimeError("Anthropic client not initialized. Check ANTHROPIC_API_KEY environment variable.")

        schema = response_model.model_json_schema()
        json_guard = (
            "Return only a single valid JSON object that matches this schema exactly. "
            "Do not include markdown or extra text.\n"
            f"{json.dumps(schema)}"
        )

        resp = self._client.messages.create(
            model=self._model_name,
            max_tokens=1200,
            temperature=0.2,
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
                        {"type": "text", "text": json_guard},
                    ],
                }
            ],
        )

        text_chunks = [block.text for block in resp.content if getattr(block, "type", "") == "text"]
        raw = "".join(text_chunks).strip()
        if not raw:
            raise RuntimeError("Anthropic returned empty response text.")

        if raw.startswith("```") and raw.endswith("```"):
            lines = raw.splitlines()
            if len(lines) >= 2:
                raw = "\n".join(lines[1:-1]).strip()

        return response_model.model_validate_json(raw)


class Claude35SonnetProvider(_BaseAnthropicProvider):
    """Provider for Claude Sonnet."""

    def __init__(self, api_key: str = None):
        super().__init__(api_key=api_key, model_name="claude-sonnet-4-6")
