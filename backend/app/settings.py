# app/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Always load backend/app/.env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"), override=True)
except Exception:
    pass


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


@dataclass
class Settings:
    APP_NAME: str = "VidGenAI Backend"
    API_PREFIX: str = "/vidgenai"
    DEBUG: bool = field(default_factory=lambda: _bool_env("DEBUG", False))

    OPENROUTER_API_KEY: str = field(default_factory=lambda: (os.getenv("OPENROUTER_API_KEY") or "").strip())
    ELEVEN_API_KEY: str = field(default_factory=lambda: (os.getenv("ELEVEN_API_KEY") or "").strip())

    ELEVEN_VOICE_POOLS_PATH: str = field(default_factory=lambda: os.getenv("ELEVEN_VOICE_POOLS_PATH", "app/pipelines/voice_pools.json"))

    OUTPUT_ROOT: str = field(default_factory=lambda: os.getenv("OUTPUT_ROOT", "outputs"))
    PROJECT_ROOT: str = field(default_factory=lambda: os.getenv("PROJECT_ROOT", "outputs/projects"))
    JOB_ROOT: str = field(default_factory=lambda: os.getenv("JOB_ROOT", "outputs/jobs"))

    STORE_BACKEND: str = field(default_factory=lambda: os.getenv("STORE_BACKEND", "memory").strip().lower())  # memory|mongo
    MONGODB_URI: str = field(default_factory=lambda: os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    MONGODB_DB: str = field(default_factory=lambda: os.getenv("MONGODB_DB", "vidgenai"))

    MAX_ACTIVE_JOBS: int = field(default_factory=lambda: _int_env("MAX_ACTIVE_JOBS", 2))

    # ✅ Cloudinary
    CLOUDINARY_URL: str = field(default_factory=lambda: (os.getenv("CLOUDINARY_URL") or "").strip())
    CLOUDINARY_FOLDER: str = field(default_factory=lambda: os.getenv("CLOUDINARY_FOLDER", "vidgenai").strip())

    # Background music list prefix in Cloudinary
    CLOUDINARY_BGM_PREFIX: str = field(default_factory=lambda: os.getenv("CLOUDINARY_BGM_PREFIX", "vidgenai/backgroundmusic").strip())


settings = Settings()
