"""
ClipBot Inbox — a tiny public page where friends can send reels straight to ClipBot.
It can ONLY accept links (needs the secret code). It can't show clips or change anything else.

Secrets: GITHUB_TOKEN, INBOX_CODE (the secret code friends use), optional REPO.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data import GitHub  # noqa: E402

st.set_page_config(page_title="ClipBot Inbox", page_icon="🌴", layout="centered")
st.markdown("""<style>
.stApp{background:#0d0b12} h1{font-weight:800!important}
.big{font-size:3rem;text-align:center;margin-top:1rem}
</style>""", unsafe_allow_html=True)

TOKEN = st.secrets.get("GITHUB_TOKEN", "")
CODE = str(st.secrets.get("INBOX_CODE", ""))
REPO = st.secrets.get("REPO", "gilkalbfeld/clipbot")
DAILY_LIMIT = 25
if not TOKEN or not CODE:
    st.error("Inbox isn't set up yet (needs GITHUB_TOKEN and INBOX_CODE in Secrets).")
    st.stop()
gh = GitHub(TOKEN, REPO)


def send(url, who):
    jobs, _ = gh.read_json("jobs.json")
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    today = [j for j in jobs.values() if j.get("from_inbox") and j.get("started_at", "") > since]
    if len(today) >= DAILY_LIMIT:
        return "ClipBot's inbox is full for today — try again tomorrow."
    if any(j.get("reel_url") == url for j in jobs.values()):
        return "already"
    gh.start_job("find", "find.yml", {"query": url, "count": "3"},
                 {"label": f"Reel from {who or 'a friend'}: {url[:70]}", "count": 3,
                  "from_inbox": True, "reel_url": url, "sender": who})
    return "ok"


st.markdown('<div class="big">🌴</div>', unsafe_allow_html=True)
st.title("Send a clip to ClipBot")

qp = st.query_params
url = (qp.get("reel") or "").strip()
code = (qp.get("code") or "").strip()
who = (qp.get("from") or "").strip()[:30]

if url and code:   # came from the iPhone Shortcut
    if code != CODE:
        st.error("Wrong code.")
    elif not re.match(r"https?://", url):
        st.error("That doesn't look like a link.")
    else:
        r = send(url, who)
        if r == "ok":
            st.success("✅ Sent! ClipBot is finding this clip now.")
            st.balloons()
        elif r == "already":
            st.info("👍 ClipBot already has this one.")
        else:
            st.warning(r)
    st.caption(url)
    st.stop()

with st.form("send"):
    link = st.text_input("Reel / TikTok link", placeholder="https://www.tiktok.com/…")
    name = st.text_input("Your name (optional)")
    c = st.text_input("Secret code", type="password")
    if st.form_submit_button("📲 Send to ClipBot", use_container_width=True):
        if c.strip() != CODE:
            st.error("Wrong code.")
        elif not re.match(r"https?://", link.strip()):
            st.error("Paste a link first.")
        else:
            r = send(link.strip(), name.strip())
            st.success("✅ Sent! ClipBot is on it.") if r == "ok" else \
                st.info("👍 ClipBot already has this one.") if r == "already" else st.warning(r)
