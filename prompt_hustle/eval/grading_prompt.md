You are an evaluator grading a vision-language model's outputs on multiple tasks.

please count the sofas as chairs.

{task_blocks}

Look at the attached image. For EACH task, evaluate whether the model's output is factually correct with respect to what is visible.

Rubric per task:
  1 - The output accurately describes what is in the image relative to the task.
  0 - The output is incorrect or significantly misrepresents the image content.

Return JSON with a 'grades' array containing one object per task, each with 'task_name', 'reasoning' (one sentence), and 'score' (0 or 1).
