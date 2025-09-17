from __future__ import annotations
import io
import os
from typing import Dict, Iterable, Optional, Tuple
import json

from models import Asset, FileStat


class IMetadataStore:
    def create(self, asset: Asset) -> None: ...
    def get(self, asset_id: str) -> Optional[Asset]: ...
    def list_assets(
        self,
        user_id: str,
        *,
        page_token: Optional[str] = None,
        page_size: int = 50,
        include_deleted: bool = False,
        order: str = "created_desc",
    ) -> Tuple[list[Asset], Optional[str]]: ...
    def update_text(self, asset_id: str, text: Optional[str]) -> None: ...
    def soft_delete(self, asset_id: str) -> None: ...
    def count_assets(self, user_id: str) -> int: ...


class InMemoryMetadataStore(IMetadataStore):
    def __init__(self) -> None:
        self._assets: Dict[str, Asset] = {}

    def create(self, asset: Asset) -> None:
        self._assets[asset.asset_id] = asset

    def get(self, asset_id: str) -> Optional[Asset]:
        return self._assets.get(asset_id)

    def list_assets(
        self,
        user_id: str,
        *,
        page_token: Optional[str] = None,
        page_size: int = 50,
        include_deleted: bool = False,
        order: str = "created_desc",
    ) -> Tuple[list[Asset], Optional[str]]:
        items = [a for a in self._assets.values() if a.user_id == user_id and (include_deleted or not a.deleted)]
        reverse = order == "created_desc"
        items.sort(key=lambda a: a.created_at, reverse=reverse)
        start = int(page_token) if page_token else 0
        end = start + page_size
        next_token = str(end) if end < len(items) else None
        return items[start:end], next_token

    def update_text(self, asset_id: str, text: Optional[str]) -> None:
        a = self._assets.get(asset_id)
        if a:
            a.text = text
            a.has_text = bool(text)

    def soft_delete(self, asset_id: str) -> None:
        a = self._assets.get(asset_id)
        if a:
            a.deleted = True

    def count_assets(self, user_id: str) -> int:
        return len([a for a in self._assets.values() if a.user_id == user_id and not a.deleted])


class IFileStore:
    def write(self, asset_id: str, *, data: io.BufferedIOBase | bytes, mime: str) -> FileStat: ...
    def stream(self, asset_id: str, *, chunk_size: int = 64 * 1024) -> Iterable[bytes]: ...
    def delete(self, asset_id: str) -> None: ...
    def stat(self, asset_id: str) -> Optional[FileStat]: ...


class FSFileStore(IFileStore):
    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, asset_id: str) -> str:
        # store as /base/ab/cd/asset_id to avoid too many files in one dir
        shard = (asset_id[:2] or "xx") + "/" + (asset_id[2:4] or "yy")
        p = os.path.join(self.base_dir, shard)
        os.makedirs(p, exist_ok=True)
        return os.path.join(p, asset_id)
    def _meta_path(self, asset_id: str) -> str:
        return self._path(asset_id) + ".meta.json"

    def write(self, asset_id: str, *, data: io.BufferedIOBase | bytes, mime: str) -> FileStat:
        path = self._path(asset_id)
        if isinstance(data, (bytes, bytearray)):
            b = data
        else:
            b = data.read()
        with open(path, "wb") as f:
            f.write(b)
        # write sidecar metadata
        meta = {"mime": mime, "size_bytes": len(b)}
        with open(self._meta_path(asset_id), "w", encoding="utf-8") as mf:
            json.dump(meta, mf)
        return FileStat(mime=mime, size_bytes=len(b))

    def stream(self, asset_id: str, *, chunk_size: int = 64 * 1024) -> Iterable[bytes]:
        path = self._path(asset_id)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def delete(self, asset_id: str) -> None:
        path = self._path(asset_id)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        try:
            os.remove(self._meta_path(asset_id))
        except FileNotFoundError:
            pass

    def stat(self, asset_id: str) -> Optional[FileStat]:
        path = self._path(asset_id)
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        # try reading sidecar for mime
        mime = "application/octet-stream"
        try:
            with open(self._meta_path(asset_id), "r", encoding="utf-8") as mf:
                meta = json.load(mf)
                mime = meta.get("mime", mime)
                size = int(meta.get("size_bytes", st.st_size))
                return FileStat(mime=mime, size_bytes=size)
        except FileNotFoundError:
            return FileStat(mime=mime, size_bytes=st.st_size)
