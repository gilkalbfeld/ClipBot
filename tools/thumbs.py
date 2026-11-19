"""
Makes a thumbnail (_thumb.jpg) for every clip in the GitHub releases that doesn't have one.
Runs in GitHub Actions (needs gh + ffmpeg). Usage: python tools/thumbs.py
"""
import json
import os
import subprocess
import tempfile

TAGS = ["live-clips", "clips"]


def make_thumb(video, out):
    """Grab a frame 2s in, crop the middle to 4:3 so the gameplay shows, shrink it."""
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-ss", "2", "-i", video, "-frames:v", "1",
         "-vf", "crop=iw:iw*3/4:0:(ih-iw*3/4)/2,scale=640:-2", "-q:v", "4", out],
        check=True,
    )


def backfill(tag):
    r = subprocess.run(["gh", "release", "view", tag, "--json", "assets"], capture_output=True, text=True)
    if r.returncode:
        return
    names = {a["name"] for a in json.loads(r.stdout)["assets"]}
    todo = [n for n in names if n.endswith("_vertical.mp4")
            and n.replace("_vertical.mp4", "_thumb.jpg") not in names]
    print(f"{tag}: {len(todo)} clips need thumbnails")
    with tempfile.TemporaryDirectory() as d:
        for n in todo:
            try:
                subprocess.run(["gh", "release", "download", tag, "-p", n, "-D", d, "--clobber"], check=True)
                thumb = os.path.join(d, n.replace("_vertical.mp4", "_thumb.jpg"))
                make_thumb(os.path.join(d, n), thumb)
                subprocess.run(["gh", "release", "upload", tag, thumb, "--clobber"], check=True)
                os.remove(os.path.join(d, n))
                print("  made", os.path.basename(thumb))
            except subprocess.CalledProcessError as e:
                print("  failed", n, e)


if __name__ == "__main__":
    for t in TAGS:
        backfill(t)
