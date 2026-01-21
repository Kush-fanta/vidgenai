# app/integrations/cloudinary_storage.py
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api

from app.settings import settings


def is_url(s: str) -> bool:
    if not s:
        return False
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def init_cloudinary() -> None:
    """
    Requires CLOUDINARY_URL to be set (recommended Cloudinary config method).
    """
    if not settings.CLOUDINARY_URL:
        # Cloudinary SDK also reads CLOUDINARY_URL from env,
        # but we enforce it for clarity.
        raise ValueError("CLOUDINARY_URL missing in environment.")
    cloudinary.config(secure=True)


def upload_bytes(
    data: bytes,
    filename: str,
    *,
    resource_type: str,
    folder: str,
    public_id: Optional[str] = None,
    overwrite: bool = True,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    init_cloudinary()
    bio = BytesIO(data)
    bio.name = filename

    opts: Dict[str, Any] = {
        "resource_type": resource_type,  # image|video|raw
        "folder": folder,
        "overwrite": overwrite,
        "use_filename": True,
        "unique_filename": False,
    }
    if public_id:
        opts["public_id"] = public_id
    if tags:
        opts["tags"] = tags

    return cloudinary.uploader.upload(bio, **opts)


def upload_path(
    path: str,
    *,
    resource_type: str,
    folder: str,
    public_id: Optional[str] = None,
    overwrite: bool = True,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    init_cloudinary()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"upload_path: file not found: {path}")

    opts: Dict[str, Any] = {
        "resource_type": resource_type,
        "folder": folder,
        "overwrite": overwrite,
        "use_filename": True,
        "unique_filename": False,
    }
    if public_id:
        opts["public_id"] = public_id
    if tags:
        opts["tags"] = tags

    # Use chunked upload for large videos
    size = p.stat().st_size
    if resource_type == "video" and size > 100 * 1024 * 1024:
        return cloudinary.uploader.upload_large(str(p), **opts)
    return cloudinary.uploader.upload(str(p), **opts)


def download_url_to_file(url: str, dest_path: str) -> str:
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with requests.get(url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

    return str(dest.resolve())


def list_folder_resources(prefix: str, resource_type: str = "video", max_results: int = 100) -> List[Dict[str, Any]]:
    """
    Lists resources under a folder/prefix using Cloudinary Admin API.
    Good for listing background music assets stored in Cloudinary.
    """
    init_cloudinary()
    res = cloudinary.api.resources(
        type="upload",
        resource_type=resource_type,
        prefix=prefix,
        max_results=max_results,
    )
    return res.get("resources", [])
