# app/pipelines/template.py
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.integrations.cloudinary_storage import is_url, download_url_to_file

from .subtitles import normalize_whisper_lang, get_whisper_subtitles, generate_combined_ass_subtitles

W, H = 1080, 1920

SUPPORTED_TEMPLATES = {
    "t0": "NO TEMPLATE (AI video only)",
    "t1": "50/50 TOP=AI BOTTOM=GAMEPLAY",
    "t2": "50/50 TOP=GAMEPLAY BOTTOM=AI",
    "t3": "60/40 TOP=AI BOTTOM=GAMEPLAY",
    "t4": "60/40 TOP=GAMEPLAY BOTTOM=AI",
    "t5": "70/30 TOP=AI BOTTOM=GAMEPLAY",
    "t6": "70/30 TOP=GAMEPLAY BOTTOM=AI",
    "t7": "GAMEPLAY BG + AI PIP",
    "t9": "GAMEPLAY + AI AUDIO + SUBS (NO AI VIDEO)",
}

FPS = 60

def require_bin(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required binary '{name}' not found on PATH.")

def run_ffmpeg(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True)

def ffprobe_duration(path: str) -> float:
    cmd = ["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",path]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)

def ffprobe_has_audio(path: str) -> bool:
    try:
        cmd = ["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=index","-of","csv=p=0",path]
        out = subprocess.check_output(cmd, text=True).strip()
        return bool(out)
    except Exception:
        return False

def escape_ass_path(p: str) -> str:
    ap = str(Path(p).resolve()).replace("\\","/")
    ap = ap.replace(":","\\:")
    ap = ap.replace("'","\\'")
    return ap

def fit_cover(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}"

def split_heights(ratio_top: float) -> Tuple[int,int]:
    top_h = int(round(H*ratio_top))
    return top_h, H-top_h

def build_filter_split(top_is_ai: bool, ratio_top: float) -> str:
    top_h, bot_h = split_heights(ratio_top)
    ai_top = f"[1:v]{fit_cover(W, top_h)}[ai_top]"
    ai_bot = f"[1:v]{fit_cover(W, bot_h)}[ai_bot]"
    gp_top = f"[0:v]{fit_cover(W, top_h)}[gp_top]"
    gp_bot = f"[0:v]{fit_cover(W, bot_h)}[gp_bot]"
    if top_is_ai:
        return ";".join([ai_top, gp_bot, "[ai_top][gp_bot]vstack=inputs=2[v]"])
    return ";".join([gp_top, ai_bot, "[gp_top][ai_bot]vstack=inputs=2[v]"])

def build_filter_pip_gameplay_bg() -> str:
    pip_w, pip_h = 720, 1280
    pip_x = (W - pip_w)//2
    pip_y = 60
    bg = f"[0:v]{fit_cover(W,H)}[bg]"
    ov = f"[1:v]{fit_cover(pip_w,pip_h)}[ov]"
    bordered = "[ov]pad=w=iw+12:h=ih+12:x=6:y=6:color=white[pip]"
    overlay = f"[bg][pip]overlay=x={pip_x}:y={pip_y}[v]"
    return ";".join([bg, ov, bordered, overlay])

def concat_audio_files(audio_files: List[str], out_audio_path: str) -> str:
    if not audio_files:
        raise ValueError("concat_audio_files: empty")
    list_path = out_audio_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in audio_files:
            pn = str(Path(p).resolve()).replace("\\","/")
            pn = pn.replace("'","'\\''")
            f.write(f"file '{pn}'\n")
    cmd = ["ffmpeg","-y","-f","concat","-safe","0","-i",list_path,"-c:a","libmp3lame","-b:a","192k",out_audio_path]
    run_ffmpeg(cmd)
    try: os.remove(list_path)
    except OSError: pass
    return out_audio_path

def generate_ass_from_audio(audio_files: List[str], voice_overs: List[str], tts_lang: str, out_ass_path: str) -> float:
    scene_durations=[]; all_word_segments=[]
    lang_for_whisper = normalize_whisper_lang(tts_lang)
    for i, ap in enumerate(audio_files):
        dur = ffprobe_duration(ap)
        scene_durations.append(dur)
        expected = voice_overs[i] if i < len(voice_overs) else None
        segs = get_whisper_subtitles(ap, language=lang_for_whisper, expected_text=expected, audio_duration=dur)
        all_word_segments.append(segs)
    generate_combined_ass_subtitles(all_word_segments, scene_durations, out_ass_path)
    return float(sum(scene_durations))

def mix_bgm_into_video_inplace(video_path: str, bgm_local_path: str, volume: float) -> str:
    require_bin("ffmpeg"); require_bin("ffprobe")
    duration = ffprobe_duration(video_path)
    has_audio = ffprobe_has_audio(video_path)

    try: vol=float(volume)
    except Exception: vol=0.12
    vol=max(0.0, min(vol, 2.0))

    tmp_out = str(Path(video_path).with_suffix(".bgm_tmp.mp4"))

    if has_audio:
        fc = (
            f"[1:a]volume={vol},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[bgm];"
            f"[0:a]asetpts=PTS-STARTPTS[voice];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
    else:
        fc = f"[1:a]volume={vol},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[aout]"

    cmd = ["ffmpeg","-y","-i",video_path,"-stream_loop","-1","-i",bgm_local_path,
           "-filter_complex",fc,"-map","0:v","-map","[aout]","-t",f"{duration:.3f}",
           "-c:v","copy","-c:a","aac","-b:a","192k",tmp_out]
    try:
        run_ffmpeg(cmd)
    except subprocess.CalledProcessError:
        cmd2 = ["ffmpeg","-y","-i",video_path,"-stream_loop","-1","-i",bgm_local_path,
                "-filter_complex",fc,"-map","0:v","-map","[aout]","-t",f"{duration:.3f}",
                "-c:v","libx264","-preset","fast","-crf","18","-c:a","aac","-b:a","192k",tmp_out]
        run_ffmpeg(cmd2)

    try: os.remove(video_path)
    except OSError: pass
    os.rename(tmp_out, video_path)
    return video_path

def apply_template_to_ai_video(template_id: str, gameplay_local: str, ai_video_local: str, out_path: str) -> str:
    duration = ffprobe_duration(ai_video_local)

    if template_id == "t1": fc = build_filter_split(True,0.5)
    elif template_id == "t2": fc = build_filter_split(False,0.5)
    elif template_id == "t3": fc = build_filter_split(True,0.6)
    elif template_id == "t4": fc = build_filter_split(False,0.6)
    elif template_id == "t5": fc = build_filter_split(True,0.7)
    elif template_id == "t6": fc = build_filter_split(False,0.7)
    elif template_id == "t7": fc = build_filter_pip_gameplay_bg()
    else: raise ValueError(f"Unknown template: {template_id}")

    cmd = ["ffmpeg","-y","-stream_loop","-1","-i",gameplay_local,"-i",ai_video_local,
           "-filter_complex",fc,"-map","[v]","-map","1:a?","-t",f"{duration:.3f}",
           "-r",str(FPS),"-pix_fmt","yuv420p","-c:v","libx264","-preset","veryfast","-crf","20",
           "-c:a","aac","-b:a","192k",out_path]
    run_ffmpeg(cmd)
    return out_path

def apply_template_9(workdir: str, gameplay_local: str, audio_files: List[str], voice_overs: List[str], tts_lang: str, out_path: str) -> Tuple[str,str]:
    wd = Path(workdir).resolve()
    wd.mkdir(parents=True, exist_ok=True)

    temp_dir = wd / "template9"
    temp_dir.mkdir(parents=True, exist_ok=True)

    combined_audio = str((temp_dir / "combined_audio.mp3").resolve())
    combined_audio = concat_audio_files(audio_files, combined_audio)
    audio_duration = ffprobe_duration(combined_audio)

    subtitle_path = str((wd / "subtitle.ass").resolve())
    generate_ass_from_audio(audio_files, voice_overs, tts_lang, subtitle_path)

    sp = escape_ass_path(subtitle_path)
    vf = f"{fit_cover(W,H)},ass='{sp}'"

    cmd = ["ffmpeg","-y","-stream_loop","-1","-i",gameplay_local,"-i",combined_audio,
           "-vf",vf,"-map","0:v","-map","1:a","-t",f"{audio_duration:.3f}",
           "-r",str(FPS),"-pix_fmt","yuv420p","-c:v","libx264","-preset","fast","-crf","18",
           "-c:a","aac","-b:a","192k",out_path]
    run_ffmpeg(cmd)
    return out_path, subtitle_path

def apply_template_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    require_bin("ffmpeg"); require_bin("ffprobe")

    template_id = str(state.get("template_id") or "t0").strip()
    if template_id not in SUPPORTED_TEMPLATES:
        raise ValueError(f"Unknown template_id={template_id}")

    workdir = str(state.get("workdir") or Path.cwd())
    wd = Path(workdir).resolve()
    wd.mkdir(parents=True, exist_ok=True)

    output_file = str(Path(state.get("output_file") or (wd/"final.mp4")).resolve())

    bgm_path = state.get("background_music_path")
    bgm_vol = float(state.get("background_music_volume") or 0.12)

    # download BGM if URL
    bgm_local = None
    if bgm_path and str(bgm_path).strip().lower() not in {"none","null","","string"}:
        bp = str(bgm_path).strip()
        if is_url(bp):
            bgm_local = download_url_to_file(bp, str((wd/"bgm.mp3").resolve()))
        else:
            bgm_local = str(Path(bp).resolve())

    if template_id == "t9":
        gameplay = str(state.get("gameplay_video_path") or "").strip()
        if not gameplay:
            raise ValueError("t9 requires gameplay_video_path")
        if is_url(gameplay):
            gameplay_local = download_url_to_file(gameplay, str((wd/"gameplay.mp4").resolve()))
        else:
            gameplay_local = str(Path(gameplay).resolve())

        final_path, subtitle_path = apply_template_9(
            workdir=workdir,
            gameplay_local=gameplay_local,
            audio_files=state.get("audio_files") or [],
            voice_overs=state.get("voice_overs") or [],
            tts_lang=str(state.get("tts_lang") or "en"),
            out_path=output_file
        )

        if bgm_local:
            mix_bgm_into_video_inplace(final_path, bgm_local, bgm_vol)
        return {"final_video_path": final_path, "subtitle_path": subtitle_path}

    if template_id == "t0":
        ai_video = str(state.get("ai_video_path") or "").strip()
        if not ai_video:
            raise ValueError("t0 requires ai_video_path")
        ai_video_local = str(Path(ai_video).resolve())
        shutil.copy2(ai_video_local, output_file)
        if bgm_local:
            mix_bgm_into_video_inplace(output_file, bgm_local, bgm_vol)
        return {"final_video_path": output_file, "subtitle_path": state.get("subtitle_path")}

    # t1..t7 need gameplay + ai video
    gameplay = str(state.get("gameplay_video_path") or "").strip()
    if not gameplay:
        raise ValueError(f"{template_id} requires gameplay_video_path")

    ai_video = str(state.get("ai_video_path") or "").strip()
    if not ai_video:
        raise ValueError(f"{template_id} requires ai_video_path")

    if is_url(gameplay):
        gameplay_local = download_url_to_file(gameplay, str((wd/"gameplay.mp4").resolve()))
    else:
        gameplay_local = str(Path(gameplay).resolve())

    ai_video_local = str(Path(ai_video).resolve())

    final_path = apply_template_to_ai_video(template_id, gameplay_local, ai_video_local, output_file)
    if bgm_local:
        mix_bgm_into_video_inplace(final_path, bgm_local, bgm_vol)
    return {"final_video_path": final_path, "subtitle_path": state.get("subtitle_path")}
