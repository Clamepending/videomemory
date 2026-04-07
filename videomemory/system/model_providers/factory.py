"""Factory function for creating model providers from environment variables."""

import os
import logging
from difflib import get_close_matches
from typing import Optional
from .base import BaseModelProvider
from .google_provider import Gemini25FlashProvider, Gemini25FlashLiteProvider
from .openai_provider import OpenAIGPT41NanoProvider, OpenAIGPT4oMiniProvider
from .anthropic_provider import (
    AnthropicClaudeHaiku45Provider,
    AnthropicClaudeOpus46Provider,
    AnthropicClaudeSonnet46Provider,
)
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
    # Anthropic models
    "claude-sonnet-4-6": AnthropicClaudeSonnet46Provider,
    "claude-haiku-4-5": AnthropicClaudeHaiku45Provider,
    "claude-opus-4-6": AnthropicClaudeOpus46Provider,
    # OpenRouter models
    "molmo-2-8b": OpenRouterMolmo28BProvider,
    "qwen-2-vl-7b": OpenRouterQwen2VL7BProvider,
    "phi-4-multimodal": OpenRouterPhi4MultimodalProvider,
    "mistral-small-3.1": OpenRouterMistralSmall31Provider,
    "qwen3-vl-8b": OpenRouterQwen3VL8BProvider,
    # Local vLLM (no cloud API key; uses whatever model the server is serving)
    "local-vllm": LocalVLLMProvider,
}

MODEL_NAME_ALIASES = {
    # OpenAI
    "gpt4o": "gpt-4o-mini",
    "gpt4o-mini": "gpt-4o-mini",
    "gpt-4o": "gpt-4o-mini",
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
    "gpt-4.1-nano-2025-04-14": "gpt-4.1-nano",
    # Anthropic
    "claude-sonnet-4.6": "claude-sonnet-4-6",
    "claude-haiku-4.5": "claude-haiku-4-5",
    "claude-opus-4.6": "claude-opus-4-6",
    # OpenRouter
    "qwen-3-vl-8b": "qwen3-vl-8b",
    "qwen/qwen3-vl-8b-instruct": "qwen3-vl-8b",
    # Local
    "vllm": "local-vllm",
}

MODEL_REQUIRED_ENV_KEY_MAP = {
    "gemini-2.5-flash": "GOOGLE_API_KEY",
    "gemini-2.5-flash-lite": "GOOGLE_API_KEY",
    "gpt-4.1-nano": "OPENAI_API_KEY",
    "gpt-4o-mini": "OPENAI_API_KEY",
    "claude-sonnet-4-6": "ANTHROPIC_API_KEY",
    "claude-haiku-4-5": "ANTHROPIC_API_KEY",
    "claude-opus-4-6": "ANTHROPIC_API_KEY",
    "molmo-2-8b": "OPENROUTER_API_KEY",
    "qwen-2-vl-7b": "OPENROUTER_API_KEY",
    "phi-4-multimodal": "OPENROUTER_API_KEY",
    "mistral-small-3.1": "OPENROUTER_API_KEY",
    "qwen3-vl-8b": "OPENROUTER_API_KEY",
    "local-vllm": None,
}

DEFAULT_MODEL_BY_AVAILABLE_KEY = [
    ("ANTHROPIC_API_KEY", "claude-sonnet-4-6"),
    ("OPENAI_API_KEY", "gpt-4o-mini"),
    ("GOOGLE_API_KEY", "gemini-2.5-flash"),
    ("OPENROUTER_API_KEY", "qwen3-vl-8b"),
]


def normalize_model_name(model_name: Optional[str]) -> Optional[str]:
    """Normalize user-facing aliases into supported canonical model names."""
    if model_name is None:
        return None

    normalized = str(model_name).strip().lower()
    if not normalized:
        return None

    return MODEL_NAME_ALIASES.get(normalized, normalized)


def get_supported_model_names() -> list[str]:
    """Return the supported canonical model names exposed to users."""
    return sorted(MODEL_PROVIDER_MAP.keys())


def get_required_api_key_env(model_name: Optional[str]) -> Optional[str]:
    """Return the API-key env var required by a canonical model, if any."""
    canonical = normalize_model_name(model_name)
    return MODEL_REQUIRED_ENV_KEY_MAP.get(canonical)


def choose_default_model_for_available_keys(env: Optional[dict[str, str]] = None) -> Optional[str]:
    """Choose the default canonical cloud model for whatever key is present."""
    env_map = env or os.environ
    google_key = env_map.get("GOOGLE_API_KEY") or env_map.get("GEMINI_API_KEY")
    if google_key and not env_map.get("GOOGLE_API_KEY"):
        env_map = dict(env_map)
        env_map["GOOGLE_API_KEY"] = google_key

    for env_key, model_name in DEFAULT_MODEL_BY_AVAILABLE_KEY:
        if str(env_map.get(env_key, "")).strip():
            return model_name
    return None


def validate_model_name(model_name: Optional[str]) -> Optional[str]:
    """Validate and canonicalize a model name from user input or settings."""
    canonical = normalize_model_name(model_name)
    if canonical is None:
        return None
    if canonical in MODEL_PROVIDER_MAP or "/" in canonical:
        return canonical

    suggestions = get_close_matches(canonical, list(MODEL_PROVIDER_MAP) + list(MODEL_NAME_ALIASES), n=1)
    suggestion = MODEL_NAME_ALIASES.get(suggestions[0], suggestions[0]) if suggestions else None
    supported = ", ".join(get_supported_model_names())
    if suggestion:
        raise ValueError(
            f"Unknown model name '{model_name}'. Did you mean '{suggestion}'? Supported models: {supported}"
        )
    raise ValueError(f"Unknown model name '{model_name}'. Supported models: {supported}")


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
    raw_model_name = model_name
    if raw_model_name is None:
        raw_model_name = os.getenv("VIDEO_INGESTOR_MODEL", "local-vllm")

    model_name = normalize_model_name(raw_model_name) or "local-vllm"
    if raw_model_name and model_name != str(raw_model_name).strip().lower():
        logger.info("Normalized model alias %s -> %s", raw_model_name, model_name)

    if model_name not in MODEL_PROVIDER_MAP:
        if "/" in model_name:
            logger.info(f"Creating OpenRouter custom model provider: {model_name}")
            return OpenRouterCustomModelProvider(model_name=model_name)
        available_models = ", ".join(MODEL_PROVIDER_MAP.keys())
        suggestions = get_close_matches(model_name, list(MODEL_PROVIDER_MAP) + list(MODEL_NAME_ALIASES), n=1)
        suggestion = MODEL_NAME_ALIASES.get(suggestions[0], suggestions[0]) if suggestions else None
        error_msg = (
            f"Unknown model name: '{model_name}'. "
            + (f"Did you mean '{suggestion}'? " if suggestion else "")
            + f"Available models: {available_models}. "
            f"Falling back to default: local-vllm"
        )
        logger.warning(error_msg)
        model_name = "local-vllm"
    
    provider_class = MODEL_PROVIDER_MAP[model_name]
    logger.info(f"Creating model provider: {model_name} ({provider_class.__name__})")
    return provider_class()
