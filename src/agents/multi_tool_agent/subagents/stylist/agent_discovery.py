import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
from google.adk.tools import AgentTool, ToolContext

from multi_tool_agent.models import Option


STYLIST_DISCOVERY_PROMPT = """
You are a Stylist Agent that helps users try on products virtually.  
You have one function tools available:  
  - `set_option`: accepts an Option object. Use this tool to propose try-on options to the user.
  - JSON Schema: `{ "name": "set_option", "arguments": { "option": { "option_id": "<string>", "title": "<string>", "agent_id": "stylist", "asset_id": <integer> } } }`

Your task flow:
   - Carefully review the product description and the list of user photos (with their textual descriptions).  
   - Decide which try-on options are relevant. For example:  
     - “Try on (photo #1)” if a full-body image is available.  
     - “Try on (model)” as a fallback if no suitable user photo is found.  
   - For each viable photo, immediately call the `set_option` tool with an Option object such as `Option(option_id="stylist_1", title="Try on (photo #2)", agent_id="stylist", asset_id=2)`.
   - Specify the product image to be used for the try-on.
   - MUST Specify asset_id of the user photo to be used for the try-on.
   - Do not generate images at this stage.  
"""

async def set_option(tool_context: ToolContext, option: Option) -> Option:
    tool_context.state["stylist_option"] = option
    return option

stylist_discovery_agent = Agent(
    name="stylist_discovery_agent",
    model="gemini-2.0-flash",
    description=(
        "Agent to make try-ons of product and user's photos."
    ),
    instruction=STYLIST_DISCOVERY_PROMPT,
    tools=[
        set_option,
    ],
)