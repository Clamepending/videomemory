"""Prompt construction and structured output models for video ingestion."""

import logging
import time
from typing import Any, List, Optional

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from ..task_types import NoteEntry, Task


logger = logging.getLogger("VideoStreamIngestor")


class TaskUpdate(BaseModel):
    """Model for task update output."""

    model_config = ConfigDict(extra="forbid")
    task_number: int = Field(..., description="The task number")
    task_note: str = Field(..., description="Updated description/note for the task")
    task_done: bool = Field(..., description="Whether the task is completed")


class VideoIngestorOutput(BaseModel):
    """Model for the complete output structure."""

    model_config = ConfigDict(extra="forbid")
    task_updates: List[TaskUpdate] = Field(default_factory=list, description="List of task updates")


VLM_INGESTOR_PROMPT_INSTRUCTIONS = """<instructions>

You are a video ingestor. Output one JSON object containing task_updates.

When task_newest_note is "None", you MUST ALWAYS output at least one task_update. Describe what you see in the image relevant to the task. NEVER return {"task_updates": []} when the newest note is "None".


CRITICAL: Any change in count, quantity, or state MUST be reported, including:
- Changes from a non-zero count to zero
- Changes from zero to a non-zero count
- Any numerical change in counts or quantities
- Changes in status, positions, or states

Include updates for:
- New observations related to the task
- Changes in status, counts, positions, or states (including transitions to/from zero)
- Progress that advances task tracking

Output format (JSON only, nothing else):
{"task_updates": [{task_number: <number>, task_note: <description>, task_done: <true/false>}, ...]}

Examples:
First observation (newest_note is None): {"task_updates": [{task_number: 0, task_note: "No people visible in frame.", task_done: false}]}

When you observe a clap for "Count claps" task: {"task_updates": [{task_number: 0, task_note: "Clap detected. Total count: 1 clap.", task_done: false}]}

When you observe 4 more claps (building on previous count): {"task_updates": [{task_number: 0, task_note: "4 more claps detected. Total count: 5 claps.", task_done: false}]}

When you observe people for "Keep track of number of people": {"task_updates": [{task_number: 1, task_note: "Currently 2 people visible in frame.", task_done: false}]}

When only 1 person is visible: {"task_updates": [{task_number: 1, task_note: "1 person is visible in frame.", task_done: false}]}

When the person leaves the frame: {"task_updates": [{task_number: 1, task_note: "Person left frame. Now 0 people visible.", task_done: false}]}

When tracking counts and the count changes to zero (e.g., most recent note says "1 item" but image shows 0): {"task_updates": [{task_number: 0, task_note: "No items visible. Count is now 0.", task_done: false}]}

When tracking counts and the count changes from zero to non-zero (e.g., most recent note says "0 items" but image shows 2): {"task_updates": [{task_number: 0, task_note: "2 items are now visible.", task_done: false}]}

When task_newest_note is "None" (first observation): {"task_updates": [{task_number: 0, task_note: "Initial observation: 1 person visible in frame.", task_done: false}]}

When there is no new information and the task notes perfectly match the image (and newest note is NOT "None"): {"task_updates": []}

For multiple task updates: {"task_updates": [{task_number: 0, task_note: "Clap count: 5", task_done: false}, {task_number: 1, task_note: "2 people visible", task_done: false}]}

When task is complete: {"task_updates": [{task_number: 0, task_note: "Task completed - 10 claps counted", task_done: true}]}
</instructions>"""


def build_video_ingestor_prompt(
    tasks: List[Task],
    *,
    context_label: Optional[Any] = None,
    visual_context: Optional[str] = None,
    include_done: bool = False,
) -> str:
    """Build the canonical VLM prompt for a set of tasks."""

    selected_tasks = list(tasks) if include_done else [task for task in tasks if not task.done]
    if not selected_tasks:
        return ""

    tasks_lines = ["<tasks>"]
    for task in selected_tasks:
        tasks_lines.append("<task>")
        tasks_lines.append(f"<task_number>{task.task_number}</task_number>")
        tasks_lines.append(f"<task_desc>{task.task_desc}</task_desc>")

        newest_note = task.task_note[-1] if task.task_note else NoteEntry(content="None", timestamp=time.time())
        note_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest_note.timestamp))
        tasks_lines.append(
            f"<task_newest_note timestamp=\"{note_time}\">{newest_note.content}</task_newest_note>"
        )
        tasks_lines.append("</task>")
    tasks_lines.append("</tasks>")

    if visual_context:
        tasks_lines.append("")
        tasks_lines.append("<visual_context>")
        tasks_lines.append(visual_context)
        tasks_lines.append("</visual_context>")

    prompt_so_far = "\n".join(tasks_lines)
    prompt_size_chars = len(prompt_so_far)
    if prompt_size_chars > 10000:
        context_suffix = f" (camera={context_label})" if context_label is not None else ""
        logger.warning("Prompt is getting large: %s characters%s", prompt_size_chars, context_suffix)

    return prompt_so_far + "\n\n" + VLM_INGESTOR_PROMPT_INSTRUCTIONS
