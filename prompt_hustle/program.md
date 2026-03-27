# prompt_hustle

Autonomous prompt engineering for VideoMemory video ingestor. Multi-agent safe.

## Context

VideoMemory is a video monitoring system. A VLM analyses video frames and produces structured observations. The VLM prompt has two parts:

1. **Task XML** - injected per-task, same format as the real system (task_number, task_desc, task_newest_note).
2. **Universal instructions** - the instructions block that tells the VLM how to process any task. This is what you optimise.

The evaluation runs many different tasks (count people, detect luggage, describe clothing, etc.) across multiple videos. The overall metric is **overall_accuracy** (oracle-graded, 0/1 per frame) averaged across all tasks and videos. Higher is better.

**Your job**: craft universal instructions that work well across ALL tasks and videos, not just one.

## Setup

1. Agree on a run tag (e.g. `mar27`). The shared branch is `prompt_hustle_multiagent/<tag>/main`.
2. Generate a random 4-character agent ID (e.g. `a3f2`). This identifies your work branches.
3. Create or checkout the shared branch `prompt_hustle_multiagent/<tag>/main`. If it doesn't exist, create it and initialize `results/results.tsv` with the header row.
4. Read in-scope files: program.md, prompt.md (only file you edit), data/train/tasks/<video name>/*.md (fixed test cases), eval/run.py (do not modify).
5. Verify data exists in data/train/frames/ and data/validation/frames/.

## What you CAN and CANNOT do

CAN: Modify prompt_hustle/prompt.md. This content replaces the instructions block in the VLM prompt.

CANNOT: Modify prompts/*.md, eval/run.py, .env, or any VideoMemory source code.

## Running an evaluation

```
uv run python -m eval --instructions prompt.md > outputs/logs/run.log 2>&1
```

Run from the `prompt_hustle/` directory. Extract metrics from outputs/logs/run.log:
- Use `overall_accuracy` as the optimization target (training metric only).
- Record `validation_overall_accuracy` for human tracking only (do not consider this at all. This is just for another agent).
- Do not use validation accuracy to decide keep/revert.

## Logging results

results/results.tsv: tab-separated with columns: timestamp, branch, train_accuracy, validation_accuracy, graded, status, train_oracle_time_s, train_ingestor_time_s, description.

The `branch` column holds the full branch name of the experiment (e.g. `prompt_hustle_multiagent/mar27/a3f2_1430`). Any agent can `git checkout <branch>` to retrieve that prompt.

## The experiment loop

LOOP FOREVER:

### 1. Find the best starting point

- `git checkout prompt_hustle_multiagent/<tag>/main && git pull`
- Parse `results/results.tsv`. Find the row with the highest `train_accuracy`.
- If rows exist: `git checkout <best_branch>` to start from the best-known prompt.
- If no rows (header only): stay on the main branch and use the current prompt.md as-is.

### 2. Create your experiment branch

- `git checkout -b prompt_hustle_multiagent/<tag>/<agent_id>_<HHMM>`
  (use current time for `<HHMM>`, e.g. `prompt_hustle_multiagent/mar27/a3f2_1430`)

### 3. Edit and commit

- Edit `prompt_hustle/prompt.md` with a new idea.
- `git add prompt_hustle/prompt.md && git commit -m 'prompt: <description>'`

### 4. Run eval

- Run eval (see above). Redirect to `outputs/logs/run.log`.
- Read results from `outputs/logs/run.log`.
- `git add -A && git commit -m 'score: <train_accuracy>'`
- `git push -u origin HEAD`

### 5. Log results to the shared branch (atomic append with retry)

```
git checkout prompt_hustle_multiagent/<tag>/main
RETRY up to 5 times:
  git pull --rebase origin prompt_hustle_multiagent/<tag>/main
  append one row to results/results.tsv  (do NOT touch any other rows)
  git add results/results.tsv
  git commit -m 'result: <branch> <train_accuracy>'
  git push  →  if success, break; else continue retry
```

Only append your single result row. Never edit or remove existing rows.

CRITICAL: Never use git reset --hard. All experiments must remain in results/results.tsv.

NEVER STOP: Run autonomously until manually interrupted.

## Strategies to try

The instructions must work across counting, detection, description, and scene understanding tasks:

- Add examples for description tasks (Describe X -> detailed notes)
- Add examples for detection tasks (Is there X? -> yes/no with details)
- Improve no-change logic (when to emit updates vs return empty)
- Add structured observation strategies
- Tune level of detail in task_note responses
- Handle 'nothing found' tasks properly
- Try chain-of-thought reasoning before JSON output
- Vary example diversity across task categories
- Combine improvements that helped individual categories
