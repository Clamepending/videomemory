import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import TVQALong
from captioners import PaligemmaCaptioner

# Configuration
SHOW = "bbt"
SEASON = "s01"
EPISODE = "e01"
SPLIT = "train"
CAPTIONER = PaligemmaCaptioner(stride=30)

# Get all frames from episode
dataset = TVQALong()
episode = dataset.get_episode(SHOW, SEASON, EPISODE, split=SPLIT)

all_frames = []
for clip_name in episode['clips']:
    all_frames.extend(dataset.get_clip_frames(clip_name, show=SHOW))
all_frames.sort()

# Generate captions
print(f"Generating captions for {len(all_frames)} frames")
captions = CAPTIONER.caption(all_frames)

# Save each caption as markdown file
model_name = CAPTIONER.model_id.split("/")[-1]
output_dir = Path(f"outputs/captioners/{model_name}/default_caption")
# Clear the output directory if it exists
if output_dir.exists():
    shutil.rmtree(output_dir)
output_dir.mkdir(parents=True, exist_ok=True)

for i, caption in enumerate(captions):
    if caption:  # Only save non-empty captions
        output_path = output_dir / f"frame_{i:06d}.md"
        output_path.write_text(f"Frame {i}: {caption}")

print(f"Saved {sum(1 for c in captions if c)} captions to {output_dir}")

