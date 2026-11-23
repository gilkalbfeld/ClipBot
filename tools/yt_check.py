"""Checks why recent uploads might not be getting views: privacy, processing, copyright blocks, age limits."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import youtube as ytapi  # noqa: E402

yt = ytapi.YouTube(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"], os.environ["YT_REFRESH_TOKEN"])
ch = yt.channel()
ids = []
d = yt.get(f"{ytapi.API}/playlistItems", part="contentDetails", playlistId=ch["uploads"], maxResults=10)
ids = [i["contentDetails"]["videoId"] for i in d.get("items", [])]
v = yt.get(f"{ytapi.API}/videos", part="snippet,status,contentDetails,statistics,processingDetails",
           id=",".join(ids))
for x in v.get("items", []):
    st, cd, s = x["status"], x["contentDetails"], x["snippet"]
    print(json.dumps({
        "title": s["title"][:60], "published": s["publishedAt"], "views": x["statistics"].get("viewCount"),
        "privacy": st.get("privacyStatus"), "upload": st.get("uploadStatus"), "rejection": st.get("rejectionReason"),
        "embeddable": st.get("embeddable"), "madeForKids": st.get("madeForKids"),
        "duration": cd.get("duration"), "regionRestriction": cd.get("regionRestriction"),
        "ageRestricted": cd.get("contentRating", {}).get("ytRating"),
        "licensedContent": cd.get("licensedContent"),
        "processing": x.get("processingDetails", {}).get("processingStatus"),
    }))
