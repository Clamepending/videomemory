"""Factory function for creating model providers from environment variables."""

import os
import logging
from typing import Optional
from .base import BaseModelProvider
from .google_provider import Gemini25FlashProvider, Gemini25FlashLiteProvider
from .openai_provider import OpenAIGPT41NanoProvider, OpenAIGPT4oMiniProvider
from .openrouter_providers import (
    OpenRouterMolmo28BProvider,
    OpenRouterQwen2VL7BProvider,
    OpenRouterPhi4MultimodalProvider
)

logger = logging.getLogger('ModelProviderFactory')

# Mapping of model names to provider classes
MODEL_PROVIDER_MAP = {
    # Google models
    "gemini-2.5-flash": Gemini25FlashProvider,
    "gemini-2.5-flash-lite": Gemini25FlashLiteProvider,
    # OpenAI models
    "gpt-4.1-nano": OpenAIGPT41NanoProvider,
    "gpt-4o-mini": OpenAIGPT4oMiniProvider,
    # OpenRouter models
    "molmo-2-8b": OpenRouterMolmo28BProvider,
    "qwen-2-vl-7b": OpenRouterQwen2VL7BProvider,
    "phi-4-multimodal": OpenRouterPhi4MultimodalProvider,
}


def get_VLM_provider(model_name: Optional[str] = None) -> BaseModelProvider:
    """Get a VLM (Vision Language Model) provider instance based on environment variable or provided name.
    
    Reads VIDEO_INGESTOR_MODEL environment variable if model_name is not provided.
    Defaults to "gemini-2.5-flash" if neither is set.
    
    Args:
        model_name: Optional model name to use. If None, reads from VIDEO_INGESTOR_MODEL env var.
        
    Returns:
        BaseModelProvider instance
        
    Raises:
        ValueError: If model name is not recognized
    """
    if model_name is None:
        model_name = os.getenv("VIDEO_INGESTOR_MODEL")
        assert model_name is not None, "VIDEO_INGESTOR_MODEL environment variable is not set, recommended: 'gemini-2.5-flash'"
    
    model_name = model_name.lower().strip()
    
    if model_name not in MODEL_PROVIDER_MAP:
        available_models = ", ".join(MODEL_PROVIDER_MAP.keys())
        error_msg = (
            f"Unknown model name: '{model_name}'. "
            f"Available models: {available_models}. "
            f"Falling back to default: gemini-2.5-flash"
        )
        logger.warning(error_msg)
        model_name = "gemini-2.5-flash"
    
    provider_class = MODEL_PROVIDER_MAP[model_name]
    logger.info(f"Creating model provider: {model_name} ({provider_class.__name__})")
    return provider_class()

