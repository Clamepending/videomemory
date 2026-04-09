"""Base class for model providers."""

import logging
from abc import ABC, abstractmethod
from threading import Lock
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel

from ..usage import ModelUsageEvent, estimate_model_cost_usd

logger = logging.getLogger('ModelProvider')


class BaseModelProvider(ABC):
    """Base class for all model providers.
    
    Each provider must implement _sync_generate_content() which takes
    image_base64 (str), prompt (str), and a Pydantic model class describing
    the structured output, and returns an instance of that model.
    """
    
    def __init__(self, api_key: str = None):
        """Initialize the model provider.
        
        Args:
            api_key: API key for the provider (if needed)
        """
        self.api_key = api_key
        self._client = None
        self._canonical_model_name = ""
        self._api_model_name = ""
        self._usage_callback: Optional[Callable[[dict[str, Any]], None]] = None
        self._usage_callback_lock = Lock()

    def set_usage_callback(self, callback: Optional[Callable[[dict[str, Any]], None]]) -> None:
        """Attach a callback that receives one dict per completed model call."""
        with self._usage_callback_lock:
            self._usage_callback = callback

    @staticmethod
    def _coerce_optional_int(value: Any) -> Optional[int]:
        """Best-effort conversion for SDK token fields that may be absent or mocked."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _emit_usage_event(
        self,
        *,
        usage_context: Optional[dict[str, Any]] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        latency_ms: Optional[float] = None,
        was_success: bool = True,
    ) -> None:
        """Emit a normalized usage event to the configured callback, if any."""
        with self._usage_callback_lock:
            callback = self._usage_callback
        if callback is None:
            return

        model_name = self._canonical_model_name or self._api_model_name or type(self).__name__
        api_model_name = self._api_model_name or self._canonical_model_name or model_name
        estimated_cost_usd = estimate_model_cost_usd(
            model_name,
            api_model_name=api_model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        event = ModelUsageEvent(
            provider_name=type(self).__name__,
            model_name=model_name,
            api_model_name=api_model_name,
            source=str((usage_context or {}).get("source") or "unknown"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
            was_success=was_success,
        )
        try:
            callback(event.to_dict())
        except Exception as exc:
            logger.warning("Usage callback failed for %s: %s", type(self).__name__, exc, exc_info=True)
    
    @abstractmethod
    def _sync_generate_content(
        self,
        image_base64: str,
        prompt: str,
        response_model: Type[BaseModel],
        usage_context: Optional[dict[str, Any]] = None,
    ) -> BaseModel:
        """Synchronous method to generate content from image and prompt.
        
        This method should be synchronous and will be wrapped in asyncio.to_thread()
        to avoid blocking the event loop.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt for the model
            response_model: Pydantic model class describing the expected output
            usage_context: Optional context such as the caller source
            
        Returns:
            Parsed and validated Pydantic model instance
        """
        pass
