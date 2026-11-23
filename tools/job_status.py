"""Updates jobs.json when an edit / find job finishes (the dashboard shows it in the Editor + 🔔)."""
import json
import os
from datetime import datetime, timezone

job_id = os.environ.get("JOB_ID", "")
if job_id:
    try:
        jobs = json.load(open("jobs.json"))
    except (OSError, ValueError):
        jobs = {}
    try:
        msg = open("job_message.txt").read().strip()
    except OSError:
        msg = ""
    ok = os.environ.get("JOB_STATUS", "") == "success"
    j = jobs.setdefault(job_id, {})
    if os.environ.get("JOB_KIND"):
        j.setdefault("kind", os.environ["JOB_KIND"])
    j.update({"status": "done" if ok else "failed",
              "message": msg or ("Done" if ok else "Something went wrong — check the run logs"),
              "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "run_url": os.environ.get("RUN_URL", "")})
    try:
        j["new_clips"] = json.load(open("job_clips.json"))
    except (OSError, ValueError):
        pass
    with open("jobs.json", "w") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    print(job_id, j["status"], j["message"])
