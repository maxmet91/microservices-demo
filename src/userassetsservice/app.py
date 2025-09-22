from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional, Iterable
import logging

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse

from models import Asset, AllocateUploadResponse, UploadFileResponse, FinalizeRequest
from pydantic import BaseModel
from storage import InMemoryMetadataStore, FSFileStore
import config

logger = logging.getLogger("userassetsservice")
logging.basicConfig(level=config.LOG_LEVEL if hasattr(config, "LOG_LEVEL") else "INFO")

app = FastAPI(title="User Assets Service")

meta = InMemoryMetadataStore()
fs = FSFileStore(config.UAS_DATA_DIR)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_mime_allowed(mime: str) -> None:
    if config.UAS_ALLOWED_MIME and mime not in config.UAS_ALLOWED_MIME:
        logger.warning("Rejected upload (mime not allowed): %s", mime)
        raise HTTPException(status_code=400, detail=f"mime not allowed: {mime}")


def _require_size_ok(size: int) -> None:
    if size > config.UAS_MAX_UPLOAD_MB * 1024 * 1024:
        logger.warning("Rejected upload (file too large): size=%d bytes", size)
        raise HTTPException(status_code=400, detail="file too large")


@app.post("/v1/uploads")
def allocate_upload() -> AllocateUploadResponse:
    """Allocate a new asset ID for subsequent upload."""
    asset_id = str(uuid.uuid4())
    logger.debug("Allocated upload asset_id=%s", asset_id)
    return AllocateUploadResponse(asset_id=asset_id)


@app.post("/v1/assets/upload")
def upload_file(asset_id: str, user_id: str, file: UploadFile = File(...)) -> UploadFileResponse:
    """Upload raw file bytes for an allocated asset ID.

    Validates MIME type and size against configuration limits.
    """
    mime = file.content_type or "application/octet-stream"
    _require_mime_allowed(mime)
    data = file.file.read()
    _require_size_ok(len(data))
    stat = fs.write(asset_id, data=data, mime=mime)
    logger.info("Uploaded asset asset_id=%s user_id=%s size=%d mime=%s", asset_id, user_id, stat.size_bytes, mime)
    return UploadFileResponse(asset_id=asset_id, mime=stat.mime, size_bytes=stat.size_bytes)


@app.post("/v1/assets/finalize")
def finalize(req: FinalizeRequest) -> dict:
    """Finalize an uploaded file into a user asset record."""
    if meta.count_assets(req.user_id) >= config.UAS_MAX_ASSETS_PER_USER:
        logger.warning("User %s reached asset limit", req.user_id)
        raise HTTPException(status_code=400, detail="asset limit reached")
    st = fs.stat(req.asset_id)
    if not st:
        raise HTTPException(status_code=404, detail="file not found for asset")
    asset = Asset(
        asset_id=req.asset_id,
        user_id=req.user_id,
        mime=st.mime,
        size_bytes=st.size_bytes,
        has_text=bool(req.text),
        text=req.text,
        created_at=_now(),
        deleted=False,
    )
    meta.create(asset)
    doc = asset.to_public()
    doc["ui_url"] = f"{config.BASE_URL}/api/uas/assets/{asset.asset_id}/file"
    logger.info("Finalized asset asset_id=%s user_id=%s", asset.asset_id, asset.user_id)
    return doc


class UpdateTextPayload(BaseModel):
    text: Optional[str] = None

@app.patch("/v1/assets/{asset_id}/text")
def update_text(asset_id: str, payload: Optional[UpdateTextPayload] = None, text: Optional[str] = None) -> dict:
    """Update the text (note) for an asset.

    Accepts either JSON body {"text": "..."} or a query parameter ?text=... for backward compatibility.
    """
    asset = meta.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")
    new_text = payload.text if (payload and payload.text is not None) else text
    meta.update_text(asset_id, new_text)
    asset = meta.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found after update")
    doc = asset.to_public()
    doc["ui_url"] = f"{config.BASE_URL}/api/uas/assets/{asset.asset_id}/file"
    logger.info("Updated text for asset_id=%s length=%d", asset.asset_id, len(new_text or ""))
    return doc


@app.get("/v1/assets")
def list_assets(user_id: str, page_token: Optional[str] = None, page_size: int = 50) -> dict:
    items, next_token = meta.list_assets(user_id, page_token=page_token, page_size=page_size)
    assets: list[dict] = []
    for asset in items:
        doc = asset.to_public()
        doc["ui_url"] = f"{config.BASE_URL}/api/uas/assets/{asset.asset_id}/file"
        assets.append(doc)
    return {"assets": assets, "next_page_token": next_token}


@app.get("/v1/assets/{asset_id}/file")
def get_file(asset_id: str):
    asset = meta.get(asset_id)
    if not asset or asset.deleted:
        raise HTTPException(status_code=404, detail="asset not found")

    def stream() -> Iterable[bytes]:
        yield from fs.stream(asset_id)

    return StreamingResponse(stream(), media_type=asset.mime)


@app.delete("/v1/assets/{asset_id}")
def delete_asset(asset_id: str):
    asset = meta.get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")
    meta.soft_delete(asset_id)
    fs.delete(asset_id)
    logger.info("Deleted asset asset_id=%s", asset_id)
    return {"ok": True}
