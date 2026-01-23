# app/services/vidgen_service.py
from __future__ import annotations
import os
from difflib import SequenceMatcher
from openai import OpenAI
import json
from typing import Any, Dict, List
from uuid import uuid4

from app.services.store import STORE
from app.settings import settings

from app.pipelines.script_generator import generate_script, sanitize_model_json
from app.pipelines.images import generate_image_for_scene_keywords
from app.integrations.cloudinary_storage import upload_bytes, upload_path


LANG_MAP = {
    "english": "en",
    "hindi": "hi",
    "marathi": "mr",
    "tamil": "ta",
    "telugu": "te",
    "bengali": "bn",
    "gujarati": "gu",
    "kannada": "kn",
    "malayalam": "ml",
    "punjabi": "pa",
    "odia": "or",
    "oriya": "or",
    "assamese": "as",
    "urdu": "ur",
}

def derive_tts_lang(languages: List[str]) -> str:
    if not languages:
        return "en"
    x = str(languages[0]).strip().lower().replace("_", "-")
    if len(x) == 2:
        return x
    if "-" in x and len(x.split("-", 1)[0]) == 2:
        return x.split("-", 1)[0]
    return LANG_MAP.get(x, "en")


class VidGenService:
    def create_project(self, payload: Dict[str, Any]) -> str:
        tts_lang = payload.get("tts_lang") or derive_tts_lang(payload.get("languages") or ["English"])

        doc = {
            "mode": payload["mode"],
            "user_query": payload.get("user_query"),
            "script_text": payload.get("script_text"),

            "languages": payload.get("languages") or ["English"],
            "tts_lang": tts_lang,
            "style": payload.get("style") or "Cinematic",
            "duration_seconds": int(payload.get("duration_seconds") or 60),

            "template_id": payload.get("template_id") or "t0",
            "gameplay_video_path": payload.get("gameplay_video_path"),

            # ✅ voice selection stored
            "voice_mode": payload.get("voice_mode") or "female",
            "male_voice_id": payload.get("male_voice_id"),
            "female_voice_id": payload.get("female_voice_id"),
            "seed": int(payload.get("seed") or 42),

            # backend default (not user input)
            "max_duration_attempts": int(payload.get("max_duration_attempts") or 2),

            "background_music_path": payload.get("background_music_path"),
            "background_music_volume": float(payload.get("background_music_volume") or 0.12),

            "scenes": [],
            "last_video_url": None,
            "last_subtitle_url": None,
        }
        rec = STORE.create_project(doc)
        return rec["project_id"]

    def _ensure_project(self, project_id: str) -> Dict[str, Any]:
        proj = STORE.get_project(project_id)
        if not proj:
            raise ValueError("project_not_found")
        return proj

    def get_or_generate_script(self, project_id: str) -> List[Dict[str, Any]]:
        proj = self._ensure_project(project_id)
        if proj.get("scenes"):
            return proj["scenes"]

        if proj["mode"] == "prompt":
            query = proj.get("user_query") or ""
        else:
            raw = proj.get("script_text") or ""
            query = (
                "Split the following script into multiple short scenes without changing meaning. "
                "Keep the same language/script.\n\nScript:\n" + raw
            )

        state = {
            "user_query": query,
            "languages": proj.get("languages") or ["English"],
            "style": proj.get("style") or "Cinematic",
            "tts_lang": proj.get("tts_lang") or "en",
            "duration_seconds": proj.get("duration_seconds") or 60,
        }

        out = generate_script(state)
        raw_json = sanitize_model_json(out["video_script"])
        data = json.loads(raw_json)

        scenes: List[Dict[str, Any]] = []
        for i, s in enumerate(data.get("video_script", []), start=1):
            scene_id = str(uuid4())
            scenes.append({
                "scene_id": scene_id,
                "order_index": i - 1,
                "text": s.get("voiceover", ""),
                "expected_time_in_seconds": float(s.get("expected_time_in_seconds") or 0) or None,
                "visual_keywords": s.get("visual_keywords"),
                "overlay_text": s.get("overlay_text"),
                "image_url": None,
                "audio_url": None,
            })

        STORE.update_project(project_id, {"scenes": scenes})
        return scenes

    def patch_scene_script(self, project_id: str, scene_id: str, text: str) -> Dict[str, Any]:
        proj = self._ensure_project(project_id)
        scenes = proj.get("scenes") or []
        for s in scenes:
            if s["scene_id"] == scene_id:
                s["text"] = text
                STORE.update_project(project_id, {"scenes": scenes})
                return s
        raise ValueError("scene_not_found")

    def save_uploaded_image(self, project_id: str, scene_id: str, filename: str, content: bytes) -> str:
        proj = self._ensure_project(project_id)
        scenes = proj.get("scenes") or []
        scene = next((x for x in scenes if x["scene_id"] == scene_id), None)
        if not scene:
            raise ValueError("scene_not_found")

        folder = f"{settings.CLOUDINARY_FOLDER}/projects/{project_id}/scenes/{scene_id}/images"
        res = upload_bytes(
            content,
            filename=filename,
            resource_type="image",
            folder=folder,
            public_id="scene_image_upload",
            overwrite=True,
            tags=["vidgenai", project_id, scene_id, "upload"],
        )

        scene["image_url"] = res.get("secure_url") or res.get("url")
        STORE.update_project(project_id, {"scenes": scenes})
        return scene["image_url"]

    def generate_scene_image(self, project_id: str, scene_id: str) -> str:
        proj = self._ensure_project(project_id)
        scenes = proj.get("scenes") or []
        scene = next((x for x in scenes if x["scene_id"] == scene_id), None)
        if not scene:
            raise ValueError("scene_not_found")

        keywords = scene.get("visual_keywords") or scene.get("text") or "Scene"
        workdir = f"outputs/projects/{project_id}/workdir"
        local_img = generate_image_for_scene_keywords(keywords=keywords, scene_id=scene_id, workdir=workdir)

        folder = f"{settings.CLOUDINARY_FOLDER}/projects/{project_id}/scenes/{scene_id}/images"
        res = upload_path(
            local_img,
            resource_type="image",
            folder=folder,
            public_id="scene_image_ai",
            overwrite=True,
            tags=["vidgenai", project_id, scene_id, "ai"],
        )

        scene["image_url"] = res.get("secure_url") or res.get("url")
        STORE.update_project(project_id, {"scenes": scenes})
        return scene["image_url"]

    def regenerate_scene_script(self, project_id: str, scene_id: str) -> Dict[str, Any]:
        proj = self._ensure_project(project_id)
        scenes = proj.get("scenes") or []
        scene = next((x for x in scenes if x["scene_id"] == scene_id), None)
        if not scene:
            raise ValueError("scene_not_found")

        base_text = (scene.get("text") or "").strip()
        if not base_text:
            base_text = "Rewrite this scene."

        # Helper: similarity to avoid “no change” outputs
        def sim(a: str, b: str) -> float:
            a = (a or "").strip()
            b = (b or "").strip()
            if not a or not b:
                return 0.0
            return SequenceMatcher(None, a, b).ratio()

        # We will try at most 2 times
        tries = 2

        # Use project language/style
        tts_lang = proj.get("tts_lang") or "en"
        lang_label = ", ".join(proj.get("languages") or ["English"])
        style = proj.get("style") or "Cinematic"

        # Keep roughly the same duration for this scene, if you have it
        target_sec = scene.get("expected_time_in_seconds") or 8
        try:
            target_sec = int(float(target_sec))
        except Exception:
            target_sec = 8
        if target_sec <= 0:
            target_sec = 8

        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=(os.getenv("OPENROUTER_API_KEY") or "").strip()
        )
        if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
            raise ValueError("OPENROUTER_API_KEY missing/empty.")

        last_err = None

        for attempt in range(1, tries + 1):
            # Stronger instruction on attempt 2
            extra_rule = ""
            if attempt == 2:
                extra_rule = (
                    "\n- IMPORTANT: Do NOT reuse the original phrasing. Paraphrase aggressively. "
                    "Keep meaning, but change wording.\n"
                )

            prompt = f"""
You are rewriting ONE scene for a vertical faceless video.

Rules:
- Output ONLY valid JSON, nothing else.
- Language: {lang_label} (use native script only; no English except proper nouns).
- Target language code: {tts_lang}.
- Approx duration: {target_sec} seconds.
- Include tone tags like [excited], [curious], [laughs] in the voiceover.
{extra_rule}

Return JSON with EXACT keys:
{{
  "voiceover": "...",
  "visual_keywords": "k1, k2, k3",
  "overlay_text": "SHORT TEXT",
  "expected_time_in_seconds": {target_sec}
}}

Original scene (rewrite this):
{base_text}
""".strip()

            try:
                resp = client.chat.completions.create(
                    model="google/gemini-2.5-flash-lite",
                    messages=[
                        {"role": "system", "content": "Return JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=600
                )

                raw = resp.choices[0].message.content
                clean = sanitize_model_json(raw)
                data = json.loads(clean)

            # Robust extraction: try multiple possible keys just in case
                new_voice = (
                    (data.get("voiceover") or "")
                    or (data.get("voice_over") or "")
                    or (data.get("voiceOver") or "")
                    or (data.get("narration") or "")
                    or (data.get("text") or "")
                ).strip()

                new_keywords = (data.get("visual_keywords") or scene.get("visual_keywords") or "").strip()
                new_overlay  = (data.get("overlay_text") or scene.get("overlay_text") or "").strip()
                new_time     = data.get("expected_time_in_seconds", scene.get("expected_time_in_seconds"))

                if not new_voice:
                    raise ValueError("regen_failed_no_voiceover_in_model_output")

            # If it’s basically identical, retry (attempt 2)
                if sim(new_voice, base_text) > 0.90 and attempt < tries:
                    continue

            # ✅ Apply updates (THIS fixes your issue)
                scene["text"] = new_voice
                scene["visual_keywords"] = new_keywords
                scene["overlay_text"] = new_overlay

                try:
                    scene["expected_time_in_seconds"] = float(new_time)
                except Exception:
                    pass

                STORE.update_project(project_id, {"scenes": scenes})
                return scene

            except Exception as e:
                last_err = e

        # If we exhausted retries
        raise ValueError(f"scene_regen_failed: {last_err}")


    def get_last_video_url(self, project_id: str) -> str:
        proj = self._ensure_project(project_id)
        url = proj.get("last_video_url")
        if not url:
            raise ValueError("video_not_ready")
        return url

    def get_last_subtitle_url(self, project_id: str) -> str:
        proj = self._ensure_project(project_id)
        url = proj.get("last_subtitle_url")
        if not url:
            raise ValueError("subtitle_not_ready")
        return url
