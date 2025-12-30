#!/usr/bin/env python3
"""Simple conversational AI agent using Gemini 2.0 Flash with Google ADK."""

import os
import asyncio
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
import tools

# Load environment variables from .env file
load_dotenv()

async def main():
    # Create the agent
    agent = Agent(
        name="system_administrator",
        model="gemini-2.0-flash",
        description="A helpful system administrator. It controls the system on behalf of the user.",
        instruction="You are a helpful and friendly system administrator. Be concise and clear in your responses. "
                   "You have access to tools that can help you check available input streams on the system.",
        tools=[tools.get_available_input_streams],
    )
    
    # Set up session service
    session_service = InMemorySessionService()
    
    # Create session
    APP_NAME = "conversation_app"
    USER_ID = "user_1"
    SESSION_ID = "session_001"
    
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID
    )
    
    # Create runner
    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=session_service
    )
    
    print("AI Agent initialized. Type 'quit' or 'exit' to end the conversation.\n")
    
    # Conversation loop
    while True:
        user_input = input("You: ").strip()
        
        if user_input.lower() in ['quit', 'exit']:
            print("Goodbye!")
            break
        
        if not user_input:
            continue
        
        try:
            # Create message content
            content = types.Content(role='user', parts=[types.Part(text=user_input)])
            
            # Run the agent and get response
            final_response_text = "No response received"
            async for event in runner.run_async(
                user_id=USER_ID,
                session_id=SESSION_ID,
                new_message=content
            ):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        final_response_text = event.content.parts[0].text
                    break
            
            print(f"Agent: {final_response_text}\n")
        except Exception as e:
            print(f"Error: {e}\n")

if __name__ == "__main__":
    asyncio.run(main())

