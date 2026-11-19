"""ClipBot dashboard. Run locally: streamlit run dashboard/streamlit_app.py"""
import html
import importlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data  # noqa: E402

importlib.reload(data)  # pick up changes to data.py on every update, no reboot needed
GitHub, split_post = data.GitHub, data.split_post

st.set_page_config(page_title="ClipBot", page_icon="🌴", layout="wide")

TOKEN = st.secrets.get("GITHUB_TOKEN", "")
REPO = st.secrets.get("REPO", "gilkalbfeld/clipbot")
if not TOKEN:
    st.error("Add GITHUB_TOKEN in this app's Settings → Secrets.")
    st.stop()
gh = GitHub(TOKEN, REPO)

NICK = {"ishowspeed": "Speed", "kaicenat": "Kai Cenat", "caseoh_": "CaseOh", "xqc": "xQc",
        "jynxzi": "Jynxzi", "lacy": "Lacy", "ohnepixel": "ohnePixel", "adinross": "Adin Ross"}
PINK, PURPLE = "#ff3ea5", "#8b5cf6"

# ---------------- look & feel ----------------
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, button, input {{ font-family: 'Inter', sans-serif !important; }}
.stApp {{ background: radial-gradient(1200px 600px at 100% -10%, rgba(139,92,246,.12), transparent 60%),
                     radial-gradient(900px 500px at -10% 110%, rgba(255,62,165,.08), transparent 60%), #0d0b12; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.6rem; max-width: 1400px; }}

/* ---- sidebar: slim + clean ---- */
section[data-testid="stSidebar"] {{ width: 210px !important; min-width: 210px !important; max-width: 210px !important;
  background: #110e17; border-right: 1px solid rgba(255,255,255,.06); }}
section[data-testid="stSidebar"] .block-container, section[data-testid="stSidebarContent"] {{ padding: 0 .9rem; }}
.logo {{ display:flex; align-items:center; gap:.5rem; font-weight:800; font-size:1.25rem; color:#fff;
  margin: .4rem 0 1.4rem .2rem; letter-spacing:-.02em; }}
.logo span {{ background: linear-gradient(90deg,{PINK},{PURPLE}); -webkit-background-clip:text; color:transparent; }}
.navlabel {{ color:#6f6880; font-size:.7rem; font-weight:600; letter-spacing:.12em; margin:1.2rem 0 .4rem .5rem; }}
section[data-testid="stSidebar"] .stButton > button {{ width:100%; justify-content:flex-start; border:1px solid transparent;
  background:transparent; color:#a8a1b8; font-weight:500; font-size:.9rem; padding:.45rem .7rem; border-radius:10px; }}
section[data-testid="stSidebar"] .stButton > button:hover {{ background:rgba(255,255,255,.04); color:#fff; border-color:transparent; }}
section[data-testid="stSidebar"] .stButton > button[kind="primary"],
section[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {{
  background:rgba(255,62,165,.10); color:#fff; border:1px solid rgba(255,62,165,.55);
  box-shadow:0 0 14px rgba(255,62,165,.25); }}

/* ---- buttons ---- */
.stButton > button, .stLinkButton > a {{ border-radius:10px; border:1px solid rgba(255,255,255,.10);
  background:#1a1622; color:#e9e5f2; font-weight:500; }}
.stButton > button:hover {{ border-color:rgba(255,62,165,.6); color:#fff; }}
.main .stButton > button[kind="primary"], [data-testid="stMain"] [data-testid="stBaseButton-primary"] {{
  background:linear-gradient(90deg,{PINK},#d946ef); border:none; color:#fff; font-weight:600;
  box-shadow:0 0 18px rgba(255,62,165,.35); }}

/* ---- inputs ---- */
.stTextInput input, .stSelectbox div[data-baseweb="select"] > div {{ background:#15121c !important;
  border:1px solid rgba(255,255,255,.08) !important; border-radius:10px !important; }}

/* ---- cards ---- */
div[data-testid="stVerticalBlockBorderWrapper"] {{ background:linear-gradient(180deg,#17131f,#130f19);
  border:1px solid rgba(255,255,255,.07) !important; border-radius:16px !important; }}
.tile {{ background:linear-gradient(180deg,#17131f,#130f19); border:1px solid rgba(255,255,255,.07);
  border-radius:14px; padding:1rem 1.2rem; }}
.tile .k {{ color:#a8a1b8; font-size:.85rem; }}
.tile .v {{ font-size:2rem; font-weight:800; letter-spacing:-.03em;
  background:linear-gradient(90deg,{PINK},{PURPLE}); -webkit-background-clip:text; color:transparent; }}
.meta {{ display:flex; align-items:center; gap:.45rem; color:#8d86a0; font-size:.82rem; margin:.5rem 0 .2rem; }}
.avatar {{ width:22px; height:22px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
  font-size:.7rem; font-weight:700; color:#fff; background:linear-gradient(135deg,{PINK},{PURPLE}); }}
.live {{ color:{PINK}; font-weight:600; }}
.ctitle {{ font-weight:700; font-size:1.02rem; line-height:1.35; color:#fff; margin:.15rem 0 .6rem; min-height:2.7em; }}
.badge {{ display:inline-block; padding:.12rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600; }}
.b-ready {{ background:rgba(255,62,165,.15); color:{PINK}; }}
.b-posted {{ background:rgba(139,92,246,.18); color:#b79cff; }}
.b-run {{ background:rgba(139,92,246,.2); color:#c4b0ff; }}
.b-ok {{ background:rgba(34,197,94,.15); color:#4ade80; }}
.b-bad {{ background:rgba(239,68,68,.15); color:#f87171; }}
h1 {{ font-weight:800 !important; letter-spacing:-.03em; }}
.run {{ display:flex; justify-content:space-between; align-items:center; padding:.75rem 1rem; margin-bottom:.5rem;
  background:#15121c; border:1px solid rgba(255,255,255,.06); border-radius:12px; color:#ddd8e8; }}
.run a {{ color:#8d86a0; }}
.banner {{ background:rgba(139,92,246,.08); border:1px solid rgba(139,92,246,.35); border-radius:14px;
  padding:1rem 1.2rem; color:#c9c2d8; margin-bottom:1rem; }}
</style>
""", unsafe_allow_html=True)


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


@st.cache_data(ttl=30)
def load_feedback():
    return gh.feedback()


@st.cache_data(ttl=20)
def load_runs():
    return gh.recent_runs(8)


def refresh():
    for f in (load_clips, load_posted, load_feedback, load_runs):
        f.clear()


def nice(name):
    return NICK.get(name, name) or "Unknown"


def ago(iso):
    mins = int((datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    if mins < 1440:
        return f"{mins // 60}h ago"
    return f"{mins // 1440}d ago"


def tiles(items):
    cols = st.columns(len(items))
    for col, (k, v) in zip(cols, items):
        col.markdown(f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div></div>',
                     unsafe_allow_html=True)


def copy_buttons(title, desc, key):
    """Two real copy-to-clipboard buttons (works on iPad Safari too)."""
    components.html(f"""
    <style>
      body{{margin:0;font-family:Inter,sans-serif}} .r{{display:flex;gap:8px}}
      button{{flex:1;padding:8px 0;border-radius:10px;border:1px solid rgba(255,255,255,.12);background:#1a1622;
        color:#e9e5f2;font-size:13px;font-weight:500;cursor:pointer}} button:hover{{border-color:#ff3ea5}}
    </style>
    <div class="r"><button id="t">Copy Title</button><button id="d">Copy Description</button></div>
    <script>
      function cp(txt, b, label){{
        const done=()=>{{b.textContent='Copied ✓';setTimeout(()=>b.textContent=label,1400)}};
        const fb=()=>{{const t=document.createElement('textarea');t.value=txt;document.body.appendChild(t);
          t.select();document.execCommand('copy');t.remove();done()}};
        if(navigator.clipboard){{navigator.clipboard.writeText(txt).then(done,fb)}}else{{fb()}}
      }}
      const T={json.dumps(title)}, D={json.dumps(desc)};
      document.getElementById('t').onclick=e=>cp(T,e.target,'Copy Title');
      document.getElementById('d').onclick=e=>cp(D,e.target,'Copy Description');
    </script>""", height=42)


# ---------------- clip card ----------------
def card(c, posted, show_badge=False):
    title, desc = split_post(post_text(c["post_asset"])) if "post_asset" in c else ("", "")
    url = video_url(c["video_asset"])
    is_posted = c["id"] in posted
    fb = load_feedback().get(c["id"], {})
    with st.container(border=True):
        if url:
            st.video(url)
        badge = ""
        if show_badge:
            badge = ('<span class="badge b-posted">Posted</span>' if is_posted
                     else '<span class="badge b-ready">Ready</span>')
        name = nice(c["streamer"])
        src = '<span class="live">Live</span>' if c["source"] == "Live" else "Top clip"
        st.markdown(
            f'<div class="meta"><span class="avatar">{html.escape(name[:1].upper())}</span>'
            f'{html.escape(name)} · {src} · {ago(c["made_at"])} {badge}</div>'
            f'<div class="ctitle">{html.escape(title or c["id"])}</div>',
            unsafe_allow_html=True)
        copy_buttons(title, desc, c["id"])

        # feedback: 👍 👎 + comment
        up, down, box = st.columns([1, 1, 4], vertical_alignment="center")
        r = fb.get("rating", 0)
        comment = box.text_input("Feedback", value=fb.get("comment", ""), placeholder="Add feedback…",
                                 label_visibility="collapsed", key="c" + c["id"])
        if up.button("👍", key="up" + c["id"], type="primary" if r > 0 else "secondary", use_container_width=True):
            gh.set_feedback(c, 1, comment)
            load_feedback.clear()
            st.rerun()
        if down.button("👎", key="dn" + c["id"], type="primary" if r < 0 else "secondary", use_container_width=True):
            gh.set_feedback(c, -1, comment)
            load_feedback.clear()
            st.rerun()
        if r and comment != fb.get("comment", ""):
            gh.set_feedback(c, r, comment)
            load_feedback.clear()
            st.toast("Comment saved")

        if is_posted:
            if st.button("↩ Mark as not posted", key="u" + c["id"], use_container_width=True):
                gh.set_posted(c["id"], undo=True)
                refresh()
                st.rerun()
        else:
            if st.button("Mark as posted", key="p" + c["id"], use_container_width=True):
                gh.set_posted(c["id"])
                refresh()
                st.rerun()


def grid(clips, posted, per_page=12, key="g", show_badge=False):
    if not clips:
        st.info("No clips here yet.")
        return
    pages = max(1, -(-len(clips) // per_page))
    chunk_page = 1
    if pages > 1:
        chunk_page = st.session_state.get(key + "page", 1)
    chunk = clips[(chunk_page - 1) * per_page: chunk_page * per_page]
    cols = st.columns(3, gap="medium")
    for i, c in enumerate(chunk):
        with cols[i % 3]:
            card(c, posted, show_badge)
    if pages > 1:
        st.number_input("Page", 1, pages, key=key + "page")


def search(clips, q):
    q = q.lower().strip()
    out = []
    for c in clips:
        title = split_post(post_text(c["post_asset"]))[0] if "post_asset" in c else ""
        if q in " ".join([c["id"], c["streamer"], nice(c["streamer"]), title, c["made_at"]]).lower():
            out.append(c)
    return out


# ---------------- pages ----------------
def page_ready():
    clips, posted = load_clips(), load_posted()
    todo = [c for c in clips if c["id"] not in posted]
    st.title("Ready to Post")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tiles([("Waiting to post", len(todo)), ("Posted", len(posted)),
           ("Made today", sum(c["made_at"][:10] == today for c in clips))])
    st.write("")
    grid(todo, posted, key="ready")


def page_library():
    clips, posted = load_clips(), load_posted()
    st.title("Library")
    f1, f2, f3 = st.columns([2, 1, 1])
    q = f1.text_input("Search", placeholder="Search streamer, title, date…")
    streamers = sorted({c["streamer"] for c in clips if c["streamer"]})
    who = f2.selectbox("Streamer", ["All"] + streamers, format_func=lambda s: s if s == "All" else nice(s))
    status = f3.selectbox("Status", ["All", "Ready", "Posted"])
    out = [c for c in clips
           if (who == "All" or c["streamer"] == who)
           and (status == "All" or (status == "Posted") == (c["id"] in posted))]
    if q:
        out = search(out, q)
    st.caption(f"{len(out)} clips")
    grid(out, posted, key="lib", show_badge=True)


def page_run():
    st.title("Make Clips")
    a, b = st.columns(2, gap="medium")
    with a.container(border=True):
        st.subheader("Top GTA clips 💥")
        st.write("Grabs the hottest new GTA clips on Twitch and makes up to 3 Shorts (~10 min).")
        st.write("")
        if st.button("Make clips now", type="primary", use_container_width=True, key="mk"):
            gh.start_workflow("make.yml")
            load_runs.clear()
            st.success("Started! Clips show up in about 10 minutes.")
    with b.container(border=True):
        st.subheader("Live watcher 📡")
        st.write("Watches your streamers live and clips every chat explosion.")
        mins = st.slider("How long (minutes)", 15, 340, 330, step=15)
        if st.button("Start watching", type="primary", use_container_width=True):
            gh.start_workflow("live.yml", {"minutes": str(mins)})
            load_runs.clear()
            st.success(f"Watching for {mins} minutes. Clips appear as they happen.")

    st.subheader("Recent runs")
    for r in load_runs():
        if r["status"] != "completed":
            pill = '<span class="badge b-run">Running</span>'
        elif r["conclusion"] == "success":
            pill = '<span class="badge b-ok">✓ Done</span>'
        else:
            pill = f'<span class="badge b-bad">{r["conclusion"] or "Failed"}</span>'
        st.markdown(f'<div class="run"><div><b>{html.escape(r["name"])}</b> · {ago(r["created_at"])} · '
                    f'<a href="{r["html_url"]}" target="_blank">logs</a></div>{pill}</div>',
                    unsafe_allow_html=True)


def page_analytics():
    clips, posted, fb = load_clips(), load_posted(), load_feedback()
    st.title("Analytics")
    st.markdown('<div class="banner">YouTube views, comments and your best video show up here once your '
                'YouTube channel is connected. Below is what the bot has made so far.</div>',
                unsafe_allow_html=True)
    ups = sum(1 for v in fb.values() if v.get("rating", 0) > 0)
    tiles([("Total clips", len(clips)), ("Posted", len(posted)),
           ("Live clips", sum(c["source"] == "Live" for c in clips)),
           ("👍 rate", f"{round(100 * ups / len(fb))}%" if fb else "—")])
    st.write("")
    by = Counter(nice(c["streamer"]) for c in clips)
    if by:
        with st.container(border=True):
            st.subheader("Clips by streamer")
            df = pd.DataFrame(by.most_common(), columns=["Streamer", "Clips"])
            chart = alt.Chart(df).mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8, size=48).encode(
                x=alt.X("Streamer", sort="-y", axis=alt.Axis(labelAngle=0, title=None)),
                y=alt.Y("Clips", axis=alt.Axis(title=None, tickMinStep=1)),
                color=alt.value(alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                                             stops=[alt.GradientStop(color=PURPLE, offset=0),
                                                    alt.GradientStop(color=PINK, offset=1)])),
            ).properties(height=320).configure_view(strokeWidth=0).configure(background="transparent")
            st.altair_chart(chart, use_container_width=True)


def page_money():
    st.title("Money")
    st.markdown('<div class="banner">Turns on once the channel is in the YouTube Partner Program. '
                'Shorts need 1,000 subscribers + 10M Shorts views in 90 days.</div>', unsafe_allow_html=True)


PAGES = {
    "Ready to Post": ("🎬", page_ready),
    "Library": ("📚", page_library),
    "Make Clips": ("⚡", page_run),
    "Analytics": ("📈", page_analytics),
    "Money": ("💰", page_money),
}
if "page" not in st.session_state:
    st.session_state.page = "Ready to Post"

with st.sidebar:
    st.markdown('<div class="logo">🌴 <span>ClipBot</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="navlabel">MENU</div>', unsafe_allow_html=True)
    for name, (icon, _) in PAGES.items():
        if st.button(f"{icon}  {name}", key="nav" + name,
                     type="primary" if st.session_state.page == name else "secondary"):
            st.session_state.page = name
            st.rerun()
    st.markdown('<div class="navlabel">TOOLS</div>', unsafe_allow_html=True)
    if st.button("↻  Refresh", key="refresh"):
        refresh()
        st.rerun()

# ---- top bar: search + make clips ----
s1, s2 = st.columns([5, 1.2], vertical_alignment="center")
top_q = s1.text_input("Search", placeholder="🔍  Search clips, streamers…", label_visibility="collapsed")
if s2.button("Make clips now", type="primary", use_container_width=True, key="topmake"):
    gh.start_workflow("make.yml")
    load_runs.clear()
    st.toast("Started! New clips in about 10 minutes.")

if top_q:
    st.title(f"Results for “{top_q}”")
    grid(search(load_clips(), top_q), load_posted(), key="search", show_badge=True)
else:
    PAGES[st.session_state.page][1]()
