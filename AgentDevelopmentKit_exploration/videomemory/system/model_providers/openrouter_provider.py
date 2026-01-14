"""OpenRouter model providers."""

import os
import json
import time
import logging
from typing import Any
import httpx
from .base import BaseModelProvider

logger = logging.getLogger('OpenRouterProviders')


class RateLimiter:
    """Simple rate limiter to enforce requests per minute limit."""
    def __init__(self, requests_per_minute: float):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0.0
    
    def wait_if_needed(self):
        """Wait if necessary to respect rate limit."""
        current_time = time.time()
        if self.last_request_time > 0:
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                if sleep_time > 0:
                    time.sleep(sleep_time)
        self.last_request_time = time.time()


# Global rate limiter for OpenRouter (20 requests per minute for free models, use 18 to be conservative)
_openrouter_rate_limiter = RateLimiter(18.0)


class _BaseOpenRouterProvider(BaseModelProvider):
    """Base class for OpenRouter providers with shared functionality."""
    
    def __init__(self, api_key: str = None, model_name: str = None):
        """Initialize OpenRouter provider.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
            model_name: The model name to use (e.g., "molmo/molmo-2-8b-free")
        """
        if api_key is None:
            api_key = os.getenv("OPENROUTER_API_KEY")
        super().__init__(api_key)
        self._rate_limiter = _openrouter_rate_limiter
        self._model_name = model_name
        
        # Initialize the OpenRouter provider
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not found. OpenRouter provider will fail.")
        else:
            logger.info(f"Initialized OpenRouter provider for {self._model_name}")
    
    def _sync_generate_content(self, image_base64: str, prompt: str, response_schema: dict) -> Any:
        """Generate content using OpenRouter API.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt
            response_schema: JSON schema for structured output (not used by OpenRouter, but kept for interface consistency)
            
        Returns:
            Response object with .text attribute containing JSON
        """
        if not self.api_key:
            raise RuntimeError("OpenRouter API key not set. Check OPENROUTER_API_KEY environment variable.")
        
        # Enforce rate limit
        self._rate_limiter.wait_if_needed()
        
        # Add JSON schema instruction to prompt for OpenRouter models
        json_schema_str = json.dumps(response_schema, indent=2)
        enhanced_prompt = f"{prompt}\n\nPlease respond with valid JSON matching this schema: {json_schema_str}"
        
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self._model_name,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                            {"type": "text", "text": enhanced_prompt}
                        ]
                    }],
                    "response_format": {"type": "json_object"}
                }
            )
            
            if response.status_code == 429:
                raise RuntimeError("Rate limit exceeded (429)")
            
            response.raise_for_status()
            result = response.json()
            
            # Create a simple response object with .text attribute
            class Response:
                def __init__(self, text: str):
                    self.text = text
            
            return Response(result["choices"][0]["message"]["content"])


class OpenRouterMolmo28BProvider(_BaseOpenRouterProvider):
    """Provider for OpenRouter Molmo 2 8B free model."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenRouter provider for Molmo 2 8B.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="molmo/molmo-2-8b-free")


class OpenRouterQwen2VL7BProvider(_BaseOpenRouterProvider):
    """Provider for OpenRouter Qwen 2 VL 7B model."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenRouter provider for Qwen 2 VL 7B.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="qwen/qwen-2-vl-7b-instruct")


class OpenRouterPhi4MultimodalProvider(_BaseOpenRouterProvider):
    """Provider for OpenRouter Microsoft Phi 4 Multimodal Instruct model."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenRouter provider for Microsoft Phi 4 Multimodal Instruct.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="microsoft/phi-4-multimodal-instruct")

