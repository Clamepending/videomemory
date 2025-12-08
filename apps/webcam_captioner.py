"""
Bare bones webcam captioning using Qwen2VL.
"""

import gradio as gr
import cv2
import time
import tempfile
from pathlib import Path
import sys
import socket

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from captioners import Qwen2VLCaptioner

# Global state
is_captioning = False
current_caption = "No caption yet"
last_caption_time = 0
CAPTION_INTERVAL = 2.0  # seconds between captions

# Initialize captioner at startup
print("Loading Qwen2VL model...")
captioner = Qwen2VLCaptioner(
    prompt="What do you see in this image?",
    chunk_size=1,
    fps=1.0,
    max_new_tokens=256
)
print("Model loaded!")


def start_captioning():
    """Start auto-captioning."""
    global is_captioning
    is_captioning = True
    return "🟢 Captioning started (every 2 seconds)"


def stop_captioning():
    """Stop auto-captioning."""
    global is_captioning
    is_captioning = False
    return "⚫ Captioning stopped"


def auto_caption(frame):
    """Auto-caption frame every 2 seconds."""
    global current_caption, last_caption_time, is_captioning
    
    if not is_captioning or frame is None:
        return frame, current_caption
    
    # Check if enough time has passed since last caption
    current_time = time.time()
    time_since_last = current_time - last_caption_time
    
    if time_since_last >= CAPTION_INTERVAL:
        # Save frame to temp file
        temp_file = Path(tempfile.mkdtemp()) / "frame.jpg"
        cv2.imwrite(str(temp_file), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        
        # Generate caption
        try:
            captions = captioner.caption([str(temp_file)])
            current_caption = captions[0] if captions else "Failed to generate caption"
            last_caption_time = time.time()
            temp_file.unlink()
        except Exception as e:
            current_caption = f"Error: {str(e)}"
    
    return frame, current_caption


def find_port(start=7860):
    """Find available port."""
    for port in range(start, start + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    return None  # Let Gradio auto-select


# Create Gradio interface
with gr.Blocks() as demo:
    gr.Markdown("# Webcam Captioner")
    
    status = gr.Markdown("⚫ Captioning stopped")
    
    with gr.Row():
        input_img = gr.Image(label="Camera", sources="webcam")
        caption = gr.Textbox(label="Caption", lines=5, value="No caption yet")
    
    with gr.Row():
        start_btn = gr.Button("Start Captioning", variant="primary")
        stop_btn = gr.Button("Stop Captioning", variant="stop")
    
    start_btn.click(fn=start_captioning, outputs=status)
    stop_btn.click(fn=stop_captioning, outputs=status)
    
    # Stream frames and auto-caption every 2 seconds
    input_img.stream(
        fn=auto_caption,
        inputs=input_img,
        outputs=[input_img, caption],
        time_limit=15,
        stream_every=0.1
    )


if __name__ == "__main__":
    port = find_port(7860)
    if port:
        print(f"Using port {port}")
    else:
        print("Port 7860-7869 busy, auto-selecting port...")
    demo.launch(server_port=port)
