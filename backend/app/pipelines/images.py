# app/pipelines/images.py
import os
import time
import base64
import subprocess
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI


def _get_openrouter_key() -> str:
    k = (os.getenv("OPENROUTER_API_KEY") or "").strip().strip('"').strip("'")
    if not k:
        raise ValueError("OPENROUTER_API_KEY missing/empty.")
    return k


def create_placeholder_image(output_path: str, text: str = "Scene") -> None:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "color=c=0x1a1a2e:s=1080x1920:d=1",
        "-vf", f"drawtext=text='{text}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2",
        "-frames:v", "1",
        output_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "color=c=0x1a1a2e:s=1080x1920:d=1",
            "-frames:v", "1",
            output_path
        ], check=True, capture_output=True)


def generate_image_for_scene_keywords(keywords: str, scene_id: str, workdir: str) -> str:
    """
    Generates one image for a scene based on keywords.
    Saves into {workdir}/scene_images/scene_{scene_id}.jpg
    """
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=_get_openrouter_key())

    out_dir = Path(workdir) / "scene_images"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = str((out_dir / f"scene_{scene_id}.jpg").resolve())

    prompt_for_nemotron = (
        "Write a brief 20-word image prompt. Documentary style, no text, no faces. "
        "Indian context only. Topic: " + (keywords or "India")
    )

    try:
        nemotron = client.chat.completions.create(
            model="nvidia/nemotron-3-nano-30b-a3b:free",
            messages=[{"role": "user", "content": prompt_for_nemotron}],
            max_tokens=100
        )
        refined_prompt = nemotron.choices[0].message.content.strip()
    except Exception:
        refined_prompt = f"Documentary photo, Indian context, realistic, no text, no faces. Topic: {keywords}"

    MAX_RETRIES = 3
    ok = False

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model="google/gemini-2.5-flash-image",
                messages=[{"role": "user", "content": refined_prompt}],
                max_tokens=1024,
                extra_body={"modalities": ["image", "text"]}
            )
            msg = resp.choices[0].message
            if hasattr(msg, "images") and msg.images:
                image_data_url = msg.images[0]["image_url"]["url"]
                b64 = image_data_url.split(",")[1]
                img_bytes = base64.b64decode(b64)
                with open(file_path, "wb") as f:
                    f.write(img_bytes)
                ok = True
                break
        except Exception:
            time.sleep(1)

    if not ok:
        create_placeholder_image(file_path, f"Scene {scene_id}")

    return file_path
