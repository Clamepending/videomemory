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




# --- using GPT 4o model
try:
    weather_agent_gpt_4o = Agent(
        name = "weather_agent_v1",
        model=MODEL_GPT_4O,
        description="An agent that provides weather information for specified cities.",
        instruction="""You are a helpful assistant that provides weather information for specified cities.
    When the user asks for weather information, you should use the 'get_weather' tool to get the weather information.
    If the tool returns an error, inform the user politely.
    If the tool is successful, present the report clearly and concisely.""",
        tools=[get_weather],
    )
    
    session_service_gpt_4o = InMemorySessionService()
    APP_NAME_GPT_4O = "weather_app_gpt_4o"
    USER_ID_GPT_4O = "user_123_gpt_4o"
    SESSION_ID_GPT_4O = "session_123_gpt_4o"

    async def init_session_gpt_4o():
        session = await session_service_gpt_4o.create_session(app_name=APP_NAME_GPT_4O, user_id=USER_ID_GPT_4O, session_id=SESSION_ID_GPT_4O)
        return session
    
    session_gpt_4o = asyncio.run(init_session_gpt_4o())
    print(f"session {session_gpt_4o.id} created successfully")
    
    runner_gpt_4o = Runner(
        agent=weather_agent_gpt_4o,
        session_service=session_service_gpt_4o,
        app_name=APP_NAME_GPT_4O,
    )
    
    print(f"runner {runner_gpt_4o.agent.name} created successfully")

except Exception as e:
    print(f"Error creating weather agent GPT 4o: {e}")
    

# # --- using gemini 2.0 flash model
# weather_agent = Agent(
#     name = "weather_agent_v1",
#     model=MODEL_GEMINI_2_0_FLASH,
#     description="An agent that provides weather information for specified cities.",
#     instruction="""You are a helpful assistant that provides weather information for specified cities.
# When the user asks for weather information, you should use the 'get_weather' tool to get the weather information.
# If the tool returns an error, inform the user politely.
# If the tool is successful, present the report clearly and concisely.""",
#     tools=[get_weather],
# )

# print(f"weather agent {weather_agent.name} created successfully")


# session_service = InMemorySessionService()

# APP_NAME = "weather_app"
# USER_ID = "user_123"
# SESSION_ID = "session_123"

# async def init_session(APP_NAME: str, USER_ID: str, SESSION_ID: str) -> InMemorySessionService:
#     session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
#     return session

# session = asyncio.run(init_session(APP_NAME, USER_ID, SESSION_ID))
# print(f"session {session.id} created successfully")

# runner = Runner(
#     agent=weather_agent,
#     session_service=session_service,
#     app_name=APP_NAME,
# )

# print(f"runner created successfully")

from google.genai import types

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
    print("asking for the weather in New York")
    await call_agent_async(query="What is the weather in New York?", runner=runner_gpt_4o, user_id=USER_ID_GPT_4O, session_id=SESSION_ID_GPT_4O)
    
    print("asking for the weather in Paris")
    await call_agent_async(query="How about Paris?",
                                       runner=runner_gpt_4o,
                                       user_id=USER_ID_GPT_4O,
                                       session_id=SESSION_ID_GPT_4O) # Expecting the tool's error message
    
    print("asking for the weather in London")
    await call_agent_async(query="What is the weather like in London?",
                                       runner=runner_gpt_4o,
                                       user_id=USER_ID_GPT_4O,
                                       session_id=SESSION_ID_GPT_4O)
    
if __name__ == "__main__":
    try:
        asyncio.run(run_conversation())
    except Exception as e:
        print(f"An error occurred: {e}")
    