# app/integrations/cloudinary_storage.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import cloudinary
import cloudinary.uploader
import cloudinary.api
import cloudinary.utils

from app.settings import settings


def is_url(s: str) -> bool:
    if not s:
        return False
    s = s.strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def init_cloudinary() -> None:
    if not settings.CLOUDINARY_URL:
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


def build_delivery_url(public_id: str, fmt: Optional[str], resource_type: str = "video") -> str:
    """
    Build a secure delivery URL even if Admin API doesn't return secure_url.
    """
    init_cloudinary()
    url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        resource_type=resource_type,
        secure=True,
        format=fmt
    )
    return url


def list_resources_by_prefix(
    prefix: Optional[str],
    *,
    resource_type: str = "video",
    max_results: int = 100,
    fields: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Lists resources using Cloudinary Admin API (requires CLOUDINARY_URL with api_key/secret).
    Supports pagination (next_cursor).
    """
    init_cloudinary()
    out: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None

    while True:
        params: Dict[str, Any] = {
            "type": "upload",
            "resource_type": resource_type,
            "max_results": max_results,
        }
        if prefix:
            params["prefix"] = prefix
        if next_cursor:
            params["next_cursor"] = next_cursor
        if fields:
            params["fields"] = fields

        resp = cloudinary.api.resources(**params)
        out.extend(resp.get("resources", []))
        next_cursor = resp.get("next_cursor")
        if not next_cursor:
            break

        # safety cap
        if len(out) >= 1000:
            break

    return out

def list_folder_resources(prefix: str, resource_type: str = "video", max_results: int = 100) -> List[Dict[str, Any]]:
    """
    Backward-compatible alias used by older route files.
    """
    fields = "public_id,format,resource_type,type,bytes,width,height,duration,created_at,secure_url,url,filename,display_name,folder,asset_folder"
    return list_resources_by_prefix(prefix, resource_type=resource_type, max_results=max_results, fields=fields)

def list_resources_by_asset_folder(asset_folder: str, max_results: int = 100, fields: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Lists assets in a Cloudinary asset folder (dynamic folder mode).
    This is the correct way when you place files in a UI folder like /gameplay. :contentReference[oaicite:1]{index=1}
    """
    init_cloudinary()
    out: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None

    while True:
        params: Dict[str, Any] = {
            "asset_folder": asset_folder,
            "max_results": max_results,
        }
        if fields:
            params["fields"] = fields
        if next_cursor:
            params["next_cursor"] = next_cursor

        resp = cloudinary.api.resources_by_asset_folder(**params)  # Admin API wrapper
        out.extend(resp.get("resources", []))
        next_cursor = resp.get("next_cursor")
        if not next_cursor:
            break
        if len(out) >= 1000:
            break

    return out
