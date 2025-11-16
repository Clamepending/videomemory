"""
Captioners package for generating text captions from image frames.
"""

from .base import Captioner
from .paligemma_captioner import PaligemmaCaptioner

__all__ = ['Captioner', 'PaligemmaCaptioner']

