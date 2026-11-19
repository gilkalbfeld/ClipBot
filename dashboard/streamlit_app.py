"""ClipBot dashboard. Run locally: streamlit run dashboard/streamlit_app.py"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data import GitHub, split_post  # noqa: E402

st.set_page_config(page_title="ClipBot", page_icon="🎬", layout="wide")

TOKEN = st.secrets.get("GITHUB_TOKEN", "")
REPO = st.secrets.get("REPO", "gilkalbfeld/clipbot")
if not TOKEN:
    st.error("Add GITHUB_TOKEN in this app's Settings → Secrets.")
    st.stop()
gh = GitHub(TOKEN, REPO)

NICK = {"ishowspeed": "Speed", "kaicenat": "Kai Cenat", "caseoh_": "CaseOh", "xqc": "xQc"}


# ---------------- cached data ----------------
@st.cache_data(ttl=60, show_spinner="Loading clips…")
def load_clips():
    return gh.clips()


@st.cache_data(ttl=30)
def load_posted():
    return gh.posted()[0]


@st.cache_data(ttl=200)
def video_url(asset_id):
    return gh.asset_url(asset_id)


@st.cache_data(ttl=None)
def post_text(asset_id):
    return gh.asset_text(asset_id)


def refresh():
    load_clips.clear()
    load_posted.clear()


def nice(name):
    return NICK.get(name, name) or "Unknown"


def ago(iso):
    mins = int((datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    if mins < 1440:
        return f"{mins // 60}h ago"
    return f"{mins // 1440}d ago"


# ---------------- clip card ----------------
def card(c, posted):
    title, desc = split_post(post_text(c["post_asset"])) if "post_asset" in c else ("", "")
    url = video_url(c["video_asset"])
    with st.container(border=True):
        if url:
            st.video(url)
        st.markdown(f"**{title or c['id']}**")
        st.caption(f"{nice(c['streamer'])} · {c['source']} · {ago(c['made_at'])} · {c['size_mb']} MB")
        st.code(title, language=None, wrap_lines=True)
        with st.expander("Description"):
            st.code(desc, language=None, wrap_lines=True)
        a, b = st.columns(2)
        if url:
            a.link_button("⬇️ Download", url, use_container_width=True)
        if c["id"] in posted:
            if b.button("↩️ Unmark", key="u" + c["id"], use_container_width=True):
                gh.set_posted(c["id"], undo=True)
                refresh()
                st.rerun()
            yt = posted[c["id"]].get("youtube_url")
            st.caption("✅ Posted" + (f" · [view]({yt})" if yt else ""))
        else:
            if b.button("✅ Posted", key="p" + c["id"], use_container_width=True):
                gh.set_posted(c["id"])
                refresh()
                st.rerun()


def grid(clips, posted, per_page=12, key="g"):
    if not clips:
        st.info("No clips here yet.")
        return
    pages = max(1, -(-len(clips) // per_page))
    page = st.number_input("Page", 1, pages, 1, key=key + "page") if pages > 1 else 1
    chunk = clips[(page - 1) * per_page: page * per_page]
    cols = st.columns(3)
    for i, c in enumerate(chunk):
        with cols[i % 3]:
            card(c, posted)


# ---------------- pages ----------------
def page_ready():
    clips, posted = load_clips(), load_posted()
    todo = [c for c in clips if c["id"] not in posted]
    st.title("🎬 Ready to post")
    m1, m2, m3 = st.columns(3)
    m1.metric("Waiting to post", len(todo))
    m2.metric("Posted", len(posted))
    m3.metric("Made today", sum(1 for c in clips if c["made_at"][:10] == datetime.now(timezone.utc).strftime("%Y-%m-%d")))
    grid(todo, posted, key="ready")


def page_library():
    clips, posted = load_clips(), load_posted()
    st.title("📚 Library")
    f1, f2, f3 = st.columns([2, 1, 1])
    q = f1.text_input("Search", placeholder="streamer, title, date (2026-11-19)…")
    streamers = sorted({c["streamer"] for c in clips if c["streamer"]})
    who = f2.selectbox("Streamer", ["All"] + streamers, format_func=lambda s: s if s == "All" else nice(s))
    status = f3.selectbox("Status", ["All", "Not posted", "Posted"])
    out = []
    for c in clips:
        if who != "All" and c["streamer"] != who:
            continue
        if status == "Posted" and c["id"] not in posted:
            continue
        if status == "Not posted" and c["id"] in posted:
            continue
        if q:
            title = split_post(post_text(c["post_asset"]))[0] if "post_asset" in c else ""
            hay = " ".join([c["id"], c["streamer"], nice(c["streamer"]), title, c["made_at"]]).lower()
            if q.lower() not in hay:
                continue
        out.append(c)
    st.caption(f"{len(out)} clips")
    grid(out, posted, key="lib")


def page_run():
    st.title("⚡ Make clips")
    a, b = st.columns(2)
    with a.container(border=True):
        st.subheader("Top GTA clips")
        st.write("Grabs the hottest new GTA clips on Twitch and makes up to 3 Shorts (~10 min).")
        if st.button("Make clips now", type="primary", use_container_width=True):
            gh.start_workflow("make.yml")
            st.success("Started! Clips show up in about 10 minutes.")
    with b.container(border=True):
        st.subheader("Live watcher")
        st.write("Watches your streamers live and clips every chat explosion.")
        mins = st.slider("How long (minutes)", 15, 340, 330, step=15)
        if st.button("Start watching", type="primary", use_container_width=True):
            gh.start_workflow("live.yml", {"minutes": str(mins)})
            st.success(f"Watching for {mins} minutes. Clips appear as they happen.")

    st.subheader("Recent runs")
    icons = {"success": "✅", "failure": "❌", "cancelled": "⏹️", None: "⏳"}
    for r in gh.recent_runs(10):
        st.write(f"{icons.get(r['conclusion'], '•')} **{r['name']}** · {ago(r['created_at'])} · "
                 f"[logs]({r['html_url']})")


def page_analytics():
    clips, posted = load_clips(), load_posted()
    st.title("📈 Analytics")
    st.info("YouTube views, comments and your best video show up here once your YouTube channel is connected. "
            "Below is what the bot has made so far.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total clips", len(clips))
    m2.metric("Posted", len(posted))
    m3.metric("Live clips", sum(c["source"] == "Live" for c in clips))
    m4.metric("Streamers", len({c["streamer"] for c in clips if c["streamer"]}))
    by = Counter(nice(c["streamer"]) for c in clips)
    st.subheader("Clips by streamer")
    st.bar_chart(dict(by.most_common()), color="#ff3c8e")
    st.subheader("Clips per day")
    st.bar_chart(dict(sorted(Counter(c["made_at"][:10] for c in clips).items())), color="#8b5cf6")


def page_money():
    st.title("💰 Money")
    st.info("Turns on once the channel is in the YouTube Partner Program. "
            "Shorts need 1,000 subscribers + 10M Shorts views in 90 days.")


PAGES = {
    "🎬 Ready to post": page_ready,
    "📚 Library": page_library,
    "⚡ Make clips": page_run,
    "📈 Analytics": page_analytics,
    "💰 Money": page_money,
}
with st.sidebar:
    st.markdown("## 🌴 ClipBot")
    choice = st.radio("Go to", list(PAGES), label_visibility="collapsed")
    if st.button("🔄 Refresh", use_container_width=True):
        refresh()
        st.rerun()
PAGES[choice]()
