import sys
import argparse
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import TVQALong
from captioners import PaligemmaCaptioner

# Parse command line arguments
parser = argparse.ArgumentParser(description="Generate captions with a custom prompt")
parser.add_argument(
    "--prompt",
    type=str,
    required=True,
    help="Custom prompt for the captioning model (e.g., 'describe this scene in detail')"
)
parser.add_argument(
    "--show",
    type=str,
    default="bbt",
    help="Show name (default: bbt)"
)
parser.add_argument(
    "--season",
    type=str,
    default="s01",
    help="Season (default: s01)"
)
parser.add_argument(
    "--episode",
    type=str,
    default="e01",
    help="Episode (default: e01)"
)
parser.add_argument(
    "--split",
    type=str,
    default="train",
    help="Dataset split (default: train)"
)
parser.add_argument(
    "--stride",
    type=int,
    default=30,
    help="Frame stride for captioning (default: 30)"
)

args = parser.parse_args()

# Configuration
SHOW = args.show
SEASON = args.season
EPISODE = args.episode
SPLIT = args.split
CAPTIONER = PaligemmaCaptioner(stride=args.stride, prompt=args.prompt)

# Get all frames from episode
dataset = TVQALong()
episode = dataset.get_episode(SHOW, SEASON, EPISODE, split=SPLIT)

all_frames = []
for clip_name in episode['clips']:
    all_frames.extend(dataset.get_clip_frames(clip_name, show=SHOW))
all_frames.sort()

# Generate captions
print(f"Generating captions for {len(all_frames)} frames with custom prompt: '{args.prompt}'")
captions = CAPTIONER.caption(all_frames)

# Save each caption as markdown file
model_name = CAPTIONER.model_id.split("/")[-1]
output_dir = Path(f"outputs/captioners/{model_name}/custom_caption")
# Clear the output directory if it exists
if output_dir.exists():
    shutil.rmtree(output_dir)
output_dir.mkdir(parents=True, exist_ok=True)

for i, caption in enumerate(captions):
    if caption:  # Only save non-empty captions
        output_path = output_dir / f"frame_{i:06d}.md"
        output_path.write_text(caption)

print(f"Saved {sum(1 for c in captions if c)} captions to {output_dir}")

