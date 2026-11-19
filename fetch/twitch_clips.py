import os
import requests
from datetime import datetime, timedelta, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.learned import LEARNED, streamer_weight  # noqa: E402

CLIENT_ID = os.environ["TWITCH_CLIENT_ID"]
CLIENT_SECRET = os.environ["TWITCH_CLIENT_SECRET"]

# Twitch category names. GTA VI gets picked up once it exists.
GAME_NAMES = ["Grand Theft Auto VI", "Grand Theft Auto V"]

# Big streamers: we always check their clips (edit anytime)
FAMOUS_STREAMERS = ["kaicenat", "xqc", "ishowspeed", "summit1g", "adinross", "lacy"]

# Favorites get pushed up the list (score x this number)
FAVORITES = {"ishowspeed": 3, "lacy": 2}
FAMOUS_ANY_GAME = False  # True = any game, False = only their GTA clips

LANGUAGE = "en"      # "en" = English only
MIN_VIEWS = LEARNED.get("min_views", 1000)   # raise to be pickier (can be set from the dashboard chat)
MAX_SECONDS = 60     # short clips only
PAGES = 3            # more pages = bigger pool of clips


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


def fetch_clips(params, headers):
    """Gets several pages of clips for one search."""
    clips = []
    cursor = None
    for _ in range(PAGES):
        p = dict(params)
        p["first"] = 100
        if cursor:
            p["after"] = cursor
        r = requests.get(
            "https://api.twitch.tv/helix/clips", headers=headers, params=p
        )
        r.raise_for_status()
        j = r.json()
        clips.extend(j.get("data", []))
        cursor = j.get("pagination", {}).get("cursor")
        if not cursor:
            break
    return clips


def keep(c):
    return (
        streamer_weight(c["broadcaster_name"]) > 0
        and c["view_count"] >= MIN_VIEWS
        and c["duration"] <= MAX_SECONDS
        and c.get("language") == LANGUAGE
    )


def add_score(c):
    """Views per hour since the clip was made = how fast it's blowing up."""
    created = datetime.fromisoformat(c["created_at"].replace("Z", "+00:00"))
    hours = max((datetime.now(timezone.utc) - created).total_seconds() / 3600, 1)
    boost = FAVORITES.get(c["broadcaster_name"].lower(), 1) * streamer_weight(c["broadcaster_name"])
    c["score"] = round(c["view_count"] / hours * boost, 1)
    return c


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
        for c in fetch_clips({"game_id": gid, "started_at": since}, headers):
            if keep(c):
                found[c["id"]] = c

    # 2) Clips from famous streamers
    for login in FAMOUS_STREAMERS:
        uid = get_user_id(login, headers)
        if not uid:
            print(f"Streamer not found: {login}")
            continue
        for c in fetch_clips({"broadcaster_id": uid, "started_at": since}, headers):
            if not keep(c):
                continue
            if FAMOUS_ANY_GAME or c["game_id"] in game_ids:
                found[c["id"]] = c

    clips = [add_score(c) for c in found.values()]
    clips.sort(key=lambda c: c["score"], reverse=True)
    return clips[:limit]


if __name__ == "__main__":
    for c in get_clips()[:15]:
        print(c["score"], c["view_count"], c["broadcaster_name"], c["title"], c["url"])
