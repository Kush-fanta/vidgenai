# app/pipelines/render.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from app.settings import settings
from app.services.store import STORE

from app.integrations.cloudinary_storage import is_url, download_url_to_file, upload_path

from .voice import generate_voice
from .images import generate_image_for_scene_keywords, create_placeholder_image
from .video import build_scenes, stitch_final_video
from .template import apply_template_from_state


def render_project_video(project: Dict[str, Any], workdir: str) -> Dict[str, Any]:
    """
    Produces final video + subtitle, uploads to Cloudinary, and returns:
      final_video_url, subtitle_url, plus local paths.
    """
    project_id = project["project_id"]
    workdir_p = Path(workdir).resolve()
    workdir_p.mkdir(parents=True, exist_ok=True)

    scenes = project.get("scenes") or []
    scenes = sorted(scenes, key=lambda s: s.get("order_index", 0))
    if not scenes:
        raise ValueError("No scenes. Call GET /script/{project_id} first.")

    template_id = (project.get("template_id") or "t0").strip()
    tts_lang = project.get("tts_lang") or "en"

    scene_ids = [s["scene_id"] for s in scenes]
    voice_overs = [s.get("text") or "" for s in scenes]

    # -------- Prepare images for ffmpeg (download URLs to local files) --------
    image_files: List[str] = []
    if template_id != "t9":
        img_dir = workdir_p / "scene_images"
        img_dir.mkdir(parents=True, exist_ok=True)

        for s in scenes:
            sid = s["scene_id"]
            url = s.get("image_url")
            local = str((img_dir / f"{sid}.jpg").resolve())

            if url and is_url(url):
                download_url_to_file(url, local)
                image_files.append(local)
                continue

            # if no image_url, generate one (AI if key, else placeholder) and upload
            keywords = s.get("visual_keywords") or s.get("text") or "Scene"
            try:
                if settings.OPENROUTER_API_KEY:
                    generated = generate_image_for_scene_keywords(keywords=keywords, scene_id=sid, workdir=str(workdir_p))
                else:
                    generated = local
                    create_placeholder_image(generated, f"Scene {sid}")
            except Exception:
                generated = local
                create_placeholder_image(generated, f"Scene {sid}")

            # upload generated image to Cloudinary
            folder = f"{settings.CLOUDINARY_FOLDER}/projects/{project_id}/scenes/{sid}/images"
            res = upload_path(
                generated,
                resource_type="image",
                folder=folder,
                public_id="scene_image_auto",
                overwrite=True,
                tags=["vidgenai", project_id, sid, "auto"],
            )
            s["image_url"] = res.get("secure_url") or res.get("url")
            image_files.append(generated)

        # persist updated scene image_url values
        STORE.update_project(project_id, {"scenes": scenes})

    # -------- Voice generation (uploads per-scene audio, returns audio_urls) --------
    state: Dict[str, Any] = {
        "project_id": project_id,
        "workdir": str(workdir_p),
        "tts_lang": tts_lang,

        "voice_mode": project.get("voice_mode") or "female",
        "male_voice_id": project.get("male_voice_id"),
        "female_voice_id": project.get("female_voice_id"),
        "seed": int(project.get("seed") or 42),

        "scene_ids": scene_ids,
        "voice_overs": voice_overs,
        "image_files": image_files,

        "template_id": template_id,
        "gameplay_video_path": project.get("gameplay_video_path"),
        "background_music_path": project.get("background_music_path"),
        "background_music_volume": float(project.get("background_music_volume") or 0.12),
        "output_file": str((workdir_p / "final.mp4").resolve()),
    }

    state = generate_voice(state)

    # attach audio urls to scenes
    audio_urls = state.get("audio_urls") or []
    for i, s in enumerate(scenes):
        if i < len(audio_urls):
            s["audio_url"] = audio_urls[i]
    STORE.update_project(project_id, {"scenes": scenes})

    # -------- Template t9 special: gameplay + audio + subs only --------
    if template_id == "t9":
        state["voice_overs"] = voice_overs
        res = apply_template_from_state(state)  # returns local final + local subtitle
        final_path = res["final_video_path"]
        subtitle_path = res["subtitle_path"]

        # upload outputs
        out_folder = f"{settings.CLOUDINARY_FOLDER}/projects/{project_id}/outputs"
        final_up = upload_path(final_path, resource_type="video", folder=out_folder, public_id="final_video", overwrite=True, tags=["vidgenai", project_id, "final"])
        sub_up = upload_path(subtitle_path, resource_type="raw", folder=out_folder, public_id="subtitle.ass", overwrite=True, tags=["vidgenai", project_id, "subtitle"])

        final_url = final_up.get("secure_url") or final_up.get("url")
        subtitle_url = sub_up.get("secure_url") or sub_up.get("url")

        return {
            "final_video_path": str(Path(final_path).resolve()),
            "subtitle_path": str(Path(subtitle_path).resolve()),
            "final_video_url": final_url,
            "subtitle_url": subtitle_url,
        }

    # -------- Normal pipeline: scenes -> AI video with subs -> template -> BGM --------
    state = build_scenes(state)
    ai_video_path = str((workdir_p / "ai_with_subs.mp4").resolve())
    state = stitch_final_video(state, output_file=ai_video_path)
    state["ai_video_path"] = ai_video_path

    # subtitle generated by stitch
    subtitle_path = state.get("subtitle_path") or str((workdir_p / "subtitle.ass").resolve())
    state["subtitle_path"] = subtitle_path

    # Apply template + BGM
    res = apply_template_from_state(state)
    final_path = res["final_video_path"]

    # Upload final video + subtitle to Cloudinary
    out_folder = f"{settings.CLOUDINARY_FOLDER}/projects/{project_id}/outputs"
    final_up = upload_path(final_path, resource_type="video", folder=out_folder, public_id="final_video", overwrite=True, tags=["vidgenai", project_id, "final"])
    sub_up = upload_path(subtitle_path, resource_type="raw", folder=out_folder, public_id="subtitle.ass", overwrite=True, tags=["vidgenai", project_id, "subtitle"])

    final_url = final_up.get("secure_url") or final_up.get("url")
    subtitle_url = sub_up.get("secure_url") or sub_up.get("url")

    return {
        "final_video_path": str(Path(final_path).resolve()),
        "subtitle_path": str(Path(subtitle_path).resolve()),
        "final_video_url": final_url,
        "subtitle_url": subtitle_url,
    }
