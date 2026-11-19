"""
Has the AI judge score every clip that doesn't have a score yet. Doesn't delete anything —
scores show up on the dashboard so you can sort and clear out the weak ones.
Runs in GitHub Actions: needs gh, ffmpeg, GEMINI_API_KEY.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.judge import judge, judge_text, transcribe, LAST_ERROR  # noqa: E402

# "text" (default) = read the transcript (cheap, fits the free tier); "video" = watch the video
MODE = os.environ.get("JUDGE_MODE", "text")
_whisper = []


def whisper():
    if not _whisper:
        from faster_whisper import WhisperModel
        _whisper.append(WhisperModel("base", device="cpu", compute_type="int8"))
    return _whisper[0]

TAGS = ["live-clips", "clips"]


def assets(tag):
    r = subprocess.run(["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[].name"],
                       capture_output=True, text=True)
    return set(r.stdout.split())


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY secret is missing")
    done = 0
    fails = 0
    for tag in TAGS:
        names = assets(tag)
        clips = sorted(n[:-len("_vertical.mp4")] for n in names if n.endswith("_vertical.mp4"))
        with tempfile.TemporaryDirectory() as d:
            for cid in clips:
                info = {}
                if f"{cid}.json" in names:
                    subprocess.run(["gh", "release", "download", tag, "-p", f"{cid}.json", "-D", d, "--clobber"],
                                   capture_output=True)
                    try:
                        info = json.load(open(os.path.join(d, f"{cid}.json")))
                    except (OSError, ValueError):
                        info = {}
                if info.get("ai_score") is not None:
                    continue
                r = subprocess.run(["gh", "release", "download", tag, "-p", f"{cid}_vertical.mp4", "-D", d,
                                    "--clobber"], capture_output=True, text=True)
                if r.returncode:
                    print(f"{cid}: skipped (couldn't download — deleted?)")
                    continue
                video = os.path.join(d, f"{cid}_vertical.mp4")
                streamer = info.get("streamer") or cid.rsplit("_", 2)[0]
                v = None
                if MODE == "video":
                    v = judge(video, streamer, info.get("platform", "twitch"), 40)
                if not v:
                    v = judge_text(transcribe(video, whisper()), streamer, info.get("platform", "twitch"),
                                   info.get("stream_title", ""))
                os.remove(video)
                if not v:
                    fails += 1
                    print(f"{cid}: couldn't score — {LAST_ERROR['text']}")
                    if "429" in LAST_ERROR["text"]:
                        time.sleep(60)
                    if fails >= 4:
                        sys.exit("Stopping: Gemini keeps failing (see reason above). Try again later.")
                    continue
                fails = 0
                time.sleep(4 if MODE == "text" else 12)   # stay under the free tier's per-minute limit
                info.update({"ai_score": v["score"], "ai_reason": v.get("reason", ""),
                             "ai_problems": v.get("problems", []), "streamer": streamer,
                             "ai_summary": v.get("summary", ""), "ai_tags": v.get("tags", [])})
                files = []
                if v.get("title"):
                    from edit.titles import make_description, make_tags
                    url = info.get("source_url") or f"https://www.twitch.tv/{streamer}"
                    fake = {"broadcaster_name": streamer, "title": "", "url": url}
                    info["youtube_title"] = v["title"]
                    info["youtube_description"] = make_description(fake, v["title"])
                    info["youtube_tags"] = make_tags(fake) + v.get("tags", [])[:5]
                    pp = os.path.join(d, f"{cid}_post.txt")
                    with open(pp, "w", encoding="utf-8") as f:
                        f.write(info["youtube_description"])
                    files.append(pp)
                jp = os.path.join(d, f"{cid}.json")
                with open(jp, "w") as f:
                    json.dump(info, f, indent=2)
                subprocess.run(["gh", "release", "upload", tag, jp, *files, "--clobber"], check=True,
                               capture_output=True)
                done += 1
                print(f"{cid}: {v['score']}/10 — {v.get('reason', '')}")
    print(f"Scored {done} clips")


if __name__ == "__main__":
    main()
