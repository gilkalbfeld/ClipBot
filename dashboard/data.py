"""Talks to GitHub: lists clips, gets video links, marks clips posted, starts runs."""
import base64
import json
import re
from datetime import datetime, timezone

import requests

API = "https://api.github.com"
RELEASES = {"live-clips": "Live", "clips": "Scheduled"}
POSTED_FILE = "posted.json"
REVIEW_FILE = "review.json"
NUMBERS_FILE = "numbers.json"
FEEDBACK_FILE = "feedback.json"


class GitHub:
    def __init__(self, token, repo):
        self.repo = repo
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def get(self, path, **kw):
        r = self.s.get(f"{API}/repos/{self.repo}{path}", timeout=30, **kw)
        r.raise_for_status()
        return r

    # ---------- clips ----------
    def release_assets(self, tag):
        try:
            rel = self.get(f"/releases/tags/{tag}").json()
        except requests.HTTPError:
            return []
        assets, page = [], 1
        while True:
            batch = self.get(f"/releases/{rel['id']}/assets",
                             params={"per_page": 100, "page": page}).json()
            assets += batch
            if len(batch) < 100:
                return assets
            page += 1

    def clips(self):
        """One record per clip, newest first."""
        clips = {}
        for tag, source in RELEASES.items():
            for a in self.release_assets(tag):
                name = a["name"]
                m = re.match(r"(.+?)(_vertical\.mp4|_post\.txt|_thumb\.jpg|\.json)$", name)
                if not m:
                    continue
                cid, kind = m.groups()
                c = clips.setdefault(cid, {"id": cid, "source": source, "assets": []})
                c["assets"].append(a["id"])
                if kind == "_vertical.mp4":
                    c["video_asset"] = a["id"]
                    c["size_mb"] = round(a["size"] / 1e6, 1)
                    c["made_at"] = a["created_at"]
                elif kind == "_post.txt":
                    c["post_asset"] = a["id"]
                elif kind == "_thumb.jpg":
                    c["thumb_asset"] = a["id"]
                else:
                    c["json_asset"] = a["id"]
        out = [c for c in clips.values() if "video_asset" in c]
        for c in out:
            c["streamer"] = guess_streamer(c)
        out.sort(key=lambda c: c["made_at"], reverse=True)
        return out

    def asset_url(self, asset_id):
        """Short-lived direct link to a release file (works in a video player)."""
        r = self.s.get(f"{API}/repos/{self.repo}/releases/assets/{asset_id}",
                       headers={"Accept": "application/octet-stream"},
                       allow_redirects=False, timeout=30)
        return r.headers.get("Location")

    def asset_bytes(self, asset_id):
        """Downloads a release file (video, thumbnail) so the dashboard can serve it itself.
        Needed because iPad Safari won't play GitHub's direct links."""
        url = self.asset_url(asset_id)
        return requests.get(url, timeout=120).content if url else b""

    def asset_text(self, asset_id):
        url = self.asset_url(asset_id)
        return requests.get(url, timeout=30).content.decode("utf-8", "ignore") if url else ""

    # ---------- json files kept in the repo ----------
    def read_json(self, path):
        try:
            r = self.get(f"/contents/{path}").json()
            return json.loads(base64.b64decode(r["content"])), r["sha"]
        except requests.HTTPError:
            return {}, None

    def write_json(self, path, data, sha, message):
        body = {
            "message": message,
            "content": base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode()).decode(),
        }
        if sha:
            body["sha"] = sha
        r = self.s.put(f"{API}/repos/{self.repo}/contents/{path}", json=body, timeout=30)
        r.raise_for_status()

    def feedback(self):
        return self.read_json(FEEDBACK_FILE)[0]

    def set_feedback(self, clip, rating, comment):
        """rating: 1 = thumbs up, -1 = thumbs down. Saved to feedback.json for the bot to learn from."""
        data, sha = self.read_json(FEEDBACK_FILE)
        data[clip["id"]] = {
            "rating": rating,
            "comment": comment.strip(),
            "streamer": clip.get("streamer", ""),
            "source": clip.get("source", ""),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.write_json(FEEDBACK_FILE, data, sha,
                        f"Feedback {'👍' if rating > 0 else '👎'}: {clip['id']}")

    def delete_clip(self, clip):
        """Removes a clip's files for good. Counts as a 👎 so the bot learns from it."""
        data, sha = self.read_json(FEEDBACK_FILE)
        prev = data.get(clip["id"], {})
        data[clip["id"]] = {
            "rating": -1,
            "comment": (prev.get("comment") or "deleted").strip(),
            "deleted": True,
            "streamer": clip.get("streamer", ""),
            "source": clip.get("source", ""),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.write_json(FEEDBACK_FILE, data, sha, f"Deleted clip: {clip['id']}")
        for aid in clip.get("assets", []):
            self.s.delete(f"{API}/repos/{self.repo}/releases/assets/{aid}", timeout=30)

    # ---------- clip numbers (#1, #2…) that never change, so you can refer to clips by number ----------
    def number_clips(self, clips):
        nums, sha = self.read_json(NUMBERS_FILE)
        nxt = max(nums.values(), default=0) + 1
        changed = False
        for c in sorted(clips, key=lambda c: c["made_at"]):
            if c["id"] not in nums:
                nums[c["id"]] = nxt
                nxt += 1
                changed = True
        if changed:
            try:
                self.write_json(NUMBERS_FILE, nums, sha, "Number new clips")
            except requests.HTTPError:
                pass   # someone else wrote at the same time; numbers get saved next load
        for c in clips:
            c["num"] = nums.get(c["id"], 0)
        return clips

    # ---------- review: approved (-> Ready to Post) or library (keep, don't post) ----------
    def review(self):
        return self.read_json(REVIEW_FILE)[0]

    def set_review(self, clip, status):
        data, sha = self.read_json(REVIEW_FILE)
        if status is None:
            data.pop(clip["id"], None)
        else:
            data[clip["id"]] = {"status": status, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.write_json(REVIEW_FILE, data, sha, f"Review {status or 'reset'}: {clip['id']}")
        if status == "approved":   # approving counts as a 👍 for learning, unless you already rated it
            fb, fsha = self.read_json(FEEDBACK_FILE)
            if clip["id"] not in fb:
                fb[clip["id"]] = {"rating": 1, "comment": "", "approved": True,
                                  "streamer": clip.get("streamer", ""), "source": clip.get("source", ""),
                                  "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                self.write_json(FEEDBACK_FILE, fb, fsha, f"Feedback 👍 (approved): {clip['id']}")

    # ---------- posted list ----------
    def posted(self):
        return self.read_json(POSTED_FILE)

    def set_posted(self, clip_id, youtube_url="", undo=False):
        data, sha = self.posted()
        if undo:
            data.pop(clip_id, None)
        else:
            data[clip_id] = {
                "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "youtube_url": youtube_url,
            }
        body = {
            "message": f"{'Unmark' if undo else 'Mark'} posted: {clip_id}",
            "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
        }
        if sha:
            body["sha"] = sha
        r = self.s.put(f"{API}/repos/{self.repo}/contents/{POSTED_FILE}", json=body, timeout=30)
        r.raise_for_status()

    # ---------- runs ----------
    def start_workflow(self, file, inputs=None):
        r = self.s.post(f"{API}/repos/{self.repo}/actions/workflows/{file}/dispatches",
                        json={"ref": "main", "inputs": inputs or {}}, timeout=30)
        r.raise_for_status()

    def recent_runs(self, n=10):
        return self.get("/actions/runs", params={"per_page": n}).json()["workflow_runs"]


def split_post(text):
    """post.txt -> (title, description)"""
    title = text.strip().splitlines()[0] if text.strip() else ""
    return title, text.strip()


def guess_streamer(c):
    m = re.match(r"(.+)_\d{8}_\d{6}$", c["id"])   # live clips: name_YYYYmmdd_HHMMSS
    return m.group(1) if m else ""
