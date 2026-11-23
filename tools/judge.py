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

LAST_ERROR = {"text": ""}   # why the last judge() call failed (for logs)

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
    ok = [m for m in names if "flash" in m and not any(x in m for x in ("image", "tts", "live", "audio", "embed"))]
    flash = sorted([m for m in ok if "lite" not in m and "preview" not in m], reverse=True)
    lite = sorted([m for m in ok if "lite" in m and "preview" not in m], reverse=True)
    # full models first, then lighter "lite" ones (less busy when Google is overloaded)
    out = good + [m for m in flash if m not in good][:2] + lite[:2]
    return out or preferred


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
  "problems": list from ["nothing_happens","calm_talking","ad_break","loading_or_menu","offscreen","too_long_setup","cut_off"],
  "title": "YouTube Shorts title about what ACTUALLY happens in this clip. Specific, punchy, max 70 chars,
            curiosity hook, streamer's name ({streamer_nick}), 1 emoji at the end. Don't spoil the payoff.
            Avoid generic templates like 'can't believe what happened' or 'was NOT ready'.",
  "summary": "2-3 plain sentences describing exactly what happens: characters (e.g. Jason, Lucia), places,
              vehicles, actions, what the streamer says/does. Used for searching clips later.",
  "tags": ["5-8 short search tags about the content, e.g. 'fishing', 'police chase', 'lucia', 'boat'"],
  "hook": "3-6 word ALL CAPS on-screen hook for the first second, no emojis, e.g. HE WAS NOT READY"}}"""


def nick(streamer):
    try:
        from edit.titles import NICKNAMES
        return NICKNAMES.get(streamer.lower(), streamer)
    except Exception:
        return streamer


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
            {"text": PROMPT.format(platform=platform, streamer=streamer, spike_at=spike_at,
                                   streamer_nick=nick(streamer))},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2,
                             "mediaResolution": "MEDIA_RESOLUTION_LOW",   # ~4x fewer tokens per frame (free tier)
                             "thinkingConfig": {"thinkingBudget": 512}},
    }
    for attempt in range(3):
        for model in pick_models(key, MODELS):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key}, json=body, timeout=120)
            except requests.RequestException as e:
                LAST_ERROR["text"] = f"{model}: {str(e)[:120]}"
                continue
            if r.status_code == 400 and "thinking" in r.text.lower():
                body["generationConfig"].pop("thinkingConfig", None)
                continue
            if r.status_code == 400 and "media" in r.text.lower():
                body["generationConfig"].pop("mediaResolution", None)
                continue
            if r.status_code == 200:
                try:
                    out = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                    out["score"] = float(out.get("score", 0))
                    out["model"] = model
                    return out
                except (KeyError, IndexError, ValueError):
                    continue
            LAST_ERROR["text"] = f"{model}: {r.status_code} " + " ".join(r.text.split())[:300]
            if r.status_code == 429:      # free-tier rate limit: wait a bit
                time.sleep(20)
                break
        time.sleep(3)
    return None


TEXT_PROMPT = """You are writing for ViceClips, a YouTube Shorts channel of funny / hype GTA 6 moments from streamers.
Below is the transcript of a ~50 second clip from {streamer_nick}'s {platform} stream (GTA 6). Chat went crazy during it.
Stream title: {stream_title}

Transcript (with seconds):
{transcript}

{want_line}
Based on what the streamer says and reacts to, reply ONLY with JSON:
{{"match": 0-10 (how well it fits what the owner is looking for; 10 if no request),
  "score": 1-10 (how funny/hype this moment probably is; 7+ great, 5 mid, 1-3 nothing happens / calm talking),
  "reason": "max 12 words, what happens",
  "title": "YouTube Shorts title about what ACTUALLY happens in THIS clip — use a specific detail from the
            transcript (a quote, a character, a car, a place, the mistake, the target). Max 65 chars, include
            {streamer_nick}, 1 emoji at the end, curiosity hook, don't spoil the payoff.
            BANNED phrases: 'loses his mind', 'can't believe', 'was NOT ready', 'found something crazy',
            'goes crazy', 'freaks out', 'insane moment', 'you won't believe'.
            Vary the style: a quote ("\"I'm NOT paying that\" — Kai Cenat 💀"), a situation
            ("Kai Cenat tried to rob a gas station with a fishing rod 🎣"), a question
            ("Why did CaseOh just drive into the ocean? 🌊"), or a POV.
            Don't reuse these recent titles' wording: {avoid}",
  "summary": "2-3 plain sentences on what happens (characters like Jason/Lucia, places, cars, actions, quotes). For search.",
  "tags": ["5-8 short search tags"],
  "moment_start": seconds (from the transcript times) where the setup of the best moment starts,
  "moment_end": seconds where the reaction/payoff is over,
  "hook": "3-6 word ALL CAPS on-screen hook for the first second, no emojis, e.g. HE WAS NOT READY"}}"""


def judge_text(transcript, streamer, platform="twitch", stream_title="", avoid=(), want=""):
    """Cheaper judge: reads the transcript instead of watching the video (works when video quota is used up)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not transcript.strip():
        return None
    body = {
        "contents": [{"parts": [{"text": TEXT_PROMPT.format(
            streamer_nick=nick(streamer), platform=platform, stream_title=stream_title or "?",
            transcript=transcript[:6000], avoid=json.dumps(list(avoid)[-12:]),
            want_line=(f"The owner is specifically looking for: \"{want}\". Judge how well this clip matches."
                       if want else ""))}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9,
                             "thinkingConfig": {"thinkingBudget": 256}},
    }
    models = pick_models(key, MODELS)
    models = [m for m in models if "lite" in m] + [m for m in models if "lite" not in m]  # lite = more free quota
    for attempt in range(3):
        for model in models:
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key}, json=body, timeout=60)
            except requests.RequestException as e:
                LAST_ERROR["text"] = f"{model}: {str(e)[:120]}"
                continue
            if r.status_code == 400 and "thinking" in r.text.lower():
                body["generationConfig"].pop("thinkingConfig", None)
                continue
            if r.status_code == 200:
                try:
                    out = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                    out["score"] = float(out.get("score", 0))
                    out["model"] = model + " (transcript)"
                    return out
                except (KeyError, IndexError, ValueError):
                    continue
            LAST_ERROR["text"] = f"{model}: {r.status_code} " + " ".join(r.text.split())[:300]
            if r.status_code == 429:
                continue      # try the next model, each has its own free quota
        time.sleep(10)
    return None


def transcribe(video, model=None):
    """Transcript with timestamps, e.g. '[12s] bro no way'."""
    from faster_whisper import WhisperModel
    model = model or WhisperModel("base", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(video, vad_filter=True)
    return "\n".join(f"[{int(s.start)}s] {s.text.strip()}" for s in segs)


def trim(src, verdict, max_len=35, pad_before=2.0, pad_after=2.5):
    """Cut the clip down to the real moment, at most max_len seconds (short Shorts keep viewers)."""
    import subprocess as sp
    try:
        dur = float(sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                           capture_output=True, text=True).stdout.strip())
    except ValueError:
        return src
    ms, me = (verdict or {}).get("moment_start"), (verdict or {}).get("moment_end")
    if isinstance(ms, (int, float)) and isinstance(me, (int, float)) and me > ms:
        a, b = max(0, ms - pad_before), min(dur, me + pad_after)
    else:
        a, b = 0, dur
    if b - a > max_len:          # too long: keep the end (the payoff) and the lead-up right before it
        a = b - max_len
    if b - a < 8:                # too short to make sense: widen
        a, b = max(0, b - 12), min(dur, b + 2)
    if a <= 0.5 and b >= dur - 0.5:
        return src
    out = src.rsplit(".", 1)[0] + "_trim.mp4"
    r = sp.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{a:.2f}", "-to", f"{b:.2f}", "-i", src,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", out])
    return out if r.returncode == 0 else src


def polish(src, model, streamer, platform="twitch", stream_title="", avoid=(), verdict=None, max_len=35):
    """One call for every clip: AI review (if not done), trim to the moment, and return (new_src, verdict)."""
    if not verdict:
        verdict = judge_text(transcribe(src, model), streamer, platform, stream_title, avoid)
    return trim(src, verdict, max_len), verdict
