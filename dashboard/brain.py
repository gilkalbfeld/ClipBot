"""
"Talk to ClipBot": sends your message to Google Gemini along with what ClipBot knows
(current settings, your feedback), and gets back a reply plus setting changes.
Everything you agree on is saved to instructions.json, which the bot reads before every run.
"""
import json

import requests

MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"]

# Settings the chat is allowed to change, with safe limits
LIMITS = {
    "seconds_before": (20, 60, "seconds of lead-up kept before the funny moment (live clips)"),
    "seconds_after": (6, 30, "seconds kept after the moment (live clips)"),
    "spike_x": (1.6, 5.0, "how much busier chat must be than normal to clip (higher = pickier, fewer clips)"),
    "min_views": (0, 20000, "minimum Twitch views for scheduled 'top GTA clips'"),
    "min_ai_score": (1, 10, "AI judge watches each live clip and scores it 1-10; clips below this are thrown out"),
}
LAYOUTS = ["blur", "fill", "bars"]
CAPTION_WORDS = ["2", "3", "4"]

SYSTEM = """You are ClipBot, an AI that automatically clips funny GTA 6 moments from streamers
(Twitch + YouTube) into vertical YouTube Shorts for your owner. You are talking to your owner.
They tell you what they notice in the clips; your job is to understand it, confirm it back briefly,
and turn it into concrete changes.

How you work:
- Live watcher: records streams, reads chat, and when chat explodes (spike) it cuts a clip from
  `seconds_before` before the spike to `seconds_after` after it. `spike_x` = how big the explosion must be.
- Scheduled: grabs top GTA clips on Twitch (min_views filter) 3x a day.
- AI judge: an AI watches every live clip, scores it 1-10 for "did something big happen", throws out
  clips below `min_ai_score`, and trims the clip around the real moment.
- Layouts: "blur" (blurred background, full frame in middle), "fill" (zoomed/cropped to fill screen),
  "bars" (full frame with black bars). Captions show 2, 3 or 4 words at a time.
- Streamers watched: {streamers}.

Current settings: {settings}
Standing instructions already saved: {rules}
Feedback so far: {feedback}

Reply ONLY with JSON:
{{
  "reply": "short, casual answer to the owner (1-4 sentences). Say exactly what you're changing.",
  "new_rules": ["standing instructions to remember, written clearly; [] if none"],
  "remove_rules": ["exact text of saved rules the owner wants dropped; [] if none"],
  "settings": {{"seconds_before": number, "seconds_after": number, "spike_x": number, "min_views": number, "min_ai_score": number}}
              (only include ones that should change),
  "layouts": {{"blur": weight, "fill": weight, "bars": weight}} (0 = never use, 1 = normal, 3 = prefer; only if asked),
  "caption_words": {{"2": weight, "3": weight, "4": weight}} (only if asked),
  "streamers": {{"login": weight}} (0 = stop clipping them, 1 = normal, 3 = top priority; only if asked),
  "needs_developer": "if the request needs new code (new features, caption font/size/colour,
                      title style, editing tricks), describe it in one sentence for the developer; else empty"
}}
Only change what the owner actually asked for. Never invent feedback."""


def ask(api_key, message, history, instructions, learned, feedback, streamers):
    fb_summary = {
        "ratings": len(feedback),
        "thumbs_up": sum(1 for f in feedback.values() if f.get("rating", 0) > 0),
        "thumbs_down": sum(1 for f in feedback.values() if f.get("rating", 0) < 0),
        "recent_comments": [f"{f.get('streamer')}: {f['comment']}" for f in list(feedback.values())[-25:]
                            if f.get("comment")],
    }
    settings = {k: instructions.get("settings", {}).get(k, learned.get(k)) for k in LIMITS}
    system = SYSTEM.format(
        streamers=", ".join(streamers),
        settings=json.dumps(settings),
        rules=json.dumps(instructions.get("rules", [])),
        feedback=json.dumps(fb_summary),
    )
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["text"]}]}
                for m in history[-12:]]
    contents.append({"role": "user", "parts": [{"text": message}]})
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    last_err = ""
    for model in MODELS:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key}, json=body, timeout=60)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        last_err = f"{model}: {r.status_code} {r.text[:200]}"
    raise RuntimeError(last_err)


def apply(instructions, result):
    """Merge Gemini's answer into instructions.json (with safe limits). Returns list of change notes."""
    changes = []
    rules = instructions.setdefault("rules", [])
    for r in result.get("remove_rules", []) or []:
        if r in rules:
            rules.remove(r)
            changes.append(f"Forgot: {r}")
    for r in result.get("new_rules", []) or []:
        if r and r not in rules:
            rules.append(r)
            changes.append(f"Remembering: {r}")
    st = instructions.setdefault("settings", {})
    for k, v in (result.get("settings") or {}).items():
        if k in LIMITS and isinstance(v, (int, float)):
            lo, hi, _ = LIMITS[k]
            st[k] = max(lo, min(hi, v))
            changes.append(f"{k} → {st[k]}")
    for key, allowed in (("layouts", LAYOUTS), ("caption_words", CAPTION_WORDS)):
        for k, v in (result.get(key) or {}).items():
            if str(k) in allowed and isinstance(v, (int, float)):
                instructions.setdefault(key, {})[str(k)] = max(0, min(3, v))
                changes.append(f"{key} {k} → {v}")
    for k, v in (result.get("streamers") or {}).items():
        if isinstance(v, (int, float)):
            instructions.setdefault("streamers", {})[k.lower()] = max(0, min(3, v))
            changes.append(f"streamer {k} → {v}")
    if result.get("needs_developer"):
        instructions.setdefault("developer_requests", []).append(result["needs_developer"])
        changes.append("Flagged for the developer: " + result["needs_developer"])
    return changes
