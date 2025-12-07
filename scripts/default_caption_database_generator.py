import sys
import argparse
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import TVQALong
from captioners import PaligemmaCaptioner, Qwen2VLCaptioner, SmolVLMCaptioner

parser = argparse.ArgumentParser(description="Generate default captions")
parser.add_argument("--captioner", type=str, choices=["paligemma", "qwen2vl", "smolvlm"], default="qwen2vl", help="Captioner to use")

args = parser.parse_args()

# Configuration
SHOW = "bbt"
SEASON = "s01"
EPISODE = "e01"
SPLIT = "train"

# Initialize captioner
if args.captioner == "paligemma":
    CAPTIONER = PaligemmaCaptioner(stride=30)
elif args.captioner == "qwen2vl":
    CAPTIONER = Qwen2VLCaptioner(chunk_size=30, fps=3.0)
elif args.captioner == "smolvlm":
    CAPTIONER = SmolVLMCaptioner(chunk_size=30, prompt="Describe this video.")
    
# Save each caption as markdown file
model_name = CAPTIONER.model_id.split("/")[-1]
output_dir = Path(f"outputs/captioners/{model_name}/default_caption")
if output_dir.exists():
    shutil.rmtree(output_dir)
output_dir.mkdir(parents=True, exist_ok=True)

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



# Save captions by chunk (for Paligemma, chunk = 1 frame; for Qwen2VL, chunk = multiple frames)
num_chunks = len(captions)
for chunk_idx, caption in enumerate(captions):
    if caption:
        output_path = output_dir / f"chunk_{chunk_idx + 1:06d}_of_{num_chunks:06d}.md"
        output_path.write_text(f"Chunk {chunk_idx + 1}/{num_chunks}: {caption}")

print(f"Saved {sum(1 for c in captions if c)} captions in {num_chunks} chunks to {output_dir}")
