"""OpenAI model providers."""

import os
import logging
from typing import Any
from openai import OpenAI
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
    
    def _sync_generate_content(self, image_base64: str, prompt: str, response_schema: dict) -> Any:
        """Generate content using OpenAI GPT-4.1-nano.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt
            response_schema: JSON schema for structured output (not used by OpenAI, but kept for interface consistency)
            
        Returns:
            Response object with .text attribute containing JSON
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized. Check OPENAI_API_KEY environment variable.")
        
        response = self._client.chat.completions.create(
            model="gpt-4.1-nano-2025-04-14",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt}
                ]
            }],
            response_format={"type": "json_object"}
        )
        
        # Create a simple response object with .text attribute
        class Response:
            def __init__(self, text: str):
                self.text = text
        
        return Response(response.choices[0].message.content)


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
    
    def _sync_generate_content(self, image_base64: str, prompt: str, response_schema: dict) -> Any:
        """Generate content using OpenAI GPT-4o-mini.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt
            response_schema: JSON schema for structured output (not used by OpenAI, but kept for interface consistency)
            
        Returns:
            Response object with .text attribute containing JSON
        """
        if not self._client:
            raise RuntimeError("OpenAI client not initialized. Check OPENAI_API_KEY environment variable.")
        
        response = self._client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt}
                ]
            }],
            response_format={"type": "json_object"}
        )
        
        # Create a simple response object with .text attribute
        class Response:
            def __init__(self, text: str):
                self.text = text
        
        return Response(response.choices[0].message.content)

