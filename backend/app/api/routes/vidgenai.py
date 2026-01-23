# app/api/routes/vidgenai.py
from __future__ import annotations

import os
import requests
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
import re
from app.schemas.vidgenai import (
    CreateProjectRequest, CreateProjectResponse,
    ScriptResponse, SceneOut,
    PatchScriptRequest,
    GenerateVideoResponse,
    JobStatusResponse,
    GenerateImageResponse,
    RegenerateSceneScriptResponse,
    CatalogResponse, CatalogItem
)
from app.services.vidgen_service import VidGenService, derive_tts_lang
from app.services.job_service import JobService
from app.services.store import STORE
from app.settings import settings
from app.integrations.cloudinary_storage import list_folder_resources,list_resources_by_asset_folder,build_delivery_url,is_url

router = APIRouter()
svc = VidGenService()
jobs = JobService()


def stream_from_url(url: str, content_type: str, download_filename: str | None = None):
    def gen():
        with requests.get(url, stream=True, timeout=90) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    yield chunk

    headers = {}
    if download_filename:
        headers["Content-Disposition"] = f'attachment; filename="{download_filename}"'
    return StreamingResponse(gen(), media_type=content_type, headers=headers)

def _clean_clip_name(s: str) -> str:
    """
    If filename is like clip_003_zsftrl -> return clip_003
    Only applies to clip_XXX_* pattern.
    """
    base = (s or "").strip()
    m = re.match(r"^(clip_\d{3})(?:[_-][a-z0-9]{4,})$", base, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return base

@router.get("/gameplay", response_model=CatalogResponse)
def gameplay_list():
    fields = "public_id,format,resource_type,bytes,width,height,duration,created_at,secure_url,url,filename,display_name,asset_folder,folder"

    from app.integrations.cloudinary_storage import (
        list_resources_by_asset_folder,
        list_resources_by_prefix,
        build_delivery_url,
    )

    # ✅ 1) First try: list by asset_folder="gameplay" (your UI folder)
    resources = []
    try:
        resources = list_resources_by_asset_folder("gameplay", max_results=200, fields=fields)
    except Exception as e:
        # don’t silently swallow; print to terminal so you can debug
        print("[gameplay] asset_folder listing failed:", e)

    # ✅ 2) Fallback: prefix listing (if your account is fixed folder mode)
    if not resources:
        try:
            resources = list_resources_by_prefix("gameplay/", resource_type="video", max_results=200, fields=fields)
        except Exception as e:
            print("[gameplay] prefix gameplay/ failed:", e)

    # ✅ 3) Last fallback: prefix clip_
    if not resources:
        try:
            resources = list_resources_by_prefix("clip_", resource_type="video", max_results=200, fields=fields)
        except Exception as e:
            print("[gameplay] prefix clip_ failed:", e)

    items = []
    for r in resources:
        public_id = r.get("public_id")
        if not public_id:
            continue

        fmt = r.get("format") or "mp4"
        url = r.get("secure_url") or r.get("url") or build_delivery_url(public_id, fmt, resource_type="video")

        raw_name = r.get("display_name") or r.get("filename") or public_id.split("/")[-1]
        name = _clean_clip_name(raw_name)

        # filter videos only (resources_by_asset_folder can return any resource_type)
        if r.get("resource_type") and r.get("resource_type") != "video":
            continue

        items.append(
            CatalogItem(
                id=public_id,
                name=name,
                meta={
                    "url": url,
                    "duration": r.get("duration"),
                    "width": r.get("width"),
                    "height": r.get("height"),
                    "bytes": r.get("bytes"),
                    "created_at": r.get("created_at"),
                    "asset_folder": r.get("asset_folder"),
                    "folder": r.get("folder"),
                },
            )
        )

    return CatalogResponse(items=items)


@router.post("/generate/project_id", response_model=CreateProjectResponse)
def generate_project_id(req: CreateProjectRequest):
    if req.mode == "prompt" and not req.user_query:
        raise HTTPException(status_code=400, detail="user_query_required_for_prompt")
    if req.mode == "script" and not req.script_text:
        raise HTTPException(status_code=400, detail="script_text_required_for_script")

    payload = req.model_dump()
    payload["tts_lang"] = derive_tts_lang(payload.get("languages", []))
    payload["max_duration_attempts"] = 2  # backend default

    # Template gameplay requirement
    tid = (payload.get("template_id") or "t0").strip()
    gp = payload.get("gameplay_video_path")
    if tid in {"t1","t2","t3","t4","t5","t6","t7","t9"}:
        if not gp:
            raise HTTPException(status_code=400, detail=f"gameplay_video_path_required_for_template_{tid}")
        # ✅ enforce Cloudinary/URL only
        if not is_url(str(gp)):
            raise HTTPException(status_code=400, detail="gameplay_video_path_must_be_a_url")

    # ✅ STRICT voice requirements (no random fallback)
    vm = (payload.get("voice_mode") or "female").strip().lower()
    male_id = (payload.get("male_voice_id") or "").strip()
    female_id = (payload.get("female_voice_id") or "").strip()

    if vm == "female" and not female_id:
        raise HTTPException(status_code=400, detail="female_voice_id_required_when_voice_mode_female")
    if vm == "male" and not male_id:
        raise HTTPException(status_code=400, detail="male_voice_id_required_when_voice_mode_male")
    if vm == "both" and (not male_id or not female_id):
        raise HTTPException(status_code=400, detail="male_voice_id_and_female_voice_id_required_when_voice_mode_both")

    pid = svc.create_project(payload)
    return CreateProjectResponse(project_id=pid)


@router.get("/script/{project_id}", response_model=ScriptResponse)
def get_script(project_id: str):
    scenes = svc.get_or_generate_script(project_id)
    proj = STORE.get_project(project_id)
    tts_lang = proj.get("tts_lang") if proj else "en"
    return ScriptResponse(project_id=project_id, tts_lang=tts_lang, scenes=[SceneOut(**s) for s in scenes])


@router.patch("/{project_id}/script/{scene_id}", response_model=SceneOut)
def patch_scene_script(project_id: str, scene_id: str, req: PatchScriptRequest):
    s = svc.patch_scene_script(project_id, scene_id, req.text)
    return SceneOut(**s)


@router.patch("/{project_id}/image/{scene_id}")
def patch_scene_image(project_id: str, scene_id: str, file: UploadFile = File(...)):
    content = file.file.read()
    url = svc.save_uploaded_image(project_id, scene_id, file.filename or "upload.jpg", content)
    return {"project_id": project_id, "scene_id": scene_id, "image_url": url}


@router.post("/generate/image/{project_id}/{scene_id}", response_model=GenerateImageResponse)
def generate_image(project_id: str, scene_id: str):
    url = svc.generate_scene_image(project_id, scene_id)
    return GenerateImageResponse(project_id=project_id, scene_id=scene_id, image_url=url)


@router.post("/generate/script/{project_id}/{scene_id}", response_model=RegenerateSceneScriptResponse)
def regenerate_scene_script(project_id: str, scene_id: str):
    s = svc.regenerate_scene_script(project_id, scene_id)
    return RegenerateSceneScriptResponse(
        project_id=project_id,
        scene_id=scene_id,
        text=s.get("text", ""),
        expected_time_in_seconds=s.get("expected_time_in_seconds"),
        visual_keywords=s.get("visual_keywords"),
        overlay_text=s.get("overlay_text"),
    )


@router.post("/generate/video/{project_id}", response_model=GenerateVideoResponse)
def generate_video(project_id: str):
    job_id = jobs.start_generate_video(project_id)
    return GenerateVideoResponse(project_id=project_id, job_id=job_id, status="started")


@router.get("/job/status/{project_id}", response_model=JobStatusResponse)
def job_status(project_id: str):
    job = jobs.get_status_for_project(project_id)
    if not job:
        return JobStatusResponse(project_id=project_id, status="no_job", progress=0)

    result = job.get("result") or {}
    return JobStatusResponse(
        project_id=project_id,
        job_id=job.get("job_id"),
        status=job.get("status"),
        stage=job.get("stage"),
        progress=int(job.get("progress") or 0),
        error=job.get("error"),
        final_video_url=result.get("final_video_url"),
        subtitle_url=result.get("subtitle_url"),
        updated_at=job.get("updated_at"),
    )


@router.get("/subtitle/{project_id}")
def get_subtitle(project_id: str):
    url = svc.get_last_subtitle_url(project_id)
    return stream_from_url(url, content_type="text/plain", download_filename=f"{project_id}.ass")


@router.get("/video/preview/{project_id}")
def video_preview(project_id: str):
    url = svc.get_last_video_url(project_id)
    return stream_from_url(url, content_type="video/mp4")


@router.get("/video/export/{project_id}")
def video_export(project_id: str):
    url = svc.get_last_video_url(project_id)
    return stream_from_url(url, content_type="video/mp4", download_filename=f"{project_id}.mp4")


@router.get("/languages", response_model=CatalogResponse)
def languages():
    items = [CatalogItem(id=k, name=k.title()) for k in ["English","Hindi","Marathi","Tamil","Telugu","Bengali","Gujarati","Kannada","Malayalam","Punjabi","Odia","Assamese","Urdu"]]
    return CatalogResponse(items=items)


@router.get("/voice/male", response_model=CatalogResponse)
def voice_male():
    from app.pipelines.voice import load_voice_pools
    os.environ["ELEVEN_VOICE_POOLS_PATH"] = settings.ELEVEN_VOICE_POOLS_PATH
    pools = load_voice_pools(settings.ELEVEN_VOICE_POOLS_PATH)

    items = [CatalogItem(id=vid, name=vid, meta={"gender":"male"}) for vid in pools.get("male", [])]
    return CatalogResponse(items=items)


@router.get("/voice/female", response_model=CatalogResponse)
def voice_female():
    from app.pipelines.voice import load_voice_pools
    os.environ["ELEVEN_VOICE_POOLS_PATH"] = settings.ELEVEN_VOICE_POOLS_PATH
    pools = load_voice_pools(settings.ELEVEN_VOICE_POOLS_PATH)

    items = [CatalogItem(id=vid, name=vid, meta={"gender":"female"}) for vid in pools.get("female", [])]
    return CatalogResponse(items=items)


@router.get("/style", response_model=CatalogResponse)
def styles():
    styles_list = ["Cinematic","Explainer","News","Aggressive","Funny","Meme","Serious","Debate","Documentary","Motivational"]
    return CatalogResponse(items=[CatalogItem(id=s.lower(), name=s) for s in styles_list])


@router.get("/template", response_model=CatalogResponse)
def templates():
    from app.pipelines.template import SUPPORTED_TEMPLATES
    return CatalogResponse(items=[CatalogItem(id=k, name=v) for k,v in SUPPORTED_TEMPLATES.items()])


@router.get("/backgroundmusic", response_model=CatalogResponse)
def backgroundmusic():
    try:
        resources = list_folder_resources(prefix=settings.CLOUDINARY_BGM_PREFIX, resource_type="video", max_results=100)
        items=[]
        for r in resources:
            url = r.get("secure_url") or r.get("url")
            items.append(CatalogItem(id=r.get("public_id"), name=r.get("public_id"), meta={"url": url}))
        return CatalogResponse(items=items)
    except Exception:
        return CatalogResponse(items=[])
