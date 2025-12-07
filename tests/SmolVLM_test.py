import sys
from pathlib import Path
import glob
import os

# Add parent directory to path to import captioners
sys.path.insert(0, str(Path(__file__).parent.parent))

from captioners import SmolVLMCaptioner

# Option 1: Test with multiple frames from a video directory
video_dir = "datasets/tvqa/videos/frames_hq/bbt_frames/s01e01_seg01_clip_00"
frame_files = sorted(glob.glob(os.path.join(video_dir, "*.jpg")))[50:51]

# Option 2: Test with a single image (uncomment to use)
# frame_files = ["outputs/captioners/frame_30.jpg"]

# Initialize captioner
# For multiple frames, set chunk_size to process them together
# For single frame, chunk_size=1 processes individually
captioner = SmolVLMCaptioner(
    chunk_size=len(frame_files) if len(frame_files) > 1 else 1,
    prompt="Describe this video. Be concise." if len(frame_files) > 1 else "Describe this image. Be concise.",
    max_new_tokens=500,
)

# Generate captions
captions = captioner.caption(frame_files)
print("generated captions")
# Print results
if len(captions) == 1:
    print(captions[0])
else:
    for i, caption in enumerate(captions):
        print(f"\nCaption {i+1}/{len(captions)}:")
        print(caption)

