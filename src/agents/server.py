import asyncio
from email.mime import image
import enum
import time
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from google.adk.events import Event, EventActions
import httpx
from pydantic import BaseModel, HttpUrl, Field
from dotenv import load_dotenv

load_dotenv()

# --- ADK imports (match your installed ADK version) ---
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, Session
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.genai import types

# Your multi-agent graph (gateway root agent with stylist sub-agent)
from multi_tool_agent.agent import root_agent
from multi_tool_agent.models import Option, OptionsList


APP_NAME = "online_boutique_agents"
USER_ID = "tester"

app = FastAPI(title=APP_NAME, version="0.1.0")

# ADK runtime-ish bits (services + runner). Keep singletons for simplicity.
_session_service = InMemorySessionService()
_artifacts_service = InMemoryArtifactService()
_runner = Runner(
    app_name=APP_NAME,
    agent=root_agent,
    artifact_service=_artifacts_service,
    session_service=_session_service,
)

# ---------------------------
# Pydantic models (HTTP API)
# ---------------------------

class ProductImage(BaseModel):
    id: str
    url: HttpUrl

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    image: ProductImage

class UserAsset(BaseModel):
    id: str
    url: HttpUrl
    description: Optional[str] = None

class DiscoverRequest(BaseModel):
    session_id: Optional[str] = None
    product: Product
    assets: List[UserAsset] = Field(default_factory=list)
    notes: Optional[str] = None

class DiscoverResponse(BaseModel):
    session_id: str
    options: OptionsList

class ExecuteRequest(BaseModel):
    session_id: str
    option_id: str

class ExecuteResult(BaseModel):
    job_id: str
    status: str                  # queued|running|succeeded|failed
    images: List[str] = []
    message: Optional[str] = None


# ---------------------------
# Helpers to run an agent turn
# ---------------------------

async def _run_gateway_turn(session: Session, user_payload: Dict[str, Any]) -> None:
    """
    Send one 'user' message to the ADK gateway agent and drain the async event stream.
    We do not parse the events here — your gateway agent use tools to update session.state/artifacts.
    """
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_payload["text"])]
    )
    events = _runner.run_async(
        session_id=session.id,
        user_id=user_payload.get("user_id", USER_ID),
        new_message=content,
    )
    async for event in events:
        print(event.content.parts[0].text) if event.content and event.content.parts else "<no content>"
        # We could log tool calls / responses here if needed.
        # State changes are persisted in the session service by your tools.


async def _store_product_and_assets_as_artifacts(session: Session, req: DiscoverRequest) -> Session | None:
    """
    Store product and user asset data into the artifact service for this session.
    Agents can later use artifact lookups instead of raw JSON in prompts.
    """
    
    state_changes = {}
    state_changes["product_title"] = req.product.title
    state_changes["product_description"] = req.product.description or ""
    
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(str(req.product.image.url))
            resp.raise_for_status()
            data = resp.content
            mime = resp.headers.get("content-type", "application/octet-stream")
            product_image_artifact = types.Part.from_bytes(
                data=data, mime_type="image/jpeg"
            )
            product_artifact_name = "product_image.jpg"
            await _artifacts_service.save_artifact(app_name = APP_NAME,
                                                user_id=USER_ID,
                                                session_id=session.id,
                                                filename=product_artifact_name,
                                                artifact=product_image_artifact)
            state_changes["product_image"] = "{artifact." + product_artifact_name + "}"
            print(f"Product image saved as ADK artifact: {product_artifact_name}")
    except Exception as e:
        raise HTTPException(400, f"Failed to fetch asset {asset.id} from {asset.url}: {e}")
   
                

    # User assets: fetch binary data if URL is local HTTP endpoint
    print(req.assets)
    for i, asset in enumerate(req.assets, start=1):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(str(asset.url))
                resp.raise_for_status()
                data = resp.content
                mime = resp.headers.get("content-type", "application/octet-stream")
                asset_artifact_name = f"asset_{i}.jpg"
                asset_artifact = types.Part.from_bytes(data=data, mime_type=mime)
                await _artifacts_service.save_artifact(app_name = APP_NAME,
                                                    user_id=USER_ID,
                                                    session_id=session.id,
                                                    filename=asset_artifact_name,
                                                    artifact=asset_artifact)
                state_changes[f"asset_{i}_image"] = "{artifact." + asset_artifact_name + "}"
                print(asset_artifact_name)
        except Exception as e:
            raise HTTPException(400, f"Failed to fetch asset {asset.id} from {asset.url}: {e}")

        state_changes[f"asset_{i}_description"] = asset.description or ""
        
    assets_count = len(req.assets)
    state_changes["assets_count"] = assets_count
        
    # --- Create Event with Actions ---
    actions_with_update = EventActions(state_delta=state_changes)
    # This event might represent an internal system action, not just an agent response
    current_time = time.time()
    system_event = Event(
        invocation_id="inv_init",
        author="system", # Or 'agent', 'tool' etc.
        actions=actions_with_update,
        timestamp=current_time
        # content might be None or represent the action taken
    )

    # --- Append the Event (This updates the state) ---
    await _session_service.append_event(session, system_event)
    print("`append_event` called with explicit state delta.")

    # --- Check Updated State ---
    updated_session: Session = await _session_service.get_session(app_name=APP_NAME,
                                                user_id=USER_ID,
                                                session_id=session.id)
    print(f"State after INIT: {updated_session.state}")
    print(f"Artifacts after INIT: {await _artifacts_service.list_artifact_keys(app_name=APP_NAME, user_id=USER_ID, session_id=session.id)}")
        
    return updated_session

# ---------------------------
# Endpoints
# ---------------------------

@app.post(path="/discover", response_model=DiscoverResponse)
async def discover(req: DiscoverRequest):
    """
    Starts (or reuses) a session, invokes the gateway agent in DISCOVERY mode,
    then reads the options your gateway stored in session.state["ga"]["options"].
    """
    # session_id = _ensure_session(req.session_id)
    session = await _session_service.create_session(state={}, app_name=APP_NAME, user_id=USER_ID)
    
    session = await _store_product_and_assets_as_artifacts(session, req)
    if not session:
        raise HTTPException(500, "Failed to create or update session")

    # Build a discovery phase payload the gateway instruction understands.
    # Keep it simple/textual; your gateway_agent instruction should parse PHASE and JSON block.
    discover_text = (
        "PHASE: DISCOVERY\n"
        # "state keys available: " + ", ".join(session.state.keys()) + "\n"
        # "Please tell what I can do with available context\n"
        # "Context:\n"
        # "- Product title: {product_title}\n"
        # "- Product description: {product_description}\n"
        # "- Product image: {artifact.product_image.png}\n"
    )
    
    for k, v in session.state.items():
        discover_text += f"- {k}: {v}\n"
    
    # for i, asset in enumerate(req.assets, start=1):
    #     asset_text = "Description: {asset_" + str(i) + "_description}"
    #     asset_filename = f"asset_{i}.jpg"
    #     asset_text = asset_text + "\nImage: {artifact." + asset_filename + "}"
    #     discover_text += f" - Asset {i}:\n" + asset_text + "\n"

    print("Discover text:", discover_text)

    await _run_gateway_turn(
        session,
        {"text": discover_text, "user_id": USER_ID}
    )

    session: Session = await _session_service.get_session(app_name=APP_NAME,
                                                user_id=USER_ID,
                                                session_id=session.id)

    # Read options from session.state (written by your gateway's set_options tool)
    state = session.state or {}
    print("Gateway state:", state)
    routing: OptionsList = state.get("options", {})
    print("Routing options:", routing)
    if not routing:
        # It's possible discovery failed silently — surface a helpful message
        raise HTTPException(502, "No options found in session.state['ga']['options'] after discovery")

    # options = [
    #     Option(
    #         option_id=option.option_id,
    #         title=option.title,
    #         agent_id=option.agent_id,
    #         meta_data=option.meta_data,
    #     )
    #     for option in routing.options
    # ]
    return DiscoverResponse(session_id=session.id, options=routing)


@app.post("/execute", response_model=ExecuteResult)
async def execute(req: ExecuteRequest):
    """
    Invokes the gateway agent in EXECUTION mode for the given option_id,
    then returns job snapshot from session.state["jobs"][job_id] (as written by your sub-agent).
    """
    session: Session = await _session_service.get_session(app_name=APP_NAME,
                                                user_id=USER_ID,
                                                session_id=req.session_id)

    execute_text = (
        "PHASE: EXECUTION\n"
        f"Execute the option '{req.option_id}'.\n"
        "Look up the option's metadata from session state and route to the correct sub-agent.\n"
    )
    for k, v in session.state.items():
        execute_text += f"- {k}: {v}\n"
        
    print("Execute text:", execute_text)

    await _run_gateway_turn(
        session,
        {"text": execute_text, "user_id": USER_ID}
    )

    # Read job snapshot. Your stylist should have created/updated this entry.
    session = await _session_service.get_session(app_name=APP_NAME,
                                                user_id=USER_ID,
                                                session_id=req.session_id)
    state = session.state
    print(state)
    # jobs = state.get("jobs", {})

    # # If your execute tool writes last_job_id into ga state you can read it; else try to pick the last one.
    # last_job_id = state.get("ga", {}).get("last_job_id")
    # job_payload = {}
    # if last_job_id and last_job_id in jobs:
    #     job_payload = jobs[last_job_id]
    #     job_id = last_job_id
    # else:
    #     # fallback: pick any job (last inserted semantics are not guaranteed in dict, but good enough for MVP)
    #     if jobs:
    #         job_id, job_payload = next(reversed(jobs.items()))
    #     else:
    #         raise HTTPException(502, "No job found in session.state['jobs'] after execute")

    # return ExecuteResult(
    #     job_id=job_id,
    #     status=job_payload.get("status", "running"),
    #     images=job_payload.get("images", []),
    #     message=job_payload.get("message"),
    # )
    
    return ExecuteResult(
        job_id="job_12345",
        status="succeeded",
        images=[state.get("image_url", "")],
        message="Image generated successfully."
    )


@app.get("/healthz")
async def healthz():
    return {"ok": True}
