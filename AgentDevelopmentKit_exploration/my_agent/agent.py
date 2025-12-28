from google.adk.agents.llm_agent import Agent
import datetime

def get_current_time(city: str):
    return {"status": "success", "city": city, "time": "10:00 AM"}



root_agent = Agent(
    model='gemini-2.5-flash',
    name='root_agent',
    description='A helpful assistant for user questions.',
    instruction='Answer user questions to the best of your knowledge',
    tools=[get_current_time],
)


