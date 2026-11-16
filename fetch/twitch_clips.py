import os
import requests
from datetime import datetime, timedelta, timezone

CLIENT_ID = os.environ["TWITCH_CLIENT_ID"]
CLIENT_SECRET = os.environ["TWITCH_CLIENT_SECRET"]

# Twitch category names. GTA VI gets picked up once it exists.
GAME_NAMES = ["Grand Theft Auto VI", "Grand Theft Auto V"]

# Big streamers: we always check their clips (edit this list anytime)
FAMOUS_STREAMERS = ["kaicenat", "xqc", "ishowspeed", "summit1g", "adinross"]
FAMOUS_ANY_GAME = True  # False = only their GTA clips

MIN_VIEWS = 500
MAX_SECONDS = 60


def get_token():
    r = requests.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def get_game_id(name, headers):
    r = requests.get(
        "https://api.twitch.tv/helix/games",
        headers=headers,
        params={"name": name},
    )
    data = r.json().get("data", [])
    return data[0]["id"] if data else None


def get_user_id(login, headers):
    r = requests.get(
        "https://api.twitch.tv/helix/users",
        headers=headers,
        params={"login": login},
    )
    data = r.json().get("data", [])
    return data[0]["id"] if data else None


def keep(c):
    return c["view_count"] >= MIN_VIEWS and c["duration"] <= MAX_SECONDS


def get_clips(days=3, limit=50):
    headers = {
        "Client-Id": CLIENT_ID,
        "Authorization": f"Bearer {get_token()}",
    }
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = {}
    game_ids = []

    # 1) Top GTA clips from anyone
    for name in GAME_NAMES:
        gid = get_game_id(name, headers)
        if not gid:
            print(f"Category not found yet: {name}")
            continue
        game_ids.append(gid)
        r = requests.get(
            "https://api.twitch.tv/helix/clips",
            headers=headers,
            params={"game_id": gid, "started_at": since, "first": 100},
        )
        r.raise_for_status()
        for c in r.json().get("data", []):
            if keep(c):
                found[c["id"]] = c

    # 2) Clips from famous streamers
    for login in FAMOUS_STREAMERS:
        uid = get_user_id(login, headers)
        if not uid:
            print(f"Streamer not found: {login}")
            continue
        r = requests.get(
            "https://api.twitch.tv/helix/clips",
            headers=headers,
            params={"broadcaster_id": uid, "started_at": since, "first": 50},
        )
        r.raise_for_status()
        for c in r.json().get("data", []):
            if not keep(c):
                continue
            if FAMOUS_ANY_GAME or c["game_id"] in game_ids:
                found[c["id"]] = c

    clips = sorted(found.values(), key=lambda c: c["view_count"], reverse=True)
    return clips[:limit]


if __name__ == "__main__":
    for c in get_clips()[:10]:
        print(c["view_count"], c["broadcaster_name"], c["title"], c["url"])
