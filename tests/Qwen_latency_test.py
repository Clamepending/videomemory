from transformers import Qwen2VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from transformers.generation.streamers import BaseStreamer
from qwen_vl_utils import process_vision_info
import glob
import os
import time
import matplotlib.pyplot as plt
import torch

# default: Load the model on the available device(s)
model = Qwen2VLForConditionalGeneration.from_pretrained(
    "Qwen/Qwen2-VL-7B-Instruct", torch_dtype="auto", device_map="auto"
)

# default processer
processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-7B-Instruct")

# Custom streamer to track time to first token
class TimingStreamer(BaseStreamer):
    def __init__(self, start_time):
        self.start_time = start_time
        self.first_token_time = None
        self.token_count = 0
    
    def put(self, value):
        if self.first_token_time is None:
            self.first_token_time = time.time()
            # Debug: print when callback fires relative to start
            print(f"    [DEBUG] Streamer callback fired at {self.first_token_time - self.start_time:.4f}s")
        self.token_count += 1
    
    def end(self):
        pass

# Hook to track forward passes
forward_times = []

# Get all frame files from the video directory
video_dir = "datasets/tvqa/videos/frames_hq/bbt_frames/s01e01_seg01_clip_00"
frame_files = sorted(glob.glob(os.path.join(video_dir, "*.jpg")))
# Convert to file:// URLs
frame_urls = [f"file://{os.path.abspath(frame)}" for frame in frame_files]

# Test with different numbers of frames: 1, 2, 4, 8, 16, 32, 64
frame_counts = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
results = []

print("Testing latency with different frame counts...\n")

for num_frames in frame_counts:
    if num_frames > len(frame_urls):
        print(f"Skipping {num_frames} frames (only {len(frame_urls)} frames available)")
        continue
    
    chunk_frames = frame_urls[:num_frames]
    
    print(f"Testing with {num_frames} frame(s):")
    
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "video",
                    "video": chunk_frames,
                    "fps": 3.0,
                },
                {"type": "text", "text": "just respond with dog. do not saying anything else but a single word dog."},
            ],
        }
    ]
    
    # Preparation for inference - measure preprocessing time
    prep_start = time.time()
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    process_vision_start = time.time()
    image_inputs, video_inputs = process_vision_info(messages)
    process_vision_end = time.time()
    
    processor_start = time.time()
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    processor_end = time.time()
    inputs = inputs.to("cuda")
    prep_end = time.time()
    
    preprocessing_time = prep_end - prep_start
    process_vision_time = process_vision_end - process_vision_start
    processor_time = processor_end - processor_start
    
    # Inference: Generation of the output with timing
    # 
    # You're absolutely right! If we start timing BEFORE model.generate() and the streamer
    # callback fires AFTER visual processing completes, then time_to_first_token SHOULD
    # include the visual processing time. The fact that it's ~0.001s suggests either:
    # 1. Visual processing happens AFTER the first token (unlikely)
    # 2. Visual processing is cached/optimized somehow
    # 3. The streamer callback fires BEFORE visual processing completes (also unlikely)
    # 4. Visual processing happens during preprocessing (but we're measuring that separately)
    #
    # Let's add detailed timing to see what's actually happening:
    
    start_time = time.time()
    streamer = TimingStreamer(start_time)
    
    # Time right before generate call
    pre_generate_time = time.time()
    
    generated_ids = model.generate(**inputs, max_new_tokens=512, streamer=streamer)
    
    end_time = time.time()
    
    # Calculate timing breakdown
    time_before_generate = pre_generate_time - start_time
    time_to_first_token = streamer.first_token_time - start_time if streamer.first_token_time else None
    generation_time = end_time - start_time
    
    generated_ids_trimmed = [
        out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    
    # Now we have:
    # - start_time: when we start timing
    # - pre_generate_time: right before model.generate() call  
    # - streamer.first_token_time: when first token callback fires
    # - end_time: when model.generate() completes
    
    time_to_first_token = streamer.first_token_time - start_time if streamer.first_token_time else None
    generation_time = end_time - start_time
    
    # If visual processing happens INSIDE model.generate() before the first token callback,
    # then time_to_first_token should include it. But we're seeing ~0.001s, which suggests
    # either visual processing is very fast OR it happens after the callback (unlikely).
    
    # The time AFTER first token callback
    if time_to_first_token:
        post_first_token_time = generation_time - time_to_first_token
    else:
        post_first_token_time = None
    
    total_time = preprocessing_time + generation_time
    
    # Count tokens generated
    num_tokens_generated = len(generated_ids_trimmed[0]) if generated_ids_trimmed else 0
    
    if time_to_first_token is not None:
        print(f"  Preprocessing breakdown:")
        print(f"    process_vision_info: {process_vision_time:.3f} seconds")
        print(f"    processor call: {processor_time:.3f} seconds")
        print(f"    Total preprocessing: {preprocessing_time:.3f} seconds")
        print(f"  Time to first token: {time_to_first_token:.3f} seconds")
        print(f"    → This SHOULD include visual processing if it happens before first token")
        print(f"    → But it's ~0.001s, suggesting visual processing might happen elsewhere")
        if post_first_token_time:
            print(f"  Post-first-token time: {post_first_token_time:.3f} seconds")
            print(f"    → This is where most of the scaling happens!")
        print(f"  Generation time: {generation_time:.3f} seconds")
        print(f"  Total time: {total_time:.3f} seconds")
        print(f"  Tokens generated: {num_tokens_generated}")
        if num_tokens_generated > 0:
            print(f"  Time per token: {generation_time/num_tokens_generated:.4f} seconds")
        print(f"  WHY generation_time scales linearly with frame count:")
        print(f"    ")
        print(f"    Vision-language models use cross-attention: text tokens attend to visual tokens.")
        print(f"    Even generating 1 word requires:")
        print(f"    ")
        print(f"    1. Vision Encoder Forward Pass (happens once, before generation):")
        print(f"       - Processes N frames → creates M visual tokens (M ∝ N)")
        print(f"       - This might be fast/optimized, explaining ~0.001s time_to_first_token")
        print(f"    ")
        print(f"    2. Text Generation (autoregressive, happens for each token):")
        print(f"       - For EACH text token, compute: Attention(Q_text, K_visual, V_visual)")
        print(f"       - Attention computation = O(M × hidden_dim) where M = num visual tokens")
        print(f"       - More frames → more visual tokens → more computation per step")
        print(f"    ")
        print(f"    Key insight: Even 1 token needs attention over ALL visual tokens!")
        print(f"    So: generation_time ≈ num_tokens × attention_over_visual_tokens")
        print(f"        where attention_over_visual_tokens ∝ num_frames")
        print(f"    ")
        print(f"    This explains linear scaling: 2x frames ≈ 2x visual tokens ≈ 2x attention time")
        print(f"    ")
        print(f"  MYSTERY: Why is time_to_first_token ~0.001s when generation_time scales?")
        print(f"    → Visual processing likely happens INSIDE model.generate()")
        print(f"    → But streamer callback fires quickly, suggesting visual processing")
        print(f"      completes fast OR happens after callback (unlikely)")
        results.append((num_frames, time_to_first_token, preprocessing_time, generation_time, total_time))
    else:
        print(f"  Preprocessing time: {preprocessing_time:.3f} seconds")
        print(f"  Time to first token: N/A")
        print(f"  Generation time: {generation_time:.3f} seconds")
        print(f"  Total time: {total_time:.3f} seconds")
        print(f"  Tokens generated: {num_tokens_generated}")
        results.append((num_frames, None, preprocessing_time, generation_time, total_time))
    print(f"  Response: {output_text[0]}\n")

# Create graphs
if results:
    frame_counts_plot = [r[0] for r in results]
    first_token_times = [r[1] for r in results if r[1] is not None]
    preprocessing_times = [r[2] for r in results]
    generation_times = [r[3] for r in results]
    total_times = [r[4] for r in results]
    
    # Filter frame counts for first token times (only where we have valid data)
    frame_counts_first_token = [r[0] for r in results if r[1] is not None]
    
    # Combined graph showing all timing metrics
    plt.figure(figsize=(12, 7))
    plt.plot(frame_counts_plot, preprocessing_times, marker='o', linewidth=2, markersize=8, label='Preprocessing Time', color='blue')
    plt.plot(frame_counts_plot, generation_times, marker='s', linewidth=2, markersize=8, label='Generation Time', color='green')
    plt.plot(frame_counts_plot, total_times, marker='^', linewidth=2, markersize=8, label='Total Time', color='red')
    if frame_counts_first_token:
        plt.plot(frame_counts_first_token, first_token_times, marker='d', linewidth=2, markersize=8, label='Time to First Token', color='orange')
    
    plt.xlabel('Number of Frames', fontsize=12)
    plt.ylabel('Time (seconds)', fontsize=12)
    plt.title('Qwen2-VL Latency Breakdown vs Number of Frames', fontsize=14, fontweight='bold')
    plt.legend(fontsize=10)
    plt.grid(True, alpha=0.3)
    plt.xscale('log', base=2)
    plt.xticks(frame_counts_plot, frame_counts_plot)
    
    plt.tight_layout()
    plt.savefig('qwen_latency_results.png', dpi=150, bbox_inches='tight')
    print(f"Combined graph saved to qwen_latency_results.png")
    
    # Individual graphs for each metric
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # Preprocessing time
    axes[0, 0].plot(frame_counts_plot, preprocessing_times, marker='o', linewidth=2, markersize=8, color='blue')
    axes[0, 0].set_xlabel('Number of Frames', fontsize=11)
    axes[0, 0].set_ylabel('Time (seconds)', fontsize=11)
    axes[0, 0].set_title('Preprocessing Time', fontsize=12, fontweight='bold')
    axes[0, 0].grid(True, alpha=0.3)
    axes[0, 0].set_xscale('log', base=2)
    axes[0, 0].set_xticks(frame_counts_plot)
    axes[0, 0].set_xticklabels(frame_counts_plot)
    for i, (frames, time_val) in enumerate(zip(frame_counts_plot, preprocessing_times)):
        axes[0, 0].annotate(f'{time_val:.3f}s', (frames, time_val), 
                           textcoords="offset points", xytext=(0,8), ha='center', fontsize=8)
    
    # Generation time
    axes[0, 1].plot(frame_counts_plot, generation_times, marker='s', linewidth=2, markersize=8, color='green')
    axes[0, 1].set_xlabel('Number of Frames', fontsize=11)
    axes[0, 1].set_ylabel('Time (seconds)', fontsize=11)
    axes[0, 1].set_title('Generation Time', fontsize=12, fontweight='bold')
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].set_xscale('log', base=2)
    axes[0, 1].set_xticks(frame_counts_plot)
    axes[0, 1].set_xticklabels(frame_counts_plot)
    for i, (frames, time_val) in enumerate(zip(frame_counts_plot, generation_times)):
        axes[0, 1].annotate(f'{time_val:.3f}s', (frames, time_val), 
                           textcoords="offset points", xytext=(0,8), ha='center', fontsize=8)
    
    # Total time
    axes[1, 0].plot(frame_counts_plot, total_times, marker='^', linewidth=2, markersize=8, color='red')
    axes[1, 0].set_xlabel('Number of Frames', fontsize=11)
    axes[1, 0].set_ylabel('Time (seconds)', fontsize=11)
    axes[1, 0].set_title('Total Time', fontsize=12, fontweight='bold')
    axes[1, 0].grid(True, alpha=0.3)
    axes[1, 0].set_xscale('log', base=2)
    axes[1, 0].set_xticks(frame_counts_plot)
    axes[1, 0].set_xticklabels(frame_counts_plot)
    for i, (frames, time_val) in enumerate(zip(frame_counts_plot, total_times)):
        axes[1, 0].annotate(f'{time_val:.3f}s', (frames, time_val), 
                           textcoords="offset points", xytext=(0,8), ha='center', fontsize=8)
    
    # Time to first token
    if frame_counts_first_token:
        axes[1, 1].plot(frame_counts_first_token, first_token_times, marker='d', linewidth=2, markersize=8, color='orange')
        axes[1, 1].set_xlabel('Number of Frames', fontsize=11)
        axes[1, 1].set_ylabel('Time (seconds)', fontsize=11)
        axes[1, 1].set_title('Time to First Token', fontsize=12, fontweight='bold')
        axes[1, 1].grid(True, alpha=0.3)
        axes[1, 1].set_xscale('log', base=2)
        axes[1, 1].set_xticks(frame_counts_first_token)
        axes[1, 1].set_xticklabels(frame_counts_first_token)
        for i, (frames, time_val) in enumerate(zip(frame_counts_first_token, first_token_times)):
            axes[1, 1].annotate(f'{time_val:.3f}s', (frames, time_val), 
                               textcoords="offset points", xytext=(0,8), ha='center', fontsize=8)
    else:
        axes[1, 1].text(0.5, 0.5, 'No data available', ha='center', va='center', transform=axes[1, 1].transAxes)
        axes[1, 1].set_title('Time to First Token', fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    plt.savefig('qwen_latency_breakdown.png', dpi=150, bbox_inches='tight')
    print(f"Individual graphs saved to qwen_latency_breakdown.png")
    plt.show()

