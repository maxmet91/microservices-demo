from re import sub
from typing import List
from google.adk.agents import Agent
from google.adk.flows.llm_flows import instructions
from google.adk.tools import AgentTool, FunctionTool, ToolContext
from google.genai import types


from multi_tool_agent.models import Option
from multi_tool_agent.subagents.stylist.agent_executor import stylist_executor_agent
from multi_tool_agent.subagents.interior_designer.agent_executor import interior_designer_executor_agent
from .subagents.stylist.agent_discovery import stylist_discovery_agent
from .subagents.interior_designer.agent_discovery import interior_designer_discovery_agent


GATEWAY_PROMPT = """
You are a Gateway Agent.  
You receive requests from the client and must decide whether the request is in the **discovery phase** or in the **execution phase**.  
You can communicate only with your sub-agents, by invoking them directly.

Task flow:

1. **Discovery phase** (the client provides product details and user assets, but has not yet chosen an option):  
   - Forward the product and asset information to Discovery sub-agents tools.  
   - Ask them explicitly to perform their discovery step and return a list of available options.  
   - Do not generate options yourself. Simply collect and merge options from the sub-agents and return them to the client.
   - Invoke `set_options` after gathering options from all invoked sub-agents.
   - If no options are found than options list should be empty.

2. **Execution phase** (the client provides a selected option to execute):  
   - Forward the selected option metadata to the choosen Executor Agent.  
   - Ask it explicitly to perform its execution step for that option.  

3. **General rules:**  
   - Always determine which phase the client request belongs to: discovery or execution.  
   - Never invent results or mix phases. Only pass through and route correctly.  
   - Your output must always be based on the sub-agent’s response.
   - Pass all user-provided data to the sub-agents without removing any fields.
   - Do not edit outputs from sub-agents, except for merging options lists during discovery.

OUTPUT FORMAT:  
- For discovery: a JSON object containing the list of options from the sub-agent.
"""

async def set_options(tool_context: ToolContext, options: List[Option]) -> dict:
    print("set_options called: {options}")
    tool_context.state["options"] = options
    return {"status": "ok", "options": options}

root_agent = Agent(
    name="gateway_agent",
    model="gemini-2.5-flash",
    description=(
        "Agent to communicate with client and rout requests to sub-agents."
    ),
    instruction=GATEWAY_PROMPT,
    tools=[
        AgentTool(agent=stylist_discovery_agent),
        AgentTool(agent=interior_designer_discovery_agent),
        set_options
    ],
    sub_agents=[stylist_executor_agent, interior_designer_executor_agent],
)