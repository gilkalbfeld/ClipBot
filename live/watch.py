"""
Live watcher: records streams while they're live, reads chat in real time,
and cuts a clip whenever chat blows up.

Run:  python live/watch.py            (runs until RUN_MINUTES is up)
"""
import glob
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.learned import LEARNED, weighted_choice, streamer_weight, spike_mult  # noqa: E402

# ---------------- settings (edit anytime) ----------------

# Who to watch, in priority order. platform: "youtube" or "twitch".
WATCHLIST = [
    {"name": "ishowspeed", "platform": "youtube", "channel": "@IShowSpeed"},
    {"name": "lacy", "platform": "twitch"},
    {"name": "kaicenat", "platform": "twitch"},
    {"name": "xqc", "platform": "twitch"},
    {"name": "jynxzi", "platform": "twitch"},
    {"name": "caseoh_", "platform": "twitch"},
    {"name": "adinross", "platform": "twitch"},
    {"name": "ohnepixel", "platform": "twitch"},
]
TWITCH_GTA_ONLY = True     # Twitch: only record when they're in a GTA category
MAX_STREAMS = 4            # how many streams to record at once
CHECK_EVERY = 120          # seconds between "who's live?" checks
RUN_MINUTES = int(os.environ.get("RUN_MINUTES", "330"))

SECONDS_BEFORE = LEARNED.get("seconds_before", 40)   # clip length before chat exploded (learned from feedback)
SECONDS_AFTER = LEARNED.get("seconds_after", 12)     # and after
SEGMENT = 4                # recording chunk size in seconds
KEEP_SECONDS = 240         # how much recent stream to keep on disk

BUCKET = 5                 # chat is counted in 5-second buckets
SPIKE_X = LEARNED.get("spike_x", 2.5)              # chat must be this many times busier than normal
MIN_HYPE = LEARNED.get("min_hype", 25)              # ...and at least this much hype in 10 seconds
COOLDOWN = LEARNED.get("cooldown", 90)              # seconds between clips from the same stream
RENDERERS = 2              # clips finished at the same time
WARMUP = 60                # seconds of chat to learn what "normal" is

# Words/emotes that mean something funny or crazy just happened
HYPE_WORDS = [
    "lmao", "lmfao", "lol", "lul", "kekw", "omegalul", "icant", "💀", "😂", "🤣",
    "😭", "clip", "w ", "bro", "nah", "wtf", "omg", "noway", "no way", "😳",
    "aware", "pogger", "pog", "hahaha", "dead", "crazy",
]

OUT_DIR = "output/live"
WORK_DIR = "live_work"
RELEASE_TAG = os.environ.get("RELEASE_TAG", "")  # if set, upload clips here as they're made

# ---------------------------------------------------------

stop_at = time.time() + RUN_MINUTES * 60
render_queue = queue.Queue()
stats = {"rejected": 0}
recent_titles = []   # so the AI doesn't keep writing the same title
active = {}          # name -> Watcher
lock = threading.Lock()


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def hype_of(text):
    t = text.lower() + " "
    return 1 + 2 * sum(1 for w in HYPE_WORDS if w in t)


# ---------------- who's live? ----------------

def twitch_live(names):
    """Returns {login: (title, game)} for Twitch streamers that are live."""
    from fetch.twitch_clips import get_token, CLIENT_ID
    if not names:
        return {}
    headers = {"Client-Id": CLIENT_ID, "Authorization": f"Bearer {get_token()}"}
    import requests
    r = requests.get(
        "https://api.twitch.tv/helix/streams",
        headers=headers,
        params=[("user_login", n) for n in names],
        timeout=20,
    )
    out = {}
    for s in r.json().get("data", []):
        out[s["user_login"].lower()] = (s["title"], s.get("game_name", ""))
    return out


def youtube_live(channel):
    """Returns (video_url, title) if the YouTube channel is live, else None."""
    url = f"https://www.youtube.com/{channel}/live"
    p = subprocess.run(
        ["yt-dlp", "--skip-download", "--print", "%(is_live)s|%(webpage_url)s|%(title)s", url],
        capture_output=True, text=True, timeout=90,
    )
    line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
    if line.startswith("True|"):
        _, vurl, title = line.split("|", 2)
        return vurl, title
    if p.stderr and "not currently live" not in p.stderr and "will begin" not in p.stderr:
        log(f"[{channel}] live check note:", p.stderr.strip().splitlines()[-1][:200])
    return None


# ---------------- one stream ----------------

class Watcher:
    def __init__(self, name, platform, url, title):
        self.name, self.platform, self.url, self.title = name, platform, url, title
        self.dir = os.path.join(WORK_DIR, name)
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir, exist_ok=True)
        self.buckets = deque(maxlen=60)   # (bucket_start, hype)
        self.started = time.time()
        self.last_clip = 0
        self.alive = True
        self.procs = []

    # --- recording: yt-dlp pipes the live stream into ffmpeg, which saves 4s chunks
    def record(self):
        if self.platform == "twitch":
            # streamlink skips Twitch commercial breaks (feedback: "majority of this clip is a commercial break")
            cmd = ["streamlink", "--twitch-disable-ads", "--stdout", self.url, "1080p60,1080p,936p60,720p60,720p,best"]
        else:
            cmd = ["yt-dlp", "-q", "--no-part", "-f", "best[height<=1080]/best", "-o", "-", self.url]
        dl = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        ff = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-c", "copy", "-map", "0",
             "-f", "segment", "-segment_time", str(SEGMENT), "-reset_timestamps", "1",
             os.path.join(self.dir, "%07d.ts")],
            stdin=dl.stdout, stderr=subprocess.DEVNULL,
        )
        self.procs = [dl, ff]
        log(f"[{self.name}] recording {self.url}")
        while self.alive and time.time() < stop_at and ff.poll() is None:
            self.cleanup()
            time.sleep(10)
        log(f"[{self.name}] recording stopped")
        self.alive = False
        for p in self.procs:
            if p.poll() is None:
                p.kill()

    def cleanup(self):
        segs = sorted(glob.glob(os.path.join(self.dir, "*.ts")))
        keep = KEEP_SECONDS // SEGMENT
        for f in segs[:-keep]:
            try:
                os.remove(f)
            except OSError:
                pass

    # --- chat
    def add_message(self, text):
        now = time.time()
        b = int(now // BUCKET) * BUCKET
        if self.buckets and self.buckets[-1][0] == b:
            self.buckets[-1][1] += hype_of(text)
        else:
            self.buckets.append([b, hype_of(text)])
            self.check_spike(now)

    def check_spike(self, now):
        # look at the last two finished buckets (10s) vs. the ones before
        done = list(self.buckets)[:-1]
        if len(done) < 6 or now - self.started < WARMUP:
            return
        recent = done[-1][1] + done[-2][1]
        older = [h for _, h in done[:-2]]
        normal = (sum(older) / len(older)) * 2
        need = SPIKE_X * spike_mult(self.name)   # pickier for streamers you rate 👎
        if recent >= MIN_HYPE and recent >= need * normal and now - self.last_clip > COOLDOWN:
            self.last_clip = now
            strength = round(recent / max(normal, 1), 1)
            log(f"[{self.name}] 🔥 chat spike x{strength} (hype {recent}) — clipping")
            threading.Thread(target=self.cut, args=(now, strength), daemon=True).start()

    def twitch_chat(self):
        s = socket.socket()
        s.settimeout(300)
        s.connect(("irc.chat.twitch.tv", 6667))
        s.send(b"PASS SCHMOOPIIE\r\nNICK justinfan" + str(int(time.time()) % 99999).encode() + b"\r\n")
        s.send(f"JOIN #{self.name}\r\n".encode())
        buf = ""
        while self.alive and time.time() < stop_at:
            try:
                data = s.recv(65536).decode("utf-8", "ignore")
            except socket.timeout:
                continue
            if not data:
                break
            buf += data
            *lines, buf = buf.split("\r\n")
            for line in lines:
                if line.startswith("PING"):
                    s.send(b"PONG :tmi.twitch.tv\r\n")
                elif " PRIVMSG " in line:
                    self.add_message(line.split(" :", 1)[-1])
        s.close()

    def youtube_chat(self):
        from chat_downloader import ChatDownloader
        for msg in ChatDownloader().get_chat(self.url):
            if not self.alive or time.time() > stop_at:
                break
            self.add_message(msg.get("message") or "")

    def chat(self):
        while self.alive and time.time() < stop_at:
            try:
                self.youtube_chat() if self.platform == "youtube" else self.twitch_chat()
            except Exception as e:
                log(f"[{self.name}] chat error, retrying:", str(e)[:150])
                time.sleep(10)

    # --- cut a clip out of the recent recording
    def cut(self, spike_time, strength):
        time.sleep(SECONDS_AFTER + SEGMENT)
        segs = [
            f for f in sorted(glob.glob(os.path.join(self.dir, "*.ts")))
            if spike_time - SECONDS_BEFORE <= os.path.getmtime(f) <= spike_time + SECONDS_AFTER + SEGMENT
        ]
        if len(segs) < 3:
            log(f"[{self.name}] not enough recording for this spike, skipped")
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        clip_id = f"{self.name}_{stamp}"
        raw = os.path.join(WORK_DIR, clip_id + ".mp4")
        lst = raw + ".txt"
        with open(lst, "w") as f:
            f.writelines(f"file '{os.path.abspath(s)}'\n" for s in segs)
        r = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
             "-c", "copy", "-bsf:a", "aac_adtstoasc", raw]
        )
        if r.returncode == 0:
            render_queue.put({
                "id": clip_id, "src": raw, "name": self.name, "platform": self.platform,
                "url": self.url, "stream_title": self.title, "strength": strength,
                "time": stamp,
                # wall-clock window, so the clip can be re-cut later from the saved stream
                "window_utc": [spike_time - SECONDS_BEFORE, spike_time + SECONDS_AFTER],
            })


# ---------------- turning raw cuts into finished Shorts ----------------

def renderer():
    import random
    from faster_whisper import WhisperModel
    from edit.make_vertical import LAYOUTS, CAPTION_WORDS, make_srt, make_vertical
    from edit.download import has_audio
    from edit.titles import make_title, make_description, make_tags
    from tools.judge import judge, judge_text, transcribe

    model = WhisperModel("base", device="cpu", compute_type="int8")
    os.makedirs(OUT_DIR, exist_ok=True)
    while True:
        job = render_queue.get()
        if job is None:
            break
        try:
            # ---- AI judge: does something actually happen in this clip?
            verdict = judge(job["src"], job["name"], job["platform"], SECONDS_BEFORE)
            if not verdict:   # video quota used up -> read the transcript instead
                verdict = judge_text(transcribe(job["src"], model), job["name"], job["platform"],
                                     job["stream_title"], recent_titles)
            if verdict:
                log(f"[{job['name']}] 🤖 AI score {verdict['score']}/10 — {verdict.get('reason', '')}")
                if verdict["score"] < MIN_AI_SCORE:
                    log(f"[{job['name']}] ✗ thrown out (below {MIN_AI_SCORE})")
                    stats["rejected"] += 1
                    continue
                ms, me = verdict.get("moment_start"), verdict.get("moment_end")
                if AI_TRIM and isinstance(ms, (int, float)) and isinstance(me, (int, float)) and me - ms >= 6:
                    a, b = max(0, ms - 3), me + 3
                    trimmed = job["src"] + ".trim.mp4"
                    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{a:.2f}", "-to", f"{b:.2f}",
                                        "-i", job["src"], "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                                        "-c:a", "aac", trimmed])
                    if r.returncode == 0:
                        os.replace(trimmed, job["src"])
                        w0 = job["window_utc"][0]
                        job["window_utc"] = [w0 + a, w0 + b]
            layout = weighted_choice(LAYOUTS, "layout_weight")
            words_per = weighted_choice(CAPTION_WORDS, "words_weight")
            srt = os.path.join(OUT_DIR, job["id"] + ".srt")
            has_caps = has_audio(job["src"]) and make_srt(model, job["src"], srt, words_per)
            out = os.path.join(OUT_DIR, job["id"] + "_vertical.mp4")
            make_vertical(job["src"], srt, out, has_caps, layout)

            # Title/description helpers expect a clip-like dict
            clip = {"broadcaster_name": job["name"], "title": "", "url": job["url"]}
            title = (verdict or {}).get("title") or make_title(clip)   # AI writes a title about what happens
            recent_titles.append(title)
            desc = make_description(clip, title, (verdict or {}).get("tags", []))
            info = {
                "youtube_title": title,
                "youtube_description": desc,
                "youtube_tags": make_tags(clip),
                "source_type": "live_chat_spike",
                "streamer": job["name"],
                "platform": job["platform"],
                "stream_title": job["stream_title"],
                "source_url": job["url"],
                "hype_strength": job["strength"],
                "made_at_utc": job["time"],
                "window_utc": job["window_utc"],
                "ai_score": verdict["score"] if verdict else None,
                "ai_reason": verdict.get("reason", "") if verdict else "",
                "ai_problems": verdict.get("problems", []) if verdict else [],
                "ai_summary": verdict.get("summary", "") if verdict else "",
                "ai_tags": verdict.get("tags", []) if verdict else [],
                "captions": bool(has_caps),
                "layout": layout,
                "caption_words": words_per,
            }
            with open(os.path.join(OUT_DIR, job["id"] + ".json"), "w") as f:
                json.dump(info, f, indent=2)
            with open(os.path.join(OUT_DIR, job["id"] + "_post.txt"), "w", encoding="utf-8") as f:
                f.write(desc)
            thumb = os.path.join(OUT_DIR, job["id"] + "_thumb.jpg")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "2", "-i", out, "-frames:v", "1",
                            "-vf", "crop=iw:iw*3/4:0:(ih-iw*3/4)/2,scale=640:-2", "-q:v", "4", thumb])
            log(f"✅ clip ready: {out} | {title}")
            if RELEASE_TAG:
                subprocess.run(["gh", "release", "upload", RELEASE_TAG, out, thumb,
                                os.path.join(OUT_DIR, job["id"] + "_post.txt"),
                                os.path.join(OUT_DIR, job["id"] + ".json"), "--clobber"])
        except Exception as e:
            log("render failed:", job["id"], str(e)[:200])
        finally:
            try:
                os.remove(job["src"])
            except OSError:
                pass


# ---------------- main loop ----------------

def start(name, platform, url, title):
    w = Watcher(name, platform, url, title)
    active[name] = w
    threading.Thread(target=w.record, daemon=True).start()
    threading.Thread(target=w.chat, daemon=True).start()


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    renderers = [threading.Thread(target=renderer, daemon=True) for _ in range(RENDERERS)]
    for rt in renderers:
        rt.start()
    log(f"Live watcher running for {RUN_MINUTES} minutes")

    # streamers you rate 👍 get watched first when there are more live than MAX_STREAMS
    WATCHLIST.sort(key=lambda s: -streamer_weight(s["name"]) if s["name"] != "ishowspeed" else -99)
    log("learned:", "; ".join(LEARNED.get("notes", [])) or "nothing yet")
    while time.time() < stop_at:
        for n in [n for n, w in active.items() if not w.alive]:
            del active[n]
        try:
            tw = twitch_live([s["name"] for s in WATCHLIST if s["platform"] == "twitch"])
        except Exception as e:
            log("twitch check failed:", str(e)[:150])
            tw = {}
        for s in WATCHLIST:
            if len(active) >= MAX_STREAMS or s["name"] in active:
                continue
            if streamer_weight(s["name"]) <= 0:   # you told ClipBot to stop clipping them
                continue
            try:
                if s["platform"] == "twitch" and s["name"] in tw:
                    title, game = tw[s["name"]]
                    if TWITCH_GTA_ONLY and "grand theft auto" not in game.lower():
                        continue
                    start(s["name"], "twitch", f"https://www.twitch.tv/{s['name']}", title)
                elif s["platform"] == "youtube":
                    live = youtube_live(s["channel"])
                    if live:
                        start(s["name"], "youtube", live[0], live[1])
            except Exception as e:
                log(f"[{s['name']}] couldn't start:", str(e)[:150])
        log("live now:", ", ".join(active) or "nobody")
        time.sleep(CHECK_EVERY)

    log(f"time's up — finishing clips in progress (AI threw out {stats['rejected']} so far)")
    for w in active.values():
        w.alive = False
    time.sleep(SECONDS_AFTER + SEGMENT + 5)
    for rt in renderers:
        render_queue.put(None)
    for rt in renderers:
        rt.join(timeout=900)


if __name__ == "__main__":
    main()
