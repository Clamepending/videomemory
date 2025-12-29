# @title Import necessary libraries
import os
import asyncio
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm # For multi-model support
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types # For creating message Content/Parts

from dotenv import load_dotenv
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_GEMINI_2_0_FLASH = os.getenv("MODEL_GEMINI_2_0_FLASH")
MODEL_GPT_4O = os.getenv("MODEL_GPT_4O")
MODEL_CLAUDE_SONNET = os.getenv("MODEL_CLAUDE_SONNET")

import warnings
# Ignore all warnings
warnings.filterwarnings("ignore")

import logging
logging.basicConfig(level=logging.ERROR)

print("Libraries imported.")

# @title Define the get_weather Tool
def get_weather(city: str) -> dict:
    """Retrieves the current weather report for a specified city.

    Args:
        city (str): The name of the city (e.g., "New York", "London", "Tokyo").

    Returns:
        dict: A dictionary containing the weather information.
              Includes a 'status' key ('success' or 'error').
              If 'success', includes a 'report' key with weather details.
              If 'error', includes an 'error_message' key.
    """
    print(f"--- Tool: get_weather called for city: {city} ---") # Log tool execution
    city_normalized = city.lower().replace(" ", "") # Basic normalization

    # Mock weather data
    mock_weather_db = {
        "newyork": {"status": "success", "report": "The weather in New York is sunny with a temperature of 25°C."},
        "london": {"status": "success", "report": "It's cloudy in London with a temperature of 15°C."},
        "tokyo": {"status": "success", "report": "Tokyo is experiencing light rain and a temperature of 18°C."},
    }

    if city_normalized in mock_weather_db:
        return mock_weather_db[city_normalized]
    else:
        return {"status": "error", "error_message": f"Sorry, I don't have weather information for '{city}'."}




# @title Define and Test GPT Agent
# --- Agent using GPT-4o ---
weather_agent_gpt = None
runner_gpt = None

try:
    weather_agent_gpt = Agent(
        name="weather_agent_gpt",
        # Key change: Wrap the LiteLLM model identifier
        model=LiteLlm(model=MODEL_GPT_4O),
        description="Provides weather information (using GPT-4o).",
        instruction="You are a helpful weather assistant powered by GPT-4o. "
                    "Use the 'get_weather' tool for city weather requests. "
                    "Clearly present successful reports or polite error messages based on the tool's output status.",
        tools=[get_weather],
    )
    print(f"Agent '{weather_agent_gpt.name}' created using model '{MODEL_GPT_4O}'.")

    # InMemorySessionService is simple, non-persistent storage for this tutorial.
    session_service_gpt = InMemorySessionService()

    # Define constants for identifying the interaction context
    APP_NAME_GPT = "weather_tutorial_app_gpt"
    USER_ID_GPT = "user_1_gpt"
    SESSION_ID_GPT = "session_001_gpt"

    # Create the specific session where the conversation will happen
    async def init_session_gpt():
        return await session_service_gpt.create_session(
            app_name=APP_NAME_GPT,
            user_id=USER_ID_GPT,
            session_id=SESSION_ID_GPT
        )
    
    session_gpt = asyncio.run(init_session_gpt())
    print(f"Session created: App='{APP_NAME_GPT}', User='{USER_ID_GPT}', Session='{SESSION_ID_GPT}'")

    # Create a runner specific to this agent and its session service
    runner_gpt = Runner(
        agent=weather_agent_gpt,
        app_name=APP_NAME_GPT,
        session_service=session_service_gpt
    )
    print(f"Runner created for agent '{runner_gpt.agent.name}'.")

except Exception as e:
    print(f"❌ Could not create GPT agent '{MODEL_GPT_4O}'. Check API Key and model name. Error: {e}")

# @title Define and Test Gemini Agent
# --- Agent using Gemini 2.0 Flash ---
weather_agent_gemini = None
runner_gemini = None

try:
    weather_agent_gemini = Agent(
        name="weather_agent_gemini",
        # Key change: Wrap the LiteLLM model identifier
        model=MODEL_GEMINI_2_0_FLASH,
        description="Provides weather information (using Gemini 2.0 Flash).",
        instruction="You are a helpful weather assistant powered by Gemini 2.0 Flash. "
                    "Use the 'get_weather' tool for city weather requests. "
                    "Clearly present successful reports or polite error messages based on the tool's output status.",
        tools=[get_weather],
    )
    print(f"Agent '{weather_agent_gemini.name}' created using model '{MODEL_GEMINI_2_0_FLASH}'.")

    # InMemorySessionService is simple, non-persistent storage for this tutorial.
    session_service_gemini = InMemorySessionService()

    # Define constants for identifying the interaction context
    APP_NAME_GEMINI = "weather_tutorial_app_gemini"
    USER_ID_GEMINI = "user_1_gemini"
    SESSION_ID_GEMINI = "session_001_gemini"

    # Create the specific session where the conversation will happen
    async def init_session_gemini():
        return await session_service_gemini.create_session(
            app_name=APP_NAME_GEMINI,
            user_id=USER_ID_GEMINI,
            session_id=SESSION_ID_GEMINI
        )
    
    session_gemini = asyncio.run(init_session_gemini())
    print(f"Session created: App='{APP_NAME_GEMINI}', User='{USER_ID_GEMINI}', Session='{SESSION_ID_GEMINI}'")

    # Create a runner specific to this agent and its session service
    runner_gemini = Runner(
        agent=weather_agent_gemini,
        app_name=APP_NAME_GEMINI,
        session_service=session_service_gemini
    )
    print(f"Runner created for agent '{runner_gemini.agent.name}'.")

except Exception as e:
    print(f"❌ Could not create Gemini agent '{MODEL_GEMINI_2_0_FLASH}'. Check API Key and model name. Error: {e}")

# @title Define and Test Claude Agent
# --- Agent using Claude Sonnet ---
weather_agent_claude = None
runner_claude = None

try:
    weather_agent_claude = Agent(
        name="weather_agent_claude",
        # Key change: Wrap the LiteLLM model identifier
        model=LiteLlm(model=MODEL_CLAUDE_SONNET),
        description="Provides weather information (using Claude Sonnet).",
        instruction="You are a helpful weather assistant powered by Claude Sonnet. "
                    "Use the 'get_weather' tool for city weather requests. "
                    "Analyze the tool's dictionary output ('status', 'report'/'error_message'). "
                    "Clearly present successful reports or polite error messages.",
        tools=[get_weather],
    )
    print(f"Agent '{weather_agent_claude.name}' created using model '{MODEL_CLAUDE_SONNET}'.")

    # InMemorySessionService is simple, non-persistent storage for this tutorial.
    session_service_claude = InMemorySessionService()

    # Define constants for identifying the interaction context
    APP_NAME_CLAUDE = "weather_tutorial_app_claude"
    USER_ID_CLAUDE = "user_1_claude"
    SESSION_ID_CLAUDE = "session_001_claude"

    # Create the specific session where the conversation will happen
    async def init_session_claude():
        return await session_service_claude.create_session(
            app_name=APP_NAME_CLAUDE,
            user_id=USER_ID_CLAUDE,
            session_id=SESSION_ID_CLAUDE
        )
    
    session_claude = asyncio.run(init_session_claude())
    print(f"Session created: App='{APP_NAME_CLAUDE}', User='{USER_ID_CLAUDE}', Session='{SESSION_ID_CLAUDE}'")

    # Create a runner specific to this agent and its session service
    runner_claude = Runner(
        agent=weather_agent_claude,
        app_name=APP_NAME_CLAUDE,
        session_service=session_service_claude
    )
    print(f"Runner created for agent '{runner_claude.agent.name}'.")

except Exception as e:
    print(f"❌ Could not create Claude agent '{MODEL_CLAUDE_SONNET}'. Check API Key and model name. Error: {e}")

async def call_agent_async(query: str, runner: Runner, user_id: str, session_id: str):
    
    
    content = types.Content(role='user', parts=[types.Part(text=query)])
    
    final_response_text = "Agent did not produce a final response" # Default
    
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        
        
        if event.is_final_response():
            if event.content and event.content.parts:
                final_response_text = event.content.parts[0].text
            elif event.actions and event.actions.escalate:
                final_response_text = f"Agent escalated: {event.error_message or 'no specific message'}"
            break

    print(f"<<< Agent Response: {final_response_text}")



async def run_conversation():
    # --- Test OpenAI GPT Agent ---
    if runner_gpt:
        print("\n" + "="*60)
        print("--- Testing OpenAI GPT Agent ---")
        print("="*60)
        await call_agent_async(
            query="What's the weather in Tokyo?",
            runner=runner_gpt,
            user_id=USER_ID_GPT,
            session_id=SESSION_ID_GPT
        )
    else:
        print("\n⚠️ Skipping GPT agent test (agent not initialized)")

    # --- Test Gemini Agent ---
    if runner_gemini:
        print("\n" + "="*60)
        print("--- Testing Gemini Agent ---")
        print("="*60)
        await call_agent_async(
            query="What's the weather in Tokyo?",
            runner=runner_gemini,
            user_id=USER_ID_GEMINI,
            session_id=SESSION_ID_GEMINI
        )
    else:
        print("\n⚠️ Skipping Gemini agent test (agent not initialized)")

    # --- Test Claude Agent ---
    if runner_claude:
        print("\n" + "="*60)
        print("--- Testing Claude Agent ---")
        print("="*60)
        await call_agent_async(
            query="What's the weather in Tokyo?",
            runner=runner_claude,
            user_id=USER_ID_CLAUDE,
            session_id=SESSION_ID_CLAUDE
        )
    else:
        print("\n⚠️ Skipping Claude agent test (agent not initialized)")

if __name__ == "__main__":
    try:
        asyncio.run(run_conversation())
    except Exception as e:
        print(f"An error occurred: {e}")
    