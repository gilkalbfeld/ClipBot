"""ClipBot dashboard. Run locally: streamlit run dashboard/streamlit_app.py"""
import html
import importlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import brain  # noqa: E402
from tools import youtube as ytapi  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import brain  # noqa: E402
from tools import youtube as ytapi  # noqa: E402
import data  # noqa: E402

importlib.reload(data)
importlib.reload(brain)
importlib.reload(ytapi)
importlib.reload(brain)
importlib.reload(ytapi)  # pick up changes to data.py on every update, no reboot needed
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
.ctitle {{ font-weight:700; font-size:1rem; line-height:1.35; color:#fff; margin:.35rem 0 .3rem; min-height:2.7em;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
.badge {{ display:inline-block; padding:.12rem .55rem; border-radius:999px; font-size:.72rem; font-weight:600; }}
.b-ready {{ background:rgba(255,62,165,.15); color:{PINK}; }}
.b-posted {{ background:rgba(139,92,246,.18); color:#b79cff; }}
.b-run {{ background:rgba(139,92,246,.2); color:#c4b0ff; }}
.b-ok {{ background:rgba(34,197,94,.15); color:#4ade80; }}
.b-bad {{ background:rgba(239,68,68,.15); color:#f87171; }}
h1 {{ font-weight:800 !important; letter-spacing:-.03em; }}
.meta {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.cardhead {{ display:flex; justify-content:space-between; align-items:center; margin-top:.2rem; }}
.cardhead .num {{ font-weight:800; color:#fff; font-size:.85rem; background:rgba(255,255,255,.08);
  padding:.1rem .5rem; border-radius:6px; }}
.cardhead .badges {{ display:flex; gap:.3rem; }}
.why {{ color:#8d86a0; font-size:.8rem; font-style:italic; margin:-.1rem 0 .3rem;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] {{ gap:.55rem; }}
div[data-testid="stPopover"] button {{ padding:.35rem .2rem; }}
.nothumb {{ aspect-ratio:4/3; border-radius:12px; background:linear-gradient(135deg,#2a1638,#1a1030);
  display:flex; align-items:center; justify-content:center; font-size:2.2rem; }}
div[data-testid="stImage"] img {{ border-radius:12px; aspect-ratio:4/3; object-fit:cover; }}
div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button {{ padding:.35rem .4rem; min-height:2.3rem; }}
[data-testid="stToolbarActions"], [data-testid="stStatusWidget"] {{ display:none; }}
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
    return gh.number_clips(gh.clips())


@st.cache_data(ttl=30)
def load_posted():
    return gh.posted()[0]


@st.cache_data(ttl=200)
def video_url(asset_id):
    return gh.asset_url(asset_id)


@st.cache_data(ttl=None, max_entries=500, show_spinner=False)
def thumb_bytes(asset_id):
    return gh.asset_bytes(asset_id)


@st.cache_data(ttl=None, max_entries=4, show_spinner="Loading video…")
def video_bytes(asset_id):
    return gh.asset_bytes(asset_id)


@st.cache_data(ttl=None, show_spinner=False)
def clip_info(asset_id):
    try:
        return json.loads(gh.asset_text(asset_id))
    except ValueError:
        return {}


@st.cache_data(ttl=None)
def post_text(asset_id):
    return gh.asset_text(asset_id)


@st.cache_data(ttl=30)
def load_feedback():
    return gh.feedback()


@st.cache_data(ttl=30)
def load_review():
    return gh.review()


@st.cache_data(ttl=20)
def load_runs():
    return gh.recent_runs(8)


def refresh():
    for f in (load_clips, load_posted, load_feedback, load_runs, load_review):
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
      button{{flex:1;padding:8px 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-radius:10px;border:1px solid rgba(255,255,255,.12);background:#1a1622;
        color:#e9e5f2;font-size:13px;font-weight:500;cursor:pointer}} button:hover{{border-color:#ff3ea5}}
    </style>
    <div class="r"><button id="t">📋 Title</button><button id="d">📋 Description</button></div>
    <script>
      function cp(txt, b, label){{
        const done=()=>{{b.textContent='Copied ✓';setTimeout(()=>b.textContent=label,1400)}};
        const fb=()=>{{const t=document.createElement('textarea');t.value=txt;document.body.appendChild(t);
          t.select();document.execCommand('copy');t.remove();done()}};
        if(navigator.clipboard){{navigator.clipboard.writeText(txt).then(done,fb)}}else{{fb()}}
      }}
      const T={json.dumps(title)}, D={json.dumps(desc)};
      document.getElementById('t').onclick=e=>cp(T,e.target,'📋 Title');
      document.getElementById('d').onclick=e=>cp(D,e.target,'📋 Description');
    </script>""", height=42)


# ---------------- pop-ups ----------------
def share_button(title, fname):
    """Opens the iPad share sheet with the video attached (→ YouTube or Save Video)."""
    components.html(f"""
    <style>body{{margin:0;font-family:Inter,sans-serif}}
      button{{width:100%;padding:12px;border:none;border-radius:10px;font-size:15px;font-weight:600;color:#fff;
        background:linear-gradient(90deg,#ff3ea5,#d946ef);cursor:pointer}} #s{{color:#a8a1b8;font-size:12px;margin-top:6px}}
    </style>
    <button id="b">⏳ Getting video ready…</button><div id="s"></div>
    <script>
      let file=null; const b=document.getElementById('b'), s=document.getElementById('s');
      function find(){{
        const vids=[...window.parent.document.querySelectorAll('div[role="dialog"] video, video')];
        const v=vids.reverse().find(x=>x.src||x.querySelector('source')); if(!v) return null;
        return v.src || v.querySelector('source').src;
      }}
      async function prep(n=0){{
        const src=find(); if(!src){{ if(n<20) return setTimeout(()=>prep(n+1),500); s.textContent='Video not found'; return; }}
        try{{ const blob=await (await fetch(src)).blob();
          file=new File([blob], {json.dumps(fname)}, {{type:'video/mp4'}});
          if(navigator.canShare && navigator.canShare({{files:[file]}})){{ b.textContent='📲 Share → YouTube / Save Video'; }}
          else {{ b.textContent='Sharing not supported here'; s.textContent='Use Download below instead.'; }}
        }}catch(e){{ b.textContent='Sharing not available'; s.textContent='Use Download below instead.'; }}
      }}
      b.onclick=async()=>{{ if(!file) return; try{{ await navigator.share({{files:[file], title:{json.dumps(title)}}}); }}
        catch(e){{ if(e.name!=='AbortError') s.textContent='Share failed: '+e.message+' — use Download below.'; }} }};
      prep();
    </script>""", height=78)


@st.dialog("Post to YouTube")
def post_dialog(c, title, desc):
    st.markdown("**1. Get the video on your iPad**")
    st.video(video_bytes(c["video_asset"]), format="video/mp4")
    share_button(title, f"{c['id']}.mp4")
    st.download_button("⬇️  Or download the file", video_bytes(c["video_asset"]), file_name=f"{c['id']}.mp4",
                       mime="video/mp4", use_container_width=True)
    st.markdown("**2. Copy the title and description**")
    copy_buttons(title, desc, "dlg" + c["id"])
    st.markdown("**3. Upload it on YouTube**")
    st.link_button("Open YouTube upload ↗", "https://www.youtube.com/upload", use_container_width=True)
    st.caption("On iPad you can also open the YouTube app → ＋ → Short → pick the downloaded video.")
    st.markdown("**4. Done?**")
    yt = st.text_input("YouTube link (optional)", placeholder="https://youtube.com/shorts/…")
    if st.button("✅  Mark as posted", use_container_width=True, key="dlgposted" + c["id"]):
        try:
            gh.set_posted(c["id"], yt)
        except Exception as e:
            st.error(f"Couldn't save: {str(e)[:200]}")
            return
        refresh()
        st.rerun()


@st.dialog("✂️ Fix timing")
def recut_dialog(c, title):
    st.write(f"**{title or c['id']}**")
    st.caption("ClipBot goes back to the saved stream and cuts this moment again. "
               "Works for a few days after the stream (Twitch deletes old streams).")
    start = st.slider("Start", -30, 30, 0, step=2,
                      help="Negative = start earlier (more lead-up). Positive = start later.",
                      format="%+d s")
    end = st.slider("End", -20, 40, 0, step=2,
                    help="Positive = keep going longer. Negative = end sooner.", format="%+d s")
    st.caption(f"Start {abs(start)}s {'earlier' if start < 0 else 'later'} · "
               f"end {abs(end)}s {'later' if end > 0 else 'sooner'}" if (start or end) else "Move a slider")
    if st.button("✂️  Re-cut clip", type="primary", use_container_width=True, disabled=not (start or end)):
        gh.start_workflow("recut.yml", {"clip_id": c["id"], "start_shift": str(start), "end_shift": str(end)})
        st.session_state.setdefault("recutting", set()).add(c["id"])
        st.rerun()


@st.dialog("Delete low-score clips?")
def bulk_delete_dialog(clips):
    st.write(f"This permanently deletes **{len(clips)} clips** the AI scored under 5/10 "
             "(posted clips are never included). It can't be undone.")
    a, b = st.columns(2)
    if a.button("Cancel", use_container_width=True):
        st.rerun()
    if b.button(f"🗑 Delete {len(clips)}", type="primary", use_container_width=True):
        bar = st.progress(0.0)
        for i, c in enumerate(clips):
            gh.delete_clip(c)
            bar.progress((i + 1) / len(clips))
        refresh()
        st.rerun()


@st.dialog("Delete this clip?")
def delete_dialog(c, title):
    st.write(f"**{title or c['id']}**")
    st.write("This permanently removes the video. It can't be undone. "
             "ClipBot will count it as a 👎 and learn from it.")
    a, b = st.columns(2)
    if a.button("Cancel", use_container_width=True):
        st.rerun()
    if b.button("🗑  Yes, delete", type="primary", use_container_width=True):
        gh.delete_clip(c)
        refresh()
        st.rerun()


# ---------------- clip card ----------------
def card(c, posted, show_badge=False, mode="library"):
    title, desc = split_post(post_text(c["post_asset"])) if "post_asset" in c else ("", "")
    is_posted = c["id"] in posted
    fb = load_feedback().get(c["id"], {})
    info = clip_info(c["json_asset"]) if "json_asset" in c else {}
    playing = st.session_state.get("playing") == c["id"]
    with st.container(border=True):
        # ---- media
        if playing:
            st.video(video_bytes(c["video_asset"]), format="video/mp4", autoplay=True)
            if st.button("✕ Close", key="close" + c["id"], use_container_width=True):
                st.session_state.playing = None
                st.rerun()
        else:
            if "thumb_asset" in c:
                st.image(thumb_bytes(c["thumb_asset"]), use_container_width=True)
            else:
                st.markdown('<div class="nothumb">🎬</div>', unsafe_allow_html=True)
            if st.button("▶  Play", key="play" + c["id"], use_container_width=True):
                st.session_state.playing = c["id"]
                st.rerun()

        # ---- info
        name = nice(c["streamer"])
        badges = ""
        if info.get("ai_score") is not None:
            sc = info["ai_score"]
            col = "b-ok" if sc >= 7 else ("b-ready" if sc >= 5 else "b-bad")
            badges += f'<span class="badge {col}">🤖 {sc:g}</span>'
        if show_badge:
            rv = load_review().get(c["id"], {}).get("status")
            badges += ('<span class="badge b-posted">Posted</span>' if is_posted
                       else '<span class="badge b-ok">Approved</span>' if rv == "approved"
                       else '<span class="badge b-run">Kept</span>' if rv == "library"
                       else '<span class="badge b-ready">New</span>')
        src = '<span class="live">● Live</span>' if c["source"] == "Live" else "Top clip"
        st.markdown(
            f'<div class="cardhead"><span class="num">#{c.get("num", "")}</span>'
            f'<span class="badges">{badges}</span></div>'
            f'<div class="ctitle">{html.escape(title or c["id"])}</div>'
            f'<div class="meta"><span class="avatar">{html.escape(name[:1].upper())}</span>'
            f'{html.escape(name)} · {src} · {ago(c["made_at"])}</div>'
            + (f'<div class="why">{html.escape(info["ai_reason"])}</div>' if info.get("ai_reason") else ""),
            unsafe_allow_html=True)

        # ---- Ready to Post: only the posting buttons
        if mode == "ready":
            r1, r2, r3 = st.columns(3, gap="small")
            if r1.button("🚀 Post", key="p" + c["id"], type="primary", use_container_width=True):
                post_dialog(c, title, desc)
            if r2.button("📚 Library", key="lib" + c["id"], use_container_width=True,
                         help="Not posting this one — send it back to the Library"):
                gh.set_review(c, "library")
                refresh()
                st.rerun()
            if r3.button("✅ Posted", key="mp" + c["id"], use_container_width=True,
                         help="Already uploaded it? Mark it posted"):
                mark_posted(c)
            return

        # ---- feedback
        r = fb.get("rating", 0)
        up, down = st.columns(2, gap="small")
        if up.button("👍 Good", key="up" + c["id"], type="primary" if r > 0 else "secondary",
                     use_container_width=True):
            gh.set_feedback(c, 1, st.session_state.get("c" + c["id"], fb.get("comment", "")))
            load_feedback.clear()
            st.rerun()
        if down.button("👎 Bad", key="dn" + c["id"], type="primary" if r < 0 else "secondary",
                       use_container_width=True):
            gh.set_feedback(c, -1, st.session_state.get("c" + c["id"], fb.get("comment", "")))
            load_feedback.clear()
            st.rerun()
        comment = st.text_input("Feedback", value=fb.get("comment", ""), placeholder="Add a note for ClipBot…",
                                label_visibility="collapsed", key="c" + c["id"])
        if r and comment != fb.get("comment", ""):
            gh.set_feedback(c, r, comment)
            load_feedback.clear()
            st.toast("Note saved")

        # ---- main actions + "more" menu
        if mode == "new":
            a1, a2, a3 = st.columns([2, 2, 1], gap="small")
            if a1.button("✅ Approve", key="ap" + c["id"], type="primary", use_container_width=True,
                         help="Moves it to Ready to Post"):
                gh.set_review(c, "approved")
                refresh()
                st.rerun()
            if a2.button("📚 Keep", key="kp" + c["id"], use_container_width=True,
                         help="Not posting it, but keep it in your Library"):
                gh.set_review(c, "library")
                refresh()
                st.rerun()
            more = a3
        else:
            a1, a3 = st.columns([4, 1], gap="small")
            if is_posted:
                if a1.button("↩ Not posted", key="u" + c["id"], use_container_width=True):
                    gh.set_posted(c["id"], undo=True)
                    refresh()
                    st.rerun()
            elif a1.button("🚀 Post", key="p" + c["id"], type="primary", use_container_width=True):
                post_dialog(c, title, desc)
            more = a3
        with more.popover("⋯", use_container_width=True):
            if c["id"] in st.session_state.get("recutting", set()):
                st.caption("✂️ Re-cutting… ready in ~5 min")
            elif st.button("✂️ Fix timing", key="fix" + c["id"], use_container_width=True):
                recut_dialog(c, title)
            if not is_posted and mode != "new" and st.button("✅ Mark posted", key="mp" + c["id"],
                                                             use_container_width=True):
                mark_posted(c)
            copy_buttons(title, desc, c["id"])
            if st.button("🗑 Delete", key="del" + c["id"], use_container_width=True):
                delete_dialog(c, title)


def mark_posted(c):
    try:
        gh.set_posted(c["id"])
    except Exception as e:
        st.error(f"Couldn't save: {str(e)[:200]}")
    else:
        refresh()
        st.rerun()


def grid(clips, posted, per_page=12, key="g", show_badge=False, mode="library"):
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
            card(c, posted, show_badge, mode)
    if pages > 1:
        st.number_input("Page", 1, pages, key=key + "page")


STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "with", "is", "clip", "clips", "where",
        "that", "this", "it", "for", "gta", "6"}


def search(clips, q):
    """Finds clips by what happens in them (AI notes), title, streamer or date. Best matches first."""
    m = re.fullmatch(r"\s*#?\s*(\d+)\s*", q)
    if m:   # "#12" or "12" -> that clip
        return [c for c in clips if c.get("num") == int(m.group(1))]
    words = [w for w in q.lower().replace(",", " ").split() if w not in STOP] or q.lower().split()
    scored = []
    for c in clips:
        title = split_post(post_text(c["post_asset"]))[0] if "post_asset" in c else ""
        info = clip_info(c["json_asset"]) if "json_asset" in c else {}
        hay = " ".join([c["id"], c["streamer"], nice(c["streamer"]), title, c["made_at"],
                        info.get("ai_summary", ""), info.get("ai_reason", ""), " ".join(info.get("ai_tags", [])),
                        info.get("stream_title", "")]).lower()
        hits = sum(1 for w in words if w in hay)
        if hits and hits >= max(1, len(words) // 2):
            scored.append((hits, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored]


# ---------------- pages ----------------
def ai_score(c):
    return clip_info(c["json_asset"]).get("ai_score") if "json_asset" in c else None


def sort_and_cleanup(out, posted, key):
    """Sort by AI score + one-tap delete of everything the AI scored under 5."""
    a, b, d = st.columns([3, 2, 2], vertical_alignment="center")
    sort = a.radio("Sort", ["Newest", "🤖 Best first", "🤖 Worst first"], horizontal=True,
                   label_visibility="collapsed", key=key + "sort")
    if sort != "Newest":
        scored = [c for c in out if ai_score(c) is not None]
        rest = [c for c in out if ai_score(c) is None]
        out = sorted(scored, key=ai_score, reverse=sort.startswith("🤖 Best")) + rest
    low = [c for c in out if (ai_score(c) is not None and ai_score(c) < 5 and c["id"] not in posted)]
    only_low = b.toggle(f"Only bad ones ({len(low)})", key=key + "low", help="AI score under 5")
    if only_low:
        out = sorted(low, key=ai_score)
    if low and d.button(f"🗑 Delete {len(low)} bad clips", use_container_width=True, key=key + "bulk"):
        bulk_delete_dialog(low)
    return out


def page_new():
    clips, posted, review = load_clips(), load_posted(), load_review()
    new = [c for c in clips if c["id"] not in review and c["id"] not in posted]
    st.title("New Clips")
    st.caption("Fresh clips from the bot. ✅ Approve → Ready to Post · 📚 Keep → Library only · 🗑 Delete.")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tiles([("To review", len(new)), ("Made today", sum(c["made_at"][:10] == today for c in clips)),
           ("Approved", sum(1 for v in review.values() if v.get("status") == "approved"))])
    st.write("")
    new = sort_and_cleanup(new, posted, "new")
    grid(new, posted, key="new", mode="new")


def page_ready():
    clips, posted, review = load_clips(), load_posted(), load_review()
    todo = [c for c in clips if review.get(c["id"], {}).get("status") == "approved" and c["id"] not in posted]
    st.title("Ready to Post")
    tiles([("Approved, waiting to post", len(todo)), ("Posted", len(posted)),
           ("In New Clips", sum(1 for c in clips if c["id"] not in review and c["id"] not in posted))])
    st.write("")
    if not todo:
        st.info("Nothing approved yet — go to 🆕 New Clips and approve the good ones.")
    grid(todo, posted, key="ready", mode="ready")


def page_library():
    clips, posted = load_clips(), load_posted()
    st.title("Library")
    f1, f2, f3 = st.columns([2, 1, 1])
    q = f1.text_input("Search", placeholder="Search streamer, title, date…")
    streamers = sorted({c["streamer"] for c in clips if c["streamer"]})
    who = f2.selectbox("Streamer", ["All"] + streamers, format_func=lambda s: s if s == "All" else nice(s))
    status = f3.selectbox("Status", ["All", "New", "Approved", "Kept", "Posted"])
    review = load_review()

    def status_of(c):
        if c["id"] in posted:
            return "Posted"
        return {"approved": "Approved", "library": "Kept"}.get(review.get(c["id"], {}).get("status"), "New")
    out = [c for c in clips
           if (who == "All" or c["streamer"] == who) and (status == "All" or status_of(c) == status)]
    if q:
        out = search(out, q)

    st.caption(f"{len(out)} clips")
    out = sort_and_cleanup(out, posted, "lib")
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

    chat_box()

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


STREAMERS = ["ishowspeed (YouTube)", "lacy", "kaicenat", "xqc", "jynxzi", "caseoh_", "adinross", "ohnepixel"]


def chat_box():
    st.write("")
    with st.container(border=True):
        st.subheader("💬 Talk to ClipBot")
        st.caption("Tell it what you notice — e.g. “clips start too early”, “stop clipping Jynxzi”, "
                   "“use fill layout more”. It remembers and the bot follows it on every run.")
        key = st.secrets.get("GEMINI_API_KEY", "")
        if not key:
            st.warning("Add GEMINI_API_KEY in Settings → Secrets to turn this on.")
            return
        ins, sha = gh.read_json("instructions.json")
        history = ins.get("chat", [])
        for m in history[-10:]:
            with st.chat_message("user" if m["role"] == "user" else "assistant",
                                 avatar=None if m["role"] == "user" else "🌴"):
                st.write(m["text"])
                for ch in m.get("changes", []):
                    st.caption("✓ " + ch)
        if ins.get("rules"):
            with st.expander(f"📌 What ClipBot remembers ({len(ins['rules'])})"):
                for r in ins["rules"]:
                    st.write("• " + r)
        msg = st.chat_input("Message ClipBot… (refer to clips by number, e.g. “#12 starts too late”)")
        if msg:
            learned, _ = gh.read_json("learned.json")
            by_num = {c.get("num"): c for c in load_clips()}
            mentioned = [int(n) for n in re.findall(r"(?:#|clip\s*#?\s*)(\d+)", msg, re.I)]
            ctx = []
            for n in mentioned:
                c = by_num.get(n)
                if c:
                    info = clip_info(c["json_asset"]) if "json_asset" in c else {}
                    t = split_post(post_text(c["post_asset"]))[0] if "post_asset" in c else ""
                    ctx.append({"clip": n, "streamer": c["streamer"], "title": t,
                                "what_happens": info.get("ai_summary") or info.get("ai_reason", ""),
                                "ai_score": info.get("ai_score"), "my_feedback": load_feedback().get(c["id"])})
            with st.spinner("ClipBot is thinking…"):
                try:
                    result = brain.ask(key, msg, history, ins, learned, load_feedback(), STREAMERS, ctx)
                except Exception as e:
                    st.error(f"Couldn't reach Gemini: {str(e)[:300]}")
                    return
            changes = brain.apply(ins, result)
            for act in result.get("clip_actions") or []:   # things to do to specific clips
                c = by_num.get(act.get("clip"))
                if not c:
                    continue
                n = act["clip"]
                if act.get("rating") in (1, -1):
                    gh.set_feedback(c, act["rating"], act.get("comment", ""))
                    changes.append(f"#{n} rated {'👍' if act['rating'] > 0 else '👎'}")
                rc = act.get("recut") or {}
                ss, es = int(rc.get("start_shift") or 0), int(rc.get("end_shift") or 0)
                if ss or es:
                    gh.start_workflow("recut.yml", {"clip_id": c["id"], "start_shift": str(max(-30, min(30, ss))),
                                                    "end_shift": str(max(-20, min(40, es)))})
                    changes.append(f"#{n} re-cutting (start {ss:+d}s, end {es:+d}s) — ready in ~5 min")
                if act.get("review") in ("approved", "library"):
                    gh.set_review(c, act["review"])
                    changes.append(f"#{n} → {'Ready to Post' if act['review'] == 'approved' else 'Library'}")
            refresh()
            history += [{"role": "user", "text": msg},
                        {"role": "bot", "text": result.get("reply", ""), "changes": changes}]
            ins["chat"] = history[-40:]
            gh.write_json("instructions.json", ins, sha, "ClipBot chat: " + msg[:60])
            st.rerun()


YT_ID, YT_SECRET = st.secrets.get("YT_CLIENT_ID", ""), st.secrets.get("YT_CLIENT_SECRET", "")
YT_REFRESH, YT_REDIRECT = st.secrets.get("YT_REFRESH_TOKEN", ""), st.secrets.get("YT_REDIRECT_URI", "")


@st.cache_data(ttl=900, show_spinner="Loading YouTube stats…")
def yt_snapshot():
    return ytapi.snapshot(ytapi.YouTube(YT_ID, YT_SECRET, YT_REFRESH))


def youtube_section():
    """Connect YouTube, or show real channel stats."""
    code = st.query_params.get("code")
    if code and YT_ID:
        try:
            tok = ytapi.exchange_code(YT_ID, YT_SECRET, YT_REDIRECT, code)
            st.success("YouTube connected! One last step: copy this and add it to BOTH Streamlit Secrets and "
                       "GitHub Secrets as YT_REFRESH_TOKEN.")
            st.code(f'YT_REFRESH_TOKEN = "{tok.get("refresh_token", "")}"', language=None)
        except Exception as e:
            st.error(f"Couldn't connect: {str(e)[:200]}")
        st.query_params.clear()
        return None
    if not (YT_ID and YT_SECRET and YT_REDIRECT):
        st.markdown('<div class="banner">Connect your YouTube channel to see real views, comments and your '
                    'best videos here. (Needs YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REDIRECT_URI in Secrets.)</div>',
                    unsafe_allow_html=True)
        return None
    if not YT_REFRESH:
        st.link_button("🔗 Connect YouTube", ytapi.auth_url(YT_ID, YT_REDIRECT), type="primary")
        st.caption("If Google says the app isn't verified: tap Advanced → Go to ClipBot. It's your own app.")
        return None
    try:
        snap = yt_snapshot()
    except Exception as e:
        st.error(f"Couldn't load YouTube stats: {str(e)[:200]}")
        return None
    ch, vids = snap["channel"], snap["videos"]
    tiles([("Subscribers", f"{ch['subscribers']:,}"), ("Total views", f"{ch['views']:,}"),
           ("Comments", f"{sum(v['comments'] for v in vids):,}"), ("Videos", ch["videos"])])
    if vids:
        best = max(vids, key=lambda v: v["views"])
        st.write("")
        with st.container(border=True):
            st.markdown(f"**🏆 Best video:** [{html.escape(best['title'])}]({best['url']}) — "
                        f"{best['views']:,} views · {best['likes']:,} likes · {best['comments']:,} comments")
        if snap.get("daily"):
            df = pd.DataFrame(snap["daily"])
            with st.container(border=True):
                st.subheader("Views per day")
                st.bar_chart(df.set_index("day")["views"], color=PINK)
        with st.container(border=True):
            st.subheader("All videos")
            df = pd.DataFrame([{"Title": v["title"], "Views": v["views"], "Likes": v["likes"],
                                "Comments": v["comments"],
                                "Avg % watched": round(v.get("averageViewPercentage", 0) or 0),
                                "Subs gained": v.get("subscribersGained", 0), "Posted": v["published"][:10]}
                               for v in sorted(vids, key=lambda v: -v["views"])])
            st.dataframe(df, use_container_width=True, hide_index=True)
    return snap


def page_analytics():
    clips, posted, fb = load_clips(), load_posted(), load_feedback()
    st.title("Analytics")
    youtube_section()
    report, _ = gh.read_json("reports/latest.json")
    if report.get("text"):
        with st.container(border=True):
            st.subheader(f"📰 Daily report — {report.get('date', '')}")
            st.markdown(report["text"])
    st.subheader("ClipBot")
    ups = sum(1 for v in fb.values() if v.get("rating", 0) > 0)
    tiles([("Total clips", len(clips)), ("Posted", len(posted)),
           ("Live clips", sum(c["source"] == "Live" for c in clips)),
           ("👍 rate", f"{round(100 * ups / len(fb))}%" if fb else "—")])
    st.write("")
    learned, _ = gh.read_json("learned.json")
    with st.container(border=True):
        st.subheader("🧠 What ClipBot learned")
        if learned:
            for n in learned.get("notes", []):
                st.write("• " + n)
            sw = learned.get("streamer_weight", {})
            if sw:
                st.caption("Streamer priority (higher = watched/ranked first): " +
                           ", ".join(f"{nice(k)} ×{v}" for k, v in sorted(sw.items(), key=lambda x: -x[1])))
            st.caption(f"Based on {learned.get('ratings', 0)} ratings · updated {ago(learned['updated'])}")
        else:
            st.write("Learning kicks in on the next bot run. Keep rating clips 👍/👎.")
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
    "New Clips": ("🆕", page_new),
    "Ready to Post": ("🎬", page_ready),
    "Library": ("📚", page_library),
    "Make Clips": ("⚡", page_run),
    "Analytics": ("📈", page_analytics),
    "Money": ("💰", page_money),
}
if "page" not in st.session_state:
    st.session_state.page = "New Clips"
if st.query_params.get("code"):   # coming back from the YouTube login
    st.session_state.page = "Analytics"

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
top_q = s1.text_input("Search", placeholder="🔍  Search what happens… e.g. “Lucia fishing”, “police chase”, “Kai crash”", label_visibility="collapsed")
if s2.button("Make clips now", type="primary", use_container_width=True, key="topmake"):
    gh.start_workflow("make.yml")
    load_runs.clear()
    st.toast("Started! New clips in about 10 minutes.")

if top_q:
    st.title(f"Results for “{top_q}”")
    grid(search(load_clips(), top_q), load_posted(), key="search", show_badge=True)
else:
    PAGES[st.session_state.page][1]()
