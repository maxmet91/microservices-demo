import os
from typing import List


def _split_csv(val: str) -> List[str]:
    return [v.strip() for v in val.split(",") if v.strip()] if val else []


UAS_DATA_DIR = os.getenv("UAS_DATA_DIR", "/data/assets")
UAS_ALLOWED_MIME = _split_csv(os.getenv("UAS_ALLOWED_MIME", "image/jpeg,image/png"))
UAS_MAX_UPLOAD_MB = int(os.getenv("UAS_MAX_UPLOAD_MB", "16"))
UAS_MAX_ASSETS_PER_USER = int(os.getenv("UAS_MAX_ASSETS_PER_USER", "5"))

BASE_URL = os.getenv("BASE_URL", "")
