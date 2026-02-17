"""Model providers for video stream ingestor ML inference."""

from .base import BaseModelProvider
from .factory import get_VLM_provider

__all__ = [
    "BaseModelProvider",
    "get_VLM_provider",
]

