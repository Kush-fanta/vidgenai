# app/pipelines/voice.py
from __future__ import annotations

import os
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Set, Optional

import requests
from dotenv import load_dotenv
load_dotenv()

from app.settings import settings
from app.integrations.cloudinary_storage import upload_path

ELEVEN_API_KEY = (os.getenv("ELEVEN_API_KEY") or "").strip().strip('"').strip("'")
ELEVEN_OUTPUT_FORMAT = (os.getenv("ELEVEN_OUTPUT_FORMAT") or "mp3_44100_128").strip()
ELEVEN_MODEL_ID = (os.getenv("ELEVEN_MODEL_ID") or "eleven_v3").strip()
ELEVEN_VOICE_POOLS_PATH = (os.getenv("ELEVEN_VOICE_POOLS_PATH") or settings.ELEVEN_VOICE_POOLS_PATH).strip()

TAG_MAP = {"excitedly":"excited","curiously":"curious","giggling":"laughs","laughs":"laughs","dramatically":"excited"}
KNOWN_V3_TAGS = {"laughs","curious","excited","whispers","chuckles","sighs","happily","sad","angry","crying","laughs harder"}


# ---------- pools loader (gender-only) ----------
def _extract_json_object(text: str) -> str:
    t = text.strip()
    start = t.find("{"); end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Could not find JSON object in voice pools file")
    return t[start:end+1]

def _resolve_voice_pools_path(path_str: str) -> Path:
    p = Path((path_str or "").strip())
    if p.is_absolute() and p.exists():
        return p
    pipelines_dir = Path(__file__).resolve().parent
    app_dir = pipelines_dir.parent
    backend_dir = app_dir.parent
    candidates = [
        Path.cwd()/p,
        pipelines_dir/p,
        app_dir/p,
        backend_dir/p,
        pipelines_dir/"voice_pools.json",
        app_dir/"voice_pools.json",
        backend_dir/"voice_pools.json",
        pipelines_dir/"voice_pools.py",
        app_dir/"voice_pools.py",
        backend_dir/"voice_pools.py",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return (Path.cwd()/p).resolve()

def load_voice_pools(path: str) -> Dict[str, List[str]]:
    """
    NEW FORMAT:
      { "male": [ids...], "female": [ids...] }

    Also supports OLD FORMAT by merging if you still have it somewhere.
    """
    resolved = _resolve_voice_pools_path(path)
    if not resolved.exists():
        return {"male": [], "female": []}

    raw = resolved.read_text(encoding="utf-8")
    if resolved.suffix.lower() == ".py":
        raw = _extract_json_object(raw)

    data = json.loads(raw)

    def clean(ids):
        out=[]; seen=set()
        for x in ids or []:
            s=str(x).strip()
            if not s or s=="..." or "..." in s or s.lower() in {"none","null"}:
                continue
            if s not in seen:
                out.append(s); seen.add(s)
        return out

    # new format
    if isinstance(data, dict) and (isinstance(data.get("male"), list) or isinstance(data.get("female"), list)):
        return {"male": clean(data.get("male") or []), "female": clean(data.get("female") or [])}

    # old format fallback
    male_all=[]; female_all=[]
    if isinstance(data, dict):
        for _, gm in data.items():
            if not isinstance(gm, dict):
                continue
            male_all += (gm.get("male") or [])
            female_all += (gm.get("female") or [])
    return {"male": clean(male_all), "female": clean(female_all)}


# ---------- eleven voices availability ----------
def fetch_available_voice_ids(api_key: str) -> Set[str]:
    """
    Source of truth: /v1/voices (supports show_legacy=true).
    """
    r = requests.get(
        "https://api.elevenlabs.io/v3/voices",
        headers={"xi-api-key": api_key},
        params={"show_legacy": "true"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    voices = data.get("voices") or []
    return {v.get("voice_id") for v in voices if v.get("voice_id")}


# ---------- helpers ----------
def apply_v3_audio_tags(text: str) -> str:
    def repl(m):
        inner = m.group(1).strip().lower()
        inner = TAG_MAP.get(inner, inner)
        if inner in KNOWN_V3_TAGS:
            return f"[{inner}]"
        return ""
    out = re.sub(r"\[([^\]]+)\]", repl, text or "")
    out = re.sub(r"\s+"," ",out).strip()
    return out

def get_audio_duration(audio_path: str) -> float:
    cmd = ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",audio_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float((r.stdout or "").strip() or "0")

def _safe_convert(client, **kwargs):
    try:
        return client.text_to_speech.convert(**kwargs)
    except TypeError:
        k2=dict(kwargs); k2.pop("voice_settings",None)
        return client.text_to_speech.convert(**k2)


# ---------- main ----------
def generate_voice(state: Dict[str, Any]) -> Dict[str, Any]:
    if not ELEVEN_API_KEY:
        raise ValueError("Missing ELEVEN_API_KEY")

    voice_overs: List[str] = state.get("voice_overs") or []
    if not voice_overs:
        raise ValueError("voice_overs missing/empty")

    project_id = str(state.get("project_id") or "unknown")
    scene_ids: List[str] = state.get("scene_ids") or [f"scene_{i+1}" for i in range(len(voice_overs))]

    voice_mode = (state.get("voice_mode") or "female").strip().lower()
    male_voice_id = (state.get("male_voice_id") or "").strip()
    female_voice_id = (state.get("female_voice_id") or "").strip()

    available = fetch_available_voice_ids(ELEVEN_API_KEY)

    # ✅ STRICT: require proper IDs
    if voice_mode == "female":
        if not female_voice_id:
            raise ValueError("female_voice_id required when voice_mode=female")
        if female_voice_id not in available:
            raise ValueError(f"female_voice_id not available for this key: {female_voice_id}")

    elif voice_mode == "male":
        if not male_voice_id:
            raise ValueError("male_voice_id required when voice_mode=male")
        if male_voice_id not in available:
            raise ValueError(f"male_voice_id not available for this key: {male_voice_id}")

    elif voice_mode == "both":
        if not male_voice_id or not female_voice_id:
            raise ValueError("male_voice_id and female_voice_id required when voice_mode=both")
        if male_voice_id not in available:
            raise ValueError(f"male_voice_id not available for this key: {male_voice_id}")
        if female_voice_id not in available:
            raise ValueError(f"female_voice_id not available for this key: {female_voice_id}")

    else:
        raise ValueError(f"Invalid voice_mode: {voice_mode}")

    # Eleven client
    try:
        from elevenlabs.client import ElevenLabs
    except Exception:
        from elevenlabs import ElevenLabs
    client = ElevenLabs(api_key=ELEVEN_API_KEY)

    out_dir = Path(state.get("workdir") or ".") / "voice_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # terminal debug
    print(f"[voice] project_id={project_id} voice_mode={voice_mode} male={male_voice_id or None} female={female_voice_id or None}")
    audio_files=[]; audio_durations=[]; audio_urls=[]; used_voice_ids=[]

    for idx, raw in enumerate(voice_overs, start=1):
        if voice_mode == "female":
            vid = female_voice_id
        elif voice_mode == "male":
            vid = male_voice_id
        else:
            # both: alternate scenes always
            vid = male_voice_id if (idx % 2 == 1) else female_voice_id

        used_voice_ids.append(vid)
        print(f"[voice] scene={idx} voice_id={vid}")

        text = apply_v3_audio_tags(raw) if ELEVEN_MODEL_ID=="eleven_v3" else re.sub(r"\[[^\]]*\]","",raw or "")
        local_path = str((out_dir / f"scene{idx}.mp3").resolve())

        audio = _safe_convert(
            client,
            voice_id=vid,
            model_id=ELEVEN_MODEL_ID,
            text=text,
            output_format=ELEVEN_OUTPUT_FORMAT
        )

        with open(local_path, "wb") as f:
            if isinstance(audio, (bytes, bytearray)):
                f.write(audio)
            else:
                for chunk in audio:
                    if chunk:
                        f.write(chunk)

        audio_files.append(local_path)
        audio_durations.append(get_audio_duration(local_path))

        sid = scene_ids[idx-1] if idx-1 < len(scene_ids) else f"scene_{idx}"
        folder = f"{settings.CLOUDINARY_FOLDER}/projects/{project_id}/scenes/{sid}/audio"
        res = upload_path(
            local_path,
            resource_type="video",
            folder=folder,
            public_id="voiceover",
            overwrite=True,
            tags=["vidgenai", project_id, sid, "audio"],
        )
        audio_urls.append(res.get("secure_url") or res.get("url"))

    state["audio_files"] = audio_files
    state["audio_durations"] = audio_durations
    state["audio_total_duration"] = float(sum(audio_durations))
    state["audio_urls"] = audio_urls
    state["used_voice_ids"] = used_voice_ids
    return state
