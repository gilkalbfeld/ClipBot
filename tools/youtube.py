"""
YouTube connection: login (OAuth), channel + per-video stats, and analytics.
Used by the dashboard (Analytics page) and by the daily report.

Needs: YT_CLIENT_ID, YT_CLIENT_SECRET (from Google Cloud) and YT_REFRESH_TOKEN (from connecting once).
"""
import re
from datetime import date, timedelta
from urllib.parse import urlencode

import requests

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",   # post Shorts for you
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",   # revenue, once monetized
]
API = "https://www.googleapis.com/youtube/v3"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"


# ---------------- login ----------------
def auth_url(client_id, redirect_uri):
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true",
    })


def exchange_code(client_id, client_secret, redirect_uri, code):
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code"}, timeout=30)
    r.raise_for_status()
    return r.json()   # has refresh_token


class YouTube:
    def __init__(self, client_id, client_secret, refresh_token):
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token"}, timeout=30)
        r.raise_for_status()
        self.h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    def get(self, url, **params):
        r = requests.get(url, headers=self.h, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # ---------------- channel ----------------
    def channel(self):
        c = self.get(f"{API}/channels", part="snippet,statistics,contentDetails", mine="true")["items"][0]
        return {
            "id": c["id"], "title": c["snippet"]["title"],
            "published": c["snippet"]["publishedAt"][:10],
            "subscribers": int(c["statistics"].get("subscriberCount", 0)),
            "views": int(c["statistics"].get("viewCount", 0)),
            "videos": int(c["statistics"].get("videoCount", 0)),
            "uploads": c["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def videos(self, uploads_playlist, limit=200):
        ids, token = [], None
        while len(ids) < limit:
            p = {"part": "contentDetails", "playlistId": uploads_playlist, "maxResults": 50}
            if token:
                p["pageToken"] = token
            d = self.get(f"{API}/playlistItems", **p)
            ids += [i["contentDetails"]["videoId"] for i in d.get("items", [])]
            token = d.get("nextPageToken")
            if not token:
                break
        out = []
        for i in range(0, len(ids), 50):
            d = self.get(f"{API}/videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]))
            for v in d.get("items", []):
                s, st = v["snippet"], v["statistics"]
                out.append({
                    "id": v["id"], "title": s["title"], "published": s["publishedAt"],
                    "description": s.get("description", ""),
                    "hashtags": sorted({h.lower() for h in re.findall(r"#\w+", s.get("description", "") + " " + s["title"])}),
                    "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                    "comments": int(st.get("commentCount", 0)),
                    "url": f"https://youtube.com/shorts/{v['id']}",
                })
        return out

    # ---------------- analytics ----------------
    def video_analytics(self, start=None):
        """Watch time, average % watched, subs gained, shares per video."""
        start = start or (date.today() - timedelta(days=90)).isoformat()
        try:
            d = self.get(ANALYTICS, ids="channel==MINE", startDate=start, endDate=date.today().isoformat(),
                         metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                                 "likes,comments,shares,subscribersGained",
                         dimensions="video", sort="-views", maxResults=200)
        except requests.HTTPError:
            return {}
        cols = [c["name"] for c in d.get("columnHeaders", [])]
        return {row[0]: dict(zip(cols[1:], row[1:])) for row in d.get("rows", [])}

    def daily(self, days=28):
        start = (date.today() - timedelta(days=days)).isoformat()
        try:
            d = self.get(ANALYTICS, ids="channel==MINE", startDate=start, endDate=date.today().isoformat(),
                         metrics="views,likes,comments,subscribersGained,estimatedMinutesWatched",
                         dimensions="day", sort="day")
        except requests.HTTPError:
            return []
        cols = [c["name"] for c in d.get("columnHeaders", [])]
        return [dict(zip(cols, row)) for row in d.get("rows", [])]

    def revenue(self, days=28):
        start = (date.today() - timedelta(days=days)).isoformat()
        try:
            d = self.get(ANALYTICS, ids="channel==MINE", startDate=start, endDate=date.today().isoformat(),
                         metrics="estimatedRevenue,cpm,playbackBasedCpm", dimensions="day", sort="day")
        except requests.HTTPError:
            return None   # not monetized yet
        cols = [c["name"] for c in d.get("columnHeaders", [])]
        return [dict(zip(cols, row)) for row in d.get("rows", [])]


def snapshot(yt):
    """Everything in one dict (saved to youtube_stats.json for the dashboard + learning)."""
    ch = yt.channel()
    vids = yt.videos(ch["uploads"])
    an = yt.video_analytics(ch["published"])
    for v in vids:
        v.update(an.get(v["id"], {}))
    return {"channel": ch, "videos": vids, "daily": yt.daily(), "revenue": yt.revenue()}


# ---------------- uploading ----------------
def upload(yt, video_bytes, title, description, tags=(), privacy="public", publish_at=None):
    """Uploads a Short to the channel. Returns the new video id."""
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:                    # scheduled: must be private until publish time
        status.update(privacyStatus="private", publishAt=publish_at)
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": [t for t in tags if t][:15], "categoryId": "20"},   # 20 = Gaming
        "status": status,
    }
    r = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={**yt.h, "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(video_bytes))},
        json=meta, timeout=60)
    r.raise_for_status()
    up = requests.put(r.headers["Location"], data=video_bytes,
                      headers={"Content-Type": "video/mp4"}, timeout=600)
    up.raise_for_status()
    return up.json()["id"]
