from transformers import Qwen2VLForConditionalGeneration, AutoTokenizer, AutoProcessor
from transformers.generation.streamers import BaseStreamer
from qwen_vl_utils import process_vision_info
import glob
import os
import time

# default: Load the model on the available device(s)
model = Qwen2VLForConditionalGeneration.from_pretrained(
    "Qwen/Qwen2-VL-7B-Instruct", torch_dtype="auto", device_map="auto"
)

# We recommend enabling flash_attention_2 for better acceleration and memory saving, especially in multi-image and video scenarios.
# model = Qwen2VLForConditionalGeneration.from_pretrained(
#     "Qwen/Qwen2-VL-7B-Instruct",
#     torch_dtype=torch.bfloat16,
#     attn_implementation="flash_attention_2",
#     device_map="auto",
# )

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
        self.token_count += 1
    
    def end(self):
        pass

# The default range for the number of visual tokens per image in the model is 4-16384. You can set min_pixels and max_pixels according to your needs, such as a token count range of 256-1280, to balance speed and memory usage.
# min_pixels = 256*28*28
# max_pixels = 1280*28*28
# processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-7B-Instruct", min_pixels=min_pixels, max_pixels=max_pixels)

# Get all frame files from the video directory
video_dir = "datasets/tvqa/videos/frames_hq/bbt_frames/s01e01_seg01_clip_00"
frame_files = sorted(glob.glob(os.path.join(video_dir, "*.jpg")))
# Convert to file:// URLs
frame_urls = [f"file://{os.path.abspath(frame)}" for frame in frame_files][:30]

# Process frames in chunks of 6
chunk_size = 1
total_chunks = (len(frame_urls) + chunk_size - 1) // chunk_size
print(f"Processing {len(frame_urls)} frames in {total_chunks} chunks of {chunk_size} frames each\n")

for chunk_idx in range(total_chunks):
    start_frame = chunk_idx * chunk_size
    end_frame = min(start_frame + chunk_size, len(frame_urls))
    chunk_frames = frame_urls[start_frame:end_frame]
    
    print(f"Chunk {chunk_idx + 1}/{total_chunks} (frames {start_frame}-{end_frame-1}):")
    
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "video",
                    "video": chunk_frames,
                    "fps": 3.0,
                },
                {"type": "text", "text": "Describe this video."},
            ],
        }
    ]
    
    # Preparation for inference
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    inputs = inputs.to("cuda")
    
    # Inference: Generation of the output with timing
    start_time = time.time()
    streamer = TimingStreamer(start_time)
    generated_ids = model.generate(**inputs, max_new_tokens=512, streamer=streamer)
    end_time = time.time()
    
    generated_ids_trimmed = [
        out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )
    
    time_to_first_token = streamer.first_token_time - start_time if streamer.first_token_time else None
    time_to_completion = end_time - start_time
    
    if time_to_first_token is not None:
        print(f"  Time to first token: {time_to_first_token:.3f} seconds")
    else:
        print(f"  Time to first token: N/A")
    print(f"  Time to completion: {time_to_completion:.2f} seconds")
    print(f"  Caption: {output_text[0]}\n")
