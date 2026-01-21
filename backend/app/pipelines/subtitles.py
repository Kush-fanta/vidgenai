# app/pipelines/subtitles.py
import re
from typing import Any, Dict, List, Optional

def normalize_whisper_lang(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    c = str(code).lower().strip()
    if "-" in c:
        c = c.split("-")[0]
    return c

REGIONAL_LANG_PREFIXES = {"hi","mr","bn","ta","te","gu","kn","ml","or","pa","ur","as"}

def _clean_voiceover_text(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\[[^\]]*\]", "", text).strip()
    t = re.sub(r"\s+", " ", t)
    return t

def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    tokens = text.split()
    cleaned=[]
    for tok in tokens:
        tok2 = tok.strip(" \t\n\r,.;:!?\"'“”‘’()[]{}<>|—–-…।॥")
        if tok2:
            cleaned.append(tok2)
    return cleaned

def _approx_segments(expected_text: str, audio_duration: float) -> List[dict]:
    expected_text=_clean_voiceover_text(expected_text)
    words=_tokenize(expected_text)
    if not words or not audio_duration or audio_duration<=0:
        return []
    weights=[max(1,len(w)) for w in words]
    total=float(sum(weights)) or 1.0
    MIN_D=0.06
    segs=[]; t=0.0
    for w,wt in zip(words,weights):
        d=max(MIN_D, audio_duration*(wt/total))
        start=t; end=min(audio_duration, start+d)
        if end<=start: end=min(audio_duration, start+MIN_D)
        segs.append({"word":w,"start":start,"end":end})
        t=end
    segs[-1]["end"]=max(segs[-1]["end"], audio_duration)
    return segs

def get_whisper_subtitles(audio_path: str, language: Optional[str]=None, expected_text: Optional[str]=None, audio_duration: Optional[float]=None) -> List[dict]:
    lang_norm = normalize_whisper_lang(language)
    if expected_text and audio_duration and lang_norm in REGIONAL_LANG_PREFIXES:
        return _approx_segments(expected_text, audio_duration)

    import whisper
    model = whisper.load_model("base")
    kwargs: Dict[str, Any] = {"word_timestamps": True}
    if language:
        kwargs["language"]=language
        kwargs["task"]="transcribe"
    result = model.transcribe(audio_path, **kwargs)
    out=[]
    for seg in result.get("segments", []):
        for w in seg.get("words", []) or []:
            out.append({"word":w["word"].strip(),"start":w["start"],"end":w["end"]})
    if expected_text and audio_duration and (not out or len(out)<3):
        return _approx_segments(expected_text, audio_duration)
    return out

def escape_ass_text(text: str) -> str:
    return text.replace("\n","\\N")

def format_ass_time(seconds: float) -> str:
    h=int(seconds//3600)
    m=int((seconds%3600)//60)
    s=seconds%60
    return f"{h}:{m:02d}:{s:05.2f}"

def smart_wrap_with_tags(text: str, max_width: int=35) -> str:
    parts=text.split(" ")
    lines=[]; cur=[]; cur_len=0
    for part in parts:
        visible=re.sub(r"\{[^}]*\}","",part)
        L=len(visible)
        if cur_len + L + 1 <= max_width or not cur:
            cur.append(part); cur_len += L+1
        else:
            lines.append(" ".join(cur))
            cur=[part]; cur_len=L+1
    if cur: lines.append(" ".join(cur))
    return "\\N".join(lines)

def generate_combined_ass_subtitles(all_word_segments: List[List[dict]], scene_durations: List[float], output_path: str) -> str:
    HIGHLIGHT="&H00FFFF&"
    NORMAL="&HFFFFFF&"
    header = """[Script Info]
Title: Video Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,52,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,3,1.5,2,40,40,480,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events=[]
    offset=0.0
    for si, segs in enumerate(all_word_segments):
        dur = scene_durations[si] if si < len(scene_durations) else 5.0
        if not segs:
            offset += dur
            continue
        words=[w["word"] for w in segs]
        last_end=max(segs[-1]["end"], dur)

        # intro all white
        first_start=segs[0]["start"]
        if first_start>0.1:
            intro=" ".join(words)
            wrapped=smart_wrap_with_tags(intro,35)
            events.append(f"Dialogue: 0,{format_ass_time(offset)},{format_ass_time(offset+first_start)},Default,,0,0,0,,{escape_ass_text(wrapped)}")

        for i, wd in enumerate(segs):
            st = offset + wd["start"]
            en = offset + (segs[i+1]["start"] if i < len(segs)-1 else last_end)
            if en<=st: en=st+0.1
            colored=[]
            for j,w in enumerate(words):
                if j==i:
                    colored.append(f"{{\\c{HIGHLIGHT}\\b1\\fscx110\\fscy110}}{w.upper()}{{\\c{NORMAL}\\b0\\fscx100\\fscy100}}")
                else:
                    colored.append(w)
            full=" ".join(colored)
            wrapped=smart_wrap_with_tags(full,35)
            events.append(f"Dialogue: 0,{format_ass_time(st)},{format_ass_time(en)},Default,,0,0,0,,{escape_ass_text(wrapped)}")

        offset += dur

    with open(output_path,"w",encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events))
    return output_path
