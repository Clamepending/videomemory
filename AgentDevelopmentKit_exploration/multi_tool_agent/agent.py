from google.adk.agents import Agent
import datetime
from zoneinfo import ZoneInfo

def get_weather(city: str) -> dict:
    if city.lower() == "new york":
        weather = "sunny"
    else:
        return {
            "status": "error",
            "error_message": (
                f"Sorry, I don't have weather information for {city}."
            ),
        }
    return {"status": "success", "weather": weather}

def get_time(city: str) -> dict:
    if city.lower() == "new york":
        tz_identifier = "America/New_York"
    else:
        return {
            "status": "error",
            "error_message": (
                f"Sorry, I don't have timezone information for {city}."
            ),
        }

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    report = f'The current time in {city} is {now.strftime("%Y-%m-%d %H:%M:%S %Z%z")}'
    
    return {"status": "success", "report": report}

root_agent = Agent(
    name = "weather_time_agent",
    model = "gemini-2.5-flash",
    description = "An agent to answer questions about the weather and time in a city.",
    instruction="You are a helpful assistant hwo can answer questions about the time and weather in a city.",
    tools = [get_weather, get_time],
)