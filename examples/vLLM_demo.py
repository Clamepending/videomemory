"""
Simple vLLM demo that completes a sentence and prints it.
"""

from vllm import LLM, SamplingParams

# Initialize the model
print("Loading model...")
llm = LLM(model="gpt2")  # Using a small model for quick demo

# Define sampling parameters
sampling_params = SamplingParams(temperature=0.8, top_p=0.95, max_tokens=50)

# Prompt to complete
prompt = "The future of artificial intelligence is"

# Generate completion
outputs = llm.generate([prompt], sampling_params)

# Print the result
for output in outputs:
    generated_text = output.outputs[0].text
    print(f"\nPrompt: {prompt} \nGenerated text: {generated_text}")

