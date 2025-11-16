import sys
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import TVQALong
from captioners import PaligemmaCaptioner

# Get 30th frame from first episode
dataset = TVQALong()
episode = dataset.get_episode("bbt", "s01", "e01", split="train")

all_frames = []
for clip_name in episode['clips']:
    all_frames.extend(dataset.get_clip_frames(clip_name, show='bbt'))
all_frames.sort()

frame_path = all_frames[29]

# Save frame
output_dir = Path("outputs/captioners")
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / "frame_30.jpg"
shutil.copy2(frame_path, output_path)
print(f"Saved frame to: {output_path}")

# Caption frame
captioner = PaligemmaCaptioner()
caption = captioner.caption([frame_path])[0]
print(f"\nCaption: {caption}")

