"""
Qwen2VL captioner that generates text captions from video sequences using Qwen's Qwen2-VL model.
"""

from typing import List, Union
from pathlib import Path
import torch
import os
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
from tqdm import tqdm

from .base import Captioner


class Qwen2VLCaptioner(Captioner):
    """
    Captioner using Qwen's Qwen2-VL model to generate captions from video frame sequences.
    Processes frames in chunks as video sequences.
    """
    
    def __init__(
        self,
        model_id: str = "Qwen/Qwen2-VL-7B-Instruct",
        device: str = "cuda",
        prompt: str = "Describe this video.",
        max_new_tokens: int = 512,
        chunk_size: int = 30,
        fps: float = 3.0,
    ):
        """
        Initialize the Qwen2VL captioner.
        
        Args:
            model_id: Hugging Face model ID for Qwen2-VL
            device: Device to run the model on (e.g., "cuda", "cpu")
            prompt: Text prompt to use for captioning
            max_new_tokens: Maximum number of tokens to generate
            chunk_size: Number of consecutive frames to process together
            fps: Frames per second for video processing
        """
        self.model_id = model_id
        self.device = device
        self.prompt = prompt
        self.max_new_tokens = max_new_tokens
        self.chunk_size = chunk_size
        self.fps = fps
        
        print(f"Loading Qwen2VL model: {model_id}...")
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_id,
            torch_dtype="auto",
            device_map="auto" if device == "cuda" else device,
        ).eval()
        
        self.processor = AutoProcessor.from_pretrained(model_id)
        print("✓ Model loaded successfully")
    
    def _get_frame_path(self, frame: Union[str, Path]) -> str:
        """Convert frame to absolute file path with file:// protocol."""
        if isinstance(frame, Path):
            frame = str(frame)
        return f"file://{os.path.abspath(frame)}"
    
    def _caption_chunk(self, frame_paths: List[str]) -> str:
        """Generate a caption for a chunk of frames processed as a video."""
        frame_urls = [self._get_frame_path(frame) for frame in frame_paths]
        
        messages = [{
            "role": "user",
            "content": [
                {"type": "video", "video": frame_urls, "fps": self.fps},
                {"type": "text", "text": self.prompt},
            ],
        }]
        
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(text=[text], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt")
        inputs = inputs.to(self.device)
        
        with torch.inference_mode():
            generated_ids = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
            generated_ids_trimmed = [out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)]
            output_text = self.processor.batch_decode(generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        
        return output_text[0].strip() if output_text else ""
    
    def caption(self, frames: List) -> List[str]:
        """
        Generate captions for a list of image frames.
        Processes frames in consecutive non-overlapping chunks.
        
        Returns:
            List of captions, one per chunk. Length will be ceil(len(frames) / chunk_size).
        """
        if not frames:
            return []
        
        num_chunks = (len(frames) + self.chunk_size - 1) // self.chunk_size
        captions = []
        
        for chunk_idx in tqdm(range(num_chunks), desc=f"Captioning chunks", unit="chunk"):
            start_idx = chunk_idx * self.chunk_size
            end_idx = min(start_idx + self.chunk_size, len(frames))
            chunk_frames = frames[start_idx:end_idx]
            
            try:
                caption = self._caption_chunk(chunk_frames)
                captions.append(caption)
            except Exception as e:
                print(f"Warning: Failed to caption chunk {chunk_idx + 1}/{num_chunks} (frames {start_idx}-{end_idx-1}): {e}")
                captions.append("")  # Empty string on error
        
        return captions
