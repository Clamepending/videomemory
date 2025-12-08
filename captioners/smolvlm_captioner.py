"""
SmolVLM captioner that generates text captions from image frames using Hugging Face's SmolVLM model.
"""

from typing import List, Union
from pathlib import Path
import re
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForVision2Seq
from transformers.image_utils import load_image
from tqdm import tqdm

from .base import Captioner


class SmolVLMCaptioner(Captioner):
    """
    Captioner using Hugging Face's SmolVLM model to generate captions from image frames.
    
    SmolVLM is a compact multimodal model that can process multiple images in a single request.
    Supports both single-frame and multi-frame captioning modes.
    """
    
    def __init__(
        self,
        model_id: str = "HuggingFaceTB/SmolVLM-Instruct",
        device: str = "cuda",
        dtype: torch.dtype = torch.bfloat16,
        prompt: str = "Describe this image.",
        max_new_tokens: int = 500,
        chunk_size: int = 1,
        stride: int = 3,
        use_flash_attention: bool = True,
    ):
        """
        Initialize the SmolVLM captioner.
        
        Args:
            model_id: Hugging Face model ID for SmolVLM
            device: Device to run the model on (e.g., "cuda", "cpu")
            dtype: Data type for model weights (default: torch.bfloat16)
            prompt: Text prompt to use for captioning
            max_new_tokens: Maximum number of tokens to generate
            chunk_size: Number of frames to process together (1 = individual, >1 = multi-frame)
            stride: How often to sample frames for captioning (1 = every frame, 2 = every other frame, etc.)
            use_flash_attention: Whether to use flash attention 2 (only on CUDA)
        """
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self.prompt = prompt
        self.max_new_tokens = max_new_tokens
        self.chunk_size = chunk_size
        self.stride = stride
        self.use_flash_attention = use_flash_attention and device.startswith("cuda")
        
        # Initialize model and processor
        print(f"Loading SmolVLM model: {model_id}...")
        attn_implementation = "flash_attention_2" if self.use_flash_attention else "eager"
        
        # Load model on specified device (single GPU for simplicity and stability)
        self.model = AutoModelForVision2Seq.from_pretrained(
            model_id,
            torch_dtype=dtype,
            device_map=device,
            _attn_implementation=attn_implementation,
        ).eval()
        
        self.processor = AutoProcessor.from_pretrained(model_id)
        print("✓ Model loaded successfully")
    
    def _load_image(self, frame: Union[str, Path, Image.Image]) -> Image.Image:
        """
        Load an image from various input formats.
        
        Args:
            frame: Can be a PIL Image, file path (str or Path), or URL
            
        Returns:
            PIL Image in RGB format
        """
        if isinstance(frame, Image.Image):
            return frame.convert("RGB")
        elif isinstance(frame, (str, Path)):
            # Check if it's a URL
            if isinstance(frame, str) and (frame.startswith("http://") or frame.startswith("https://")):
                return load_image(frame)
            else:
                return Image.open(frame).convert("RGB")
        elif hasattr(frame, '__array__'):  # numpy array
            return Image.fromarray(frame).convert("RGB")
        else:
            raise TypeError(f"Unsupported frame type: {type(frame)}")
    
    def _caption_single(self, image: Image.Image) -> str:
        """Generate a caption for a single image."""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": self.prompt}
                ]
            },
        ]
        
        prompt_text = self.processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = self.processor(text=prompt_text, images=[image], return_tensors="pt")
        inputs = inputs.to(self.device)
        
        with torch.inference_mode():
            input_length = inputs['input_ids'].shape[1]
            generated_ids = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
            generated_ids_trimmed = generated_ids[0][input_length:]
            generated_texts = self.processor.batch_decode(
                [generated_ids_trimmed],
                skip_special_tokens=True,
            )
        
        response = generated_texts[0] if generated_texts else ""
        
        # Remove "Assistant:" prefix if present
        if response.startswith("Assistant:"):
            response = response[len("Assistant:"):].strip()
        
        # Remove any remaining image tokens or special markers
        response = re.sub(r'<row_\d+_col_\d+>', '', response)
        response = re.sub(r'<global-img>', '', response)
        response = re.sub(r'<image>', '', response)
        
        return response.strip()
    
    def _caption_multiple(self, images: List[Image.Image]) -> str:
        """Generate a caption for multiple images."""
        messages = [
            {
                "role": "user",
                "content": (
                    [{"type": "image"}] * len(images) +
                    [{"type": "text", "text": self.prompt}]
                )
            },
        ]
        
        prompt_text = self.processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = self.processor(text=prompt_text, images=images, return_tensors="pt")
        inputs = inputs.to(self.device)
        
        with torch.inference_mode():
            input_length = inputs['input_ids'].shape[1]
            generated_ids = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
            generated_ids_trimmed = generated_ids[0][input_length:]
            generated_texts = self.processor.batch_decode(
                [generated_ids_trimmed],
                skip_special_tokens=True,
            )
        
        response = generated_texts[0] if generated_texts else ""
        
        # Remove "Assistant:" prefix if present
        if response.startswith("Assistant:"):
            response = response[len("Assistant:"):].strip()
        
        # Remove any remaining image tokens or special markers
        response = re.sub(r'<row_\d+_col_\d+>', '', response)
        response = re.sub(r'<global-img>', '', response)
        response = re.sub(r'<image>', '', response)
        
        return response.strip()
    
    def caption(self, frames: List) -> List[str]:
        """
        Generate captions for a list of image frames.
        
        Frames are subsampled by stride before processing to reduce context size.
        Only frames at stride intervals are processed.
        
        Args:
            frames: List of file paths to images or PIL Images.
        
        Returns:
            List of text captions. If chunk_size=1, one caption per original frame
            (empty strings for skipped frames). If chunk_size>1, one caption per chunk
            of subsampled frames.
        """
        if not frames:
            return []
        
        # Subsample frames by stride
        subsampled_frames = frames[::self.stride]
        subsampled_indices = list(range(0, len(frames), self.stride))
        
        # Process frames in chunks (chunk_size=1 is just chunks of size 1)
        num_chunks = (len(subsampled_frames) + self.chunk_size - 1) // self.chunk_size
        captions = []
        
        for chunk_idx in tqdm(range(num_chunks), desc="Captioning chunks", unit="chunk"):
            start_idx = chunk_idx * self.chunk_size
            end_idx = min(start_idx + self.chunk_size, len(subsampled_frames))
            chunk_frames = subsampled_frames[start_idx:end_idx]
            
            try:
                images = [self._load_image(frame) for frame in chunk_frames]
                if len(images) == 1:
                    caption = self._caption_single(images[0])
                else:
                    caption = self._caption_multiple(images)
                captions.append(caption)
            except Exception as e:
                original_start = subsampled_indices[start_idx] if start_idx < len(subsampled_indices) else start_idx
                original_end = subsampled_indices[end_idx-1] if end_idx-1 < len(subsampled_indices) else end_idx-1
                print(f"Warning: Failed to caption chunk {chunk_idx + 1}/{num_chunks} (original frames {original_start}-{original_end}): {e}")
                captions.append("")
        
        # If chunk_size=1, map captions back to original frame positions
        if self.chunk_size == 1:
            caption_map = dict(zip(subsampled_indices, captions))
            return [caption_map.get(i, "") for i in range(len(frames))]
        
        return captions

