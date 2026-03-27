"""Factory function for creating model providers from environment variables."""

import os
import logging
from typing import Optional
from .base import BaseModelProvider
from .google_provider import Gemini25FlashProvider, Gemini25FlashLiteProvider
from .openai_provider import OpenAIGPT41NanoProvider, OpenAIGPT4oMiniProvider
from .openrouter_provider import (
    OpenRouterMolmo28BProvider,
    OpenRouterQwen2VL7BProvider,
    OpenRouterPhi4MultimodalProvider,
    OpenRouterMistralSmall31Provider,
    OpenRouterQwen3VL8BProvider,
    OpenRouterCustomModelProvider,
)
from .vllm_provider import LocalVLLMProvider

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
    "mistral-small-3.1": OpenRouterMistralSmall31Provider,
    "qwen3-vl-8b": OpenRouterQwen3VL8BProvider,
    # Local vLLM (no cloud API key; uses whatever model the server is serving)
    "local-vllm": LocalVLLMProvider,
}


def get_VLM_provider(model_name: Optional[str] = None) -> BaseModelProvider:
    """Get a VLM (Vision Language Model) provider instance based on environment variable or provided name.
    
    Reads VIDEO_INGESTOR_MODEL environment variable if model_name is not provided.
    Defaults to "local-vllm" if neither is set.
    
    Args:
        model_name: Optional model name to use. If None, reads from VIDEO_INGESTOR_MODEL env var.
        
    Returns:
        BaseModelProvider instance
        
    Raises:
        ValueError: If model name is not recognized
    """
    if model_name is None:
        model_name = os.getenv("VIDEO_INGESTOR_MODEL", "local-vllm")
    
    model_name = model_name.lower().strip()
    
    if model_name not in MODEL_PROVIDER_MAP:
        if "/" in model_name:
            logger.info(f"Creating OpenRouter custom model provider: {model_name}")
            return OpenRouterCustomModelProvider(model_name=model_name)
        available_models = ", ".join(MODEL_PROVIDER_MAP.keys())
        error_msg = (
            f"Unknown model name: '{model_name}'. "
            f"Available models: {available_models}. "
            f"Falling back to default: local-vllm"
        )
        logger.warning(error_msg)
        model_name = "local-vllm"
    
    provider_class = MODEL_PROVIDER_MAP[model_name]
    logger.info(f"Creating model provider: {model_name} ({provider_class.__name__})")
    return provider_class()

