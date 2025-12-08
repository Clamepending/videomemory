import sys
from pathlib import Path
import glob
import os
import time

# Add parent directory to path to import captioners
sys.path.insert(0, str(Path(__file__).parent.parent))

from captioners import SmolVLMCaptioner

prompt = "Describe this video. describe the actions that the people in the video are taking. Focus on the actions they take on the environment. describe if they open a door."

# Option 1: Test with multiple frames from a video directory
video_dir = "datasets/tvqa/videos/frames_hq/bbt_frames/s01e01_seg01_clip_00"
frame_files = sorted(glob.glob(os.path.join(video_dir, "*.jpg")))[45:56]

# Option 2: Test with a single image (uncomment to use)
# frame_files = ["outputs/captioners/frame_30.jpg"]

# Initialize captioner
# For multiple frames, set chunk_size to process them together
# For single frame, chunk_size=1 processes individually
print(f"Loading captioner and model...")
start_init = time.perf_counter()
captioner = SmolVLMCaptioner(
    chunk_size=len(frame_files) if len(frame_files) > 1 else 1,
    prompt=prompt,
    max_new_tokens=500,
)
init_time = time.perf_counter() - start_init
print(f"Model loaded in {init_time:.2f} seconds\n")

# Generate captions
print(f"Captioning {len(frame_files)} frame(s)...")
start_caption = time.perf_counter()
captions = captioner.caption(frame_files)
caption_time = time.perf_counter() - start_caption

# Print timing statistics
print(f"\n{'='*60}")
print(f"TIMING STATISTICS:")
print(f"{'='*60}")
print(f"Model initialization: {init_time:.2f} seconds")
print(f"Captioning time: {caption_time:.2f} seconds")
print(f"Total time: {init_time + caption_time:.2f} seconds")
if len(frame_files) > 0:
    print(f"Average time per frame: {caption_time / len(frame_files):.2f} seconds")
    if captioner.chunk_size > 1:
        num_chunks = (len(frame_files) + captioner.chunk_size - 1) // captioner.chunk_size
        print(f"Average time per chunk: {caption_time / num_chunks:.2f} seconds")
print(f"{'='*60}\n")
# Print results
if len(captions) == 1:
    print(captions[0])
else:
    for i, caption in enumerate(captions):
        print(f"\nCaption {i+1}/{len(captions)}:")
        print(caption)

