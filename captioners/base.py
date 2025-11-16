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
            frames: List of file paths to images.
        
        Returns:
            List of text captions, one for each input frame.
        """
        pass

