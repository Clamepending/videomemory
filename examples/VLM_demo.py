"""
Demo script for using PaliGemma captioner to caption video frames.
"""

import os
import sys
from pathlib import Path
from huggingface_hub import login
import shutil

# Add the parent directory (videomemory) to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Get token from environment and login if available
token = os.getenv('HF_TOKEN')
if token:
    login(token=token)
    print("✓ Authenticated with Hugging Face")

from datasets import TVQALong
from captioners import PaligemmaCaptioner

# Initialize the dataset
print("Loading TVQALong dataset...")
dataset = TVQALong()

# Get the first episode (season 1, episode 1) of bbt
print("Getting first episode of bbt...")
episode = dataset.get_episode("bbt", "s01", "e01", split="train")
print(f"Episode {episode['season']} {episode['episode']} has {episode['num_clips']} clips")

# Get all frames from all clips in the episode
all_frames = []
for clip_name in episode['clips']:
    clip_frames = dataset.get_clip_frames(clip_name, show='bbt')
    all_frames.extend(clip_frames)

# Sort all frames to ensure consistent ordering
all_frames.sort()

# Get the 30th frame (index 29)
if len(all_frames) < 30:
    raise ValueError(f"Episode only has {len(all_frames)} frames, need at least 30")
    
frame_30_path = all_frames[29]
print(f"Selected frame: {frame_30_path}")

# Save the image to outputs/captioners
output_dir = Path("outputs/captioners")
output_dir.mkdir(parents=True, exist_ok=True)
output_image_path = output_dir / "frame_30.jpg"
shutil.copy2(frame_30_path, output_image_path)
print(f"Saved image to: {output_image_path}")

# Initialize the captioner
print("\nInitializing PaliGemma captioner...")
captioner = PaligemmaCaptioner(stride=1)  # stride=1 to caption this single frame

# Generate caption
print("Generating caption...")
captions = captioner.caption([frame_30_path])

# Print the result
if captions and captions[0]:
    print(f"\n{'='*60}")
    print(f"Caption for frame 30:")
    print(f"{'='*60}")
    print(captions[0])
    print(f"{'='*60}\n")
else:
    print("\nWarning: No caption generated")

