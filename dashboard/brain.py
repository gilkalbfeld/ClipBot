"""ClipBot chat: you talk, Gemini turns it into settings the bot uses on its next run."""
import json

import requests

MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"]

# What the chat is allowed to change, with safe limits.
TUNABLES = {
    "seconds_before": (25, 60, "seconds of lead-up kept before the funny moment (live clips)"),
    "seconds_after": (8, 25, "seconds kept after the moment (live clips)"),
    "spike_x": (1.5, 5.0, "how much busier than normal chat must be to clip (higher = pickier, fewer clips)"),
    "min_hype": (10, 80, "minimum chat hype in 10s to clip (higher = only big moments)"),
    "cooldown": (30, 300, "seconds to wait between clips from the same streamer"),
}
WEIGHTS = {
    "streamer_weight": "per-streamer priority 0.2-3 (higher = watched/ranked first), keys are twitch logins",
    "layout_weight": "layouts 'blur','fill','bars' weight 0.2-3",
    "words_weight": "caption words shown at once '2','3','4' weight 0.2-3",
}

SYSTEM = """You are ClipBot, an AI that clips funny GTA 6 moments from Twitch/YouTube streams
into YouTube Shorts for the user. The user tells you what they notice about the clips.
Reply like a helpful teammate (short, casual, 1-3 sentences) and turn their notes into changes.

You can change these settings (stay inside the limits):
{tunables}
Weight maps you can set: {weights}

Current settings: {current}
Recent clip feedback (rating 1 = 👍, -1 = 👎, with comments): {feedback}
Standing instructions already saved: {instructions}

Return ONLY JSON:
{{"reply": "what you say back",
  "set": {{"setting_name": number, ...}},
  "weights": {{"streamer_weight": {{"login": number}}, ...}},
  "instruction": "one-line summary of what the user wants, to remember (or empty)",
  "needs_code": "describe any request your settings can't do (e.g. new caption style, skip intros), or empty"}}
Only include settings you are actually changing. Be honest in "reply" about what you changed
and what needs a code change from the developer."""


def ask(api_key, message, history, current, feedback, instructions):
    prompt = SYSTEM.format(
        tunables="\n".join(f"- {k}: {lo}-{hi}, {d}" for k, (lo, hi, d) in TUNABLES.items()),
        weights=json.dumps(WEIGHTS),
        current=json.dumps(current),
        feedback=json.dumps(feedback)[:6000],
        instructions=json.dumps(instructions),
    )
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["text"]}]}
                for m in history[-10:]]
    contents.append({"role": "user", "parts": [{"text": message}]})
    body = {
        "systemInstruction": {"parts": [{"text": prompt}]},
        "contents": contents,
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    last = None
    for model in MODELS:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key}, json=body, timeout=60)
        if r.status_code == 404:
            last = r
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return clean(json.loads(text))
    last.raise_for_status()


def clean(out):
    """Keep only allowed settings, clamped to safe limits."""
    sets = {}
    for k, v in (out.get("set") or {}).items():
        if k in TUNABLES and isinstance(v, (int, float)):
            lo, hi, _ = TUNABLES[k]
            sets[k] = max(lo, min(hi, v))
    weights = {}
    for k, m in (out.get("weights") or {}).items():
        if k in WEIGHTS and isinstance(m, dict):
            weights[k] = {str(a).lower(): max(0.2, min(3.0, float(b)))
                          for a, b in m.items() if isinstance(b, (int, float))}
    return {
        "reply": out.get("reply", "Got it."),
        "set": sets,
        "weights": weights,
        "instruction": (out.get("instruction") or "").strip(),
        "needs_code": (out.get("needs_code") or "").strip(),
    }
