import sys
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import TVQALong
from captioners import PaligemmaCaptioner

# Get frames 30, 130, 230, 330 from first episode
dataset = TVQALong()
episode = dataset.get_episode("bbt", "s01", "e01", split="train")

all_frames = []
for clip_name in episode['clips']:
    all_frames.extend(dataset.get_clip_frames(clip_name, show='bbt'))
all_frames.sort()

frame_indices = [29, 129, 229, 329]  # 0-based indexing
frame_paths = [(i, all_frames[i]) for i in frame_indices if i < len(all_frames)]

# Save frames
output_dir = Path("outputs/captioners")
output_dir.mkdir(parents=True, exist_ok=True)
for frame_idx, frame_path in frame_paths:
    output_path = output_dir / f"frame_{frame_idx+1}.jpg"
    shutil.copy2(frame_path, output_path)
    print(f"Saved frame {frame_idx+1} to: {output_path}")

# Caption frames
captioner = PaligemmaCaptioner(stride=1)
captions = captioner.caption([fp for _, fp in frame_paths])

# Print captions
for (frame_idx, _), caption in zip(frame_paths, captions):
    print(f"\nFrame {frame_idx+1} caption: {caption}")

