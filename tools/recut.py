"""
Re-cuts an existing clip from the saved stream (Twitch VOD / YouTube replay) with a new start/end.
Replaces the clip's video, thumbnail and info in place, so it stays the same clip on the dashboard.

Env: CLIP_ID, START_SHIFT (seconds, negative = start earlier), END_SHIFT (seconds, positive = longer)
Runs in GitHub Actions (needs gh, ffmpeg, yt-dlp, Twitch secrets).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

LATENCY = 5        # seconds the live recording runs behind the broadcast
OLD_BEFORE, OLD_AFTER, CUT_DELAY = 40, 12, 16   # settings used before clips stored their window


def gh(*args, **kw):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, **kw).stdout


def find_clip(cid, d):
    for tag in ["live-clips", "clips"]:
        r = subprocess.run(["gh", "release", "download", tag, "-p", f"{cid}.json", "-D", d, "--clobber"],
                           capture_output=True)
        if r.returncode == 0:
            with open(os.path.join(d, f"{cid}.json")) as f:
                return tag, json.load(f)
    # early clips have no info file — rebuild the basics from the clip's name
    for tag in ["live-clips", "clips"]:
        names = gh("release", "view", tag, "--json", "assets", "-q", ".assets[].name").split()
        m = re.match(r"(.+)_\d{8}_\d{6}$", cid)
        if f"{cid}_vertical.mp4" in names and m:
            name = m.group(1)
            return tag, {"streamer": name, "platform": "youtube" if name == "ishowspeed" else "twitch",
                         "layout": "blur", "caption_words": 3,
                         "source_url": f"https://www.twitch.tv/{name}"}
    sys.exit(f"Clip {cid} not found")


def ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def twitch_vod_for(login, t):
    """The Twitch VOD that was recording at time t, and its start time."""
    from fetch.twitch_clips import get_token, CLIENT_ID
    h = {"Client-Id": CLIENT_ID, "Authorization": f"Bearer {get_token()}"}
    u = requests.get("https://api.twitch.tv/helix/users", headers=h, params={"login": login}).json()["data"][0]
    vids = requests.get("https://api.twitch.tv/helix/videos", headers=h,
                        params={"user_id": u["id"], "type": "archive", "first": 20}).json()["data"]
    for v in vids:
        start = ts(v["created_at"])
        m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", v["duration"])
        length = sum(int(x or 0) * k for x, k in zip(m.groups(), (3600, 60, 1)))
        if start <= t <= start + length + 600:
            return v["id"], start
    sys.exit(f"No saved stream (VOD) found for {login} at that time — it may be deleted or sub-only.")


def main():
    cid = os.environ["CLIP_ID"]
    shift_start = float(os.environ.get("START_SHIFT", "0"))
    shift_end = float(os.environ.get("END_SHIFT", "0"))

    with tempfile.TemporaryDirectory() as d:
        tag, info = find_clip(cid, d)

        # 1) where is the clip in the full stream?
        if info.get("vod_id") and info.get("vod_window"):
            vod_url = f"https://www.twitch.tv/videos/{info['vod_id']}"
            w0, w1 = info["vod_window"]
        else:
            if info.get("window_utc"):
                a, b = info["window_utc"]
            else:   # older live clips: work it out from the clip's timestamp
                m = re.search(r"_(\d{8}_\d{6})$", cid)
                cut = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc).timestamp()
                spike = cut - CUT_DELAY
                a, b = spike - OLD_BEFORE, spike + OLD_AFTER
            if info.get("platform") == "youtube":
                vod_url = info["source_url"]
                start = float(subprocess.run(["yt-dlp", "--print", "%(release_timestamp)s", vod_url],
                                             capture_output=True, text=True).stdout.strip() or 0)
            else:
                vid, start = twitch_vod_for(info["streamer"], a)
                vod_url = f"https://www.twitch.tv/videos/{vid}"
                info["vod_id"] = vid
            w0, w1 = a - start - LATENCY, b - start - LATENCY

        # 2) apply your adjustment
        n0, n1 = max(0, w0 + shift_start), w1 + shift_end
        if n1 - n0 < 8:
            n1 = n0 + 8
        n1 = min(n1, n0 + 60)
        print(f"Re-cutting {cid}: {w0:.0f}-{w1:.0f}s -> {n0:.0f}-{n1:.0f}s of {vod_url}")

        raw = os.path.join(d, "raw.mp4")
        subprocess.run(["yt-dlp", "-q", "-f", "best[height<=1080]/best", "--download-sections",
                        f"*{n0:.1f}-{n1:.1f}", "--force-keyframes-at-cuts", "-o", raw, vod_url], check=True)

        # 3) render it the same way as before
        from faster_whisper import WhisperModel
        from edit.make_vertical import make_srt, make_vertical
        from edit.download import has_audio
        model = WhisperModel("base", device="cpu", compute_type="int8")
        layout = info.get("layout", "blur")
        words = info.get("caption_words", 3)
        srt = os.path.join(d, "c.srt")
        caps = has_audio(raw) and make_srt(model, raw, srt, words)
        out = os.path.join(d, f"{cid}_vertical.mp4")
        make_vertical(raw, srt, out, caps, layout)
        thumb = os.path.join(d, f"{cid}_thumb.jpg")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "2", "-i", out, "-frames:v", "1",
                        "-vf", "crop=iw:iw*3/4:0:(ih-iw*3/4)/2,scale=640:-2", "-q:v", "4", thumb], check=True)

        info["vod_window"] = [n0, n1]
        info["recut_count"] = info.get("recut_count", 0) + 1
        jpath = os.path.join(d, f"{cid}.json")
        with open(jpath, "w") as f:
            json.dump(info, f, indent=2)

        # 4) replace the old files
        gh("release", "upload", tag, out, thumb, jpath, "--clobber")
        print(f"✅ {cid} re-cut ({n1 - n0:.0f}s long)")


if __name__ == "__main__":
    main()
