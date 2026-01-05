"""Action router agent that intelligently routes action descriptions to appropriate tools."""

from google.adk.agents import Agent
from tools import actions


action_router_agent = Agent(
    name="action_router",
    model="gemini-2.5-flash",
    description="An intelligent agent that routes action descriptions to the appropriate action tools.",
    instruction="""You are an intelligent action router agent. Your job is to understand action descriptions 
    and route them to the appropriate tool.

    Available tools:
    - send_email: For sending emails. Requires 'to' (email address), optional 'subject', and 'content' (body text).
    - open_door: For opening doors. Requires 'door_name' (e.g., 'front door', 'garage door').
    - close_door: For closing doors. Requires 'door_name'.
    - turn_on_light: For turning on lights. Requires 'light_name'.
    - turn_off_light: For turning off lights. Requires 'light_name'.

    When you receive an action description:
    1. Parse the description to understand the intent
    2. Extract the necessary parameters (email address, door name, etc.)
    3. Call the appropriate tool with the extracted parameters
    4. Return a clear confirmation of what action was taken

    Examples:
    - "send email to example@gmail.com with content hello!" -> call send_email(to="example@gmail.com", content="hello!")
    - "open front door" -> call open_door(door_name="front door")
    - "turn on the living room light" -> call turn_on_light(light_name="living room")
    
    Be smart about extracting parameters from natural language descriptions.""",
    tools=[
        actions.send_email,
        actions.open_door,
        actions.close_door,
        actions.turn_on_light,
        actions.turn_off_light,
        actions.print_to_user
    ],
)

