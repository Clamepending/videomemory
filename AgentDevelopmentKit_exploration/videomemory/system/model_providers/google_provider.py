"""Google model providers."""

import os
import base64
import logging
from typing import Any, Type
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
    
    def _sync_generate_content(self, image_base64: str, prompt: str, response_model: Type[BaseModel]) -> BaseModel:
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
        
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=[image_part, text_part],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_model.model_json_schema()
            )
        )

        # Google returns JSON as text; validate into the requested model.
        raw = getattr(response, "text", None)
        if raw is None:
            raise RuntimeError("Google model returned empty response text.")
        return response_model.model_validate_json(raw)


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

