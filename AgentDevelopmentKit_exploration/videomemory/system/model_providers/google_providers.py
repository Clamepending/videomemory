"""Google model providers."""

import os
import base64
import logging
from typing import Any
from google import genai
from google.genai import types as genai_types
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
        self._client = None
        self._model_name = model_name
    
    def initialize(self):
        """Initialize the Google GenAI client."""
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not found. Google provider will fail.")
            return
        
        try:
            self._client = genai.Client(api_key=self.api_key)
            logger.info(f"Initialized Google GenAI client for {self._model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Google GenAI client: {e}")
            self._client = None
    
    def _sync_generate_content(self, image_base64: str, prompt: str, response_schema: dict) -> Any:
        """Generate content using Google GenAI.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt
            response_schema: JSON schema for structured output
            
        Returns:
            Response object with .text attribute containing JSON
        """
        if not self._client:
            raise RuntimeError("Google client not initialized. Call initialize() first.")
        
        image_part = genai_types.Part(
            inline_data=genai_types.Blob(
                data=base64.b64decode(image_base64),
                mime_type="image/jpeg"
            )
        )
        text_part = genai_types.Part(text=prompt)
        
        return self._client.models.generate_content(
            model=self._model_name,
            contents=[image_part, text_part],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema
            )
        )


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

