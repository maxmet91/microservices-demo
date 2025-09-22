from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse

from models import Asset, AllocateUploadResponse, UploadFileResponse, FinalizeRequest
from pydantic import BaseModel
from storage import InMemoryMetadataStore, FSFileStore
import config

app = FastAPI(title="User Assets Service")

meta = InMemoryMetadataStore()
fs = FSFileStore(config.UAS_DATA_DIR)


def _now():
    return datetime.now(timezone.utc)


def _require_mime_allowed(mime: str):
    if config.UAS_ALLOWED_MIME and mime not in config.UAS_ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"mime not allowed: {mime}")


def _require_size_ok(size: int):
    if size > config.UAS_MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file too large")


@app.post("/v1/uploads")
def allocate_upload() -> AllocateUploadResponse:
    return AllocateUploadResponse(asset_id=str(uuid.uuid4()))


@app.post("/v1/assets/upload")
def upload_file(asset_id: str, user_id: str, file: UploadFile = File(...)) -> UploadFileResponse:
    # Validate mime and size
    mime = file.content_type
    _require_mime_allowed(mime)
    data = file.file.read()
    _require_size_ok(len(data))
    stat = fs.write(asset_id, data=data, mime=mime)
    return UploadFileResponse(asset_id=asset_id, mime=stat.mime, size_bytes=stat.size_bytes)


@app.post("/v1/assets/finalize")
def finalize(req: FinalizeRequest) -> dict:
    # enforce per-user limit
    if meta.count_assets(req.user_id) >= config.UAS_MAX_ASSETS_PER_USER:
        raise HTTPException(status_code=400, detail="asset limit reached")
    st = fs.stat(req.asset_id)
    if not st:
        raise HTTPException(status_code=404, detail="file not found for asset")
    a = Asset(
        asset_id=req.asset_id,
        user_id=req.user_id,
        mime=st.mime,
        size_bytes=st.size_bytes,
        has_text=bool(req.text),
        text=req.text,
        created_at=_now(),
        deleted=False,
    )
    meta.create(a)
    out = a.to_public()
    out["ui_url"] = f"{config.BASE_URL}/api/uas/assets/{a.asset_id}/file"
    return out


class UpdateTextPayload(BaseModel):
    text: Optional[str] = None

@app.patch("/v1/assets/{asset_id}/text")
def update_text(asset_id: str, payload: Optional[UpdateTextPayload] = None, text: Optional[str] = None) -> dict:
    """Update the text (note) for an asset.

    Accepts either JSON body {"text": "..."} (preferred) or a query parameter ?text=... for backward compatibility.
    """
    a = meta.get(asset_id)
    if not a:
        raise HTTPException(status_code=404, detail="asset not found")
    # Prefer JSON payload if provided, else fallback to query param.
    new_text = payload.text if (payload and payload.text is not None) else text
    meta.update_text(asset_id, new_text)
    a = meta.get(asset_id)
    if not a:  # Extremely unlikely since we just updated, but guard anyway.
        raise HTTPException(status_code=404, detail="asset not found after update")
    out = a.to_public()
    out["ui_url"] = f"{config.BASE_URL}/api/uas/assets/{a.asset_id}/file"
    return out


@app.get("/v1/assets")
def list_assets(user_id: str, page_token: Optional[str] = None, page_size: int = 50):
    items, next_token = meta.list_assets(user_id, page_token=page_token, page_size=page_size)
    assets = []
    for a in items:
        d = a.to_public()
        d["ui_url"] = f"{config.BASE_URL}/api/uas/assets/{a.asset_id}/file"
        assets.append(d)
    return {"assets": assets, "next_page_token": next_token}


@app.get("/v1/assets/{asset_id}/file")
def get_file(asset_id: str):
    a = meta.get(asset_id)
    if not a or a.deleted:
        raise HTTPException(status_code=404, detail="asset not found")
    # stream from fs
    def stream():
        yield from fs.stream(asset_id)
    return StreamingResponse(stream(), media_type=a.mime)


@app.delete("/v1/assets/{asset_id}")
def delete_asset(asset_id: str):
    a = meta.get(asset_id)
    if not a:
        raise HTTPException(status_code=404, detail="asset not found")
    meta.soft_delete(asset_id)
    fs.delete(asset_id)
    return {"ok": True}
