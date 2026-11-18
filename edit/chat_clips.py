import json
import os
import re
import subprocess
from collections import Counter

from faster_whisper import WhisperModel

VOD = os.environ["VOD"]
TDL = "tdl/TwitchDownloaderCLI"
OUT = "output"

TOP = 6          # how many clips
BEFORE = 20      # seconds before the spike
AFTER = 10       # seconds after the spike
BUCKET = 10      # chat is counted in 10-second slices
GAP = 90         # min seconds between two clips
MIN_MSGS = 8     # ignore tiny spikes
WORDS_PER = 3

os.makedirs(OUT, exist_ok=True)


def find_vod_id(text):
    m = re.search(r"(\d{6,})", text)
    if not m:
        raise SystemExit("Could not find a VOD id in: " + text)
    return m.group(1)


def get_chat(vod_id):
    subprocess.run(
        [TDL, "chatdownload", "--id", vod_id, "-o", "chat.json"], check=True
    )
    with open("chat.json", encoding="utf-8") as f:
        return json.load(f)["comments"]


def find_moments(comments):
    counts = Counter(int(c["content_offset_seconds"] // BUCKET) for c in comments)
    n = max(counts) + 1
    arr = [counts.get(i, 0) for i in range(n)]
    cands = []
    for i, cnt in enumerate(arr):
        lo, hi = max(0, i - 15), min(n, i + 16)
        window = arr[lo:i] + arr[i + 1 : hi]
        base = sum(window) / len(window) if window else 0
        if cnt >= MIN_MSGS and cnt >= 2.5 * max(base, 1):
            cands.append((cnt / max(base, 1), i * BUCKET, cnt))
    cands.sort(reverse=True)
    picked = []
    for score, t, cnt in cands:
        if all(abs(t - p[1]) >= GAP for p in picked):
            picked.append((score, t, cnt))
        if len(picked) >= TOP:
            break
    return picked


def ass_time(t):
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02}:{s:05.2f}"


def make_ass(model, video, path):
    segments, _ = model.transcribe(video, word_timestamps=True)
    words = [w for seg in segments for w in (seg.words or [])]
    if not words:
        return False
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,DejaVu Sans,72,&H00FFFFFF,&H00FFFFFF,&H00000000,"
        "&H00000000,-1,0,0,0,100,100,0,0,1,5,0,2,60,60,420,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )
    lines = []
    for i in range(0, len(words), WORDS_PER):
        chunk = words[i : i + WORDS_PER]
        text = " ".join(w.word.strip() for w in chunk).upper()
        lines.append(
            f"Dialogue: 0,{ass_time(chunk[0].start)},{ass_time(chunk[-1].end)},"
            f"Default,,0,0,0,,{text}"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n")
    return True


def make_vertical(video, ass_path, out_path, has_caps):
    chain = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:5[bgb];"
        "[fg]scale=1080:-2[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
    )
    if has_caps:
        chain += f",ass={ass_path}"
    chain += "[v]"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video,
            "-filter_complex", chain,
            "-map", "[v]", "-map", "0:a?",
