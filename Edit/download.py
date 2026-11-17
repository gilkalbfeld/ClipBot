import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_dlp
from fetch.twitch_clips import get_clips

OUT_DIR = "downloads"
HOW_MANY = 3


def has_audio(path):
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            path,
        ],
        capture_output=True,
        text=True,
    ).stdout
    return "audio" in out


def download(clip):
    os.makedirs(OUT_DIR, exist_ok=True)
    opts = {
        "outtmpl": f"{OUT_DIR}/{clip['id']}.%(ext)s",
        "format": "best",
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([clip["url"]])
    for f in os.listdir(OUT_DIR):
        if f.startswith(clip["id"]):
            return os.path.join(OUT_DIR, f)
    return None


if __name__ == "__main__":
    for clip in get_clips()[:HOW_MANY]:
        print("Downloading:", clip["broadcaster_name"], clip["title"])
        path = download(clip)
        if path:
            print("  saved:", path, "| has audio:", has_audio(path))
        else:
            print("  download failed")
