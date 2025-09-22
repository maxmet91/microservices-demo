import asyncio
import time
import os
import io
import logging
from typing import List, Optional, Dict, Any, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from google.adk.events import Event, EventActions
import httpx
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# --- ADK imports (match your installed ADK version) ---
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, Session
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.genai import types

# Your multi-agent graph (gateway root agent with stylist sub-agent)
from multi_tool_agent.agent import root_agent
from multi_tool_agent.models import Option


APP_NAME = "online_boutique_agents"
USER_ID = "tester"

logger = logging.getLogger(APP_NAME)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

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
    # Accept relative ("/api/uas/assets/.../file") or absolute http(s) URLs.
    url: str

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    image: ProductImage

class UserAsset(BaseModel):
    id: str
    # Relative path or absolute URL. Normalized later in _store_product_and_assets_as_artifacts.
    url: str
    description: Optional[str] = None

class DiscoverRequest(BaseModel):
    session_id: Optional[str] = None
    product: Product
    assets: List[UserAsset] = Field(default_factory=list)
    notes: Optional[str] = None

class DiscoverResponse(BaseModel):
    session_id: str
    options: List[Option]

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
        if event.content and event.content.parts:
            # Log only first part text to avoid overly large logs.
            logger.debug("Event text: %s", event.content.parts[0].text[:500])
        else:
            logger.debug("Event with no content")
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
    
    frontend_base = os.getenv("FRONTEND_ADDR", "http://frontend:80")
    def _abs(u: str) -> str:
        if u.startswith("http://") or u.startswith("https://"):
            return u
        # Ensure the URL starts with http:// if not present
        if not frontend_base.startswith("http://") and not frontend_base.startswith("https://"):
            frontend_base_with_http = "http://" + frontend_base
        else:
            frontend_base_with_http = frontend_base
        return frontend_base_with_http.rstrip("/") + u
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            prod_url = _abs(str(req.product.image.url))
            resp = await client.get(prod_url)
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
            logger.info("Saved product image artifact: %s", product_artifact_name)
    except Exception as e:
        logger.exception("Failed to fetch product image")
        raise HTTPException(400, f"Failed to fetch product image: {e}") from e
   
                

    # User assets: fetch binary data if URL is local HTTP endpoint
    logger.debug("User assets count=%d", len(req.assets))
    for i, asset in enumerate(req.assets, start=1):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                asset_url = _abs(str(asset.url))
                resp = await client.get(asset_url)
                resp.raise_for_status()
                data = resp.content
                mime = resp.headers.get("content-type", "application/octet-stream")
                asset_artifact_name = f"asset_image_{i}.jpg"
                asset_artifact = types.Part.from_bytes(data=data, mime_type=mime)
                await _artifacts_service.save_artifact(app_name = APP_NAME,
                                                    user_id=USER_ID,
                                                    session_id=session.id,
                                                    filename=asset_artifact_name,
                                                    artifact=asset_artifact)
                state_changes[f"asset_image_{i}"] = "{artifact." + asset_artifact_name + "}"
                logger.info("Saved user asset artifact: %s", asset_artifact_name)
        except Exception as e:
            logger.exception("Failed to fetch asset %s from %s", asset.id, asset.url)
            raise HTTPException(400, f"Failed to fetch asset {asset.id} from {asset.url}: {e}") from e

        state_changes[f"asset_description_{i}"] = asset.description or ""
        
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
    logger.debug("append_event called with explicit state delta")

    # --- Check Updated State ---
    updated_session: Session = await _session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    logger.debug("State after INIT: %s", updated_session.state)
    logger.debug(
        "Artifacts after INIT: %s",
        await _artifacts_service.list_artifact_keys(
            app_name=APP_NAME, user_id=USER_ID, session_id=session.id
        ),
    )
        
    return updated_session

# ---------------------------
# Endpoints
# ---------------------------

@app.post(path="/discover", response_model=DiscoverResponse)
async def discover(req: DiscoverRequest):
    session = await _session_service.create_session(state={}, app_name=APP_NAME, user_id=USER_ID)
    
    session = await _store_product_and_assets_as_artifacts(session, req)
    if not session:
        raise HTTPException(500, "Failed to create or update session")

    # Build a discovery phase payload the gateway instruction understands.
    # Keep it simple/textual; your gateway_agent instruction should parse PHASE and JSON block.
    discover_text = (
        "PHASE: DISCOVERY\n"
    )
    for k, v in session.state.items():
        discover_text += f"- {k}: {v}\n"
    
    logger.debug("Discover text: %s", discover_text[:1000])

    await _run_gateway_turn(
        session,
        {"text": discover_text, "user_id": USER_ID}
    )

    session: Session = await _session_service.get_session(app_name=APP_NAME,
                                                user_id=USER_ID,
                                                session_id=session.id)

    state = session.state or {}
    logger.debug("Gateway state: %s", state)
    options: List[Option] = state.get("options") or []
    logger.debug("Routing options: %s", options)

    return DiscoverResponse(session_id=session.id, options=options)


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
        
    logger.debug("Execute text: %s", execute_text[:1000])

    await _run_gateway_turn(
        session,
        {"text": execute_text, "user_id": USER_ID}
    )

    # Read job snapshot. Your stylist should have created/updated this entry.
    session = await _session_service.get_session(app_name=APP_NAME,
                                                user_id=USER_ID,
                                                session_id=req.session_id)
    state = session.state
    logger.debug("Session state after execute: %s", state)
    
    # If image generation tool stored output_image (artifact filename)
    output_image = state.get("output_image") if state else None
    images: List[str] = []

    if output_image:
        # Try to load from artifact service (preferred)
        try:
            part = await _artifacts_service.load_artifact(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=req.session_id,
                filename=output_image,
            )
            if part is not None:
                # Expose via artifacts endpoint using session_id query param
                images.append(f"/artifacts/{output_image}?session_id={req.session_id}")
            else:
                # Fallback: check disk (legacy path)
                if os.path.exists(output_image):
                    images.append(f"/artifacts/{output_image}")
        except Exception as e:
            logger.exception("Failed to load artifact '%s' from service", output_image)
            # Try disk as last resort
            if os.path.exists(output_image):
                images.append(f"/artifacts/{output_image}")

    status = "succeeded" if images else "running"
    return ExecuteResult(
        job_id="job_12345",
        status=status,
        images=images,
        message="Image generated successfully." if images else "No image yet."
    )


def _extract_part_bytes(part) -> Tuple[Optional[bytes], str]:
    """Attempt to extract raw bytes + mime from a google.genai.types.Part instance."""
    try:
        if part is None:
            return None, "application/octet-stream"
        inline_data = getattr(part, "inline_data", None)
        if inline_data is not None:
            data = getattr(inline_data, "data", None)
            mime = getattr(inline_data, "mime_type", "application/octet-stream")
            if data:
                return data, mime
        data_attr = getattr(part, "data", None)
        if data_attr is not None:
            mime = getattr(part, "mime_type", "application/octet-stream")
            return data_attr, mime
    except Exception as e:  # pragma: no cover - defensive
        print(f"Could not extract bytes from part: {e}")
    return None, "application/octet-stream"


@app.get("/artifacts/{filename}")
async def get_artifact(filename: str, session_id: Optional[str] = None):
    """
    Serve an artifact either from the in-memory artifact service (preferred) or disk fallback.
    session_id is required for in-memory lookup; if omitted we try disk only.
    """
    # Try artifact service first if session_id given
    if session_id:
        try:
            part = await _artifacts_service.load_artifact(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=session_id,
                filename=filename,
            )
            if part is not None:
                data, mime = _extract_part_bytes(part)
                if data:
                    return StreamingResponse(io.BytesIO(data), media_type=mime)
        except Exception:
            logger.exception("Artifact service load failed for %s / %s", filename, session_id)

    # Fallback to disk (legacy behavior)
    if os.path.exists(filename):
        return FileResponse(filename)
    raise HTTPException(404, "artifact not found")


@app.get("/healthz")
async def healthz():
    return {"ok": True}
