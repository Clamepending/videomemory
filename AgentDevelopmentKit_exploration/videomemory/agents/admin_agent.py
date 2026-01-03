"""System administrator agent."""

from google.adk.agents import Agent
import tools


admin_agent = Agent(
    name="system_administrator",
    model="gemini-2.0-flash",
    description="A helpful system administrator. It controls the system on behalf of the user.",
    instruction="You are a helpful and friendly system administrator. Be concise and clear in your responses. "
               "You have access to tools that can help you check available input devices on the system "
               "and manage tasks. Use list_input_devices_with_ids to get io_ids, "
               "use add_task with the io_id to create tasks, "
               "use list_tasks to view all tasks (optionally filtered by io_id), "
               "and use remove_task to delete a task by its task_id. "
               "You can also use take_output_action to execute various actions like sending emails, "
               "opening/closing doors, or controlling lights by providing a natural language description of the action.",
    tools=[tools.list_input_devices_with_ids, tools.add_task, tools.list_tasks, tools.remove_task, tools.take_output_action],
)

