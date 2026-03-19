Offline experiments for running VideoMemory on local image/video datasets.

Structure:
- `data/mp4/<dataset>/`: source videos
- `data/frames/<dataset>/`: extracted frames (`*.jpg`)
- `experiments/`: experiment scripts
- `outputs/frame_sequence_experiment/`: JSON experiment results
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

With model override:
```bash
./offline/scripts/run_frame_sequence_experiment.sh --video_name house_tour --task "count chairs" --viewer_port 9000 --model local-vllm
```

## Data preprocessing

Extract frames from mp4:
```bash
./offline/data/video_to_frames.sh house_tour
```