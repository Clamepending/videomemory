"""Action router agent that intelligently routes action descriptions to appropriate tools."""

from google.adk.agents import Agent
from ..tools import actions


action_router_agent = Agent(
    name="action_router",
    model="gemini-2.5-flash",
    description="An intelligent agent that routes action descriptions to the appropriate action tools.",
    instruction="""You are an intelligent action router agent. Your job is to understand action descriptions 
    and route them to the appropriate tool.

    Available tools:
    - send_email: For sending emails. Requires 'to' (email address), optional 'subject', and 'content' (body text).
    - send_discord_notification: For sending notifications to Discord. Requires 'message' (the notification text), optional 'username' (to override bot name).
    - send_telegram_notification: For sending notifications to Telegram. Requires 'message' (the notification text).
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
    - "send discord notification: motion detected in the living room!" -> call send_discord_notification(message="motion detected in the living room!")
    - "send telegram notification: someone is at the door" -> call send_telegram_notification(message="someone is at the door")
    - "open front door" -> call open_door(door_name="front door")
    - "turn on the living room light" -> call turn_on_light(light_name="living room")
    
    If the user asks to "send a notification" or "send a message" without specifying which service, 
    prefer Telegram if configured, then Discord, then fall back to print_to_user.
    
    Be smart about extracting parameters from natural language descriptions.""",
    tools=[
        actions.send_email,
        actions.send_discord_notification,
        actions.send_telegram_notification,
        actions.open_door,
        actions.close_door,
        actions.turn_on_light,
        actions.turn_off_light,
        actions.print_to_user
    ],
)

