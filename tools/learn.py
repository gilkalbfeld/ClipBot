"""
Reads your 👍/👎 + comments (feedback.json) and turns them into settings the bot uses
on its next run (learned.json). Run before each bot run:  python tools/learn.py

What it learns:
  - which streamers you like  -> watched first / ranked higher
  - which streamers' clips are weak -> needs a bigger chat explosion before clipping
  - which layouts + caption speeds you like -> used more often
  - timing complaints in comments ("starts too late", "cut off") -> clip window adjusted
"""
import glob
import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime, timezone

BASE_BEFORE, BASE_AFTER = 40, 12

# comment keywords -> what to change
RULES = [
    (r"start(s|ed)? (too )?late|missing (the )?(start|beginning|setup)|need(s)? more (before|context)|"
     r"what happened before|too short", "more_before"),
    (r"too long|boring (start|beginning)|takes too long|slow start|drag", "less_before"),
    (r"cut(s)? off|ended (too )?(early|soon)|end(s)? too (early|soon)|missing (the )?(end|ending|punchline)|"
     r"more after", "more_after"),
    (r"commercial|ad break|\bads?\b", "ads"),
    (r"caption|subtitle|text", "captions"),
    (r"not funny|boring|nothing happen|mid\b|dead", "not_funny"),
]


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def clip_meta():
    """Layout/caption info for each clip, from the json files next to the videos."""
    meta = {}
    with tempfile.TemporaryDirectory() as d:
        for tag in ["live-clips", "clips"]:
            subprocess.run(["gh", "release", "download", tag, "-p", "*.json", "-D", d, "--clobber"],
                           capture_output=True)
        for f in glob.glob(os.path.join(d, "*.json")):
            meta[os.path.basename(f)[:-5]] = load(f, {})
    return meta


def ratio(up, down):
    return round(min(3.0, max(0.3, (up + 1) / (down + 1))), 2)


def main():
    fb = load("feedback.json", {})
    meta = clip_meta() if os.environ.get("GH_TOKEN") else {}
    by_streamer = defaultdict(lambda: [0, 0])
    by_layout = defaultdict(lambda: [0, 0])
    by_words = defaultdict(lambda: [0, 0])
    issues = defaultdict(int)

    for cid, f in fb.items():
        r = f.get("rating", 0)
        if not r:
            continue
        i = 0 if r > 0 else 1
        if f.get("streamer"):
            by_streamer[f["streamer"]][i] += 1
        m = meta.get(cid, {})
        if m.get("layout"):
            by_layout[m["layout"]][i] += 1
        if m.get("caption_words"):
            by_words[str(m["caption_words"])][i] += 1
        text = (f.get("comment") or "").lower()
        for pattern, issue in RULES:
            if re.search(pattern, text):
                issues[issue] += 1

    learned = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ratings": sum(1 for f in fb.values() if f.get("rating")),
        "streamer_weight": {s: ratio(u, d) for s, (u, d) in by_streamer.items()},
        "spike_mult": {},
        "layout_weight": {k: ratio(u, d) for k, (u, d) in by_layout.items()},
        "words_weight": {k: ratio(u, d) for k, (u, d) in by_words.items()},
        "seconds_before": BASE_BEFORE,
        "seconds_after": BASE_AFTER,
        "issues": dict(issues),
        "notes": [],
    }
    notes = learned["notes"]

    for s, (u, d) in by_streamer.items():
        if d >= 3 and d >= 2 * u:
            learned["spike_mult"][s] = 1.3
            notes.append(f"{s}: lots of 👎 — only clipping their biggest chat explosions now")
        elif u >= 3 and u >= 2 * d:
            learned["spike_mult"][s] = 0.85
            notes.append(f"{s}: you like their clips — clipping more of their moments")

    net_before = issues["more_before"] - issues["less_before"]
    learned["seconds_before"] = max(25, min(60, BASE_BEFORE + 5 * (net_before // 2)))
    learned["seconds_after"] = max(8, min(25, BASE_AFTER + 4 * (issues["more_after"] // 2)))
    if learned["seconds_before"] != BASE_BEFORE:
        notes.append(f"Clips now start {learned['seconds_before']}s before the moment (was {BASE_BEFORE}s)")
    if learned["seconds_after"] != BASE_AFTER:
        notes.append(f"Clips now run {learned['seconds_after']}s after the moment (was {BASE_AFTER}s)")
    for k, w in sorted(learned["layout_weight"].items(), key=lambda x: -x[1])[:1]:
        if w > 1.3:
            notes.append(f"'{k}' layout gets the most 👍 — using it more")
    if issues["ads"]:
        notes.append(f"{issues['ads']} comment(s) about commercial breaks — ads are now skipped when recording Twitch")
    # things you told ClipBot in the dashboard chat win over what it worked out itself
    chat = load("chat_settings.json", {})
    for k, v in chat.get("overrides", {}).items():
        if isinstance(v, dict) and isinstance(learned.get(k), dict):
            learned[k].update(v)
        else:
            learned[k] = v
    for line in chat.get("instructions", [])[-5:]:
        notes.append("You told me: " + line)
    if not notes:
        notes.append("Not enough feedback yet to change anything — keep rating clips.")

    with open("learned.json", "w") as f:
        json.dump(learned, f, indent=2)
    print(json.dumps(learned, indent=2))


if __name__ == "__main__":
    main()
