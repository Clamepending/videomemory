import sys
import argparse
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datasets import TVQALong
from captioners import PaligemmaCaptioner, Qwen2VLCaptioner

parser = argparse.ArgumentParser(description="Generate captions with a custom prompt")
parser.add_argument("--prompt", type=str, required=True, help="Custom prompt for the captioning model")
parser.add_argument("--show", type=str, default="bbt", help="Show name (default: bbt)")
parser.add_argument("--season", type=str, default="s01", help="Season (default: s01)")
parser.add_argument("--episode", type=str, default="e01", help="Episode (default: e01)")
parser.add_argument("--split", type=str, default="train", help="Dataset split (default: train)")
parser.add_argument("--stride", type=int, default=30, help="Frame stride for Paligemma (default: 30)")
parser.add_argument("--captioner", type=str, choices=["paligemma", "qwen2vl"], default="qwen2vl", help="Captioner to use")
parser.add_argument("--chunk-size", type=int, default=30, help="Video chunk size for Qwen2VL (default: 30)")
parser.add_argument("--fps", type=float, default=3.0, help="FPS for Qwen2VL (default: 3.0)")

args = parser.parse_args()

# Initialize captioner
if args.captioner == "paligemma":
    CAPTIONER = PaligemmaCaptioner(stride=args.stride, prompt=args.prompt)
elif args.captioner == "qwen2vl":
    CAPTIONER = Qwen2VLCaptioner(prompt=args.prompt, chunk_size=args.chunk_size, fps=args.fps)

# Delete existing output directory and create fresh one
model_name = CAPTIONER.model_id.split("/")[-1]
output_dir = Path(f"outputs/captioners/{model_name}/custom_caption")
if output_dir.exists():
    shutil.rmtree(output_dir)
output_dir.mkdir(parents=True, exist_ok=True)

# Get all frames from episode
dataset = TVQALong()
episode = dataset.get_episode(args.show, args.season, args.episode, split=args.split)

all_frames = []
for clip_name in episode['clips']:
    all_frames.extend(dataset.get_clip_frames(clip_name, show=args.show))
all_frames.sort()

# Generate captions
print(f"Generating captions for {len(all_frames)} frames with prompt: '{args.prompt}'")
captions = CAPTIONER.caption(all_frames)

# Save captions by chunk (for Paligemma, chunk = 1 frame; for Qwen2VL, chunk = multiple frames)
num_chunks = len(captions)
for chunk_idx, caption in enumerate(captions):
    if caption:
        output_path = output_dir / f"chunk_{chunk_idx + 1:06d}_of_{num_chunks:06d}.md"
        output_path.write_text(f"Chunk {chunk_idx + 1}/{num_chunks}: {caption}")

print(f"Saved {sum(1 for c in captions if c)} captions in {num_chunks} chunks to {output_dir}")
