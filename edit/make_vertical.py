import json
import os
import re
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faster_whisper import WhisperModel
from fetch.twitch_clips import get_clips
from edit.download import download, has_audio
from edit.titles import make_title, make_description, make_tags
from tools.learned import weighted_choice

OUT_DIR = "output"
HOW_MANY = 3

# Options the bot is allowed to test. Add more anytime.
LAYOUTS = {
    "blur": (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:5[bgb];"
        "[fg]scale=1080:-2[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
    ),
    "fill": "[0:v]scale=-2:1920,crop=1080:1920",
    "bars": "[0:v]scale=1080:-2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
}
CAPTION_WORDS = [2, 3, 4]  # words shown at a time


def fmt(t):
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def make_srt(model, video, srt_path, words_per):
    try:
        segments, _ = model.transcribe(video, word_timestamps=True)
        words = [w for seg in segments for w in (seg.words or [])]
    except Exception as e:   # whisper sometimes fails on odd audio: just skip captions for this clip
        print("  captions skipped:", str(e)[:100])
        return False
    if not words:
        return False
    lines = []
    for i in range(0, len(words), words_per):
        chunk = words[i : i + words_per]
        text = " ".join(w.word.strip() for w in chunk).upper()
        lines.append(f"{len(lines) + 1}\n{fmt(chunk[0].start)} --> {fmt(chunk[-1].end)}\n{text}\n")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return True


def hook_font():
    import glob as _g
    for pat in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/**/*Sans*Bold*.ttf",
                "/usr/share/fonts/**/*Bold*.ttf"]:
        found = _g.glob(pat, recursive=True)
        if found:
            return found[0]
    return ""


def make_vertical(video, srt_path, out_path, has_caps, layout, hook=""):
    chain = LAYOUTS[layout]
    # big hook text at the top for the first ~3 seconds (stops the scroll)
    hook = re.sub(r"[^\w\s!?'.,$&-]", "", hook or "").strip().upper()[:40]
    font = hook_font() if hook else ""
    if hook and font:
        words, lines, cur = hook.split(), [], ""
        for w in words:
            if len(cur) + len(w) > 16 and cur:
                lines.append(cur.strip())
                cur = ""
            cur += w + " "
        lines.append(cur.strip())
        hook_file = out_path + ".hook.txt"
        with open(hook_file, "w") as f:
            f.write("\n".join(lines[:2]))
        chain += (f",drawtext=fontfile='{font}':textfile='{hook_file}':fontsize=76:fontcolor=white:"
                  f"borderw=6:bordercolor=black:line_spacing=12:x=(w-text_w)/2:y=230:enable='lt(t,3.2)'")
    if has_caps:
        style = (
            "FontSize=64,Bold=1,Outline=4,Shadow=0,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "Alignment=2,MarginV=420"
        )
        chain += f",subtitles={srt_path}:original_size=1080x1920:force_style='{style}'"
    chain += "[v]"
    cmd = [
        "ffmpeg", "-y", "-i", video,
        "-filter_complex", chain,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-t", "60", out_path,
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    model = WhisperModel("base", device="cpu", compute_type="int8")

    # Clips we already made, so we never make the same one twice
    MADE_FILE = "made_clips.json"
    made = []
    if os.path.exists(MADE_FILE):
        with open(MADE_FILE) as f:
            made = json.load(f)

    new_clips = [c for c in get_clips() if c["id"] not in made]
    print(f"{len(new_clips)} new clips found ({len(made)} already made)")

    for clip in new_clips[:HOW_MANY]:
        print("Working on:", clip["broadcaster_name"], "-", clip["title"])
        src = download(clip)
        if not src:
            print("  download failed, skipping")
            continue

        # AI reads the transcript: trims to the moment (short = more views), hook text + real title
        from tools.judge import polish
        from tools.learned import LEARNED
        from tools.safety import safe_title
        src, verdict = polish(src, model, clip["broadcaster_name"].lower(), "twitch", clip["title"],
                              max_len=LEARNED.get("max_len", 35))
        verdict = verdict or {}
        print("  AI:", verdict.get("score"), "|", verdict.get("hook", ""), "|", verdict.get("title", "(no AI title)"))

        # Pick this video's random options
        layout = weighted_choice(LAYOUTS, "layout_weight")       # favours layouts you rated 👍
        words_per = weighted_choice(CAPTION_WORDS, "words_weight")

        srt = os.path.join(OUT_DIR, f"{clip['id']}.srt")
        has_caps = make_srt(model, src, srt, words_per)
        out = os.path.join(OUT_DIR, f"{clip['id']}_vertical.mp4")
        make_vertical(src, srt, out, has_caps, layout, verdict.get("hook", ""))

        yt_title = safe_title(verdict.get("title") or make_title(clip))
        yt_desc = make_description(clip, yt_title, verdict.get("tags", []))
        info = {
            "youtube_title": yt_title,
            "youtube_description": yt_desc,
            "youtube_tags": make_tags(clip),
            "title": clip["title"],
            "streamer": clip["broadcaster_name"],
            "credit": f"Clip from twitch.tv/{clip['broadcaster_name']}",
            "source_url": clip["url"],
            "views": clip["view_count"],
            "viral_score": clip["score"],
            "captions": has_caps,
            "layout": layout,
            "caption_words": words_per,
            "ai_score": verdict.get("score"), "ai_reason": verdict.get("reason", ""),
            "ai_summary": verdict.get("summary", ""), "ai_tags": verdict.get("tags", []),
            "hook": verdict.get("hook", ""),
            # where this clip sits in the full stream (lets the dashboard re-cut it)
            "platform": "twitch",
            "vod_id": clip.get("video_id") or "",
            "vod_window": ([clip["vod_offset"], clip["vod_offset"] + clip["duration"]]
                           if clip.get("vod_offset") is not None else None),
        }
        with open(os.path.join(OUT_DIR, f"{clip['id']}.json"), "w") as f:
            json.dump(info, f, indent=2)
        # Ready-to-paste text for posting from your phone
        with open(os.path.join(OUT_DIR, f"{clip['id']}_post.txt"), "w", encoding="utf-8") as f:
            f.write(yt_desc)
        print("  done:", out, "| layout:", layout, "| words:", words_per)
        print("  title:", yt_title)

        made.append(clip["id"])
        with open(MADE_FILE, "w") as f:
            json.dump(made, f, indent=2)
