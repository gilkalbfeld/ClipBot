import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fetch.twitch_clips import get_token, CLIENT_ID

# Twitch login names (the part after twitch.tv/). Fix any that are wrong.
STREAMERS = [
    "kaicenat", "ishowspeed", "caseoh_", "jinnytty", "lacy",
    "marlon",
]
HOURS_BACK = 30       # only VODs from the last 30 hours
MIN_VOD_MINUTES = 60  # skip short streams
KEYWORDS = []         # e.g. ["gta", "rp"] to only take VODs with these in the title
MAX_VODS = 4          # cap per run so it fits the free minutes


def minutes(dur):
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", dur)
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 60 + mi + s / 60


def main():
    headers = {
        "Client-Id": CLIENT_ID,
        "Authorization": f"Bearer {get_token()}",
    }
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    picked = []

    for login in STREAMERS:
        u = requests.get(
            "https://api.twitch.tv/helix/users", headers=headers, params={"login": login}
        ).json().get("data", [])
        if not u:
            print("Streamer not found:", login)
            continue
        vids = requests.get(
            "https://api.twitch.tv/helix/videos",
            headers=headers,
            params={"user_id": u[0]["id"], "type": "archive", "first": 5},
        ).json().get("data", [])
        for v in vids:
            created = datetime.fromisoformat(v["created_at"].replace("Z", "+00:00"))
            if created < cutoff or minutes(v["duration"]) < MIN_VOD_MINUTES:
                continue
            if KEYWORDS and not any(k in v["title"].lower() for k in KEYWORDS):
                continue
            picked.append((login, v))
            print("Picked:", login, "|", v["title"], "|", v["duration"])
            break
        if len(picked) >= MAX_VODS:
            break

    if not picked:
        print("No new VODs found.")
        return

    os.makedirs("all", exist_ok=True)
    for login, v in picked:
        print("=== Processing", login, v["url"])
        env = dict(os.environ, VOD=v["url"])
        r = subprocess.run([sys.executable, "edit/chat_clips.py"], env=env)
        if r.returncode != 0:
            print("  failed, moving on")
            continue
        dest = f"all/{login}_{v['id']}"
        if os.path.isdir("output"):
            shutil.move("output", dest)
            print("  saved to", dest)


if __name__ == "__main__":
    main()
