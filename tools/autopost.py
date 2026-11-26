"""
🤖 Auto-poster: picks the best clip and uploads it to ViceClips — no taps needed.

Order of picks: clips you approved first, then clips the AI scored 7+ (never ones you rated 👎 or kept
for Library only). Every clip passes the YouTube safety check before posting; unsafe ones are moved to
the Library with the reason. Mixes streamers so the same one isn't posted twice in a row.
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import youtube as ytapi  # noqa: E402
from tools.judge import transcribe  # noqa: E402
from tools.safety import check  # noqa: E402

BANGER = 9             # posts even if the daily limit is reached...
HARD_CAP = 10          # ...but never more than this many posts in 24h
MIN_SCORE = 8          # "bangers only" for clips you didn't approve
FALLBACK_SCORE = 7     # used only if there are no 8+ clips left
PROVEN_VIEWS = 5000   # Twitch clips with this many views are proven bangers


def load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def clips():
    out = []
    with tempfile.TemporaryDirectory() as d:
        for tag in ["live-clips", "clips"]:
            names = subprocess.run(["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[].name"],
                                   capture_output=True, text=True).stdout.split()
            subprocess.run(["gh", "release", "download", tag, "-p", "*.json", "-D", d, "--clobber"],
                           capture_output=True)
            for n in names:
                if n.endswith("_vertical.mp4"):
                    cid = n[:-len("_vertical.mp4")]
                    info = load(os.path.join(d, cid + ".json"), {})
                    out.append({"id": cid, "tag": tag, "info": info})
    return out


def main():
    settings = load("autopost.json", {"enabled": True, "per_day": 6})
    if not settings.get("enabled", True):
        print("Auto-posting is turned off")
        return
    posted, review, fb = load("posted.json", {}), load("review.json", {}), load("feedback.json", {})
    editing = {j.get("clip_id") for j in load("jobs.json", {}).values()
               if j.get("kind") == "edit" and not j.get("resolved")}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # count ALL posts in the last 24h (yours + ClipBot's) so the channel isn't flooded
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    done_today = [v for v in posted.values() if v.get("posted_at", "") > since]
    over_limit = len(done_today) >= settings.get("per_day", 6)
    if len(done_today) >= HARD_CAP:
        print("Hard cap reached")
        return
    recent = sorted(posted.values(), key=lambda v: v.get("posted_at", ""))[-3:]
    recent_streamers = {(v.get("streamer") or "").lower() for v in recent}

    cands = []
    for c in clips():
        cid, info = c["id"], c["info"]
        status = review.get(cid, {}).get("status")
        if cid in posted or cid in editing or status == "library" or fb.get(cid, {}).get("rating", 0) < 0:
            continue
        score = info.get("ai_score") or 0
        if status != "approved" and score < FALLBACK_SCORE:
            continue
        # proven = already went viral on Twitch (thousands of views) — the guide's "repost what performs"
        proven = (info.get("views") or 0) >= PROVEN_VIEWS
        fresh = (info.get("streamer") or "").lower() not in recent_streamers   # switch it up
        rank = (status == "approved", fresh, proven, score, info.get("views") or 0, cid)
        cands.append((rank, c))
    cands.sort(key=lambda x: x[0], reverse=True)
    if any(r[0] or r[2] or r[3] >= MIN_SCORE for r, _ in cands):   # prefer approved / 8+; 7s only if nothing better
        cands = [(r, c) for r, c in cands if r[0] or r[2] or r[3] >= MIN_SCORE]
    if over_limit:   # daily limit hit: only true bangers get through
        cands = [(r, c) for r, c in cands if (c["info"].get("ai_score") or 0) >= BANGER]
        print(f"Daily limit reached — {len(cands)} banger(s) (9+) can still go out")
    print(f"{len(cands)} clips ready to auto-post")

    yt = ytapi.YouTube(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"], os.environ["YT_REFRESH_TOKEN"])
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")

    for _, c in cands[:6]:
        cid, info, tag = c["id"], c["info"], c["tag"]
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["gh", "release", "download", tag, "-p", f"{cid}_vertical.mp4", "-p", f"{cid}_post.txt",
                            "-D", d, "--clobber"], capture_output=True)
            video = os.path.join(d, f"{cid}_vertical.mp4")
            if not os.path.exists(video):
                continue
            desc = open(os.path.join(d, f"{cid}_post.txt"), encoding="utf-8").read() \
                if os.path.exists(os.path.join(d, f"{cid}_post.txt")) else ""
            title = info.get("youtube_title") or (desc.splitlines() or [cid])[0]

            verdict = check(transcribe(video, model), title, info.get("ai_summary", ""))
            if not verdict["safe"]:
                print(f"✗ {cid} not YouTube-safe: {verdict['reason']}")
                review[cid] = {"status": "library", "reason": "Not YouTube-safe: " + verdict["reason"],
                               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                save("review.json", review)
                continue

            safe_t = verdict["title"]
            desc = desc.replace(title, safe_t, 1) if title in desc else f"{safe_t}\n\n{desc}"
            vid = ytapi.upload(yt, open(video, "rb").read(), safe_t, desc, info.get("youtube_tags") or [], "public")
            url = f"https://youtube.com/shorts/{vid}"
            posted[cid] = {"posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "youtube_url": url, "auto": True, "streamer": info.get("streamer", ""), "title": safe_t}
            save("posted.json", posted)
            with open("job_message.txt", "w") as f:
                f.write(f"Posted “{safe_t}” → {url}")
            print(f"✅ Posted {cid}: {safe_t} → {url}")
            return
    print("Nothing safe to post right now")
    with open("job_message.txt", "w") as f:
        f.write("No YouTube-safe clips ready to post — approve some or run Find clips")


if __name__ == "__main__":
    main()
