# app/pipelines/script_generator.py
import os
import re
import json
from typing import Dict, Any

from dotenv import load_dotenv
load_dotenv()

from langchain_core.prompts import PromptTemplate
from openai import OpenAI


def sanitize_model_json(text: str) -> str:
    if not isinstance(text, str):
        return text
    t = text.strip()
    t = re.sub(r"^\s*```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t).strip()
    start = t.find("{"); end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]
    return t


def _get_openrouter_key() -> str:
    k = (os.getenv("OPENROUTER_API_KEY") or "").strip().strip('"').strip("'")
    if not k:
        raise ValueError("OPENROUTER_API_KEY missing/empty.")
    return k


def generate_script(state: Dict[str, Any]) -> Dict[str, Any]:
    duration_seconds = state.get("duration_seconds", 60)
    try:
        duration_seconds = int(float(duration_seconds))
    except Exception:
        duration_seconds = 60
    if duration_seconds <= 0:
        duration_seconds = 60

    prompt_string = """
You are an expert video script generator for faceless vertical videos (9:16).

TARGET:
- Total spoken duration should be about {duration_seconds} seconds.
- Split into scenes and assign expected_time_in_seconds.

RULES:
- Hook in first 3 seconds
- End with CTA
- Include tone tags in [] (e.g., [excited], [curious], [laughs])
- IMPORTANT: Write voiceover strictly in {languages} (native script). No English except proper nouns.

Output STRICT JSON:
{{
  "metadata": {{
    "language": "{languages}",
    "style": "{style}",
    "target_duration_seconds": {duration_seconds}
  }},
  "video_script": [
    {{
      "scene_id": 1,
      "expected_time_in_seconds": 6,
      "voiceover": "text",
      "visual_keywords": "k1, k2, k3",
      "overlay_text": "TEXT"
    }}
  ]
}}

Query:
{query}
"""

    prompt = PromptTemplate(
        input_variables=["query", "languages", "style", "duration_seconds"],
        template=prompt_string
    )

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=_get_openrouter_key())

    response = client.chat.completions.create(
        model="nvidia/nemotron-3-nano-30b-a3b:free",
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt.format(
                query=state["user_query"],
                languages=", ".join(state.get("languages", [])) if isinstance(state.get("languages"), list) else str(state.get("languages", "")),
                style=str(state.get("style", "")),
                duration_seconds=str(duration_seconds),
            )}
        ]
    )

    script = sanitize_model_json(response.choices[0].message.content)
    return {"video_script": script}
