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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.judge import judge  # noqa: E402

TAGS = ["live-clips", "clips"]


def assets(tag):
    r = subprocess.run(["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[].name"],
                       capture_output=True, text=True)
    return set(r.stdout.split())


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY secret is missing")
    done = 0
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
                subprocess.run(["gh", "release", "download", tag, "-p", f"{cid}_vertical.mp4", "-D", d,
                                "--clobber"], check=True, capture_output=True)
                video = os.path.join(d, f"{cid}_vertical.mp4")
                streamer = info.get("streamer") or cid.rsplit("_", 2)[0]
                v = judge(video, streamer, info.get("platform", "twitch"), 40)
                os.remove(video)
                if not v:
                    print(f"{cid}: couldn't score (rate limit?)")
                    continue
                info.update({"ai_score": v["score"], "ai_reason": v.get("reason", ""),
                             "ai_problems": v.get("problems", []), "streamer": streamer})
                jp = os.path.join(d, f"{cid}.json")
                with open(jp, "w") as f:
                    json.dump(info, f, indent=2)
                subprocess.run(["gh", "release", "upload", tag, jp, "--clobber"], check=True, capture_output=True)
                done += 1
                print(f"{cid}: {v['score']}/10 — {v.get('reason', '')}")
    print(f"Scored {done} clips")


if __name__ == "__main__":
    main()
