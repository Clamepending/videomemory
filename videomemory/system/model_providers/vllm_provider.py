"""Local vLLM model provider (OpenAI-compatible API)."""

import os
import logging
from typing import Type, Optional
import httpx
from pydantic import BaseModel
from .base import BaseModelProvider

logger = logging.getLogger('VLLMProvider')


def _get_base_url() -> str:
    """Get local vLLM base URL from env/settings."""
    url = (
        os.getenv("LOCAL_MODEL_BASE_URL")
        or os.getenv("VLLM_LOCAL_URL")
        or "http://localhost:8100"
    ).rstrip("/")
    return url


class LocalVLLMProvider(BaseModelProvider):
    """Provider for local vLLM (any model the server is serving).
    
    Uses OpenAI-compatible API. No API key required.
    Base URL from LOCAL_MODEL_BASE_URL or VLLM_LOCAL_URL (set by start_vllm.sh).
    Resolves the actual model ID from the server via /v1/models.
    """

    def __init__(self):
        super().__init__(api_key=None)
        self._base_url = _get_base_url()
        # Fallback when /v1/models is unreachable. Match start_vllm.sh default.
        self._fallback_model = os.getenv("VLLM_LOCAL_MODEL", "Qwen/Qwen3-VL-8B-Instruct-FP8")
        self._model_id: Optional[str] = None  # Resolved from server on first request
        # Signal "initialized" so VideoStreamIngestor doesn't falsely warn.
        self._client = True
        logger.info("Initialized local vLLM provider at %s", self._base_url)

    def _resolve_model_id(self, client: httpx.Client) -> str:
        """Get the model ID from the vLLM server. Uses first model in /v1/models."""
        if self._model_id is not None:
            return self._model_id
        url = f"{self._base_url}/v1/models"
        try:
            resp = client.get(url, timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data") or []
            if models:
                model_id = models[0].get("id")
                if model_id:
                    self._model_id = model_id
                    logger.info("Resolved vLLM model id: %s", model_id)
                    return model_id
        except Exception as e:
            logger.warning("Could not resolve vLLM model id from /v1/models: %s. Using fallback: %s", e, self._fallback_model)
        return self._fallback_model

    def _sync_generate_content(
        self, image_base64: str, prompt: str, response_model: Type[BaseModel]
    ) -> BaseModel:
        """Generate content using local vLLM OpenAI-compatible API."""
        schema = response_model.model_json_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": schema,
            },
        }

        url = f"{self._base_url}/v1/chat/completions"
        logger.debug("Local vLLM request to %s (image %d chars, prompt %d chars)", url, len(image_base64), len(prompt))
        with httpx.Client(timeout=30.0) as client:
            model_id = self._resolve_model_id(client)
            response = client.post(
                url,
                json={
                    "model": model_id,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                            {"type": "text", "text": prompt}
                        ]
                    }],
                    "response_format": response_format,
                    "max_tokens": 1024,
                }
            )
            if response.status_code >= 400:
                logger.error(
                    "Local vLLM HTTP %s: %s",
                    response.status_code,
                    response.text[:500] if response.text else "(no body)",
                )
            response.raise_for_status()
            result = response.json()

        message = (result.get("choices") or [{}])[0].get("message") or {}
        content = message.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            logger.error(
                "Local vLLM returned empty content. Response keys: %s. choices[0] keys: %s. message keys: %s. "
                "message=%r. finish_reason=%s",
                list(result.keys()),
                list((result.get("choices") or [{}])[0].keys()) if result.get("choices") else [],
                list(message.keys()),
                message,
                (result.get("choices") or [{}])[0].get("finish_reason") if result.get("choices") else None,
            )
            raise RuntimeError("Local vLLM returned empty content.")

        s = str(content).strip()
        if s.startswith("```") and s.endswith("```"):
            lines = s.splitlines()
            if len(lines) >= 2:
                s = "\n".join(lines[1:-1]).strip()

        try:
            return response_model.model_validate_json(s)
        except Exception as parse_err:
            logger.error(
                "Local vLLM returned invalid JSON for %s. Raw content (first 800 chars): %r. Parse error: %s",
                response_model.__name__,
                s[:800] if s else "(empty)",
                parse_err,
            )
            raise
