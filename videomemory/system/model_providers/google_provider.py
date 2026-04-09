"""Google model providers."""

import os
import base64
import logging
import time
from typing import Any, Optional, Type
from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel
from .base import BaseModelProvider

logger = logging.getLogger('GoogleProviders')


class _BaseGoogleProvider(BaseModelProvider):
    """Base class for Google providers with shared functionality."""
    
    def __init__(self, api_key: str = None, model_name: str = None):
        """Initialize Google provider.
        
        Args:
            api_key: Google API key. If None, will try to get from GOOGLE_API_KEY env var.
            model_name: The model name to use (e.g., "gemini-2.5-flash")
        """
        if api_key is None:
            api_key = os.getenv("GOOGLE_API_KEY")
        super().__init__(api_key)
        self._model_name = model_name
        self._canonical_model_name = str(model_name or "")
        self._api_model_name = str(model_name or "")
        
        # Initialize the Google GenAI client
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not found. Google provider will fail.")
            self._client = None
        else:
            try:
                self._client = genai.Client(api_key=self.api_key)
                logger.info(f"Initialized Google GenAI client for {self._model_name}")
            except Exception as e:
                logger.error(f"Failed to initialize Google GenAI client: {e}")
                self._client = None
    
    def _sync_generate_content(
        self,
        image_base64: str,
        prompt: str,
        response_model: Type[BaseModel],
        usage_context: Optional[dict[str, Any]] = None,
    ) -> BaseModel:
        """Generate content using Google GenAI.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt
            response_model: Pydantic model class describing expected output
            
        Returns:
            Parsed and validated Pydantic model instance
        """
        if not self._client:
            raise RuntimeError("Google client not initialized. Check GOOGLE_API_KEY environment variable.")
        
        image_part = genai_types.Part(
            inline_data=genai_types.Blob(
                data=base64.b64decode(image_base64),
                mime_type="image/jpeg"
            )
        )
        text_part = genai_types.Part(text=prompt)
        
        # Use response_json_schema instead of response_schema to bypass client-side
        # validation that rejects additional_properties. The API itself supports it.
        started_at = time.time()
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=[image_part, text_part],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=response_model.model_json_schema()
            )
        )
        latency_ms = round((time.time() - started_at) * 1000.0, 3)
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", None)
        if input_tokens is None:
            input_tokens = getattr(usage, "promptTokenCount", None)
        output_tokens = getattr(usage, "candidates_token_count", None)
        if output_tokens is None:
            output_tokens = getattr(usage, "candidatesTokenCount", None)
        total_tokens = getattr(usage, "total_token_count", None)
        if total_tokens is None:
            total_tokens = getattr(usage, "totalTokenCount", None)
        input_tokens = self._coerce_optional_int(input_tokens)
        output_tokens = self._coerce_optional_int(output_tokens)
        total_tokens = self._coerce_optional_int(total_tokens)

        # Google returns JSON as text; validate into the requested model.
        raw = getattr(response, "text", None)
        if raw is None:
            self._emit_usage_event(
                usage_context=usage_context,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                was_success=False,
            )
            raise RuntimeError("Google model returned empty response text.")
        try:
            parsed = response_model.model_validate_json(raw)
        except Exception:
            self._emit_usage_event(
                usage_context=usage_context,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                was_success=False,
            )
            raise
        self._emit_usage_event(
            usage_context=usage_context,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            was_success=True,
        )
        return parsed


class Gemini25FlashProvider(_BaseGoogleProvider):
    """Provider for Google Gemini 2.5 Flash model."""
    
    def __init__(self, api_key: str = None):
        """Initialize Gemini 2.5 Flash provider.
        
        Args:
            api_key: Google API key. If None, will try to get from GOOGLE_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="gemini-2.5-flash")


class Gemini25FlashLiteProvider(_BaseGoogleProvider):
    """Provider for Google Gemini 2.5 Flash Lite model."""
    
    def __init__(self, api_key: str = None):
        """Initialize Gemini 2.5 Flash Lite provider.
        
        Args:
            api_key: Google API key. If None, will try to get from GOOGLE_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="gemini-2.5-flash-lite")
