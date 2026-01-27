# app/pipelines/video.py
import os
import subprocess
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .subtitles import normalize_whisper_lang, get_whisper_subtitles, generate_combined_ass_subtitles

FPS = 60
WIDTH = 1080
HEIGHT = 1920
TRANSITION_DURATION = 1.0
MAX_ZOOM = 1.08
ZOOM_SPEED = 0.7


def get_audio_duration(audio_path: str) -> float:
    cmd = ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",audio_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float((r.stdout or "").strip() or "0")


def combine_scene_with_animation(
    image_path: str,
    audio_path: str,
    output_path: str,
    scene_idx: int,
    tts_lang: Optional[str] = None,
    expected_text: Optional[str] = None,
) -> Tuple[float, List[dict]]:
    audio_duration = get_audio_duration(audio_path)

    video_duration = audio_duration + TRANSITION_DURATION if scene_idx > 0 else audio_duration
    frames = int(video_duration * FPS)
    zoom_frames = int(frames * ZOOM_SPEED)

    start_zoom, end_zoom = random.choice([(1.00, MAX_ZOOM), (MAX_ZOOM, 1.00)])
    zoom_expr = (
        f"if(lte(n\\,{zoom_frames})\\,"
        f"{start_zoom}+({end_zoom-start_zoom})*(1-cos(PI*n/{zoom_frames}))/2\\,"
        f"{end_zoom})"
    )

    lang_for_whisper = normalize_whisper_lang(tts_lang)
    word_segments = get_whisper_subtitles(audio_path, language=lang_for_whisper, expected_text=expected_text, audio_duration=audio_duration)

    vf = (
        f"scale='max({WIDTH},iw)':'max({HEIGHT},ih)',"
        f"scale=iw*({zoom_expr}):ih*({zoom_expr}):eval=frame,"
        f"crop={WIDTH}:{HEIGHT}:(iw-{WIDTH})/2:(ih-{HEIGHT})/2"
    )

    cmd = [
        "ffmpeg","-y",
        "-loop","1","-i",image_path,
        "-i",audio_path,
        "-vf",vf,
        "-t",str(video_duration),
        "-r",str(FPS),
        "-pix_fmt","yuv420p",
        "-c:v","libx264","-preset","fast","-crf","23",
        "-c:a","aac","-b:a","192k",
        output_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return audio_duration, word_segments


def build_scenes(state: Dict[str, Any]) -> Dict[str, Any]:
    workdir = Path(state.get("workdir") or ".")
    video_dir = workdir / "scene_videos"
    video_dir.mkdir(parents=True, exist_ok=True)

    audio_files: List[str] = state.get("audio_files") or []
    image_files: List[str] = state.get("image_files") or []
    voice_overs: List[str] = state.get("voice_overs") or []
    total = min(len(audio_files), len(image_files))

    scene_videos=[]; scene_durations=[]; all_word_segments=[]
    for i in range(total):
        out_path = str((video_dir / f"scene_{i+1}.mp4").resolve())
        expected_text = voice_overs[i] if i < len(voice_overs) else None
        dur, segs = combine_scene_with_animation(
            image_path=image_files[i],
            audio_path=audio_files[i],
            output_path=out_path,
            scene_idx=i,
            tts_lang=state.get("tts_lang","en"),
            expected_text=expected_text
        )
        scene_videos.append(out_path)
        scene_durations.append(dur)
        all_word_segments.append(segs)

    state["scene_videos"]=scene_videos
    state["scene_durations"]=scene_durations
    state["all_word_segments"]=all_word_segments
    return state


def stitch_final_video(state: Dict[str, Any], output_file: str) -> Dict[str, Any]:
    workdir = Path(state.get("workdir") or ".")
    scene_videos: List[str] = state.get("scene_videos") or []
    scene_durations: List[float] = state.get("scene_durations") or []
    all_word_segments: List[List[dict]] = state.get("all_word_segments") or []

    if not scene_videos:
        raise ValueError("No scene videos to stitch")

    temp_out = str((workdir / "temp_stitched.mp4").resolve())

    if len(scene_videos) == 1:
        subprocess.run(["ffmpeg","-y","-i",scene_videos[0],"-c","copy",temp_out], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        inputs=[]
        for clip in scene_videos:
            inputs += ["-i", clip]

        filter_complex=""
        prev="0:v"
        cumulative = scene_durations[0] if scene_durations else 0.0

        for i in range(1, len(scene_videos)):
            cur=f"v{i}"
            offset=cumulative - TRANSITION_DURATION
            filter_complex += f"[{prev}][{i}:v]xfade=transition=fade:duration={TRANSITION_DURATION}:offset={offset}[{cur}];"
            prev=cur
            if i < len(scene_durations):
                cumulative += scene_durations[i]

        audio_labels=[]
        for i in range(len(scene_videos)):
            dur = scene_durations[i] if i < len(scene_durations) else 5.0
            al=f"a{i}"
            filter_complex += f"[{i}:a]atrim=0:{dur},asetpts=PTS-STARTPTS[{al}];"
            audio_labels.append(f"[{al}]")
        filter_complex += f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[aout]"

        cmd=["ffmpeg","-y"]+inputs+[
            "-filter_complex",filter_complex,
            "-map",f"[{prev}]",
            "-map","[aout]",
            "-r",str(FPS),
            "-pix_fmt","yuv420p",
            "-c:v","libx264","-preset","fast","-crf","23",
            "-c:a","aac","-b:a","192k",
            temp_out
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # write subtitle file always into workdir
    subtitle_path = str((workdir / "subtitle.ass").resolve())
    generate_combined_ass_subtitles(all_word_segments, scene_durations, subtitle_path)
    state["subtitle_path"] = subtitle_path

    # ✅ NO subtitle burning - produce clean video
    # Just copy the stitched video to output (or rename if single scene)
    if temp_out != output_file:
        try:
            os.rename(temp_out, output_file)
        except OSError:
            # If rename fails (cross-device), copy instead
            import shutil
            shutil.copy2(temp_out, output_file)
            try:
                os.remove(temp_out)
            except OSError:
                pass

    return state
