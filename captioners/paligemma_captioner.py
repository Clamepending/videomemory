"""
PaliGemma captioner that generates text captions from image frames using Google's PaliGemma model.
"""

from typing import List, Union
from pathlib import Path
import torch
from PIL import Image
from transformers import AutoProcessor, PaliGemmaForConditionalGeneration

from .base import Captioner


class PaligemmaCaptioner(Captioner):
    """
    Captioner using Google's PaliGemma model to generate captions from image frames.
    
    Uses a stride parameter to control how often frames are sampled for captioning.
    Only frames at stride intervals are actually processed through the model.
    """
    
    def __init__(
        self,
        model_id: str = "google/paligemma-3b-mix-224",
        device: str = "cuda:0",
        dtype: torch.dtype = torch.bfloat16,
        stride: int = 6,
        prompt: str = "Describe the image in detail.",
        max_new_tokens: int = 100,
        revision: str = "bfloat16"
    ):
        """
        Initialize the PaliGemma captioner.
        
        Args:
            model_id: Hugging Face model ID for PaliGemma
            device: Device to run the model on (e.g., "cuda:0", "cpu")
            dtype: Data type for model weights (default: torch.bfloat16)
            stride: How often to sample frames for captioning (1 = every frame, 2 = every other frame, etc.)
            prompt: Text prompt to use for captioning (default: "caption")
            max_new_tokens: Maximum number of tokens to generate
            revision: Model revision to use (default: "bfloat16")
        """
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self.stride = stride
        self.prompt = prompt
        self.max_new_tokens = max_new_tokens
        self.revision = revision
        
        # Initialize model and processor
        print(f"Loading PaliGemma model: {model_id}...")
        self.model = PaliGemmaForConditionalGeneration.from_pretrained(
            model_id,
            dtype=dtype,
            device_map=device,
            revision=revision,
        ).eval()
        
        self.processor = AutoProcessor.from_pretrained(model_id)
        print("✓ Model loaded successfully")
    
    def _load_image(self, frame: Union[str, Path, Image.Image]) -> Image.Image:
        """
        Load an image from various input formats.
        
        Args:
            frame: Can be a PIL Image, file path (str or Path), or numpy array
            
        Returns:
            PIL Image in RGB format
        """
        if isinstance(frame, Image.Image):
            return frame.convert("RGB")
        elif isinstance(frame, (str, Path)):
            return Image.open(frame).convert("RGB")
        elif hasattr(frame, '__array__'):  # numpy array
            return Image.fromarray(frame).convert("RGB")
        else:
            raise TypeError(f"Unsupported frame type: {type(frame)}")
    
    def caption(self, frames: List) -> List[str]:
        """
        Generate captions for a list of image frames.
        
        Only frames at stride intervals are actually processed through the model.
        Other frames receive empty string captions.
        
        Args:
            frames: List of image frames. Each frame can be a PIL Image, numpy array,
                   file path (str), or any other image format supported by PIL.
        
        Returns:
            List of text captions, one for each input frame.
            Frames not processed (due to stride) will have empty string captions.
        """
        if not frames:
            return []
        
        # Initialize result list with empty strings
        captions = [""] * len(frames)
        
        # Process frames at stride intervals
        for i in range(0, len(frames), self.stride):
            try:
                # Load the image
                image = self._load_image(frames[i])
                
                # Prepare inputs
                model_inputs = self.processor(
                    text=self.prompt,
                    images=image,
                    return_tensors="pt"
                ).to(self.model.device)
                
                input_len = model_inputs["input_ids"].shape[-1]
                
                # Generate caption
                with torch.inference_mode():
                    generation = self.model.generate(
                        **model_inputs,
                        max_new_tokens=self.max_new_tokens,
                        do_sample=False
                    )
                    generation = generation[0][input_len:]
                    decoded = self.processor.decode(generation, skip_special_tokens=True)
                    captions[i] = decoded.strip()
                    
            except Exception as e:
                print(f"Warning: Failed to caption frame {i}: {e}")
                captions[i] = ""  # Keep empty string on error
        
        return captions

