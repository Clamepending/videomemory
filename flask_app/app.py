#!/usr/bin/env python3
"""Simple Flask app for chat interface with admin agent."""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path so we can import videomemory
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
import videomemory.agents
import videomemory.system
import videomemory.tools
from videomemory.system.logging_config import setup_logging
from videomemory.system.model_providers import get_VLM_provider

# Load environment variables
load_dotenv()

# Initialize logging
setup_logging()

app = Flask(__name__)

# Initialize system components (similar to main.py)
io_manager = videomemory.system.IOmanager()
app_name = "videomemory_app"
session_service = InMemorySessionService()
runner = Runner(
    agent=videomemory.agents.admin_agent,
    app_name=app_name,
    session_service=session_service
)
model_provider = get_VLM_provider()
task_manager = videomemory.system.TaskManager(
    io_manager=io_manager,
    action_runner=runner,
    session_service=session_service,
    app_name=app_name,
    model_provider=model_provider
)

# Set managers in tools
videomemory.tools.tasks.set_managers(io_manager, task_manager)

# Create admin session
USER_ID = "user_1"
SESSION_ID = "admin_session"

# Initialize session at startup
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(session_service.create_session(
    app_name=app_name,
    user_id=USER_ID,
    session_id=SESSION_ID
))
loop.close()

@app.route('/')
def index():
    """Render the chat interface."""
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages."""
    data = request.json
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({'error': 'Message cannot be empty'}), 400
    
    try:
        # Run the agent and get response
        content = types.Content(role='user', parts=[types.Part(text=user_message)])
        
        # Use asyncio to run the async agent
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        final_response_text = "No response received"
        async def get_response():
            nonlocal final_response_text
            # Use async generator properly with try/finally to ensure cleanup
            gen = runner.run_async(
                user_id=USER_ID,
                session_id=SESSION_ID,
                new_message=content
            )
            try:
                async for event in gen:
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            final_response_text = event.content.parts[0].text
                        break
            finally:
                # Properly close the async generator to avoid resource leaks
                await gen.aclose()

        
        loop.run_until_complete(get_response())
        loop.close()
        
        return jsonify({'response': final_response_text})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
