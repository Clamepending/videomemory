#!/usr/bin/env python3
"""Run VideoIngestor on a frame sequence with two prompts and visualise side by side.

Processes the same video with two different prompt files (default vs tuned),
optionally grades each frame with an oracle model, saves captions to
outputs/results/<prompt_stem>/captions.md, and launches a local web visualiser
for qualitative comparison.

Usage (from project root):
    uv run python -m prompt_hustle.results.videoingestor_on_frame_sequence house_tour
    uv run python -m prompt_hustle.results.videoingestor_on_frame_sequence house_tour \
        --prompt1 prompt_hustle/results/default_prompt.md \
        --prompt2 prompt_hustle/prompt.md \
        --no-oracle
"""

import argparse
import json
import os
import sys
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import cv2
from pydantic import BaseModel, Field

# eval is a sibling package under prompt_hustle/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.common import (
    DATA_DIR,
    OUTPUT_DIR,
    load_frames,
    create_ingestor,
    process_frames,
)

RESULTS_OUTPUT_DIR = OUTPUT_DIR / "results"
VIDEO_INGESTOR_MODEL = os.getenv("VIDEO_INGESTOR_MODEL")
ORACLE_MODEL = os.getenv("ORACLE_MODEL", "gemini-2.5-flash")
SCRIPT_DIR = Path(__file__).resolve().parent
PROMPT_HUSTLE_ROOT = SCRIPT_DIR.parent
GRADING_PROMPT_TEMPLATE = (PROMPT_HUSTLE_ROOT / "eval" / "grading_prompt.md").read_text()


# ---------------------------------------------------------------------------
# Oracle grading
# ---------------------------------------------------------------------------

class TaskGrade(BaseModel):
    task_name: str = Field(..., description="Name of the task being graded")
    reasoning: str = Field(..., description="Brief reasoning for the grade")
    score: int = Field(..., ge=0, le=1, description="0 for incorrect, 1 for correct")


class BatchGradingResult(BaseModel):
    grades: list[TaskGrade] = Field(..., description="One grade per task")


def build_oracle_client():
    from google import genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY must be set for oracle grading.")
    return genai.Client(api_key=api_key)


def oracle_grade_frame(client, image_bytes: bytes, task_outputs: list[tuple[str, str, str]]):
    """Grade all tasks for one frame. Returns {task_name: {score, reasoning}}."""
    from google.genai import types as genai_types

    task_blocks = "\n\n".join(
        f"Task '{tname}':\n  Description: {tdesc}\n  Model output: {vlm_out}"
        for tname, tdesc, vlm_out in task_outputs
    )
    grading_prompt = GRADING_PROMPT_TEMPLATE.format(task_blocks=task_blocks)
    image_part = genai_types.Part(
        inline_data=genai_types.Blob(data=image_bytes, mime_type="image/jpeg")
    )
    response = client.models.generate_content(
        model=ORACLE_MODEL,
        contents=[image_part, genai_types.Part(text=grading_prompt)],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=BatchGradingResult.model_json_schema(),
        ),
    )
    raw = getattr(response, "text", None)
    if not raw:
        raise RuntimeError("Oracle model returned empty response.")
    result = BatchGradingResult.model_validate_json(raw)
    return {
        g.task_name: {"score": g.score, "reasoning": g.reasoning}
        for g in result.grades
    }


# ---------------------------------------------------------------------------
# Ingestor runner
# ---------------------------------------------------------------------------

def load_video_tasks(tasks_dir: Path) -> list[tuple[str, str]]:
    """Load all .md task files from a directory. Returns [(name, desc), ...]."""
    return [
        (p.stem, p.read_text().strip())
        for p in sorted(tasks_dir.glob("*.md"))
        if p.read_text().strip()
    ]


def run_ingestor_with_prompt(
    prompt_path: Path,
    model_name: str | None,
    task_descs: list[tuple[str, str]],
    frames: list[tuple[str, object]],
    oracle_client=None,
) -> list[dict]:
    """Run the ingestor on all frames with the given prompt. Returns per-frame results."""
    custom_instructions = prompt_path.read_text().strip()
    if not custom_instructions:
        sys.exit(f"Prompt file is empty: {prompt_path}")

    ingestor, tasks = create_ingestor(
        task_descs,
        model_name,
        custom_instructions=custom_instructions,
    )
    task_map = {
        t.task_number: (name, desc)
        for t, (name, desc) in zip(tasks, task_descs)
    }

    results = []
    for r in process_frames(ingestor, tasks, frames):
        filename = r["filename"]
        label = f"[{r['index'] + 1}/{r['total']}] {filename}"
        entry: dict = {"index": r["index"], "filename": filename}

        if r["status"] == "error":
            print(f"  {label}  -> error ({r['error']})")
            entry.update(status="error", error=r["error"])
        elif r["status"] == "skipped":
            print(f"  {label}  -> skipped")
            entry.update(status="skipped")
        else:
            per_task = {}
            for tn, (tname, _) in task_map.items():
                per_task[tname] = r["per_task_outputs"].get(tn, "(no output)")

            ms = r["processing_time_ms"]
            entry.update(
                status="processed",
                processing_time_ms=ms,
                prompt=r["prompt"],
                per_task_outputs=per_task,
            )

            if oracle_client is not None:
                _, buf = cv2.imencode(".jpg", r["frame"])
                batch_input = [
                    (tname, tdesc, per_task.get(tname, "(no output)"))
                    for tname, tdesc in task_descs
                ]
                try:
                    t0 = time.time()
                    grades = oracle_grade_frame(oracle_client, bytes(buf), batch_input)
                    oracle_ms = round((time.time() - t0) * 1000)
                    entry["oracle_grades"] = grades
                    entry["oracle_time_ms"] = oracle_ms
                    scores = [g["score"] for g in grades.values()]
                    score_str = f"{sum(scores)}/{len(scores)}"
                    print(f"  {label}  -> {ms}ms  oracle={score_str} ({oracle_ms}ms)")
                except Exception as e:
                    print(f"  {label}  -> {ms}ms  oracle_error={e}")
                    entry["oracle_grades"] = {}
                    entry["oracle_time_ms"] = -1
            else:
                print(f"  {label}  -> {ms}ms")

        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def save_captions_md(
    out_path: Path,
    video_name: str,
    prompt_path: Path,
    frame_results: list[dict],
):
    """Save a human-readable markdown file with captions and oracle grades."""
    processed = [f for f in frame_results if f["status"] == "processed"]
    skipped = sum(1 for f in frame_results if f["status"] == "skipped")
    errors = sum(1 for f in frame_results if f["status"] == "error")
    has_oracle = any(f.get("oracle_grades") for f in frame_results)

    lines = [
        f"# Captions — {video_name}",
        "",
        f"**Prompt:** `{prompt_path}`  ",
        f"**Model:** `{VIDEO_INGESTOR_MODEL or 'default'}`  ",
        f"**Oracle:** `{ORACLE_MODEL}`  " if has_oracle else "",
        f"**Frames:** {len(frame_results)} total, {len(processed)} processed, "
        f"{skipped} skipped, {errors} errors",
        "",
        "---",
        "",
    ]

    for fr in frame_results:
        lines.append(f"## Frame {fr['index'] + 1}: {fr['filename']}")
        if fr["status"] == "error":
            lines.append(f"**Status:** error — {fr.get('error', 'unknown')}")
        elif fr["status"] == "skipped":
            lines.append("**Status:** skipped (duplicate frame)")
        else:
            lines.append(
                f"**Status:** processed ({fr.get('processing_time_ms', '?')}ms)"
            )
            lines.append("")
            outputs = fr.get("per_task_outputs", {})
            grades = fr.get("oracle_grades", {})
            for tname, output in outputs.items():
                grade = grades.get(tname)
                if grade:
                    icon = "\u2705" if grade["score"] == 1 else "\u274c"
                    lines.append(
                        f"- **{tname}:** {output}  \n"
                        f"  {icon} **Oracle ({grade['score']}):** {grade['reasoning']}"
                    )
                else:
                    lines.append(f"- **{tname}:** {output}")
        lines.append("")
        lines.append("---")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    print(f"  Saved: {out_path}")


def save_captions_json(out_path: Path, data: dict):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {out_path}")


# ---------------------------------------------------------------------------
# Visualiser
# ---------------------------------------------------------------------------

VISUALIZER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VLM Caption Comparison</title>
<style>
  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #111827; color: #e5e7eb; min-height: 100vh;
  }
  .header {
    background: #1f2937; padding: 14px 24px;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #374151;
  }
  .header h1 { font-size: 17px; font-weight: 600; color: #f9fafb; }
  .nav { display: flex; align-items: center; gap: 10px; }
  .nav button {
    background: #374151; color: #e5e7eb; border: 1px solid #4b5563;
    padding: 7px 16px; border-radius: 6px; cursor: pointer; font-size: 13px;
    transition: background 0.15s;
  }
  .nav button:hover { background: #4b5563; }
  .nav button:disabled { opacity: 0.35; cursor: default; background: #374151; }
  .counter { font-size: 13px; color: #9ca3af; min-width: 80px; text-align: center; }
  .frame-wrap {
    display: flex; justify-content: center; padding: 18px; background: #0f172a;
  }
  .frame-wrap img {
    max-width: 780px; max-height: 420px; border-radius: 6px;
    border: 1px solid #1e293b; display: block;
  }
  .status-bar {
    text-align: center; padding: 7px; font-size: 12px;
    color: #6b7280; background: #1f2937; border-top: 1px solid #374151;
  }
  .cols {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 1px; background: #374151;
  }
  .col { background: #111827; padding: 18px; min-height: 260px; }
  .col h2 {
    font-size: 14px; font-weight: 600; margin-bottom: 10px;
    padding-bottom: 7px; border-bottom: 2px solid #1f2937;
  }
  .col:first-child h2 { color: #38bdf8; }
  .col:last-child  h2 { color: #f472b6; }
  .lbl {
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px;
    color: #6b7280; margin: 12px 0 5px;
  }
  .block {
    background: #0f172a; border-radius: 5px; padding: 10px; font-size: 13px;
    line-height: 1.55; white-space: pre-wrap; word-break: break-word;
    max-height: 320px; overflow-y: auto;
  }
  .task-row { margin-bottom: 10px; }
  .tname { font-weight: 600; color: #fbbf24; font-size: 12px; }
  .tval  { color: #d1d5db; }
  .grade {
    margin-top: 3px; padding: 4px 8px; border-radius: 4px;
    font-size: 11px; line-height: 1.4;
  }
  .grade-pass { background: #052e16; color: #86efac; border-left: 3px solid #22c55e; }
  .grade-fail { background: #2a0a0a; color: #fca5a5; border-left: 3px solid #ef4444; }
  .grade-icon { margin-right: 4px; }
  details { margin-top: 4px; }
  details summary {
    cursor: pointer; font-size: 11px; color: #6b7280; user-select: none;
  }
  details summary:hover { color: #9ca3af; }
  details .block { margin-top: 5px; max-height: 180px; font-size: 11px; color: #9ca3af; }
  .badge {
    display: inline-block; padding: 1px 7px; border-radius: 4px;
    font-size: 10px; font-weight: 600; margin-left: 6px; vertical-align: middle;
  }
  .b-processed { background: #064e3b; color: #6ee7b7; }
  .b-skipped   { background: #713f12; color: #fde68a; }
  .b-error     { background: #7f1d1d; color: #fca5a5; }
  .score-summary {
    display: inline-block; margin-left: 8px; font-size: 11px;
    color: #9ca3af; font-weight: 400;
  }
</style>
</head>
<body>
<div class="header">
  <h1>VLM Caption Comparison</h1>
  <div class="nav">
    <button id="prev" onclick="go(-1)">&larr; Prev</button>
    <span class="counter" id="ctr">1 / 1</span>
    <button id="next" onclick="go(1)">Next &rarr;</button>
  </div>
</div>
<div class="frame-wrap"><img id="img" src="" alt="frame"></div>
<div class="status-bar" id="sbar"></div>
<div class="cols">
  <div class="col" id="left"></div>
  <div class="col" id="right"></div>
</div>
<script>
let D, idx = 0;
async function init() {
  D = await (await fetch('/api/data')).json();
  render();
}
function go(d) {
  const n = idx + d;
  if (D && n >= 0 && n < D.total_frames) { idx = n; render(); }
}
document.addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft') go(-1);
  if (e.key === 'ArrowRight') go(1);
});
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}
function bc(s) {
  return s === 'processed' ? 'b-processed' : s === 'skipped' ? 'b-skipped' : 'b-error';
}
function renderCol(name, f) {
  let h = `<h2>${esc(name)} <span class="badge ${bc(f.status)}">${f.status}</span>`;
  if (f.oracle_grades && Object.keys(f.oracle_grades).length) {
    const scores = Object.values(f.oracle_grades).map(g => g.score);
    const sum = scores.reduce((a,b) => a+b, 0);
    h += `<span class="score-summary">${sum}/${scores.length} correct</span>`;
  }
  h += '</h2>';

  h += '<div class="lbl">Output &amp; Oracle Grade</div>';
  if (f.per_task_outputs) {
    h += '<div class="block">';
    for (const [t, v] of Object.entries(f.per_task_outputs)) {
      h += '<div class="task-row">';
      h += `<div><span class="tname">${esc(t)}:</span> <span class="tval">${esc(v)}</span></div>`;
      const g = f.oracle_grades && f.oracle_grades[t];
      if (g) {
        const cls = g.score === 1 ? 'grade-pass' : 'grade-fail';
        const icon = g.score === 1 ? '\u2705' : '\u274c';
        h += `<div class="grade ${cls}"><span class="grade-icon">${icon}</span>${esc(g.reasoning)}</div>`;
      }
      h += '</div>';
    }
    h += '</div>';
  } else if (f.error) {
    h += `<div class="block" style="color:#fca5a5">${esc(f.error)}</div>`;
  } else {
    h += '<div class="block" style="color:#6b7280">(no output)</div>';
  }
  if (f.prompt) {
    h += '<details><summary>Show VLM prompt (input)</summary>';
    h += `<div class="block">${esc(f.prompt)}</div></details>`;
  }
  return h;
}
function render() {
  if (!D) return;
  const f1 = D.prompt1.frames[idx], f2 = D.prompt2.frames[idx];
  document.getElementById('ctr').textContent = `${idx+1} / ${D.total_frames}`;
  document.getElementById('img').src = `/frames/${f1.filename}`;
  document.getElementById('prev').disabled = idx === 0;
  document.getElementById('next').disabled = idx === D.total_frames - 1;
  const t = ms => ms != null && ms >= 0 ? `${ms}ms` : '';
  const orc = f => {
    if (!f.oracle_grades || !Object.keys(f.oracle_grades).length) return '';
    const scores = Object.values(f.oracle_grades).map(g => g.score);
    return ` oracle=${scores.reduce((a,b)=>a+b,0)}/${scores.length}`;
  };
  document.getElementById('sbar').textContent =
    `${f1.filename}  \u00b7  ${D.prompt1.name}: ${f1.status} ${t(f1.processing_time_ms)}${orc(f1)}  \u00b7  ${D.prompt2.name}: ${f2.status} ${t(f2.processing_time_ms)}${orc(f2)}`;
  document.getElementById('left').innerHTML  = renderCol(D.prompt1.name, f1);
  document.getElementById('right').innerHTML = renderCol(D.prompt2.name, f2);
}
init();
</script>
</body>
</html>"""


def start_visualizer(
    frames_dir: Path,
    prompt1_data: dict,
    prompt2_data: dict,
    port: int,
):
    """Launch a local HTTP server with the comparison visualiser."""
    combined = json.dumps({
        "video_name": prompt1_data["video_name"],
        "total_frames": len(prompt1_data["frames"]),
        "tasks": prompt1_data["tasks"],
        "prompt1": {
            "name": prompt1_data["prompt_stem"],
            "file": prompt1_data["prompt_file"],
            "frames": prompt1_data["frames"],
        },
        "prompt2": {
            "name": prompt2_data["prompt_stem"],
            "file": prompt2_data["prompt_file"],
            "frames": prompt2_data["frames"],
        },
    }).encode()

    fdir = frames_dir

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._respond(200, "text/html", VISUALIZER_HTML.encode())
            elif path == "/api/data":
                self._respond(200, "application/json", combined)
            elif path.startswith("/frames/"):
                fpath = fdir / path[len("/frames/"):]
                if fpath.is_file():
                    self._respond(200, "image/jpeg", fpath.read_bytes())
                else:
                    self._respond(404, "text/plain", b"not found")
            else:
                self._respond(404, "text/plain", b"not found")

        def _respond(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"\nVisualiser: {url}")
    print("Use \u2190 \u2192 arrow keys to navigate frames. Ctrl+C to stop.\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run VideoIngestor with two prompts and compare side by side",
    )
    parser.add_argument(
        "video_name",
        help="Video directory name under data/{split}/frames/",
    )
    parser.add_argument(
        "--prompt1",
        default=str(SCRIPT_DIR / "default_prompt.md"),
        help="First prompt file (default: results/default_prompt.md)",
    )
    parser.add_argument(
        "--prompt2",
        default=str(PROMPT_HUSTLE_ROOT / "prompt.md"),
        help="Second prompt file (default: prompt.md)",
    )
    parser.add_argument(
        "--model", default=VIDEO_INGESTOR_MODEL,
        help="Model name (default: VIDEO_INGESTOR_MODEL from .env)",
    )
    parser.add_argument(
        "--split", default="train", choices=["train", "validation"],
    )
    parser.add_argument(
        "--no-oracle", action="store_true",
        help="Skip oracle grading",
    )
    parser.add_argument(
        "--no-visualizer", action="store_true",
        help="Skip launching the browser visualiser",
    )
    parser.add_argument("--port", type=int, default=8765, help="Visualiser port")
    args = parser.parse_args()

    prompt1_path = Path(args.prompt1)
    prompt2_path = Path(args.prompt2)
    for p in (prompt1_path, prompt2_path):
        if not p.exists():
            sys.exit(f"Prompt file not found: {p}")

    frames_dir = DATA_DIR / args.split / "frames" / args.video_name
    tasks_dir = DATA_DIR / args.split / "tasks" / args.video_name
    if not frames_dir.exists():
        sys.exit(f"Frames directory not found: {frames_dir}")
    if not tasks_dir.is_dir():
        sys.exit(f"Tasks directory not found: {tasks_dir}")

    task_descs = load_video_tasks(tasks_dir)
    if not task_descs:
        sys.exit(f"No task .md files found in {tasks_dir}")

    oracle_client = None
    if not args.no_oracle:
        try:
            oracle_client = build_oracle_client()
            print(f"Oracle:  {ORACLE_MODEL}")
        except RuntimeError as e:
            print(f"Warning: oracle disabled — {e}")

    frames = load_frames(frames_dir)
    print(f"Video:   {args.video_name} ({args.split})")
    print(f"Frames:  {len(frames)}")
    print(f"Tasks:   {len(task_descs)}")
    print(f"Model:   {args.model or 'default (from .env)'}")
    print(f"Prompt1: {prompt1_path}")
    print(f"Prompt2: {prompt2_path}")
    print()

    all_results: dict[str, dict] = {}
    for prompt_path in (prompt1_path, prompt2_path):
        stem = prompt_path.stem
        print(f"{'=' * 60}")
        print(f"Running: {stem}  ({prompt_path})")
        print(f"{'=' * 60}")

        t0 = time.time()
        frame_results = run_ingestor_with_prompt(
            prompt_path, args.model, task_descs, frames,
            oracle_client=oracle_client,
        )
        elapsed = round(time.time() - t0, 1)
        processed = sum(1 for f in frame_results if f["status"] == "processed")
        print(f"  Done in {elapsed}s — {processed}/{len(frame_results)} processed")

        if oracle_client:
            graded = [f for f in frame_results if f.get("oracle_grades")]
            if graded:
                all_scores = [
                    g["score"]
                    for f in graded
                    for g in f["oracle_grades"].values()
                ]
                acc = sum(all_scores) / len(all_scores) if all_scores else 0
                print(f"  Oracle accuracy: {acc:.2%} ({sum(all_scores)}/{len(all_scores)})")

        out_dir = RESULTS_OUTPUT_DIR / stem
        save_captions_md(out_dir / "captions.md", args.video_name, prompt_path, frame_results)

        result_data = {
            "video_name": args.video_name,
            "split": args.split,
            "prompt_file": str(prompt_path),
            "prompt_stem": stem,
            "model": args.model,
            "tasks": [{"name": n, "description": d} for n, d in task_descs],
            "frames": frame_results,
        }
        save_captions_json(out_dir / "captions.json", result_data)
        all_results[stem] = result_data
        print()

    stems = list(all_results.keys())
    if not args.no_visualizer and len(stems) >= 2:
        start_visualizer(
            frames_dir,
            all_results[stems[0]],
            all_results[stems[1]],
            port=args.port,
        )


if __name__ == "__main__":
    main()
