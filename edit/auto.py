
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from fetch.twitch_clips import get_token, CLIENT_ID

STREAMERS = [
    "kaicenat", "ishowspeed", "caseoh_", "jynxzi",
    "xqc", "ninja", "lacy", "marlon"
]

HOURS_BACK = 30
MIN_VOD_MINUTES = 60
MAX_VODS = 4
KEYWORDS = []

PROCESSED_FILE = "processed_vods.json"


def minutes(duration):
    match = re.fullmatch(
        r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?",
        duration
    )

    if not match:
        return 0

    hours, mins, secs = (int(x or 0) for x in match.groups())
    return hours * 60 + mins + secs / 60


def load_processed():
    if not os.path.exists(PROCESSED_FILE):
        return []

    with open(PROCESSED_FILE, encoding="utf-8") as file:
        return json.load(file)


def save_processed(processed):
    with open(PROCESSED_FILE, "w", encoding="utf-8") as file:
        json.dump(processed, file, indent=2)


def main():
    import json

    headers = {
        "Client-Id": CLIENT_ID,
        "Authorization": f"Bearer {get_token()}"
    }

    processed = load_processed()

    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=HOURS_BACK
    )

    picked = []

    for login in STREAMERS:
        user_response = requests.get(
            "https://api.twitch.tv/helix/users",
            headers=headers,
            params={"login": login}
        )
        user_response.raise_for_status()

        users = user_response.json().get("data", [])

        if not users:
            print("Streamer not found:", login)
            continue

        video_response = requests.get(
            "https://api.twitch.tv/helix/videos",
            headers=headers,
            params={
                "user_id": users[0]["id"],
                "type": "archive",
                "first": 5
            }
        )
        video_response.raise_for_status()

        videos = video_response.json().get("data", [])

        for video in videos:
            vod_id = video["id"]

            created = datetime.fromisoformat(
                video["created_at"].replace("Z", "+00:00")
            )

            if vod_id in processed:
                continue

            if created < cutoff:
                continue

            if minutes(video["duration"]) < MIN_VOD_MINUTES:
                continue

            if KEYWORDS and not any(
                word.lower() in video["title"].lower()
                for word in KEYWORDS
            ):
                continue

            picked.append((login, video))
            print("Picked:", login, "|", video["title"])

            break

        if len(picked) >= MAX_VODS:
            break

    if not picked:
        print("No new VODs found.")
        return

    for login, video in picked:
        vod_id = video["id"]

        print("Processing:", login, video["url"])

        env = dict(os.environ, VOD=video["url"])

        result = subprocess.run(
            [sys.executable, "edit/chat_clips.py"],
            env=env
        )

        if result.returncode != 0:
            print("Processing failed:", vod_id)
            continue

        destination = f"all/{login}_{vod_id}"

        os.makedirs("all", exist_ok=True)

        if os.path.isdir("output"):
            if os.path.exists(destination):
                shutil.rmtree(destination)

            shutil.move("output", destination)

        processed.append(vod_id)
        save_processed(processed)

        print("Saved:", destination)


if __name__ == "__main__":
    main()
