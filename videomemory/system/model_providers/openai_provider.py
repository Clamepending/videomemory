"""OpenAI model providers."""

import os
import logging
import time
from typing import Any, Optional, Type
from openai import OpenAI
from pydantic import BaseModel
from .base import BaseModelProvider

logger = logging.getLogger('OpenAIProvider')


class OpenAIGPT41NanoProvider(BaseModelProvider):
    """Provider for OpenAI GPT-4.1-nano-2025-04-14 model."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key. If None, will try to get from OPENAI_API_KEY env var.
        """
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
        super().__init__(api_key)
        self._canonical_model_name = "gpt-4.1-nano"
        self._api_model_name = "gpt-4.1-nano-2025-04-14"
        
        # Initialize the OpenAI client
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found. OpenAI provider will fail.")
            self._client = None
        else:
            try:
                self._client = OpenAI(api_key=self.api_key)
                logger.info("Initialized OpenAI client for GPT-4.1-nano-2025-04-14")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self._client = None
    
    def _sync_generate_content(
        self,
        image_base64: str,
        prompt: str,
        response_model: Type[BaseModel],
        usage_context: Optional[dict[str, Any]] = None,
    ) -> BaseModel:
        """Generate content using OpenAI GPT-4.1-nano.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt
            response_model: Pydantic model class describing expected output
            
        Returns:
            Parsed and validated Pydantic model instance
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized. Check OPENAI_API_KEY environment variable.")
        
        # Use Structured Outputs parsing directly into the Pydantic model.
        started_at = time.time()
        completion = self._client.beta.chat.completions.parse(
            model="gpt-4.1-nano-2025-04-14",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt}
                ]
            }],
            response_format=response_model,
        )
        latency_ms = round((time.time() - started_at) * 1000.0, 3)
        usage = getattr(completion, "usage", None)
        input_tokens = self._coerce_optional_int(getattr(usage, "prompt_tokens", None))
        output_tokens = self._coerce_optional_int(getattr(usage, "completion_tokens", None))
        total_tokens = self._coerce_optional_int(getattr(usage, "total_tokens", None))

        message = completion.choices[0].message
        if getattr(message, "parsed", None) is not None:
            parsed = response_model.model_validate(message.parsed)
            self._emit_usage_event(
                usage_context=usage_context,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                was_success=True,
            )
            return parsed
        refusal = getattr(message, "refusal", None)
        self._emit_usage_event(
            usage_context=usage_context,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            was_success=False,
        )
        raise RuntimeError(f"OpenAI refused or returned no parsed output: {refusal or 'unknown'}")


class OpenAIGPT4oMiniProvider(BaseModelProvider):
    """Provider for OpenAI GPT-4o-mini-2024-07-18 model."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key. If None, will try to get from OPENAI_API_KEY env var.
        """
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
        super().__init__(api_key)
        self._canonical_model_name = "gpt-4o-mini"
        self._api_model_name = "gpt-4o-mini-2024-07-18"
        
        # Initialize the OpenAI client
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not found. OpenAI provider will fail.")
            self._client = None
        else:
            try:
                self._client = OpenAI(api_key=self.api_key)
                logger.info("Initialized OpenAI client for GPT-4o-mini-2024-07-18")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self._client = None
    
    def _sync_generate_content(
        self,
        image_base64: str,
        prompt: str,
        response_model: Type[BaseModel],
        usage_context: Optional[dict[str, Any]] = None,
    ) -> BaseModel:
        """Generate content using OpenAI GPT-4o-mini.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt
            response_model: Pydantic model class describing expected output
            
        Returns:
            Parsed and validated Pydantic model instance
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized. Check OPENAI_API_KEY environment variable.")
        
        started_at = time.time()
        completion = self._client.beta.chat.completions.parse(
            model="gpt-4o-mini-2024-07-18",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt}
                ]
            }],
            response_format=response_model,
        )
        latency_ms = round((time.time() - started_at) * 1000.0, 3)
        usage = getattr(completion, "usage", None)
        input_tokens = self._coerce_optional_int(getattr(usage, "prompt_tokens", None))
        output_tokens = self._coerce_optional_int(getattr(usage, "completion_tokens", None))
        total_tokens = self._coerce_optional_int(getattr(usage, "total_tokens", None))

        message = completion.choices[0].message
        if getattr(message, "parsed", None) is not None:
            parsed = response_model.model_validate(message.parsed)
            self._emit_usage_event(
                usage_context=usage_context,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                was_success=True,
            )
            return parsed
        refusal = getattr(message, "refusal", None)
        self._emit_usage_event(
            usage_context=usage_context,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            was_success=False,
        )
        raise RuntimeError(f"OpenAI refused or returned no parsed output: {refusal or 'unknown'}")
