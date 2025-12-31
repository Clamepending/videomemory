"""System administrator agent."""

from google.adk.agents import Agent
import tools


admin_agent = Agent(
    name="system_administrator",
    model="gemini-2.0-flash",
    description="A helpful system administrator. It controls the system on behalf of the user.",
    instruction="You are a helpful and friendly system administrator. Be concise and clear in your responses. "
               "You have access to tools that can help you check available input devices on the system "
               "and add tasks for specific input devices. Use list_input_devices_with_ids to get io_ids, "
               "then use add_task with the io_id to create tasks.",
    tools=[tools.list_input_devices_with_ids, tools.add_task],
)

