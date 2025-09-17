from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class FileStat:
    mime: str
    size_bytes: int


@dataclass
class Asset:
    asset_id: str
    user_id: str
    mime: str
    size_bytes: int
    has_text: bool
    text: Optional[str]
    created_at: datetime
    deleted: bool = False

    def to_public(self) -> dict:
        d = asdict(self)
        # datetime to isoformat
        d["created_at"] = self.created_at.astimezone(timezone.utc).isoformat()
        return d


# DTOs
@dataclass
class AllocateUploadResponse:
    asset_id: str
    upload_method: str = "multipart"


@dataclass
class UploadFileResponse:
    asset_id: str
    mime: str
    size_bytes: int


@dataclass
class FinalizeRequest:
    user_id: str
    asset_id: str
    text: Optional[str] = None


@dataclass
class ListAssetsResponse:
    assets: list[dict]
    next_page_token: Optional[str]

