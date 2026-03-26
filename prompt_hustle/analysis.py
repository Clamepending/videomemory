#!/usr/bin/env python3
"""Analyse prompt_hustle experiment results.

Reads results.tsv and prompt_log.jsonl and produces:
  1. An accuracy-over-experiments plot (saved as PNG).
  2. A text summary of the prompt evolution (printed to stdout).

Usage (from project root):
    uv run python prompt_hustle/analysis.py
    uv run python prompt_hustle/analysis.py --out prompt_hustle/progress.png
"""

import argparse
import json
import textwrap
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parent
RESULTS_TSV = ROOT / "results.tsv"
PROMPT_LOG = ROOT / "prompt_log.jsonl"
DEFAULT_PNG = ROOT / "progress.png"


def load_results(path: Path) -> list[dict]:
    rows = []
    with open(path) as f:
        header = f.readline().strip().split("\t")
        for line in f:
            vals = line.strip().split("\t")
            if len(vals) < len(header):
                continue
            row = dict(zip(header, vals))
            row["accuracy"] = float(row.get("accuracy", 0))
            row["graded"] = int(row.get("graded", 0))
            if "timestamp" in row:
                try:
                    row["_dt"] = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
                except ValueError:
                    row["_dt"] = None
            else:
                row["_dt"] = None
            rows.append(row)
    return rows


def load_prompt_log(path: Path) -> dict[str, dict]:
    """Return a dict keyed by commit hash with full prompt text."""
    entries = {}
    if not path.exists():
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                key = obj.get("commit", "")
                entries[key] = obj
            except json.JSONDecodeError:
                continue
    return entries


def plot_accuracy(rows: list[dict], out_path: Path):
    if not rows:
        print("No results to plot.")
        return

    has_timestamps = all(r.get("_dt") for r in rows)

    fig, ax = plt.subplots(figsize=(12, 5))

    colors = {"keep": "#2ecc71", "discard": "#e74c3c", "crash": "#95a5a6"}
    status_labels_seen = set()

    if has_timestamps:
        x_vals = [r["_dt"] for r in rows]
        ax.set_xlabel("Time")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        fig.autofmt_xdate(rotation=30)
    else:
        x_vals = list(range(len(rows)))
        ax.set_xlabel("Experiment #")

    best_so_far = 0.0
    best_line_x = []
    best_line_y = []

    for i, (x, row) in enumerate(zip(x_vals, rows)):
        status = row.get("status", "keep")
        color = colors.get(status, "#3498db")
        label = status if status not in status_labels_seen else None
        status_labels_seen.add(status)
        ax.scatter(x, row["accuracy"], c=color, s=60, zorder=3, label=label, edgecolors="white", linewidths=0.5)

        if row["accuracy"] > best_so_far:
            best_so_far = row["accuracy"]
        best_line_x.append(x)
        best_line_y.append(best_so_far)

    ax.plot(best_line_x, best_line_y, color="#2c3e50", linewidth=1.5, linestyle="--", alpha=0.7, label="best so far")

    ax.set_ylabel("Accuracy")
    ax.set_title("prompt_hustle — accuracy over experiments")
    ax.set_ylim(-0.05, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Plot saved to {out_path}")
    plt.close(fig)


def print_prompt_evolution(rows: list[dict], prompt_log: dict[str, dict]):
    print("\n" + "=" * 70)
    print("PROMPT EVOLUTION")
    print("=" * 70)

    for i, row in enumerate(rows):
        status = row.get("status", "?")
        acc = row["accuracy"]
        desc = row.get("description", "")
        commit = row.get("commit", "?")
        ts = row.get("timestamp", "")

        marker = {"keep": "+", "discard": "x", "crash": "!!"}.get(status, "?")
        print(f"\n[{marker}] #{i}  {ts}  {commit}  acc={acc:.4f}  ({status})")
        print(f"    {desc}")

        entry = prompt_log.get(commit)
        if entry and "prompt" in entry:
            prompt_text = entry["prompt"]
            if isinstance(prompt_text, str):
                try:
                    prompt_text = json.loads(prompt_text)
                except (json.JSONDecodeError, TypeError):
                    pass
            wrapped = textwrap.indent(prompt_text.strip(), "    | ")
            print(f"    prompt text:")
            print(wrapped)

    print("\n" + "=" * 70)

    keeps = [r for r in rows if r.get("status") == "keep"]
    discards = [r for r in rows if r.get("status") == "discard"]
    crashes = [r for r in rows if r.get("status") == "crash"]
    best = max(rows, key=lambda r: r["accuracy"]) if rows else None

    print(f"Total experiments: {len(rows)}")
    print(f"  Kept:      {len(keeps)}")
    print(f"  Discarded: {len(discards)}")
    print(f"  Crashed:   {len(crashes)}")
    if best:
        print(f"  Best acc:  {best['accuracy']:.4f} ({best.get('description', '?')})")


def main():
    parser = argparse.ArgumentParser(description="Analyse prompt_hustle experiments")
    parser.add_argument("--out", default=str(DEFAULT_PNG), help="Path to save the accuracy plot PNG")
    args = parser.parse_args()

    if not RESULTS_TSV.exists():
        print(f"No results file found at {RESULTS_TSV}")
        print("Run some experiments first!")
        return

    rows = load_results(RESULTS_TSV)
    prompt_log = load_prompt_log(PROMPT_LOG)

    print(f"Loaded {len(rows)} experiments from {RESULTS_TSV}")
    if prompt_log:
        print(f"Loaded {len(prompt_log)} prompt snapshots from {PROMPT_LOG}")

    plot_accuracy(rows, Path(args.out))
    print_prompt_evolution(rows, prompt_log)


if __name__ == "__main__":
    main()
