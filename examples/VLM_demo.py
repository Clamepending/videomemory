import os
import re
from pathlib import Path
from huggingface_hub import login

# Get token from environment
token = os.getenv('HF_TOKEN')

# Login
login(token=token)
print("✓ Authenticated with Hugging Face")

from vllm import LLM, SamplingParams

# Initialize the model
print("Loading model...")
llm = LLM(model="google/paligemma-3b-mix-224")

# Define sampling parameters
sampling_params = SamplingParams(temperature=0.8, top_p=0.95, max_tokens=50)

prompt = "My favorite color is "
outputs = llm.generate([prompt], sampling_params)

for output in outputs:
    generated_text = output.outputs[0].text
    print(f"\nPrompt: {prompt}\nGenerated text: {generated_text}")