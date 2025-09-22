from code import interact
import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
from google.adk.tools import AgentTool, ToolContext

from multi_tool_agent.models import Option


INTERIOR_DESIGNER_DISCOVERY_PROMPT = """
You are an Interior Designer Agent that helps users visualize how products would look inside their rooms.  
You have one function tool available:  
  - `set_option`: accepts an Option object. Use this tool to propose room-placement options to the user.
  - JSON Schema: `{ "name": "set_option", "arguments": { "option": { "option_id": "<string>", "title": "<string>", "agent_id": "stylist", "asset_id": <integer> } } }`

Your task flow:
   - Carefully review the product description and the list of user photos (with their textual descriptions).  
   - Identify which photos are suitable for interior visualization (for example, those described as “room”, “living room”, “bedroom”, “kitchen”, etc).  
   - For each viable photo, immediately call the `set_option` tool with an Option object such as `Option(option_id="interior_1", title="Place in living room (photo #2)", agent_id="interior_designer", asset_id=2)`.
   - MUST Specify asset_id of the user photo to be used for the try-on.
   - If no room-like photo is provided, return nothing (no option).  
   - Do not generate images at this stage.  
"""


async def set_option(tool_context: ToolContext, option: Option) -> Option:
    print("set_option called")
    print(f"interior_designer_option is {option}")
    tool_context.state["interior_designer_option"] = option
    return option

interior_designer_discovery_agent = Agent(
    name="interior_designer_discovery_agent",
    model="gemini-2.0-flash",
    description=(
        "Agent to put furniture in user's room photos."
    ),
    instruction=INTERIOR_DESIGNER_DISCOVERY_PROMPT,
    tools=[
        set_option,
    ],
)