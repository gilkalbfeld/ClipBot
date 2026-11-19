"""
AI judge: Gemini actually watches + listens to a clip and decides if something big happened.
Returns a score 1-10, a short reason, and where the real moment is inside the clip.

Needs GEMINI_API_KEY (GitHub repo secret). If it's missing or Gemini fails, clips are kept unjudged.
"""
import base64
import json
import os
import subprocess
import tempfile
import time

import requests

MODELS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-2.5-flash"]

def pick_models(api_key, preferred):
    """Google retires model names often — use our favourites if they exist, else any current Flash model."""
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         headers={"x-goog-api-key": api_key}, params={"pageSize": 200}, timeout=20)
        names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception:
        return preferred
    good = [m for m in preferred if m in names]
    flash = sorted([m for m in names if "flash" in m and "lite" not in m and "image" not in m
                    and "tts" not in m and "live" not in m and "preview" not in m], reverse=True)
    return (good + [m for m in flash if m not in good])[:4] or preferred


PROMPT = """You are judging a clip from a {platform} livestream by {streamer} playing GTA 6,
for a YouTube Shorts channel of funny / hype GTA 6 moments. Chat went crazy around {spike_at:.0f}s into this clip.

Watch AND listen. A GREAT clip has a real moment: something funny, shocking, chaotic or impressive happens
in the game AND/OR the streamer reacts big (screaming, laughing hard, freaking out, roasting).
A BAD clip: nothing visible happens, streamer just talking calmly, ad/commercial break, loading screen,
menus, "be right back" screen, or chat hype about something off-screen.

Reply ONLY with JSON:
{{"score": 1-10 (7+ = would go viral-ish, 5 = mid, 1-3 = nothing happens),
  "reason": "max 12 words, what happens",
  "moment_start": seconds where the setup of the moment starts,
  "moment_end": seconds where the reaction/payoff is over,
  "problems": list from ["nothing_happens","calm_talking","ad_break","loading_or_menu","offscreen","too_long_setup","cut_off"]}}"""


def _small_copy(src, dst):
    """360p, low bitrate copy so it fits in one request (and stays fast)."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", "scale=-2:360", "-r", "15",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-c:a", "aac", "-b:a", "48k",
                    "-ac", "1", dst], check=True)


def judge(video, streamer, platform, spike_at):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    with tempfile.TemporaryDirectory() as d:
        small = os.path.join(d, "s.mp4")
        _small_copy(video, small)
        with open(small, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "video/mp4", "data": b64}},
            {"text": PROMPT.format(platform=platform, streamer=streamer, spike_at=spike_at)},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2,
                             "thinkingConfig": {"thinkingBudget": 512}},
    }
    for attempt in range(3):
        for model in pick_models(key, MODELS):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key}, json=body, timeout=120)
            except requests.RequestException:
                continue
            if r.status_code == 400 and "thinking" in r.text.lower():
                body["generationConfig"].pop("thinkingConfig", None)
                continue
            if r.status_code == 200:
                try:
                    out = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                    out["score"] = float(out.get("score", 0))
                    out["model"] = model
                    return out
                except (KeyError, IndexError, ValueError):
                    continue
            if r.status_code == 429:      # free-tier rate limit: wait a bit
                time.sleep(20)
                break
        time.sleep(3)
    return None
