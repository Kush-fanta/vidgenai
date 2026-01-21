# app/main.py
from __future__ import annotations

import os
import shutil
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.settings import settings
from app.api.router import api_router


def create_app() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.API_PREFIX)

    @app.on_event("startup")
    def _startup():
        os.makedirs(settings.OUTPUT_ROOT, exist_ok=True)
        os.makedirs(settings.PROJECT_ROOT, exist_ok=True)
        os.makedirs(settings.JOB_ROOT, exist_ok=True)

        if shutil.which("ffmpeg") is None:
            print("[WARN] ffmpeg not found on PATH")
        if shutil.which("ffprobe") is None:
            print("[WARN] ffprobe not found on PATH")

        if settings.STORE_BACKEND == "mongo":
            try:
                from app.db.mongo_indexes import ensure_indexes
                ensure_indexes()
                print("[db] Mongo indexes ensured")
            except Exception as e:
                print("[WARN] Mongo index ensure failed:", e)

    return app


app = create_app()
