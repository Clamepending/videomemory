"""Base class for model providers."""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger('ModelProvider')


class BaseModelProvider(ABC):
    """Base class for all model providers.
    
    Each provider must implement _sync_generate_content() which takes
    image_base64 (str) and prompt (str) and returns a response object
    with a .text attribute containing JSON.
    """
    
    def __init__(self, api_key: str = None):
        """Initialize the model provider.
        
        Args:
            api_key: API key for the provider (if needed)
        """
        self.api_key = api_key
        self._client = None
    
    @abstractmethod
    def _sync_generate_content(self, image_base64: str, prompt: str, response_schema: dict) -> Any:
        """Synchronous method to generate content from image and prompt.
        
        This method should be synchronous and will be wrapped in asyncio.to_thread()
        to avoid blocking the event loop.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt for the model
            response_schema: JSON schema for structured output (Pydantic model schema)
            
        Returns:
            Response object with a .text attribute containing JSON string
        """
        pass

