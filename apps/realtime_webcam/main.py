"""
FastAPI backend for real-time webcam captioning using WebSockets.
Captures frames from webcam every 2 seconds and generates captions using Qwen2VL.
"""

import asyncio
import base64
import binascii
import cv2
import numpy as np
import tempfile
import socket
import json
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sys

# Add parent directory to path to import captioners
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from captioners import Qwen2VLCaptioner

app = FastAPI(title="Real-time Webcam Captioner")

# Initialize captioner at startup
print("Loading Qwen2VL model...")
captioner = Qwen2VLCaptioner(
    prompt="Describe this image in 2 sentences.",
    chunk_size=1,
    fps=1.0,
    max_new_tokens=256
)
print("Model loaded!")

# Mount static files directory for serving HTML/JS/CSS
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def read_root():
    """Serve the main HTML page."""
    html_file = static_dir / "index.html"
    if html_file.exists():
        return FileResponse(str(html_file))
    return {"message": "Please create index.html in the static directory"}


@app.websocket("/ws/captioning")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time frame captioning.
    
    Client sends JSON messages with type "frame" or "prompt":
    - {"type": "frame", "data": "data:image/jpeg;base64,..."}
    - {"type": "prompt", "prompt": "new prompt text"}
    Server processes them and returns captions.
    """
    await websocket.accept()
    print("Client connected")
    
    # Store current prompt for this connection (default to captioner's prompt)
    current_prompt = captioner.prompt
    
    try:
        while True:
            # 1. RECEIVE MESSAGE (Async/Await prevents blocking)
            data = await websocket.receive_text()
            
            # Try to parse as JSON (for prompt updates or structured frame messages)
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                
                if msg_type == "prompt":
                    # Update prompt
                    new_prompt = message.get("prompt", "").strip()
                    if new_prompt:
                        current_prompt = new_prompt
                        captioner.prompt = current_prompt
                        await websocket.send_text(json.dumps({"type": "prompt_updated", "prompt": current_prompt}))
                        print(f"Prompt updated: {current_prompt}")
                    continue
                elif msg_type == "frame":
                    # Extract frame data
                    frame_data = message.get("data", "")
                    if not frame_data:
                        await websocket.send_text("Error: No frame data provided")
                        continue
                else:
                    # Unknown message type, try to treat as base64 image (backward compatibility)
                    frame_data = data
            except (json.JSONDecodeError, KeyError):
                # Not JSON, treat as base64 image data (backward compatibility)
                frame_data = data
            
            # 2. DECODE FRAME from base64
            try:
                # Handle data URL format: "data:image/jpeg;base64,/9j/4AAQ..."
                if "," in frame_data:
                    header, encoded = frame_data.split(",", 1)
                else:
                    encoded = frame_data
                
                if not encoded:
                    await websocket.send_text("Error: Empty frame data")
                    continue
                
                frame_bytes = base64.b64decode(encoded, validate=True)
                
                if len(frame_bytes) == 0:
                    await websocket.send_text("Error: Decoded frame is empty")
                    continue
                
                # Convert bytes to numpy array
                nparr = np.frombuffer(frame_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame is None:
                    print(f"Warning: cv2.imdecode returned None. Frame data length: {len(frame_bytes)}")
                    print(f"First 20 bytes: {frame_bytes[:20]}")
                    await websocket.send_text("Error: Could not decode image - invalid image data")
                    continue
                
            except binascii.Error as e:
                await websocket.send_text(f"Error: Invalid base64 data: {str(e)}")
                print(f"Base64 decode error: {e}")
                continue
            except Exception as e:
                await websocket.send_text(f"Error decoding frame: {str(e)}")
                print(f"Frame decode error: {e}")
                import traceback
                traceback.print_exc()
                continue
            
            # 3. AI CAPTIONING (using run_in_executor for CPU-intensive work)
            try:
                # Save frame to temporary file (Qwen2VL expects file paths)
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
                    tmp_path = Path(tmp_file.name)
                    cv2.imwrite(str(tmp_path), frame)
                    
                    # Ensure prompt is up to date
                    captioner.prompt = current_prompt
                    
                    # Run captioning in thread pool to avoid blocking
                    loop = asyncio.get_event_loop()
                    captions = await loop.run_in_executor(
                        None,
                        captioner.caption,
                        [str(tmp_path)]
                    )
                    
                    caption = captions[0] if captions else "Failed to generate caption"
                    
                    # Clean up temp file
                    tmp_path.unlink()
                
            except Exception as e:
                caption = f"Error generating caption: {str(e)}"
                print(f"Captioning error: {e}")
            
            # 4. SEND CAPTION BACK
            await websocket.send_text(caption)
            
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except:
            pass


def find_port(start=8000):
    """Find available port."""
    for port in range(start, start + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('', port))
                return port
            except OSError:
                continue
    return start  # Fallback to start port if all are busy


if __name__ == "__main__":
    import uvicorn
    port = find_port(8000)
    if port != 8000:
        print(f"Port 8000 busy, using port {port}")
    else:
        print(f"Using port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

