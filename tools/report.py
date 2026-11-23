"""
Daily ViceClips report: pulls YouTube stats, links each video back to its clip (streamer, hashtags,
title, AI score), works out what's doing well, and has Gemini write a short report.
Saves reports/latest.json, reports/YYYY-MM-DD.md and youtube_stats.json (used by learn.py).
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests  # noqa: E402

from tools import youtube as ytapi  # noqa: E402
from tools.judge import MODELS, pick_models  # noqa: E402


def norm(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())[:40]


def clip_meta():
    meta = {}
    with tempfile.TemporaryDirectory() as d:
        for tag in ["live-clips", "clips"]:
            subprocess.run(["gh", "release", "download", tag, "-p", "*.json", "-D", d, "--clobber"],
                           capture_output=True)
        for f in glob.glob(os.path.join(d, "*.json")):
            try:
                m = json.load(open(f))
            except ValueError:
                continue
            if m.get("youtube_title"):
                meta[norm(m["youtube_title"])] = m
    return meta


def avg_by(vids, key_fn):
    groups = defaultdict(list)
    for v in vids:
        for k in key_fn(v):
            groups[k].append(v["views"])
    return {k: {"videos": len(x), "avg_views": round(sum(x) / len(x))} for k, x in groups.items()}


def length_buckets(vids):
    """Average % watched by clip length (helps pick the best Short length)."""
    out = {}
    for name, lo, hi in (("under_20s", 0, 20), ("20-30s", 20, 30), ("30-40s", 30, 40), ("40s+", 40, 999)):
        g = [v for v in vids if lo <= (v.get("seconds") or 0) < hi and v.get("averageViewPercentage") is not None]
        if g:
            out[name] = {"videos": len(g), "max": hi,
                         "avg_pct_watched": round(sum(v["averageViewPercentage"] for v in g) / len(g), 1),
                         "avg_views": round(sum(v["views"] for v in g) / len(g))}
    return out


def write_report(stats, key):
    prompt = f"""You are the analyst for ViceClips, a YouTube Shorts channel posting funny GTA 6 clips from streamers.
Write today's short daily report for the owner (casual, direct, no fluff, use markdown, max ~200 words):
1. Headline numbers (subs, views, change since yesterday if known)
2. 🏆 Best video and why it probably worked (title, streamer, hashtags, % watched)
3. 💀 Worst video and why
4. What's working: streamers, hashtags, title styles (only if there's enough data; say if it's too early)
5. 3 specific things to do today
Never invent numbers — only use these stats:
{json.dumps(stats)[:12000]}"""
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.5}}
    for model in sorted(pick_models(key, MODELS), key=lambda m: "lite" not in m):
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          headers={"x-goog-api-key": key}, json=body, timeout=90)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return None


def main():
    yt = ytapi.YouTube(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"], os.environ["YT_REFRESH_TOKEN"])
    snap = ytapi.snapshot(yt)
    meta = clip_meta()
    vids = snap["videos"]
    for v in vids:
        m = meta.get(norm(v["title"]), {})
        v["streamer"] = m.get("streamer", "")
        v["ai_score"] = m.get("ai_score")
        v["layout"] = m.get("layout")

    prev = {}
    try:
        prev = json.load(open("youtube_stats.json"))
    except (OSError, ValueError):
        pass
    ch = snap["channel"]
    pch = prev.get("channel", {})
    stats = {
        "date": date.today().isoformat(),
        "channel": ch,
        "change_since_last_report": {
            "subscribers": ch["subscribers"] - pch.get("subscribers", ch["subscribers"]),
            "views": ch["views"] - pch.get("views", ch["views"]),
        } if pch else "first report",
        "videos": [{k: v.get(k) for k in ("title", "views", "likes", "comments", "averageViewPercentage",
                                           "subscribersGained", "shares", "streamer", "hashtags", "published")}
                   for v in sorted(vids, key=lambda v: -v["views"])[:40]],
        "by_streamer": avg_by(vids, lambda v: [v["streamer"]] if v["streamer"] else []),
        "by_hashtag": avg_by(vids, lambda v: v["hashtags"]),
        "by_length": length_buckets(vids),
        "last_28_days": snap.get("daily", []),
        "revenue": snap.get("revenue"),
    }
    text = write_report(stats, os.environ.get("GEMINI_API_KEY", "")) if os.environ.get("GEMINI_API_KEY") else None
    if not text:
        top = stats["videos"][:3]
        text = (f"**{ch['subscribers']:,} subs · {ch['views']:,} views**\n\n" +
                "\n".join(f"- {v['title']} — {v['views']:,} views" for v in top))
    os.makedirs("reports", exist_ok=True)
    with open("reports/latest.json", "w") as f:
        json.dump({"date": stats["date"], "text": text}, f, indent=2)
    with open(f"reports/{stats['date']}.md", "w") as f:
        f.write(f"# ViceClips report — {stats['date']}\n\n{text}\n")
    with open("youtube_stats.json", "w") as f:
        json.dump({"channel": ch, "by_streamer": stats["by_streamer"], "by_hashtag": stats["by_hashtag"],
                   "by_length": stats["by_length"],
                   "date": stats["date"]}, f, indent=2)
    print(text)


if __name__ == "__main__":
    main()
