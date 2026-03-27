Offline experiments and evaluation for running VideoMemory on local image/video datasets.

Structure:
- `data/train/mp4/<dataset>/`: training source videos
- `data/train/frames/<dataset>/`: training extracted frames (`*.jpg`)
- `data/validation/mp4/<dataset>/`: validation source videos
- `data/validation/frames/<dataset>/`: validation extracted frames (`*.jpg`)
- `prompts/`: markdown files containing task descriptions for eval
- `experiments/`: experiment scripts
- `outputs/frame_sequence_experiment/`: JSON experiment results
- `outputs/eval/`: JSON evaluation results
- `outputs/logs/`: run logs
- `results/`: experiment artifacts (`results.tsv`, `progress.png`)
- `scripts/video_to_frames.sh`: helper to extract frames from videos

## Experiments

Run frame-sequence experiment on frames:
```bash
uv run python -m offline.experiments.videoingestor_on_frame_sequence house_tour "count chairs"
```

Run experiment + launch viewer in one command:
```bash
./offline/scripts/run_frame_sequence_experiment.sh --video_name house_tour --task "count chairs" --viewer_port 9000
```

This script always runs with `local-vllm` for inference.

## Evaluation

Run the eval pipeline on the **train** split (default):
```bash
uv run python -m offline.eval --prompt-file offline/prompts/count_people.md
```

Run on the **validation** split with `--eval`:
```bash
uv run python -m offline.eval --prompt-file offline/prompts/count_people.md --eval
```

Options:
- `--prompt-file` (required): path to a markdown file whose content is the task description
- `--eval`: switch from train to validation split
- `--model`: model name for the video ingestor (default: `VIDEO_INGESTOR_MODEL` env or `local-vllm`)
- `--no-dedup`: disable frame deduplication

The eval pipeline:
1. Runs the VideoMemory video ingestor on every frame in each video folder of the selected split
2. Sends each (frame, task, VLM output) to an oracle model (Gemini 2.5 Flash) for binary grading (0 = incorrect, 1 = correct)
3. Reports per-video and overall accuracy, saves detailed results to `outputs/eval/`

Requires `GOOGLE_API_KEY` to be set for the oracle model.

## Data preprocessing

Extract frames from mp4:
```bash
./offline/scripts/video_to_frames.sh house_tour
```
