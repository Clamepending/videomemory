# prompt_hustle

Autonomous prompt engineering for VideoMemory's video ingestor.

## Context

VideoMemory is a video monitoring system. A VLM (vision-language model) analyses video frames according to a task description and produces structured observations. The task description is defined in a prompt file (`prompts/*.md`). The evaluation pipeline (`eval/run.py`) runs the VLM on frames from a data split, then an oracle model (Gemini 2.5 Flash) grades each output for correctness (0 = wrong, 1 = correct). The overall metric is **overall_accuracy** — higher is better.

## Setup

To set up a new experiment run, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar24`). The branch `prompt_hustle/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b prompt_hustle/<tag>` from current main.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `prompt_hustle/program.md` — this file (your instructions).
   - `prompt_hustle/eval/run.py` — the evaluation harness. **Do not modify.**
   - `prompt_hustle/prompts/count_people.md` — the prompt file you iterate on. **This is the only file you edit.**
   - `videomemory/system/stream_ingestors/video_stream_ingestor.py` — read `_build_prompt()` to understand how the task description is embedded in the full VLM prompt. **Do not modify.**
4. **Verify data exists**: Check that `prompt_hustle/data/train/frames/` and `prompt_hustle/data/validation/frames/` contain video folders with `.jpg` frames.
5. **Initialize logs**: Create `prompt_hustle/results.tsv` with just the header row (`timestamp\tcommit\taccuracy\tgraded\tstatus\tdescription`). Create an empty `prompt_hustle/prompt_log.jsonl`. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

**What you CAN do:**
- Modify `prompt_hustle/prompts/count_people.md` — this is the only file you edit. The content becomes the `task_desc` field in the VLM prompt. Everything is fair game: wording, specificity, examples, formatting, constraints, step-by-step instructions to the VLM.

**What you CANNOT do:**
- Modify `prompt_hustle/eval/run.py`. It is read-only. It contains the fixed evaluation and oracle grading.
- Modify any VideoMemory source code (`videomemory/` directory).
- Install new packages or add dependencies.

**The goal is simple: get the highest overall_accuracy.** The evaluation runs the VLM on all frames in the train split and has an oracle grade each output. Your job is to craft the task description so the VLM produces the most accurate observations.

**The first run**: Your very first run should always be to establish the baseline, so run the eval with the current prompt as-is.

## Running an evaluation

From the project root:

```bash
uv run python -m prompt_hustle.eval --prompt-file prompt_hustle/prompts/count_people.md --model gemini-2.5-flash --no-dedup > prompt_hustle/run.log 2>&1
```

Always redirect output to `prompt_hustle/run.log` — do NOT use tee or let output flood your context.

Extract the key metric:

```bash
grep "^overall_accuracy:" prompt_hustle/run.log
```

If the grep output is empty, the run crashed. Run `tail -n 50 prompt_hustle/run.log` to read the error and attempt a fix.

## Output format

Once the eval finishes it prints a machine-readable summary:

```
---
overall_accuracy: 0.800000
total_graded:     115
total_correct:    92
```

## Logging results

### results.tsv

When an experiment is done, log it to `prompt_hustle/results.tsv` (tab-separated, NOT comma-separated — commas break in descriptions).

The TSV has a header row and 6 columns:

```
timestamp	commit	accuracy	graded	status	description
```

1. ISO-8601 timestamp (`date -u +%Y-%m-%dT%H:%M:%SZ`)
2. git commit hash (short, 7 chars)
3. overall_accuracy (e.g. 0.800000) — use 0.000000 for crashes
4. total frames graded (e.g. 115) — use 0 for crashes
5. status: `keep`, `discard`, or `crash`
6. short text description of what this prompt change tried

Example:

```
timestamp	commit	accuracy	graded	status	description
2026-03-23T08:00:00Z	a1b2c3d	0.800000	115	keep	baseline
2026-03-23T08:06:00Z	b2c3d4e	0.860870	115	keep	added specificity about counting individuals
2026-03-23T08:12:00Z	c3d4e5f	0.730435	115	discard	tried bullet-point format
2026-03-23T08:18:00Z	d4e5f6g	0.000000	0	crash	malformed prompt caused parse error
```

### prompt_log.jsonl

After every experiment, **also** append one JSON line to `prompt_hustle/prompt_log.jsonl` with the full prompt text. This survives git reverts and lets you reconstruct exactly what was tried.

```bash
echo '{"timestamp":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'","commit":"'"$(git rev-parse --short HEAD)"'","accuracy":0.800000,"status":"keep","description":"baseline","prompt":"'"$(cat prompt_hustle/prompts/count_people.md | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')"'"}' >> prompt_hustle/prompt_log.jsonl
```

The `prompt` field contains the **full text** of the prompt file at the time of the experiment. Since prompts may contain newlines and special characters, pipe through `json.dumps()` to escape them properly.

## The experiment loop

The experiment runs on a dedicated branch (e.g. `prompt_hustle/mar24`).

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on.
2. Edit `prompt_hustle/prompts/count_people.md` with a new prompt engineering idea.
3. git commit: `git add prompt_hustle/prompts/count_people.md && git commit -m "prompt: <short description>"`
4. Run the evaluation: `uv run python -m prompt_hustle.eval --prompt-file prompt_hustle/prompts/count_people.md --model gemini-2.5-flash --no-dedup > prompt_hustle/run.log 2>&1`
5. Read out the results: `grep "^overall_accuracy:\|^total_graded:" prompt_hustle/run.log`
6. If the grep output is empty, the run crashed. Run `tail -n 50 prompt_hustle/run.log` to read the Python stack trace and attempt a fix. If you can't get things to work after more than a few attempts, give up on that idea.
7. Log the results:
   a. Append the row to `prompt_hustle/results.tsv` (include timestamp — see Logging section).
   b. Append the prompt snapshot to `prompt_hustle/prompt_log.jsonl` (see Logging section).
   c. Commit logs: `git add prompt_hustle/results.tsv prompt_hustle/prompt_log.jsonl && git commit -m "results: <short description>"`
8. If overall_accuracy improved (higher), the prompt is kept — you're done, move to next iteration.
9. If overall_accuracy is equal or worse, **revert the prompt file only** (do NOT use `git reset --hard` — that destroys the results log):
   ```bash
   git checkout HEAD~2 -- prompt_hustle/prompts/count_people.md
   git commit -m "revert: <short description>"
   ```
   This restores the prompt file to the last-known-good version while preserving the full experiment history in results.tsv and prompt_log.jsonl.

**CRITICAL**: Never use `git reset --hard` in the experiment loop. All experiments (including discards and crashes) must remain in the git log and results.tsv so the human can review the full history.

The idea is that you are a completely autonomous prompt engineer trying things out. If they work, keep. If they don't, discard. And you're advancing the branch so that you can iterate. If you feel like you're getting stuck, you can rewind but should do this very sparingly.

**Timeout**: Each eval should take a few minutes (depends on frame count). If a run exceeds 10 minutes, kill it and treat it as a failure (discard and revert).

**Crashes**: If a run crashes, use your judgment: if it's something easy to fix (e.g. an encoding issue), fix and re-run. If the prompt idea is fundamentally broken, log "crash", revert, and move on.

**NEVER STOP**: Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep, or away from the computer and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of ideas, think harder — re-read the VLM prompt builder code, study how the task description flows into the system prompt, try combining previous near-misses, try radically different phrasings. The loop runs until the human interrupts you, period.

As an example use case, a user might leave you running while they sleep. If each experiment takes ~5 minutes then you can run approx 12/hour, for a total of about 100 over the duration of the average human sleep. The user then wakes up to a `results.tsv` full of experiments and (hopefully) a better prompt.

## Prompt engineering strategies to try

- Be more specific about what constitutes a "person" (full body, partial, silhouette, reflection)
- Add explicit instructions for edge cases (empty frames, crowded scenes, partially visible people)
- Include counting methodology ("count each distinct individual separately")
- Specify desired output format ("Currently N people visible in frame")
- Try chain-of-thought style ("First scan left to right, then count...")
- Add constraints ("Never report more people than are actually visible")
- Vary level of detail and verbosity
- Try structured vs. natural language descriptions
- Combine multiple strategies that each showed marginal improvement
