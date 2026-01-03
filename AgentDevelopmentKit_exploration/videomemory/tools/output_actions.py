"""Tool for taking output actions using the action router agent."""

from google.adk.tools.agent_tool import AgentTool
from agents.action_router_agent import action_router_agent


# Create the tool that wraps the action router agent
take_output_action = AgentTool(action_router_agent)

