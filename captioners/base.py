"""
Base interface for captioners that generate text captions from image frames.
"""

from abc import ABC, abstractmethod
from typing import List


class Captioner(ABC):
    """
    Abstract base class for captioners.
    
    A captioner takes an array of image frames and returns an array of text captions.
    """
    
    @abstractmethod
    def caption(self, frames: List) -> List[str]:
        """
        Generate captions for a list of image frames.
        
        Args:
            frames: List of image frames. Each frame can be a PIL Image, numpy array,
                   file path (str), or any other image format supported by the implementation.
        
        Returns:
            List of text captions, one for each input frame.
        """
        pass

