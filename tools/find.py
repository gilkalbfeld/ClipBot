"""
🔎 Find clips on request: "5 clips of police chases", "streamer rages after dying", or paste links.

1. Any links in the request (Twitch clip, Twitch VOD with ?t=, other sites) are clipped directly.
2. Otherwise: grab hundreds of recent GTA clips from Twitch, let the AI shortlist the ones whose
   titles/streamers fit, then read each shortlisted clip's transcript and keep the best matches.
3. Matches are rendered into Shorts and land in New Clips.

Env: QUERY, COUNT (default 5). Runs in GitHub Actions.
"""
import json
import os
import random
import re
import time
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests  # noqa: E402

import fetch.twitch_clips as tw  # noqa: E402
from tools.judge import MODELS, pick_models, judge_text, transcribe  # noqa: E402
from tools.learned import weighted_choice  # noqa: E402

QUERY = os.environ.get("QUERY", "").strip()
COUNT = max(1, min(10, int(os.environ.get("COUNT", "5") or 5)))
OUT = "output"
KEY = os.environ.get("GEMINI_API_KEY", "")
MADE = []


def gemini(prompt):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3}}
    for model in sorted(pick_models(KEY, MODELS), key=lambda m: "lite" not in m):
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          headers={"x-goog-api-key": KEY}, json=body, timeout=120)
        if r.status_code == 200:
            try:
                return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            except (KeyError, ValueError):
                continue
    return None


def render(src, streamer, url, verdict, source_type, model, extra=None):
    """Same look as the other clips: vertical, captions, AI title, thumbnail, post text."""
    from edit.make_vertical import LAYOUTS, CAPTION_WORDS, make_srt, make_vertical
    from edit.download import has_audio
    from edit.titles import make_title, make_description, make_tags
    time.sleep(1.1)   # ids are name_date_time, keep them unique
    cid = f"{streamer}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    from tools.judge import trim
    from tools.learned import LEARNED
    src = trim(src, verdict, LEARNED.get("max_len", 35))      # short, starts near the action
    layout = weighted_choice(LAYOUTS, "layout_weight")
    words = weighted_choice(CAPTION_WORDS, "words_weight")
    srt = os.path.join(OUT, cid + ".srt")
    caps = has_audio(src) and make_srt(model, src, srt, words)
    out = os.path.join(OUT, cid + "_vertical.mp4")
    make_vertical(src, srt, out, caps, layout, (verdict or {}).get("hook", ""))
    clip = {"broadcaster_name": streamer, "title": "", "url": url}
    from tools.safety import safe_title
    title = safe_title((verdict or {}).get("title") or make_title(clip))
    desc = make_description(clip, title, (verdict or {}).get("tags", []))
    info = {
        "youtube_title": title, "youtube_description": desc, "youtube_tags": make_tags(clip),
        "source_type": source_type, "request": QUERY, "streamer": streamer, "platform": "twitch",
        "source_url": url, "layout": layout, "caption_words": words, "captions": bool(caps),
        "ai_score": (verdict or {}).get("score"), "ai_reason": (verdict or {}).get("reason", ""),
        "ai_summary": (verdict or {}).get("summary", ""), "ai_tags": (verdict or {}).get("tags", []),
        "match": (verdict or {}).get("match"),
        "hook": (verdict or {}).get("hook", ""),
        "made_at_utc": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
    }
    info.update(extra or {})
    with open(os.path.join(OUT, cid + ".json"), "w") as f:
        json.dump(info, f, indent=2)
    with open(os.path.join(OUT, cid + "_post.txt"), "w", encoding="utf-8") as f:
        f.write(desc)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "2", "-i", out, "-frames:v", "1",
                    "-vf", "crop=iw:iw*3/4:0:(ih-iw*3/4)/2,scale=640:-2", "-q:v", "4",
                    os.path.join(OUT, cid + "_thumb.jpg")])
    print(f"✅ {title}")
    MADE.append(cid)
    return cid


def from_links(urls, model):
    """Clip links the owner pasted. Twitch VOD links with ?t=1h2m3s get the 50s around that moment."""
    made = 0
    for url in urls:
        m = re.search(r"[?&]t=(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", url)
        section = []
        if m and "/videos/" in url:
            t = sum(int(x or 0) * k for x, k in zip(m.groups(), (3600, 60, 1)))
            section = ["--download-sections", f"*{max(0, t - 25)}-{t + 25}", "--force-keyframes-at-cuts"]
        src = os.path.join(OUT, f"link_{made}.mp4")
        r = subprocess.run(["yt-dlp", "-q", "-f", "best[height<=1080]/best", *section, "-o", src, url])
        if r.returncode or not os.path.exists(src):
            print(f"✗ couldn't download {url}")
            continue
        streamer = (re.search(r"twitch\.tv/([A-Za-z0-9_]+)", url) or [None, "clip"])[1].lower()
        if streamer in ("videos", "clip"):
            streamer = "clip"
        v = judge_text(transcribe(src, model), streamer, "twitch", "", (), QUERY)
        render(src, streamer, url, v, "requested_link", model)
        made += 1
    return made


def streamer_clips(login, days=14):
    """Recent clips from one streamer (any game)."""
    h = {"Client-Id": tw.CLIENT_ID, "Authorization": f"Bearer {tw.get_token()}"}
    uid = tw.get_user_id(login, h)
    if not uid:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return tw.fetch_clips({"broadcaster_id": uid, "started_at": since}, h)


def search(model, query=None, count=None, streamer=None, extra_cands=()):
    QUERY_ = query or QUERY
    COUNT_ = count or COUNT
    tw.MIN_VIEWS = 30                     # cast a wide net
    cands = list(extra_cands) + tw.get_clips(days=7, limit=400)
    if streamer:
        cands = [c for c in cands if c["broadcaster_name"].lower() == streamer.lower()] or cands
    seen_ids = set()
    cands = [c for c in cands if not (c["id"] in seen_ids or seen_ids.add(c["id"]))]
    try:
        done = set(json.load(open("made_clips.json")))
    except (OSError, ValueError):
        done = set()
    cands = [c for c in cands if c["id"] not in done]
    print(f"{len(cands)} candidate clips from Twitch")
    if not cands:
        return 0

    # 1) AI shortlist from titles (cheap, one request)
    listing = "\n".join(f"{i}|{c['broadcaster_name']}|{c['view_count']} views|{c['title'][:90]}"
                        for i, c in enumerate(cands[:350]))
    pick = gemini(f"""The owner of a GTA 6 clips channel asked for: "{QUERY_}".
Here are Twitch GTA clips (index|streamer|views|clip title). Clip titles are often vague, so also use the
streamer and popularity. Pick the {COUNT_ * 3} indexes most likely to match the request (best first).
If the request names a streamer, only pick that streamer's clips.
Reply ONLY with JSON: {{"indexes": [numbers]}}
{listing}""") or {}
    idx = [i for i in pick.get("indexes", []) if isinstance(i, int) and 0 <= i < len(cands)]
    shortlist = [cands[i] for i in idx] or cands[:COUNT_ * 3]
    print(f"shortlisted {len(shortlist)}")

    # 2) read each shortlisted clip and score the match
    from edit.download import download
    scored = []
    for c in shortlist[:COUNT_ * 3]:
        src = download(c)
        if not src:
            continue
        v = judge_text(transcribe(src, model), c["broadcaster_name"].lower(), "twitch", c["title"], (), QUERY_)
        if not v:
            continue
        print(f"  match {v.get('match')}/10 · score {v.get('score')} — {c['broadcaster_name']}: {v.get('reason', '')}")
        scored.append((float(v.get("match") or 0), float(v.get("score") or 0), c, src, v))

    scored.sort(key=lambda x: (-x[0], -x[1]))
    keep = [s for s in scored if s[0] >= 6][:COUNT_] or scored[:min(2, COUNT_)]
    for _, _, c, src, v in keep:
        render(src, c["broadcaster_name"].lower(), c["url"], v, "requested_search", model,
               {"vod_id": c.get("video_id") or "",
                "vod_window": [c["vod_offset"], c["vod_offset"] + c["duration"]] if c.get("vod_offset") is not None else None})
        done.add(c["id"])
    with open("made_clips.json", "w") as f:
        json.dump(sorted(done), f, indent=2)
    return len(keep)


def main():
    if not QUERY:
        sys.exit("No request given")
    os.makedirs(OUT, exist_ok=True)
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    urls = re.findall(r"https?://\S+", QUERY)
    twitch = [u for u in urls if "twitch.tv" in u]
    reels = [u for u in urls if "twitch.tv" not in u]   # Instagram / TikTok / YouTube / X → reel finder
    made = 0
    if twitch:
        made += from_links(twitch, model)
    if reels:
        from tools.reel import find_from_reel
        for u in reels:
            made += find_from_reel(u, model, COUNT)
    if not urls:
        made = search(model)
    import tools.find as tf   # the reel finder records its clips in the imported copy of this module
    MADE.extend(x for x in tf.MADE if x not in MADE)
    print(f"Made {made} clip(s) for: {QUERY}")
    with open("job_clips.json", "w") as f:
        json.dump(MADE, f)
    if reels and os.path.exists("job_message.txt"):
        return   # the reel finder already wrote what happened
    with open("job_message.txt", "w") as f:
        f.write(f"Found {made} clip(s) — they're in New Clips" if made else
                "Couldn't find clips matching that — try describing it differently or paste a link")


if __name__ == "__main__":
    main()
