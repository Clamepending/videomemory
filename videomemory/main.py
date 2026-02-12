#!/usr/bin/env python3
"""Simple conversational AI agent using Gemini 2.0 Flash with Google ADK."""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from google.adk.sessions import DatabaseSessionService
from google.adk.runners import Runner
from google.genai import types
import httpx
import agents
import system
from system.database import TaskDatabase, get_default_data_dir
from system.logging_config import setup_logging
from system.model_providers import get_VLM_provider

# Load environment variables from .env file
load_dotenv()

# Check for required API key
if not os.getenv("GOOGLE_API_KEY"):
    print("WARNING: GOOGLE_API_KEY not found in environment variables.")
    print("Please create a .env file in this directory with:")
    print("  GOOGLE_API_KEY=your_api_key_here")
    print("The application may fail to connect to the AI service.\n")

# Initialize logging
setup_logging()

async def main():
    # Initialize database paths
    data_dir = get_default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    
    sessions_db_url = f"sqlite+aiosqlite:///{data_dir / 'sessions.db'}"
    task_db = TaskDatabase(str(data_dir / 'videomemory.db'))
    
    # Initialize system managers
    io_manager = system.IOmanager()
    
    # Set up shared session service and runner for all agents
    app_name = "videomemory_app"
    session_service = DatabaseSessionService(db_url=sessions_db_url)
    runner = Runner(
        agent=agents.admin_agent,
        app_name=app_name,
        session_service=session_service
    )
    
    # Initialize model provider from environment variable
    model_provider = get_VLM_provider()
    
    # Pass shared runner and session service to task manager (for video ingestor actions)
    task_manager = system.TaskManager(
        io_manager=io_manager, 
        action_runner=runner,
        session_service=session_service,
        app_name=app_name,
        model_provider=model_provider,
        db=task_db
    )
    
    # Set managers in tools so they can access them
    import tools
    tools.tasks.set_managers(io_manager, task_manager)
    
    # Create or resume admin conversation session
    USER_ID = "user_1"
    SESSION_ID = "admin_session"
    existing = await session_service.get_session(
        app_name=app_name,
        user_id=USER_ID,
        session_id=SESSION_ID
    )
    if existing is None:
        await session_service.create_session(
            app_name=app_name,
            user_id=USER_ID,
            session_id=SESSION_ID
        )
    
    print("AI Agent initialized. Type 'quit' or 'exit' to end the conversation.\n")
    
    # Conversation loop
    while True:
        # Use asyncio.to_thread to run blocking input() in a thread pool
        # This allows the event loop to continue processing other tasks
        user_input = await asyncio.to_thread(input, "You: ")
        user_input = user_input.strip()
        
        if user_input.lower() in ['quit', 'exit']:
            print("Goodbye!")
            break
        
        if not user_input:
            continue
        
        try:
            # Create message content
            import logging
            logger = logging.getLogger('main')
            logger.debug(f"[DEBUG] main: Processing user input: {user_input}")
            
            content = types.Content(role='user', parts=[types.Part(text=user_input)])
            
            # Run the agent and get response
            logger.debug(f"[DEBUG] main: About to call runner.run_async")
            final_response_text = "No response received"
            try:
                async for event in runner.run_async(
                    user_id=USER_ID,
                    session_id=SESSION_ID,
                    new_message=content
                ):
                    logger.debug(f"[DEBUG] main: Received event, is_final_response={event.is_final_response()}")
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            final_response_text = event.content.parts[0].text
                        break
                logger.debug(f"[DEBUG] main: Finished processing events, final_response_text={final_response_text}")
            except Exception as inner_e:
                logger.error(f"[ERROR] main: Exception during runner.run_async: {type(inner_e).__name__}: {inner_e}", exc_info=True)
                raise
            
            print(f"Agent: {final_response_text}\n")
        except (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            # Network-related errors - provide user-friendly message
            import logging
            logger = logging.getLogger('main')
            error_type = type(e).__name__
            error_msg = str(e) if str(e) else "No additional details"
            logger.error(f"[ERROR] main: Network error caught: {error_type}: {error_msg}", exc_info=True)
            print(f"Network Error: Connection issue with the AI service ({error_type}). Please try again in a moment.\n")
            print(f"Error details: {error_msg}\n")
        except Exception as e:
            # Other errors - show more details
            import traceback
            error_msg = str(e) if str(e) else type(e).__name__
            print(f"Error: {error_msg}\n")
            # Print full traceback for debugging
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
