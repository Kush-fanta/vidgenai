# app/schemas/vidgenai.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

Mode = Literal["prompt", "script"]


class CreateProjectRequest(BaseModel):
    mode: Mode
    user_query: Optional[str] = None
    script_text: Optional[str] = None

    languages: List[str] = Field(default_factory=lambda: ["English"])
    style: str = "Cinematic"
    duration_seconds: int = 60

    template_id: str = "t0"
    gameplay_video_path: Optional[str] = None  # local path or URL

    # ✅ Voice selection
    voice_mode: Literal["male", "female", "both"] = "female"
    male_voice_id: Optional[str] = None
    female_voice_id: Optional[str] = None
    seed: int = 42

    # ✅ BGM
    background_music_path: Optional[str] = None
    background_music_volume: float = 0.12


class CreateProjectResponse(BaseModel):
    project_id: str


class SceneOut(BaseModel):
    scene_id: str
    order_index: int
    text: str
    expected_time_in_seconds: Optional[float] = None
    visual_keywords: Optional[str] = None
    overlay_text: Optional[str] = None

    image_url: Optional[str] = None
    audio_url: Optional[str] = None


class ScriptResponse(BaseModel):
    project_id: str
    tts_lang: str
    scenes: List[SceneOut]


class PatchScriptRequest(BaseModel):
    text: str


class GenerateVideoResponse(BaseModel):
    project_id: str
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    project_id: str
    job_id: Optional[str] = None
    status: str
    stage: Optional[str] = None
    progress: int = 0
    error: Optional[str] = None

    final_video_url: Optional[str] = None
    subtitle_url: Optional[str] = None

    updated_at: Optional[str] = None


class GenerateImageResponse(BaseModel):
    project_id: str
    scene_id: str
    image_url: str


class RegenerateSceneScriptResponse(BaseModel):
    project_id: str
    scene_id: str
    text: str
    expected_time_in_seconds: Optional[float] = None
    visual_keywords: Optional[str] = None
    overlay_text: Optional[str] = None


class CatalogItem(BaseModel):
    id: str
    name: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class CatalogResponse(BaseModel):
    items: List[CatalogItem]
