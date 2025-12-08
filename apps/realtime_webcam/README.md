# Real-time Webcam Captioner

A FastAPI-based web application that captures frames from your webcam every 2 seconds and generates AI captions using Qwen2VL.

## Features

- 🎥 **Real-time webcam access** via HTML5 Media API
- ⚡ **WebSocket communication** for efficient frame transmission
- 🤖 **AI-powered captioning** using Qwen2VL model
- 🎨 **Modern, responsive UI** with live status updates
- ⏱️ **Automatic frame capture** every 2 seconds

## Tech Stack

- **Backend**: FastAPI with WebSocket support
- **Frontend**: HTML5 + JavaScript (no frameworks required)
- **AI Model**: Qwen2VL-7B-Instruct
- **Image Processing**: OpenCV

## Installation

Make sure you have the required dependencies installed:

```bash
pip install fastapi uvicorn opencv-python numpy
```

The Qwen2VL captioner and its dependencies should already be installed in your environment.

## Running the Application

1. Navigate to the app directory:
```bash
cd apps/realtime_webcam
```

2. Start the FastAPI server:
```bash
python main.py
```

Or using uvicorn directly:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

3. Open your browser and navigate to:
```
http://localhost:8000
```

4. Click "Start Captioning" to begin:
   - Grant webcam permissions when prompted
   - The app will automatically capture frames every 2 seconds
   - Captions will appear in real-time

## How It Works

1. **Frontend (Browser)**:
   - Uses `getUserMedia()` API to access the webcam
   - Displays video feed in a `<video>` element
   - Captures frames every 2 seconds using Canvas API
   - Converts frames to base64 JPEG
   - Sends frames to backend via WebSocket

2. **Backend (FastAPI)**:
   - Receives frames via WebSocket endpoint (`/ws/captioning`)
   - Decodes base64 image data
   - Saves frame to temporary file
   - Processes frame through Qwen2VL captioner
   - Returns caption via WebSocket
   - Cleans up temporary files

3. **Display**:
   - Frontend receives caption and updates the UI
   - Status indicators show connection and processing state

## Architecture Benefits

- **Asynchronous Processing**: FastAPI's async/await prevents blocking during LLM inference
- **Real-time Communication**: WebSockets provide low-latency bidirectional communication
- **Efficient Frame Transfer**: Base64 encoding allows direct image transmission
- **Non-blocking**: Multiple clients can be served concurrently

## Troubleshooting

- **Webcam not working**: Check browser permissions and ensure no other app is using the webcam
- **Connection errors**: Verify the server is running and accessible
- **Slow captioning**: The model may take a few seconds per frame depending on your hardware
- **Port already in use**: Change the port in `main.py` or use `--port` flag with uvicorn

## Notes

- The model loads at startup, which may take a minute or two
- Frame capture interval is set to 2 seconds (configurable in the JavaScript)
- Captions are generated for individual frames, not video sequences
- The app works best with modern browsers that support WebSocket and getUserMedia APIs

