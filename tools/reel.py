"""
📲 Reel finder: you (or a friend) share a reel/TikTok/Short of a streamer moment.
ClipBot works out who the streamer is and what happens, then hunts down the ORIGINAL moment on Twitch
and makes its own Short from the source — it never reposts the reel itself.
If it can't find the exact moment, it makes clips that are like it instead.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.find import gemini, render, search, streamer_clips, OUT, MADE  # noqa: E402
from tools.judge import judge_text, transcribe  # noqa: E402

KNOWN = ["ishowspeed", "kaicenat", "xqc", "lacy", "jynxzi", "caseoh_", "adinross", "ohnepixel", "summit1g",
         "jasontheween", "stableronaldo", "clix", "zoil", "lirik", "n3on", "clavicular"]


def words(t):
    return set(re.findall(r"[a-z']{3,}", t.lower()))


def similarity(a, b):
    """How much two transcripts overlap (0-1)."""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def say(msg):
    with open("job_message.txt", "w") as f:
        f.write(msg)


def find_from_reel(url, model, count=3):
    os.makedirs(OUT, exist_ok=True)
    reel = os.path.join(OUT, "reel_source.mp4")
    meta = {}
    r = subprocess.run(["yt-dlp", "-q", "--no-playlist", "-f", "best[height<=720]/best", "--print-json",
                        "-o", reel, url], capture_output=True, text=True)
    if r.stdout.strip():
        try:
            meta = json.loads(r.stdout.strip().splitlines()[-1])
        except ValueError:
            pass
    if not os.path.exists(reel):
        say("Couldn't open that link (Instagram/YouTube sometimes block bots). "
            "Try a TikTok link, or describe the clip in Find clips instead.")
        print("download failed:", r.stderr[-300:])
        return 0

    said = transcribe(reel, model)
    caption = " ".join(str(meta.get(k, "")) for k in ("title", "description", "uploader", "channel"))[:1500]
    print("reel transcript:", said[:300])

    # 1) who is it and what happens?
    info = gemini(f"""A short reel/TikTok shows a clip of a livestreamer (usually GTA 6).
Reel caption/uploader: {caption}
What's said in it:
{said[:3000]}
Known streamers (Twitch logins): {", ".join(KNOWN)}
Work out which streamer it is (Twitch login, lowercase; guess from names, handles, watermarks text, how people
address them, catchphrases) and describe the moment so it can be searched for.
Reply ONLY with JSON: {{"streamer": "login or empty", "confidence": 0-10,
 "description": "one sentence: what happens", "search": "short search request for similar moments"}}""") or {}
    streamer = (info.get("streamer") or "").lower().strip().lstrip("@")
    desc = info.get("description") or "a funny GTA 6 streamer moment"
    print("reel is:", info)

    # 2) look for the exact original moment in that streamer's recent Twitch clips
    if streamer:
        cands = streamer_clips(streamer, days=14)
        cands.sort(key=lambda c: -c["view_count"])
        listing = "\n".join(f"{i}|{c['view_count']} views|{c['created_at'][:10]}|{c['title'][:90]}"
                            for i, c in enumerate(cands[:200]))
        pick = gemini(f"""Find the Twitch clip that is most likely the SAME moment as this reel.
Moment: {desc}
Reel words: {said[:800]}
Clips (index|views|date|title):
{listing}
Reply ONLY with JSON: {{"indexes": [up to 8 best guesses, best first]}}""") or {}
        idx = [i for i in pick.get("indexes", []) if isinstance(i, int) and 0 <= i < len(cands)]
        best = None
        from edit.download import download
        for c in [cands[i] for i in idx][:8]:
            src = download(c)
            if not src:
                continue
            t = transcribe(src, model)
            sim = similarity(said, t)
            print(f"  {sim:.2f} — {c['title'][:60]}")
            if sim > (best[0] if best else 0):
                best = (sim, c, src, t)
        if best and best[0] >= 0.45:
            sim, c, src, t = best
            v = judge_text(t, streamer, "twitch", c["title"], (), desc)
            render(src, streamer, c["url"], v, "from_reel", model,
                   {"reel_url": url, "match_similarity": round(sim, 2),
                    "vod_id": c.get("video_id") or "",
                    "vod_window": [c["vod_offset"], c["vod_offset"] + c["duration"]]
                    if c.get("vod_offset") is not None else None})
            made = 1
            if count > 1:
                made += search(model, info.get("search") or desc, count - 1, streamer, cands)
            say(f"Found the original moment from {streamer}'s stream ✅" +
                (f" plus {made - 1} similar clip(s)" if made > 1 else "") + " — check New Clips")
            return made

    # 3) couldn't find the exact one: make clips like it
    made = search(model, info.get("search") or desc, count, streamer or None)
    who = f"{streamer}'s" if streamer else "the"
    say((f"Couldn't find {who} exact original (it may be older than 2 weeks or not on Twitch), "
         f"so I made {made} similar clip(s) — check New Clips") if made else
        "Couldn't find that moment or anything similar. Try describing it in Find clips.")
    return made
