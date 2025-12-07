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
            use_flash_attention: Whether to use flash attention 2 (only on CUDA)
        """
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self.prompt = prompt
        self.max_new_tokens = max_new_tokens
        self.chunk_size = chunk_size
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
        print(f"[DEBUG] _load_image called with type: {type(frame)}")
        if isinstance(frame, Image.Image):
            print(f"[DEBUG] Input is PIL Image, size: {frame.size}, mode: {frame.mode}")
            return frame.convert("RGB")
        elif isinstance(frame, (str, Path)):
            print(f"[DEBUG] Input is path: {frame}")
            # Check if it's a URL
            if isinstance(frame, str) and (frame.startswith("http://") or frame.startswith("https://")):
                print(f"[DEBUG] Loading from URL")
                img = load_image(frame)
                print(f"[DEBUG] Loaded image from URL, size: {img.size}, mode: {img.mode}")
                return img
            else:
                print(f"[DEBUG] Loading from file path")
                img = Image.open(frame).convert("RGB")
                print(f"[DEBUG] Loaded image from file, size: {img.size}, mode: {img.mode}")
                return img
        elif hasattr(frame, '__array__'):  # numpy array
            print(f"[DEBUG] Input is numpy array, shape: {frame.shape if hasattr(frame, 'shape') else 'N/A'}")
            img = Image.fromarray(frame).convert("RGB")
            print(f"[DEBUG] Converted numpy to PIL, size: {img.size}, mode: {img.mode}")
            return img
        else:
            raise TypeError(f"Unsupported frame type: {type(frame)}")
    
    def _caption_single(self, image: Image.Image) -> str:
        """Generate a caption for a single image."""
        print(f"[DEBUG] _caption_single called")
        print(f"[DEBUG] Image type: {type(image)}, size: {image.size if hasattr(image, 'size') else 'N/A'}, mode: {image.mode if hasattr(image, 'mode') else 'N/A'}")
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": self.prompt}
                ]
            },
        ]
        print(f"[DEBUG] Messages structure: {messages}")
        print(f"[DEBUG] Prompt: {self.prompt}")
        
        prompt_text = self.processor.apply_chat_template(messages, add_generation_prompt=True)
        print(f"[DEBUG] Prompt text after chat template (first 200 chars): {prompt_text[:200]}")
        print(f"[DEBUG] Prompt text length: {len(prompt_text)}")
        
        inputs = self.processor(text=prompt_text, images=[image], return_tensors="pt")
        print(f"[DEBUG] Inputs keys: {inputs.keys()}")
        for key, value in inputs.items():
            if isinstance(value, torch.Tensor):
                print(f"[DEBUG] Input '{key}' shape: {value.shape}, dtype: {value.dtype}, device: {value.device}")
            else:
                print(f"[DEBUG] Input '{key}' type: {type(value)}, value: {value}")
        
        inputs = inputs.to(self.device)
        print(f"[DEBUG] Inputs moved to device: {self.device}")
        
        with torch.inference_mode():
            print(f"[DEBUG] Starting model.generate()...")
            input_length = inputs['input_ids'].shape[1]
            print(f"[DEBUG] Input length: {input_length}")
            
            generated_ids = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
            print(f"[DEBUG] Generated IDs shape: {generated_ids.shape}")
            print(f"[DEBUG] Generated IDs (first 50 tokens): {generated_ids[0][:50].tolist()}")
            
            # Trim input tokens - only decode the newly generated tokens
            generated_ids_trimmed = generated_ids[0][input_length:]
            print(f"[DEBUG] Trimmed generated IDs length: {len(generated_ids_trimmed)}")
            print(f"[DEBUG] Trimmed generated IDs (first 50 tokens): {generated_ids_trimmed[:50].tolist()}")
            
            generated_texts = self.processor.batch_decode(
                [generated_ids_trimmed],
                skip_special_tokens=True,
            )
            print(f"[DEBUG] Decoded text (trimmed): {generated_texts[0] if generated_texts else 'None'}")
        
        # Extract the assistant response
        response = generated_texts[0] if generated_texts else ""
        print(f"[DEBUG] Response before processing: {response[:300]}")
        
        # Remove "Assistant:" prefix if present (from chat template)
        if response.startswith("Assistant:"):
            response = response[len("Assistant:"):].strip()
        
        # Remove any remaining image tokens or special markers
        response = re.sub(r'<row_\d+_col_\d+>', '', response)
        response = re.sub(r'<global-img>', '', response)
        response = re.sub(r'<image>', '', response)
        
        print(f"[DEBUG] Final response: {response[:200]}")
        return response.strip()
    
    def _caption_multiple(self, images: List[Image.Image]) -> str:
        """Generate a caption for multiple images."""
        print(f"[DEBUG] _caption_multiple called with {len(images)} images")
        for i, img in enumerate(images):
            print(f"[DEBUG] Image {i}: type={type(img)}, size={img.size if hasattr(img, 'size') else 'N/A'}, mode={img.mode if hasattr(img, 'mode') else 'N/A'}")
        
        messages = [
            {
                "role": "user",
                "content": (
                    [{"type": "image"}] * len(images) +
                    [{"type": "text", "text": self.prompt}]
                )
            },
        ]
        print(f"[DEBUG] Messages structure: {messages}")
        print(f"[DEBUG] Prompt: {self.prompt}")
        
        prompt_text = self.processor.apply_chat_template(messages, add_generation_prompt=True)
        print(f"[DEBUG] Prompt text after chat template (first 200 chars): {prompt_text[:200]}")
        
        inputs = self.processor(text=prompt_text, images=images, return_tensors="pt")
        print(f"[DEBUG] Inputs keys: {inputs.keys()}")
        for key, value in inputs.items():
            if isinstance(value, torch.Tensor):
                print(f"[DEBUG] Input '{key}' shape: {value.shape}, dtype: {value.dtype}")
            else:
                print(f"[DEBUG] Input '{key}' type: {type(value)}")
        
        inputs = inputs.to(self.device)
        
        with torch.inference_mode():
            print(f"[DEBUG] Starting model.generate()...")
            input_length = inputs['input_ids'].shape[1]
            print(f"[DEBUG] Input length: {input_length}")
            
            generated_ids = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
            print(f"[DEBUG] Generated IDs shape: {generated_ids.shape}")
            
            # Trim input tokens - only decode the newly generated tokens
            generated_ids_trimmed = generated_ids[0][input_length:]
            print(f"[DEBUG] Trimmed generated IDs length: {len(generated_ids_trimmed)}")
            
            generated_texts = self.processor.batch_decode(
                [generated_ids_trimmed],
                skip_special_tokens=True,
            )
            print(f"[DEBUG] Decoded text (trimmed): {generated_texts[0] if generated_texts else 'None'}")
        
        # Extract the assistant response
        response = generated_texts[0] if generated_texts else ""
        print(f"[DEBUG] Response before processing: {response[:300]}")
        
        # Remove "Assistant:" prefix if present (from chat template)
        if response.startswith("Assistant:"):
            response = response[len("Assistant:"):].strip()
        
        # Remove any remaining image tokens or special markers
        response = re.sub(r'<row_\d+_col_\d+>', '', response)
        response = re.sub(r'<global-img>', '', response)
        response = re.sub(r'<image>', '', response)
        
        print(f"[DEBUG] Final response: {response[:200]}")
        return response.strip()
    
    def caption(self, frames: List) -> List[str]:
        """
        Generate captions for a list of image frames.
        
        Args:
            frames: List of file paths to images or PIL Images.
        
        Returns:
            List of text captions. If chunk_size=1, one caption per frame.
            If chunk_size>1, one caption per chunk (length = ceil(len(frames) / chunk_size)).
        """
        print(f"[DEBUG] caption() called with {len(frames)} frames")
        print(f"[DEBUG] chunk_size: {self.chunk_size}")
        for i, frame in enumerate(frames):
            print(f"[DEBUG] Frame {i}: {frame} (type: {type(frame)})")
        
        if not frames:
            return []
        
        captions = []
        
        if self.chunk_size == 1:
            # Process frames individually
            for i, frame in enumerate(tqdm(frames, desc="Captioning frames")):
                try:
                    image = self._load_image(frame)
                    caption = self._caption_single(image)
                    captions.append(caption)
                except Exception as e:
                    print(f"Warning: Failed to caption frame {i}: {e}")
                    captions.append("")  # Empty string on error
        else:
            # Process frames in chunks
            num_chunks = (len(frames) + self.chunk_size - 1) // self.chunk_size
            
            for chunk_idx in tqdm(range(num_chunks), desc="Captioning chunks", unit="chunk"):
                start_idx = chunk_idx * self.chunk_size
                end_idx = min(start_idx + self.chunk_size, len(frames))
                chunk_frames = frames[start_idx:end_idx]
                
                try:
                    images = [self._load_image(frame) for frame in chunk_frames]
                    if len(images) == 1:
                        caption = self._caption_single(images[0])
                    else:
                        caption = self._caption_multiple(images)
                    captions.append(caption)
                except Exception as e:
                    print(f"Warning: Failed to caption chunk {chunk_idx + 1}/{num_chunks} (frames {start_idx}-{end_idx-1}): {e}")
                    captions.append("")  # Empty string on error
        
        return captions

